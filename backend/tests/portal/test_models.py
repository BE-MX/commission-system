from datetime import datetime

import pytest
from sqlalchemy import insert, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.portal.models import Account, AuthorityBarrier, CustomerAccess, Site


def test_all_portal_tables_compile_for_mysql(portal_metadata):
    tables = [t for t in portal_metadata.tables.values() if t.name.startswith("ark_order_portal_")]
    assert len(tables) == 24
    for table in tables:
        sql = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "CREATE TABLE" in sql
        assert all(len(constraint.name or "") <= 64 for constraint in table.constraints)


def test_disabled_site_is_default_and_account_email_unique(portal_db):
    site = Site(code="leshine", name="LeShine", allowed_origin="https://shop.example")
    portal_db.add(site)
    portal_db.add(Account(email_normalized="buyer@example.com", email_display="Buyer@example.com", contact_name="Buyer"))
    portal_db.commit()
    assert site.status == "disabled" and site.row_version == 1
    assert site.created_at.tzinfo is None
    portal_db.add(Account(email_normalized="buyer@example.com", email_display="buyer@example.com", contact_name="Other"))
    with pytest.raises(IntegrityError):
        portal_db.commit()
    portal_db.rollback()


def test_global_authority_barrier_is_unique(portal_db):
    portal_db.add(AuthorityBarrier(code="authority", version=1))
    portal_db.commit()
    with pytest.raises(IntegrityError):
        portal_db.execute(insert(AuthorityBarrier).values(code="authority", version=2))
    portal_db.rollback()


def test_no_order_permission_without_price_permission(portal_db, portal_metadata):
    for name in ["ark_users", "ark_customer_accounts", "ark_customer_external_identities", "ark_customer_assignments"]:
        portal_db.execute(portal_metadata.tables[name].insert().values(id=1))
    site = Site(code="leshine", name="LeShine", allowed_origin="https://shop.example")
    portal_db.add(site)
    portal_db.flush()
    portal_db.add(CustomerAccess(site_id=site.id, customer_id=1, okki_namespace="okki:tenant",
        okki_company_id="9007199254740993", external_identity_id=1, binding_fingerprint="a"*64,
        assignment_id=1, sales_user_id=1, can_order=True, can_view_price=False))
    with pytest.raises(IntegrityError):
        portal_db.flush()
    portal_db.rollback()


def test_quote_and_permanent_lineage_have_database_uniqueness(portal_metadata):
    request = portal_metadata.tables["ark_order_portal_requests"]
    conversion = portal_metadata.tables["ark_order_portal_conversions"]
    key_sets = {tuple(c.columns.keys()) for c in request.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert ("access_id", "account_id", "idempotency_key") in key_sets
    assert ("quote_id",) in key_sets
    assert conversion.c.request_id.unique
    assert next(iter(conversion.c.invoice_id.foreign_keys)).ondelete == "RESTRICT"
