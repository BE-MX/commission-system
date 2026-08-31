import hashlib
import hmac
import importlib.util
import inspect
import json
import copy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects.mysql import DECIMAL as MYSQL_DECIMAL
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- registers string FK targets for Agent DDL
import app.customer.cutover_service as cutover_service
from app.agent_runtime.event_service import content_hash as agent_content_hash
from app.agent_runtime.models import (
    AgentArtifact,
    AgentEvent,
    AgentProfile,
    AgentRun,
    AgentSession,
)
from app.core.database import Base
from app.customer.models import (
    ACQUISITION_WORKFLOW_TABLES as ORM_ACQUISITION_WORKFLOW_TABLES,
    CORE_TABLES as ORM_CORE_TABLES,
    CUSTOMER_WORKFLOW_TABLES as ORM_CUSTOMER_WORKFLOW_TABLES,
    CustomerAccount,
    CustomerSuppressionRegistry,
)
from app.customer.cutover_service import (
    AGENT_CONTROL_TABLES,
    KNOWN_WRITER_CATEGORIES,
    NEW_CUSTOMER_TABLES,
    REBUILT_CUSTOMER_WORKFLOW_TABLES,
    REBUILT_WORKFLOW_COLUMNS,
    REQUIRED_LEGACY_TABLES,
    RETIRED_CUSTOMER_BUSINESS_TABLES,
    CutoverGuardError,
    CUTOVER_EVIDENCE_ROOT,
    build_inventory,
    build_suppression_manifest,
    canonical_json_bytes,
    compare_physical_schema_signature,
    expected_customer_schema_sha256,
    migration_preflight,
    normalize_physical_schema_signature,
    read_maintenance_fence_evidence,
    resolve_agent_history_closure,
    snapshot_unrelated_agent_rows,
    validate_suppression_manifest,
    validate_customer_physical_schema_contract,
    verify_ready,
    verify_expected_customer_table_state,
    verify_frozen_business_ids_removed,
    verify_agent_history_removed,
    verify_unrelated_unchanged,
)


BEIJING = ZoneInfo("Asia/Shanghai")
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/customer_domain_cutover.py"
SCHEMA_RESOURCE_PATH = (
    REPO_ROOT
    / "backend/alembic/versions/126_unified_customer_domain_schema.json"
)
SUPPRESSION_HMAC_KEY = b"cutover-test-hmac-key-32-bytes!!"
PREFLIGHT_REPORT_SHA256 = "a" * 64
READY_CHECKED_AT = datetime(2026, 8, 30, 9, 0, tzinfo=BEIJING)


def _target_profile_policy_entry(snapshot):
    policy_json = {
        "schema_version": "target_profile_policy_v1",
        "thresholds": {
            "research_threshold": 70,
            "qualification_threshold": 80,
            "tier_1_min_score": 90,
            "tier_2_min_score": 75,
            "tier_3_min_score": 60,
        },
        "weights": {"industry_fit": 0.6, "country_fit": 0.4},
        "research_rules": {
            "minimum_independent_sources": 2,
            "evidence_freshness_days": 90,
            "auto_research_enabled": True,
            "gate_required": True,
        },
        "claim_rules": {
            "cooldown_days": 30,
            "requires_qualification": True,
            "per_user_quota": 20,
            "per_team_quota": 100,
            "block_identity_conflict": True,
            "block_do_not_contact": True,
        },
    }
    applied_at = READY_CHECKED_AT.isoformat()
    entry = {
        "profile_id": snapshot["id"],
        "expected_profile_snapshot": snapshot,
        "expected_profile_snapshot_hash": hashlib.sha256(
            canonical_json_bytes(snapshot)
        ).hexdigest(),
        "policy_version": "policy-2026-08-30-1",
        "policy_json": policy_json,
        "last_improvement_artifact_id": None,
        "policy_applied_at": applied_at,
    }
    complete_snapshot = {
        "schema_version": "target_profile_policy_snapshot_v1",
        "profile": snapshot,
        "policy_version": entry["policy_version"],
        "policy_json": policy_json,
        "last_improvement_artifact_id": None,
        "policy_applied_at": applied_at,
    }
    entry["policy_snapshot_hash"] = hashlib.sha256(
        canonical_json_bytes(complete_snapshot)
    ).hexdigest()
    entry["improvement_approval"] = None
    return entry


def _target_profile_policy_artifact(entries=(), *, confirmed_empty=False):
    payload = {
        "schema_version": 1,
        "artifact_type": "target_profile_policy_backfill",
        "migration_revision": "126",
        "approved_at": READY_CHECKED_AT.isoformat(),
        "confirmed_empty": confirmed_empty,
        "profiles": list(entries),
    }
    return {
        **payload,
        "artifact_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _rehash_target_profile_policy_entry(entry):
    refreshed = copy.deepcopy(entry)
    complete_snapshot = {
        "schema_version": "target_profile_policy_snapshot_v1",
        "profile": refreshed["expected_profile_snapshot"],
        "policy_version": refreshed["policy_version"],
        "policy_json": refreshed["policy_json"],
        "last_improvement_artifact_id": refreshed[
            "last_improvement_artifact_id"
        ],
        "policy_applied_at": refreshed["policy_applied_at"],
    }
    refreshed["policy_snapshot_hash"] = hashlib.sha256(
        canonical_json_bytes(complete_snapshot)
    ).hexdigest()
    return refreshed


def _target_profile_physical_contract_sha256():
    resource = json.loads(SCHEMA_RESOURCE_PATH.read_text(encoding="utf-8"))
    return resource["target_profile_physical_contract"]["contract_sha256"]


def _legacy_target_profile_table() -> Table:
    """Build the exact pre-126 target-profile table used by cutover fixtures."""
    resource = json.loads(SCHEMA_RESOURCE_PATH.read_text(encoding="utf-8"))
    before = resource["target_profile_physical_contract"]["before"]
    comments = {column["name"]: column["comment"] for column in before["columns"]}
    metadata = MetaData()
    table = Table(
        "ark_sales_target_profiles",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True, comment=comments["id"]),
        Column("profile_key", String(64), nullable=False, comment=comments["profile_key"]),
        Column("company_name", String(255), nullable=False, comment=comments["company_name"]),
        Column("company_website", String(512), nullable=True, comment=comments["company_website"]),
        Column("products", JSON, nullable=False, comment=comments["products"]),
        Column("advantages", JSON, nullable=False, comment=comments["advantages"]),
        Column("target_countries", JSON, nullable=False, comment=comments["target_countries"]),
        Column("target_industries", JSON, nullable=False, comment=comments["target_industries"]),
        Column("target_roles", JSON, nullable=False, comment=comments["target_roles"]),
        Column("exclusions", JSON, nullable=False, comment=comments["exclusions"]),
        Column("default_language", String(16), nullable=False, comment=comments["default_language"]),
        Column("status", String(16), nullable=False, comment=comments["status"]),
        Column("created_by", Integer, nullable=True, comment=comments["created_by"]),
        Column("updated_by", Integer, nullable=True, comment=comments["updated_by"]),
        Column("created_at", DateTime, nullable=False, comment=comments["created_at"]),
        Column("updated_at", DateTime, nullable=False, comment=comments["updated_at"]),
        Column("deleted_at", DateTime, nullable=True, comment=comments["deleted_at"]),
        UniqueConstraint(
            "profile_key",
            name="uq_ark_sales_target_profiles_profile_key",
        ),
        comment=before["table_comment"],
    )
    Index("idx_sales_profile_status", table.c.status)
    assert tuple(table.c.keys()) == tuple(
        column["name"] for column in before["columns"]
    )
    return table


def _create_legacy_target_profile_table(engine) -> None:
    _legacy_target_profile_table().create(engine)


def _insert_legacy_target_profile(db: Session, **overrides) -> None:
    row = {
        "id": 7,
        "profile_key": "profile-seven",
        "company_name": "Ark Hair",
        "company_website": None,
        "products": ["wigs"],
        "advantages": ["quality"],
        "target_countries": ["US"],
        "target_industries": ["beauty"],
        "target_roles": ["buyer"],
        "exclusions": [],
        "default_language": "en",
        "status": "active",
        "created_by": None,
        "updated_by": None,
        "created_at": datetime(2026, 8, 1, 9, 0),
        "updated_at": datetime(2026, 8, 2, 9, 0),
        "deleted_at": None,
    }
    row.update(overrides)
    db.execute(_legacy_target_profile_table().insert(), row)


def _suppression_row(**overrides):
    row = {
        "identifier_type": "email",
        "value": " Alice@Example.COM ",
        "source_system": "provider",
        "source_account_key": "provider-account-01",
        "scope_type": "global",
        "scope_ref_id": None,
        "reason_code": "hard_bounce",
        "reason_text": None,
        "source_ref_type": "provider_event",
        "source_ref_id": "event-1",
        "status": "active",
        "mapping_status": "unmapped",
        "mapped_customer_id": None,
        "mapped_contact_point_id": None,
        "effective_at": datetime(2026, 8, 30, 9, 0, tzinfo=BEIJING),
        "revoked_by": None,
        "revoked_at": None,
        "created_by": None,
    }
    row.update(overrides)
    return row


def _authoritative_source_manifest(
    *,
    provider_rows=None,
    omit=None,
    approved_at=READY_CHECKED_AT,
    omit_confirmed_empty=None,
    confirmed_empty_overrides=None,
):
    rows_by_kind = {
        "okki": [],
        "alibaba": [],
        "provider": list(provider_rows or []),
    }
    sources = []
    for source_kind, rows in rows_by_kind.items():
        if source_kind == omit:
            continue
        artifact_rows = []
        for original in rows:
            row = dict(original)
            for field_name in ("effective_at", "revoked_at"):
                if isinstance(row.get(field_name), datetime):
                    row[field_name] = row[field_name].isoformat()
            artifact_rows.append(row)
        artifact_rows.sort(key=canonical_json_bytes)
        artifact = {
            "schema_version": 1,
            "source_kind": source_kind,
            "source_namespace": source_kind,
            "source_account_key": f"{source_kind}-account-01",
            "exported_at": approved_at.isoformat(),
            "approved_at": approved_at.isoformat(),
            "rows": artifact_rows,
        }
        if source_kind != omit_confirmed_empty:
            artifact["confirmed_empty"] = (confirmed_empty_overrides or {}).get(
                source_kind, not artifact_rows
            )
        artifact_bytes = canonical_json_bytes(artifact) + b"\n"
        artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
        relative_path = Path("pytest-suppressions") / f"{source_kind}-{artifact_hash}.json"
        artifact_path = CUTOVER_EVIDENCE_ROOT / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if not artifact_path.exists():
            artifact_path.write_bytes(artifact_bytes)
        sources.append({"artifact_path": relative_path.as_posix()})
    return {"sources": sources}


def _build_suppression(
    db,
    inventory,
    rows,
    *,
    key=SUPPRESSION_HMAC_KEY,
    preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
):
    return build_suppression_manifest(
        db,
        _authoritative_source_manifest(provider_rows=rows),
        key,
        "v1",
        inventory_sha256=inventory.inventory_sha256,
        preflight_report_sha256=preflight_report_sha256,
        now=READY_CHECKED_AT + timedelta(minutes=1),
    )


def _create_cutover_db():
    engine = create_engine("sqlite:///:memory:")
    statements = (
        "CREATE TABLE ark_sales_search_jobs (id INTEGER PRIMARY KEY, name TEXT)",
        "CREATE TABLE ark_customer_profiles (id INTEGER PRIMARY KEY, profile TEXT)",
        "CREATE TABLE ark_customer_actions (id INTEGER PRIMARY KEY, action TEXT)",
    )
    old_rows = (
        "INSERT INTO ark_sales_search_jobs VALUES (7, 'job-seven')",
        "INSERT INTO ark_customer_profiles VALUES (12, 'profile-twelve')",
        "INSERT INTO ark_customer_actions VALUES (9, 'block')",
    )
    with engine.begin() as connection:
        for statement in statements + old_rows:
            connection.execute(text(statement))
        for table_name in REQUIRED_LEGACY_TABLES:
            if table_name not in {
                "ark_sales_search_jobs",
                "ark_customer_profiles",
                "ark_customer_actions",
            }:
                columns = "id INTEGER PRIMARY KEY"
                if table_name == "ark_sales_contacts":
                    columns += (
                        ", email_normalized TEXT, email_status TEXT, "
                        "source_provider TEXT, captured_at DATETIME"
                    )
                connection.execute(text(f"CREATE TABLE {table_name} ({columns})"))
    _create_legacy_target_profile_table(engine)
    agent_tables = [
        AgentProfile.__table__,
        AgentSession.__table__,
        AgentRun.__table__,
        AgentEvent.__table__,
        AgentArtifact.__table__,
    ]
    Base.metadata.create_all(engine, tables=agent_tables)
    with Session(engine) as db:
        db.add_all(
            [
                _agent_profile(1, "preserved-used"),
                _agent_profile(2, "preserved-unrelated"),
                _agent_session(1, 1, "search_job", "7", "seed"),
                _agent_session(2, 1, "customer", "12", "profile-seed"),
                _agent_session(3, 2, "search_job", "07", "leading-zero"),
                _agent_session(4, 2, "Search_Job", "7", "case-change"),
                _agent_session(5, 2, "customer", "7", "same-id-other-type"),
                _agent_session(20, 1, None, None, "artifact-expanded"),
            ]
        )
        db.add_all(
            [
                _agent_run(1, 1, 1, None, None, "session-seed"),
                _agent_run(2, 2, 1, None, None, "profile-session-seed"),
                _agent_run(3, 3, 2, "search_job", "07", "leading-zero"),
                _agent_run(4, 4, 2, "Search_Job", "7", "case-change"),
                _agent_run(5, 5, 2, "customer_action", "7", "same-id"),
                _agent_run(20, 20, 1, None, None, "artifact-run"),
                _agent_run(21, 20, 1, None, None, "sibling-run"),
                _agent_run(30, 3, 2, "customer_action", "9 ", "space"),
            ]
        )
        db.add_all(
            [
                _agent_event(1, 1, 1, "run-match"),
                _agent_event(2, 999, 2, "session-match"),
                _agent_event(3, 20, 20, "artifact-expansion"),
                _agent_event(4, 21, 20, "sibling-expansion"),
                _agent_event(5, 3, 3, "unrelated"),
                _agent_artifact(1, 20, "customer_action", "9", "seed"),
                _agent_artifact(2, 21, None, None, "sibling"),
                _agent_artifact(3, 3, "search_job", "07", "unrelated"),
                _agent_artifact(4, 4, "SEARCH_JOB", "7", "unrelated-case"),
            ]
        )
        db.commit()
    return engine


