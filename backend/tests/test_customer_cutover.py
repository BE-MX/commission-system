import hashlib
import hmac
import importlib.util
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- registers string FK targets for Agent DDL
from app.agent_runtime.models import (
    AgentArtifact,
    AgentEvent,
    AgentProfile,
    AgentRun,
    AgentSession,
)
from app.core.database import Base
from app.customer.cutover_service import (
    AGENT_CONTROL_TABLES,
    KNOWN_WRITER_CATEGORIES,
    NEW_CUSTOMER_TABLES,
    REBUILT_CUSTOMER_WORKFLOW_TABLES,
    RETIRED_CUSTOMER_BUSINESS_TABLES,
    CutoverGuardError,
    build_inventory,
    build_suppression_manifest,
    resolve_agent_history_closure,
    snapshot_unrelated_agent_rows,
    verify_ready,
    verify_expected_customer_table_state,
    verify_agent_history_removed,
    verify_unrelated_unchanged,
)


BEIJING = ZoneInfo("Asia/Shanghai")
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/customer_domain_cutover.py"
SUPPRESSION_HMAC_KEY = b"cutover-test-hmac-key-32-bytes!!"


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


def _writer_manifest(*, omitted=None, running=None):
    checked_at = "2026-08-29T22:00:00+08:00"
    return {
        "writers": [
            {
                "category": category,
                "instance_id": f"{category}-01",
                "stopped": category != running,
                "checked_at": checked_at,
                "evidence": {"process": "stopped", "ticket": "CUTOVER-1"},
            }
            for category in KNOWN_WRITER_CATEGORIES
            if category != omitted
        ]
    }


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


def test_suppression_manifest_contains_only_hmac_and_preserves_ambiguous_rows():
    key = SUPPRESSION_HMAC_KEY
    candidates = [
        {
            "source_namespace": "crm",
            "scope": "email",
            "value": " Alice@Example.COM ",
            "reason": "do_not_contact",
            "source_ref": "customer-42",
            "effective_at": datetime(2026, 8, 29, 9, 30, tzinfo=BEIJING),
            "mapping_status": "matched",
        },
        {
            "source_namespace": "legacy-import",
            "scope": "domain",
            "value": "EXAMPLE.ORG.",
            "reason": "manual_block",
            "source_ref": "block-7",
            "effective_at": datetime(2026, 8, 28, 17, 0, tzinfo=BEIJING),
            "mapping_status": "ambiguous",
        },
    ]

    manifest = build_suppression_manifest(candidates, key, "v3")
    serialized = json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True)
    expected = hmac.new(
        key,
        b"crm\0email\0alice@example.com",
        hashlib.sha256,
    ).hexdigest()

    assert len(manifest.entries) == 2
    assert manifest.entries[0].value_hmac_sha256 == expected
    assert {entry.mapping_status for entry in manifest.entries} == {"matched", "ambiguous"}
    assert manifest.entries[0].effective_at == "2026-08-29T09:30:00+08:00"
    assert "Alice@Example.COM" not in serialized
    assert "alice@example.com" not in serialized
    assert key.decode("ascii") not in serialized
    assert '"value"' not in serialized


def test_suppression_empty_requires_confirmation_and_hash_is_order_independent():
    with pytest.raises(CutoverGuardError, match="confirmed_empty"):
        build_suppression_manifest([], SUPPRESSION_HMAC_KEY, "v1")

    empty = build_suppression_manifest(
        [], SUPPRESSION_HMAC_KEY, "v1", confirmed_empty=True
    )
    assert empty.entries == ()

    rows = [
        {
            "source_namespace": "crm",
            "scope": "phone",
            "value": "+86 138-0013-8000",
            "reason": "opted_out",
            "source_ref": "a",
            "effective_at": datetime(2026, 8, 29, 11, 0, tzinfo=BEIJING),
        },
        {
            "source_namespace": "email-provider",
            "scope": "provider_id",
            "value": " Message-ID-CaseSensitive ",
            "reason": "hard_bounce",
            "source_ref": "b",
            "effective_at": datetime(2026, 8, 29, 12, 0, tzinfo=BEIJING),
            "mapping_status": "unmapped",
        },
    ]
    first = build_suppression_manifest(rows, SUPPRESSION_HMAC_KEY, "v1")
    second = build_suppression_manifest(
        list(reversed(rows)), SUPPRESSION_HMAC_KEY, "v1"
    )
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.entries == second.entries


