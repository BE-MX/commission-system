"""指定跟单员（merchandiser）与上一单号提醒的后端契约测试。"""
from datetime import date

import pytest

from app.auth.models import ArkRole, ArkUser, ArkUserRole
from app.invoice import service
from app.invoice.delegation_service import list_merchandisers
from app.invoice.models import Invoice
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate


def _make_user(db, username, real_name, *, role_label=None, active=True):
    user = ArkUser(username=username, password_hash="x", real_name=real_name, is_active=active)
    db.add(user)
    db.flush()
    if role_label:
        role = ArkRole(name=f"role_{username}", label=role_label)
        db.add(role)
        db.flush()
        db.add(ArkUserRole(user_id=user.id, role_id=role.id))
        db.flush()
    return user


def _payload(**extra):
    return dict(customer_id="C1", customer_name="Customer", invoice_date=date(2026, 9, 23),
                okki_new_deal=1, okki_free_shipping=1, okki_first_return=0, items=[], **extra)


def test_merchandiser_snapshot_round_trip_and_clear(db):
    merch = _make_user(db, "m001", "跟单小李", role_label="跟单员")
    invoice = service.create_invoice(db, InvoiceCreate(**_payload(merchandiser_id=merch.id)))
    detail = service.serialize_detail(invoice)
    assert detail["merchandiser_id"] == merch.id
    assert detail["merchandiser_name"] == "跟单小李"
    # 编辑改为空 = 清空跟单员
    service.update_invoice(db, invoice, InvoiceUpdate(**_payload(merchandiser_id=None)))
    assert invoice.merchandiser_id is None
    assert invoice.merchandiser_name is None


def test_merchandiser_rejects_missing_or_disabled_user(db):
    ghost = _make_user(db, "m002", "停用账号", active=False)
    with pytest.raises(ValueError, match="跟单员"):
        service.create_invoice(db, InvoiceCreate(**_payload(merchandiser_id=ghost.id)))
    with pytest.raises(ValueError, match="跟单员"):
        service.create_invoice(db, InvoiceCreate(**_payload(merchandiser_id=999999)))


def test_list_merchandisers_only_returns_active_users_with_the_role(db):
    _make_user(db, "sales01", "销售甲")
    merch = _make_user(db, "m003", "跟单乙", role_label="跟单员")
    disabled = _make_user(db, "m004", "跟单停用", role_label="跟单员", active=False)
    options = list_merchandisers(db)
    ids = [option["id"] for option in options]
    assert merch.id in ids
    assert disabled.id not in ids
    assert all(option["real_name"] for option in options)


def test_previous_invoice_no_scoped_by_salesperson_and_type(db):
    def _inv(no, sales_id, order_type):
        row = Invoice(invoice_no=no, order_type=order_type, customer_id="C1", customer_name="C",
                      invoice_date=date(2026, 9, 1), sales_user_id=sales_id)
        db.add(row)
        db.flush()
        return row

    _inv("wang-KC-0901", 7, "stock")
    latest = _inv("wang-KC-0902", 7, "stock")
    _inv("SC-0901", 7, "production")
    _inv("li-KC-0901", 8, "stock")

    assert service.previous_invoice_no(db, 7, "stock") == "wang-KC-0902"
    assert service.previous_invoice_no(db, 7, "production") == "SC-0901"
    # 编辑场景排除自身
    assert service.previous_invoice_no(db, 7, "stock", exclude_id=latest.id) == "wang-KC-0901"
    assert service.previous_invoice_no(db, 9, "stock") is None
    assert service.previous_invoice_no(db, None, "stock") is None


def test_migration_167_adds_nullable_merchandiser_columns():
    import importlib.util
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    path = Path(__file__).resolve().parents[1] / "alembic/versions/167_invoice_merchandiser.py"
    spec = importlib.util.spec_from_file_location("merchandiser_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ark_invoices (id INTEGER PRIMARY KEY, customer_name TEXT)"))
        connection.execute(text("INSERT INTO ark_invoices VALUES (1, 'Existing customer')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        row = connection.execute(text("SELECT customer_name, merchandiser_id, merchandiser_name FROM ark_invoices")).one()
        assert row == ("Existing customer", None, None)
    config = Config()
    config.set_main_option("script_location", str(path.parents[1]))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    assert migration.revision in {revision.revision for revision in scripts.walk_revisions()}