def _agent_profile(profile_id, name):
    return AgentProfile(
        id=profile_id,
        profile_key=f"profile-{profile_id}",
        version=1,
        name=name,
        runtime="native",
        mode="scheduled",
        model_preset="cutover-test",
        system_prompt="test",
        prompt_hash=f"prompt-{profile_id}",
        skill_manifest=[],
        tool_allowlist=[],
        limits_json={},
        policy_json={},
        output_schema={},
        status="active",
    )


def _agent_session(session_id, profile_id, context_type, context_id, title):
    return AgentSession(
        id=session_id,
        owner_user_id=1,
        profile_id=profile_id,
        title=title,
        context_type=context_type,
        context_id=context_id,
    )


def _agent_run(run_id, session_id, profile_id, ref_type, ref_id, label):
    return AgentRun(
        id=run_id,
        session_id=session_id,
        profile_id=profile_id,
        owner_user_id=1,
        idempotency_key=f"run-{run_id}",
        trigger_type="manual",
        source_runtime="native",
        mode="scheduled",
        business_ref_type=ref_type,
        business_ref_id=ref_id,
        input_json={"label": label},
        context_snapshot={},
    )


def _agent_event(event_id, run_id, session_id, label):
    return AgentEvent(
        id=event_id,
        run_id=run_id,
        session_id=session_id,
        sequence_no=event_id,
        event_id=f"event-{event_id}",
        event_type="test",
        actor_type="system",
        payload_json={"label": label},
        source_event_ids=[],
        payload_sha256=f"payload-{event_id}",
    )


def _agent_artifact(artifact_id, run_id, ref_type, ref_id, label):
    return AgentArtifact(
        id=artifact_id,
        run_id=run_id,
        artifact_type="test",
        content_json={"label": label},
        evidence_json=[],
        content_sha256=f"content-{artifact_id}",
        validation_errors=[],
        business_ref_type=ref_type,
        business_ref_id=ref_id,
    )


def _writer_manifest(
    inventory_sha256,
    *,
    omitted=None,
    running=None,
    extra_writer=None,
    checked_at=READY_CHECKED_AT,
    preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
    weak_evidence=False,
    active_transactions=0,
    inventory_approved_at=READY_CHECKED_AT,
):
    writer_principals = ["ark_api@%", "ark_worker@10.%"]
    instance_inventory = [
        {
            "category": category,
            "instance_id": f"{category}-01",
            "db_principal": (
                writer_principals[0]
                if category == "local_api"
                else writer_principals[1]
            ),
        }
        for category in KNOWN_WRITER_CATEGORIES
    ]
    writers = [
            {
                "category": category,
                "instance_id": f"{category}-01",
                "stopped": category != running,
                "checked_at": checked_at.isoformat(),
                "inventory_sha256": inventory_sha256,
                "preflight_report_sha256": preflight_report_sha256,
                "evidence_detail": (
                    "x"
                    if weak_evidence
                    else "independent process and queue inspection confirmed stopped"
                ),
            }
            for category in KNOWN_WRITER_CATEGORIES
            if category != omitted
        ]
    if extra_writer:
        extra_writer = dict(extra_writer)
        if isinstance(extra_writer.get("checked_at"), datetime):
            extra_writer["checked_at"] = extra_writer["checked_at"].isoformat()
        writers.append(extra_writer)
    approval_payload = {
        "schema_version": 1,
        "artifact_kind": "writer_instance_inventory",
        "instances": instance_inventory,
        "approved_at": inventory_approved_at.isoformat(),
        "approved_by": "cutover-approver",
        "approval_detail": "approved deployment inventory exported from independent control plane",
        "writer_principals": writer_principals,
        "inventory_sha256": inventory_sha256,
        "preflight_report_sha256": preflight_report_sha256,
    }
    def write_artifact(label, payload):
        raw = canonical_json_bytes(payload) + b"\n"
        digest = hashlib.sha256(raw).hexdigest()
        relative = Path("pytest-readiness") / f"{label}-{digest}.json"
        path = CUTOVER_EVIDENCE_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
        return relative.as_posix(), digest

    inventory_path, inventory_artifact_sha256 = write_artifact(
        "instance-inventory", approval_payload
    )
    for writer in writers:
        writer["instance_inventory_artifact_sha256"] = (
            inventory_artifact_sha256
        )
    privilege_evidence = _writer_privilege_evidence(
        inventory_sha256=inventory_sha256,
        preflight_report_sha256=preflight_report_sha256,
        instance_inventory_artifact_sha256=inventory_artifact_sha256,
        checked_at=checked_at,
    )
    privilege_path, privilege_artifact_sha256 = write_artifact(
        "writer-privilege-revocation", privilege_evidence
    )
    writer_paths = [write_artifact("writer-stop", writer)[0] for writer in writers]
    transaction_payload = {
        "schema_version": 1,
        "artifact_kind": "active_transaction_snapshot",
        "count": active_transactions,
        "checked_at": checked_at.isoformat(),
        "inventory_sha256": inventory_sha256,
        "preflight_report_sha256": preflight_report_sha256,
        "instance_inventory_artifact_sha256": inventory_artifact_sha256,
        "evidence_detail": "active relevant customer writer transactions enumerated",
    }
    transaction_path, _ = write_artifact("transactions", transaction_payload)
    fence_payload = {
        "schema_version": 1,
        "artifact_kind": "maintenance_fence",
        "token": f"cutover-fence-{inventory_sha256[:20]}",
        "instance_inventory_artifact_sha256": inventory_artifact_sha256,
        "writer_privilege_revocation_artifact_sha256": privilege_artifact_sha256,
        "inventory_sha256": inventory_sha256,
        "preflight_report_sha256": preflight_report_sha256,
        "issued_at": checked_at.isoformat(),
        "expires_at": (checked_at + timedelta(minutes=4)).isoformat(),
        "approval_detail": "independent deployment controller disabled restart and write admission",
    }
    fence_path, _ = write_artifact("maintenance-fence", fence_payload)
    return {
        "instance_inventory_artifact": inventory_path,
        "writer_artifacts": writer_paths,
        "active_transaction_artifact": transaction_path,
        "maintenance_fence_artifact": fence_path,
        "writer_privilege_revocation_artifact": privilege_path,
    }


def _writer_privilege_evidence(
    *,
    checked_at=READY_CHECKED_AT,
    inventory_sha256="b" * 64,
    preflight_report_sha256="c" * 64,
    instance_inventory_artifact_sha256="d" * 64,
):
    snapshot = {
        "ark_api@%": ["USAGE"],
        "ark_worker@10.%": ["USAGE"],
    }
    payload = {
        "schema_version": 1,
        "artifact_kind": "writer_privilege_revocation",
        "migration_principal": "ark_migration@localhost",
        "writer_principals": sorted(snapshot),
        "privilege_snapshot": snapshot,
        "checked_at": checked_at.isoformat(),
        "inventory_sha256": inventory_sha256,
        "preflight_report_sha256": preflight_report_sha256,
        "instance_inventory_artifact_sha256": (
            instance_inventory_artifact_sha256
        ),
        "evidence_detail": "independent DBA privilege revocation and grant inspection",
    }
    return {**payload, "evidence_sha256": hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()}


def _ddl_proof_for_contract(
    contract,
    *,
    started_at=READY_CHECKED_AT + timedelta(minutes=1),
    completed_at=READY_CHECKED_AT + timedelta(minutes=2),
):
    proof = {
        field: contract[field]
        for field in (
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
            "contract_sha256",
            "contract_path",
            "ddl_proof_path",
            "ddl_proof_binding_sha256",
        )
    }
    proof.update(
        {
            "migration_revision": "126",
            "schema_signature_sha256": contract[
                "physical_schema_contract_sha256"
            ],
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "status": "ddl_verified",
        }
    )
    proof["ddl_proof_sha256"] = hashlib.sha256(
        canonical_json_bytes(proof)
    ).hexdigest()
    return proof


def _physical_schema_contract(*, omit=None):
    tables = {}
    for table_name in NEW_CUSTOMER_TABLES + REBUILT_CUSTOMER_WORKFLOW_TABLES:
        if table_name == omit:
            continue
        column_names = (
            list(ORM_CORE_TABLES[table_name].c.keys())
            if table_name in ORM_CORE_TABLES
            else sorted(REBUILT_WORKFLOW_COLUMNS[table_name])
        )
        tables[table_name] = normalize_physical_schema_signature(
            columns=[
                {
                    "name": name,
                    "type": BigInteger(),
                    "nullable": name != "id",
                    "default": None,
                    "computed": None,
                    "comment": f"approved {table_name}.{name}",
                }
                for name in column_names
            ],
            primary_key={"name": "PRIMARY", "constrained_columns": ["id"]},
            unique_constraints=[],
            indexes=[],
            foreign_keys=[],
            checks=[],
            table_comment=f"approved {table_name}",
        )
    contract = {
        "schema_version": 1,
        "migration_revision": "126",
        "tables": tables,
    }
    contract["contract_sha256"] = hashlib.sha256(
        canonical_json_bytes(contract)
    ).hexdigest()
    return contract


