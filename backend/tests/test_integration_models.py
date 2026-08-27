from datetime import datetime
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    JSON,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.core import time as core_time
from app.integration.models import IntegrationApp, InvoiceIngestRequest


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "125_invoice_integration.py"
)


def _user(username: str) -> ArkUser:
    return ArkUser(username=username, password_hash="hash", real_name=username)


def _app(owner_user_id: int, suffix: str) -> IntegrationApp:
    return IntegrationApp(
        public_id=f"app_{suffix}",
        name=f"Integration {suffix}",
        owner_user_id=owner_user_id,
        token_hash=(suffix * 64)[:64],
        token_suffix=(suffix * 6)[:6],
        scopes=["invoice:write"],
        created_by=owner_user_id,
    )


def _request(app_id: int, public_id: str, external_order_id: str) -> InvoiceIngestRequest:
    return InvoiceIngestRequest(
        public_id=public_id,
        integration_app_id=app_id,
        external_order_id=external_order_id,
        request_sha256=(public_id * 64)[:64],
    )


def test_app_models_import_registers_and_exports_integration_models():
    probe = """
from app.core.database import Base
assert "ark_integration_apps" not in Base.metadata.tables
assert "ark_invoice_ingest_requests" not in Base.metadata.tables
import app.models as models
assert models.IntegrationApp.__name__ == "IntegrationApp"
assert models.InvoiceIngestRequest.__name__ == "InvoiceIngestRequest"
assert "ark_integration_apps" in Base.metadata.tables
assert "ark_invoice_ingest_requests" in Base.metadata.tables
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_model_metadata_matches_external_invoice_contract():
    app = IntegrationApp.__table__
    request = InvoiceIngestRequest.__table__

    assert app.name == "ark_integration_apps"
    assert request.name == "ark_invoice_ingest_requests"
    assert app.c.public_id.type.length == 32
    assert app.c.public_id.nullable is False
    assert app.c.public_id.unique is True
    assert app.c.name.type.length == 100
    assert app.c.token_hash.type.length == 64
    assert app.c.token_hash.unique is True
    assert app.c.token_suffix.type.length == 6
    assert isinstance(app.c.scopes.type, JSON)
    assert app.c.scopes.nullable is False
    assert app.c.expires_at.nullable is True
    assert app.c.last_used_at.nullable is True
    assert app.c.created_by.nullable is True

    assert request.c.public_id.type.length == 32
    assert request.c.external_order_id.type.length == 64
    assert request.c.request_sha256.type.length == 64
    assert request.c.invoice_id.nullable is True
    assert request.c.error_code.type.length == 64
    assert isinstance(request.c.error_json.type, JSON)
    assert request.c.finished_at.nullable is True

    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in request.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_constraints["uq_invoice_ingest_app_order"] == (
        "integration_app_id",
        "external_order_id",
    )

    check_sql = {
        constraint.name: str(constraint.sqltext)
        for constraint in request.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "processing" in check_sql["ck_invoice_ingest_status"]
    assert "created" in check_sql["ck_invoice_ingest_status"]
    assert "rejected" in check_sql["ck_invoice_ingest_status"]
    assert "attempt_count > 0" == check_sql["ck_invoice_ingest_attempt_positive"]

    assert {index.name for index in request.indexes} == {
        "idx_invoice_ingest_status",
        "idx_invoice_ingest_invoice",
    }


def test_fk_types_and_delete_actions_are_compatible(engine):
    assert IntegrationApp.__table__.c.id.type.compile(dialect=mysql.dialect()) == "BIGINT"
    assert IntegrationApp.__table__.c.id.type.compile(dialect=sqlite.dialect()) == "INTEGER"
    assert (
        IntegrationApp.__table__.c.owner_user_id.type.compile(dialect=mysql.dialect())
        == "INTEGER UNSIGNED"
    )
    assert (
        IntegrationApp.__table__.c.created_by.type.compile(dialect=mysql.dialect())
        == "INTEGER UNSIGNED"
    )
    assert (
        InvoiceIngestRequest.__table__.c.integration_app_id.type.compile(
            dialect=mysql.dialect()
        )
        == "BIGINT"
    )
    assert (
        InvoiceIngestRequest.__table__.c.invoice_id.type.compile(dialect=mysql.dialect())
        == "BIGINT"
    )

    app_fks = {
        tuple(fk["constrained_columns"]): (fk["referred_table"], fk["options"].get("ondelete"))
        for fk in inspect(engine).get_foreign_keys("ark_integration_apps")
    }
    request_fks = {
        tuple(fk["constrained_columns"]): (fk["referred_table"], fk["options"].get("ondelete"))
        for fk in inspect(engine).get_foreign_keys("ark_invoice_ingest_requests")
    }
    assert app_fks[("owner_user_id",)] == ("ark_users", "CASCADE")
    assert app_fks[("created_by",)] == ("ark_users", "SET NULL")
    assert request_fks[("integration_app_id",)] == ("ark_integration_apps", "CASCADE")
    assert request_fks[("invoice_id",)] == ("ark_invoices", "SET NULL")


def test_defaults_use_beijing_business_midnight(monkeypatch, db):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is core_time.BEIJING_TIMEZONE
            return cls(2026, 8, 27, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr(core_time, "datetime", FrozenDateTime)
    owner = _user("midnight-owner")
    db.add(owner)
    db.flush()
    app = _app(owner.id, "a")
    db.add(app)
    db.flush()
    request = _request(app.id, "req_midnight", "ORDER-MIDNIGHT")
    db.add(request)
    db.flush()

    expected = datetime(2026, 8, 27, 0, 0, 0)
    assert app.is_active is True
    assert app.created_at == expected
    assert app.updated_at == expected
    assert request.status == "processing"
    assert request.attempt_count == 1
    assert request.created_at == expected
    assert request.updated_at == expected


def test_external_order_uniqueness_is_scoped_to_app(db):
    owner = _user("uniqueness-owner")
    db.add(owner)
    db.flush()
    first_app = _app(owner.id, "a")
    second_app = _app(owner.id, "b")
    db.add_all([first_app, second_app])
    db.flush()

    db.add_all(
        [
            _request(first_app.id, "request_one", "EXT-100"),
            _request(second_app.id, "request_two", "EXT-100"),
        ]
    )
    db.flush()

    db.add(_request(first_app.id, "request_three", "EXT-100"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_relationships_default_to_noload():
    assert IntegrationApp.__mapper__.relationships["ingest_requests"].lazy == "noload"
    assert InvoiceIngestRequest.__mapper__.relationships["integration_app"].lazy == "noload"
    assert InvoiceIngestRequest.__mapper__.relationships["invoice"].lazy == "noload"


def test_migration_chains_from_current_head_and_creates_contract_tables(monkeypatch):
    assert MIGRATION_PATH.is_file()
    spec = importlib.util.spec_from_file_location("invoice_integration_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    created_tables = []
    created_indexes = []

    class OpRecorder:
        @staticmethod
        def create_table(name, *args, **kwargs):
            created_tables.append((name, args, kwargs))

        @staticmethod
        def create_index(name, table_name, columns, **kwargs):
            created_indexes.append((name, table_name, tuple(columns), kwargs))

    monkeypatch.setattr(migration, "op", OpRecorder())
    migration.upgrade()

    assert migration.revision == "125_invoice_integration"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "124_ai_chat_modes"
    assert [name for name, _args, _kwargs in created_tables] == [
        "ark_integration_apps",
        "ark_invoice_ingest_requests",
    ]

    table_args = {name: args for name, args, _kwargs in created_tables}
    app_args = table_args["ark_integration_apps"]
    request_args = table_args["ark_invoice_ingest_requests"]
    app_columns = {item.name: item for item in app_args if isinstance(item, Column)}
    request_columns = {
        item.name: item for item in request_args if isinstance(item, Column)
    }

    assert set(app_columns) == {
        "id",
        "public_id",
        "name",
        "owner_user_id",
        "token_hash",
        "token_suffix",
        "scopes",
        "is_active",
        "expires_at",
        "last_used_at",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert set(request_columns) == {
        "id",
        "public_id",
        "integration_app_id",
        "external_order_id",
        "request_sha256",
        "invoice_id",
        "status",
        "error_code",
        "error_json",
        "attempt_count",
        "created_at",
        "finished_at",
        "updated_at",
    }

    mysql_dialect = mysql.dialect()
    assert app_columns["id"].type.compile(dialect=mysql_dialect) == "BIGINT"
    assert app_columns["owner_user_id"].type.compile(dialect=mysql_dialect) == "INTEGER UNSIGNED"
    assert app_columns["created_by"].type.compile(dialect=mysql_dialect) == "INTEGER UNSIGNED"
    assert request_columns["integration_app_id"].type.compile(dialect=mysql_dialect) == "BIGINT"
    assert request_columns["invoice_id"].type.compile(dialect=mysql_dialect) == "BIGINT"

    assert str(app_columns["is_active"].server_default.arg) == "true"
    assert str(app_columns["created_at"].server_default.arg) == "CURRENT_TIMESTAMP"
    assert (
        str(app_columns["updated_at"].server_default.arg)
        == "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
    )
    assert str(request_columns["status"].server_default.arg) == "processing"
    assert str(request_columns["attempt_count"].server_default.arg) == "1"
    assert str(request_columns["created_at"].server_default.arg) == "CURRENT_TIMESTAMP"
    assert (
        str(request_columns["updated_at"].server_default.arg)
        == "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
    )

    def foreign_keys(args):
        return {
            tuple(item.column_keys): (
                tuple(element._colspec for element in item.elements),
                item.ondelete,
            )
            for item in args
            if isinstance(item, ForeignKeyConstraint)
        }

    assert foreign_keys(app_args) == {
        ("owner_user_id",): (("ark_users.id",), "CASCADE"),
        ("created_by",): (("ark_users.id",), "SET NULL"),
    }
    assert foreign_keys(request_args) == {
        ("integration_app_id",): (("ark_integration_apps.id",), "CASCADE"),
        ("invoice_id",): (("ark_invoices.id",), "SET NULL"),
    }

    checks = {
        item.name: str(item.sqltext)
        for item in request_args
        if isinstance(item, CheckConstraint)
    }
    assert checks == {
        "ck_invoice_ingest_status": "status IN ('processing', 'created', 'rejected')",
        "ck_invoice_ingest_attempt_positive": "attempt_count > 0",
    }

    unique_constraints = {
        item.name: tuple(item._pending_colargs)
        for item in (*app_args, *request_args)
        if isinstance(item, UniqueConstraint)
    }
    assert unique_constraints == {
        "uq_integration_app_public_id": ("public_id",),
        "uq_integration_app_token_hash": ("token_hash",),
        "uq_invoice_ingest_public_id": ("public_id",),
        "uq_invoice_ingest_app_order": ("integration_app_id", "external_order_id"),
    }

    assert {name for name, _table, _columns, _kwargs in created_indexes} == {
        "idx_integration_app_owner",
        "idx_integration_app_active",
        "idx_invoice_ingest_status",
        "idx_invoice_ingest_invoice",
    }
