"""Research evidence ingestion into the unified customer fact ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.fact_service import DirectFactEvidence, append_fact, append_source_record
from app.customer.contracts import (
    FACT_REGISTRY, SOURCE_REGISTRY, PUBLIC_RESEARCH_FACT_DESCRIPTIONS,
    PRIVATE_WEB_RESEARCH_SOURCES, PRIVATE_PROVIDER_RESEARCH_SOURCES,
)
from app.customer.models import CustomerFact, CustomerResearchTask, CustomerSourceRecord
from app.sales_automation import service
from app.sales_automation.identity import normalize_source_url
from app.sales_automation.private_research_policy import LEGACY_ENRICHMENT_POLICY, is_private_research_v2


def _data(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    return dict(value)


def research_fact_contract(*, private=False) -> dict:
    """Describe the live registry intersection supported by the research API."""
    sources = []
    rules = [("public_web", "company_page", "source"), ("agent", "research_report", "inferred")]
    if private:
        rules.extend(("public_web", entity, "source") for entity in PRIVATE_WEB_RESEARCH_SOURCES)
    for system, entity, layer in rules:
        policy = SOURCE_REGISTRY[(system, entity)]
        facts = []
        for key in sorted(policy.allowed_fact_keys):
            registration = FACT_REGISTRY.get(key)
            if registration is None or (system, entity) not in registration.allowed_sources:
                continue
            facts.append({"fact_key": key, "value_types": sorted(registration.value_types),
                          "description": PUBLIC_RESEARCH_FACT_DESCRIPTIONS.get(key, key)})
        sources.append({"source_system": system, "source_entity_type": entity,
                       "fact_layer": layer, "facts": facts})
    return {"version": "registered_research_facts_v2" if private else "registered_research_facts_v1", "sources": sources,
            "rules": ["Use only listed keys and registered value types; open every evidence URL and tie it to the current subject." if private else
                      "Use only listed keys and registered value types; source facts require official company page evidence.",
                      "Inferred facts require existing supporting_fact_ids and rule_version; never relabel an inference as source.",
                      "Unsupported claims belong in evidence gaps, not invented fact keys or unrelated citations.",
                      "Only server fact receipts may be cited. Do not attempt completion if evidence ingestion failed."]}


def append_research_facts(
    db: Session,
    task_id: int,
    facts: list[Any],
    *,
    agent_run_id: int | None = None,
    provider_evidence: bool = False,
) -> tuple[list[CustomerSourceRecord], list[CustomerFact]]:
    task = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.id == task_id,
        CustomerResearchTask.task_status == "running",
    ).with_for_update().one_or_none()
    if task is None:
        raise service.ConflictError("研究任务不存在或不在执行中")
    private = is_private_research_v2(task)
    if private or task.research_policy_version == LEGACY_ENRICHMENT_POLICY:
        from app.agent_runtime.models import AgentRun

        run = db.query(AgentRun.id).filter(
            AgentRun.id == agent_run_id,
            AgentRun.business_ref_type == "research_task",
            AgentRun.business_ref_id == str(task.id),
        ).first()
        if run is None or task.agent_run_id != agent_run_id:
            raise service.ConflictError("信息补全必须通过本任务当前 Agent Run 回写候选证据")
    source_rows: list[CustomerSourceRecord] = []
    fact_rows: list[CustomerFact] = []
    for position, raw in enumerate(facts, start=1):
        data = _data(raw)
        source_system = str(data.get("source_system") or "").strip()
        source_entity_type = str(data.get("source_entity_type") or "").strip()
        key = str(data.get("fact_key") or "")
        pair = (source_system, source_entity_type)
        source_url = data.get("source_url")
        if source_system in {"monid", "username_scan"}:
            if not private or not provider_evidence or pair not in PRIVATE_PROVIDER_RESEARCH_SOURCES:
                raise ValueError("PROVIDER_EVIDENCE_REQUIRES_BIND")
        elif source_system == "public_web" and source_entity_type != "company_page":
            if not private or source_entity_type not in PRIVATE_WEB_RESEARCH_SOURCES:
                raise ValueError("PRIVATE_RESEARCH_SOURCE_REQUIRED")
        if private and source_system == "public_web":
            if not source_url:
                raise ValueError("PRIVATE_RESEARCH_SOURCE_URL_REQUIRED")
            normalize_source_url(source_url)
        policy = SOURCE_REGISTRY.get(pair)
        registration = FACT_REGISTRY.get(key)
        if registration is None:
            raise ValueError("FACT_NOT_REGISTERED: read research context fact_contract for supported keys")
        if policy is None or key not in policy.allowed_fact_keys or (source_system, source_entity_type) not in registration.allowed_sources:
            raise ValueError("FACT_SOURCE_NOT_ALLOWED: use the source/key combination from fact_contract")
        if data.get("value_type") not in registration.value_types:
            raise ValueError("FACT_VALUE_INVALID: use the registered value type from fact_contract")
        observed_at = data.get("observed_at") or beijing_now()
        source = append_source_record(
            db,
            customer_id=task.customer_id,
            source_system=source_system,
            source_account_key=f"private-research:{task.customer_id}" if private else str(data.get("source_account_key") or "global"),
            source_entity_type=source_entity_type,
            external_record_id=str(data.get("external_record_id") or f"task-{task.id}-fact-{position}"),
            payload_schema_version="research_evidence_v1",
            payload_json=data.get("source_payload") or {
                "fact_key": data.get("fact_key"),
                "value": data.get("value"),
            },
            publisher_key=data.get("publisher_key"),
            source_family_key=data.get("source_family_key"),
            source_url=source_url,
            data_classification="personal_contact" if private else None,
            visibility_scope="customer_team",
            occurred_at=observed_at,
            captured_at=data.get("captured_at") or observed_at,
            processing_status="processed",
        )
        source_rows.append(source)
        evidence = tuple(
            DirectFactEvidence("fact", int(fact_id), {"research_task_id": task.id})
            for fact_id in data.get("supporting_fact_ids") or []
        )
        row = append_fact(
            db,
            customer_id=task.customer_id,
            subject_type="customer",
            fact_key=str(data.get("fact_key") or ""),
            value_type=str(data.get("value_type") or "string"),
            value=data.get("value"),
            fact_layer=str(data.get("fact_layer") or "source"),
            verification_status="candidate",
            confidence=Decimal(str(data.get("confidence") or 0)),
            confidence_method_version=str(data.get("confidence_method_version") or "research_evidence_v1"),
            confidence_components=data.get("confidence_components") or {
                "source_authority": format(Decimal(str(data.get("confidence") or 0)), "f"),
            },
            source_system=source_system,
            source_entity_type=source_entity_type,
            observed_at=observed_at,
            source_record_id=source.id,
            direct_evidence=evidence,
            agent_run_id=agent_run_id,
            rule_version=data.get("rule_version"),
        )
        fact_rows.append(row)
    db.flush()
    return source_rows, fact_rows


__all__ = ["append_research_facts"]