def _load_cutover_script():
    spec = importlib.util.spec_from_file_location("customer_domain_cutover", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_inventory_is_exact_deterministic_immutable_and_marks_missing_tables():
    engine = _create_cutover_db()
    with Session(engine) as db:
        first = build_inventory(db)
        second = build_inventory(db)

    assert tuple(entry.table_name for entry in first.tables) == (
        RETIRED_CUSTOMER_BUSINESS_TABLES + AGENT_CONTROL_TABLES
    )
    assert first == second
    assert first.inventory_sha256 == second.inventory_sha256
    assert first.table("ark_sales_search_jobs").primary_key_ids == (7,)
    assert first.table("ark_sales_search_jobs").row_count == 1
    assert first.table("ark_sales_search_result_sources").exists is False
    assert first.table("ark_sales_search_result_sources").row_count is None
    assert first.old_business_ids.search_job_ids == frozenset({7})
    assert first.old_business_ids.customer_profile_ids == frozenset({12})
    assert first.old_business_ids.customer_action_ids == frozenset({9})
    with pytest.raises(FrozenInstanceError):
        first.inventory_sha256 = "changed"


def test_inventory_fails_closed_when_required_cutover_tables_are_missing():
    engine = create_engine("sqlite:///:memory:")

    with Session(engine) as db, pytest.raises(
        CutoverGuardError, match="required cutover tables are missing"
    ):
        build_inventory(db)


def test_inventory_content_hash_changes_for_same_ids_and_counts():
    engine = _create_cutover_db()
    with Session(engine) as db:
        before = build_inventory(db)
        db.execute(text("UPDATE ark_sales_search_jobs SET name='changed' WHERE id=7"))
        after = build_inventory(db)

    before_entry = before.table("ark_sales_search_jobs")
    after_entry = after.table("ark_sales_search_jobs")
    assert before_entry.primary_key_ids == after_entry.primary_key_ids == (7,)
    assert before_entry.row_count == after_entry.row_count == 1
    assert before_entry.content_sha256 != after_entry.content_sha256
    assert before.inventory_sha256 != after.inventory_sha256


def test_inventory_hashes_rows_with_streaming_execution_options():
    engine = _create_cutover_db()
    inventory_select_options = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_connection, _cursor, statement, _params, context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "FROM ark_" in statement:
            inventory_select_options.append(context.execution_options)

    with Session(engine) as db:
        inventory = build_inventory(db)

    assert inventory.table("ark_sales_search_jobs").content_sha256
    assert inventory_select_options
    assert all(options.get("stream_results") is True for options in inventory_select_options)
    assert all(options.get("yield_per") == 500 for options in inventory_select_options)


def test_canonical_json_normalizes_decimal_and_aware_datetime_and_rejects_unknowns():
    assert canonical_json_bytes(Decimal("1.00")) == canonical_json_bytes(Decimal("1"))
    beijing_value = datetime(2026, 8, 30, 8, 0, tzinfo=BEIJING)
    utc_value = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
    assert canonical_json_bytes(beijing_value) == canonical_json_bytes(utc_value)

    with pytest.raises(CutoverGuardError, match="unsupported canonical type"):
        canonical_json_bytes(object())


def test_canonical_evidence_readers_restore_float_policy_values(tmp_path):
    policy = {
        "weights": {"industry_fit": 0.6, "country_fit": 0.4},
    }
    raw = canonical_json_bytes(policy) + b"\n"
    ordinary_path = tmp_path / "policy.json"
    ordinary_path.write_bytes(raw)

    script = _load_cutover_script()
    assert script._read_json(ordinary_path) == policy

    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    relative_path = Path("pytest-canonical") / f"policy-{artifact_sha256}.json"
    artifact_path = CUTOVER_EVIDENCE_ROOT / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(raw)
    try:
        restored, restored_sha256, restored_path = (
            cutover_service._read_canonical_artifact(relative_path.as_posix())
        )
    finally:
        artifact_path.unlink(missing_ok=True)

    assert restored == policy
    assert restored_sha256 == artifact_sha256
    assert restored_path == relative_path.as_posix()


def test_agent_closure_is_binary_exact_and_expands_artifact_to_sibling_run():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        closure = resolve_agent_history_closure(db, inventory)

    assert closure.session_ids == frozenset({1, 2, 20})
    assert closure.run_ids == frozenset({1, 2, 20, 21})
    assert closure.event_ids == frozenset({1, 2, 3, 4})
    assert closure.artifact_ids == frozenset({1, 2})
    assert 3 not in closure.session_ids
    assert 4 not in closure.session_ids
    assert 5 not in closure.run_ids
    assert 30 not in closure.run_ids


def test_agent_closure_selects_only_required_reference_columns():
    engine = _create_cutover_db()
    captured = []
    with Session(engine) as db:
        inventory = build_inventory(db)

        @event.listens_for(engine, "before_cursor_execute")
        def _capture(_connection, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                captured.append(statement.lower())

        resolve_agent_history_closure(db, inventory)

    closure_sql = "\n".join(captured)
    assert "ark_agent_sessions.id" in closure_sql
    assert "ark_agent_runs.business_ref_id" in closure_sql
    assert "ark_agent_events.session_id" in closure_sql
    assert "ark_agent_artifacts.business_ref_id" in closure_sql
    for forbidden_column in (
        "input_json",
        "context_snapshot",
        "payload_json",
        "raw_payload_cipher",
        "content_json",
        "evidence_json",
    ):
        assert forbidden_column not in closure_sql


def test_incoming_retired_fk_snapshot_rejects_new_or_changed_constraints():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text("CREATE TABLE ark_sales_search_jobs (id INTEGER PRIMARY KEY)")
        )
        connection.execute(
            text(
                "CREATE TABLE approved_integration ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, "
                "CONSTRAINT fk_approved_job FOREIGN KEY(job_id) "
                "REFERENCES ark_sales_search_jobs(id) "
                "ON UPDATE RESTRICT ON DELETE RESTRICT)"
            )
        )
    with Session(engine) as db:
        approved = cutover_service.snapshot_incoming_retired_foreign_keys(db)
        assert approved["foreign_keys"] == [
            {
                "owning_table": "approved_integration",
                "constraint_name": "fk_approved_job",
                "local_columns": ["job_id"],
                "target_table": "ark_sales_search_jobs",
                "target_columns": ["id"],
                "onupdate": "RESTRICT",
                "ondelete": "RESTRICT",
            }
        ]

        changed = copy.deepcopy(approved)
        changed["foreign_keys"][0]["ondelete"] = "CASCADE"
        changed_payload = {
            key: value for key, value in changed.items() if key != "snapshot_sha256"
        }
        changed["snapshot_sha256"] = hashlib.sha256(
            canonical_json_bytes(changed_payload)
        ).hexdigest()
        with pytest.raises(CutoverGuardError, match="incoming.*FK.*drift"):
            cutover_service.validate_incoming_retired_foreign_keys(db, changed)

        db.execute(
            text(
                "CREATE TABLE unexpected_integration ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, "
                "CONSTRAINT fk_unexpected_job FOREIGN KEY(job_id) "
                "REFERENCES ark_sales_search_jobs(id))"
            )
        )
        with pytest.raises(CutoverGuardError, match="incoming.*FK.*drift"):
            cutover_service.validate_incoming_retired_foreign_keys(db, approved)


def test_agent_projected_rows_are_lazy_and_agent_id_queries_are_bounded(monkeypatch):
    engine = _create_cutover_db()
    parameter_counts = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_connection, _cursor, statement, params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "ark_agent_" in statement:
            parameter_counts.append(len(params))

    with Session(engine) as db:
        projected = cutover_service._projected_rows(
            db,
            "ark_agent_sessions",
            ("id", "context_type", "context_id"),
        )
        assert not isinstance(projected, list)
        assert next(iter(projected))["id"] == 1
        projected.close()

        inventory = build_inventory(db)

        class _StreamingOnlyResult:
            def __init__(self, result):
                self._result = result

            def mappings(self):
                return _StreamingOnlyResult(self._result.mappings())

            def __iter__(self):
                return iter(self._result)

            def close(self):
                return self._result.close()

            def all(self):
                raise AssertionError("Agent scans must not call all()")

            def fetchall(self):
                raise AssertionError("Agent scans must not call fetchall()")

        execute = db.execute

        def _streaming_execute(*args, **kwargs):
            return _StreamingOnlyResult(execute(*args, **kwargs))

        monkeypatch.setattr(db, "execute", _streaming_execute)
        closure = resolve_agent_history_closure(db, inventory)
        large_ids = frozenset(range(10_000, 11_001))
        large_closure = replace(
            closure,
            session_ids=closure.session_ids | large_ids,
            run_ids=closure.run_ids | large_ids,
            event_ids=closure.event_ids | large_ids,
            artifact_ids=closure.artifact_ids | large_ids,
        )
        snapshot_unrelated_agent_rows(db, large_closure)
        with pytest.raises(CutoverGuardError, match="closure rows remain"):
            verify_agent_history_removed(db, large_closure)

    assert cutover_service.AGENT_ID_QUERY_CHUNK_SIZE == 200
    assert max(parameter_counts, default=0) <= cutover_service.AGENT_ID_QUERY_CHUNK_SIZE


def test_unrelated_snapshot_preserves_all_profiles_and_detects_content_change():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        closure = resolve_agent_history_closure(db, inventory)
        before = snapshot_unrelated_agent_rows(db, closure)
        unchanged = snapshot_unrelated_agent_rows(db, closure)
        assert verify_unrelated_unchanged(before, unchanged) is True

        db.execute(
            text(
                "UPDATE ark_agent_events "
                "SET payload_json='{\"label\":\"mutated\"}' WHERE id=5"
            )
        )
        after = snapshot_unrelated_agent_rows(db, closure)

    assert before.table("ark_agent_profiles").primary_key_ids == (1, 2)
    assert before.table("ark_agent_sessions").primary_key_ids == (3, 4, 5)
    assert before.table("ark_agent_runs").primary_key_ids == (3, 4, 5, 30)
    assert before.table("ark_agent_events").primary_key_ids == (5,)
    assert before.table("ark_agent_artifacts").primary_key_ids == (3, 4)
    with pytest.raises(CutoverGuardError, match="ark_agent_events"):
        verify_unrelated_unchanged(before, after)


def test_agent_snapshot_and_removed_id_checks_never_use_resident_ordered_rows():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        closure = resolve_agent_history_closure(db, inventory)
        assert not hasattr(cutover_service, "_ordered_rows")
        snapshot = snapshot_unrelated_agent_rows(db, closure)
        assert snapshot.table("ark_agent_profiles").row_count == 2
        with pytest.raises(CutoverGuardError, match="closure rows remain"):
            verify_agent_history_removed(db, closure)


def test_verify_after_requires_every_exact_agent_closure_row_to_be_absent():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        closure = resolve_agent_history_closure(db, inventory)
        with pytest.raises(CutoverGuardError, match="closure rows remain"):
            verify_agent_history_removed(db, closure)

        for table_name, ids in (
            ("ark_agent_artifacts", closure.artifact_ids),
            ("ark_agent_events", closure.event_ids),
            ("ark_agent_runs", closure.run_ids),
            ("ark_agent_sessions", closure.session_ids),
        ):
            placeholders = ", ".join(str(value) for value in sorted(ids))
            db.execute(text(f"DELETE FROM {table_name} WHERE id IN ({placeholders})"))
        assert verify_agent_history_removed(db, closure) is True


def test_verify_after_requires_all_frozen_business_ids_removed():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        with pytest.raises(CutoverGuardError, match="frozen retired business rows remain"):
            verify_frozen_business_ids_removed(db, inventory)
        db.execute(text("DELETE FROM ark_sales_search_jobs WHERE id=7"))
        db.execute(text("DROP TABLE ark_customer_profiles"))
        db.execute(text("DELETE FROM ark_customer_actions WHERE id=9"))
        assert verify_frozen_business_ids_removed(db, inventory) is True


@pytest.mark.parametrize("table_name", RETIRED_CUSTOMER_BUSINESS_TABLES)
def test_verify_after_rejects_a_surviving_frozen_row_from_every_business_table(
    table_name,
):
    engine = _create_cutover_db()
    seeded_ids = {
        "ark_sales_search_jobs": 7,
        "ark_customer_profiles": 12,
        "ark_customer_actions": 9,
    }
    frozen_id = seeded_ids.get(table_name, 9000)
    with engine.begin() as connection:
        if table_name == "ark_sales_search_result_sources":
            connection.execute(
                text(
                    "CREATE TABLE ark_sales_search_result_sources "
                    "(id INTEGER PRIMARY KEY)"
                )
            )
        if table_name not in seeded_ids:
            connection.execute(
                text(f"INSERT INTO {table_name} (id) VALUES (:frozen_id)"),
                {"frozen_id": frozen_id},
            )
    with Session(engine) as db:
        inventory = build_inventory(db)
        for seeded_table, seeded_id in seeded_ids.items():
            if seeded_table != table_name:
                db.execute(
                    text(f"DELETE FROM {seeded_table} WHERE id=:seeded_id"),
                    {"seeded_id": seeded_id},
                )
        with pytest.raises(CutoverGuardError, match=table_name):
            verify_frozen_business_ids_removed(db, inventory)


def test_authoritative_suppression_export_matches_registry_replay_contract():
    engine = _create_cutover_db()
    source_manifest = _authoritative_source_manifest(
        provider_rows=[_suppression_row()]
    )
    with Session(engine) as db:
        inventory = build_inventory(db)
        manifest = build_suppression_manifest(
            db,
            source_manifest,
            SUPPRESSION_HMAC_KEY,
            "v3",
            inventory_sha256=inventory.inventory_sha256,
            preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )

    replay = manifest.entries[0].to_dict()
    target_columns = set(CustomerSuppressionRegistry.__table__.c.keys())
    generated_or_database_fields = {
        "id",
        "active_suppression_key",
        "created_at",
        "updated_at",
    }
    assert set(replay) == target_columns - generated_or_database_fields
    assert replay["identifier_type"] == "email"
    assert replay["normalized_value_hmac"] == hmac.new(
        SUPPRESSION_HMAC_KEY,
        b"alice@example.com",
        hashlib.sha256,
    ).hexdigest()
    assert replay["hmac_key_version"] == "v3"
    assert replay["mapping_status"] == "unmapped"
    assert replay["suppression_fingerprint"]
    assert manifest.inventory_sha256 == inventory.inventory_sha256
    assert manifest.preflight_report_sha256 == PREFLIGHT_REPORT_SHA256
    assert {evidence.source_kind for evidence in manifest.source_evidence} == {
        "ark_database",
        "okki",
        "alibaba",
        "provider",
    }
    serialized = json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True)
    assert "Alice@Example.COM" not in serialized
    assert "alice@example.com" not in serialized
    assert '"value"' not in serialized


def test_suppression_export_reconciles_every_required_authoritative_source():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        with pytest.raises(CutoverGuardError, match="authoritative source kinds"):
            build_suppression_manifest(
                db,
                _authoritative_source_manifest(omit="alibaba"),
                SUPPRESSION_HMAC_KEY,
                "v1",
                inventory_sha256=inventory.inventory_sha256,
                preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )
        missing_artifact = _authoritative_source_manifest()
        missing_artifact["sources"][-1] = {
            "artifact_path": "pytest-suppressions/does-not-exist.json"
        }
        with pytest.raises(CutoverGuardError, match="artifact is missing"):
            build_suppression_manifest(
                db,
                missing_artifact,
                SUPPRESSION_HMAC_KEY,
                "v1",
                inventory_sha256=inventory.inventory_sha256,
                preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )


def test_suppression_export_accepts_explicit_beijing_timestamps_from_json():
    engine = _create_cutover_db()
    source_manifest = _authoritative_source_manifest(
        provider_rows=[_suppression_row()]
    )
    with Session(engine) as db:
        inventory = build_inventory(db)
        manifest = build_suppression_manifest(
            db,
            source_manifest,
            SUPPRESSION_HMAC_KEY,
            "v1",
            inventory_sha256=inventory.inventory_sha256,
            preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )
    assert manifest.entries[0].effective_at == "2026-08-30T09:00:00+08:00"


def test_suppression_export_reads_authoritative_legacy_invalid_addresses():
    engine = _create_cutover_db()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ark_sales_contacts "
                "(id, email_normalized, email_status, source_provider, captured_at) "
                "VALUES (81, 'Legacy@Example.COM', 'invalid', 'validator', "
                "'2026-08-30 08:15:00')"
            )
        )
    with Session(engine) as db:
        inventory = build_inventory(db)
        manifest = _build_suppression(db, inventory, [])
    assert len(manifest.entries) == 1
    assert manifest.entries[0].source_system == "ark"
    assert manifest.entries[0].reason_code == "invalid_address"
    assert manifest.entries[0].normalized_value_hmac == hmac.new(
        SUPPRESSION_HMAC_KEY, b"legacy@example.com", hashlib.sha256
    ).hexdigest()


@pytest.mark.parametrize(
    ("approved_at", "message"),
    [
        (READY_CHECKED_AT - timedelta(minutes=6), "stale"),
        (READY_CHECKED_AT + timedelta(minutes=2), "future"),
    ],
)
def test_suppression_export_rejects_stale_or_future_approval_before_accepting_empty_dnc_evidence(
    approved_at, message
):
    engine = _create_cutover_db()
    source_manifest = _authoritative_source_manifest(approved_at=approved_at)
    with Session(engine) as db:
        inventory = build_inventory(db)
        with pytest.raises(CutoverGuardError, match=message):
            build_suppression_manifest(
                db,
                source_manifest,
                SUPPRESSION_HMAC_KEY,
                "v1",
                inventory_sha256=inventory.inventory_sha256,
                preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )

def test_suppression_manifest_contains_only_hmac_and_preserves_ambiguous_rows():
    engine = _create_cutover_db()
    rows = [
        _suppression_row(mapping_status="mapped", mapped_customer_id=42),
        _suppression_row(
            identifier_type="domain",
            value="EXAMPLE.ORG.",
            reason_code="manual_block",
            source_ref_id="block-7",
            mapping_status="ambiguous",
            stable_match_candidates=[101, 102],
        ),
    ]
    with Session(engine) as db:
        inventory = build_inventory(db)
        manifest = _build_suppression(db, inventory, rows)
    serialized = json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True)
    expected = hmac.new(
        SUPPRESSION_HMAC_KEY,
        b"alice@example.com",
        hashlib.sha256,
    ).hexdigest()

    assert len(manifest.entries) == 2
    assert expected in {entry.normalized_value_hmac for entry in manifest.entries}
    assert {entry.mapping_status for entry in manifest.entries} == {"unmapped", "ambiguous"}
    assert all(entry.mapped_customer_id is None for entry in manifest.entries)
    assert all(entry.mapped_contact_point_id is None for entry in manifest.entries)
    assert "Alice@Example.COM" not in serialized
    assert "alice@example.com" not in serialized
    assert SUPPRESSION_HMAC_KEY.decode("ascii") not in serialized
    assert '"value"' not in serialized


