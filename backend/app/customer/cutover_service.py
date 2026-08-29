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
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.models import CORE_TABLE_NAMES


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

AGENT_CONTROL_TABLES = (
    "ark_agent_profiles",
    "ark_agent_sessions",
    "ark_agent_runs",
    "ark_agent_events",
    "ark_agent_artifacts",
)

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

KNOWN_WRITER_CATEGORIES = (
    "local_api",
    "beijing_cloud_api",
    "schedulers",
    "agent_workers",
    "search",
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
ALLOWED_SUPPRESSION_SCOPES = frozenset({"email", "phone", "domain", "provider_id"})
ALLOWED_MAPPING_STATUSES = frozenset({"matched", "ambiguous", "unmapped"})
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
_CANONICAL_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
class SuppressionCandidate:
    source_namespace: str
    scope: str
    value: str
    reason: str
    source_ref: str
    effective_at: datetime
    mapping_status: str = "matched"


@dataclass(frozen=True)
class SuppressionManifestEntry:
    source_namespace: str
    scope: str
    reason: str
    source_ref: str
    effective_at: str
    mapping_status: str
    value_hmac_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_namespace": self.source_namespace,
            "scope": self.scope,
            "reason": self.reason,
            "source_ref": self.source_ref,
            "effective_at": self.effective_at,
            "mapping_status": self.mapping_status,
            "value_hmac_sha256": self.value_hmac_sha256,
        }