def test_suppression_rejects_low_entropy_hmac_keys():
    with pytest.raises(CutoverGuardError, match="at least 32 bytes"):
        build_suppression_manifest([], b"short", "v1", confirmed_empty=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason", "soft_bounce"),
        ("effective_at", datetime(2026, 8, 29, 12, 0)),
        ("source_ref", ""),
    ],
)
def test_suppression_rejects_unknown_reason_naive_time_and_missing_source(field, value):
    candidate = {
        "source_namespace": "crm",
        "scope": "email",
        "value": "alice@example.com",
        "reason": "invalid_address",
        "source_ref": "record-1",
        "effective_at": datetime(2026, 8, 29, 12, 0, tzinfo=BEIJING),
    }
    candidate[field] = value
    with pytest.raises(CutoverGuardError):
        build_suppression_manifest([candidate], SUPPRESSION_HMAC_KEY, "v1")


def test_suppression_rejects_raw_identity_copied_into_source_metadata():
    candidate = {
        "source_namespace": "crm",
        "scope": "email",
        "value": "alice@example.com",
        "reason": "invalid_address",
        "source_ref": "email:alice@example.com",
        "effective_at": datetime(2026, 8, 29, 12, 0, tzinfo=BEIJING),
    }
    with pytest.raises(CutoverGuardError, match="raw suppression value"):
        build_suppression_manifest([candidate], SUPPRESSION_HMAC_KEY, "v1")


def test_verify_ready_fails_on_hash_mismatch_missing_writer_and_running_writer():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)

    assert verify_ready(inventory, _writer_manifest(), inventory.inventory_sha256) is True
    with pytest.raises(CutoverGuardError, match="inventory SHA-256"):
        verify_ready(inventory, _writer_manifest(), "0" * 64)
    with pytest.raises(CutoverGuardError, match="missing writer categories"):
        verify_ready(
            inventory,
            _writer_manifest(omitted=KNOWN_WRITER_CATEGORIES[-1]),
            inventory.inventory_sha256,
        )
    with pytest.raises(CutoverGuardError, match="still running"):
        verify_ready(
            inventory,
            _writer_manifest(running=KNOWN_WRITER_CATEGORIES[0]),
            inventory.inventory_sha256,
        )


def test_verify_ready_requires_stopped_public_pool_batch_writer():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)

    assert "public_pool_batch" in KNOWN_WRITER_CATEGORIES
    with pytest.raises(CutoverGuardError, match="missing writer categories"):
        verify_ready(
            inventory,
            _writer_manifest(omitted="public_pool_batch"),
            inventory.inventory_sha256,
        )
    with pytest.raises(CutoverGuardError, match="still running"):
        verify_ready(
            inventory,
            _writer_manifest(running="public_pool_batch"),
            inventory.inventory_sha256,
        )


def test_verify_ready_recomputes_inventory_content_before_trusting_supplied_hash():
    engine = _create_cutover_db()
    with Session(engine) as db:
        inventory = build_inventory(db)
    forged = replace(inventory, inventory_sha256="0" * 64)

    with pytest.raises(CutoverGuardError, match="inventory content"):
        verify_ready(forged, _writer_manifest(), forged.inventory_sha256)