def test_suppression_empty_requires_evidence_and_hash_is_order_independent():
    engine = _create_cutover_db()
    rows = [
        _suppression_row(identifier_type="phone", value="+86 138-0013-8000"),
        _suppression_row(
            identifier_type="buyer_id",
            value="Message-ID-CaseSensitive",
            source_ref_id="event-2",
        ),
    ]
    with Session(engine) as db:
        inventory = build_inventory(db)
        empty = _build_suppression(db, inventory, [])
        first = _build_suppression(db, inventory, rows)
        second = _build_suppression(db, inventory, list(reversed(rows)))
    assert empty.entries == ()
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.entries == second.entries


def test_suppression_rejects_low_entropy_hmac_keys():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        with pytest.raises(CutoverGuardError, match="at least 32 bytes"):
            _build_suppression(db, inventory, [], key=b"short")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason_code", "soft_bounce"),
        ("effective_at", datetime(2026, 8, 29, 12, 0)),
        ("source_ref_type", ""),
    ],
)
def test_suppression_rejects_unknown_reason_naive_time_and_missing_source(field, value):
    engine = _create_cutover_db()
    candidate = _suppression_row()
    candidate[field] = value
    with Session(engine) as db:
        inventory = build_inventory(db)
        with pytest.raises(CutoverGuardError):
            _build_suppression(db, inventory, [candidate])


def test_suppression_rejects_raw_identity_copied_into_source_metadata():
    engine = _create_cutover_db()
    candidate = _suppression_row(source_ref_id="email:alice@example.com")
    with Session(engine) as db:
        inventory = build_inventory(db)
        with pytest.raises(CutoverGuardError, match="raw identifier"):
            _build_suppression(db, inventory, [candidate])


def test_suppression_revalidation_reads_authoritative_artifact_bytes():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        raw = _build_suppression(db, inventory, [_suppression_row()]).to_dict()
        assert validate_suppression_manifest(
            db, raw, SUPPRESSION_HMAC_KEY, now=READY_CHECKED_AT + timedelta(minutes=1)
        ) is True
        provider = next(
            item for item in raw["source_evidence"] if item["source_kind"] == "provider"
        )
        artifact_path = CUTOVER_EVIDENCE_ROOT / provider["artifact_path"]
        original = artifact_path.read_bytes()
        try:
            artifact_path.write_bytes(original + b" ")
            with pytest.raises(CutoverGuardError, match="canonical JSON"):
                validate_suppression_manifest(
                    db,
                    raw,
                    SUPPRESSION_HMAC_KEY,
                    now=READY_CHECKED_AT + timedelta(minutes=1),
                )
        finally:
            artifact_path.write_bytes(original)


def test_self_hashed_empty_suppression_and_repeated_key_fail_closed():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        empty = {
            "schema_version": 1,
            "key_version": "v1",
            "inventory_sha256": inventory.inventory_sha256,
            "preflight_report_sha256": PREFLIGHT_REPORT_SHA256,
            "source_evidence": [],
            "entries": [],
        }
        empty["manifest_sha256"] = hashlib.sha256(
            canonical_json_bytes(empty)
        ).hexdigest()
        with pytest.raises(CutoverGuardError, match="cannot be empty"):
            validate_suppression_manifest(
                db, empty, SUPPRESSION_HMAC_KEY, now=READY_CHECKED_AT
            )
        with pytest.raises(CutoverGuardError, match="HMAC key"):
            _build_suppression(db, inventory, [], key=b"x" * 64)


@pytest.mark.parametrize(
    "source_manifest",
    [
        _authoritative_source_manifest(omit_confirmed_empty="okki"),
        _authoritative_source_manifest(
            confirmed_empty_overrides={"okki": False}
        ),
        _authoritative_source_manifest(
            provider_rows=[_suppression_row()],
            confirmed_empty_overrides={"provider": True},
        ),
    ],
)
def test_suppression_empty_confirmation_must_match_artifact_rows(source_manifest):
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        with pytest.raises(CutoverGuardError, match="confirmed_empty"):
            build_suppression_manifest(
                db,
                source_manifest,
                SUPPRESSION_HMAC_KEY,
                "v1",
                inventory_sha256=inventory.inventory_sha256,
                preflight_report_sha256=PREFLIGHT_REPORT_SHA256,
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )


def test_verify_ready_fails_on_hash_mismatch_missing_writer_and_running_writer():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)

    manifest = _writer_manifest(inventory.inventory_sha256)
    assert verify_ready(
        inventory,
        manifest,
        inventory.inventory_sha256,
        PREFLIGHT_REPORT_SHA256,
        now=READY_CHECKED_AT + timedelta(minutes=1),
    ) is True
    with pytest.raises(CutoverGuardError, match="inventory SHA-256"):
        verify_ready(
            inventory, manifest, "0" * 64, PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )
    with pytest.raises(CutoverGuardError, match="instance inventory"):
        verify_ready(
            inventory,
            _writer_manifest(
                inventory.inventory_sha256,
                omitted=KNOWN_WRITER_CATEGORIES[-1],
            ),
            inventory.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )
    with pytest.raises(CutoverGuardError, match="still running"):
        verify_ready(
            inventory,
            _writer_manifest(
                inventory.inventory_sha256,
                running=KNOWN_WRITER_CATEGORIES[0],
            ),
            inventory.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )


def test_verify_ready_requires_stopped_public_pool_batch_writer():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)

    assert "public_pool_batch" in KNOWN_WRITER_CATEGORIES
    with pytest.raises(CutoverGuardError, match="instance inventory"):
        verify_ready(
            inventory,
            _writer_manifest(inventory.inventory_sha256, omitted="public_pool_batch"),
            inventory.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )
    with pytest.raises(CutoverGuardError, match="still running"):
        verify_ready(
            inventory,
            _writer_manifest(inventory.inventory_sha256, running="public_pool_batch"),
            inventory.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )


def test_verify_ready_recomputes_inventory_content_before_trusting_supplied_hash():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
    forged = replace(inventory, inventory_sha256="0" * 64)

    with pytest.raises(CutoverGuardError, match="inventory content"):
        verify_ready(
            forged,
            _writer_manifest(forged.inventory_sha256),
            forged.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    ("manifest_change", "message"),
    [
        ({"checked_at": READY_CHECKED_AT - timedelta(minutes=6)}, "stale"),
        ({"checked_at": READY_CHECKED_AT + timedelta(minutes=2)}, "future"),
        ({"preflight_report_sha256": "d" * 64}, "preflight"),
        ({"weak_evidence": True}, "structured evidence"),
        ({"active_transactions": 1}, "active transactions"),
        (
            {"inventory_approved_at": READY_CHECKED_AT - timedelta(minutes=6)},
            "instance inventory.*stale",
        ),
        (
            {"inventory_approved_at": READY_CHECKED_AT + timedelta(minutes=2)},
            "instance inventory.*future",
        ),
    ],
)
def test_verify_ready_rejects_stale_future_weak_wrongly_bound_or_active_evidence(
    manifest_change, message
):
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
    manifest = _writer_manifest(inventory.inventory_sha256, **manifest_change)
    with pytest.raises(CutoverGuardError, match=message):
        verify_ready(
            inventory,
            manifest,
            inventory.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )


def test_verify_ready_rejects_unlisted_second_instance():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
    extra = {
        "category": "local_api",
        "instance_id": "local-api-unapproved-02",
        "stopped": True,
        "checked_at": READY_CHECKED_AT,
        "inventory_sha256": inventory.inventory_sha256,
        "preflight_report_sha256": PREFLIGHT_REPORT_SHA256,
        "evidence_detail": "independent process and queue inspection confirmed stopped",
    }
    manifest = _writer_manifest(inventory.inventory_sha256, extra_writer=extra)
    with pytest.raises(CutoverGuardError, match="instance inventory"):
        verify_ready(
            inventory,
            manifest,
            inventory.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )


def test_stale_approved_instance_inventory_cannot_omit_a_later_instance():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
    extra = {
        "category": "local_api",
        "instance_id": "local-api-started-after-stale-approval",
        "stopped": True,
        "checked_at": READY_CHECKED_AT,
        "inventory_sha256": inventory.inventory_sha256,
        "preflight_report_sha256": PREFLIGHT_REPORT_SHA256,
        "evidence_detail": "independent process and queue inspection confirmed stopped",
    }
    manifest = _writer_manifest(
        inventory.inventory_sha256,
        inventory_approved_at=READY_CHECKED_AT - timedelta(minutes=6),
        extra_writer=extra,
    )
    with pytest.raises(CutoverGuardError, match="instance inventory.*stale"):
        verify_ready(
            inventory,
            manifest,
            inventory.inventory_sha256,
            PREFLIGHT_REPORT_SHA256,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )


def test_migration_preflight_requires_short_lived_contract_lock_and_live_inventory():
    engine = _create_cutover_db()
    now = READY_CHECKED_AT
    with Session(engine) as db:
        script = _load_cutover_script()
        inventory = build_inventory(db)
        report = script.build_preflight_report(db)
        assert report["incoming_retired_foreign_keys"] == (
            cutover_service.snapshot_incoming_retired_foreign_keys(db)
        )
        report_sha256 = report["report_sha256"]
        suppression = _build_suppression(
            db,
            inventory,
            [],
            preflight_report_sha256=report_sha256,
        ).to_dict()
        writer_manifest = _writer_manifest(
            inventory.inventory_sha256,
            preflight_report_sha256=report_sha256,
        )
        fence = read_maintenance_fence_evidence(writer_manifest)
        privilege_reader = lambda _db: {
            "current_principal": "ark_migration@localhost",
            "privilege_snapshot": {
                "ark_api@%": ["USAGE"],
                "ark_worker@10.%": ["USAGE"],
            },
        }
        nonce = f"cutover-{report_sha256[:24]}"
        writer_sha256 = hashlib.sha256(
            canonical_json_bytes(writer_manifest)
        ).hexdigest()
        physical_contract = _physical_schema_contract()
        target_profile_policy_backfill = _target_profile_policy_artifact(
            confirmed_empty=True
        )
        marker = {
            "approved": True,
            "inventory_sha256": inventory.inventory_sha256,
            "preflight_report_sha256": report_sha256,
            "suppression_manifest_sha256": suppression["manifest_sha256"],
            "writer_manifest_sha256": writer_sha256,
            "writer_privilege_revocation_artifact_sha256": fence[
                "writer_privilege_revocation_artifact_sha256"
            ],
            "physical_schema_contract_sha256": physical_contract[
                "contract_sha256"
            ],
            "target_profile_physical_contract_sha256": (
                _target_profile_physical_contract_sha256()
            ),
            "target_profile_policy_backfill_sha256": (
                target_profile_policy_backfill["artifact_sha256"]
            ),
            "nonce": nonce,
            "expires_at": (now + timedelta(minutes=3)).isoformat(),
        }
        documents = {
            "preflight_report": report,
            "suppression_manifest": suppression,
            "writer_manifest": writer_manifest,
            "approved_marker": marker,
            "physical_schema_contract": physical_contract,
            "target_profile_policy_backfill": target_profile_policy_backfill,
        }
        evidence_artifacts = {}
        for label, document in documents.items():
            artifact_path = CUTOVER_EVIDENCE_ROOT / f"bound-{label}-{nonce}.json"
            artifact_bytes = canonical_json_bytes(document) + b"\n"
            if not artifact_path.exists():
                artifact_path.write_bytes(artifact_bytes)
            evidence_artifacts[label] = {
                "path": str(artifact_path),
                "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            }
        with pytest.raises(CutoverGuardError, match="migration evidence contract"):
            migration_preflight(db, None, now=now, lock_acquirer=lambda _db: True)
        contract = {
            "approved": True,
            "nonce": nonce,
            "evidence_root": str(CUTOVER_EVIDENCE_ROOT),
            "issued_at": now,
            "expires_at": now + timedelta(minutes=3),
            "inventory_sha256": inventory.inventory_sha256,
            "preflight_report_sha256": report_sha256,
            "suppression_manifest_sha256": suppression["manifest_sha256"],
            "writer_manifest_sha256": writer_sha256,
            "approved_marker_sha256": hashlib.sha256(
                canonical_json_bytes(marker)
            ).hexdigest(),
            "maintenance_fence_artifact": fence["artifact_path"],
            "maintenance_fence_artifact_sha256": fence["artifact_sha256"],
            "maintenance_fence_token": fence["token"],
            "instance_inventory_artifact_sha256": fence[
                "instance_inventory_artifact_sha256"
            ],
            "writer_privilege_revocation_artifact": fence[
                "writer_privilege_revocation_artifact"
            ],
            "writer_privilege_revocation_artifact_sha256": fence[
                "writer_privilege_revocation_artifact_sha256"
            ],
            "contract_path": str(
                CUTOVER_EVIDENCE_ROOT / f"migration-contract-{nonce}.json"
            ),
            "ddl_proof_path": f"migration-ddl-proof-{nonce}.json",
            "receipt_path": f"migration-receipt-{nonce}.json",
            "migration_revision": "126",
            "evidence_artifacts": evidence_artifacts,
            "physical_schema_contract_sha256": physical_contract[
                "contract_sha256"
            ],
            "target_profile_physical_contract_sha256": (
                _target_profile_physical_contract_sha256()
            ),
            "target_profile_policy_backfill_sha256": (
                target_profile_policy_backfill["artifact_sha256"]
            ),
        }
        contract["ddl_proof_binding_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {
                    field: contract[field]
                    for field in cutover_service.MIGRATION_DDL_PROOF_BINDING_FIELDS
                }
            )
        ).hexdigest()
        contract["contract_sha256"] = hashlib.sha256(
            canonical_json_bytes(contract)
        ).hexdigest()
        assert migration_preflight(
            db,
            contract,
            now=now,
            lock_acquirer=lambda _db: True,
            transaction_inspector=lambda _db: 0,
            fence_inspector=lambda _db, _contract: True,
            privilege_reader=privilege_reader,
        ).inventory_sha256 == inventory.inventory_sha256
        with pytest.raises(CutoverGuardError, match="lock"):
            migration_preflight(db, contract, now=now, lock_acquirer=lambda _db: False)
        with pytest.raises(CutoverGuardError, match="active write transactions"):
            migration_preflight(
                db,
                contract,
                now=now,
                lock_acquirer=lambda _db: True,
                transaction_inspector=lambda _db: 1,
                fence_inspector=lambda _db, _contract: True,
            )
        with pytest.raises(CutoverGuardError, match="maintenance fence"):
            migration_preflight(
                db,
                contract,
                now=now,
                lock_acquirer=lambda _db: True,
                transaction_inspector=lambda _db: 0,
                fence_inspector=lambda _db, _contract: False,
            )
        with pytest.raises(CutoverGuardError, match="expired"):
            migration_preflight(
                db,
                {
                    **contract,
                    "expires_at": now - timedelta(seconds=1),
                    "contract_sha256": hashlib.sha256(
                        canonical_json_bytes(
                            {
                                **{
                                    key: value
                                    for key, value in contract.items()
                                    if key != "contract_sha256"
                                },
                                "expires_at": now - timedelta(seconds=1),
                            }
                        )
                    ).hexdigest(),
                },
                now=now,
                lock_acquirer=lambda _db: True,
                transaction_inspector=lambda _db: 0,
                fence_inspector=lambda _db, _contract: True,
                privilege_reader=privilege_reader,
            )
        db.execute(text("UPDATE ark_sales_search_jobs SET name='changed' WHERE id=7"))
        with pytest.raises(CutoverGuardError, match="live inventory"):
            migration_preflight(
                db,
                contract,
                now=now,
                lock_acquirer=lambda _db: True,
                transaction_inspector=lambda _db: 0,
                fence_inspector=lambda _db, _contract: True,
                privilege_reader=privilege_reader,
            )


