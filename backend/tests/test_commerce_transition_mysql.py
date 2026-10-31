"""Critical authority races on actual InnoDB REPEATABLE READ connections."""
from pathlib import Path
from uuid import uuid4
import json
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import app.models  # noqa: F401
from app.commerce_transition import models
from app.core.database import Base
from app.invoice.models import Invoice
from tests.test_inventory_mysql import MySQLTestSettings, isolated_mysql_url
from tests import test_commerce_transition_authority as scenarios


@pytest.fixture
def innodb_authority(request):
    raw = MySQLTestSettings().COMMERCE_TEST_MYSQL_URL
    if not raw:
        pytest.skip('requires owned loopback COMMERCE_TEST_MYSQL_URL')
    url = isolated_mysql_url(raw)
    assert url.port == 33079
    schema = 'ark_transition_rr_' + uuid4().hex[:16]
    control = create_engine(url, hide_parameters=True)
    engine = create_engine(url.set(database=schema), isolation_level='REPEATABLE READ', hide_parameters=True)
    with control.begin() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    try:
        with engine.begin() as connection:
            assert connection.scalar(text('SELECT @@transaction_isolation')) == 'REPEATABLE-READ'
            # Invoice's nullable customer FK is the only outside coordination
            # dependency needed by these races. Business migration coverage is
            # the separate full-chain suite, not this narrow fixture.
            connection.exec_driver_sql('CREATE TABLE ark_customer_accounts (id BIGINT PRIMARY KEY)')
        tables = [value.__table__ for value in vars(models).values() if isinstance(value, type)
                  and getattr(value, '__module__', None) == models.__name__ and hasattr(value, '__table__')]
        Base.metadata.create_all(engine, tables=[Invoice.__table__, *tables])
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        with sessions() as db:
            scenarios.install(db)
            invoice = scenarios.invoice(db)
            identity = invoice.id
            db.commit()
        yield sessions, identity
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.exec_driver_sql(f'DROP DATABASE `{schema}`')
            assert connection.scalar(text('SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=:name'), {'name': schema}) == 0
        control.dispose()
        path = Path(__file__).resolve().parents[2] / 'tmp/transition-mysql-rr-results.json'
        evidence = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        evidence.append({'test': request.node.name, 'schema': schema, 'isolation': 'REPEATABLE-READ', 'schema_dropped_readback': True})
        path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')


def test_one_durable_send_permission_under_duplicate_claims(innodb_authority):
    scenarios.test_concurrent_duplicate_claim_has_only_one_send_permission(innodb_authority)


def test_cached_terminal_claim_cannot_be_overwritten(innodb_authority):
    scenarios.test_stale_session_claim_cannot_overwrite_committed_terminal_result(innodb_authority)


def test_cached_writer_receipt_cannot_enable_revoked_writer(innodb_authority):
    scenarios.test_stale_session_writer_receipt_does_not_allow_revoked_readiness(innodb_authority)


def test_cached_bank_domain_cannot_duplicate_principal(innodb_authority):
    scenarios.test_stale_bank_domain_and_bound_payment_cannot_create_principal(innodb_authority)
