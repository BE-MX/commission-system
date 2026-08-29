"""Read-only guards and immutable evidence for the customer-domain cutover."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.models import CORE_TABLE_NAMES, CORE_TABLES


RETIRED_CUSTOMER_BUSINESS_TABLES = (
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_companies",
    "ark_sales_contacts",
    "ark_sales_research_subjects",
    "ark_sales_public_pool_batches",
    "ark_sales_public_pool_tasks",
    "ark_sales_deal_assessments",
    "ark_sales_research_runs",
    "ark_sales_research_facts",
    "ark_inquiry_import_batches",
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_profiles",
    "ark_customer_profile_events",
    "ark_customer_actions",
)

OPTIONAL_LEGACY_TABLES = ("ark_sales_search_result_sources",)
REQUIRED_LEGACY_TABLES = tuple(
    table_name
    for table_name in RETIRED_CUSTOMER_BUSINESS_TABLES
    if table_name not in OPTIONAL_LEGACY_TABLES
)

AGENT_CONTROL_TABLES = (
    "ark_agent_profiles",
    "ark_agent_sessions",
    "ark_agent_runs",
    "ark_agent_events",
    "ark_agent_artifacts",
)
REQUIRED_CUTOVER_TABLES = REQUIRED_LEGACY_TABLES + AGENT_CONTROL_TABLES

NEW_CUSTOMER_TABLES = tuple(CORE_TABLE_NAMES)
REBUILT_CUSTOMER_WORKFLOW_TABLES = (
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_public_pool_batches",
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_actions",
)
RETIRED_ONLY_CUSTOMER_TABLES = tuple(
    table_name
    for table_name in RETIRED_CUSTOMER_BUSINESS_TABLES
    if table_name not in REBUILT_CUSTOMER_WORKFLOW_TABLES
)

REBUILT_WORKFLOW_COLUMNS = {
    "ark_sales_search_jobs": frozenset("id job_run_id profile_id name status adapter target_count criteria_json profile_snapshot policy_version profile_snapshot_hash idempotency_key ingestion_receipts result_count created_customer_count deduplicated_count researched_count qualified_count provider_usage_json cost_status cost_original cost_currency cost_usd claimed_by lease_token_hash lease_expires_at attempt_count error_code error_message started_at finished_at created_by created_at updated_at".split()),
    "ark_sales_search_results": frozenset("id job_id customer_id best_rank best_score aggregated_score_reasons result_status qualification_review_id created_at updated_at".split()),
    "ark_sales_search_result_sources": frozenset("id result_id request_key source_record_id source_provider source_url captured_at rank score score_reasons allocated_cost_usd source_fingerprint created_at".split()),
    "ark_sales_public_pool_batches": frozenset("id batch_date policy_version status quotas_json selection_snapshot result_counts idempotency_key started_at finished_at error_code error_message created_by created_at updated_at".split()),
    "ark_customer_opportunities": frozenset("id customer_id opportunity_type source source_system source_account_key source_key source_ref_type source_ref_id owner_user_id primary_contact_id expected_amount currency expected_close_date stage_probability forecast_category priority_level confidence_score urgency title summary product_requirement_json quote_ref competitor_json recommended_strategy opening_message_en follow_up_message_en evidence_fact_ids status stage_entered_at due_at latest_message_at next_step next_step_due_at close_reason_code close_reason_text linked_order_id handled_at created_by created_at updated_at".split()),
    "ark_customer_opportunity_events": frozenset("id opportunity_id customer_id event_type from_status to_status event_payload evidence_fact_ids actor_user_id occurred_at event_fingerprint created_at".split()),
    "ark_customer_actions": frozenset("id customer_id owner_user_id opportunity_id contact_id action_type thread_group channel priority reason next_action suggested_message planned_at due_at action_date status snoozed_until completed_at completed_by outcome_code dismissal_reason feedback_json source_event_ids evidence_fact_ids profile_version_id source_type agent_run_id policy_version action_fingerprint evidence_status created_at updated_at".split()),
}

REBUILT_WORKFLOW_COMMENTS = {
    "ark_sales_search_jobs": "智能获客搜索任务、冻结目标画像、执行租约、幂等回执和结果统计表；不保存客户档案副本。",
    "ark_sales_search_results": "搜索任务发现统一客户的候选成员、聚合排名、匹配评分、处理状态和资格审核引用表；每个任务与客户唯一，不保存独立候选客户主档。",
    "ark_sales_search_result_sources": "搜索候选在不同批次、适配器和公开信源中的逐次发现证据、原始排名、评分和分摊成本表；多条来源汇总到唯一搜索候选。",
    "ark_sales_public_pool_batches": "公海客户分档抽样批次和冻结策略表；批次只选择统一customer_id并创建research_tasks，不拥有客户副本。",
    "ark_customer_opportunities": "统一客户的单次销售机会当前态表；保存销售过程、预测、下一步和关闭结果，不复制客户完整档案。",
    "ark_customer_opportunity_events": "客户机会分配、阶段、联系人、金额、下一步和关闭变化的追加式事件表。",
    "ark_customer_actions": "客户经营雷达给业务员的待执行、完成、忽略和延后行动表；建议与真实销售活动严格分开。",
}

KNOWN_WRITER_CATEGORIES = (
    "local_api",
    "beijing_cloud_api",
    "schedulers",
    "agent_workers",
    "search",
    "public_pool_batch",
    "inquiry_import",
    "customer_sync",
    "profile_compiler",
    "radar",
)

ALLOWED_SUPPRESSION_REASONS = frozenset(
    {
        "do_not_contact",
        "opted_out",
        "hard_bounce",
        "invalid_address",
        "manual_block",
    }
)
ALLOWED_IDENTIFIER_TYPES = frozenset(
    {"company_id", "buyer_id", "email", "phone", "whatsapp", "domain", "social_account"}
)
ALLOWED_SCOPE_TYPES = frozenset(
    {"global", "target_profile", "product", "market", "source", "channel"}
)
ALLOWED_MAPPING_STATUSES = frozenset({"mapped", "ambiguous", "unmapped"})
REQUIRED_EXTERNAL_SUPPRESSION_SOURCE_KINDS = frozenset(
    {"okki", "alibaba", "provider"}
)
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
_CANONICAL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
WRITER_EVIDENCE_MAX_AGE = timedelta(minutes=5)
MIGRATION_CONTRACT_MAX_LIFETIME = timedelta(minutes=5)
MIGRATION_LOCK_NAME = "ark_customer_domain_cutover"
CUTOVER_EVIDENCE_ROOT = (
    Path(__file__).resolve().parents[2] / "tmp/customer-domain-cutover"
).resolve()


class CutoverGuardError(ValueError):
    """Raised whenever cutover evidence is incomplete or inconsistent."""


@dataclass(frozen=True)
class FrozenBusinessIds:
    search_job_ids: frozenset[int]
    customer_profile_ids: frozenset[int]
    customer_action_ids: frozenset[int]

    def to_dict(self) -> dict[str, list[int]]:
        return {
            "search_job_ids": sorted(self.search_job_ids),
            "customer_profile_ids": sorted(self.customer_profile_ids),
            "customer_action_ids": sorted(self.customer_action_ids),
        }


@dataclass(frozen=True)
class TableSnapshot:
    table_name: str
    exists: bool
    primary_key_ids: tuple[Any, ...]
    row_count: int | None
    content_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "exists": self.exists,
            "primary_key_ids": list(self.primary_key_ids),
            "row_count": self.row_count,
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TableSnapshot:
        return cls(
            table_name=str(value["table_name"]),
            exists=value["exists"] is True,
            primary_key_ids=tuple(value.get("primary_key_ids", ())),
            row_count=value.get("row_count"),
            content_sha256=value.get("content_sha256"),
        )


@dataclass(frozen=True)
class CutoverInventory:
    tables: tuple[TableSnapshot, ...]
    old_business_ids: FrozenBusinessIds
    inventory_sha256: str

    def table(self, table_name: str) -> TableSnapshot:
        for table in self.tables:
            if table.table_name == table_name:
                return table
        raise KeyError(table_name)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tables": [table.to_dict() for table in self.tables],
            "old_business_ids": self.old_business_ids.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "inventory_sha256": self.inventory_sha256}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CutoverInventory:
        tables = tuple(TableSnapshot.from_dict(item) for item in value["tables"])
        raw_ids = value["old_business_ids"]
        inventory = cls(
            tables=tables,
            old_business_ids=FrozenBusinessIds(
                search_job_ids=frozenset(raw_ids["search_job_ids"]),
                customer_profile_ids=frozenset(raw_ids["customer_profile_ids"]),
                customer_action_ids=frozenset(raw_ids["customer_action_ids"]),
            ),
            inventory_sha256=str(value["inventory_sha256"]),
        )
        expected = _sha256(inventory._hash_payload())
        if not hmac.compare_digest(inventory.inventory_sha256, expected):
            raise CutoverGuardError("serialized inventory SHA-256 does not match its content")
        return inventory


@dataclass(frozen=True)
class AgentHistoryClosure:
    session_ids: frozenset[int]
    run_ids: frozenset[int]
    event_ids: frozenset[int]
    artifact_ids: frozenset[int]

    def to_dict(self) -> dict[str, list[int]]:
        return {
            "session_ids": sorted(self.session_ids),
            "run_ids": sorted(self.run_ids),
            "event_ids": sorted(self.event_ids),
            "artifact_ids": sorted(self.artifact_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgentHistoryClosure:
        return cls(
            session_ids=frozenset(value["session_ids"]),
            run_ids=frozenset(value["run_ids"]),
            event_ids=frozenset(value["event_ids"]),
            artifact_ids=frozenset(value["artifact_ids"]),
        )


@dataclass(frozen=True)
class AgentPreservationSnapshot:
    tables: tuple[TableSnapshot, ...]
    snapshot_sha256: str

    def table(self, table_name: str) -> TableSnapshot:
        for table in self.tables:
            if table.table_name == table_name:
                return table
        raise KeyError(table_name)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tables": [table.to_dict() for table in self.tables],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "snapshot_sha256": self.snapshot_sha256}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgentPreservationSnapshot:
        snapshot = cls(
            tables=tuple(TableSnapshot.from_dict(item) for item in value["tables"]),
            snapshot_sha256=str(value["snapshot_sha256"]),
        )
        expected = _sha256(snapshot._hash_payload())
        if not hmac.compare_digest(snapshot.snapshot_sha256, expected):
            raise CutoverGuardError("serialized Agent snapshot SHA-256 does not match its content")
        return snapshot


@dataclass(frozen=True)
class AuthoritativeSourceEvidence:
    source_kind: str
    source_namespace: str
    source_account_key: str
    artifact_sha256: str
    source_row_count: int
    extracted_count: int
    unresolved_count: int
    approved_at: str
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_namespace": self.source_namespace,
            "source_account_key": self.source_account_key,
            "artifact_sha256": self.artifact_sha256,
            "source_row_count": self.source_row_count,
            "extracted_count": self.extracted_count,
            "unresolved_count": self.unresolved_count,
            "approved_at": self.approved_at,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True)
class SuppressionManifestEntry:
    identifier_type: str
    source_system: str
    source_account_key: str
    normalized_value_hmac: str
    hmac_key_version: str
    scope_type: str
    scope_ref_id: str | None
    reason_code: str
    reason_text: str | None
    source_ref_type: str
    source_ref_id: str | None
    status: str
    mapping_status: str
    mapped_customer_id: int | None
    mapped_contact_point_id: int | None
    suppression_fingerprint: str
    effective_at: str
    revoked_by: int | None
    revoked_at: str | None
    created_by: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier_type": self.identifier_type,
            "source_system": self.source_system,
            "source_account_key": self.source_account_key,
            "normalized_value_hmac": self.normalized_value_hmac,
            "hmac_key_version": self.hmac_key_version,
            "scope_type": self.scope_type,
            "scope_ref_id": self.scope_ref_id,
            "reason_code": self.reason_code,
            "reason_text": self.reason_text,
            "source_ref_type": self.source_ref_type,
            "source_ref_id": self.source_ref_id,
            "status": self.status,
            "mapping_status": self.mapping_status,
            "mapped_customer_id": self.mapped_customer_id,
            "mapped_contact_point_id": self.mapped_contact_point_id,
            "suppression_fingerprint": self.suppression_fingerprint,
            "effective_at": self.effective_at,
            "revoked_by": self.revoked_by,
            "revoked_at": self.revoked_at,
            "created_by": self.created_by,
        }


@dataclass(frozen=True)
class SuppressionManifest:
    key_version: str
    inventory_sha256: str
    preflight_report_sha256: str
    generated_at: str
    source_evidence: tuple[AuthoritativeSourceEvidence, ...]
    entries: tuple[SuppressionManifestEntry, ...]
    manifest_sha256: str

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "key_version": self.key_version,
            "inventory_sha256": self.inventory_sha256,
            "preflight_report_sha256": self.preflight_report_sha256,
            "source_evidence": [item.to_dict() for item in self.source_evidence],
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._hash_payload(),
            "generated_at": self.generated_at,
            "manifest_sha256": self.manifest_sha256,
        }


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CutoverGuardError("non-finite float cannot be included in cutover evidence")
        return {"$float": repr(value)}
    if isinstance(value, Decimal):
        normalized = format(value.normalize(), "f")
        return {"$decimal": "0" if normalized in {"-0", "+0"} else normalized}
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(timezone.utc)
        return {"$datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, time):
        return {"$time": value.isoformat(timespec="microseconds")}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CutoverGuardError("canonical mappings require string keys")
        return {
            key: _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise CutoverGuardError(
        f"unsupported canonical type: {type(value).__module__}.{type(value).__qualname__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize evidence identically across queries and CLI invocations."""
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _table_or_none(db: Session, table_name: str) -> Table | None:
    connection = db.connection()
    if not inspect(connection).has_table(table_name):
        return None
    return Table(
        table_name,
        MetaData(),
        autoload_with=connection,
        resolve_fks=False,
    )