@pytest.mark.parametrize(
    ("live", "error"),
    (
        (
            {
                "current_principal": "ark_migration@localhost",
                "privilege_snapshot": {
                    "ark_api@%": ["INSERT", "USAGE"],
                    "ark_worker@10.%": ["USAGE"],
                },
            },
            "write privilege",
        ),
        (
            {
                "current_principal": "ark_migration@localhost",
                "privilege_snapshot": {"ark_api@%": ["USAGE"]},
            },
            "missing.*principal",
        ),
        (
            {
                "current_principal": "ark_api@%",
                "privilege_snapshot": {
                    "ark_api@%": ["USAGE"],
                    "ark_worker@10.%": ["USAGE"],
                },
            },
            "migration principal.*writer",
        ),
        (
            {
                "current_principal": "ark_migration@localhost",
                "privilege_snapshot": {
                    "ark_api@%": ["USAGE"],
                    "ark_worker@10.%": ["SELECT", "USAGE"],
                },
            },
            "snapshot.*mismatch",
        ),
    ),
)
def test_mysql_writer_privilege_gate_fails_closed_for_live_drift(live, error):
    evidence = _writer_privilege_evidence()

    with pytest.raises(CutoverGuardError, match=error):
        cutover_service.validate_mysql_writer_privilege_gate(
            object(),
            evidence,
            now=READY_CHECKED_AT,
            privilege_reader=lambda _db: live,
        )


def test_mysql_writer_privilege_gate_requires_fresh_exact_revocation_proof():
    evidence = _writer_privilege_evidence()
    live = {
        "current_principal": "ark_migration@localhost",
        "privilege_snapshot": evidence["privilege_snapshot"],
    }
    assert cutover_service.validate_mysql_writer_privilege_gate(
        object(),
        evidence,
        now=READY_CHECKED_AT,
        privilege_reader=lambda _db: live,
    ) is True

    stale = _writer_privilege_evidence(
        checked_at=(
            READY_CHECKED_AT
            - cutover_service.CUTOVER_EVIDENCE_MAX_AGE
            - timedelta(seconds=1)
        )
    )
    with pytest.raises(CutoverGuardError, match="stale"):
        cutover_service.validate_mysql_writer_privilege_gate(
            object(),
            stale,
            now=READY_CHECKED_AT,
            privilege_reader=lambda _db: live,
        )


def test_mysql_privilege_reader_uses_exact_safe_show_grants_and_sees_dynamic_grants():
    statements = []

    class _Dialect:
        name = "mysql"

    class _Bind:
        dialect = _Dialect()

    class _CurrentUser:
        def scalar_one(self):
            return "ark_migration@localhost"

    class _MandatoryRoles:
        def scalar_one(self):
            return "NONE"

    class _GrantRows:
        def __iter__(self):
            return iter(
                (
                    ("GRANT USAGE ON *.* TO 'ark_api'@'%'",),
                    (
                        "GRANT INSERT, `SYSTEM_VARIABLES_ADMIN` ON *.* "
                        "TO 'ark_api'@'%'",
                    ),
                    (
                        "GRANT UPDATE (`company_name`) ON `commission`.`customers` "
                        "TO 'ark_api'@'%'",
                    ),
                    ("GRANT 'customer_writer'@'%' TO 'ark_api'@'%'",),
                )
            )

        def close(self):
            return None

    class _RoleRows:
        def mappings(self):
            return self

        def __iter__(self):
            return iter(())

        def close(self):
            return None

    class _Db:
        def get_bind(self):
            return _Bind()

        def execute(self, statement, params=None):
            sql = str(statement)
            statements.append((sql, params))
            if sql == "SELECT CURRENT_USER()":
                return _CurrentUser()
            if sql == "SELECT @@GLOBAL.mandatory_roles":
                return _MandatoryRoles()
            if "mysql.role_edges" in sql:
                return _RoleRows()
            return _GrantRows()

    live = cutover_service._read_mysql_principal_privileges(
        _Db(), ["ark_api@%"]
    )

    assert statements == [
        ("SELECT CURRENT_USER()", None),
        ("SELECT @@GLOBAL.mandatory_roles", None),
        ("SHOW GRANTS FOR 'ark_api'@'%'", None),
        (
            "SELECT FROM_USER AS role_user, FROM_HOST AS role_host "
            "FROM mysql.role_edges WHERE TO_USER=:user AND TO_HOST=:host "
            "UNION ALL SELECT DEFAULT_ROLE_USER AS role_user, "
            "DEFAULT_ROLE_HOST AS role_host FROM mysql.default_roles "
            "WHERE USER=:user AND HOST=:host",
            {"user": "ark_api", "host": "%"},
        ),
    ]
    assert live == {
        "current_principal": "ark_migration@localhost",
        "privilege_snapshot": {
            "ark_api@%": [
                "INSERT",
                "ROLE",
                "SYSTEM VARIABLES ADMIN",
                "UPDATE",
                "USAGE",
            ]
        },
    }


def test_mysql_privilege_reader_rejects_unobservable_mandatory_roles():
    class _Dialect:
        name = "mysql"

    class _Bind:
        dialect = _Dialect()

    class _Scalar:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class _Db:
        def get_bind(self):
            return _Bind()

        def execute(self, statement, _params=None):
            if str(statement) == "SELECT CURRENT_USER()":
                return _Scalar("ark_migration@localhost")
            return _Scalar("'mandatory_writer'@'%'")

    with pytest.raises(CutoverGuardError, match="mandatory_roles"):
        cutover_service._read_mysql_principal_privileges(
            _Db(), ["ark_api@%"]
        )


@pytest.mark.parametrize(
    ("expires_at", "expected"),
    [
        (READY_CHECKED_AT.replace(tzinfo=None) + timedelta(minutes=3), True),
        (READY_CHECKED_AT.replace(tzinfo=None) - timedelta(seconds=1), False),
        (READY_CHECKED_AT.replace(tzinfo=None) + timedelta(minutes=6), False),
    ],
)
def test_mysql_fence_treats_naive_datetime_as_beijing_wall_time(
    expires_at, expected
):
    class _MappingsResult:
        def mappings(self):
            return self

        def one_or_none(self):
            return {
                "fence_token": "fence-token-20260830",
                "inventory_sha256": "a" * 64,
                "preflight_report_sha256": "b" * 64,
                "expires_at": expires_at,
                "active": 1,
            }

    class _FakeDb:
        def execute(self, *_args, **_kwargs):
            return _MappingsResult()

    contract = {
        "maintenance_fence_token": "fence-token-20260830",
        "inventory_sha256": "a" * 64,
        "preflight_report_sha256": "b" * 64,
        "expires_at": (READY_CHECKED_AT + timedelta(minutes=3)).isoformat(),
    }
    assert cutover_service._mysql_maintenance_fence_active(
        _FakeDb(), contract, now=READY_CHECKED_AT
    ) is expected


def test_read_only_postverify_fence_check_never_uses_for_update():
    expires_at = READY_CHECKED_AT.replace(tzinfo=None) + timedelta(minutes=3)
    statements = []

    class _MappingsResult:
        def mappings(self):
            return self

        def one_or_none(self):
            return {
                "fence_token": "fence-token-20260830",
                "inventory_sha256": "a" * 64,
                "preflight_report_sha256": "b" * 64,
                "expires_at": expires_at,
                "active": 1,
            }

    class _FakeDb:
        def execute(self, statement, *_args, **_kwargs):
            statements.append(str(statement))
            return _MappingsResult()

    contract = {
        "maintenance_fence_token": "fence-token-20260830",
        "inventory_sha256": "a" * 64,
        "preflight_report_sha256": "b" * 64,
        "expires_at": (READY_CHECKED_AT + timedelta(minutes=3)).isoformat(),
    }
    assert cutover_service._mysql_maintenance_fence_active(
        _FakeDb(),
        contract,
        now=READY_CHECKED_AT,
        locking=False,
    ) is True
    assert len(statements) == 1
    assert "FOR UPDATE" not in statements[0]


def test_fence_bootstrap_rejects_a_spoofed_physical_table_before_activation(
    monkeypatch,
):
    nonce = "cutover-fence-test-0001"
    contract = {
        "approved": True,
        "migration_revision": "126",
        "nonce": nonce,
        "evidence_root": str(CUTOVER_EVIDENCE_ROOT),
        "expires_at": (READY_CHECKED_AT + timedelta(minutes=3)).isoformat(),
        "maintenance_fence_artifact": "bound-fence.json",
        "maintenance_fence_artifact_sha256": "a" * 64,
        "maintenance_fence_token": "fence-token-20260830",
        "inventory_sha256": "b" * 64,
        "preflight_report_sha256": "c" * 64,
        "instance_inventory_artifact_sha256": "d" * 64,
        "suppression_manifest_sha256": "e" * 64,
        "writer_manifest_sha256": "f" * 64,
        "writer_privilege_revocation_artifact_sha256": "1" * 64,
        "approved_marker_sha256": "2" * 64,
        "physical_schema_contract_sha256": "3" * 64,
        "target_profile_physical_contract_sha256": "4" * 64,
        "target_profile_policy_backfill_sha256": "5" * 64,
        "contract_path": str(
            CUTOVER_EVIDENCE_ROOT / f"migration-contract-{nonce}.json"
        ),
        "ddl_proof_path": f"migration-ddl-proof-{nonce}.json",
        "receipt_path": f"migration-receipt-{nonce}.json",
    }
    contract["ddl_proof_binding_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {
                field: contract[field]
                for field in cutover_service.MIGRATION_DDL_PROOF_BINDING_FIELDS
            }
        )
    ).hexdigest()
    contract["contract_sha256"] = hashlib.sha256(
        canonical_json_bytes(contract)
    ).hexdigest()
    fence_document = {
        "token": contract["maintenance_fence_token"],
        "inventory_sha256": contract["inventory_sha256"],
        "preflight_report_sha256": contract["preflight_report_sha256"],
        "instance_inventory_artifact_sha256": contract[
            "instance_inventory_artifact_sha256"
        ],
        "writer_privilege_revocation_artifact_sha256": contract[
            "writer_privilege_revocation_artifact_sha256"
        ],
    }
    monkeypatch.setattr(
        cutover_service,
        "load_bound_customer_physical_schema_contract",
        lambda _contract, **_kwargs: {},
    )
    monkeypatch.setattr(
        cutover_service,
        "_read_canonical_artifact",
        lambda _descriptor: (fence_document, "a" * 64, "bound-fence.json"),
    )

    class _Dialect:
        name = "mysql"

    class _Bind:
        dialect = _Dialect()

    class _Rows:
        def mappings(self):
            return self

        def __iter__(self):
            names = {
                "fence_token": "int",  # deliberately wrong
                "inventory_sha256": "char(64)",
                "preflight_report_sha256": "char(64)",
                "instance_inventory_artifact_sha256": "char(64)",
                "expires_at": "datetime",
                "active": "tinyint(1)",
                "created_at": "datetime",
            }
            return iter(
                {
                    "COLUMN_NAME": name,
                    "COLUMN_TYPE": column_type,
                    "IS_NULLABLE": "NO",
                    "COLUMN_COMMENT": "comment",
                    "COLUMN_KEY": "PRI" if name == "fence_token" else "",
                }
                for name, column_type in names.items()
            )

    class _Existing:
        def scalar_one_or_none(self):
            return None

    class _FakeDb:
        def __init__(self):
            self.statements = []

        def get_bind(self):
            return _Bind()

        def execute(self, statement, *_args, **_kwargs):
            sql = str(statement)
            self.statements.append(sql)
            if "information_schema.COLUMNS" in sql:
                return _Rows()
            if sql.startswith("SELECT fence_token"):
                return _Existing()
            return None

    db = _FakeDb()
    with pytest.raises(CutoverGuardError, match="physical contract"):
        cutover_service.bootstrap_migration_fence(
            db,
            contract,
            now=READY_CHECKED_AT,
        )
    assert not any(statement.startswith("INSERT INTO") for statement in db.statements)


