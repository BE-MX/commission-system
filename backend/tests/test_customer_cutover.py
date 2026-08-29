import hashlib
import hmac
import importlib.util
import json
import copy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import BigInteger, Text, create_engine, event, text
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- registers string FK targets for Agent DDL
import app.customer.cutover_service as cutover_service
from app.agent_runtime.models import (
    AgentArtifact,
    AgentEvent,
    AgentProfile,
    AgentRun,
    AgentSession,
)
from app.core.database import Base
from app.customer.models import CustomerSuppressionRegistry
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
SUPPRESSION_HMAC_KEY = b"cutover-test-hmac-key-32-bytes!!"
PREFLIGHT_REPORT_SHA256 = "a" * 64
READY_CHECKED_AT = datetime(2026, 8, 30, 9, 0, tzinfo=BEIJING)


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
    instance_inventory = [
        {"category": category, "instance_id": f"{category}-01"}
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
    writer_paths = [write_artifact("writer-stop", writer)[0] for writer in writers]
    transaction_payload = {
        "schema_version": 1,
        "artifact_kind": "active_transaction_snapshot",
        "count": active_transactions,
        "checked_at": checked_at.isoformat(),
        "inventory_sha256": inventory_sha256,
        "preflight_report_sha256": preflight_report_sha256,
        "evidence_detail": "active relevant customer writer transactions enumerated",
    }
    transaction_path, _ = write_artifact("transactions", transaction_payload)
    fence_payload = {
        "schema_version": 1,
        "artifact_kind": "maintenance_fence",
        "token": f"cutover-fence-{inventory_sha256[:20]}",
        "instance_inventory_artifact_sha256": inventory_artifact_sha256,
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
    }


def _physical_schema_contract(*, omit=None):
    tables = {}
    for table_name in NEW_CUSTOMER_TABLES + REBUILT_CUSTOMER_WORKFLOW_TABLES:
        if table_name == omit:
            continue
        column_names = (
            list(cutover_service.CORE_TABLES[table_name].c.keys())
            if table_name in cutover_service.CORE_TABLES
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
        nonce = f"cutover-{report_sha256[:24]}"
        writer_sha256 = hashlib.sha256(
            canonical_json_bytes(writer_manifest)
        ).hexdigest()
        physical_contract = _physical_schema_contract()
        marker = {
            "approved": True,
            "inventory_sha256": inventory.inventory_sha256,
            "preflight_report_sha256": report_sha256,
            "suppression_manifest_sha256": suppression["manifest_sha256"],
            "writer_manifest_sha256": writer_sha256,
            "physical_schema_contract_sha256": physical_contract[
                "contract_sha256"
            ],
            "nonce": nonce,
            "expires_at": (now + timedelta(minutes=3)).isoformat(),
        }
        documents = {
            "preflight_report": report,
            "suppression_manifest": suppression,
            "writer_manifest": writer_manifest,
            "approved_marker": marker,
            "physical_schema_contract": physical_contract,
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
            "contract_path": str(
                CUTOVER_EVIDENCE_ROOT / f"migration-contract-{nonce}.json"
            ),
            "receipt_path": f"migration-receipt-{nonce}.json",
            "migration_revision": "126",
            "evidence_artifacts": evidence_artifacts,
            "physical_schema_contract_sha256": physical_contract[
                "contract_sha256"
            ],
        }
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


def test_verify_after_table_state_requires_all_new_tables_and_no_retired_only_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in NEW_CUSTOMER_TABLES],
    )
    with engine.begin() as connection:
        for table_name in REBUILT_CUSTOMER_WORKFLOW_TABLES:
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


def test_revision_126_must_register_all_38_physical_table_contracts():
    complete = _physical_schema_contract()
    assert len(complete["tables"]) == 38
    assert validate_customer_physical_schema_contract(complete) == complete[
        "contract_sha256"
    ]
    with pytest.raises(CutoverGuardError, match="exactly 38 tables"):
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
                subprocess_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )
    assert calls == []