def _ordered_rows(db: Session, table: Table) -> list[dict[str, Any]]:
    primary_key = tuple(table.primary_key.columns)
    if not primary_key:
        raise CutoverGuardError(f"target table {table.name} has no primary key")
    statement = select(table).order_by(*primary_key)
    return [dict(row) for row in db.execute(statement).mappings()]


def _primary_key_ids(table: Table, rows: Iterable[Mapping[str, Any]]) -> tuple[Any, ...]:
    columns = tuple(column.name for column in table.primary_key.columns)
    if len(columns) == 1:
        return tuple(row[columns[0]] for row in rows)
    return tuple(tuple(row[column] for column in columns) for row in rows)


def _snapshot_table(db: Session, table_name: str) -> TableSnapshot:
    table = _table_or_none(db, table_name)
    if table is None:
        return TableSnapshot(table_name, False, (), None, None)
    primary_key = tuple(table.primary_key.columns)
    if not primary_key:
        raise CutoverGuardError(f"target table {table.name} has no primary key")
    statement = (
        select(table)
        .order_by(*primary_key)
        .execution_options(stream_results=True, yield_per=500)
    )
    result = db.execute(statement).mappings()
    content_hasher = hashlib.sha256()
    content_hasher.update(b"[")
    primary_key_ids: list[Any] = []
    row_count = 0
    try:
        for row in result:
            if row_count:
                content_hasher.update(b",")
            content_hasher.update(canonical_json_bytes(dict(row)))
            if len(primary_key) == 1:
                primary_key_ids.append(row[primary_key[0].name])
            else:
                primary_key_ids.append(
                    tuple(row[column.name] for column in primary_key)
                )
            row_count += 1
    finally:
        result.close()
    content_hasher.update(b"]")
    return TableSnapshot(
        table_name=table_name,
        exists=True,
        primary_key_ids=tuple(primary_key_ids),
        row_count=row_count,
        content_sha256=content_hasher.hexdigest(),
    )


