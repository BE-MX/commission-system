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
from itertools import islice
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive


CORE_TABLE_NAMES = (
    "ark_customer_accounts",
    "ark_customer_names",
    "ark_customer_external_identities",
    "ark_customer_relationships",
    "ark_customer_assignments",
    "ark_customer_contacts",
    "ark_customer_contact_points",
    "ark_customer_contact_relationships",
    "ark_customer_source_records",
    "ark_customer_facts",
    "ark_customer_events",
    "ark_customer_annotations",
    "ark_customer_qualification_reviews",
    "ark_customer_profile_versions",
    "ark_customer_agent_contexts",
    "ark_customer_conversations",
    "ark_customer_messages",
    "ark_customer_conversation_analyses",
    "ark_customer_orders",
    "ark_customer_order_items",
    "ark_customer_research_tasks",
    "ark_customer_sync_cursors",
    "ark_customer_fact_evidence_links",
    "ark_customer_fact_conflicts",
    "ark_customer_list_projections",
    "ark_customer_change_proposals",
    "ark_customer_object_ownerships",
    "ark_customer_agent_run_scopes",
    "ark_customer_suppression_registry",
    "ark_customer_resolution_keys",
    "ark_customer_target_matches",
    "ark_customer_acquisition_attributions",
)


def _runtime_core_tables() -> Mapping[str, Table]:
    from app.customer.models import CORE_TABLES

    return CORE_TABLES


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
AGENT_ID_QUERY_CHUNK_SIZE = 200
TARGET_PROFILE_EXISTING_COLUMNS = (
    "id",
    "profile_key",
    "company_name",
    "company_website",
    "products",
    "advantages",
    "target_countries",
    "target_industries",
    "target_roles",
    "exclusions",
    "default_language",
    "status",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
    "deleted_at",
)
TARGET_PROFILE_POLICY_SECTIONS = (
    "thresholds",
    "weights",
    "research_rules",
    "claim_rules",
)
TARGET_PROFILE_THRESHOLD_FIELDS = frozenset(
    {
        "research_threshold",
        "qualification_threshold",
        "tier_1_min_score",
        "tier_2_min_score",
        "tier_3_min_score",
    }
)
TARGET_PROFILE_RESEARCH_RULE_FIELDS = frozenset(
    {
        "minimum_independent_sources",
        "evidence_freshness_days",
        "auto_research_enabled",
        "gate_required",
    }
)
TARGET_PROFILE_CLAIM_RULE_FIELDS = frozenset(
    {
        "cooldown_days",
        "requires_qualification",
        "per_user_quota",
        "per_team_quota",
        "block_identity_conflict",
        "block_do_not_contact",
    }
)
TARGET_PROFILE_POLICY_WEIGHT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TARGET_PROFILE_POLICY_PLACEHOLDER_RE = re.compile(
    r"(?:todo|tbd|placeholder|unconfigured|legacy)", re.IGNORECASE
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
    "ark_customer_actions": frozenset("id customer_id owner_user_id opportunity_id contact_id action_type thread_group channel priority reason next_action suggested_message planned_at due_at action_date status snoozed_until completed_at completed_by outcome_code dismissal_reason feedback_json source_event_ids evidence_fact_ids profile_version_id source_type agent_run_id policy_version action_fingerprint evidence_status generated_at created_at updated_at".split()),
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
MYSQL_WRITER_DANGEROUS_PRIVILEGES = frozenset(
    {
        "ALL PRIVILEGES",
        "ALTER",
        "ALTER ROUTINE",
        "CREATE",
        "CREATE ROUTINE",
        "CREATE ROLE",
        "CREATE TABLESPACE",
        "CREATE TEMPORARY TABLES",
        "CREATE USER",
        "CREATE VIEW",
        "DELETE",
        "DROP",
        "DROP ROLE",
        "EVENT",
        "EXECUTE",
        "FILE",
        "GRANT OPTION",
        "INDEX",
        "INSERT",
        "LOCK TABLES",
        "PROXY",
        "REFERENCES",
        "RELOAD",
        "SHUTDOWN",
        "SUPER",
        "ROLE",
        "ROLE ADMIN",
        "SET USER ID",
        "SYSTEM USER",
        "SYSTEM VARIABLES ADMIN",
        "TRIGGER",
        "UPDATE",
    }
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
_CUTOVER_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_RAW_EMAIL = re.compile(r"(?i)(?<![\w.-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
_RAW_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d ().-]{7,}\d)(?!\d)")
CUTOVER_EVIDENCE_MAX_AGE = timedelta(minutes=5)
MIGRATION_CONTRACT_MAX_LIFETIME = timedelta(minutes=5)
MIGRATION_LOCK_NAME = "ark_customer_domain_cutover"
MIGRATION_DDL_PROOF_BINDING_FIELDS = (
    "inventory_sha256",
    "preflight_report_sha256",
    "suppression_manifest_sha256",
    "writer_manifest_sha256",
    "writer_privilege_revocation_artifact_sha256",
    "approved_marker_sha256",
    "maintenance_fence_artifact_sha256",
    "instance_inventory_artifact_sha256",
    "physical_schema_contract_sha256",
    "target_profile_physical_contract_sha256",
    "target_profile_policy_backfill_sha256",
    "nonce",
    "contract_path",
    "ddl_proof_path",
    "migration_revision",
)
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
    artifact_path: str | None
    artifact_sha256: str
    source_row_count: int
    extracted_count: int
    unresolved_count: int
    exported_at: str
    approved_at: str
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_namespace": self.source_namespace,
            "source_account_key": self.source_account_key,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "source_row_count": self.source_row_count,
            "extracted_count": self.extracted_count,
            "unresolved_count": self.unresolved_count,
            "exported_at": self.exported_at,
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


def _agent_artifact_content_sha256(content: Any, evidence: Any) -> str:
    """Match agent_runtime.event_service.content_hash without importing runtime models."""
    payload = json.dumps(
        {"content": content, "evidence": evidence},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _projected_rows(
    db: Session,
    table_name: str,
    column_names: tuple[str, ...],
) -> Iterable[dict[str, Any]]:
    table = _table_or_none(db, table_name)
    if table is None:
        return
    missing = [name for name in column_names if name not in table.c]
    if missing:
        raise CutoverGuardError(
            f"required columns missing from {table_name}: {', '.join(missing)}"
        )
    statement = (
        select(*(table.c[name] for name in column_names))
        .order_by(table.c.id)
        .execution_options(stream_results=True, yield_per=500)
    )
    result = db.execute(statement).mappings()
    try:
        for row in result:
            yield dict(row)
    finally:
        result.close()


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
    session_ids = {
        row["id"]
        for row in _projected_rows(
            db,
            "ark_agent_sessions",
            ("id", "context_type", "context_id"),
        )
        if _business_reference_matches(row.get("context_type"), row.get("context_id"), session_refs)
    }
    run_ids = {
        row["id"]
        for row in _projected_rows(
            db,
            "ark_agent_runs",
            ("id", "session_id", "business_ref_type", "business_ref_id"),
        )
        if row.get("session_id") in session_ids
        or _business_reference_matches(
            row.get("business_ref_type"), row.get("business_ref_id"), business_refs
        )
    }
    direct_artifact_ids: set[Any] = set()
    for row in _projected_rows(
        db,
        "ark_agent_artifacts",
        ("id", "run_id", "business_ref_type", "business_ref_id"),
    ):
        if _business_reference_matches(
            row.get("business_ref_type"), row.get("business_ref_id"), business_refs
        ):
            direct_artifact_ids.add(row["id"])
            run_ids.add(row["run_id"])

    while True:
        previous = (len(session_ids), len(run_ids))
        for row in _projected_rows(
            db,
            "ark_agent_runs",
            ("id", "session_id", "business_ref_type", "business_ref_id"),
        ):
            if row["id"] in run_ids:
                session_ids.add(row["session_id"])
            if row["session_id"] in session_ids:
                run_ids.add(row["id"])
        if previous == (len(session_ids), len(run_ids)):
            break

    artifact_ids = direct_artifact_ids | {
        row["id"]
        for row in _projected_rows(
            db,
            "ark_agent_artifacts",
            ("id", "run_id", "business_ref_type", "business_ref_id"),
        )
        if row["run_id"] in run_ids
    }
    event_ids = {
        row["id"]
        for row in _projected_rows(
            db,
            "ark_agent_events",
            ("id", "run_id", "session_id"),
        )
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
        primary_key = tuple(table.primary_key.columns)
        if not primary_key:
            raise CutoverGuardError(f"target table {table.name} has no primary key")
        statement = select(table).order_by(*primary_key)
        result = db.execute(
            statement.execution_options(stream_results=True, yield_per=500)
        ).mappings()
        row_count = 0
        primary_key_ids: list[Any] = []
        content_hasher = hashlib.sha256()
        content_hasher.update(b"[")
        try:
            for row in result:
                if row[table.c.id.name] in excluded[table_name]:
                    continue
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
        tables.append(
            TableSnapshot(
                table_name=table_name,
                exists=True,
                primary_key_ids=tuple(primary_key_ids),
                row_count=row_count,
                content_sha256=content_hasher.hexdigest(),
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


def _canonical_evidence_value(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def snapshot_target_profile_rows(db: Session) -> tuple[dict[str, Any], ...]:
    """Return canonical snapshots of every preserved target-profile row."""
    table = _table_or_none(db, "ark_sales_target_profiles")
    if table is None:
        raise CutoverGuardError("preserved target-profile table is missing")
    if set(table.c.keys()) < set(TARGET_PROFILE_EXISTING_COLUMNS):
        raise CutoverGuardError("preserved target-profile columns are incomplete")
    result = db.execute(
        select(*(table.c[name] for name in TARGET_PROFILE_EXISTING_COLUMNS)).order_by(
            table.c.id
        )
    ).mappings()
    try:
        return tuple(_canonical_evidence_value(dict(row)) for row in result)
    finally:
        result.close()


def snapshot_incoming_retired_foreign_keys(db: Session) -> dict[str, Any]:
    """Freeze every FK owned by any table and targeting the 17 retired tables."""
    inspector = inspect(db.connection())
    retired_tables = tuple(RETIRED_CUSTOMER_BUSINESS_TABLES)
    retired_set = set(retired_tables)
    foreign_keys: list[dict[str, Any]] = []
    try:
        table_names = inspector.get_table_names()
        for owning_table in sorted(table_names):
            for foreign_key in inspector.get_foreign_keys(owning_table):
                target_table = foreign_key.get("referred_table")
                if target_table not in retired_set:
                    continue
                constraint_name = foreign_key.get("name")
                local_columns = foreign_key.get("constrained_columns")
                target_columns = foreign_key.get("referred_columns")
                if (
                    not isinstance(constraint_name, str)
                    or not constraint_name
                    or not isinstance(local_columns, (list, tuple))
                    or not local_columns
                    or not isinstance(target_columns, (list, tuple))
                    or len(local_columns) != len(target_columns)
                    or foreign_key.get("referred_schema") not in (None, "")
                ):
                    raise CutoverGuardError(
                        f"incoming retired FK is not safely droppable from {owning_table}"
                    )
                options = foreign_key.get("options") or {}
                onupdate = str(
                    options.get("onupdate") or foreign_key.get("onupdate") or "RESTRICT"
                ).upper()
                ondelete = str(
                    options.get("ondelete") or foreign_key.get("ondelete") or "RESTRICT"
                ).upper()
                foreign_keys.append(
                    {
                        "owning_table": owning_table,
                        "constraint_name": constraint_name,
                        "local_columns": list(local_columns),
                        "target_table": target_table,
                        "target_columns": list(target_columns),
                        "onupdate": onupdate,
                        "ondelete": ondelete,
                    }
                )
    except CutoverGuardError:
        raise
    except Exception as exc:
        raise CutoverGuardError(
            "cannot inspect incoming retired foreign keys; keep writers stopped"
        ) from exc
    foreign_keys.sort(key=canonical_json_bytes)
    payload = {
        "schema_version": 1,
        "retired_tables": list(retired_tables),
        "foreign_keys": foreign_keys,
    }
    return {**payload, "snapshot_sha256": _sha256(payload)}


def validate_incoming_retired_foreign_keys(
    db: Session,
    approved_snapshot: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(approved_snapshot, Mapping) or set(approved_snapshot) != {
        "schema_version",
        "retired_tables",
        "foreign_keys",
        "snapshot_sha256",
    }:
        raise CutoverGuardError("approved incoming retired FK snapshot is incomplete")
    payload = {
        key: value
        for key, value in approved_snapshot.items()
        if key != "snapshot_sha256"
    }
    if (
        approved_snapshot.get("schema_version") != 1
        or approved_snapshot.get("retired_tables")
        != list(RETIRED_CUSTOMER_BUSINESS_TABLES)
        or approved_snapshot.get("snapshot_sha256") != _sha256(payload)
    ):
        raise CutoverGuardError("approved incoming retired FK snapshot is invalid")
    live = snapshot_incoming_retired_foreign_keys(db)
    if canonical_json_bytes(live) != canonical_json_bytes(approved_snapshot):
        raise CutoverGuardError("incoming retired FK drift detected before DDL")
    return True


def _validate_policy_number_map(value: Any, field_name: str) -> None:
    if not isinstance(value, Mapping) or not value:
        raise CutoverGuardError(f"target-profile policy {field_name} must be non-empty")
    has_positive_value = False
    for name, number in value.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not TARGET_PROFILE_POLICY_WEIGHT_NAME_RE.fullmatch(name)
            or TARGET_PROFILE_POLICY_PLACEHOLDER_RE.search(name)
            or isinstance(number, bool)
            or not isinstance(number, (int, float, Decimal))
            or not math.isfinite(float(number))
            or number < 0
        ):
            raise CutoverGuardError(
                f"target-profile policy {field_name} contains placeholder or invalid values"
            )
        has_positive_value = has_positive_value or number > 0
    if not has_positive_value:
        raise CutoverGuardError(
            f"target-profile policy {field_name} must contain a positive value"
        )


def _validate_target_profile_policy(policy: Mapping[str, Any]) -> None:
    thresholds = policy["thresholds"]
    if not isinstance(thresholds, Mapping) or set(thresholds) != set(
        TARGET_PROFILE_THRESHOLD_FIELDS
    ):
        raise CutoverGuardError(
            "target-profile policy thresholds are not a complete semantic policy"
        )
    for value in thresholds.values():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float, Decimal))
            or not math.isfinite(float(value))
            or value < 0
            or value > 100
        ):
            raise CutoverGuardError(
                "target-profile policy thresholds are not a complete semantic policy"
            )
    if not (
        thresholds["tier_1_min_score"]
        >= thresholds["tier_2_min_score"]
        >= thresholds["tier_3_min_score"]
    ):
        raise CutoverGuardError(
            "target-profile policy tier thresholds are not ordered"
        )

    _validate_policy_number_map(policy["weights"], "weights")

    research_rules = policy["research_rules"]
    if not isinstance(research_rules, Mapping) or set(research_rules) != set(
        TARGET_PROFILE_RESEARCH_RULE_FIELDS
    ):
        raise CutoverGuardError(
            "target-profile policy research_rules are not a complete semantic policy"
        )
    for field_name in ("minimum_independent_sources", "evidence_freshness_days"):
        value = research_rules[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise CutoverGuardError(
                "target-profile policy research_rules are not a complete semantic policy"
            )
    for field_name in ("auto_research_enabled", "gate_required"):
        if not isinstance(research_rules[field_name], bool):
            raise CutoverGuardError(
                "target-profile policy research_rules are not a complete semantic policy"
            )

    claim_rules = policy["claim_rules"]
    if not isinstance(claim_rules, Mapping) or set(claim_rules) != set(
        TARGET_PROFILE_CLAIM_RULE_FIELDS
    ):
        raise CutoverGuardError(
            "target-profile policy claim_rules are not a complete semantic policy"
        )
    cooldown_days = claim_rules["cooldown_days"]
    if isinstance(cooldown_days, bool) or not isinstance(cooldown_days, int) or cooldown_days < 0:
        raise CutoverGuardError(
            "target-profile policy claim_rules are not a complete semantic policy"
        )
    for field_name in ("per_user_quota", "per_team_quota"):
        value = claim_rules[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise CutoverGuardError(
                "target-profile policy claim_rules are not a complete semantic policy"
            )
    for field_name in (
        "requires_qualification",
        "block_identity_conflict",
        "block_do_not_contact",
    ):
        if not isinstance(claim_rules[field_name], bool):
            raise CutoverGuardError(
                "target-profile policy claim_rules are not a complete semantic policy"
            )


def _target_profile_policy_snapshot(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "target_profile_policy_snapshot_v1",
        "profile": entry["expected_profile_snapshot"],
        "policy_version": entry["policy_version"],
        "policy_json": entry["policy_json"],
        "last_improvement_artifact_id": entry["last_improvement_artifact_id"],
        "policy_applied_at": entry["policy_applied_at"],
    }


def validate_target_profile_policy_backfill_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> str:
    """Validate the approved, per-profile policy backfill without inventing defaults."""
    if not isinstance(artifact, Mapping) or set(artifact) != {
        "schema_version",
        "artifact_type",
        "migration_revision",
        "approved_at",
        "confirmed_empty",
        "profiles",
        "artifact_sha256",
    }:
        raise CutoverGuardError("target-profile policy backfill artifact is incomplete")
    if (
        artifact.get("schema_version") != 1
        or artifact.get("artifact_type") != "target_profile_policy_backfill"
        or artifact.get("migration_revision") != "126"
    ):
        raise CutoverGuardError("target-profile policy backfill artifact type is invalid")
    payload = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    artifact_sha256 = _sha256(payload)
    if not hmac.compare_digest(
        str(artifact.get("artifact_sha256")), artifact_sha256
    ):
        raise CutoverGuardError("target-profile policy backfill SHA-256 mismatch")
    approved_at = _parse_writer_timestamp(
        artifact.get("approved_at"), "target-profile policy approved_at"
    )
    current = now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    _beijing_timestamp(current, "target-profile policy validation now")
    if approved_at > current:
        raise CutoverGuardError("target-profile policy approval is in the future")
    if current - approved_at > CUTOVER_EVIDENCE_MAX_AGE:
        raise CutoverGuardError("target-profile policy approval is stale")
    confirmed_empty = artifact.get("confirmed_empty")
    profiles = artifact.get("profiles")
    if not isinstance(confirmed_empty, bool) or not isinstance(profiles, list):
        raise CutoverGuardError("target-profile policy profiles must be a list")
    if confirmed_empty is not (len(profiles) == 0):
        raise CutoverGuardError(
            "target-profile policy confirmed_empty must exactly match an empty profile set"
        )

    seen_ids: set[int] = set()
    for entry in profiles:
        if not isinstance(entry, Mapping) or set(entry) != {
            "profile_id",
            "expected_profile_snapshot",
            "expected_profile_snapshot_hash",
            "policy_version",
            "policy_json",
            "policy_snapshot_hash",
            "last_improvement_artifact_id",
            "policy_applied_at",
            "improvement_approval",
        }:
            raise CutoverGuardError("target-profile policy entry is incomplete")
        profile_id = entry.get("profile_id")
        if not isinstance(profile_id, int) or isinstance(profile_id, bool) or profile_id <= 0:
            raise CutoverGuardError("target-profile policy profile_id must be positive")
        if profile_id in seen_ids:
            raise CutoverGuardError("target-profile policy profile_id is duplicated")
        seen_ids.add(profile_id)
        snapshot = entry.get("expected_profile_snapshot")
        if not isinstance(snapshot, Mapping) or set(snapshot) != set(
            TARGET_PROFILE_EXISTING_COLUMNS
        ) or snapshot.get("id") != profile_id:
            raise CutoverGuardError("target-profile expected snapshot is incomplete")
        if not hmac.compare_digest(
            str(entry.get("expected_profile_snapshot_hash")), _sha256(snapshot)
        ):
            raise CutoverGuardError("target-profile expected snapshot SHA-256 mismatch")
        policy_version = entry.get("policy_version")
        if not isinstance(policy_version, str) or not policy_version.strip() or len(
            policy_version
        ) > 32:
            raise CutoverGuardError("target-profile policy_version is invalid")
        policy = entry.get("policy_json")
        if not isinstance(policy, Mapping) or set(policy) != {
            "schema_version",
            *TARGET_PROFILE_POLICY_SECTIONS,
        } or policy.get("schema_version") != "target_profile_policy_v1":
            raise CutoverGuardError(
                "target-profile policy requires thresholds, weights, research_rules and claim_rules"
            )
        _validate_target_profile_policy(policy)
        improvement_id = entry.get("last_improvement_artifact_id")
        if improvement_id is not None and (
            not isinstance(improvement_id, int)
            or isinstance(improvement_id, bool)
            or improvement_id <= 0
        ):
            raise CutoverGuardError("target-profile improvement Artifact ID is invalid")
        applied_at = _parse_writer_timestamp(
            entry.get("policy_applied_at"), "target-profile policy_applied_at"
        )
        if applied_at > approved_at:
            raise CutoverGuardError("target-profile policy_applied_at exceeds approval")
        if not hmac.compare_digest(
            str(entry.get("policy_snapshot_hash")),
            _sha256(_target_profile_policy_snapshot(entry)),
        ):
            raise CutoverGuardError("target-profile complete policy snapshot SHA-256 mismatch")
        improvement_approval = entry.get("improvement_approval")
        if improvement_id is None:
            if improvement_approval is not None:
                raise CutoverGuardError(
                    "target-profile improvement approval requires an Artifact ID"
                )
            continue
        if not isinstance(improvement_approval, Mapping) or set(
            improvement_approval
        ) != {
            "decision",
            "approver_user_id",
            "approved_at",
            "approval_request",
            "approval_request_sha256",
            "approved_content_sha256",
        }:
            raise CutoverGuardError(
                "target-profile improvement Artifact approval is incomplete"
            )
        approver_user_id = improvement_approval.get("approver_user_id")
        if (
            improvement_approval.get("decision") != "approved"
            or not isinstance(approver_user_id, int)
            or isinstance(approver_user_id, bool)
            or approver_user_id <= 0
        ):
            raise CutoverGuardError(
                "target-profile improvement Artifact decision is not approved"
            )
        decision_at = _parse_writer_timestamp(
            improvement_approval.get("approved_at"),
            "target-profile improvement approved_at",
        )
        if decision_at > applied_at or approved_at - decision_at > CUTOVER_EVIDENCE_MAX_AGE:
            raise CutoverGuardError(
                "target-profile improvement Artifact approval is stale or unordered"
            )
        approval_request = improvement_approval.get("approval_request")
        if not isinstance(approval_request, Mapping) or set(approval_request) != {
            "artifact_id",
            "profile_id",
            "content_sha256",
            "policy_snapshot_hash",
        }:
            raise CutoverGuardError(
                "target-profile improvement Artifact approval request is incomplete"
            )
        approved_content_sha256 = improvement_approval.get(
            "approved_content_sha256"
        )
        if (
            approval_request.get("artifact_id") != improvement_id
            or approval_request.get("profile_id") != profile_id
            or approval_request.get("policy_snapshot_hash")
            != entry.get("policy_snapshot_hash")
            or approval_request.get("content_sha256") != approved_content_sha256
            or not isinstance(approved_content_sha256, str)
            or not _CANONICAL_SHA256.fullmatch(approved_content_sha256)
            or improvement_approval.get("approval_request_sha256")
            != _sha256(approval_request)
        ):
            raise CutoverGuardError(
                "target-profile improvement Artifact approval hash is invalid"
            )
    return artifact_sha256


def validate_target_profile_policy_backfill_against_live_rows(
    db: Session,
    artifact: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    validate_target_profile_policy_backfill_artifact(artifact, now=now)
    actual = {snapshot["id"]: snapshot for snapshot in snapshot_target_profile_rows(db)}
    entries = {entry["profile_id"]: entry for entry in artifact["profiles"]}
    if set(actual) != set(entries):
        raise CutoverGuardError("target-profile policy live profile set is stale")
    for profile_id, entry in entries.items():
        if actual[profile_id] != entry["expected_profile_snapshot"] or not hmac.compare_digest(
            _sha256(actual[profile_id]), entry["expected_profile_snapshot_hash"]
        ):
            raise CutoverGuardError(
                f"target-profile policy snapshot is stale for profile {profile_id}"
            )
    referenced_artifacts = {
        entry["last_improvement_artifact_id"]
        for entry in entries.values()
        if entry["last_improvement_artifact_id"] is not None
    }
    if referenced_artifacts:
        table = _table_or_none(db, "ark_agent_artifacts")
        if table is None:
            raise CutoverGuardError("target-profile improvement Artifact table is missing")
        result = db.execute(
            select(
                table.c.id,
                table.c.artifact_type,
                table.c.content_json,
                table.c.evidence_json,
                table.c.content_sha256,
                table.c.validation_status,
                table.c.decision_status,
                table.c.decided_by,
                table.c.decided_at,
                table.c.business_ref_type,
                table.c.business_ref_id,
            ).where(table.c.id.in_(referenced_artifacts))
        ).mappings()
        try:
            live_artifacts = {row["id"]: dict(row) for row in result}
        finally:
            result.close()
        if set(live_artifacts) != referenced_artifacts:
            raise CutoverGuardError("target-profile improvement Artifact binding is stale")
        users = _table_or_none(db, "ark_users")
        for profile_id, entry in entries.items():
            improvement_id = entry["last_improvement_artifact_id"]
            if improvement_id is None:
                continue
            approval = entry["improvement_approval"]
            live = live_artifacts[improvement_id]
            approved_at = _parse_writer_timestamp(
                approval["approved_at"], "target-profile improvement approved_at"
            )
            expected_decided_at = to_beijing_naive(approved_at)
            content_sha256 = _agent_artifact_content_sha256(
                live["content_json"],
                live["evidence_json"],
            )
            if (
                live["artifact_type"] != "target_profile_improvement_v1"
                or live["validation_status"] != "valid"
                or live["decision_status"] != "approved"
                or live["decided_by"] != approval["approver_user_id"]
                or live["decided_at"] != expected_decided_at
                or live["business_ref_type"] != "target_profile"
                or live["business_ref_id"] != str(profile_id)
                or live["content_sha256"] != content_sha256
                or live["content_sha256"] != approval["approved_content_sha256"]
            ):
                raise CutoverGuardError(
                    f"target-profile improvement Artifact {improvement_id} is not trusted"
                )
            if users is not None:
                approver_exists = db.execute(
                    select(users.c.id).where(
                        users.c.id == approval["approver_user_id"]
                    )
                ).scalar_one_or_none()
                if approver_exists is None:
                    raise CutoverGuardError(
                        "target-profile improvement Artifact approver is missing"
                    )
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
        table = _table_or_none(db, table_name)
        if table is None:
            continue
        existing_ids: set[Any] = set()
        id_iterator = iter(expected_removed_ids)
        while chunk := tuple(islice(id_iterator, AGENT_ID_QUERY_CHUNK_SIZE)):
            result = db.execute(
                select(table.c.id)
                .where(table.c.id.in_(chunk))
                .order_by(table.c.id)
                .execution_options(stream_results=True, yield_per=500)
            )
            try:
                existing_ids.update(row[0] for row in result)
            finally:
                result.close()
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


def _resolved_evidence_artifact(value: Any) -> tuple[Path, str]:
    relative = Path(_required_stable_text(value, "artifact_path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise CutoverGuardError("evidence artifact path must be relative to fixed root")
    root = CUTOVER_EVIDENCE_ROOT.resolve()
    lexical = root / relative
    current = lexical
    while current != root:
        if current.exists():
            stat_result = current.lstat()
            if current.is_symlink() or bool(
                getattr(stat_result, "st_file_attributes", 0) & 0x400
            ):
                raise CutoverGuardError("evidence artifact uses a symlink/reparse point")
        current = current.parent
    path = lexical.resolve()
    if not path.is_relative_to(root):
        raise CutoverGuardError("evidence artifact escaped fixed evidence root")
    if not path.is_file():
        raise CutoverGuardError(f"required evidence artifact is missing: {relative.as_posix()}")
    return path, relative.as_posix()


def _read_canonical_artifact(value: Any) -> tuple[dict[str, Any], str, str]:
    path, relative = _resolved_evidence_artifact(value)
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverGuardError(f"cannot parse evidence artifact: {relative}") from exc
    if not isinstance(document, dict):
        raise CutoverGuardError(f"evidence artifact must contain an object: {relative}")
    if raw != canonical_json_bytes(document) + b"\n":
        raise CutoverGuardError(f"evidence artifact is not canonical JSON: {relative}")
    # This digest covers immutable artifact bytes, unlike canonical evidence hashes.
    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    if not Path(relative).stem.endswith(artifact_sha256):
        raise CutoverGuardError(
            f"evidence artifact path is not content-addressed: {relative}"
        )
    return document, artifact_sha256, relative


def _external_source_artifact(
    source: Mapping[str, Any], now: datetime
) -> tuple[AuthoritativeSourceEvidence, list[Mapping[str, Any]]]:
    document, artifact_sha256, artifact_path = _read_canonical_artifact(
        source.get("artifact_path")
    )
    required_fields = {
        "schema_version",
        "source_kind",
        "source_namespace",
        "source_account_key",
        "exported_at",
        "approved_at",
        "confirmed_empty",
        "rows",
    }
    if "confirmed_empty" not in document:
        raise CutoverGuardError(
            f"suppression artifact is missing confirmed_empty: {artifact_path}"
        )
    if set(document) != required_fields or document.get("schema_version") != 1:
        raise CutoverGuardError(f"invalid suppression artifact schema: {artifact_path}")
    source_kind = _required_stable_text(document.get("source_kind"), "source_kind")
    namespace = _required_stable_text(
        document.get("source_namespace"), "source_namespace"
    )
    account = _required_stable_text(
        document.get("source_account_key"), "source_account_key"
    )
    rows = document.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise CutoverGuardError(f"suppression artifact rows are invalid: {artifact_path}")
    confirmed_empty = document.get("confirmed_empty")
    if not rows and confirmed_empty is not True:
        raise CutoverGuardError(
            f"empty suppression artifact requires confirmed_empty=true: {artifact_path}"
        )
    if rows and confirmed_empty is not False:
        raise CutoverGuardError(
            f"nonempty suppression artifact requires confirmed_empty=false: {artifact_path}"
        )
    _verify_evidence_time(
        document.get("approved_at"),
        now,
        f"authoritative source {namespace}/{account} approval",
    )
    _verify_evidence_time(
        document.get("exported_at"),
        now,
        f"authoritative source {namespace}/{account} export",
    )
    exported_at = _beijing_timestamp(document.get("exported_at"), "source exported_at")
    approved_at = _beijing_timestamp(document.get("approved_at"), "source approved_at")
    if datetime.fromisoformat(exported_at) > datetime.fromisoformat(approved_at):
        raise CutoverGuardError("source approval cannot precede artifact export")
    unresolved_count = sum(
        row.get("mapping_status", "unmapped") != "mapped" for row in rows
    )
    payload = {
        "source_kind": source_kind,
        "source_namespace": namespace,
        "source_account_key": account,
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha256,
        "source_row_count": len(rows),
        "extracted_count": len(rows),
        "unresolved_count": unresolved_count,
        "exported_at": exported_at,
        "approved_at": approved_at,
    }
    return (
        AuthoritativeSourceEvidence(**payload, evidence_sha256=_sha256(payload)),
        rows,
    )


def _database_suppression_source(
    db: Session,
    now: datetime,
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
    approved_at = _beijing_timestamp(now, "Ark database query time")
    payload = {
        "source_kind": "ark_database",
        "source_namespace": "ark",
        "source_account_key": "commission_db",
        "artifact_path": None,
        "artifact_sha256": _sha256(sorted(raw_rows, key=canonical_json_bytes)),
        "source_row_count": len(raw_rows),
        "extracted_count": len(raw_rows),
        "unresolved_count": len(raw_rows),
        "approved_at": approved_at,
        "exported_at": approved_at,
    }
    return (
        AuthoritativeSourceEvidence(**payload, evidence_sha256=_sha256(payload)),
        candidates,
    )


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
    source_mapping_status = _required_stable_text(
        _candidate_field(candidate, "mapping_status"), "mapping_status"
    )
    if source_mapping_status not in ALLOWED_MAPPING_STATUSES:
        raise CutoverGuardError(
            f"unsupported mapping_status: {source_mapping_status}"
        )
    stable_matches = candidate.get("stable_match_candidates", [])
    if not isinstance(stable_matches, list):
        raise CutoverGuardError("stable_match_candidates must be a list")
    mapping_status = "ambiguous" if len(stable_matches) > 1 else "unmapped"
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
        if metadata and (
            _RAW_EMAIL.search(str(metadata)) or _RAW_PHONE.search(str(metadata))
        ):
            raise CutoverGuardError("suppression metadata must not contain raw PII")
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
        mapped_customer_id=None,
        mapped_contact_point_id=None,
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
    now: datetime,
) -> SuppressionManifest:
    """Build an inventory-bound replay manifest from every authoritative source."""
    key = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
    if not isinstance(key, bytes) or len(key) < 32 or len(set(key)) < 8:
        raise CutoverGuardError("suppression HMAC key must contain at least 32 bytes")
    key_version = _required_stable_text(key_version, "key_version")
    now = _parse_writer_timestamp(now, "suppression export now")
    for digest, field_name in (
        (inventory_sha256, "inventory_sha256"),
        (preflight_report_sha256, "preflight_report_sha256"),
    ):
        if not isinstance(digest, str) or not _CANONICAL_SHA256.fullmatch(digest):
            raise CutoverGuardError(f"{field_name} must be lowercase SHA-256")
    sources = authoritative_source_manifest.get("sources")
    if not isinstance(sources, list):
        raise CutoverGuardError("authoritative source manifest requires sources list")
    evidence: list[AuthoritativeSourceEvidence] = []
    candidates: list[Mapping[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    actual_kinds: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            raise CutoverGuardError("authoritative source descriptor must be an object")
        item, rows = _external_source_artifact(source, now)
        actual_kinds.add(item.source_kind)
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
    missing_kinds = sorted(REQUIRED_EXTERNAL_SUPPRESSION_SOURCE_KINDS - actual_kinds)
    unsupported_kinds = sorted(actual_kinds - REQUIRED_EXTERNAL_SUPPRESSION_SOURCE_KINDS)
    if missing_kinds:
        raise CutoverGuardError(
            "missing authoritative source kinds: " + ", ".join(missing_kinds)
        )
    if unsupported_kinds:
        raise CutoverGuardError(
            "unsupported authoritative source kinds: " + ", ".join(unsupported_kinds)
        )
    database_evidence, database_candidates = _database_suppression_source(db, now)
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


def validate_suppression_manifest(
    db: Session,
    raw: Mapping[str, Any],
    hmac_key: bytes | str,
    *,
    now: datetime,
) -> bool:
    """Re-read every authority and prove a serialized replay manifest is current."""
    if not isinstance(raw, Mapping):
        raise CutoverGuardError("suppression manifest must be an object")
    source_evidence = raw.get("source_evidence")
    entries = raw.get("entries")
    if not isinstance(source_evidence, list) or not source_evidence:
        raise CutoverGuardError("suppression source evidence cannot be empty")
    if not isinstance(entries, list):
        raise CutoverGuardError("suppression entries must be a list")
    try:
        payload = {
            key: raw[key]
            for key in (
                "schema_version",
                "key_version",
                "inventory_sha256",
                "preflight_report_sha256",
                "source_evidence",
                "entries",
            )
        }
    except KeyError as exc:
        raise CutoverGuardError(
            f"suppression manifest is missing {exc.args[0]}"
        ) from exc
    if raw.get("manifest_sha256") != _sha256(payload):
        raise CutoverGuardError("suppression manifest SHA-256 does not match its content")

    external_descriptors: list[dict[str, str]] = []
    stored_database: Mapping[str, Any] | None = None
    for item in source_evidence:
        if not isinstance(item, Mapping):
            raise CutoverGuardError("suppression source evidence must be objects")
        if item.get("source_kind") == "ark_database":
            if stored_database is not None:
                raise CutoverGuardError("duplicate Ark database suppression evidence")
            stored_database = item
        else:
            external_descriptors.append({"artifact_path": item.get("artifact_path")})
    if stored_database is None:
        raise CutoverGuardError("Ark database suppression evidence is required")

    rebuilt = build_suppression_manifest(
        db,
        {"sources": external_descriptors},
        hmac_key,
        str(raw.get("key_version")),
        inventory_sha256=str(raw.get("inventory_sha256")),
        preflight_report_sha256=str(raw.get("preflight_report_sha256")),
        now=now,
    )
    rebuilt_external = {
        (item.source_kind, item.source_namespace, item.source_account_key): item.to_dict()
        for item in rebuilt.source_evidence
        if item.source_kind != "ark_database"
    }
    stored_external = {
        (str(item.get("source_kind")), str(item.get("source_namespace")), str(item.get("source_account_key"))): dict(item)
        for item in source_evidence
        if isinstance(item, Mapping) and item.get("source_kind") != "ark_database"
    }
    if stored_external != rebuilt_external:
        raise CutoverGuardError("suppression external source evidence changed")

    rebuilt_database = next(
        item.to_dict()
        for item in rebuilt.source_evidence
        if item.source_kind == "ark_database"
    )
    _verify_evidence_time(
        stored_database.get("approved_at"), now, "Ark database suppression evidence"
    )
    database_stable_fields = (
        "source_kind",
        "source_namespace",
        "source_account_key",
        "artifact_path",
        "artifact_sha256",
        "source_row_count",
        "extracted_count",
        "unresolved_count",
    )
    if any(
        stored_database.get(field) != rebuilt_database.get(field)
        for field in database_stable_fields
    ):
        raise CutoverGuardError("Ark database suppression evidence changed")
    stored_database_payload = {
        key: value
        for key, value in stored_database.items()
        if key != "evidence_sha256"
    }
    if stored_database.get("evidence_sha256") != _sha256(stored_database_payload):
        raise CutoverGuardError("Ark database suppression evidence SHA-256 mismatch")
    if entries != [entry.to_dict() for entry in rebuilt.entries]:
        raise CutoverGuardError("suppression replay entries do not match authorities")
    return True


def _parse_writer_timestamp(value: Any, field_name: str = "writer checked_at") -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CutoverGuardError(f"{field_name} must be an ISO Beijing datetime") from exc
    _beijing_timestamp(value, field_name)
    return value.astimezone(BEIJING_TIMEZONE)


def _verify_evidence_time(value: Any, now: datetime, label: str) -> None:
    checked_at = _parse_writer_timestamp(value, f"{label} checked_at")
    if checked_at > now:
        raise CutoverGuardError(f"{label} evidence is future-dated")
    if now - checked_at > CUTOVER_EVIDENCE_MAX_AGE:
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

    approved, approved_artifact_sha256, _ = _read_canonical_artifact(
        stopped_writer_manifest.get("instance_inventory_artifact")
    )
    if set(approved) != {
        "schema_version",
        "artifact_kind",
        "instances",
        "approved_at",
        "approved_by",
        "approval_detail",
        "writer_principals",
        "inventory_sha256",
        "preflight_report_sha256",
    } or approved.get("schema_version") != 1 or approved.get("artifact_kind") != "writer_instance_inventory":
        raise CutoverGuardError("invalid approved instance inventory artifact schema")
    writer_artifacts = stopped_writer_manifest.get("writer_artifacts")
    if not isinstance(writer_artifacts, list):
        raise CutoverGuardError("stopped-writer manifest requires writer artifacts")
    approved_instances = approved.get("instances")
    if not isinstance(approved_instances, list):
        raise CutoverGuardError("approved instance inventory requires instances list")
    if (
        approved.get("inventory_sha256") != inventory.inventory_sha256
        or approved.get("preflight_report_sha256") != preflight_report_sha256
    ):
        raise CutoverGuardError("approved instance inventory has wrong preflight binding")
    _required_stable_text(approved.get("approved_by"), "instance inventory approved_by")
    if len(_required_stable_text(
        approved.get("approval_detail"), "instance inventory approval_detail"
    )) < 20:
        raise CutoverGuardError("approved instance inventory requires structured evidence")
    _verify_evidence_time(
        approved.get("approved_at"), now, "instance inventory"
    )

    approved_writer_principals = approved.get("writer_principals")
    if not isinstance(approved_writer_principals, list):
        raise CutoverGuardError("approved instance inventory requires writer principals")
    approved_writer_principals = [
        _normalize_mysql_principal(value, "approved writer principal")
        for value in approved_writer_principals
    ]
    if approved_writer_principals != sorted(set(approved_writer_principals)):
        raise CutoverGuardError("approved writer principals must be unique and sorted")
    expected_instances: set[tuple[str, str]] = set()
    instance_principals: set[str] = set()
    for item in approved_instances:
        if not isinstance(item, Mapping) or set(item) != {
            "category",
            "instance_id",
            "db_principal",
        }:
            raise CutoverGuardError("approved instance inventory entries must be objects")
        identity = (
            _required_stable_text(item.get("category"), "writer category"),
            _required_stable_text(item.get("instance_id"), "writer instance_id"),
        )
        if identity in expected_instances:
            raise CutoverGuardError(f"duplicate approved writer instance: {identity}")
        expected_instances.add(identity)
        instance_principals.add(
            _normalize_mysql_principal(
                item.get("db_principal"), "approved instance DB principal"
            )
        )
    if instance_principals != set(approved_writer_principals):
        raise CutoverGuardError(
            "approved writer principals do not equal instance DB principals"
        )
    approved_categories = {category for category, _ in expected_instances}
    if approved_categories != set(KNOWN_WRITER_CATEGORIES):
        raise CutoverGuardError("approved instance inventory does not cover exact writer categories")

    actual_instances: set[tuple[str, str]] = set()
    running: list[str] = []
    expected_writer_schema = {
        "category",
        "instance_id",
        "stopped",
        "checked_at",
        "inventory_sha256",
        "preflight_report_sha256",
        "instance_inventory_artifact_sha256",
        "evidence_detail",
    }
    for writer_path in writer_artifacts:
        writer, _, _ = _read_canonical_artifact(writer_path)
        if set(writer) != expected_writer_schema:
            raise CutoverGuardError("invalid writer stop artifact schema")
        category = _required_stable_text(writer.get("category"), "writer category")
        instance_id = _required_stable_text(writer.get("instance_id"), "writer instance_id")
        identity = (category, instance_id)
        if identity in actual_instances:
            raise CutoverGuardError(f"duplicate writer instance: {category}/{instance_id}")
        actual_instances.add(identity)
        if (
            writer.get("inventory_sha256") != inventory.inventory_sha256
            or writer.get("preflight_report_sha256") != preflight_report_sha256
            or writer.get("instance_inventory_artifact_sha256")
            != approved_artifact_sha256
        ):
            raise CutoverGuardError(f"writer {category}/{instance_id} has wrong preflight binding")
        _verify_evidence_time(writer.get("checked_at"), now, f"writer {category}/{instance_id}")
        if len(_required_stable_text(
            writer.get("evidence_detail"), f"writer {category}/{instance_id} evidence"
        )) < 20:
            raise CutoverGuardError(
                f"writer {category}/{instance_id} requires nontrivial structured evidence"
            )
        if writer.get("stopped") is not True:
            running.append(f"{category}/{instance_id}")
    if actual_instances != expected_instances:
        raise CutoverGuardError("writer evidence does not equal approved instance inventory")
    if running:
        raise CutoverGuardError("writer instances still running: " + ", ".join(running))

    transactions, _, _ = _read_canonical_artifact(
        stopped_writer_manifest.get("active_transaction_artifact")
    )
    if set(transactions) != {
        "schema_version",
        "artifact_kind",
        "count",
        "checked_at",
        "inventory_sha256",
        "preflight_report_sha256",
        "instance_inventory_artifact_sha256",
        "evidence_detail",
    } or transactions.get("schema_version") != 1 or transactions.get("artifact_kind") != "active_transaction_snapshot":
        raise CutoverGuardError("invalid active transaction artifact schema")
    if (
        transactions.get("inventory_sha256") != inventory.inventory_sha256
        or transactions.get("preflight_report_sha256") != preflight_report_sha256
        or transactions.get("instance_inventory_artifact_sha256")
        != approved_artifact_sha256
    ):
        raise CutoverGuardError("active transaction evidence has wrong preflight binding")
    _verify_evidence_time(transactions.get("checked_at"), now, "active transaction")
    if len(_required_stable_text(
        transactions.get("evidence_detail"), "active transaction evidence"
    )) < 20:
        raise CutoverGuardError("active transaction requires structured evidence")
    if transactions.get("count") != 0:
        raise CutoverGuardError("relevant active transactions must be zero")

    privilege_evidence, privilege_artifact_sha256, _ = _read_canonical_artifact(
        stopped_writer_manifest.get("writer_privilege_revocation_artifact")
    )
    if (
        privilege_evidence.get("inventory_sha256") != inventory.inventory_sha256
        or privilege_evidence.get("preflight_report_sha256")
        != preflight_report_sha256
        or privilege_evidence.get("instance_inventory_artifact_sha256")
        != approved_artifact_sha256
        or privilege_evidence.get("writer_principals")
        != approved_writer_principals
    ):
        raise CutoverGuardError("writer privilege revocation has wrong readiness binding")
    validate_mysql_writer_privilege_gate(
        object(),
        privilege_evidence,
        now=now,
        privilege_reader=lambda _db: {
            "current_principal": privilege_evidence.get("migration_principal"),
            "privilege_snapshot": privilege_evidence.get("privilege_snapshot"),
        },
    )

    fence, _, _ = _read_canonical_artifact(
        stopped_writer_manifest.get("maintenance_fence_artifact")
    )
    if set(fence) != {
        "schema_version",
        "artifact_kind",
        "token",
        "instance_inventory_artifact_sha256",
        "writer_privilege_revocation_artifact_sha256",
        "inventory_sha256",
        "preflight_report_sha256",
        "issued_at",
        "expires_at",
        "approval_detail",
    } or fence.get("schema_version") != 1 or fence.get("artifact_kind") != "maintenance_fence":
        raise CutoverGuardError("invalid maintenance fence artifact schema")
    if (
        fence.get("instance_inventory_artifact_sha256") != approved_artifact_sha256
        or fence.get("writer_privilege_revocation_artifact_sha256")
        != privilege_artifact_sha256
        or fence.get("inventory_sha256") != inventory.inventory_sha256
        or fence.get("preflight_report_sha256") != preflight_report_sha256
    ):
        raise CutoverGuardError("maintenance fence has wrong readiness binding")
    _required_stable_text(fence.get("token"), "maintenance fence token")
    if len(_required_stable_text(
        fence.get("approval_detail"), "maintenance fence approval_detail"
    )) < 20:
        raise CutoverGuardError("maintenance fence requires nontrivial evidence")
    _verify_evidence_time(fence.get("issued_at"), now, "maintenance fence")
    fence_expiry = _parse_writer_timestamp(
        fence.get("expires_at"), "maintenance fence expires_at"
    )
    if fence_expiry <= now or fence_expiry - now > MIGRATION_CONTRACT_MAX_LIFETIME:
        raise CutoverGuardError("maintenance fence is expired or exceeds five-minute lifetime")
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


def _normalize_mysql_principal(value: Any, field_name: str) -> str:
    principal = _required_stable_text(value, field_name)
    if (
        len(principal) > 255
        or principal.count("@") != 1
        or any(character.isspace() or character in "'`\"" for character in principal)
    ):
        raise CutoverGuardError(f"{field_name} must be normalized user@host")
    user, host = principal.split("@", 1)
    if (
        not re.fullmatch(r"[A-Za-z0-9_$.-]+", user)
        or not re.fullmatch(r"[A-Za-z0-9_.:%-]+", host)
    ):
        raise CutoverGuardError(f"{field_name} must be normalized user@host")
    return principal


def _normalize_mysql_privilege(value: Any, field_name: str) -> str:
    privilege = _required_stable_text(value, field_name).upper().replace("_", " ")
    return " ".join(privilege.split())


def _read_mysql_principal_privileges(
    db: Session,
    writer_principals: Sequence[str],
) -> dict[str, Any]:
    """Read every exact writer grant via SHOW GRANTS on this MySQL connection."""
    if db.get_bind().dialect.name != "mysql":
        raise CutoverGuardError("writer privilege gate requires a MySQL Alembic bind")
    try:
        current = _normalize_mysql_principal(
            db.execute(text("SELECT CURRENT_USER()")).scalar_one(),
            "migration principal",
        )
        mandatory_roles = db.execute(
            text("SELECT @@GLOBAL.mandatory_roles")
        ).scalar_one()
        if mandatory_roles is not None and str(mandatory_roles).strip().upper() not in {
            "",
            "NONE",
        }:
            raise CutoverGuardError(
                "MySQL mandatory_roles must be empty during customer cutover"
            )
        privileges: dict[str, set[str]] = {}
        for principal in writer_principals:
            normalized = _normalize_mysql_principal(principal, "writer principal")
            user, host = normalized.split("@", 1)
            rows = db.execute(text(f"SHOW GRANTS FOR '{user}'@'{host}'"))
            grants: set[str] = set()
            try:
                for row in rows:
                    values = tuple(row)
                    if len(values) != 1 or not isinstance(values[0], str):
                        raise CutoverGuardError("MySQL SHOW GRANTS row is invalid")
                    statement = values[0].strip()
                    upper_statement = statement.upper()
                    if not upper_statement.startswith("GRANT "):
                        raise CutoverGuardError("MySQL SHOW GRANTS output is invalid")
                    grant_body = statement[6:]
                    upper_body = upper_statement[6:]
                    if " ON " not in upper_body:
                        grants.add("ROLE")
                        continue
                    on_index = upper_body.index(" ON ")
                    privilege_list = grant_body[:on_index]
                    for value in privilege_list.split(","):
                        privilege = _normalize_mysql_privilege(
                            value.strip().strip("`"), "MySQL SHOW GRANTS privilege"
                        )
                        if "(" in privilege:
                            privilege = privilege.split("(", 1)[0].strip()
                        grants.add(privilege)
                    if "WITH GRANT OPTION" in upper_statement:
                        grants.add("GRANT OPTION")
            finally:
                rows.close()
            role_rows = db.execute(
                text(
                    "SELECT FROM_USER AS role_user, FROM_HOST AS role_host "
                    "FROM mysql.role_edges "
                    "WHERE TO_USER=:user AND TO_HOST=:host "
                    "UNION ALL "
                    "SELECT DEFAULT_ROLE_USER AS role_user, "
                    "DEFAULT_ROLE_HOST AS role_host "
                    "FROM mysql.default_roles "
                    "WHERE USER=:user AND HOST=:host"
                ),
                {"user": user, "host": host},
            ).mappings()
            try:
                if next(iter(role_rows), None) is not None:
                    grants.add("ROLE")
            finally:
                role_rows.close()
            privileges[normalized] = grants
    except CutoverGuardError:
        raise
    except Exception as exc:
        raise CutoverGuardError(
            "cannot observe MySQL writer privileges; keep writers stopped"
        ) from exc
    return {
        "current_principal": current,
        "privilege_snapshot": {
            principal: sorted(values) for principal, values in privileges.items()
        },
    }


def validate_mysql_writer_privilege_gate(
    db: Session,
    evidence: Mapping[str, Any] | None,
    *,
    now: datetime,
    privilege_reader: Callable[[Session], Mapping[str, Any]] | None = None,
) -> bool:
    """Prove every approved writer principal is revoked on the live schema."""
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "schema_version",
        "artifact_kind",
        "migration_principal",
        "writer_principals",
        "privilege_snapshot",
        "checked_at",
        "inventory_sha256",
        "preflight_report_sha256",
        "instance_inventory_artifact_sha256",
        "evidence_detail",
        "evidence_sha256",
    }:
        raise CutoverGuardError("writer privilege revocation evidence is incomplete")
    payload = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if (
        evidence.get("schema_version") != 1
        or evidence.get("artifact_kind") != "writer_privilege_revocation"
        or evidence.get("evidence_sha256") != _sha256(payload)
    ):
        raise CutoverGuardError("writer privilege revocation evidence is invalid")
    _verify_evidence_time(evidence.get("checked_at"), now, "writer privilege revocation")
    if len(_required_stable_text(
        evidence.get("evidence_detail"), "writer privilege revocation evidence_detail"
    )) < 20:
        raise CutoverGuardError("writer privilege revocation requires structured evidence")
    migration_principal = _normalize_mysql_principal(
        evidence.get("migration_principal"), "migration principal"
    )
    principal_values = evidence.get("writer_principals")
    snapshot_values = evidence.get("privilege_snapshot")
    if not isinstance(principal_values, list) or not isinstance(snapshot_values, Mapping):
        raise CutoverGuardError("writer privilege principal snapshot is invalid")
    writer_principals = [
        _normalize_mysql_principal(value, "writer principal")
        for value in principal_values
    ]
    if writer_principals != sorted(set(writer_principals)):
        raise CutoverGuardError("writer principals must be unique and sorted")
    if migration_principal in writer_principals:
        raise CutoverGuardError("migration principal is also a writer principal")
    expected_snapshot: dict[str, list[str]] = {}
    if set(snapshot_values) != set(writer_principals):
        raise CutoverGuardError("writer privilege evidence is missing a principal")
    for principal in writer_principals:
        values = snapshot_values[principal]
        if not isinstance(values, list):
            raise CutoverGuardError("writer privilege snapshot values must be lists")
        normalized = sorted(
            {
                _normalize_mysql_privilege(value, "writer privilege")
                for value in values
            }
        )
        if normalized != values:
            raise CutoverGuardError("writer privilege snapshot must be unique and sorted")
        if set(normalized) & MYSQL_WRITER_DANGEROUS_PRIVILEGES:
            raise CutoverGuardError("writer privilege evidence retains a write privilege")
        expected_snapshot[principal] = normalized

    live = (
        privilege_reader(db)
        if privilege_reader is not None
        else _read_mysql_principal_privileges(db, writer_principals)
    )
    if not isinstance(live, Mapping):
        raise CutoverGuardError("live writer privilege proof is invalid")
    current_principal = _normalize_mysql_principal(
        live.get("current_principal"), "live migration principal"
    )
    if current_principal in writer_principals:
        raise CutoverGuardError("live migration principal is also a writer principal")
    if current_principal != migration_principal:
        raise CutoverGuardError("live migration principal does not match approved evidence")
    live_snapshot = live.get("privilege_snapshot")
    if not isinstance(live_snapshot, Mapping):
        raise CutoverGuardError("live writer privilege snapshot is invalid")
    missing = sorted(set(writer_principals) - set(live_snapshot))
    if missing:
        raise CutoverGuardError("live privilege proof is missing principal: " + ", ".join(missing))
    normalized_live: dict[str, list[str]] = {}
    for principal in writer_principals:
        values = live_snapshot[principal]
        if not isinstance(values, (list, tuple, set, frozenset)):
            raise CutoverGuardError("live writer privilege values are invalid")
        privileges = sorted(
            {
                _normalize_mysql_privilege(value, "live writer privilege")
                for value in values
            }
        )
        dangerous = sorted(set(privileges) & MYSQL_WRITER_DANGEROUS_PRIVILEGES)
        if dangerous:
            raise CutoverGuardError(
                f"writer principal {principal} retains write privilege: "
                + ", ".join(dangerous)
            )
        normalized_live[principal] = privileges
    if normalized_live != expected_snapshot:
        raise CutoverGuardError("live writer privilege snapshot mismatch")
    return True


def read_maintenance_fence_evidence(
    stopped_writer_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return content-addressed fence bindings after reading immutable bytes."""
    document, artifact_sha256, artifact_path = _read_canonical_artifact(
        stopped_writer_manifest.get("maintenance_fence_artifact")
    )
    return {
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha256,
        "token": document.get("token"),
        "instance_inventory_artifact_sha256": document.get(
            "instance_inventory_artifact_sha256"
        ),
        "writer_privilege_revocation_artifact_sha256": document.get(
            "writer_privilege_revocation_artifact_sha256"
        ),
        "writer_privilege_revocation_artifact": stopped_writer_manifest.get(
            "writer_privilege_revocation_artifact"
        ),
    }


def load_writer_privilege_revocation_evidence(
    stopped_writer_manifest: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str, str]:
    return _read_canonical_artifact(
        stopped_writer_manifest.get("writer_privilege_revocation_artifact")
    )


def validate_live_customer_cutover_writer_gate(
    db: Session,
    evidence_contract: Mapping[str, Any],
    stopped_writer_manifest: Mapping[str, Any],
    *,
    now: datetime,
) -> bool:
    """Re-prove the DB fence and revoked writer grants on the current connection."""
    privilege_evidence, artifact_sha256, artifact_path = (
        load_writer_privilege_revocation_evidence(stopped_writer_manifest)
    )
    if (
        artifact_path
        != evidence_contract.get("writer_privilege_revocation_artifact")
        or artifact_sha256
        != evidence_contract.get("writer_privilege_revocation_artifact_sha256")
    ):
        raise CutoverGuardError("live writer privilege artifact binding is invalid")
    validate_mysql_writer_privilege_gate(
        db,
        privilege_evidence,
        now=now,
    )
    if _mysql_maintenance_fence_active(
        db,
        evidence_contract,
        now=now,
        locking=False,
    ) is not True:
        raise CutoverGuardError("live customer cutover maintenance fence is not active")
    return True


def _mysql_active_write_transaction_count(db: Session) -> int:
    """Inspect live MySQL transactions on the same fenced Alembic connection."""
    try:
        connection_id = db.execute(text("SELECT CONNECTION_ID()" )).scalar_one()
        rows = db.execute(
            text(
                "SELECT trx_mysql_thread_id, trx_rows_modified, trx_tables_locked "
                "FROM information_schema.innodb_trx"
            )
        ).mappings()
        return sum(
            int(row["trx_mysql_thread_id"]) != int(connection_id)
            and (
                int(row.get("trx_rows_modified") or 0) > 0
                or int(row.get("trx_tables_locked") or 0) > 0
            )
            for row in rows
        )
    except Exception as exc:
        raise CutoverGuardError(
            "cannot inspect MySQL active transactions; keep writers stopped"
        ) from exc


def _mysql_beijing_wall_time(value: Any, field_name: str) -> datetime:
    """Interpret MySQL naive DATETIME using the application's Beijing convention."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CutoverGuardError(f"{field_name} must be a MySQL DATETIME") from exc
    if not isinstance(value, datetime):
        raise CutoverGuardError(f"{field_name} must be a MySQL DATETIME")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=BEIJING_TIMEZONE)
    return value.astimezone(BEIJING_TIMEZONE)


def _mysql_maintenance_fence_active(
    db: Session,
    contract: Mapping[str, Any],
    *,
    now: datetime | None = None,
    locking: bool = True,
) -> bool:
    """Task 3B contract: bootstrap ark_customer_cutover_fences before reset DDL."""
    try:
        statement = (
            "SELECT fence_token, inventory_sha256, preflight_report_sha256, "
            "expires_at, active FROM ark_customer_cutover_fences "
            "WHERE fence_token=:token"
        )
        if locking:
            statement += " FOR UPDATE"
        row = db.execute(
            text(statement),
            {"token": contract["maintenance_fence_token"]},
        ).mappings().one_or_none()
    except Exception as exc:
        raise CutoverGuardError(
            "maintenance fence table is unavailable; Task 3B must bootstrap "
            "ark_customer_cutover_fences before destructive DDL"
        ) from exc
    current = now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    _beijing_timestamp(current, "database fence check now")
    database_expiry = (
        _mysql_beijing_wall_time(row["expires_at"], "database fence expires_at")
        if row
        else None
    )
    contract_expiry = _parse_writer_timestamp(
        contract["expires_at"], "contract expires_at"
    )
    return bool(
        row
        and row["active"] in (True, 1)
        and row["inventory_sha256"] == contract["inventory_sha256"]
        and row["preflight_report_sha256"] == contract["preflight_report_sha256"]
        and database_expiry == contract_expiry
        and current < database_expiry <= current + MIGRATION_CONTRACT_MAX_LIFETIME
    )


def bootstrap_migration_fence(
    db: Session,
    evidence_contract: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    physical_schema_validator: Callable[[Mapping[str, Any] | None], str]
    | None = None,
) -> bool:
    """Create and activate the DB fence only from the immutable evidence chain.

    This is intentionally narrower than :func:`migration_preflight`: it performs
    no inventory read and acquires no advisory lock.  The migration invokes it on
    its Alembic bind immediately before the full preflight, which then owns the
    lock and revalidates the live inventory on that same connection.
    """
    if db.get_bind().dialect.name != "mysql":
        raise CutoverGuardError("migration fence bootstrap requires a MySQL Alembic bind")
    if not isinstance(evidence_contract, Mapping):
        raise CutoverGuardError("migration evidence contract is required for fence bootstrap")
    nonce = evidence_contract.get("nonce")
    if (
        evidence_contract.get("approved") is not True
        or evidence_contract.get("migration_revision") != "126"
        or not isinstance(nonce, str)
        or not _CUTOVER_NONCE.fullmatch(nonce)
    ):
        raise CutoverGuardError("migration fence bootstrap contract is not approved")
    contract_payload = {
        key: value for key, value in evidence_contract.items() if key != "contract_sha256"
    }
    if not hmac.compare_digest(
        str(evidence_contract.get("contract_sha256")), _sha256(contract_payload)
    ):
        raise CutoverGuardError("migration fence bootstrap contract SHA-256 mismatch")
    if evidence_contract.get("evidence_root") != str(CUTOVER_EVIDENCE_ROOT):
        raise CutoverGuardError("migration fence bootstrap evidence root is invalid")
    for field_name, prefix, relative in (
        ("contract_path", "migration-contract-", False),
        ("ddl_proof_path", "migration-ddl-proof-", True),
        ("receipt_path", "migration-receipt-", True),
    ):
        raw_path = evidence_contract.get(field_name)
        if not isinstance(raw_path, str):
            raise CutoverGuardError(
                f"migration fence bootstrap {field_name} is required"
            )
        lexical = Path(raw_path)
        if relative and (lexical.is_absolute() or ".." in lexical.parts):
            raise CutoverGuardError(
                f"migration fence bootstrap {field_name} is not fixed"
            )
        resolved = (
            (CUTOVER_EVIDENCE_ROOT / lexical).resolve()
            if relative
            else lexical.resolve()
        )
        if (
            resolved.parent != CUTOVER_EVIDENCE_ROOT
            or resolved.name != f"{prefix}{nonce}.json"
            or (relative and resolved.exists())
        ):
            raise CutoverGuardError(
                f"migration fence bootstrap {field_name} is not fixed"
            )
    try:
        ddl_proof_binding = {
            field: evidence_contract[field]
            for field in MIGRATION_DDL_PROOF_BINDING_FIELDS
        }
    except KeyError as exc:
        raise CutoverGuardError(
            f"migration fence bootstrap DDL proof binding is missing {exc.args[0]}"
        ) from exc
    if not hmac.compare_digest(
        str(evidence_contract.get("ddl_proof_binding_sha256")),
        _sha256(ddl_proof_binding),
    ):
        raise CutoverGuardError(
            "migration fence bootstrap DDL proof binding SHA-256 mismatch"
        )
    current = now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    _beijing_timestamp(current, "migration fence bootstrap now")
    load_bound_customer_physical_schema_contract(
        evidence_contract,
        now=current,
        physical_schema_validator=physical_schema_validator,
    )
    expires_at = _parse_writer_timestamp(
        evidence_contract.get("expires_at"), "migration contract expires_at"
    )
    if expires_at <= current or expires_at - current > MIGRATION_CONTRACT_MAX_LIFETIME:
        raise CutoverGuardError("migration fence bootstrap contract is expired")
    fence_document, artifact_sha256, _ = _read_canonical_artifact(
        evidence_contract.get("maintenance_fence_artifact")
    )
    bindings = {
        "token": evidence_contract.get("maintenance_fence_token"),
        "inventory_sha256": evidence_contract.get("inventory_sha256"),
        "preflight_report_sha256": evidence_contract.get("preflight_report_sha256"),
        "instance_inventory_artifact_sha256": evidence_contract.get(
            "instance_inventory_artifact_sha256"
        ),
    }
    if (
        artifact_sha256
        != evidence_contract.get("maintenance_fence_artifact_sha256")
        or fence_document.get("token") != bindings["token"]
        or fence_document.get("inventory_sha256") != bindings["inventory_sha256"]
        or fence_document.get("preflight_report_sha256")
        != bindings["preflight_report_sha256"]
        or fence_document.get("instance_inventory_artifact_sha256")
        != bindings["instance_inventory_artifact_sha256"]
        or fence_document.get("writer_privilege_revocation_artifact_sha256")
        != evidence_contract.get("writer_privilege_revocation_artifact_sha256")
    ):
        raise CutoverGuardError("migration fence bootstrap evidence binding is invalid")
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS ark_customer_cutover_fences ("
            "fence_token VARCHAR(128) NOT NULL COMMENT '维护窗口围栏令牌；仅由绑定证据激活', "
            "inventory_sha256 CHAR(64) NOT NULL COMMENT '获批清理清单SHA-256', "
            "preflight_report_sha256 CHAR(64) NOT NULL COMMENT '获批预检报告SHA-256', "
            "instance_inventory_artifact_sha256 CHAR(64) NOT NULL COMMENT '停写实例清单证据文件SHA-256', "
            "expires_at DATETIME NOT NULL COMMENT '围栏失效北京时间', "
            "active BOOLEAN NOT NULL COMMENT '围栏是否仍处于激活状态', "
            "created_at DATETIME NOT NULL COMMENT '围栏激活北京时间', "
            "PRIMARY KEY (fence_token)"
            ") COMMENT='客户域破坏性切换维护围栏；只保存短期证据绑定，不保存客户数据。'"
        )
    )
    columns = {
        row["COLUMN_NAME"]: row
        for row in db.execute(
            text(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_COMMENT, "
                "COLUMN_KEY "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='ark_customer_cutover_fences' ORDER BY ORDINAL_POSITION"
            )
        ).mappings()
    }
    expected_columns = {
        "fence_token": ("varchar(128)", "PRI"),
        "inventory_sha256": ("char(64)", ""),
        "preflight_report_sha256": ("char(64)", ""),
        "instance_inventory_artifact_sha256": ("char(64)", ""),
        "expires_at": ("datetime", ""),
        "active": ("tinyint(1)", ""),
        "created_at": ("datetime", ""),
    }
    if set(columns) != set(expected_columns) or any(
        row.get("IS_NULLABLE") != "NO"
        or not row.get("COLUMN_COMMENT")
        or str(row.get("COLUMN_TYPE", "")).lower() != expected_columns[name][0]
        or str(row.get("COLUMN_KEY", "")) != expected_columns[name][1]
        for name, row in columns.items()
    ):
        raise CutoverGuardError("migration fence table physical contract is invalid")
    existing = db.execute(
        text(
            "SELECT fence_token FROM ark_customer_cutover_fences "
            "WHERE fence_token=:fence_token FOR UPDATE"
        ),
        {"fence_token": bindings["token"]},
    ).scalar_one_or_none()
    if existing is not None:
        raise CutoverGuardError("migration fence token was already activated")
    db.execute(
        text(
            "INSERT INTO ark_customer_cutover_fences "
            "(fence_token, inventory_sha256, preflight_report_sha256, "
            "instance_inventory_artifact_sha256, expires_at, active, created_at) "
            "VALUES (:fence_token, :inventory_sha256, :preflight_report_sha256, "
            ":instance_inventory_artifact_sha256, :expires_at, 1, :created_at)"
        ),
        {
            "fence_token": bindings["token"],
            "inventory_sha256": bindings["inventory_sha256"],
            "preflight_report_sha256": bindings["preflight_report_sha256"],
            "instance_inventory_artifact_sha256": bindings[
                "instance_inventory_artifact_sha256"
            ],
            "expires_at": to_beijing_naive(expires_at),
            "created_at": to_beijing_naive(current),
        },
    )
    return True


def _read_bound_contract_artifact(
    descriptor: Any, label: str, nonce: str
) -> Mapping[str, Any]:
    if not isinstance(descriptor, Mapping) or set(descriptor) != {
        "path",
        "artifact_sha256",
    }:
        raise CutoverGuardError(f"migration {label} evidence descriptor is invalid")
    path_value = descriptor.get("path")
    if not isinstance(path_value, str):
        raise CutoverGuardError(f"migration {label} evidence path is required")
    lexical = Path(path_value)
    expected_name = f"bound-{label}-{nonce}.json"
    if lexical.name != expected_name:
        raise CutoverGuardError(f"migration {label} evidence path is not fixed")
    root = CUTOVER_EVIDENCE_ROOT.resolve()
    current = lexical
    while current != root and current.is_relative_to(root):
        if current.exists() and current.is_symlink():
            raise CutoverGuardError(f"migration {label} evidence uses a symlink")
        current = current.parent
    path = lexical.resolve()
    if path.parent != root or path.name != expected_name or not path.is_file():
        raise CutoverGuardError(f"migration {label} evidence is missing from fixed root")
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverGuardError(f"cannot read migration {label} evidence") from exc
    if not isinstance(document, Mapping) or raw != canonical_json_bytes(document) + b"\n":
        raise CutoverGuardError(f"migration {label} evidence is not canonical JSON")
    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    if artifact_sha256 != descriptor.get("artifact_sha256"):
        raise CutoverGuardError(f"migration {label} artifact SHA-256 mismatch")
    return document


def _validate_bound_contract_evidence(
    contract: Mapping[str, Any],
    nonce: str,
    *,
    now: datetime | None = None,
    physical_schema_validator: Callable[[Mapping[str, Any] | None], str]
    | None = None,
) -> dict[str, Mapping[str, Any]]:
    descriptors = contract.get("evidence_artifacts")
    labels = (
        "preflight_report",
        "suppression_manifest",
        "writer_manifest",
        "approved_marker",
        "physical_schema_contract",
        "target_profile_policy_backfill",
    )
    if not isinstance(descriptors, Mapping) or set(descriptors) != set(labels):
        raise CutoverGuardError("migration bound evidence set is incomplete")
    documents = {
        label: _read_bound_contract_artifact(descriptors[label], label, nonce)
        for label in labels
    }
    report = documents["preflight_report"]
    report_payload = {key: value for key, value in report.items() if key != "report_sha256"}
    if (
        report.get("report_sha256") != _sha256(report_payload)
        or report.get("report_sha256") != contract.get("preflight_report_sha256")
    ):
        raise CutoverGuardError("migration preflight report binding is invalid")
    inventory = CutoverInventory.from_dict(report.get("inventory", {}))
    if inventory.inventory_sha256 != contract.get("inventory_sha256"):
        raise CutoverGuardError("migration inventory report binding is invalid")

    suppression = documents["suppression_manifest"]
    suppression_payload_keys = (
        "schema_version",
        "key_version",
        "inventory_sha256",
        "preflight_report_sha256",
        "source_evidence",
        "entries",
    )
    try:
        suppression_payload = {
            key: suppression[key] for key in suppression_payload_keys
        }
    except KeyError as exc:
        raise CutoverGuardError("migration suppression evidence is incomplete") from exc
    if (
        suppression.get("manifest_sha256") != _sha256(suppression_payload)
        or suppression.get("manifest_sha256")
        != contract.get("suppression_manifest_sha256")
        or suppression.get("inventory_sha256") != contract.get("inventory_sha256")
        or suppression.get("preflight_report_sha256")
        != contract.get("preflight_report_sha256")
    ):
        raise CutoverGuardError("migration suppression manifest binding is invalid")

    writer = documents["writer_manifest"]
    if _sha256(writer) != contract.get("writer_manifest_sha256"):
        raise CutoverGuardError("migration writer manifest binding is invalid")
    privilege_evidence, privilege_artifact_sha256, privilege_path = (
        load_writer_privilege_revocation_evidence(writer)
    )
    if (
        privilege_path
        != contract.get("writer_privilege_revocation_artifact")
        or privilege_artifact_sha256
        != contract.get("writer_privilege_revocation_artifact_sha256")
        or privilege_evidence.get("inventory_sha256")
        != contract.get("inventory_sha256")
        or privilege_evidence.get("preflight_report_sha256")
        != contract.get("preflight_report_sha256")
        or privilege_evidence.get("instance_inventory_artifact_sha256")
        != contract.get("instance_inventory_artifact_sha256")
    ):
        raise CutoverGuardError(
            "migration writer privilege revocation binding is invalid"
        )
    validate_mysql_writer_privilege_gate(
        object(),
        privilege_evidence,
        now=now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE),
        privilege_reader=lambda _db: {
            "current_principal": privilege_evidence.get("migration_principal"),
            "privilege_snapshot": privilege_evidence.get("privilege_snapshot"),
        },
    )
    marker = documents["approved_marker"]
    if marker.get("approved") is not True or _sha256(marker) != contract.get(
        "approved_marker_sha256"
    ):
        raise CutoverGuardError("migration approved marker binding is invalid")
    for field_name in (
        "inventory_sha256",
        "preflight_report_sha256",
        "suppression_manifest_sha256",
        "writer_manifest_sha256",
        "writer_privilege_revocation_artifact_sha256",
        "physical_schema_contract_sha256",
        "target_profile_physical_contract_sha256",
        "target_profile_policy_backfill_sha256",
        "nonce",
    ):
        if marker.get(field_name) != contract.get(field_name):
            raise CutoverGuardError(
                f"migration approved marker does not bind {field_name}"
            )
    validate_physical_schema = (
        physical_schema_validator or validate_customer_physical_schema_contract
    )
    physical_contract_sha256 = validate_physical_schema(
        documents["physical_schema_contract"]
    )
    if physical_contract_sha256 != contract.get("physical_schema_contract_sha256"):
        raise CutoverGuardError("migration physical schema contract binding is invalid")
    policy_backfill_sha256 = validate_target_profile_policy_backfill_artifact(
        documents["target_profile_policy_backfill"],
        now=now,
    )
    if policy_backfill_sha256 != contract.get(
        "target_profile_policy_backfill_sha256"
    ):
        raise CutoverGuardError(
            "migration target-profile policy backfill binding is invalid"
        )
    return documents


def load_bound_customer_cutover_evidence(
    evidence_contract: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    physical_schema_validator: Callable[[Mapping[str, Any] | None], str]
    | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Return actual immutable evidence documents after outer and inner hash checks."""
    if not isinstance(evidence_contract, Mapping):
        raise CutoverGuardError("migration evidence contract is required")
    nonce = evidence_contract.get("nonce")
    if (
        evidence_contract.get("approved") is not True
        or evidence_contract.get("migration_revision") != "126"
        or not isinstance(nonce, str)
        or not _CUTOVER_NONCE.fullmatch(nonce)
    ):
        raise CutoverGuardError("migration evidence contract is not approved")
    payload = {
        key: value for key, value in evidence_contract.items() if key != "contract_sha256"
    }
    if not hmac.compare_digest(
        str(evidence_contract.get("contract_sha256")), _sha256(payload)
    ):
        raise CutoverGuardError("migration evidence contract SHA-256 mismatch")
    return _validate_bound_contract_evidence(
        evidence_contract,
        nonce,
        now=now,
        physical_schema_validator=physical_schema_validator,
    )


def load_bound_customer_physical_schema_contract(
    evidence_contract: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    physical_schema_validator: Callable[[Mapping[str, Any] | None], str]
    | None = None,
) -> Mapping[str, Any]:
    """Read the immutable revision-126 schema artifact bound to a contract.

    The returned document is not a descriptor.  Its canonical bytes, artifact
    bytes, inner contract hash and outer migration-contract hash have all been
    checked before a migration may compare it with its frozen DDL.
    """
    documents = load_bound_customer_cutover_evidence(
        evidence_contract,
        now=now,
        physical_schema_validator=physical_schema_validator,
    )
    physical_contract = documents["physical_schema_contract"]
    validate_physical_schema = (
        physical_schema_validator or validate_customer_physical_schema_contract
    )
    physical_sha256 = validate_physical_schema(physical_contract)
    if not hmac.compare_digest(
        physical_sha256,
        str(evidence_contract.get("physical_schema_contract_sha256")),
    ):
        raise CutoverGuardError("migration physical schema contract binding is invalid")
    return physical_contract


def load_bound_target_profile_policy_backfill(
    evidence_contract: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    documents = load_bound_customer_cutover_evidence(evidence_contract, now=now)
    artifact = documents["target_profile_policy_backfill"]
    validate_target_profile_policy_backfill_artifact(artifact, now=now)
    return artifact


def migration_preflight(
    db: Session,
    evidence_contract: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    lock_acquirer: Callable[[Session], bool] | None = None,
    transaction_inspector: Callable[[Session], int] | None = None,
    fence_inspector: Callable[[Session, Mapping[str, Any]], bool] | None = None,
    target_profile_physical_contract: Mapping[str, Any] | None = None,
    target_profile_policy_backfill: Mapping[str, Any] | None = None,
    physical_schema_validator: Callable[[Mapping[str, Any] | None], str]
    | None = None,
    privilege_reader: Callable[[Session], Mapping[str, Any]] | None = None,
) -> CutoverInventory:
    """Migration-facing fail-closed guard; the caller retains this locked bind for DDL."""
    if not isinstance(evidence_contract, Mapping):
        raise CutoverGuardError("migration evidence contract is required")
    if evidence_contract.get("approved") is not True:
        raise CutoverGuardError("migration evidence contract is not approved")
    if evidence_contract.get("evidence_root") != str(CUTOVER_EVIDENCE_ROOT):
        raise CutoverGuardError("migration evidence contract is outside the fixed evidence root")
    nonce = _required_stable_text(evidence_contract.get("nonce"), "migration nonce")
    if not _CUTOVER_NONCE.fullmatch(nonce):
        raise CutoverGuardError("migration nonce contains unsafe characters")
    for field_name, prefix in (
        ("contract_path", "migration-contract-"),
        ("ddl_proof_path", "migration-ddl-proof-"),
        ("receipt_path", "migration-receipt-"),
    ):
        raw_path = evidence_contract.get(field_name)
        if not isinstance(raw_path, str):
            raise CutoverGuardError(f"migration {field_name} is required")
        if field_name in {"ddl_proof_path", "receipt_path"}:
            relative_path = Path(raw_path)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise CutoverGuardError(
                    f"migration {field_name} must be fixed evidence-relative path"
                )
            resolved_path = (CUTOVER_EVIDENCE_ROOT / relative_path).resolve()
        else:
            resolved_path = Path(raw_path).resolve()
        if (
            not resolved_path.is_relative_to(CUTOVER_EVIDENCE_ROOT)
            or resolved_path.parent != CUTOVER_EVIDENCE_ROOT
            or resolved_path.name != f"{prefix}{nonce}.json"
        ):
            raise CutoverGuardError(f"migration {field_name} is not the fixed evidence path")
        if (
            field_name in {"ddl_proof_path", "receipt_path"}
            and resolved_path.exists()
        ):
            raise CutoverGuardError(f"migration {field_name} already exists")
    contract_payload = {
        key: value for key, value in evidence_contract.items() if key != "contract_sha256"
    }
    if not hmac.compare_digest(
        str(evidence_contract.get("contract_sha256")), _sha256(contract_payload)
    ):
        raise CutoverGuardError("migration evidence contract SHA-256 mismatch")
    if evidence_contract.get("migration_revision") != "126":
        raise CutoverGuardError("migration revision is not the approved cutover revision")
    try:
        ddl_proof_binding = {
            field: evidence_contract[field]
            for field in MIGRATION_DDL_PROOF_BINDING_FIELDS
        }
    except KeyError as exc:
        raise CutoverGuardError(
            f"migration DDL proof binding is missing {exc.args[0]}"
        ) from exc
    if not hmac.compare_digest(
        str(evidence_contract.get("ddl_proof_binding_sha256")),
        _sha256(ddl_proof_binding),
    ):
        raise CutoverGuardError("migration DDL proof binding SHA-256 mismatch")
    current = now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    _beijing_timestamp(current, "migration preflight now")
    bound_documents = _validate_bound_contract_evidence(
        evidence_contract,
        nonce,
        now=current,
        physical_schema_validator=physical_schema_validator,
    )
    for field_name in (
        "inventory_sha256",
        "preflight_report_sha256",
        "suppression_manifest_sha256",
        "writer_manifest_sha256",
        "writer_privilege_revocation_artifact_sha256",
        "approved_marker_sha256",
        "maintenance_fence_artifact_sha256",
        "instance_inventory_artifact_sha256",
        "physical_schema_contract_sha256",
        "target_profile_physical_contract_sha256",
        "target_profile_policy_backfill_sha256",
    ):
        digest = evidence_contract.get(field_name)
        if not isinstance(digest, str) or not _CANONICAL_SHA256.fullmatch(digest):
            raise CutoverGuardError(f"migration {field_name} must be lowercase SHA-256")
    issued_at = _parse_writer_timestamp(
        evidence_contract.get("issued_at"), "migration contract issued_at"
    )
    if issued_at > current or current - issued_at > MIGRATION_CONTRACT_MAX_LIFETIME:
        raise CutoverGuardError("migration evidence contract issued_at is stale or future")
    expires_at = _parse_writer_timestamp(
        evidence_contract.get("expires_at"), "migration contract expires_at"
    )
    if expires_at <= current:
        raise CutoverGuardError("migration evidence contract is expired")
    if expires_at - current > MIGRATION_CONTRACT_MAX_LIFETIME:
        raise CutoverGuardError("migration evidence contract lifetime exceeds five minutes")
    fence_document, fence_artifact_sha256, fence_artifact_path = _read_canonical_artifact(
        evidence_contract.get("maintenance_fence_artifact")
    )
    if (
        fence_artifact_sha256
        != evidence_contract.get("maintenance_fence_artifact_sha256")
        or fence_document.get("token")
        != evidence_contract.get("maintenance_fence_token")
        or fence_document.get("instance_inventory_artifact_sha256")
        != evidence_contract.get("instance_inventory_artifact_sha256")
        or fence_document.get("writer_privilege_revocation_artifact_sha256")
        != evidence_contract.get("writer_privilege_revocation_artifact_sha256")
        or fence_document.get("inventory_sha256")
        != evidence_contract.get("inventory_sha256")
        or fence_document.get("preflight_report_sha256")
        != evidence_contract.get("preflight_report_sha256")
    ):
        raise CutoverGuardError(
            f"maintenance fence artifact has wrong binding: {fence_artifact_path}"
        )
    fence_expiry = _parse_writer_timestamp(
        fence_document.get("expires_at"), "maintenance fence expires_at"
    )
    if fence_expiry < expires_at:
        raise CutoverGuardError("maintenance fence expires before migration contract")
    acquire = lock_acquirer or _acquire_mysql_cutover_lock
    if acquire(db) is not True:
        raise CutoverGuardError("customer cutover advisory lock is unavailable")
    inspect_transactions = transaction_inspector or _mysql_active_write_transaction_count
    if inspect_transactions(db) != 0:
        raise CutoverGuardError("relevant active write transactions must be zero")
    inspect_fence = fence_inspector or _mysql_maintenance_fence_active
    if inspect_fence(db, evidence_contract) is not True:
        raise CutoverGuardError("database maintenance fence is not active")
    privilege_evidence, _, _ = load_writer_privilege_revocation_evidence(
        bound_documents["writer_manifest"]
    )
    validate_mysql_writer_privilege_gate(
        db,
        privilege_evidence,
        now=current,
        privilege_reader=privilege_reader,
    )
    if (target_profile_physical_contract is None) is not (
        target_profile_policy_backfill is None
    ):
        raise CutoverGuardError(
            "target-profile physical contract and policy backfill must be supplied together"
        )
    if target_profile_physical_contract is not None:
        validate_target_profile_physical_state(
            db,
            target_profile_physical_contract,
        )
        validate_target_profile_policy_backfill_against_live_rows(
            db,
            target_profile_policy_backfill,
            now=current,
        )
    live_inventory = build_inventory(db)
    if not hmac.compare_digest(
        live_inventory.inventory_sha256, str(evidence_contract["inventory_sha256"])
    ):
        raise CutoverGuardError("live inventory changed after cutover approval")
    return live_inventory


def _sql_expression(value: Any) -> str | None:
    if value is None:
        return None
    source = str(value).strip()
    tokens: list[str] = []
    index = 0
    while index < len(source):
        character = source[index]
        if character.isspace():
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            end = index + 1
            while end < len(source):
                if source[end] == "\\":
                    end += 2
                    continue
                if source[end] == quote:
                    if end + 1 < len(source) and source[end + 1] == quote:
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            tokens.append(source[index:end])
            index = end
            continue
        if character == "`":
            end = source.find("`", index + 1)
            if end < 0:
                tokens.append(source[index:].casefold())
                break
            tokens.append(source[index + 1 : end].replace("``", "`").casefold())
            index = end + 1
            continue
        if character.isalnum() or character in {"_", "$"}:
            end = index + 1
            while end < len(source) and (
                source[end].isalnum() or source[end] in {"_", "$"}
            ):
                end += 1
            token = source[index:end]
            next_nonspace = end
            while next_nonspace < len(source) and source[next_nonspace].isspace():
                next_nonspace += 1
            if token.startswith("_") and next_nonspace < len(source) and source[
                next_nonspace
            ] in {"'", '"'}:
                index = end
                continue
            tokens.append(token.casefold())
            index = end
            continue
        operator = source[index : index + 2]
        if operator in {">=", "<=", "<>", "!=", "||", "&&", "<<", ">>"}:
            tokens.append(operator)
            index += 2
        else:
            tokens.append(character)
            index += 1

    def outer_parentheses_cover_all(items: list[str]) -> bool:
        if len(items) < 2 or items[0] != "(" or items[-1] != ")":
            return False
        depth = 0
        for position, token in enumerate(items):
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0 and position != len(items) - 1:
                    return False
            if depth < 0:
                return False
        return depth == 0

    while outer_parentheses_cover_all(tokens):
        tokens = tokens[1:-1]
    return " ".join(tokens)


def _type_signature(value: Any) -> dict[str, Any]:
    mysql_type = value.dialect_impl(mysql.dialect())
    rendered = str(mysql_type.compile(dialect=mysql.dialect())).upper()
    type_name = rendered.split("(", 1)[0].strip()
    if type_name in {"BOOL", "BOOLEAN"} or (
        type_name == "TINYINT" and getattr(mysql_type, "display_width", None) == 1
    ):
        type_name = "BOOLEAN"
    elif type_name == "NUMERIC":
        type_name = "DECIMAL"
    return {
        "name": type_name,
        "length": getattr(mysql_type, "length", None),
        "precision": getattr(mysql_type, "precision", None),
        "scale": getattr(mysql_type, "scale", None),
        "unsigned": bool(getattr(mysql_type, "unsigned", False)),
        "enum_values": tuple(getattr(mysql_type, "enums", ()) or ()),
    }


def normalize_physical_schema_signature(
    *,
    columns: Iterable[Mapping[str, Any]],
    primary_key: Mapping[str, Any],
    unique_constraints: Iterable[Mapping[str, Any]],
    indexes: Iterable[Mapping[str, Any]],
    foreign_keys: Iterable[Mapping[str, Any]],
    checks: Iterable[Mapping[str, Any]],
    table_comment: str | None,
) -> dict[str, Any]:
    """Normalize SQLAlchemy/MySQL reflection into one comparison-safe contract."""
    pk_columns = tuple(primary_key.get("constrained_columns") or ())
    unique_items = tuple(unique_constraints)
    duplicate_unique_index_names = {
        item.get("duplicates_index")
        for item in unique_items
        if item.get("duplicates_index")
    }
    index_items = tuple(
        item
        for item in indexes
        if item.get("name") not in duplicate_unique_index_names
    )

    def referential_action(value: Any) -> str:
        normalized = str(value).strip().upper() if value is not None else ""
        return "RESTRICT" if normalized in {"", "NO ACTION", "RESTRICT"} else normalized

    normalized_columns = []
    for column in columns:
        computed = column.get("computed")
        column_type = column.get("type")
        autoincrement = column.get("autoincrement", False)
        if autoincrement in {"auto", "ignore_fk"}:
            autoincrement = (
                column.get("name") in pk_columns
                and "INT" in str(column_type).upper()
            )
        normalized_columns.append(
            {
                "name": column.get("name"),
                "type": _type_signature(column_type),
                "nullable": bool(column.get("nullable")),
                "default": _sql_expression(column.get("default")),
                "primary_key": column.get("name") in pk_columns,
                "autoincrement": autoincrement is True,
                "temporal_fsp": column.get(
                    "temporal_fsp", getattr(column_type, "fsp", None)
                ),
                "computed": (
                    None
                    if not computed
                    else {
                        "expression": _sql_expression(computed.get("sqltext")),
                        "persisted": computed.get("persisted"),
                    }
                ),
                "comment": column.get("comment"),
            }
        )
    return {
        "columns": tuple(normalized_columns),
        "primary_key": {
            "name": primary_key.get("name"),
            "columns": pk_columns,
        },
        "unique_constraints": tuple(
            sorted(
                [(
                    item.get("name"),
                    tuple(item.get("column_names") or ()),
                ) for item in unique_items],
                key=canonical_json_bytes,
            )
        ),
        "indexes": tuple(
            sorted(
                [(
                    item.get("name"),
                    bool(item.get("unique")),
                    tuple(item.get("column_names") or ()),
                ) for item in index_items],
                key=canonical_json_bytes,
            )
        ),
        "foreign_keys": tuple(
            sorted(
                [(
                    item.get("name"),
                    tuple(item.get("constrained_columns") or ()),
                    item.get("referred_schema"),
                    item.get("referred_table"),
                    tuple(item.get("referred_columns") or ()),
                    referential_action(
                        (item.get("options") or {}).get("ondelete")
                    ),
                    referential_action(
                        (item.get("options") or {}).get("onupdate")
                    ),
                ) for item in foreign_keys],
                key=canonical_json_bytes,
            )
        ),
        "checks": tuple(
            sorted(
                [(
                    item.get("name"),
                    _sql_expression(item.get("sqltext")),
                    (item.get("dialect_options") or {}).get("mysql_enforced", False),
                ) for item in checks],
                key=canonical_json_bytes,
            )
        ),
        "table_comment": table_comment,
    }


def compare_physical_schema_signature(
    expected: Mapping[str, Any], actual: Mapping[str, Any], table_name: str
) -> bool:
    """Fail at the first physical category that differs from the approved contract."""
    for category in (
        "columns",
        "primary_key",
        "unique_constraints",
        "indexes",
        "foreign_keys",
        "checks",
        "table_comment",
    ):
        if canonical_json_bytes(expected.get(category)) != canonical_json_bytes(
            actual.get(category)
        ):
            raise CutoverGuardError(
                f"physical schema {category} mismatch for {table_name}"
            )
    return True


def validate_customer_physical_schema_contract(
    contract: Mapping[str, Any] | None,
) -> str:
    """Validate revision 126's mandatory 39-table expected physical contract."""
    core_tables = _runtime_core_tables()
    if not isinstance(contract, Mapping):
        raise CutoverGuardError("revision 126 physical schema contract is required")
    if set(contract) != {
        "schema_version",
        "migration_revision",
        "tables",
        "contract_sha256",
    } or contract.get("schema_version") != 1 or contract.get("migration_revision") != "126":
        raise CutoverGuardError("physical schema contract must be revision 126 schema v1")
    tables = contract.get("tables")
    expected_table_names = set(NEW_CUSTOMER_TABLES + REBUILT_CUSTOMER_WORKFLOW_TABLES)
    if not isinstance(tables, Mapping) or set(tables) != expected_table_names:
        raise CutoverGuardError(
            "revision 126 physical schema contract must contain exactly 39 tables"
        )
    signature_categories = {
        "columns",
        "primary_key",
        "unique_constraints",
        "indexes",
        "foreign_keys",
        "checks",
        "table_comment",
    }
    for table_name, signature in tables.items():
        if not isinstance(signature, Mapping) or set(signature) != signature_categories:
            raise CutoverGuardError(
                f"physical schema contract is incomplete for {table_name}"
            )
        columns = signature.get("columns")
        if not isinstance(columns, (list, tuple)) or any(
            not isinstance(column, Mapping) for column in columns
        ):
            raise CutoverGuardError(f"physical columns are invalid for {table_name}")
        actual_column_names = [column.get("name") for column in columns]
        expected_column_names = (
            list(core_tables[table_name].c.keys())
            if table_name in core_tables
            else list(REBUILT_WORKFLOW_COLUMNS[table_name])
        )
        if set(actual_column_names) != set(expected_column_names) or len(
            actual_column_names
        ) != len(expected_column_names):
            raise CutoverGuardError(
                f"physical schema contract has wrong columns for {table_name}"
            )
        for column in columns:
            if set(column) != {
                "name",
                "type",
                "nullable",
                "default",
                "primary_key",
                "autoincrement",
                "temporal_fsp",
                "computed",
                "comment",
            }:
                raise CutoverGuardError(
                    f"physical column contract is incomplete for {table_name}.{column.get('name')}"
                )
            type_contract = column.get("type")
            if not isinstance(type_contract, Mapping) or set(type_contract) != {
                "name",
                "length",
                "precision",
                "scale",
                "unsigned",
                "enum_values",
            }:
                raise CutoverGuardError(
                    f"physical type contract is incomplete for {table_name}.{column.get('name')}"
                )
            computed = column.get("computed")
            if computed is not None and (
                not isinstance(computed, Mapping)
                or set(computed) != {"expression", "persisted"}
            ):
                raise CutoverGuardError(
                    f"physical generated-column contract is incomplete for {table_name}.{column.get('name')}"
                )
            if not isinstance(column.get("comment"), str) or not column["comment"].strip():
                raise CutoverGuardError(
                    f"physical column comment is required for {table_name}.{column.get('name')}"
                )
        if not isinstance(signature.get("table_comment"), str) or not signature[
            "table_comment"
        ].strip():
            raise CutoverGuardError(f"physical table comment is required for {table_name}")
        primary_key = signature.get("primary_key")
        if (
            not isinstance(primary_key, Mapping)
            or set(primary_key) != {"name", "columns"}
            or not isinstance(primary_key.get("columns"), (list, tuple))
            or not primary_key["columns"]
        ):
            raise CutoverGuardError(f"physical primary key is incomplete for {table_name}")
        for category, item_length in (
            ("unique_constraints", 2),
            ("indexes", 3),
            ("foreign_keys", 7),
            ("checks", 3),
        ):
            items = signature.get(category)
            if not isinstance(items, (list, tuple)) or any(
                not isinstance(item, (list, tuple)) or len(item) != item_length
                for item in items
            ):
                raise CutoverGuardError(
                    f"physical {category} contract is incomplete for {table_name}"
                )
    payload = {key: value for key, value in contract.items() if key != "contract_sha256"}
    expected_sha256 = _sha256(payload)
    if contract.get("contract_sha256") != expected_sha256:
        raise CutoverGuardError("physical schema contract SHA-256 mismatch")
    return expected_sha256


def _model_physical_schema_signature(table: Table) -> dict[str, Any]:
    columns = []
    for column in table.c:
        computed = None
        if column.computed is not None:
            computed = {
                "sqltext": str(column.computed.sqltext),
                "persisted": column.computed.persisted,
            }
        columns.append(
            {
                "name": column.name,
                "type": column.type,
                "nullable": column.nullable,
                "default": (
                    None
                    if column.computed is not None
                    else str(getattr(column.server_default, "arg", column.server_default))
                    if column.server_default is not None
                    else None
                ),
                "computed": computed,
                "autoincrement": column.autoincrement,
                "temporal_fsp": getattr(column.type, "fsp", None),
                "comment": column.comment,
            }
        )
    constraints = tuple(table.constraints)
    return normalize_physical_schema_signature(
        columns=columns,
        primary_key={
            "name": table.primary_key.name,
            "constrained_columns": [column.name for column in table.primary_key.columns],
        },
        unique_constraints=(
            {
                "name": item.name,
                "column_names": [column.name for column in item.columns],
            }
            for item in constraints
            if item.__class__.__name__ == "UniqueConstraint"
        ),
        indexes=(
            {
                "name": item.name,
                "unique": item.unique,
                "column_names": [column.name for column in item.columns],
            }
            for item in table.indexes
        ),
        foreign_keys=(
            {
                "name": item.name,
                "constrained_columns": [element.parent.name for element in item.elements],
                "referred_schema": next(iter(item.elements)).column.table.schema,
                "referred_table": next(iter(item.elements)).column.table.name,
                "referred_columns": [element.column.name for element in item.elements],
                "options": {
                    "ondelete": item.ondelete,
                    "onupdate": item.onupdate,
                },
            }
            for item in constraints
            if item.__class__.__name__ == "ForeignKeyConstraint"
        ),
        checks=(
            {
                "name": item.name,
                "sqltext": str(item.sqltext),
                "dialect_options": {
                    "mysql_enforced": item.dialect_options["mysql"].get(
                        "enforced", True
                    )
                },
            }
            for item in constraints
            if item.__class__.__name__ == "CheckConstraint"
        ),
        table_comment=table.comment,
    )


def _mysql_enforced_checks(
    connection: Any,
    table_name: str,
    inspector_checks: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Bind reflected CHECK SQL to MySQL's authoritative enforcement state."""
    checks = tuple(dict(item) for item in inspector_checks)
    try:
        result = connection.execute(
            text(
                "SELECT CONSTRAINT_NAME AS constraint_name, ENFORCED AS enforced "
                "FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = DATABASE() "
                "AND TABLE_NAME = :table_name AND CONSTRAINT_TYPE = 'CHECK'"
            ),
            {"table_name": table_name},
        ).mappings()
        authoritative: dict[str, str] = {}
        try:
            for row in result:
                constraint_name = row.get("constraint_name")
                enforced = row.get("enforced")
                if (
                    not isinstance(constraint_name, str)
                    or not constraint_name
                    or constraint_name in authoritative
                ):
                    raise CutoverGuardError(
                        f"MySQL CHECK enforcement evidence is invalid for {table_name}"
                    )
                authoritative[constraint_name] = str(enforced).upper()
        finally:
            result.close()
    except CutoverGuardError:
        raise
    except Exception as exc:
        raise CutoverGuardError(
            f"could not read MySQL CHECK enforcement for {table_name}"
        ) from exc

    reflected_names = {item.get("name") for item in checks}
    if (
        None in reflected_names
        or reflected_names != set(authoritative)
        or any(authoritative[name] != "YES" for name in reflected_names)
    ):
        raise CutoverGuardError(
            f"MySQL CHECK enforcement is missing or disabled for {table_name}"
        )
    enriched = []
    for item in checks:
        dialect_options = dict(item.get("dialect_options") or {})
        dialect_options["mysql_enforced"] = True
        item["dialect_options"] = dialect_options
        enriched.append(item)
    return tuple(enriched)


def _reflected_physical_schema_signature(
    inspector: Any,
    table_name: str,
    *,
    connection: Any | None = None,
) -> dict[str, Any]:
    checks = inspector.get_check_constraints(table_name)
    if connection is not None and connection.dialect.name == "mysql":
        checks = _mysql_enforced_checks(connection, table_name, checks)
    return normalize_physical_schema_signature(
        columns=inspector.get_columns(table_name),
        primary_key=inspector.get_pk_constraint(table_name),
        unique_constraints=inspector.get_unique_constraints(table_name),
        indexes=inspector.get_indexes(table_name),
        foreign_keys=inspector.get_foreign_keys(table_name),
        checks=checks,
        table_comment=inspector.get_table_comment(table_name).get("text"),
    )


def validate_target_profile_physical_state(
    db: Session,
    expected_signature: Mapping[str, Any],
) -> bool:
    """Compare the preserved target-profile table with revision 126's frozen DDL."""
    connection = db.connection()
    inspector = inspect(connection)
    table_name = "ark_sales_target_profiles"
    if not inspector.has_table(table_name):
        raise CutoverGuardError("preserved target-profile table is missing")
    if connection.dialect.name != "mysql":
        expected_names = {
            column["name"] for column in expected_signature.get("columns", ())
        }
        actual_names = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if actual_names != expected_names:
            raise CutoverGuardError(
                "preserved target-profile columns do not match frozen contract"
            )
        return True
    actual_signature = _reflected_physical_schema_signature(
        inspector,
        table_name,
        connection=connection,
    )
    compare_physical_schema_signature(
        expected_signature,
        actual_signature,
        table_name,
    )
    return True


def verify_target_profile_post_state(
    db: Session,
    expected_signature: Mapping[str, Any],
    target_profile_policy_backfill: Mapping[str, Any],
) -> bool:
    """Verify post-ALTER schema plus exact approved policy values and snapshots."""
    validate_target_profile_physical_state(db, expected_signature)
    validate_target_profile_policy_backfill_against_live_rows(
        db,
        target_profile_policy_backfill,
    )
    table = _table_or_none(db, "ark_sales_target_profiles")
    if table is None:
        raise CutoverGuardError("preserved target-profile table is missing")
    expected_entries = {
        entry["profile_id"]: entry
        for entry in target_profile_policy_backfill["profiles"]
    }
    result = db.execute(
        select(
            table.c.id,
            table.c.policy_version,
            table.c.policy_json,
            table.c.policy_snapshot_hash,
            table.c.last_improvement_artifact_id,
            table.c.policy_applied_at,
        ).order_by(table.c.id)
    ).mappings()
    try:
        actual_rows = {row["id"]: dict(row) for row in result}
    finally:
        result.close()
    if set(actual_rows) != set(expected_entries):
        raise CutoverGuardError("target-profile post-ALTER profile set changed")
    for profile_id, entry in expected_entries.items():
        actual = actual_rows[profile_id]
        applied_at = to_beijing_naive(
            _parse_writer_timestamp(
                entry["policy_applied_at"], "target-profile policy_applied_at"
            )
        )
        expected_values = {
            "id": profile_id,
            "policy_version": entry["policy_version"],
            "policy_json": entry["policy_json"],
            "policy_snapshot_hash": entry["policy_snapshot_hash"],
            "last_improvement_artifact_id": entry[
                "last_improvement_artifact_id"
            ],
            "policy_applied_at": applied_at,
        }
        if actual != expected_values or not hmac.compare_digest(
            actual["policy_snapshot_hash"],
            _sha256(_target_profile_policy_snapshot(entry)),
        ):
            raise CutoverGuardError(
                f"target-profile post-ALTER policy mismatch for profile {profile_id}"
            )
    return True


def verify_expected_customer_table_state(
    db: Session,
    physical_schema_contract: Mapping[str, Any] | None = None,
) -> bool:
    """Verify approved table names plus exact model/design schema signatures."""
    core_tables = _runtime_core_tables()
    connection = db.connection()
    inspector = inspect(connection)
    expected_physical_tables = None
    if connection.dialect.name == "mysql":
        validate_customer_physical_schema_contract(physical_schema_contract)
        expected_physical_tables = physical_schema_contract["tables"]
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
        if table_name in core_tables:
            model_table = core_tables[table_name]
            expected_names = set(model_table.c.keys())
        else:
            expected_names = set(REBUILT_WORKFLOW_COLUMNS[table_name])
            candidate = next(iter(core_tables.values())).metadata.tables.get(table_name)
            model_table = (
                candidate
                if candidate is not None and set(candidate.c.keys()) == expected_names
                else None
            )
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
            compare_physical_schema_signature(
                expected_physical_tables[table_name],
                _reflected_physical_schema_signature(
                    inspector,
                    table_name,
                    connection=connection,
                ),
                table_name,
            )
    return True


def expected_customer_schema_sha256(
    physical_schema_contract: Mapping[str, Any] | None = None,
) -> str:
    """Return the immutable schema contract hash shared by reset and verification."""
    if physical_schema_contract is not None:
        return validate_customer_physical_schema_contract(physical_schema_contract)
    core_tables = _runtime_core_tables()
    core = {}
    for table_name in NEW_CUSTOMER_TABLES:
        table = core_tables[table_name]
        core[table_name] = _model_physical_schema_signature(table)
    rebuilt = {}
    metadata = next(iter(core_tables.values())).metadata
    for table_name in REBUILT_CUSTOMER_WORKFLOW_TABLES:
        candidate = metadata.tables.get(table_name)
        if candidate is not None and set(candidate.c.keys()) == set(
            REBUILT_WORKFLOW_COLUMNS[table_name]
        ):
            rebuilt[table_name] = _model_physical_schema_signature(candidate)
        else:
            rebuilt[table_name] = {
                "physical_contract": "unavailable",
                "columns": sorted(REBUILT_WORKFLOW_COLUMNS[table_name]),
                "table_comment": REBUILT_WORKFLOW_COMMENTS[table_name],
            }
    return _sha256({"schema_version": 2, "core": core, "rebuilt": rebuilt})


def verify_frozen_business_ids_removed(
    db: Session, inventory: CutoverInventory
) -> bool:
    """Ensure no exact preflight PK from any retired business table survived."""
    remaining: list[str] = []
    for table_name in RETIRED_CUSTOMER_BUSINESS_TABLES:
        snapshot = inventory.table(table_name)
        if not snapshot.exists or not snapshot.primary_key_ids:
            continue
        table = _table_or_none(db, table_name)
        if table is None:
            continue
        primary_key = tuple(table.primary_key.columns)
        if not primary_key:
            raise CutoverGuardError(f"post-reset table {table_name} has no primary key")
        frozen_keys = {
            tuple(value) if isinstance(value, list) else value
            for value in snapshot.primary_key_ids
        }
        statement = (
            select(*primary_key)
            .order_by(*primary_key)
            .execution_options(stream_results=True, yield_per=500)
        )
        result = db.execute(statement)
        try:
            for row in result:
                current_key: Any = row[0] if len(primary_key) == 1 else tuple(row)
                if current_key in frozen_keys:
                    remaining.append(f"{table_name}:{current_key}")
        finally:
            result.close()
    if remaining:
        raise CutoverGuardError(
            "frozen retired business rows remain: " + ", ".join(remaining)
        )
    return True