def test_apply_reset_invokes_only_alembic_upgrade_head_after_both_hashes_bind(tmp_path):
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
                    "physical_schema_contract_sha256": _physical_schema_contract()[
                        "contract_sha256"
                    ],
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
            receipt = {
                "status": "succeeded",
                **{
                    field: contract[field]
                    for field in (
                        "inventory_sha256",
                        "preflight_report_sha256",
                        "suppression_manifest_sha256",
                        "writer_manifest_sha256",
                        "approved_marker_sha256",
                        "maintenance_fence_artifact_sha256",
                        "instance_inventory_artifact_sha256",
                        "physical_schema_contract_sha256",
                        "nonce",
                        "contract_sha256",
                        "contract_path",
                        "receipt_path",
                        "migration_revision",
                    )
                },
                "schema_signature_sha256": contract[
                    "physical_schema_contract_sha256"
                ],
                "started_at": (READY_CHECKED_AT + timedelta(minutes=1)).isoformat(),
                "completed_at": (READY_CHECKED_AT + timedelta(minutes=2)).isoformat(),
            }
            receipt["receipt_sha256"] = hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest()
            script._write_canonical_json(contract["receipt_path"], receipt)

        result = script.apply_reset(
            db=db,
            preflight_report=report,
            suppression_manifest=suppression,
            stopped_writer_manifest=writer,
            expected_inventory_sha256=inventory.inventory_sha256,
            approved_marker_path=marker,
            suppression_hmac_key=SUPPRESSION_HMAC_KEY,
            physical_schema_contract=_physical_schema_contract(),
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


def test_apply_reset_runner_success_without_receipt_keeps_writers_stopped(tmp_path):
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
                    "physical_schema_contract_sha256": _physical_schema_contract()[
                        "contract_sha256"
                    ],
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
                subprocess_runner=lambda *args, **kwargs: None,
                now=READY_CHECKED_AT + timedelta(minutes=1),
            )


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
        marker_data = {
            "approved": True,
            "inventory_sha256": inventory.inventory_sha256,
            "preflight_report_sha256": report["report_sha256"],
            "suppression_manifest_sha256": suppression["manifest_sha256"],
            "writer_manifest_sha256": hashlib.sha256(canonical_json_bytes(writer)).hexdigest(),
            "physical_schema_contract_sha256": _physical_schema_contract()[
                "contract_sha256"
            ],
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
        "approved_marker_sha256": "e" * 64,
        "maintenance_fence_artifact_sha256": "f" * 64,
        "instance_inventory_artifact_sha256": "1" * 64,
        "physical_schema_contract_sha256": "2" * 64,
        "nonce": "receipt-nonce-20260830",
        "contract_path": str(CUTOVER_EVIDENCE_ROOT / "contract.json"),
        "receipt_path": "migration-receipt-receipt-nonce-20260830.json",
        "migration_revision": script.CUTOVER_MIGRATION_REVISION,
        "issued_at": "2026-08-30T09:00:00+08:00",
        "expires_at": "2026-08-30T09:04:00+08:00",
    }
    contract["contract_sha256"] = hashlib.sha256(
        canonical_json_bytes(contract)
    ).hexdigest()
    receipt = {
        "status": "succeeded",
        **{
            field: contract[field]
            for field in (
                "inventory_sha256",
                "preflight_report_sha256",
                "suppression_manifest_sha256",
                "writer_manifest_sha256",
                "approved_marker_sha256",
                "maintenance_fence_artifact_sha256",
                "instance_inventory_artifact_sha256",
                "physical_schema_contract_sha256",
                "nonce",
                "contract_sha256",
                "contract_path",
                "receipt_path",
                "migration_revision",
            )
        },
        "schema_signature_sha256": contract["physical_schema_contract_sha256"],
        "started_at": "2026-08-30T09:01:00+08:00",
        "completed_at": "2026-08-30T09:03:00+08:00",
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(receipt)
    ).hexdigest()
    assert script.validate_execution_receipt(
        receipt,
        evidence_contract=contract,
        receipt_resolved_path=(
            CUTOVER_EVIDENCE_ROOT / contract["receipt_path"]
        ),
    ) is True
    with pytest.raises(CutoverGuardError, match="approved_marker_sha256"):
        script.validate_execution_receipt(
            receipt,
            evidence_contract={
                **contract,
                "approved_marker_sha256": "2" * 64,
                "contract_sha256": hashlib.sha256(
                    canonical_json_bytes(
                        {
                            **{
                                key: value
                                for key, value in contract.items()
                                if key != "contract_sha256"
                            },
                            "approved_marker_sha256": "2" * 64,
                        }
                    )
                ).hexdigest(),
            },
            receipt_resolved_path=(
                CUTOVER_EVIDENCE_ROOT / contract["receipt_path"]
            ),
        )

    alternate = CUTOVER_EVIDENCE_ROOT / "alternate-valid-looking-receipt.json"
    with pytest.raises(CutoverGuardError, match="receipt path"):
        script.validate_execution_receipt(
            receipt,
            evidence_contract=contract,
            receipt_resolved_path=alternate,
        )