def test_verify_after_table_state_requires_all_new_tables_and_no_retired_only_tables():
    engine = create_engine("sqlite:///:memory:")
    expected = NEW_CUSTOMER_TABLES + REBUILT_CUSTOMER_WORKFLOW_TABLES
    with engine.begin() as connection:
        for table_name in expected:
            connection.execute(text(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY)"))
    with Session(engine) as db:
        assert verify_expected_customer_table_state(db) is True
        db.execute(text("CREATE TABLE ark_sales_companies (id INTEGER PRIMARY KEY)"))
        with pytest.raises(CutoverGuardError, match="retired-only tables still exist"):
            verify_expected_customer_table_state(db)


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
    with pytest.raises(CutoverGuardError, match="safe roots"):
        script.resolve_safe_path(Path("../outside.json"))
    with pytest.raises(CutoverGuardError, match="absolute"):
        script.resolve_safe_path(Path("report.json"), safe_root=Path("relative-root"))
    output = script.resolve_safe_output_path(Path("reports/preflight.json"))
    assert output == REPO_ROOT / "tmp/customer-domain-cutover/reports/preflight.json"
    with pytest.raises(CutoverGuardError, match="output root"):
        script.resolve_safe_output_path(REPO_ROOT / "README.md")
    with pytest.raises(CutoverGuardError, match="dedicated evidence directory"):
        script.resolve_safe_output_path(Path("report.json"), safe_root=REPO_ROOT)


def test_safe_output_root_is_repo_contained_and_blocks_relative_traversal(tmp_path):
    script = _load_cutover_script()
    safe_root = REPO_ROOT / "tmp/explicit-cutover-evidence"
    expected = safe_root / "reports/preflight.json"

    assert (
        script.resolve_safe_output_path(
            Path("reports/preflight.json"), safe_root=safe_root
        )
        == expected
    )
    assert script.resolve_safe_path(Path("writers.json"), safe_root=safe_root) == (
        safe_root / "writers.json"
    )
    with pytest.raises(CutoverGuardError, match="root"):
        script.resolve_safe_output_path(
            Path("../escaped.json"), safe_root=safe_root
        )
    with pytest.raises(CutoverGuardError, match="root"):
        script.resolve_safe_path(Path("../escaped.json"), safe_root=safe_root)

    outside_root = tmp_path / "outside-cutover-evidence"
    with pytest.raises(CutoverGuardError, match="repository"):
        script.resolve_safe_output_path(Path("report.json"), safe_root=outside_root)
    with pytest.raises(CutoverGuardError, match="repository"):
        script.resolve_safe_path(Path("writers.json"), safe_root=outside_root)


def test_apply_reset_never_invokes_alembic_when_guard_or_marker_hash_fails(tmp_path):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    calls = []
    marker = tmp_path / "approved.json"
    marker.write_text(
        json.dumps({"approved": True, "inventory_sha256": "f" * 64}),
        encoding="utf-8",
    )

    with Session(engine) as db, pytest.raises(CutoverGuardError):
        script.apply_reset(
            db=db,
            stopped_writer_manifest=_writer_manifest(),
            expected_inventory_sha256="0" * 64,
            approved_marker_path=marker,
            subprocess_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []


def test_apply_reset_invokes_only_alembic_upgrade_head_after_both_hashes_bind(tmp_path):
    script = _load_cutover_script()
    engine = _create_cutover_db()
    calls = []
    with Session(engine) as db:
        inventory = build_inventory(db)
        marker = tmp_path / "approved.json"
        marker.write_text(
            json.dumps(
                {
                    "approved": True,
                    "inventory_sha256": inventory.inventory_sha256,
                }
            ),
            encoding="utf-8",
        )
        def capture_runner(*args, **kwargs):
            assert db.in_transaction() is False
            calls.append((args, kwargs))

        result = script.apply_reset(
            db=db,
            stopped_writer_manifest=_writer_manifest(),
            expected_inventory_sha256=inventory.inventory_sha256,
            approved_marker_path=marker,
            subprocess_runner=capture_runner,
        )

    assert result.inventory_sha256 == inventory.inventory_sha256
    assert len(calls) == 1
    command = calls[0][0][0]
    assert command[-4:] == ["-m", "alembic", "upgrade", "head"]
    assert calls[0][1]["check"] is True
    assert calls[0][1]["cwd"] == REPO_ROOT / "backend"
