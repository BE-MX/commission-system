"""Portal tests use isolated SQLite only; reject every attempted MySQL connection.

Run with --confcutdir=tests/portal so unrelated application fixtures are not loaded.
"""

from pathlib import Path

import pymysql
import pytest
from sqlalchemy import BigInteger, Column, Integer, MetaData, Table, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def _deny_mysql(*args, **kwargs):
    raise AssertionError("Portal tests must never connect to MySQL or a shared database")


pymysql.connect = _deny_mysql
pymysql.connections.Connection.connect = _deny_mysql


@event.listens_for(Engine, "do_connect")
def _isolated_connections(dialect, connection_record, args, kwargs):
    if dialect.name != "sqlite":
        _deny_mysql()


assert not (Path(__file__).resolve().parents[2] / '.env').exists(), "Use an isolated checkout without backend/.env"

from app.core.database import Base  # noqa: E402
from app.auth import models as auth_models  # noqa: E402,F401
from app.customer import models as customer_models  # noqa: E402,F401
from app.invoice import models as invoice_models  # noqa: E402,F401
from app.portal import models  # noqa: E402,F401


@pytest.fixture
def portal_metadata():
    metadata = MetaData()
    # Only FK targets are needed for model/constraint tests. Domain integration
    # tests add the real upstream schema; this fixture does not claim to test it.
    for table in ("ark_users", "ark_customer_accounts", "ark_customer_external_identities",
                  "ark_customer_assignments", "ark_invoices"):
        Table(table, metadata, Column("id", BigInteger().with_variant(Integer(), "sqlite"), primary_key=True))
    for table in Base.metadata.tables.values():
        if table.name.startswith("ark_order_portal_"):
            table.to_metadata(metadata)
    return metadata


@pytest.fixture
def portal_db(portal_metadata):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    portal_metadata.create_all(engine)
    with Session(engine) as db:
        yield db
        db.rollback()
    engine.dispose()


def pytest_addoption(parser):
    group = parser.getgroup("portal-live-browser")
    for name in ("node", "module", "chromium"):
        group.addoption("--portal-browser-" + name, default=None, help="Opt-in local browser runtime path")