def test_verify_after_table_state_requires_all_new_tables_and_no_retired_only_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in NEW_CUSTOMER_TABLES],
    )
    Base.metadata.create_all(
        engine,
        tables=[
            *ORM_ACQUISITION_WORKFLOW_TABLES.values(),
            *ORM_CUSTOMER_WORKFLOW_TABLES.values(),
        ],
    )
    with engine.begin() as connection:
        for table_name in REBUILT_CUSTOMER_WORKFLOW_TABLES:
            if (
                table_name in ORM_ACQUISITION_WORKFLOW_TABLES
                or table_name in ORM_CUSTOMER_WORKFLOW_TABLES
            ):
                continue
            columns = ["id INTEGER PRIMARY KEY"] + [
                f"{name} TEXT"
                for name in sorted(REBUILT_WORKFLOW_COLUMNS[table_name] - {"id"})
            ]
            connection.execute(text(f"CREATE TABLE {table_name} ({', '.join(columns)})"))
    with Session(engine) as db:
        assert verify_expected_customer_table_state(db) is True
        db.execute(text("DROP TABLE ark_customer_suppression_registry"))
        with pytest.raises(CutoverGuardError, match="expected customer tables are missing"):
            verify_expected_customer_table_state(db)


@pytest.mark.parametrize(
    "category",
    [
        "type",
        "nullable_default",
        "unique",
        "index",
        "foreign_key",
        "check",
        "generated",
        "autoincrement",
        "temporal_fsp",
        "comment",
    ],
)
def test_physical_schema_signature_rejects_every_structural_category(category):
    raw = {
        "columns": [
            {
                "name": "id",
                "type": BigInteger(),
                "nullable": False,
                "default": None,
                "computed": None,
                "autoincrement": True,
                "comment": "identity",
            },
            {
                "name": "normalized",
                "type": MYSQL_DATETIME(fsp=6),
                "nullable": False,
                "default": "''",
                "computed": {"sqltext": "lower(source)", "persisted": True},
                "autoincrement": False,
                "comment": "generated value",
            },
        ],
        "primary_key": {"name": "PRIMARY", "constrained_columns": ["id"]},
        "unique_constraints": [{"name": "uq_value", "column_names": ["normalized"]}],
        "indexes": [{"name": "ix_value", "unique": False, "column_names": ["normalized"]}],
        "foreign_keys": [
            {
                "name": "fk_id",
                "constrained_columns": ["id"],
                "referred_schema": None,
                "referred_table": "parent",
                "referred_columns": ["id"],
                "options": {"ondelete": "CASCADE", "onupdate": "RESTRICT"},
            }
        ],
        "checks": [
            {
                "name": "ck_value",
                "sqltext": "id > 0",
                "dialect_options": {"mysql_enforced": True},
            }
        ],
        "table_comment": "approved table",
    }
    expected = normalize_physical_schema_signature(**raw)
    changed = copy.deepcopy(raw)
    if category == "type":
        changed["columns"][0]["type"] = Text()
    elif category == "nullable_default":
        changed["columns"][1]["nullable"] = True
        changed["columns"][1]["default"] = None
    elif category == "unique":
        changed["unique_constraints"] = []
    elif category == "index":
        changed["indexes"] = []
    elif category == "foreign_key":
        changed["foreign_keys"] = []
    elif category == "check":
        changed["checks"][0]["sqltext"] = "id >= 0"
    elif category == "generated":
        changed["columns"][1]["computed"]["sqltext"] = "upper(source)"
    elif category == "autoincrement":
        changed["columns"][0]["autoincrement"] = False
    elif category == "temporal_fsp":
        changed["columns"][1]["type"] = MYSQL_DATETIME(fsp=0)
    else:
        changed["table_comment"] = "wrong"
    actual = normalize_physical_schema_signature(**changed)
    with pytest.raises(CutoverGuardError, match="physical schema"):
        compare_physical_schema_signature(expected, actual, "synthetic_customer")


def test_mysql_physical_signature_normalizes_unique_index_and_type_aliases():
    generic_numeric = normalize_physical_schema_signature(
        columns=[
            {
                "name": "amount",
                "type": Numeric(15, 2),
                "nullable": False,
                "default": None,
                "computed": None,
                "comment": "amount",
            },
            {
                "name": "owner_id",
                "type": Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                "nullable": False,
                "default": None,
                "computed": None,
                "comment": "owner",
            },
        ],
        primary_key={"name": None, "constrained_columns": []},
        unique_constraints=[
            {
                "name": "uq_amount",
                "column_names": ["amount"],
                "duplicates_index": "uq_amount",
            }
        ],
        indexes=[
            {"name": "uq_amount", "unique": True, "column_names": ["amount"]},
            {"name": "ix_owner", "unique": False, "column_names": ["owner_id"]},
        ],
        foreign_keys=[
            {
                "name": "fk_owner",
                "constrained_columns": ["owner_id"],
                "referred_schema": None,
                "referred_table": "ark_users",
                "referred_columns": ["id"],
                "options": {},
            }
        ],
        checks=[],
        table_comment="synthetic",
    )
    reflected_mysql = normalize_physical_schema_signature(
        columns=[
            {
                "name": "amount",
                "type": MYSQL_DECIMAL(15, 2),
                "nullable": False,
                "default": None,
                "computed": None,
                "comment": "amount",
            },
            {
                "name": "owner_id",
                "type": mysql.INTEGER(unsigned=True),
                "nullable": False,
                "default": None,
                "computed": None,
                "comment": "owner",
            },
        ],
        primary_key={"name": None, "constrained_columns": []},
        unique_constraints=[
            {
                "name": "uq_amount",
                "column_names": ["amount"],
                "duplicates_index": "uq_amount",
            }
        ],
        indexes=[
            {"name": "uq_amount", "unique": True, "column_names": ["amount"]},
            {"name": "ix_owner", "unique": False, "column_names": ["owner_id"]},
        ],
        foreign_keys=[
            {
                "name": "fk_owner",
                "constrained_columns": ["owner_id"],
                "referred_schema": None,
                "referred_table": "ark_users",
                "referred_columns": ["id"],
                "options": {"ondelete": "RESTRICT", "onupdate": "NO ACTION"},
            }
        ],
        checks=[],
        table_comment="synthetic",
    )

    assert generic_numeric == reflected_mysql
    assert generic_numeric["indexes"] == (("ix_owner", False, ("owner_id",)),)


def test_mysql_physical_signature_ignores_reflected_text_collation_suffix():
    def signature(column_type):
        return normalize_physical_schema_signature(
            columns=[
                {
                    "name": "summary",
                    "type": column_type,
                    "nullable": True,
                    "default": None,
                    "computed": None,
                    "comment": "summary",
                }
            ],
            primary_key={"name": None, "constrained_columns": []},
            unique_constraints=[],
            indexes=[],
            foreign_keys=[],
            checks=[],
            table_comment="synthetic",
        )

    assert signature(Text()) == signature(
        mysql.TEXT(collation="utf8mb4_unicode_ci")
    )


def test_mysql_physical_signature_normalizes_show_create_generated_sql():
    def signature(expression):
        return normalize_physical_schema_signature(
            columns=[
                {
                    "name": "active_slot",
                    "type": mysql.CHAR(64),
                    "nullable": True,
                    "default": None,
                    "computed": {"sqltext": expression, "persisted": True},
                    "comment": "slot",
                }
            ],
            primary_key={"name": None, "constrained_columns": []},
            unique_constraints=[],
            indexes=[],
            foreign_keys=[],
            checks=[],
            table_comment="synthetic",
        )

    expected = signature(
        "CASE WHEN status='active' THEN "
        "SHA2(CONCAT_WS(CHAR(31), customer_id, source_system), 256) ELSE NULL END"
    )
    reflected = signature(
        "((case when `status` = _utf8mb4'active' then "
        "sha2(concat_ws(char(31),`customer_id`,`source_system`),256) else null end))"
    )

    assert expected == reflected

    expected_boolean_condition = signature(
        "CASE WHEN status='active' AND is_primary=1 THEN source ELSE NULL END"
    )
    reflected_boolean_condition = signature(
        "CASE WHEN (`status`='active' AND `is_primary`=1) THEN `source` ELSE NULL END"
    )

    assert expected_boolean_condition == reflected_boolean_condition

    expected_in_condition = signature(
        "CASE WHEN effective_to IS NULL AND verification_status IN ('candidate', 'verified') "
        "THEN source ELSE NULL END"
    )
    reflected_in_condition = signature(
        "CASE WHEN effective_to IS NULL AND (verification_status IN ('candidate', 'verified')) "
        "THEN source ELSE NULL END"
    )

    assert expected_in_condition == reflected_in_condition


def test_mysql_physical_signature_normalizes_check_comparison_parentheses():
    def signature(expression):
        return normalize_physical_schema_signature(
            columns=[],
            primary_key={"name": None, "constrained_columns": []},
            unique_constraints=[],
            indexes=[],
            foreign_keys=[],
            checks=[
                {
                    "name": "ck_confidence",
                    "sqltext": expression,
                    "dialect_options": {"mysql_enforced": True},
                }
            ],
            table_comment="synthetic",
        )

    expected = signature(
        "(record_status = 'merged' and merged_into_customer_id is not null) "
        "or (record_status <> 'merged' and merged_into_customer_id is null)"
    )
    reflected = signature(
        "((record_status = 'merged') and (merged_into_customer_id is not null)) "
        "or ((record_status <> 'merged') and (merged_into_customer_id is null))"
    )

    assert expected == reflected


def test_target_profile_policy_backfill_requires_complete_approved_policy():
    bound_validator_source = inspect.getsource(
        cutover_service._validate_bound_contract_evidence
    )
    assert "target_profile_physical_contract_sha256" in bound_validator_source
    assert "target_profile_policy_backfill_sha256" in bound_validator_source

    empty = _target_profile_policy_artifact(confirmed_empty=True)
    assert cutover_service.validate_target_profile_policy_backfill_artifact(
        empty,
        now=READY_CHECKED_AT,
    ) == empty["artifact_sha256"]

    snapshot = {
        "id": 1,
        "profile_key": "profile-one",
        "company_name": "Ark",
        "company_website": None,
        "products": [],
        "advantages": [],
        "target_countries": [],
        "target_industries": [],
        "target_roles": [],
        "exclusions": [],
        "default_language": "en",
        "status": "active",
        "created_by": None,
        "updated_by": None,
        "created_at": {"$datetime": "2026-08-01T01:00:00.000000"},
        "updated_at": {"$datetime": "2026-08-01T01:00:00.000000"},
        "deleted_at": None,
    }
    entry = _target_profile_policy_entry(snapshot)
    artifact = _target_profile_policy_artifact((entry,))
    assert cutover_service.validate_target_profile_policy_backfill_artifact(
        artifact,
        now=READY_CHECKED_AT,
    ) == artifact["artifact_sha256"]

    incomplete_entry = copy.deepcopy(entry)
    incomplete_entry["policy_json"] = {
        "schema_version": "target_profile_policy_v1",
        "migration_state": "legacy_unconfigured",
    }
    incomplete = _target_profile_policy_artifact((incomplete_entry,))
    with pytest.raises(CutoverGuardError, match="thresholds.*weights.*research.*claim"):
        cutover_service.validate_target_profile_policy_backfill_artifact(
            incomplete,
            now=READY_CHECKED_AT,
        )

    placeholder_entry = copy.deepcopy(entry)
    placeholder_entry["policy_json"] = {
        "schema_version": "target_profile_policy_v1",
        "thresholds": {
            "research_threshold": 0,
            "qualification_threshold": 0,
            "tier_1_min_score": 0,
            "tier_2_min_score": 0,
            "tier_3_min_score": 0,
        },
        "weights": {"todo": 0},
        "research_rules": {"placeholder": True},
        "claim_rules": {"todo": "TBD"},
    }
    placeholder = _target_profile_policy_artifact(
        (_rehash_target_profile_policy_entry(placeholder_entry),)
    )
    with pytest.raises(CutoverGuardError, match="complete|placeholder|semantic"):
        cutover_service.validate_target_profile_policy_backfill_artifact(
            placeholder,
            now=READY_CHECKED_AT,
        )


def test_target_profile_policy_backfill_rejects_stale_approval():
    stale = _target_profile_policy_artifact(confirmed_empty=True)
    stale["approved_at"] = (
        READY_CHECKED_AT - cutover_service.CUTOVER_EVIDENCE_MAX_AGE - timedelta(seconds=1)
    ).isoformat()
    stale_payload = {
        key: value for key, value in stale.items() if key != "artifact_sha256"
    }
    stale["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(stale_payload)
    ).hexdigest()
    with pytest.raises(CutoverGuardError, match="approval.*stale|stale.*approval"):
        cutover_service.validate_target_profile_policy_backfill_artifact(
            stale,
            now=READY_CHECKED_AT,
        )


def test_target_profile_policy_backfill_rejects_subsecond_applied_at():
    engine = create_engine("sqlite:///:memory:")
    _create_legacy_target_profile_table(engine)
    with Session(engine) as db:
        _insert_legacy_target_profile(db)
        db.flush()
        snapshot = cutover_service.snapshot_target_profile_rows(db)[0]
    entry = _target_profile_policy_entry(snapshot)
    entry["policy_applied_at"] = (
        READY_CHECKED_AT + timedelta(microseconds=1)
    ).isoformat()
    entry = _rehash_target_profile_policy_entry(entry)
    artifact = _target_profile_policy_artifact((entry,))
    artifact["approved_at"] = (READY_CHECKED_AT + timedelta(seconds=1)).isoformat()
    artifact_payload = {
        key: value for key, value in artifact.items() if key != "artifact_sha256"
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact_payload)
    ).hexdigest()

    with pytest.raises(CutoverGuardError, match="whole-second precision"):
        cutover_service.validate_target_profile_policy_backfill_artifact(
            artifact,
            now=READY_CHECKED_AT + timedelta(seconds=1),
        )


