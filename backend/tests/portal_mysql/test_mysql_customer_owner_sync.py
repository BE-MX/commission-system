"""Owned MySQL only: numeric JSON ownership, column grants and atomic repairs."""

from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from queue import Queue
from threading import Event

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.invoice import customer_sync_service, okki_client, product_service
from app.invoice.customer_sync_models import CustomerSyncLog
from app.invoice.models import InvoiceCustomerOverlay
from test_mysql_concurrency import wait_for_lock

OWNER = 55411216
OTHER = 99999999


@pytest.fixture(scope="module")
def customer_engine(mysql_engine):
    assert product_service._schema() == "lsordertest"
    InvoiceCustomerOverlay.__table__.create(mysql_engine)
    path = Path(__file__).resolve().parents[2] / "alembic/versions/262_invoice_customer_sync_log.py"
    spec = spec_from_file_location("customer_sync_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with mysql_engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(text("CREATE DATABASE lsordertest CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
        connection.execute(text("""CREATE TABLE lsordertest.customer_info (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            company_id BIGINT NOT NULL UNIQUE, company_name VARCHAR(255), country_name VARCHAR(255),
            owner_user_ids JSON, update_time DATETIME,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB"""))
        connection.execute(text("""CREATE TABLE lsordertest.user_basic (
            user_id VARCHAR(64) PRIMARY KEY, full_name VARCHAR(128), nickname VARCHAR(128), user_mobile VARCHAR(32)
        ) ENGINE=InnoDB"""))
    assert "ark_invoice_customer_sync_logs" in inspect(mysql_engine).get_table_names()
    return mysql_engine


def _remote(monkeypatch, company_id, owner=OWNER):
    info = {"company_id": company_id, "name": "Synthetic Salon", "country": "US",
            "owner": [{"user_id": owner}], "update_time": "2026-11-12T16:00:00Z"}
    monkeypatch.setattr(okki_client, "query_companies_by_name", lambda *args: [{"company_id": company_id, "name": info["name"]}])
    monkeypatch.setattr(okki_client, "get_company_info", lambda *args: info)
    return info


def _seed(engine, company_id, owners="[]", *, overlay=False):
    with Session(engine) as db:
        db.execute(text("""INSERT INTO lsordertest.customer_info
            (company_id, company_name, country_name, owner_user_ids, update_time)
            VALUES (:id, 'Original name', 'DE', :owners, '2026-11-12 00:00:00')"""),
                   {"id": company_id, "owners": owners})
        if overlay:
            db.add(InvoiceCustomerOverlay(company_id=str(company_id), company_name="Original name",
                                          owner_user_ids=[], source_update_time="2026-11-12 00:00:00"))
        db.commit()


@pytest.mark.parametrize("company_id, owners, owner", [(99001, None, OWNER), (99002, '["99999999"]', OWNER), (99003, '[true]', 1)])
def test_mirror_numeric_json_works_without_overlay(customer_engine, monkeypatch, company_id, owners, owner):
    _seed(customer_engine, company_id, owners)
    _remote(monkeypatch, company_id, owner)
    with Session(customer_engine) as db:
        customer_sync_service.sync_customer_from_okki(db, company_name="Synthetic Salon", operator_id=5)
        db.commit()
    with Session(customer_engine) as db:
        # Exact production predicate, not SQLite LIKE approximation.
        assert db.scalar(text("SELECT JSON_CONTAINS(owner_user_ids, :owner) FROM lsordertest.customer_info WHERE company_id=:id"),
                         {"owner": str(owner), "id": company_id}) == 1
        row = db.execute(text("SELECT company_name, country_name, update_time FROM lsordertest.customer_info WHERE company_id=:id"),
                         {"id": company_id}).one()
        assert tuple(map(str, row)) == ("Original name", "DE", "2026-11-12 00:00:00")
        assert db.query(CustomerSyncLog).filter_by(company_id=str(company_id)).one().after_data["owner_user_ids"] == [owner]
        assert len(product_service.search_customers(db, keyword=str(company_id), owner_okki_id=owner)) == 1


def test_mirror_insert_and_audit_rollback_together(customer_engine, monkeypatch):
    _remote(monkeypatch, 99004)
    with Session(customer_engine) as db:
        customer_sync_service.sync_customer_from_okki(db, company_name="Synthetic Salon", operator_id=5)
        db.rollback()
    with Session(customer_engine) as db:
        assert db.scalar(text("SELECT COUNT(*) FROM lsordertest.customer_info WHERE company_id=99004")) == 0
        assert db.get(InvoiceCustomerOverlay, "99004") is None
        assert db.query(CustomerSyncLog).filter_by(company_id="99004").count() == 0
        customer_sync_service.sync_customer_from_okki(db, company_name="Synthetic Salon", operator_id=5)
        db.commit()
        assert db.query(CustomerSyncLog).filter_by(company_id="99004").one().before_data is None


def test_stale_response_waits_for_owner_writer_then_rejects(customer_engine, monkeypatch):
    _seed(customer_engine, 99005, overlay=True)
    info = _remote(monkeypatch, 99005)
    started = Queue()
    release = Event()

    def delayed(db, company_id):
        started.put(db.scalar(text("SELECT CONNECTION_ID()")))
        assert release.wait(5)
        return info

    monkeypatch.setattr(okki_client, "get_company_info", delayed)

    def slow_sync():
        with Session(customer_engine) as db:
            with pytest.raises(customer_sync_service.CustomerSyncError, match="其他同步更新"):
                customer_sync_service.sync_customer_from_okki(db, company_name="Synthetic Salon", operator_id=5)
            db.rollback()

    with Session(customer_engine) as writer, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(slow_sync)
        connection_id = started.get(timeout=5)
        row = writer.query(InvoiceCustomerOverlay).filter_by(company_id="99005").with_for_update().one()
        row.owner_user_ids = [str(OTHER)]
        writer.flush()
        writer.execute(text("UPDATE lsordertest.customer_info SET owner_user_ids='[99999999]' WHERE company_id=99005"))
        try:
            release.set()
            wait_for_lock(customer_engine, connection_id)
            assert not future.done()
            writer.commit()
        finally:
            writer.rollback()
            release.set()
        future.result(timeout=6)
    with Session(customer_engine) as db:
        assert db.scalar(text("SELECT JSON_CONTAINS(owner_user_ids, '99999999') FROM lsordertest.customer_info WHERE company_id=99005")) == 1
        assert db.query(CustomerSyncLog).filter_by(company_id="99005").count() == 0


def test_minimal_column_grants_allow_sync_but_not_unrelated_update(customer_engine, monkeypatch):
    database = customer_engine.url.database
    with customer_engine.begin() as conn:
        conn.execute(text("CREATE USER 'customer_sync_app'@'127.0.0.1' IDENTIFIED BY :password"),
                     {"password": customer_engine.url.password})
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.* TO 'customer_sync_app'@'127.0.0.1'"))
        conn.execute(text("GRANT SELECT ON lsordertest.* TO 'customer_sync_app'@'127.0.0.1'"))
        conn.execute(text("GRANT UPDATE (owner_user_ids), INSERT (company_id, company_name, country_name, owner_user_ids) "
                          "ON lsordertest.customer_info TO 'customer_sync_app'@'127.0.0.1'"))
    application = create_engine(customer_engine.url.set(username="customer_sync_app"), hide_parameters=True)
    try:
        for company_id in (99006, 99007):
            if company_id == 99007:
                _seed(customer_engine, company_id)
            _remote(monkeypatch, company_id)
            with Session(application) as db:
                customer_sync_service.sync_customer_from_okki(db, company_name="Synthetic Salon", operator_id=5)
                db.commit()
        with application.begin() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text("UPDATE lsordertest.customer_info SET country_name='FR' WHERE company_id=99007"))
        with Session(customer_engine) as db:
            assert db.query(CustomerSyncLog).filter(CustomerSyncLog.company_id.in_(["99006", "99007"])).count() == 2
    finally:
        application.dispose()