def _business_id_set(entry: TableSnapshot) -> frozenset[int]:
    if not entry.exists:
        return frozenset()
    values: set[int] = set()
    for value in entry.primary_key_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CutoverGuardError(
                f"{entry.table_name} must use non-negative integer primary-key IDs"
            )
        values.add(value)
    return frozenset(values)


def build_inventory(db: Session) -> CutoverInventory:
    """Inventory only the exact destructive-cutover and Agent control tables."""
    tables = tuple(
        _snapshot_table(db, table_name)
        for table_name in RETIRED_CUSTOMER_BUSINESS_TABLES + AGENT_CONTROL_TABLES
    )
    by_name = {table.table_name: table for table in tables}
    missing_required = [
        table_name
        for table_name in REQUIRED_CUTOVER_TABLES
        if not by_name[table_name].exists
    ]
    if missing_required:
        raise CutoverGuardError(
            "required cutover tables are missing: " + ", ".join(missing_required)
        )
    frozen_ids = FrozenBusinessIds(
        search_job_ids=_business_id_set(by_name["ark_sales_search_jobs"]),
        customer_profile_ids=_business_id_set(by_name["ark_customer_profiles"]),
        customer_action_ids=_business_id_set(by_name["ark_customer_actions"]),
    )
    inventory = CutoverInventory(tables, frozen_ids, "")
    return CutoverInventory(tables, frozen_ids, _sha256(inventory._hash_payload()))


def _rows_for(db: Session, table_name: str) -> list[dict[str, Any]]:
    table = _table_or_none(db, table_name)
    return [] if table is None else _ordered_rows(db, table)