def test_target_profile_policy_backfill_requires_exact_live_set_and_snapshot():
    engine = create_engine("sqlite:///:memory:")
    _create_legacy_target_profile_table(engine)
    with Session(engine) as db:
        _insert_legacy_target_profile(
            db,
            company_website="https://example.com",
            exclusions=["retail"],
        )
        db.flush()
        snapshots = cutover_service.snapshot_target_profile_rows(db)
        assert len(snapshots) == 1
        artifact = _target_profile_policy_artifact(
            (_target_profile_policy_entry(snapshots[0]),)
        )
        assert cutover_service.validate_target_profile_policy_backfill_against_live_rows(
            db,
            artifact,
            now=READY_CHECKED_AT,
        ) is True

        db.execute(
            text(
                "UPDATE ark_sales_target_profiles "
                "SET company_name='changed' WHERE id=7"
            )
        )
        with pytest.raises(CutoverGuardError, match="stale|snapshot"):
            cutover_service.validate_target_profile_policy_backfill_against_live_rows(
                db,
                artifact,
                now=READY_CHECKED_AT,
            )

    empty_engine = create_engine("sqlite:///:memory:")
    _create_legacy_target_profile_table(empty_engine)
    with Session(empty_engine) as db:
        assert cutover_service.validate_target_profile_policy_backfill_against_live_rows(
            db,
            _target_profile_policy_artifact(confirmed_empty=True),
            now=READY_CHECKED_AT,
        ) is True


def test_target_profile_improvement_requires_valid_bound_approved_agent_artifact():
    engine = _create_cutover_db()
    with Session(engine) as db:
        _insert_legacy_target_profile(db)
        db.flush()
        snapshot = cutover_service.snapshot_target_profile_rows(db)[0]
        entry = _target_profile_policy_entry(snapshot)
        entry["last_improvement_artifact_id"] = 3
        entry = _rehash_target_profile_policy_entry(entry)
        content = {
            "schema_version": "target_profile_improvement_v1",
            "profile_id": 7,
            "policy_patch": {"weights": {"industry_fit": 0.6}},
        }
        content_sha256 = agent_content_hash({"content": content, "evidence": []})
        assert content_sha256 == cutover_service._agent_artifact_content_sha256(
            content, []
        )
        approval_request = {
            "artifact_id": 3,
            "profile_id": 7,
            "content_sha256": content_sha256,
            "policy_snapshot_hash": entry["policy_snapshot_hash"],
        }
        entry["improvement_approval"] = {
            "decision": "approved",
            "approver_user_id": 99,
            "approved_at": READY_CHECKED_AT.isoformat(),
            "approval_request": approval_request,
            "approval_request_sha256": hashlib.sha256(
                canonical_json_bytes(approval_request)
            ).hexdigest(),
            "approved_content_sha256": content_sha256,
        }
        artifact_evidence = _target_profile_policy_artifact((entry,))
        agent_artifact = db.get(AgentArtifact, 3)
        agent_artifact.artifact_type = "target_profile_improvement_v1"
        agent_artifact.content_json = content
        agent_artifact.content_sha256 = content_sha256
        agent_artifact.validation_status = "valid"
        agent_artifact.validation_errors = []
        agent_artifact.decision_status = "approved"
        agent_artifact.decided_by = 99
        agent_artifact.decided_at = READY_CHECKED_AT.replace(tzinfo=None)
        agent_artifact.business_ref_type = "target_profile"
        agent_artifact.business_ref_id = "7"
        db.flush()

        assert cutover_service.validate_target_profile_policy_backfill_against_live_rows(
            db,
            artifact_evidence,
            now=READY_CHECKED_AT,
        ) is True

        for field_name, invalid_value in (
            ("validation_status", "invalid"),
            ("decision_status", "rejected"),
            ("business_ref_id", "8"),
            ("content_sha256", "0" * 64),
        ):
            original = getattr(agent_artifact, field_name)
            setattr(agent_artifact, field_name, invalid_value)
            db.flush()
            with pytest.raises(CutoverGuardError, match="improvement Artifact"):
                cutover_service.validate_target_profile_policy_backfill_against_live_rows(
                    db,
                    artifact_evidence,
                    now=READY_CHECKED_AT,
                )
            setattr(agent_artifact, field_name, original)
            db.flush()


def test_customer_account_integer_pk_autoincrement_modes_match_mysql_reflection():
    model_id = CustomerAccount.__table__.c.id

    def _signature(autoincrement):
        return normalize_physical_schema_signature(
            columns=[
                {
                    "name": model_id.name,
                    "type": model_id.type,
                    "nullable": model_id.nullable,
                    "default": None,
                    "computed": None,
                    "autoincrement": autoincrement,
                    "comment": model_id.comment,
                }
            ],
            primary_key={"name": "PRIMARY", "constrained_columns": ["id"]},
            unique_constraints=[],
            indexes=[],
            foreign_keys=[],
            checks=[],
            table_comment="synthetic customer account",
        )

    reflected_mysql = _signature(True)
    assert model_id.autoincrement == "ignore_fk"
    assert _signature(model_id.autoincrement) == reflected_mysql
    assert _signature("auto") == reflected_mysql


def test_mysql_check_enforcement_requires_authoritative_yes_for_every_check():
    inspector_checks = [{"name": "ck_value", "sqltext": "id > 0"}]
    missing_enforcement = normalize_physical_schema_signature(
        columns=[],
        primary_key={"name": None, "constrained_columns": []},
        unique_constraints=[],
        indexes=[],
        foreign_keys=[],
        checks=inspector_checks,
        table_comment="synthetic",
    )
    assert missing_enforcement["checks"] == (("ck_value", "id > 0", False),)

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def __iter__(self):
            return iter(self._rows)

        def close(self):
            return None

    class _Connection:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, statement, params):
            assert "information_schema.TABLE_CONSTRAINTS" in str(statement)
            assert params == {"table_name": "ark_customer_accounts"}
            return _Rows(self.rows)

    enforced = cutover_service._mysql_enforced_checks(
        _Connection([{"constraint_name": "ck_value", "enforced": "YES"}]),
        "ark_customer_accounts",
        inspector_checks,
    )
    signature = normalize_physical_schema_signature(
        columns=[],
        primary_key={"name": None, "constrained_columns": []},
        unique_constraints=[],
        indexes=[],
        foreign_keys=[],
        checks=enforced,
        table_comment="synthetic",
    )
    assert signature["checks"] == (("ck_value", "id > 0", True),)

    for rows in (
        [{"constraint_name": "ck_value", "enforced": "NO"}],
        [],
    ):
        with pytest.raises(CutoverGuardError, match="CHECK enforcement"):
            cutover_service._mysql_enforced_checks(
                _Connection(rows),
                "ark_customer_accounts",
                inspector_checks,
            )


def test_revision_126_must_register_all_39_physical_table_contracts():
    complete = _physical_schema_contract()
    assert len(complete["tables"]) == 39
    assert validate_customer_physical_schema_contract(complete) == complete[
        "contract_sha256"
    ]
    with pytest.raises(CutoverGuardError, match="exactly 39 tables"):
        validate_customer_physical_schema_contract(
            _physical_schema_contract(omit="ark_sales_search_result_sources")
        )


def test_cli_exposes_only_guarded_commands_and_rejects_escaping_paths():
    script = _load_cutover_script()
    parser = script.build_parser()
    command_action = next(action for action in parser._actions if action.dest == "command")

    assert set(command_action.choices) == {
        "preflight",
        "export-suppressions",
        "verify-ready",
        "apply-reset",
        "verify-after",
    }
    assert "--safe-output-root" not in parser.format_help()
    with pytest.raises(CutoverGuardError, match="repository"):
        script.resolve_read_path(Path("../outside.json"))
    output = script.resolve_evidence_output_path(Path("reports/preflight.json"))
    assert output == REPO_ROOT / "backend/tmp/customer-domain-cutover/reports/preflight.json"
    with pytest.raises(CutoverGuardError, match="fixed evidence root"):
        script.resolve_evidence_output_path(REPO_ROOT / "README.md")


def test_fixed_output_root_blocks_traversal_symlinks_and_overwrite(tmp_path, monkeypatch):
    script = _load_cutover_script()
    unique = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
    output = script.resolve_evidence_output_path(f"tests/{unique}.json")
    script._write_canonical_json(output, {"ok": True})
    with pytest.raises(CutoverGuardError, match="will not be overwritten"):
        script._write_canonical_json(output, {"ok": False})
    with pytest.raises(CutoverGuardError, match="fixed evidence root"):
        script.resolve_evidence_output_path("../escaped.json")

    reparse_parent = script.EVIDENCE_ROOT / f"tests/{unique}-reparse"
    reparse_parent.mkdir()
    original = script._is_reparse_point
    monkeypatch.setattr(
        script,
        "_is_reparse_point",
        lambda path: path == reparse_parent or original(path),
    )
    with pytest.raises(CutoverGuardError, match="symlink/reparse"):
        script.resolve_evidence_output_path(reparse_parent / "escape.json")


def test_apply_reset_never_invokes_alembic_when_guard_or_marker_hash_fails(tmp_path):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    calls = []
    with Session(engine) as db:
        inventory = build_inventory(db)
        report = script.build_preflight_report(db)
        suppression = _build_suppression(
            db, inventory, [], preflight_report_sha256=report["report_sha256"]
        ).to_dict()
        writer = _writer_manifest(
            inventory.inventory_sha256,
            preflight_report_sha256=report["report_sha256"],
        )
        marker = tmp_path / "approved.json"
        marker.write_text(
            json.dumps({"approved": True, "inventory_sha256": "f" * 64}),
            encoding="utf-8",
        )
        with pytest.raises(CutoverGuardError):
            script.apply_reset(
                db=db,
                preflight_report=report,
                suppression_manifest=suppression,
                stopped_writer_manifest=writer,
                expected_inventory_sha256=inventory.inventory_sha256,
                approved_marker_path=marker,
                suppression_hmac_key=SUPPRESSION_HMAC_KEY,
                physical_schema_contract=_physical_schema_contract(),
                target_profile_policy_backfill=_target_profile_policy_artifact(
                    confirmed_empty=True
                ),
                subprocess_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )

    assert calls == []


def test_apply_reset_rejects_tampered_preflight_content_before_runner(tmp_path):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    calls = []
    with Session(engine) as db:
        inventory = build_inventory(db)
        report = script.build_preflight_report(db)
        suppression = _build_suppression(
            db, inventory, [], preflight_report_sha256=report["report_sha256"]
        ).to_dict()
        writer = _writer_manifest(
            inventory.inventory_sha256,
            preflight_report_sha256=report["report_sha256"],
        )
        marker = tmp_path / "approved.json"
        marker.write_text(json.dumps({"approved": True}), encoding="utf-8")
        with pytest.raises(CutoverGuardError, match="preflight report SHA-256"):
            script.apply_reset(
                db=db,
                preflight_report={**report, "generated_at": "tampered"},
                suppression_manifest=suppression,
                stopped_writer_manifest=writer,
                expected_inventory_sha256=inventory.inventory_sha256,
                approved_marker_path=marker,
                suppression_hmac_key=SUPPRESSION_HMAC_KEY,
                physical_schema_contract=_physical_schema_contract(),
                target_profile_policy_backfill=_target_profile_policy_artifact(
                    confirmed_empty=True
                ),
                subprocess_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )
    assert calls == []