@dataclass(frozen=True)
class SuppressionManifest:
    key_version: str
    generated_at: str
    entries: tuple[SuppressionManifestEntry, ...]
    manifest_sha256: str

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "key_version": self.key_version,
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
        return {"$decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, time):
        return {"$time": value.isoformat(timespec="microseconds")}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return {"$type": type(value).__qualname__, "$string": str(value)}


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
    rows = _ordered_rows(db, table)
    return TableSnapshot(
        table_name=table_name,
        exists=True,
        primary_key_ids=_primary_key_ids(table, rows),
        row_count=len(rows),
        content_sha256=_sha256(rows),
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
    sessions = _rows_for(db, "ark_agent_sessions")
    runs = _rows_for(db, "ark_agent_runs")
    events = _rows_for(db, "ark_agent_events")
    artifacts = _rows_for(db, "ark_agent_artifacts")

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


def _candidate_field(candidate: SuppressionCandidate | Mapping[str, Any], name: str) -> Any:
    if isinstance(candidate, Mapping):
        try:
            return candidate[name]
        except KeyError as exc:
            raise CutoverGuardError(f"suppression candidate requires {name}") from exc
    return getattr(candidate, name)


def _optional_candidate_field(
    candidate: SuppressionCandidate | Mapping[str, Any],
    name: str,
    default: Any,
) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


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


def _normalize_suppression_value(scope: str, value: Any) -> str:
    if not isinstance(value, str):
        raise CutoverGuardError("suppression value must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if scope == "email":
        if normalized.count("@") != 1:
            raise CutoverGuardError("email suppression value is invalid")
        local, domain = normalized.rsplit("@", 1)
        if not local:
            raise CutoverGuardError("email suppression value is invalid")
        return f"{local.casefold()}@{_normalize_domain(domain)}"
    if scope == "domain":
        return _normalize_domain(normalized)
    if scope == "phone":
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
    if scope == "provider_id":
        if not normalized:
            raise CutoverGuardError("provider ID suppression value is invalid")
        return normalized
    raise CutoverGuardError(f"unsupported suppression scope: {scope}")


def _beijing_timestamp(value: Any, field_name: str) -> str:
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


def build_suppression_manifest(
    candidates: Iterable[SuppressionCandidate | Mapping[str, Any]],
    hmac_key: bytes | str,
    key_version: str,
    *,
    confirmed_empty: bool = False,
) -> SuppressionManifest:
    """Build a deterministic HMAC-only compliance manifest from explicit candidates."""
    rows = list(candidates)
    if not rows and confirmed_empty is not True:
        raise CutoverGuardError("empty suppressions require confirmed_empty=True")
    key = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
    if not isinstance(key, bytes) or len(key) < 32:
        raise CutoverGuardError("suppression HMAC key must contain at least 32 bytes")
    key_version = _required_stable_text(key_version, "key_version")

    entries: list[SuppressionManifestEntry] = []
    for candidate in rows:
        namespace = _required_stable_text(
            _candidate_field(candidate, "source_namespace"), "source_namespace"
        )
        scope = _required_stable_text(_candidate_field(candidate, "scope"), "scope")
        if scope not in ALLOWED_SUPPRESSION_SCOPES:
            raise CutoverGuardError(f"unsupported suppression scope: {scope}")
        reason = _required_stable_text(_candidate_field(candidate, "reason"), "reason")
        if reason not in ALLOWED_SUPPRESSION_REASONS:
            raise CutoverGuardError(f"unsupported suppression reason: {reason}")
        source_ref = _required_stable_text(
            _candidate_field(candidate, "source_ref"), "source_ref"
        )
        mapping_status = _required_stable_text(
            _optional_candidate_field(candidate, "mapping_status", "matched"),
            "mapping_status",
        )
        if mapping_status not in ALLOWED_MAPPING_STATUSES:
            raise CutoverGuardError(f"unsupported mapping_status: {mapping_status}")
        normalized_value = _normalize_suppression_value(
            scope, _candidate_field(candidate, "value")
        )
        raw_value = unicodedata.normalize(
            "NFKC", _candidate_field(candidate, "value")
        ).strip()
        variable_metadata = (namespace, source_ref, key_version)
        if any(
            identity.casefold() in metadata.casefold()
            for identity in {raw_value, normalized_value}
            for metadata in variable_metadata
            if identity
        ):
            raise CutoverGuardError(
                "source metadata must not contain the raw suppression value"
            )
        digest_input = "\0".join((namespace, scope, normalized_value)).encode("utf-8")
        entries.append(
            SuppressionManifestEntry(
                source_namespace=namespace,
                scope=scope,
                reason=reason,
                source_ref=source_ref,
                effective_at=_beijing_timestamp(
                    _candidate_field(candidate, "effective_at"), "effective_at"
                ),
                mapping_status=mapping_status,
                value_hmac_sha256=hmac.new(key, digest_input, hashlib.sha256).hexdigest(),
            )
        )

    entries.sort(
        key=lambda entry: (
            entry.source_namespace,
            entry.scope,
            entry.source_ref,
            entry.reason,
            entry.effective_at,
            entry.mapping_status,
            entry.value_hmac_sha256,
        )
    )
    provisional = SuppressionManifest(key_version, _generated_at(), tuple(entries), "")
    return SuppressionManifest(
        key_version=key_version,
        generated_at=provisional.generated_at,
        entries=tuple(entries),
        manifest_sha256=_sha256(provisional._hash_payload()),
    )


def _parse_writer_timestamp(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CutoverGuardError("writer checked_at must be an ISO Beijing datetime") from exc
    return _beijing_timestamp(value, "writer checked_at")


def verify_ready(
    inventory: CutoverInventory,
    stopped_writer_manifest: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    expected_inventory_sha256: str,
) -> bool:
    """Validate the exact inventory and evidence for every known writer category."""
    actual_content_hash = _sha256(inventory._hash_payload())
    if not hmac.compare_digest(inventory.inventory_sha256, actual_content_hash):
        raise CutoverGuardError("inventory content does not match its embedded SHA-256")
    if not isinstance(expected_inventory_sha256, str) or not _CANONICAL_SHA256.fullmatch(
        expected_inventory_sha256
    ):
        raise CutoverGuardError("expected inventory SHA-256 must be 64 lowercase hex characters")
    if not hmac.compare_digest(inventory.inventory_sha256, expected_inventory_sha256):
        raise CutoverGuardError("inventory SHA-256 does not match the approved inventory")

    if isinstance(stopped_writer_manifest, Mapping):
        writers = stopped_writer_manifest.get("writers")
    else:
        writers = stopped_writer_manifest
    if not isinstance(writers, (list, tuple)):
        raise CutoverGuardError("stopped-writer manifest requires a writers list")

    seen_categories: set[str] = set()
    seen_instances: set[tuple[str, str]] = set()
    running: list[str] = []
    for writer in writers:
        if not isinstance(writer, Mapping):
            raise CutoverGuardError("each stopped-writer entry must be an object")
        category = _required_stable_text(writer.get("category"), "writer category")
        instance_id = _required_stable_text(writer.get("instance_id"), "writer instance_id")
        identity = (category, instance_id)
        if identity in seen_instances:
            raise CutoverGuardError(f"duplicate writer instance: {category}/{instance_id}")
        seen_instances.add(identity)
        seen_categories.add(category)
        _parse_writer_timestamp(writer.get("checked_at"))
        evidence = writer.get("evidence")
        if not evidence or not isinstance(evidence, (str, Mapping)):
            raise CutoverGuardError(f"writer {category}/{instance_id} requires evidence")
        if writer.get("stopped") is not True:
            running.append(f"{category}/{instance_id}")

    missing = sorted(set(KNOWN_WRITER_CATEGORIES) - seen_categories)
    if missing:
        raise CutoverGuardError("missing writer categories: " + ", ".join(missing))
    if running:
        raise CutoverGuardError("writer instances still running: " + ", ".join(running))
    return True


def verify_expected_customer_table_state(db: Session) -> bool:
    """Verify only the approved new/rebuilt and retired-only physical table names."""
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
    return True