def _projected_rows(
    db: Session,
    table_name: str,
    column_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    table = _table_or_none(db, table_name)
    if table is None:
        return []
    missing = [name for name in column_names if name not in table.c]
    if missing:
        raise CutoverGuardError(
            f"required columns missing from {table_name}: {', '.join(missing)}"
        )
    statement = select(*(table.c[name] for name in column_names)).order_by(table.c.id)
    return [dict(row) for row in db.execute(statement).mappings()]


def _canonical_decimal_ids(values: frozenset[int]) -> frozenset[str]:
    return frozenset(str(value) for value in values)


def _business_reference_matches(
    reference_type: Any,
    reference_id: Any,
    exact_ids: Mapping[str, frozenset[str]],
) -> bool:
    return (
        isinstance(reference_type, str)
        and isinstance(reference_id, str)
        and reference_type in exact_ids
        and reference_id in exact_ids[reference_type]
    )


def resolve_agent_history_closure(
    db: Session,
    inventory: CutoverInventory,
) -> AgentHistoryClosure:
    """Compute the approved binary-exact Session/Run fixed-point closure."""
    ids = inventory.old_business_ids
    session_refs = {
        "search_job": _canonical_decimal_ids(ids.search_job_ids),
        "customer": _canonical_decimal_ids(ids.customer_profile_ids),
    }
    business_refs = {
        "search_job": _canonical_decimal_ids(ids.search_job_ids),
        "customer_profile": _canonical_decimal_ids(ids.customer_profile_ids),
        "customer_action": _canonical_decimal_ids(ids.customer_action_ids),
    }
    sessions = _projected_rows(
        db,
        "ark_agent_sessions",
        ("id", "context_type", "context_id"),
    )
    runs = _projected_rows(
        db,
        "ark_agent_runs",
        ("id", "session_id", "business_ref_type", "business_ref_id"),
    )
    events = _projected_rows(
        db,
        "ark_agent_events",
        ("id", "run_id", "session_id"),
    )
    artifacts = _projected_rows(
        db,
        "ark_agent_artifacts",
        ("id", "run_id", "business_ref_type", "business_ref_id"),
    )

    session_ids = {
        row["id"]
        for row in sessions
        if _business_reference_matches(row.get("context_type"), row.get("context_id"), session_refs)
    }
    run_ids = {
        row["id"]
        for row in runs
        if row.get("session_id") in session_ids
        or _business_reference_matches(
            row.get("business_ref_type"), row.get("business_ref_id"), business_refs
        )
    }
    direct_artifact_ids = {
        row["id"]
        for row in artifacts
        if _business_reference_matches(
            row.get("business_ref_type"), row.get("business_ref_id"), business_refs
        )
    }
    run_ids.update(
        row["run_id"] for row in artifacts if row["id"] in direct_artifact_ids
    )

    while True:
        previous = (len(session_ids), len(run_ids))
        session_ids.update(row["session_id"] for row in runs if row["id"] in run_ids)
        run_ids.update(row["id"] for row in runs if row["session_id"] in session_ids)
        if previous == (len(session_ids), len(run_ids)):
            break

    artifact_ids = direct_artifact_ids | {
        row["id"] for row in artifacts if row["run_id"] in run_ids
    }
    event_ids = {
        row["id"]
        for row in events
        if row["run_id"] in run_ids or row["session_id"] in session_ids
    }
    return AgentHistoryClosure(
        session_ids=frozenset(session_ids),
        run_ids=frozenset(run_ids),
        event_ids=frozenset(event_ids),
        artifact_ids=frozenset(artifact_ids),
    )


def snapshot_unrelated_agent_rows(
    db: Session,
    closure: AgentHistoryClosure,
) -> AgentPreservationSnapshot:
    """Snapshot exact rows that the destructive migration must preserve."""
    excluded = {
        "ark_agent_profiles": frozenset(),
        "ark_agent_sessions": closure.session_ids,
        "ark_agent_runs": closure.run_ids,
        "ark_agent_events": closure.event_ids,
        "ark_agent_artifacts": closure.artifact_ids,
    }
    tables: list[TableSnapshot] = []
    for table_name in AGENT_CONTROL_TABLES:
        table = _table_or_none(db, table_name)
        if table is None:
            tables.append(TableSnapshot(table_name, False, (), None, None))
            continue
        rows = [row for row in _ordered_rows(db, table) if row["id"] not in excluded[table_name]]
        tables.append(
            TableSnapshot(
                table_name=table_name,
                exists=True,
                primary_key_ids=_primary_key_ids(table, rows),
                row_count=len(rows),
                content_sha256=_sha256(rows),
            )
        )
    provisional = AgentPreservationSnapshot(tuple(tables), "")
    return AgentPreservationSnapshot(tuple(tables), _sha256(provisional._hash_payload()))


def verify_unrelated_unchanged(
    before: AgentPreservationSnapshot,
    after: AgentPreservationSnapshot,
) -> bool:
    """Fail closed if any preserved Agent row ID, count, or byte-stable content changed."""
    before_by_name = {table.table_name: table for table in before.tables}
    after_by_name = {table.table_name: table for table in after.tables}
    changed = [
        table_name
        for table_name in AGENT_CONTROL_TABLES
        if before_by_name.get(table_name) != after_by_name.get(table_name)
    ]
    if changed:
        raise CutoverGuardError(
            "unrelated Agent rows changed in: " + ", ".join(changed)
        )
    if not hmac.compare_digest(before.snapshot_sha256, after.snapshot_sha256):
        raise CutoverGuardError("unrelated Agent snapshot SHA-256 changed")
    return True


def verify_agent_history_removed(db: Session, closure: AgentHistoryClosure) -> bool:
    """Assert that every exact preflight closure row is absent after reset."""
    targets = {
        "ark_agent_sessions": closure.session_ids,
        "ark_agent_runs": closure.run_ids,
        "ark_agent_events": closure.event_ids,
        "ark_agent_artifacts": closure.artifact_ids,
    }
    remaining: list[str] = []
    for table_name, expected_removed_ids in targets.items():
        if not expected_removed_ids:
            continue
        existing_ids = {
            row["id"]
            for row in _rows_for(db, table_name)
            if row["id"] in expected_removed_ids
        }
        if existing_ids:
            remaining.append(
                f"{table_name}={','.join(str(value) for value in sorted(existing_ids))}"
            )
    if remaining:
        raise CutoverGuardError("Agent closure rows remain: " + "; ".join(remaining))
    return True


def _candidate_field(candidate: Mapping[str, Any], name: str) -> Any:
    try:
        return candidate[name]
    except KeyError as exc:
        raise CutoverGuardError(f"suppression source row requires {name}") from exc


def _required_stable_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CutoverGuardError(f"{field_name} must be a non-empty stable string")
    return value


def _normalize_domain(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().rstrip(".").casefold()
    if not normalized or any(char.isspace() for char in normalized):
        raise CutoverGuardError("domain suppression value is invalid")
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise CutoverGuardError("domain suppression value is invalid") from exc


def _normalize_suppression_value(identifier_type: str, value: Any) -> str:
    if not isinstance(value, str):
        raise CutoverGuardError("suppression value must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if identifier_type == "email":
        if normalized.count("@") != 1:
            raise CutoverGuardError("email suppression value is invalid")
        local, domain = normalized.rsplit("@", 1)
        if not local:
            raise CutoverGuardError("email suppression value is invalid")
        return f"{local.casefold()}@{_normalize_domain(domain)}"
    if identifier_type == "domain":
        return _normalize_domain(normalized)
    if identifier_type in {"phone", "whatsapp"}:
        leading_plus = normalized.startswith("+")
        digits = "".join(char for char in normalized if char.isdecimal())
        disallowed = {
            char
            for char in normalized
            if not char.isdecimal() and char not in "+-(). \t"
        }
        if not digits or disallowed or "+" in normalized[1:]:
            raise CutoverGuardError("phone suppression value is invalid")
        return ("+" if leading_plus else "") + digits
    if identifier_type in {"company_id", "buyer_id", "social_account"}:
        if not normalized:
            raise CutoverGuardError("provider ID suppression value is invalid")
        return normalized
    raise CutoverGuardError(f"unsupported suppression identifier_type: {identifier_type}")


def _beijing_timestamp(value: Any, field_name: str) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CutoverGuardError(
                f"{field_name} must be an explicit Beijing datetime"
            ) from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CutoverGuardError(f"{field_name} must be an explicit Beijing datetime")
    if value.utcoffset() != timedelta(hours=8):
        raise CutoverGuardError(f"{field_name} must use Beijing UTC+08:00")
    beijing = value.astimezone(BEIJING_TIMEZONE)
    timespec = "microseconds" if beijing.microsecond else "seconds"
    return beijing.isoformat(timespec=timespec)


def _generated_at() -> str:
    value = beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=timespec)


def _source_evidence(
    source: Mapping[str, Any],
    *,
    rows: list[Mapping[str, Any]],
) -> AuthoritativeSourceEvidence:
    source_kind = _required_stable_text(source.get("source_kind"), "source_kind")
    namespace = _required_stable_text(
        source.get("source_namespace"), "source_namespace"
    )
    account = _required_stable_text(
        source.get("source_account_key"), "source_account_key"
    )
    artifact_sha256 = _required_stable_text(
        source.get("artifact_sha256"), "artifact_sha256"
    )
    if not _CANONICAL_SHA256.fullmatch(artifact_sha256):
        raise CutoverGuardError("authoritative artifact SHA-256 must be lowercase hex")
    canonical_rows = sorted(rows, key=canonical_json_bytes)
    if not hmac.compare_digest(artifact_sha256, _sha256(canonical_rows)):
        raise CutoverGuardError(
            f"authoritative artifact SHA-256 mismatch for {namespace}/{account}"
        )
    expected_unresolved = sum(
        row.get("mapping_status", "unmapped") != "mapped" for row in rows
    )
    counts = (
        source.get("source_row_count"),
        source.get("extracted_count"),
        source.get("unresolved_count"),
    )
    if counts != (len(rows), len(rows), expected_unresolved):
        raise CutoverGuardError(
            f"source row reconciliation failed for {namespace}/{account}"
        )
    approved_at = _beijing_timestamp(source.get("approved_at"), "source approved_at")
    payload = {
        "source_kind": source_kind,
        "source_namespace": namespace,
        "source_account_key": account,
        "artifact_sha256": artifact_sha256,
        "source_row_count": len(rows),
        "extracted_count": len(rows),
        "unresolved_count": expected_unresolved,
        "approved_at": approved_at,
    }
    return AuthoritativeSourceEvidence(**payload, evidence_sha256=_sha256(payload))


def _database_suppression_source(
    db: Session,
    approved_at: Any,
) -> tuple[AuthoritativeSourceEvidence, list[dict[str, Any]]]:
    table = _table_or_none(db, "ark_sales_contacts")
    required_columns = {
        "id",
        "email_normalized",
        "email_status",
        "source_provider",
        "captured_at",
    }
    if table is None or not required_columns <= set(table.c.keys()):
        raise CutoverGuardError(
            "ark_sales_contacts lacks authoritative suppression source fields"
        )
    statement = (
        select(*(table.c[name] for name in sorted(required_columns)))
        .where(table.c.email_status == "invalid")
        .order_by(table.c.id)
        .execution_options(stream_results=True, yield_per=500)
    )
    raw_rows = [dict(row) for row in db.execute(statement).mappings()]
    candidates = []
    for row in raw_rows:
        if not row["email_normalized"] or row["captured_at"] is None:
            raise CutoverGuardError(
                "invalid legacy contact lacks normalized email or captured_at"
            )
        effective_at = row["captured_at"]
        if effective_at.tzinfo is None:
            effective_at = effective_at.replace(tzinfo=BEIJING_TIMEZONE)
        candidates.append(
            {
                "identifier_type": "email",
                "value": row["email_normalized"],
                "source_system": "ark",
                "source_account_key": "commission_db",
                "scope_type": "global",
                "scope_ref_id": None,
                "reason_code": "invalid_address",
                "reason_text": None,
                "source_ref_type": "legacy_export",
                "source_ref_id": str(row["id"]),
                "status": "active",
                "mapping_status": "unmapped",
                "mapped_customer_id": None,
                "mapped_contact_point_id": None,
                "effective_at": effective_at,
                "revoked_by": None,
                "revoked_at": None,
                "created_by": None,
            }
        )
    source = {
        "source_kind": "ark_database",
        "source_namespace": "ark",
        "source_account_key": "commission_db",
        "artifact_sha256": _sha256(sorted(raw_rows, key=canonical_json_bytes)),
        "source_row_count": len(raw_rows),
        "extracted_count": len(raw_rows),
        "unresolved_count": len(raw_rows),
        "approved_at": approved_at,
    }
    return _source_evidence(source, rows=raw_rows), candidates


def _suppression_entry(
    candidate: Mapping[str, Any],
    key: bytes,
    key_version: str,
) -> SuppressionManifestEntry:
    identifier_type = _required_stable_text(
        _candidate_field(candidate, "identifier_type"), "identifier_type"
    )
    if identifier_type not in ALLOWED_IDENTIFIER_TYPES:
        raise CutoverGuardError(f"unsupported identifier_type: {identifier_type}")
    source_system = _required_stable_text(
        _candidate_field(candidate, "source_system"), "source_system"
    )
    source_account_key = _required_stable_text(
        _candidate_field(candidate, "source_account_key"), "source_account_key"
    )
    scope_type = _required_stable_text(
        _candidate_field(candidate, "scope_type"), "scope_type"
    )
    if scope_type not in ALLOWED_SCOPE_TYPES:
        raise CutoverGuardError(f"unsupported scope_type: {scope_type}")
    scope_ref_id = candidate.get("scope_ref_id")
    if (scope_type == "global") != (scope_ref_id is None):
        raise CutoverGuardError("global scope requires null scope_ref_id and other scopes require it")
    reason_code = _required_stable_text(
        _candidate_field(candidate, "reason_code"), "reason_code"
    )
    if reason_code not in ALLOWED_SUPPRESSION_REASONS:
        raise CutoverGuardError(f"unsupported suppression reason: {reason_code}")
    mapping_status = _required_stable_text(
        _candidate_field(candidate, "mapping_status"), "mapping_status"
    )
    if mapping_status not in ALLOWED_MAPPING_STATUSES:
        raise CutoverGuardError(f"unsupported mapping_status: {mapping_status}")
    status = _required_stable_text(_candidate_field(candidate, "status"), "status")
    if status not in {"active", "revoked"}:
        raise CutoverGuardError(f"unsupported suppression status: {status}")
    normalized_value = _normalize_suppression_value(
        identifier_type, _candidate_field(candidate, "value")
    )
    normalized_value_hmac = hmac.new(
        key, normalized_value.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    effective_at = _beijing_timestamp(
        _candidate_field(candidate, "effective_at"), "effective_at"
    )
    revoked_at_value = candidate.get("revoked_at")
    revoked_at = (
        _beijing_timestamp(revoked_at_value, "revoked_at")
        if revoked_at_value is not None
        else None
    )
    if status == "revoked" and revoked_at is None:
        raise CutoverGuardError("revoked suppression requires revoked_at")
    source_ref_type = _required_stable_text(
        _candidate_field(candidate, "source_ref_type"), "source_ref_type"
    )
    source_ref_id = candidate.get("source_ref_id")
    fingerprint_payload = {
        "normalized_value_hmac": normalized_value_hmac,
        "scope_type": scope_type,
        "scope_ref_id": scope_ref_id,
        "reason_code": reason_code,
        "source_system": source_system,
        "source_account_key": source_account_key,
        "source_ref_type": source_ref_type,
        "source_ref_id": source_ref_id,
        "effective_at": effective_at,
    }
    reason_text = candidate.get("reason_text")
    if reason_text is not None and not isinstance(reason_text, str):
        raise CutoverGuardError("reason_text must be a string or null")
    raw_value = unicodedata.normalize("NFKC", str(candidate["value"])).strip()
    for metadata in (
        reason_text,
        source_ref_id,
        source_ref_type,
        source_system,
        source_account_key,
        scope_ref_id,
    ):
        if metadata and (
            raw_value.casefold() in str(metadata).casefold()
            or normalized_value.casefold() in str(metadata).casefold()
        ):
            raise CutoverGuardError("suppression metadata must not contain raw identifier")
    return SuppressionManifestEntry(
        identifier_type=identifier_type,
        source_system=source_system,
        source_account_key=source_account_key,
        normalized_value_hmac=normalized_value_hmac,
        hmac_key_version=key_version,
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        reason_code=reason_code,
        reason_text=reason_text,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        status=status,
        mapping_status=mapping_status,
        mapped_customer_id=candidate.get("mapped_customer_id"),
        mapped_contact_point_id=candidate.get("mapped_contact_point_id"),
        suppression_fingerprint=_sha256(fingerprint_payload),
        effective_at=effective_at,
        revoked_by=candidate.get("revoked_by"),
        revoked_at=revoked_at,
        created_by=candidate.get("created_by"),
    )


def build_suppression_manifest(
    db: Session,
    authoritative_source_manifest: Mapping[str, Any],
    hmac_key: bytes | str,
    key_version: str,
    *,
    inventory_sha256: str,
    preflight_report_sha256: str,
) -> SuppressionManifest:
    """Build an inventory-bound replay manifest from every authoritative source."""
    key = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
    if not isinstance(key, bytes) or len(key) < 32:
        raise CutoverGuardError("suppression HMAC key must contain at least 32 bytes")
    key_version = _required_stable_text(key_version, "key_version")
    for digest, field_name in (
        (inventory_sha256, "inventory_sha256"),
        (preflight_report_sha256, "preflight_report_sha256"),
    ):
        if not isinstance(digest, str) or not _CANONICAL_SHA256.fullmatch(digest):
            raise CutoverGuardError(f"{field_name} must be lowercase SHA-256")
    sources = authoritative_source_manifest.get("sources")
    if not isinstance(sources, list):
        raise CutoverGuardError("authoritative source manifest requires sources list")
    actual_kinds = {source.get("source_kind") for source in sources if isinstance(source, Mapping)}
    missing_kinds = sorted(REQUIRED_EXTERNAL_SUPPRESSION_SOURCE_KINDS - actual_kinds)
    if missing_kinds:
        raise CutoverGuardError(
            "missing authoritative source kinds: " + ", ".join(missing_kinds)
        )
    unsupported_kinds = sorted(
        kind
        for kind in actual_kinds - REQUIRED_EXTERNAL_SUPPRESSION_SOURCE_KINDS
        if isinstance(kind, str)
    )
    if unsupported_kinds:
        raise CutoverGuardError(
            "unsupported authoritative source kinds: " + ", ".join(unsupported_kinds)
        )
    evidence: list[AuthoritativeSourceEvidence] = []
    candidates: list[Mapping[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for source in sources:
        if not isinstance(source, Mapping) or not isinstance(source.get("rows"), list):
            raise CutoverGuardError("authoritative source requires explicit rows list")
        rows = source["rows"]
        if any(not isinstance(row, Mapping) for row in rows):
            raise CutoverGuardError("authoritative source rows must be objects")
        item = _source_evidence(source, rows=rows)
        identity = (item.source_namespace, item.source_account_key)
        if identity in identities:
            raise CutoverGuardError(f"duplicate authoritative source: {identity}")
        identities.add(identity)
        for row in rows:
            if (
                row.get("source_system") != item.source_namespace
                or row.get("source_account_key") != item.source_account_key
            ):
                raise CutoverGuardError("source row namespace/account does not match evidence")
        evidence.append(item)
        candidates.extend(rows)
    database_evidence, database_candidates = _database_suppression_source(
        db, authoritative_source_manifest.get("database_approved_at")
    )
    evidence.append(database_evidence)
    candidates.extend(database_candidates)
    entries = [_suppression_entry(row, key, key_version) for row in candidates]
    entries.sort(key=lambda entry: canonical_json_bytes(entry.to_dict()))
    evidence.sort(key=lambda item: (item.source_kind, item.source_namespace, item.source_account_key))
    provisional = SuppressionManifest(
        key_version,
        inventory_sha256,
        preflight_report_sha256,
        _generated_at(),
        tuple(evidence),
        tuple(entries),
        "",
    )
    return SuppressionManifest(
        key_version=key_version,
        inventory_sha256=inventory_sha256,
        preflight_report_sha256=preflight_report_sha256,
        generated_at=provisional.generated_at,
        source_evidence=tuple(evidence),
        entries=tuple(entries),
        manifest_sha256=_sha256(provisional._hash_payload()),
    )


def _parse_writer_timestamp(value: Any, field_name: str = "writer checked_at") -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CutoverGuardError(f"{field_name} must be an ISO Beijing datetime") from exc
    _beijing_timestamp(value, field_name)
    return value.astimezone(BEIJING_TIMEZONE)


def _verify_evidence(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise CutoverGuardError(f"{label} requires structured evidence")
    method = value.get("method")
    artifact = value.get("artifact_sha256")
    detail = value.get("detail")
    if (
        not isinstance(method, str)
        or len(method.strip()) < 8
        or not isinstance(artifact, str)
        or not _CANONICAL_SHA256.fullmatch(artifact)
        or not isinstance(detail, str)
        or len(detail.strip()) < 20
    ):
        raise CutoverGuardError(f"{label} requires nontrivial structured evidence")


def _verify_evidence_time(value: Any, now: datetime, label: str) -> None:
    checked_at = _parse_writer_timestamp(value, f"{label} checked_at")
    if checked_at > now:
        raise CutoverGuardError(f"{label} evidence is future-dated")
    if now - checked_at > WRITER_EVIDENCE_MAX_AGE:
        raise CutoverGuardError(f"{label} evidence is stale")


def verify_ready(
    inventory: CutoverInventory,
    stopped_writer_manifest: Mapping[str, Any],
    expected_inventory_sha256: str,
    preflight_report_sha256: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Validate exact approved instances and fresh, inventory-bound stop evidence."""
    actual_content_hash = _sha256(inventory._hash_payload())
    if not hmac.compare_digest(inventory.inventory_sha256, actual_content_hash):
        raise CutoverGuardError("inventory content does not match its embedded SHA-256")
    if not isinstance(expected_inventory_sha256, str) or not _CANONICAL_SHA256.fullmatch(
        expected_inventory_sha256
    ):
        raise CutoverGuardError("expected inventory SHA-256 must be 64 lowercase hex characters")
    if not hmac.compare_digest(inventory.inventory_sha256, expected_inventory_sha256):
        raise CutoverGuardError("inventory SHA-256 does not match the approved inventory")
    if not isinstance(preflight_report_sha256, str) or not _CANONICAL_SHA256.fullmatch(
        preflight_report_sha256
    ):
        raise CutoverGuardError("preflight report SHA-256 must be lowercase hex")
    now = now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    _beijing_timestamp(now, "readiness now")

    approved = stopped_writer_manifest.get("instance_inventory")
    writers = stopped_writer_manifest.get("writers")
    if not isinstance(approved, Mapping) or not isinstance(writers, list):
        raise CutoverGuardError("stopped-writer manifest requires a writers list")
    approved_instances = approved.get("instances")
    if not isinstance(approved_instances, list):
        raise CutoverGuardError("approved instance inventory requires instances list")
    approved_payload = {
        key: value for key, value in approved.items() if key != "instance_inventory_sha256"
    }
    if not hmac.compare_digest(
        str(approved.get("instance_inventory_sha256")), _sha256(approved_payload)
    ):
        raise CutoverGuardError("approved instance inventory SHA-256 mismatch")
    if (
        approved.get("inventory_sha256") != inventory.inventory_sha256
        or approved.get("preflight_report_sha256") != preflight_report_sha256
    ):
        raise CutoverGuardError("approved instance inventory has wrong preflight binding")
    _required_stable_text(approved.get("approved_by"), "instance inventory approved_by")
    _verify_evidence(
        approved.get("approval_evidence"), "approved instance inventory"
    )
    _parse_writer_timestamp(approved.get("approved_at"), "instance inventory approved_at")

    expected_instances: set[tuple[str, str]] = set()
    for item in approved_instances:
        if not isinstance(item, Mapping):
            raise CutoverGuardError("approved instance inventory entries must be objects")
        identity = (
            _required_stable_text(item.get("category"), "writer category"),
            _required_stable_text(item.get("instance_id"), "writer instance_id"),
        )
        if identity in expected_instances:
            raise CutoverGuardError(f"duplicate approved writer instance: {identity}")
        expected_instances.add(identity)
    approved_categories = {category for category, _ in expected_instances}
    if approved_categories != set(KNOWN_WRITER_CATEGORIES):
        raise CutoverGuardError("approved instance inventory does not cover exact writer categories")

    actual_instances: set[tuple[str, str]] = set()
    running: list[str] = []
    for writer in writers:
        if not isinstance(writer, Mapping):
            raise CutoverGuardError("each stopped-writer entry must be an object")
        category = _required_stable_text(writer.get("category"), "writer category")
        instance_id = _required_stable_text(writer.get("instance_id"), "writer instance_id")
        identity = (category, instance_id)
        if identity in actual_instances:
            raise CutoverGuardError(f"duplicate writer instance: {category}/{instance_id}")
        actual_instances.add(identity)
        if (
            writer.get("inventory_sha256") != inventory.inventory_sha256
            or writer.get("preflight_report_sha256") != preflight_report_sha256
        ):
            raise CutoverGuardError(f"writer {category}/{instance_id} has wrong preflight binding")
        _verify_evidence_time(writer.get("checked_at"), now, f"writer {category}/{instance_id}")
        _verify_evidence(writer.get("evidence"), f"writer {category}/{instance_id}")
        if writer.get("stopped") is not True:
            running.append(f"{category}/{instance_id}")
    if actual_instances != expected_instances:
        raise CutoverGuardError("writer evidence does not equal approved instance inventory")
    if running:
        raise CutoverGuardError("writer instances still running: " + ", ".join(running))

    transactions = stopped_writer_manifest.get("active_transactions")
    if not isinstance(transactions, Mapping):
        raise CutoverGuardError("active transaction evidence is required")
    if (
        transactions.get("inventory_sha256") != inventory.inventory_sha256
        or transactions.get("preflight_report_sha256") != preflight_report_sha256
    ):
        raise CutoverGuardError("active transaction evidence has wrong preflight binding")
    _verify_evidence_time(transactions.get("checked_at"), now, "active transaction")
    _verify_evidence(transactions.get("evidence"), "active transaction")
    if transactions.get("count") != 0:
        raise CutoverGuardError("relevant active transactions must be zero")
    return True


def _acquire_mysql_cutover_lock(db: Session) -> bool:
    if db.get_bind().dialect.name != "mysql":
        raise CutoverGuardError(
            "customer cutover migration lock requires a MySQL Alembic bind"
        )
    result = db.execute(
        text("SELECT GET_LOCK(:lock_name, 0)"), {"lock_name": MIGRATION_LOCK_NAME}
    ).scalar_one()
    return result == 1


def migration_preflight(
    db: Session,
    evidence_contract: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    lock_acquirer: Callable[[Session], bool] | None = None,
) -> CutoverInventory:
    """Migration-facing fail-closed guard; the caller retains this locked bind for DDL."""
    if not isinstance(evidence_contract, Mapping):
        raise CutoverGuardError("migration evidence contract is required")
    if evidence_contract.get("approved") is not True:
        raise CutoverGuardError("migration evidence contract is not approved")
    if evidence_contract.get("evidence_root") != str(CUTOVER_EVIDENCE_ROOT):
        raise CutoverGuardError("migration evidence contract is outside the fixed evidence root")
    contract_payload = {
        key: value for key, value in evidence_contract.items() if key != "contract_sha256"
    }
    if not hmac.compare_digest(
        str(evidence_contract.get("contract_sha256")), _sha256(contract_payload)
    ):
        raise CutoverGuardError("migration evidence contract SHA-256 mismatch")
    _required_stable_text(evidence_contract.get("nonce"), "migration nonce")
    for field_name in (
        "inventory_sha256",
        "preflight_report_sha256",
        "suppression_manifest_sha256",
        "writer_manifest_sha256",
        "approved_marker_sha256",
    ):
        digest = evidence_contract.get(field_name)
        if not isinstance(digest, str) or not _CANONICAL_SHA256.fullmatch(digest):
            raise CutoverGuardError(f"migration {field_name} must be lowercase SHA-256")
    now = now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    _beijing_timestamp(now, "migration preflight now")
    issued_at = _parse_writer_timestamp(
        evidence_contract.get("issued_at"), "migration contract issued_at"
    )
    if issued_at > now or now - issued_at > MIGRATION_CONTRACT_MAX_LIFETIME:
        raise CutoverGuardError("migration evidence contract issued_at is stale or future")
    expires_at = _parse_writer_timestamp(
        evidence_contract.get("expires_at"), "migration contract expires_at"
    )
    if expires_at <= now:
        raise CutoverGuardError("migration evidence contract is expired")
    if expires_at - now > MIGRATION_CONTRACT_MAX_LIFETIME:
        raise CutoverGuardError("migration evidence contract lifetime exceeds five minutes")
    acquire = lock_acquirer or _acquire_mysql_cutover_lock
    if acquire(db) is not True:
        raise CutoverGuardError("customer cutover advisory lock is unavailable")
    live_inventory = build_inventory(db)
    if not hmac.compare_digest(
        live_inventory.inventory_sha256, str(evidence_contract["inventory_sha256"])
    ):
        raise CutoverGuardError("live inventory changed after cutover approval")
    return live_inventory


def verify_expected_customer_table_state(db: Session) -> bool:
    """Verify approved table names plus exact model/design schema signatures."""
    connection = db.connection()
    inspector = inspect(connection)
    missing = [
        table_name
        for table_name in NEW_CUSTOMER_TABLES + REBUILT_CUSTOMER_WORKFLOW_TABLES
        if not inspector.has_table(table_name)
    ]
    if missing:
        raise CutoverGuardError("expected customer tables are missing: " + ", ".join(missing))
    remaining = [
        table_name
        for table_name in RETIRED_ONLY_CUSTOMER_TABLES
        if inspector.has_table(table_name)
    ]
    if remaining:
        raise CutoverGuardError(
            "retired-only tables still exist: " + ", ".join(remaining)
        )
    for table_name in NEW_CUSTOMER_TABLES + REBUILT_CUSTOMER_WORKFLOW_TABLES:
        reflected_columns = inspector.get_columns(table_name)
        actual_names = {column["name"] for column in reflected_columns}
        if table_name in CORE_TABLES:
            model_table = CORE_TABLES[table_name]
            expected_names = set(model_table.c.keys())
        else:
            model_table = None
            expected_names = set(REBUILT_WORKFLOW_COLUMNS[table_name])
        if actual_names != expected_names:
            missing_columns = sorted(expected_names - actual_names)
            extra_columns = sorted(actual_names - expected_names)
            raise CutoverGuardError(
                f"schema signature mismatch for {table_name}: "
                f"missing={missing_columns}, extra={extra_columns}"
            )
        if model_table is not None:
            actual_by_name = {column["name"]: column for column in reflected_columns}
            for expected_column in model_table.c:
                if expected_column.computed is not None and not actual_by_name[
                    expected_column.name
                ].get("computed"):
                    raise CutoverGuardError(
                        f"generated column missing from {table_name}.{expected_column.name}"
                    )
            expected_checks = {
                constraint.name
                for constraint in model_table.constraints
                if constraint.__class__.__name__ == "CheckConstraint"
            }
            actual_checks = {
                constraint.get("name")
                for constraint in inspector.get_check_constraints(table_name)
            }
            if not expected_checks <= actual_checks:
                raise CutoverGuardError(
                    f"check constraints missing from {table_name}: "
                    + ", ".join(sorted(expected_checks - actual_checks))
                )
        if connection.dialect.name == "mysql":
            expected_comment = (
                model_table.comment
                if model_table is not None
                else REBUILT_WORKFLOW_COMMENTS[table_name]
            )
            actual_comment = inspector.get_table_comment(table_name).get("text")
            if actual_comment != expected_comment:
                raise CutoverGuardError(f"table comment mismatch for {table_name}")
            if model_table is not None:
                actual_by_name = {
                    column["name"]: column for column in reflected_columns
                }
                mismatched_comments = [
                    column.name
                    for column in model_table.c
                    if actual_by_name[column.name].get("comment") != column.comment
                ]
                if mismatched_comments:
                    raise CutoverGuardError(
                        f"column comments mismatch for {table_name}: "
                        + ", ".join(mismatched_comments)
                    )
            elif any(not column.get("comment") for column in reflected_columns):
                raise CutoverGuardError(f"column comments are incomplete for {table_name}")
    return True


def expected_customer_schema_sha256() -> str:
    """Return the immutable schema contract hash shared by reset and verification."""
    core = {}
    for table_name in NEW_CUSTOMER_TABLES:
        table = CORE_TABLES[table_name]
        core[table_name] = {
            "columns": list(table.c.keys()),
            "computed_columns": sorted(
                column.name for column in table.c if column.computed is not None
            ),
            "check_constraints": sorted(
                constraint.name
                for constraint in table.constraints
                if constraint.__class__.__name__ == "CheckConstraint"
            ),
            "table_comment": table.comment,
        }
    rebuilt = {
        table_name: {
            "columns": sorted(REBUILT_WORKFLOW_COLUMNS[table_name]),
            "table_comment": REBUILT_WORKFLOW_COMMENTS[table_name],
        }
        for table_name in REBUILT_CUSTOMER_WORKFLOW_TABLES
    }
    return _sha256({"schema_version": 1, "core": core, "rebuilt": rebuilt})


def verify_frozen_business_ids_removed(
    db: Session, inventory: CutoverInventory
) -> bool:
    """Ensure the reset did not retain any approved old J/P/A business row."""
    frozen = (
        ("ark_sales_search_jobs", inventory.old_business_ids.search_job_ids),
        ("ark_customer_profiles", inventory.old_business_ids.customer_profile_ids),
        ("ark_customer_actions", inventory.old_business_ids.customer_action_ids),
    )
    remaining: list[str] = []
    for table_name, ids in frozen:
        table = _table_or_none(db, table_name)
        if table is None:
            if table_name in REBUILT_CUSTOMER_WORKFLOW_TABLES:
                remaining.append(f"{table_name}:missing")
            continue
        if "id" not in table.c:
            remaining.append(f"{table_name}:missing-id")
            continue
        found = db.execute(select(table.c.id).where(table.c.id.in_(ids))).scalars().all()
        remaining.extend(f"{table_name}:{value}" for value in found)
    if remaining:
        raise CutoverGuardError("frozen retired business IDs remain: " + ", ".join(remaining))
    return True