def test_apply_reset_invokes_only_alembic_upgrade_head_after_both_hashes_bind(
    tmp_path, monkeypatch
):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    calls = []
    with Session(engine) as db:
        inventory = build_inventory(db)
        report = script.build_preflight_report(db)
        suppression = _build_suppression(
            db, inventory, [], preflight_report_sha256=report["report_sha256"]
        ).to_dict()
        writer = _writer_manifest(
            inventory.inventory_sha256,
            preflight_report_sha256=report["report_sha256"],
        )
        fence = read_maintenance_fence_evidence(writer)
        nonce = "successful-cutover-" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
        marker = tmp_path / "approved.json"
        marker.write_text(
            json.dumps(
                {
                    "approved": True,
                    "inventory_sha256": inventory.inventory_sha256,
                    "preflight_report_sha256": report["report_sha256"],
                    "suppression_manifest_sha256": suppression["manifest_sha256"],
                    "writer_manifest_sha256": hashlib.sha256(
                        canonical_json_bytes(writer)
                    ).hexdigest(),
                    "writer_privilege_revocation_artifact_sha256": fence[
                        "writer_privilege_revocation_artifact_sha256"
                    ],
                    "physical_schema_contract_sha256": _physical_schema_contract()[
                        "contract_sha256"
                    ],
                    "target_profile_physical_contract_sha256": (
                        _target_profile_physical_contract_sha256()
                    ),
                    "target_profile_policy_backfill_sha256": (
                        _target_profile_policy_artifact(confirmed_empty=True)[
                            "artifact_sha256"
                        ]
                    ),
                    "nonce": nonce,
                    "expires_at": (READY_CHECKED_AT + timedelta(minutes=4)).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        def capture_runner(*args, **kwargs):
            assert db.in_transaction() is False
            calls.append((args, kwargs))
            contract_path = Path(args[0][-3].split("=", 1)[1])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            proof = _ddl_proof_for_contract(
                contract,
                started_at=READY_CHECKED_AT + timedelta(minutes=1),
                completed_at=READY_CHECKED_AT + timedelta(minutes=1),
            )
            script._write_canonical_json(contract["ddl_proof_path"], proof)

        monkeypatch.setattr(script, "_post_migration_verify", lambda *_a, **_k: True)

        result = script.apply_reset(
            db=db,
            preflight_report=report,
            suppression_manifest=suppression,
            stopped_writer_manifest=writer,
            expected_inventory_sha256=inventory.inventory_sha256,
            approved_marker_path=marker,
            suppression_hmac_key=SUPPRESSION_HMAC_KEY,
            physical_schema_contract=_physical_schema_contract(),
            target_profile_policy_backfill=_target_profile_policy_artifact(
                confirmed_empty=True
            ),
            subprocess_runner=capture_runner,
            now=READY_CHECKED_AT + timedelta(minutes=1),
        )

    assert result.inventory_sha256 == inventory.inventory_sha256
    assert len(calls) == 1
    command = calls[0][0][0]
    assert command[-2:] == ["upgrade", "head"]
    assert command[-4] == "-x"
    assert command[-3].startswith("customer_cutover_contract=")
    assert calls[0][1]["check"] is True
    assert calls[0][1]["cwd"] == REPO_ROOT / "backend"
    contract_path = Path(command[-3].split("=", 1)[1])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    proof_path = CUTOVER_EVIDENCE_ROOT / contract["ddl_proof_path"]
    receipt_path = CUTOVER_EVIDENCE_ROOT / contract["receipt_path"]
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert script.validate_execution_receipt(
        receipt,
        evidence_contract=contract,
        ddl_proof=proof,
        ddl_proof_resolved_path=proof_path,
        receipt_resolved_path=receipt_path,
    ) is True


def test_apply_reset_runner_success_without_ddl_proof_keeps_writers_stopped(tmp_path):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
        report = script.build_preflight_report(db)
        suppression = _build_suppression(
            db, inventory, [], preflight_report_sha256=report["report_sha256"]
        ).to_dict()
        writer = _writer_manifest(
            inventory.inventory_sha256,
            preflight_report_sha256=report["report_sha256"],
        )
        fence = read_maintenance_fence_evidence(writer)
        marker = tmp_path / "approved-no-receipt.json"
        marker.write_text(
            json.dumps(
                {
                    "approved": True,
                    "inventory_sha256": inventory.inventory_sha256,
                    "preflight_report_sha256": report["report_sha256"],
                    "suppression_manifest_sha256": suppression["manifest_sha256"],
                    "writer_manifest_sha256": hashlib.sha256(
                        canonical_json_bytes(writer)
                    ).hexdigest(),
                    "writer_privilege_revocation_artifact_sha256": fence[
                        "writer_privilege_revocation_artifact_sha256"
                    ],
                    "physical_schema_contract_sha256": _physical_schema_contract()[
                        "contract_sha256"
                    ],
                    "target_profile_physical_contract_sha256": (
                        _target_profile_physical_contract_sha256()
                    ),
                    "target_profile_policy_backfill_sha256": (
                        _target_profile_policy_artifact(confirmed_empty=True)[
                            "artifact_sha256"
                        ]
                    ),
                    "nonce": "missing-receipt-" + hashlib.sha256(
                        str(tmp_path).encode()
                    ).hexdigest()[:16],
                    "expires_at": (READY_CHECKED_AT + timedelta(minutes=4)).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(CutoverGuardError, match="keep all writers stopped"):
            script.apply_reset(
                db=db,
                preflight_report=report,
                suppression_manifest=suppression,
                stopped_writer_manifest=writer,
                expected_inventory_sha256=inventory.inventory_sha256,
                approved_marker_path=marker,
                suppression_hmac_key=SUPPRESSION_HMAC_KEY,
                physical_schema_contract=_physical_schema_contract(),
                target_profile_policy_backfill=_target_profile_policy_artifact(
                    confirmed_empty=True
                ),
                subprocess_runner=lambda *args, **kwargs: None,
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )


@pytest.mark.parametrize(
    "failure_mode",
    (
        "tampered_ddl_proof",
        "old_alembic_version",
        "postverify",
        "expired_during_postverify",
        "publication",
    ),
)
def test_apply_reset_never_publishes_success_when_finalization_fails(
    tmp_path, monkeypatch, failure_mode
):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    captured = {}
    with Session(engine) as db:
        inventory = build_inventory(db)
        report = script.build_preflight_report(db)
        suppression = _build_suppression(
            db, inventory, [], preflight_report_sha256=report["report_sha256"]
        ).to_dict()
        writer = _writer_manifest(
            inventory.inventory_sha256,
            preflight_report_sha256=report["report_sha256"],
        )
        fence = read_maintenance_fence_evidence(writer)
        nonce = (
            f"{failure_mode}-"
            + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:20]
        )
        marker = tmp_path / f"{failure_mode}-approved.json"
        marker.write_text(
            json.dumps(
                {
                    "approved": True,
                    "inventory_sha256": inventory.inventory_sha256,
                    "preflight_report_sha256": report["report_sha256"],
                    "suppression_manifest_sha256": suppression["manifest_sha256"],
                    "writer_manifest_sha256": hashlib.sha256(
                        canonical_json_bytes(writer)
                    ).hexdigest(),
                    "writer_privilege_revocation_artifact_sha256": fence[
                        "writer_privilege_revocation_artifact_sha256"
                    ],
                    "physical_schema_contract_sha256": _physical_schema_contract()[
                        "contract_sha256"
                    ],
                    "target_profile_physical_contract_sha256": (
                        _target_profile_physical_contract_sha256()
                    ),
                    "target_profile_policy_backfill_sha256": (
                        _target_profile_policy_artifact(confirmed_empty=True)[
                            "artifact_sha256"
                        ]
                    ),
                    "nonce": nonce,
                    "expires_at": (
                        READY_CHECKED_AT + timedelta(minutes=4)
                    ).isoformat(),
                }
            ),
            encoding="utf-8",
        )

        def fake_runner(*args, **_kwargs):
            contract_path = Path(args[0][-3].split("=", 1)[1])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            captured["contract"] = contract
            proof = _ddl_proof_for_contract(
                contract,
                started_at=READY_CHECKED_AT + timedelta(minutes=1),
                completed_at=READY_CHECKED_AT + timedelta(minutes=1),
            )
            if failure_mode == "tampered_ddl_proof":
                proof["status"] = "tampered"
            script._write_canonical_json(contract["ddl_proof_path"], proof)
            if failure_mode == "old_alembic_version":
                with engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE alembic_version (version_num TEXT)")
                    )
                    connection.execute(
                        text("INSERT INTO alembic_version VALUES ('125')")
                    )

        if failure_mode == "postverify":
            monkeypatch.setattr(
                script,
                "_post_migration_verify",
                lambda *_a, **_k: (_ for _ in ()).throw(
                    CutoverGuardError("synthetic postverify failure")
                ),
            )
        elif failure_mode not in {"old_alembic_version"}:
            monkeypatch.setattr(
                script, "_post_migration_verify", lambda *_a, **_k: True
            )
        if failure_mode == "publication":
            original_write = script._write_canonical_json

            def fail_final_receipt(path, value):
                if Path(path).name.startswith("migration-receipt-"):
                    raise CutoverGuardError("synthetic final publication crash")
                return original_write(path, value)

            monkeypatch.setattr(script, "_write_canonical_json", fail_final_receipt)

        with pytest.raises(CutoverGuardError, match="keep all writers stopped"):
            script.apply_reset(
                db=db,
                preflight_report=report,
                suppression_manifest=suppression,
                stopped_writer_manifest=writer,
                expected_inventory_sha256=inventory.inventory_sha256,
                approved_marker_path=marker,
                suppression_hmac_key=SUPPRESSION_HMAC_KEY,
                physical_schema_contract=_physical_schema_contract(),
                target_profile_policy_backfill=_target_profile_policy_artifact(
                    confirmed_empty=True
                ),
                subprocess_runner=fake_runner,
                now=READY_CHECKED_AT + timedelta(minutes=1),
                clock=(
                    (lambda: READY_CHECKED_AT + timedelta(minutes=5))
                    if failure_mode == "expired_during_postverify"
                    else None
                ),
            )

    contract = captured["contract"]
    assert not (CUTOVER_EVIDENCE_ROOT / contract["receipt_path"]).exists()


def test_atomic_evidence_publication_crash_never_leaves_partial_target(
    tmp_path, monkeypatch
):
    script = _load_cutover_script()
    unique = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:20]
    target = script.resolve_evidence_output_path(
        f"atomic-crash-{unique}/migration-receipt-{unique}.json"
    )
    monkeypatch.setattr(
        script.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("synthetic publish crash")
        ),
    )

    with pytest.raises(CutoverGuardError, match="cannot write cutover evidence"):
        script._write_canonical_json(target, {"status": "succeeded"})

    assert not target.exists()
    assert not tuple(target.parent.glob(".cutover-*.tmp"))


@pytest.mark.parametrize(
    "marker_update",
    [
        {"approved": False},
        {"inventory_sha256": None},
        {"inventory_sha256": "f" * 64},
    ],
)
def test_apply_reset_marker_failures_are_independent_and_never_run(tmp_path, marker_update):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    calls = []
    with Session(engine) as db:
        inventory = build_inventory(db)
        report = script.build_preflight_report(db)
        suppression = _build_suppression(
            db, inventory, [], preflight_report_sha256=report["report_sha256"]
        ).to_dict()
        writer = _writer_manifest(
            inventory.inventory_sha256,
            preflight_report_sha256=report["report_sha256"],
        )
        fence = read_maintenance_fence_evidence(writer)
        marker_data = {
            "approved": True,
            "inventory_sha256": inventory.inventory_sha256,
            "preflight_report_sha256": report["report_sha256"],
            "suppression_manifest_sha256": suppression["manifest_sha256"],
            "writer_manifest_sha256": hashlib.sha256(canonical_json_bytes(writer)).hexdigest(),
            "writer_privilege_revocation_artifact_sha256": fence[
                "writer_privilege_revocation_artifact_sha256"
            ],
            "physical_schema_contract_sha256": _physical_schema_contract()[
                "contract_sha256"
            ],
            "target_profile_physical_contract_sha256": (
                _target_profile_physical_contract_sha256()
            ),
            "target_profile_policy_backfill_sha256": (
                _target_profile_policy_artifact(confirmed_empty=True)[
                    "artifact_sha256"
                ]
            ),
            "nonce": "failed-marker-check-20260830",
            "expires_at": (READY_CHECKED_AT + timedelta(minutes=4)).isoformat(),
        }
        marker_data.update(marker_update)
        marker = tmp_path / "marker.json"
        marker.write_text(json.dumps(marker_data), encoding="utf-8")
        with pytest.raises(CutoverGuardError):
            script.apply_reset(
                db=db,
                preflight_report=report,
                suppression_manifest=suppression,
                stopped_writer_manifest=writer,
                expected_inventory_sha256=inventory.inventory_sha256,
                approved_marker_path=marker,
                suppression_hmac_key=SUPPRESSION_HMAC_KEY,
                physical_schema_contract=_physical_schema_contract(),
                target_profile_policy_backfill=_target_profile_policy_artifact(
                    confirmed_empty=True
                ),
                subprocess_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )
    assert calls == []


def test_execution_receipt_must_bind_the_exact_approval_marker():
    script = _load_cutover_script()
    contract = {
        "schema_version": 1,
        "approved": True,
        "inventory_sha256": "a" * 64,
        "preflight_report_sha256": "b" * 64,
        "suppression_manifest_sha256": "c" * 64,
        "writer_manifest_sha256": "d" * 64,
        "writer_privilege_revocation_artifact_sha256": "9" * 64,
        "approved_marker_sha256": "e" * 64,
        "maintenance_fence_artifact_sha256": "f" * 64,
        "instance_inventory_artifact_sha256": "1" * 64,
        "physical_schema_contract_sha256": "2" * 64,
        "target_profile_physical_contract_sha256": "3" * 64,
        "target_profile_policy_backfill_sha256": "4" * 64,
        "nonce": "receipt-nonce-20260830",
        "contract_path": str(CUTOVER_EVIDENCE_ROOT / "contract.json"),
        "ddl_proof_path": "migration-ddl-proof-receipt-nonce-20260830.json",
        "receipt_path": "migration-receipt-receipt-nonce-20260830.json",
        "migration_revision": script.CUTOVER_MIGRATION_REVISION,
        "issued_at": "2026-08-30T09:00:00+08:00",
        "expires_at": "2026-08-30T09:04:00+08:00",
    }
    contract["ddl_proof_binding_sha256"] = script._ddl_proof_binding_sha256(
        contract
    )
    contract["contract_sha256"] = hashlib.sha256(
        canonical_json_bytes(contract)
    ).hexdigest()
    proof = _ddl_proof_for_contract(
        contract,
        started_at=datetime.fromisoformat("2026-08-30T09:01:00+08:00"),
        completed_at=datetime.fromisoformat("2026-08-30T09:02:00+08:00"),
    )
    receipt = script._build_execution_receipt(
        contract,
        proof,
        completed_at=datetime.fromisoformat("2026-08-30T09:03:00+08:00"),
    )
    proof_path = CUTOVER_EVIDENCE_ROOT / contract["ddl_proof_path"]
    assert script.validate_execution_receipt(
        receipt,
        evidence_contract=contract,
        ddl_proof=proof,
        ddl_proof_resolved_path=proof_path,
        receipt_resolved_path=(
            CUTOVER_EVIDENCE_ROOT / contract["receipt_path"]
        ),
    ) is True
    with pytest.raises(CutoverGuardError, match="approved_marker_sha256"):
        script.validate_execution_receipt(
            receipt,
            evidence_contract=(lambda changed: {
                **changed,
                "contract_sha256": hashlib.sha256(
                    canonical_json_bytes(changed)
                ).hexdigest(),
            })({
                **{
                    key: value
                    for key, value in contract.items()
                    if key != "contract_sha256"
                },
                "approved_marker_sha256": "2" * 64,
                "ddl_proof_binding_sha256": script._ddl_proof_binding_sha256({
                    **contract,
                    "approved_marker_sha256": "2" * 64,
                }),
            }),
            ddl_proof=proof,
            ddl_proof_resolved_path=proof_path,
            receipt_resolved_path=(
                CUTOVER_EVIDENCE_ROOT / contract["receipt_path"]
            ),
        )

    alternate = CUTOVER_EVIDENCE_ROOT / "alternate-valid-looking-receipt.json"
    with pytest.raises(CutoverGuardError, match="receipt path"):
        script.validate_execution_receipt(
            receipt,
            evidence_contract=contract,
            ddl_proof=proof,
            ddl_proof_resolved_path=proof_path,
            receipt_resolved_path=alternate,
        )


def test_post_migration_finalization_rejects_old_alembic_version():
    script = _load_cutover_script()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('125')"))
    with Session(engine) as db, pytest.raises(
        CutoverGuardError, match="alembic_version.*126"
    ):
        script._verify_applied_revision(db)


def test_parent_postverify_rechecks_live_writer_gate_before_and_after_data_proof():
    script = _load_cutover_script()
    source = inspect.getsource(script._post_migration_verify)

    assert source.count("validate_live_customer_cutover_writer_gate") == 2
    assert source.count("now=clock()") == 2
    read_only = source.index("SET TRANSACTION READ ONLY")
    first_gate = source.index("validate_live_customer_cutover_writer_gate")
    data_proof = source.index("verify_target_profile_post_state")
    final_gate = source.rindex("validate_live_customer_cutover_writer_gate")
    assert read_only < first_gate < data_proof < final_gate
