import importlib
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect as sqlalchemy_inspect,
    insert,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.core.database import Base
from app.core import time as core_time
from app.customer import models


EXPECTED_TABLES = {
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

DEFERRED_WORKFLOW_TABLES = {
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_actions",
}

ACQUISITION_WORKFLOW_TABLES = {
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_public_pool_batches",
}

GENERATED_SLOT_COLUMNS = {
    "ark_customer_external_identities": (
        "primary_identity_slot",
        "verified_strong_key",
    ),
    "ark_customer_relationships": ("active_relation_key",),
    "ark_customer_assignments": (
        "active_assignment_key",
        "active_primary_slot",
    ),
    "ark_customer_contact_points": ("primary_point_slot",),
    "ark_customer_contact_relationships": ("active_relation_key",),
    "ark_customer_annotations": ("active_dnc_key",),
    "ark_customer_qualification_reviews": ("current_scope_slot",),
    "ark_customer_suppression_registry": ("active_suppression_key",),
    "ark_customer_target_matches": ("current_match_slot",),
}

DESIGN_PATH = (
    Path(__file__).parents[2]
    / "docs/requirements/2026-08-28-unified-customer-profile-design.md"
)
SCHEMA_126_PATH = (
    Path(__file__).parents[1]
    / "alembic/versions/126_unified_customer_domain_schema.json"
)


def _design_tables():
    text = DESIGN_PATH.read_text(encoding="utf-8")
    section = text.split("## 7. 目标数据表与字段字典", 1)[1].split(
        "## 8. 偏好与行为的四层模型", 1
    )[0]
    tables = {}
    matches = list(re.finditer(r"^### 7\.(\d+) (ark_customer_[a-z_]+)$", section, re.M))
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        body = section[body_start:body_end]
        table_comment = re.search(r"^表备注：(.+)$", body, re.M).group(1)
        fields = {}
        for row in re.finditer(
            r"^\| ([a-z][a-z0-9_]*) \| (.+?) \| (是|否) \|\s*(.*?)\s*\| (.+?) \|$",
            body,
            re.M,
        ):
            fields[row.group(1)] = {
                "type": row.group(2),
                "nullable": row.group(3) == "是",
                "constraint": row.group(4),
                "comment": row.group(5),
            }
        tables[match.group(2)] = {"comment": table_comment, "fields": fields}
    return tables


def _module_models():
    return tuple(models.CORE_MODELS)


def _workflow_contract_tables():
    payload = json.loads(SCHEMA_126_PATH.read_text(encoding="utf-8"))
    tables = payload["customer_domain_physical_contract"]["tables"]
    return {name: tables[name] for name in ACQUISITION_WORKFLOW_TABLES}


def _unique_column_sets(table):
    unique_sets = {
        (column.name,)
        for column in table.columns
        if column.unique
    }
    unique_sets.update(
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    return unique_sets


def _fk_signatures(table):
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _assert_design_type(column, design_type):
    if " AS (" in design_type:
        assert isinstance(column.type, String)
        assert column.info.get("read_only") is True
        return
    if design_type == "BIGINT":
        assert isinstance(column.type, BigInteger)
    elif design_type == "INT UNSIGNED":
        assert column.type.compile(dialect=mysql.dialect()) == "INTEGER UNSIGNED"
    elif design_type == "INT":
        assert isinstance(column.type, Integer)
    elif design_type.startswith("VARCHAR("):
        assert isinstance(column.type, String)
        assert column.type.length == int(re.search(r"\d+", design_type).group())
    elif design_type.startswith("CHAR("):
        assert isinstance(column.type, String)
        assert column.type.length == int(re.search(r"\d+", design_type).group())
        assert column.type.compile(dialect=mysql.dialect()).startswith("CHAR(")
    elif design_type.startswith("DECIMAL("):
        precision, scale = map(int, re.findall(r"\d+", design_type))
        assert isinstance(column.type, Numeric)
        assert (column.type.precision, column.type.scale) == (precision, scale)
    elif design_type == "DATETIME":
        assert isinstance(column.type, DateTime)
    elif design_type == "DATE":
        assert isinstance(column.type, Date)
    elif design_type == "BOOLEAN":
        assert isinstance(column.type, Boolean)
    elif design_type == "JSON":
        assert isinstance(column.type, JSON)
    elif design_type in {"TEXT", "LONGTEXT"}:
        assert isinstance(column.type, Text)
    else:
        raise AssertionError(f"unhandled design type: {design_type}")


def test_customer_module_supplies_exactly_the_31_core_tables():
    module_models = _module_models()

    assert len(module_models) == 31
    assert {model.__tablename__ for model in module_models} == EXPECTED_TABLES
    assert set(models.CORE_TABLE_NAMES) == EXPECTED_TABLES
    assert not (set(models.CORE_TABLE_NAMES) & DEFERRED_WORKFLOW_TABLES)


def test_customer_module_supplies_exactly_the_4_acquisition_workflow_tables():
    workflow_models = tuple(models.ACQUISITION_WORKFLOW_MODELS)

    assert len(workflow_models) == 4
    assert {model.__tablename__ for model in workflow_models} == ACQUISITION_WORKFLOW_TABLES
    assert set(models.ACQUISITION_WORKFLOW_TABLES) == ACQUISITION_WORKFLOW_TABLES
    assert not (set(models.CORE_TABLE_NAMES) & ACQUISITION_WORKFLOW_TABLES)


def test_acquisition_workflow_tables_match_frozen_126_contract():
    contract_tables = _workflow_contract_tables()

    for model in models.ACQUISITION_WORKFLOW_MODELS:
        table = model.__table__
        expected = contract_tables[table.name]
        expected_columns = {column["name"]: column for column in expected["columns"]}
        assert table.comment == expected["table_comment"]
        assert set(table.columns.keys()) == set(expected_columns)
        for column in table.columns:
            frozen = expected_columns[column.name]
            assert column.comment == frozen["comment"]
            assert column.nullable is frozen["nullable"]
            assert column.primary_key is frozen["primary_key"]

        check_names = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        unique_signatures = {
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        fk_signatures = {
            (
                constraint.name,
                tuple(element.parent.name for element in constraint.elements),
                tuple(element.target_fullname for element in constraint.elements),
            )
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        index_signatures = {
            (index.name, index.unique, tuple(column.name for column in index.columns))
            for index in table.indexes
        }
        assert check_names == {item[0] for item in expected["checks"]}
        assert unique_signatures == {
            (item[0], tuple(item[1])) for item in expected["unique_constraints"]
        }
        assert fk_signatures == {
            (
                item[0],
                tuple(item[1]),
                tuple(f"{item[3]}.{column}" for column in item[4]),
            )
            for item in expected["foreign_keys"]
        }
        assert index_signatures == {
            (item[0], item[1], tuple(item[2])) for item in expected["indexes"]
        }


def test_every_core_table_matches_the_approved_field_dictionary_and_comments():
    design_tables = _design_tables()

    assert set(design_tables) == EXPECTED_TABLES
    for model in _module_models():
        table = model.__table__
        expected = design_tables[table.name]
        assert table.comment == expected["comment"]
        assert set(table.columns.keys()) == set(expected["fields"])
        unique_sets = _unique_column_sets(table)
        indexed_columns = {
            column.name
            for index in table.indexes
            for column in index.columns
        }
        for column in table.columns:
            field = expected["fields"][column.name]
            assert column.comment == field["comment"]
            assert column.nullable is field["nullable"]
            _assert_design_type(column, field["type"])
            if "INDEX" in field["constraint"]:
                assert column.name in indexed_columns
            if field["constraint"] == "UNIQUE":
                assert (column.name,) in unique_sets


def test_critical_enum_json_amount_and_business_time_comments_are_explicit():
    accounts = models.CustomerAccount.__table__.c
    facts = models.CustomerFact.__table__.c
    contexts = models.CustomerAgentContext.__table__.c
    messages = models.CustomerMessage.__table__.c
    orders = models.CustomerOrder.__table__.c
    research = models.CustomerResearchTask.__table__.c

    assert all(value in accounts.entity_type.comment for value in (
        "registered_company", "sole_proprietor", "individual_business", "unknown"
    ))
    assert all(value in facts.fact_layer.comment for value in (
        "source", "expressed", "observed", "inferred", "confirmed"
    ))
    assert "customer_profile_v1" in models.CustomerProfileVersion.__table__.c.profile_json.comment
    assert "customer_context_v1" in contexts.context_json.comment
    assert "file_name" in messages.attachment_meta_json.comment
    assert "currency" in facts.value_json.comment and "unit" in facts.value_json.comment
    assert "美元" in orders.amount_usd.comment
    assert "原币种" in orders.amount_original.comment
    assert "北京时间" in accounts.relationship_stage_changed_at.comment
    assert "北京时间" in research.lease_expires_at.comment


def test_company_name_is_nullable_and_never_a_unique_identity():
    column = models.CustomerAccount.__table__.c.canonical_company_name

    assert column.nullable is True
    assert column.unique is not True
    assert (column.name,) not in _unique_column_sets(models.CustomerAccount.__table__)


def test_external_identity_has_xor_check_and_read_only_strong_slots():
    table = models.CustomerExternalIdentity.__table__
    checks = {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert any("customer_id IS NULL" in check and "contact_id IS NULL" in check for check in checks)
    assert {"primary_identity_slot", "verified_strong_key"} <= set(table.columns.keys())
    for name in ("primary_identity_slot", "verified_strong_key"):
        column = table.c[name]
        assert column.nullable is True
        assert column.info == {"read_only": True, "mysql_generated": True}
        assert (name,) in _unique_column_sets(table)


def test_generated_slots_and_deferred_workflow_ids_use_exact_business_comments():
    exact_columns = {
        **GENERATED_SLOT_COLUMNS,
        "ark_customer_acquisition_attributions": (
            "search_job_id",
            "opportunity_id",
        ),
    }
    design_tables = _design_tables()

    for table_name, column_names in exact_columns.items():
        table = models.CORE_TABLES[table_name]
        for column_name in column_names:
            assert table.c[column_name].comment == (
                design_tables[table_name]["fields"][column_name]["comment"]
            )


@pytest.mark.parametrize("explicit_value", [None, "caller-supplied-slot"])
def test_generated_slots_reject_every_explicit_orm_assignment(explicit_value):
    models_by_table = {model.__tablename__: model for model in models.CORE_MODELS}

    for table_name, column_names in GENERATED_SLOT_COLUMNS.items():
        model = models_by_table[table_name]
        for column_name in column_names:
            with pytest.raises(ValueError, match=column_name):
                model(**{column_name: explicit_value})


def _required_insert_values(table, excluded):
    values = {}
    now = core_time.beijing_now()
    for column in table.columns:
        if column.name in excluded or column.nullable or column.default is not None:
            continue
        if column.primary_key and column is table.autoincrement_column:
            continue
        if isinstance(column.type, Boolean):
            values[column.name] = False
        elif isinstance(column.type, DateTime):
            values[column.name] = now
        elif isinstance(column.type, Date):
            values[column.name] = now.date()
        elif isinstance(column.type, JSON):
            values[column.name] = {}
        elif isinstance(column.type, (BigInteger, Integer, Numeric)):
            values[column.name] = 1
        else:
            values[column.name] = "x"
    return values


def test_normal_compiled_inserts_omit_all_generated_slots():
    for table_name, column_names in GENERATED_SLOT_COLUMNS.items():
        table = models.CORE_TABLES[table_name]
        statement = insert(table).values(
            **_required_insert_values(table, set(column_names))
        )
        sql = str(statement.compile(dialect=mysql.dialect()))
        for column_name in column_names:
            assert column_name not in sql


def _new_account():
    return models.CustomerAccount(
        customer_code="CUST-TEST-001",
        display_name="Autoincrement Test",
        entity_type="unknown",
        identity_status="provisional",
        relationship_stage="discovered",
        relationship_stage_changed_at=core_time.beijing_now(),
        relationship_stage_reason="created",
        record_status="active",
        identity_confidence=0,
        profile_completeness=0,
        profile_input_seq=0,
    )


def test_account_primary_key_autoincrements_despite_composite_profile_fk():
    table = models.CustomerAccount.__table__
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))

    assert table.autoincrement_column is table.c.id
    assert re.search(r"\bid BIGINT NOT NULL[^\n]*AUTO_INCREMENT\b", ddl)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=list(models.CORE_TABLES.values()))
    with Session(engine) as session:
        account = _new_account()
        session.add(account)
        session.flush()
        assert isinstance(account.id, int)
        assert account.id > 0


def test_generated_slots_are_omitted_on_flush_and_refresh_loads_physical_nulls():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=list(models.CORE_TABLES.values()))
    assignment_inserts = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture_assignment_insert(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("INSERT INTO ark_customer_assignments"):
            assignment_inserts.append(statement)

    with Session(engine) as session:
        account = _new_account()
        session.add(account)
        session.flush()
        assignment = models.CustomerAssignment(
            customer_id=account.id,
            user_id=1,
            assignment_role="primary",
            assignment_status="active",
            assignment_source="manual",
            effective_from=core_time.beijing_now(),
        )
        session.add(assignment)
        session.flush()

        assert len(assignment_inserts) == 1
        assert "active_assignment_key" not in assignment_inserts[0]
        assert "active_primary_slot" not in assignment_inserts[0]
        session.expire(assignment)
        session.refresh(assignment)
        assert assignment.active_assignment_key is None
        assert assignment.active_primary_slot is None


def test_assignment_has_one_current_primary_unique_slot():
    table = models.CustomerAssignment.__table__

    assert table.c.active_primary_slot.info["read_only"] is True
    assert ("active_assignment_key",) in _unique_column_sets(table)
    assert ("customer_id", "active_primary_slot") in _unique_column_sets(table)


def test_core_composite_unique_constraints_preserve_scope_and_identity():
    expected = {
        models.CustomerSourceRecord: {("external_record_key_hash", "content_hash")},
        models.CustomerProfileVersion: {
            ("customer_id", "version_no"),
            ("customer_id", "profile_fingerprint"),
            ("id", "customer_id"),
        },
        models.CustomerConversation: {
            ("source_system", "source_account_key", "external_conversation_id")
        },
        models.CustomerMessage: {("conversation_id", "external_message_id")},
        models.CustomerConversationAnalysis: {
            ("conversation_id", "version_no"),
            ("conversation_id", "analysis_fingerprint"),
        },
        models.CustomerOrder: {
            ("source_system", "source_account_key", "external_order_id"),
            ("id", "customer_id"),
        },
        models.CustomerOrderItem: {("order_id", "item_fingerprint")},
        models.CustomerSyncCursor: {("source_system", "resource_type", "scope_key")},
    }
    for model, unique_sets in expected.items():
        assert unique_sets <= _unique_column_sets(model.__table__)


def test_profile_consumers_enforce_same_customer_composite_foreign_keys():
    accounts = _fk_signatures(models.CustomerAccount.__table__)
    assert (
        ("current_profile_version_id", "id"),
        ("ark_customer_profile_versions.id", "ark_customer_profile_versions.customer_id"),
    ) in accounts

    for model in (
        models.CustomerAgentContext,
        models.CustomerListProjection,
        models.CustomerChangeProposal,
    ):
        assert (
            ("profile_version_id", "customer_id"),
            ("ark_customer_profile_versions.id", "ark_customer_profile_versions.customer_id"),
        ) in _fk_signatures(model.__table__)


def test_fact_evidence_and_conflict_tables_keep_customer_content_guards():
    facts = models.CustomerFact.__table__
    evidence = models.CustomerFactEvidenceLink.__table__
    conflicts = models.CustomerFactConflict.__table__

    assert facts.c.customer_id.nullable is False
    assert ("fact_fingerprint",) in _unique_column_sets(facts)
    assert evidence.c.customer_id.nullable is False
    assert evidence.c.evidence_content_hash.nullable is False
    assert ("evidence_fingerprint",) in _unique_column_sets(evidence)
    assert conflicts.c.customer_id.nullable is False
    assert ("conflict_fingerprint",) in _unique_column_sets(conflicts)
    checks = {
        str(constraint.sqltext)
        for constraint in conflicts.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert any("left_fact_id < right_fact_id" in check for check in checks)


def test_every_confidence_column_has_a_structural_zero_to_one_check():
    models_and_columns = {
        models.CustomerAccount: ("identity_confidence",),
        models.CustomerName: ("confidence",),
        models.CustomerExternalIdentity: ("confidence",),
        models.CustomerRelationship: ("confidence",),
        models.CustomerContact: ("confidence",),
        models.CustomerContactRelationship: ("confidence",),
        models.CustomerFact: ("confidence",),
        models.CustomerConversationAnalysis: ("confidence",),
    }

    for model, column_names in models_and_columns.items():
        checks = " ".join(
            str(constraint.sqltext)
            for constraint in model.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        )
        for column_name in column_names:
            assert f"{column_name} >= 0" in checks
            assert f"{column_name} <= 1" in checks


def _callable_origin(value):
    while hasattr(value, "__wrapped__"):
        value = value.__wrapped__
    return value


def test_core_audit_defaults_use_beijing_now_and_never_datetime_now():
    for model in _module_models():
        for column in model.__table__.columns:
            for default in (column.default, column.onupdate):
                if default is None or not default.is_callable:
                    continue
                callable_default = _callable_origin(default.arg)
                assert getattr(callable_default, "__name__", "") not in {"now", "utcnow"}
                assert getattr(callable_default, "__module__", "") != "datetime"

        for audit_name in ("created_at", "updated_at"):
            if audit_name not in model.__table__.c:
                continue
            audit_column = model.__table__.c[audit_name]
            assert audit_column.default is not None
            assert _callable_origin(audit_column.default.arg) is core_time.beijing_now
            if audit_name == "updated_at":
                assert audit_column.onupdate is not None
                assert _callable_origin(audit_column.onupdate.arg) is core_time.beijing_now


def test_relationships_are_minimal_and_use_noload():
    account_relationships = sqlalchemy_inspect(models.CustomerAccount).relationships
    name_relationships = sqlalchemy_inspect(models.CustomerName).relationships

    assert set(account_relationships.keys()) == {"names"}
    assert set(name_relationships.keys()) == {"customer"}
    assert account_relationships.names.lazy == "noload"
    assert name_relationships.customer.lazy == "noload"


def test_app_models_registers_core_once_and_retains_sales_tables():
    imported = importlib.import_module("app.models")
    importlib.reload(imported)

    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    assert "ark_sales_target_profiles" in Base.metadata.tables
    assert "ark_sales_search_jobs" in Base.metadata.tables
    for table_name in EXPECTED_TABLES:
        assert Base.metadata.tables[table_name] is models.CORE_TABLES[table_name]


def test_core_metadata_can_create_on_sqlite():
    importlib.import_module("app.models")
    engine = create_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine, tables=list(models.CORE_TABLES.values()))
    assert set(models.CORE_TABLE_NAMES) <= set(Base.metadata.tables)


def test_every_core_table_compiles_complete_mysql_ddl_with_comments():
    importlib.import_module("app.models")

    assert len(models.CORE_TABLES) == 31
    for table_name, table in models.CORE_TABLES.items():
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert table_name in ddl
        assert ddl.lstrip().startswith("CREATE TABLE")
        assert "COMMENT=" in ddl
