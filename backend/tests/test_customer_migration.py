"""Revision 126 customer-domain destructive migration contract tests.

These tests deliberately treat the approved design document as an independent
authority.  Expected table names are literal here; field names and comments are
parsed from the approved dictionaries rather than imported from production
constants.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.customer.cutover_service import (
    CutoverGuardError,
    canonical_json_bytes,
)
from app.customer.models import CORE_TABLES as ORM_CORE_TABLES


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
MIGRATION_PATH = BACKEND_ROOT / "alembic/versions/126_unified_customer_domain.py"
DESIGN_PATH = (
    REPO_ROOT
    / "docs/requirements/2026-08-28-unified-customer-profile-design.md"
)
CUTOVER_SCRIPT_PATH = REPO_ROOT / "scripts/customer_domain_cutover.py"

CORE_TABLES = {
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
    "ark_customer_agent_run_scopes",
    "ark_customer_suppression_registry",
    "ark_customer_resolution_keys",
    "ark_customer_target_matches",
    "ark_customer_acquisition_attributions",
}
WORKFLOW_TABLES = {
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_public_pool_batches",
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_actions",
}
RETIRED_OR_REBUILT_TABLES = (
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
TARGET_PROFILE_COLUMNS = {
    "policy_version": "策略版本",
    "policy_json": "target_profile_policy_v1阈值、权重、研究与领取规则",
    "policy_snapshot_hash": "规范快照SHA-256",
    "last_improvement_artifact_id": "最近人工批准改进Artifact",
    "policy_applied_at": "策略生效北京时间",
}
GENERATED_COLUMNS = {
    ("ark_customer_external_identities", "primary_identity_slot"),
    ("ark_customer_external_identities", "verified_strong_key"),
    ("ark_customer_relationships", "active_relation_key"),
    ("ark_customer_assignments", "active_assignment_key"),
    ("ark_customer_assignments", "active_primary_slot"),
    ("ark_customer_contact_points", "primary_point_slot"),
    ("ark_customer_contact_relationships", "active_relation_key"),
    ("ark_customer_annotations", "active_dnc_key"),
    ("ark_customer_qualification_reviews", "current_scope_slot"),
    ("ark_customer_suppression_registry", "active_suppression_key"),
    ("ark_customer_target_matches", "current_match_slot"),
}


def _load_migration():
    spec = importlib.util.spec_from_file_location("revision_126", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_cutover_script():
    spec = importlib.util.spec_from_file_location(
        "revision_126_cutover_script", CUTOVER_SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _design_contract() -> dict[str, dict[str, object]]:
    text = DESIGN_PATH.read_text(encoding="utf-8")
    headings = list(
        re.finditer(
            r"^(?:### 7\.\d+|####) (ark_(?:customer|sales)_[a-z0-9_]+)\s*$",
            text,
            re.MULTILINE,
        )
    )
    contract: dict[str, dict[str, object]] = {}
    wanted = CORE_TABLES | WORKFLOW_TABLES
    for index, heading in enumerate(headings):
        table_name = heading.group(1)
        if table_name not in wanted:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end() : end]
        table_comment_match = re.search(r"表备注：(.+)", section)
        assert table_comment_match, table_name
        columns: dict[str, dict[str, str]] = {}
        for line in section.splitlines():
            if not line.startswith("|") or line.startswith("|---") or "| 字段 |" in line:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 5:
                continue
            columns[cells[0].strip("`")] = {
                "type": cells[1].replace("`", ""),
                "nullable": cells[2],
                "constraints": cells[3].replace("`", ""),
                "comment": cells[4].replace("`", ""),
            }
        contract[table_name] = {
            "table_comment": table_comment_match.group(1).strip(),
            "columns": columns,
        }
    assert set(contract) == wanted
    return contract


def _normalized_mysql_type(column) -> str:
    compiled = column.type.dialect_impl(mysql.dialect()).compile(
        dialect=mysql.dialect()
    )
    normalized = " ".join(str(compiled).upper().split())
    normalized = normalized.replace("INTEGER", "INT").replace("NUMERIC", "DECIMAL")
    normalized = re.sub(r",\s+", ",", normalized)
    return "BOOLEAN" if normalized == "BOOL" else normalized


def _design_base_type(type_text: str) -> str:
    normalized = " ".join(type_text.upper().split())
    normalized = normalized.split(" AS (", 1)[0]
    normalized = normalized.replace("INTEGER", "INT").replace("NUMERIC", "DECIMAL")
    return re.sub(r",\s+", ",", normalized)


def _normalized_expression(value: object) -> str:
    return " ".join(str(value).strip().split())


def _offline_mysql_sql(callback) -> str:
    output = StringIO()
    migration_context = MigrationContext.configure(
        dialect_name="mysql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(migration_context):
        callback()
    return output.getvalue()


def test_revision_chain_and_literal_scope_are_frozen():
    migration = _load_migration()

    assert migration.revision == "126"
    assert migration.down_revision == "125_invoice_integration"
    assert len(migration.revision) <= 32
    assert set(migration.TARGET_TABLE_NAMES) == CORE_TABLES | WORKFLOW_TABLES
    assert tuple(migration.RETIRED_OR_REBUILT_TABLES) == RETIRED_OR_REBUILT_TABLES
    assert migration.TARGET_PROFILE_COLUMNS == TARGET_PROFILE_COLUMNS


def test_frozen_metadata_matches_approved_design_names_and_comments():
    migration = _load_migration()
    expected = _design_contract()

    assert set(migration.TARGET_METADATA.tables) == CORE_TABLES | WORKFLOW_TABLES
    for table_name, approved in expected.items():
        table = migration.TARGET_METADATA.tables[table_name]
        assert tuple(table.c.keys()) == tuple(approved["columns"]), table_name
        assert table.comment == approved["table_comment"], table_name
        for column_name, column_contract in approved["columns"].items():
            assert table.c[column_name].comment == column_contract["comment"], (
                f"{table_name}.{column_name}"
            )


def test_frozen_metadata_matches_design_types_nullability_and_generated_expressions():
    migration = _load_migration()
    expected = _design_contract()

    for table_name, approved in expected.items():
        table = migration.TARGET_METADATA.tables[table_name]
        for column_name, column_contract in approved["columns"].items():
            column = table.c[column_name]
            assert _normalized_mysql_type(column) == _design_base_type(
                column_contract["type"]
            ), f"{table_name}.{column_name}"
            assert column.nullable is (column_contract["nullable"] == "是"), (
                f"{table_name}.{column_name}"
            )
            generated = re.search(
                r" AS \((.*)\) STORED$", column_contract["type"], re.IGNORECASE
            )
            if generated:
                assert column.computed is not None, f"{table_name}.{column_name}"
                assert column.computed.persisted is True, f"{table_name}.{column_name}"
                assert _normalized_expression(column.computed.sqltext) == (
                    _normalized_expression(generated.group(1))
                ), f"{table_name}.{column_name}"
            else:
                assert column.computed is None, f"{table_name}.{column_name}"


def test_frozen_core_metadata_independently_matches_all_31_orm_contracts():
    migration = _load_migration()

    def unique_columns(table):
        return {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, migration.sa.UniqueConstraint)
        }

    def indexed_columns(table):
        return {
            (tuple(column.name for column in index.columns), bool(index.unique))
            for index in table.indexes
        }

    def foreign_keys(table):
        return {
            (
                tuple(element.parent.name for element in constraint.elements),
                tuple(
                    (element.column.table.name, element.column.name)
                    for element in constraint.elements
                ),
                constraint.ondelete,
                constraint.onupdate,
            )
            for constraint in table.constraints
            if isinstance(constraint, migration.sa.ForeignKeyConstraint)
        }

    for table_name in CORE_TABLES:
        orm_table = ORM_CORE_TABLES[table_name]
        frozen_table = migration.TARGET_METADATA.tables[table_name]
        assert tuple(frozen_table.c.keys()) == tuple(orm_table.c.keys()), table_name
        for column_name in orm_table.c.keys():
            orm_column = orm_table.c[column_name]
            frozen_column = frozen_table.c[column_name]
            assert frozen_column.nullable == orm_column.nullable, (
                f"{table_name}.{column_name}"
            )
            assert frozen_column.comment == orm_column.comment, (
                f"{table_name}.{column_name}"
            )
            if (table_name, column_name) not in GENERATED_COLUMNS:
                assert _normalized_mysql_type(frozen_column) == (
                    _normalized_mysql_type(orm_column)
                ), f"{table_name}.{column_name}"
        assert unique_columns(frozen_table) == unique_columns(orm_table), table_name
        assert indexed_columns(orm_table) <= indexed_columns(frozen_table), table_name
        expected_foreign_keys = foreign_keys(orm_table)
        actual_foreign_keys = foreign_keys(frozen_table)
        assert expected_foreign_keys <= actual_foreign_keys, table_name
        if table_name != "ark_customer_acquisition_attributions":
            assert actual_foreign_keys == expected_foreign_keys, table_name


def test_all_target_tables_compile_as_mysql_ddl_with_comments_and_contracts():
    migration = _load_migration()

    for table_name in migration.TARGET_TABLE_NAMES:
        table = migration.TARGET_METADATA.tables[table_name]
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "COMMENT" in ddl, table_name
        assert len(table.primary_key.columns) >= 1, table_name
        assert all(column.comment for column in table.c), table_name
        for constraint in table.constraints:
            if constraint.__class__.__name__ != "PrimaryKeyConstraint":
                assert constraint.name, f"{table_name}:{constraint}"
                assert len(constraint.name) <= 64
        for index in table.indexes:
            assert index.name and len(index.name) <= 64
            str(CreateIndex(index).compile(dialect=mysql.dialect()))


def test_every_foreign_key_has_an_explicit_stable_mysql_supporting_index():
    migration = _load_migration()

    for table_name, table in migration.TARGET_METADATA.tables.items():
        indexed_prefixes = [
            tuple(column.name for column in index.columns) for index in table.indexes
        ]
        indexed_prefixes.extend(
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(
                constraint,
                (migration.sa.PrimaryKeyConstraint, migration.sa.UniqueConstraint),
            )
        )
        for foreign_key in (
            constraint
            for constraint in table.constraints
            if isinstance(constraint, migration.sa.ForeignKeyConstraint)
        ):
            local_columns = tuple(
                element.parent.name for element in foreign_key.elements
            )
            assert any(
                columns[: len(local_columns)] == local_columns
                for columns in indexed_prefixes
            ), f"{table_name}.{foreign_key.name}"


def test_alembic_operations_compile_the_complete_38_table_mysql_ddl():
    migration = _load_migration()

    sql = _offline_mysql_sql(migration._create_target_tables)

    assert len(re.findall(r"^CREATE TABLE ", sql, re.MULTILINE)) == 38
    assert set(re.findall(r"CREATE TABLE (ark_[a-z0-9_]+)", sql)) == (
        CORE_TABLES | WORKFLOW_TABLES
    )
    assert "GENERATED ALWAYS AS" in sql
    assert " STORED" in sql
    assert sql.count("COMMENT") >= 38
    expected_indexes = sum(
        len(table.indexes) for table in migration.TARGET_METADATA.tables.values()
    )
    expected_foreign_keys = sum(
        isinstance(constraint, migration.sa.ForeignKeyConstraint)
        for table in migration.TARGET_METADATA.tables.values()
        for constraint in table.constraints
    )
    expected_checks = sum(
        isinstance(constraint, migration.sa.CheckConstraint)
        for table in migration.TARGET_METADATA.tables.values()
        for constraint in table.constraints
    )
    assert len(re.findall(r"^CREATE (?:UNIQUE )?INDEX ", sql, re.MULTILINE)) == (
        expected_indexes
    )
    assert len(re.findall(r"^ALTER TABLE .* FOREIGN KEY", sql, re.MULTILINE)) == (
        expected_foreign_keys
    )
    assert sql.count("CHECK (") == expected_checks


def test_generated_columns_are_real_stored_mysql_columns():
    migration = _load_migration()
    actual = {
        (table.name, column.name)
        for table in migration.TARGET_METADATA.tables.values()
        for column in table.c
        if column.computed is not None
    }

    assert actual == GENERATED_COLUMNS
    for table_name, column_name in actual:
        computed = migration.TARGET_METADATA.tables[table_name].c[column_name].computed
        assert computed.persisted is True


def test_physical_contract_is_complete_hashed_and_not_a_runtime_placeholder():
    migration = _load_migration()
    contract = migration.PHYSICAL_SCHEMA_CONTRACT

    assert contract["migration_revision"] == "126"
    assert set(contract["tables"]) == CORE_TABLES | WORKFLOW_TABLES
    assert migration.validate_customer_physical_schema_contract(contract) == contract[
        "contract_sha256"
    ]
    for table_name, signature in contract["tables"].items():
        assert set(signature) == {
            "columns",
            "primary_key",
            "unique_constraints",
            "indexes",
            "foreign_keys",
            "checks",
            "table_comment",
        }, table_name
        assert all(column["comment"] for column in signature["columns"]), table_name


def test_runtime_model_dependency_is_pinned_by_a_literal_frozen_signature():
    migration = _load_migration()

    assert re.fullmatch(r"[0-9a-f]{64}", migration.FROZEN_TARGET_SCHEMA_SHA256)
    assert migration.PHYSICAL_SCHEMA_CONTRACT["contract_sha256"] == (
        migration.FROZEN_TARGET_SCHEMA_SHA256
    )

    if "APPROVED_CORE_TABLES" in inspect.getsource(migration._build_target_metadata):
        table = migration.APPROVED_CORE_TABLES["ark_customer_accounts"]
        original_comment = table.comment
        table.comment = f"{original_comment}-mutated"
        try:
            with pytest.raises(CutoverGuardError, match="frozen.*schema"):
                migration._build_target_metadata()
        finally:
            table.comment = original_comment


def test_physical_contract_hash_is_process_stable_and_computed_has_no_default():
    first = _load_migration().PHYSICAL_SCHEMA_CONTRACT
    second = _load_migration().PHYSICAL_SCHEMA_CONTRACT

    assert first["contract_sha256"] == second["contract_sha256"]
    for signature in first["tables"].values():
        for column in signature["columns"]:
            if column["computed"] is not None:
                assert column["default"] is None

    command = (
        "import importlib.util,pathlib;"
        "p=pathlib.Path('alembic/versions/126_unified_customer_domain.py');"
        "s=importlib.util.spec_from_file_location('revision_126_subprocess',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "print(m.PHYSICAL_SCHEMA_CONTRACT['contract_sha256'])"
    )
    subprocess_hash = subprocess.check_output(
        [sys.executable, "-c", command],
        cwd=BACKEND_ROOT,
        text=True,
    ).strip()
    assert subprocess_hash == first["contract_sha256"]


def test_physical_contract_preserves_mysql_signedness():
    migration = _load_migration()

    def column_contract(table_name: str, column_name: str):
        return next(
            column
            for column in migration.PHYSICAL_SCHEMA_CONTRACT["tables"][table_name][
                "columns"
            ]
            if column["name"] == column_name
        )

    assert column_contract("ark_customer_assignments", "user_id")["type"][
        "unsigned"
    ] is True
    assert column_contract("ark_customer_assignments", "customer_id")["type"][
        "unsigned"
    ] is False
    assert column_contract("ark_customer_assignments", "active_primary_slot")[
        "type"
    ]["name"] == "TINYINT"


def test_upgrade_source_fails_closed_before_any_destructive_statement():
    migration = _load_migration()
    source = inspect.getsource(migration.upgrade)
    lowered = source.lower()

    assert "truncate" not in lowered
    assert "drop_all" not in lowered
    assert "delete from ark_agent_" not in lowered
    assert source.index("_load_cutover_contract") < source.index("bootstrap_migration_fence")
    assert source.index("bootstrap_migration_fence") < source.index("migration_preflight")
    assert source.index("migration_preflight") < source.index("_delete_agent_history_closure")
    assert source.index("_delete_agent_history_closure") < source.index("_drop_retired_tables")
    assert source.index("_drop_retired_tables") < source.index("_create_target_tables")
    assert source.index("_create_target_tables") < source.index(
        "verify_expected_customer_table_state"
    )
    assert source.index("verify_expected_customer_table_state") < source.index(
        "_write_success_receipt"
    )


def test_direct_alembic_upgrade_without_contract_fails_before_getting_a_bind(
    monkeypatch,
):
    migration = _load_migration()
    bind_calls: list[str] = []
    monkeypatch.setattr(
        migration.context,
        "get_x_argument",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: bind_calls.append("bind"),
    )

    with pytest.raises(CutoverGuardError, match="customer_cutover_contract"):
        migration.upgrade()
    assert bind_calls == []


def test_upgrade_rejects_a_bound_physical_contract_that_differs_from_frozen_ddl(
    monkeypatch,
):
    migration = _load_migration()
    mismatched = copy.deepcopy(migration.PHYSICAL_SCHEMA_CONTRACT)
    mismatched["tables"]["ark_customer_accounts"]["table_comment"] += "-tampered"
    payload = {
        key: value for key, value in mismatched.items() if key != "contract_sha256"
    }
    mismatched["contract_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    calls: list[str] = []

    monkeypatch.setattr(migration, "_load_cutover_contract", lambda: {"approved": True})
    monkeypatch.setattr(
        migration,
        "load_bound_customer_physical_schema_contract",
        lambda _contract: mismatched,
    )
    monkeypatch.setattr(
        migration,
        "bootstrap_migration_fence",
        lambda *_args, **_kwargs: calls.append("fence"),
    )

    with pytest.raises(CutoverGuardError, match="bound physical schema contract"):
        migration.upgrade()
    assert calls == []


def test_upgrade_uses_explicit_beijing_receipt_timestamps():
    migration = _load_migration()
    source = inspect.getsource(migration.upgrade)

    assert "beijing_now_aware()" in source


def test_success_receipt_exactly_matches_cutover_validator_and_never_overwrites(
    tmp_path,
    monkeypatch,
):
    migration = _load_migration()
    script = _load_cutover_script()
    backend_root = tmp_path / "backend"
    evidence_root = backend_root / "tmp/customer-domain-cutover"
    evidence_root.mkdir(parents=True)
    monkeypatch.setattr(migration, "CUTOVER_EVIDENCE_ROOT", evidence_root)
    monkeypatch.setattr(script, "BACKEND_ROOT", backend_root)
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(script, "EVIDENCE_ROOT", evidence_root)

    beijing = ZoneInfo("Asia/Shanghai")
    started_at = datetime(2026, 8, 30, 9, 0, tzinfo=beijing)
    completed_at = started_at + timedelta(seconds=1)
    monkeypatch.setattr(migration, "beijing_now_aware", lambda: completed_at)
    nonce = "receipt-contract-20260830"
    receipt_path = evidence_root / f"migration-receipt-{nonce}.json"
    contract = {
        "inventory_sha256": "1" * 64,
        "preflight_report_sha256": "2" * 64,
        "suppression_manifest_sha256": "3" * 64,
        "writer_manifest_sha256": "4" * 64,
        "approved_marker_sha256": "5" * 64,
        "maintenance_fence_artifact_sha256": "6" * 64,
        "instance_inventory_artifact_sha256": "7" * 64,
        "physical_schema_contract_sha256": migration.FROZEN_TARGET_SCHEMA_SHA256,
        "nonce": nonce,
        "contract_path": str(evidence_root / f"migration-contract-{nonce}.json"),
        "receipt_path": receipt_path.name,
        "migration_revision": "126",
        "issued_at": (started_at - timedelta(seconds=1)).isoformat(),
        "expires_at": (completed_at + timedelta(minutes=2)).isoformat(),
    }
    contract["contract_sha256"] = hashlib.sha256(
        canonical_json_bytes(contract)
    ).hexdigest()

    migration._write_success_receipt(contract, started_at)
    receipt = json.loads(receipt_path.read_bytes())

    assert script.validate_execution_receipt(
        receipt,
        evidence_contract=contract,
        receipt_resolved_path=receipt_path,
    ) is True
    with pytest.raises(CutoverGuardError, match="receipt write failed"):
        migration._write_success_receipt(contract, started_at)


def test_target_profile_alterations_compile_comments_backfill_and_constraints():
    migration = _load_migration()

    sql = _offline_mysql_sql(migration._alter_target_profiles)

    for column_name, comment in TARGET_PROFILE_COLUMNS.items():
        assert re.search(
            rf"ADD COLUMN {column_name} .*COMMENT '{re.escape(comment)}'", sql
        ), column_name
    assert "UPDATE ark_sales_target_profiles SET" in sql
    assert "policy_snapshot_hash" in sql
    assert sql.count("NOT NULL") >= 4
    assert "ix_sales_target_profile_last_improvement_artifact" in sql
    assert "fk_sales_target_profile_improvement_artifact" in sql


def test_drop_scope_is_exact_and_dependency_safe():
    migration = _load_migration()

    assert len(migration.DROP_ORDER) == 17
    assert set(migration.DROP_ORDER) == set(RETIRED_OR_REBUILT_TABLES)
    assert len(set(migration.DROP_ORDER)) == len(migration.DROP_ORDER)
    upgrade_source = inspect.getsource(migration.upgrade)
    assert upgrade_source.index("_drop_foreign_keys_into_retired") < (
        upgrade_source.index("_drop_retired_tables")
    )


def test_agent_deletion_is_exact_ordered_and_chunked():
    migration = _load_migration()
    source = inspect.getsource(migration._delete_agent_history_closure)

    assert migration.AGENT_DELETE_ORDER == (
        ("ark_agent_artifacts", "artifact_ids"),
        ("ark_agent_events", "event_ids"),
        ("ark_agent_runs", "run_ids"),
        ("ark_agent_sessions", "session_ids"),
    )
    assert "AGENT_ID_QUERY_CHUNK_SIZE" in source
    assert ".where(table.c.id.in_(chunk))" in source
    assert "ark_agent_profiles" not in source


def test_downgrade_is_explicitly_unsupported():
    migration = _load_migration()

    with pytest.raises(RuntimeError, match="destructive.*unsupported"):
        migration.downgrade()
