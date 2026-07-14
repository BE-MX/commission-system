"""发票数据范围权限（invoice:read_all）与 _user_id sub 解析测试。"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.utils import create_access_token
from app.core.database import get_db
from app.invoice import service
from app.invoice.models import Invoice  # noqa: F401 - register metadata
from app.invoice.router import _can_read_all, _ensure_invoice_visible, _user_id
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload


@pytest.fixture(autouse=True)
def seed_invoice_product_pair(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY, product_no TEXT, name TEXT, model TEXT,
            color TEXT, size TEXT, unit TEXT, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.okki_inventory (
            product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT OR IGNORE INTO lsordertest.okki_products
            (product_id, product_no, name, model, color, size, unit, disable_flag)
        VALUES (1, 'P001', 'Raw Hair/18/#1/100g', '', '#1', '18', '100g', 0)
    """))
    if not db.execute(text("""
        SELECT 1 FROM lsordertest.okki_inventory WHERE product_id = 1 AND sku_id = 9001
    """)).first():
        db.execute(text("""
            INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
            VALUES (1, 9001, 0)
        """))


@contextmanager
def _client(db, *, sub: str, permissions: list[str], roles: list[str] | None = None):
    from app.invoice.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": sub,
        "username": f"user{sub}",
        "roles": roles or [],
        "permissions": permissions,
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _create_payload():
    return InvoiceCreate(
        customer_id="123456",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 13),
        items=[
            InvoiceItemPayload(
                product_id=1, sku_id=9001, product_name="Raw Hair/18/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="18", quantity=1, price_per_piece=Decimal("10.00"),
            ),
        ],
    )


# ── _user_id：JWT payload 只有 sub（字符串）——历史 bug 是只取 id 永远 None ──


def test_user_id_parses_sub_claim():
    assert _user_id({"sub": "5"}) == 5
    assert _user_id({"id": 3}) == 3
    assert _user_id({"id": None, "sub": "7"}) == 7
    assert _user_id({"sub": "abc"}) is None
    assert _user_id({}) is None


def test_created_by_persisted_from_sub(db):
    invoice = service.create_invoice(db, _create_payload(), user_id=_user_id({"sub": "5"}))
    db.flush()
    assert invoice.created_by == 5
    assert invoice.sales_user_id == 5


# ── 数据范围判定 ─────────────────────────────────────────


def test_can_read_all_by_permission_or_super_admin():
    assert _can_read_all({"permissions": ["invoice:read_all"], "roles": []}) is True
    assert _can_read_all({"permissions": [], "roles": ["super_admin"]}) is True
    assert _can_read_all({"permissions": ["invoice:read"], "roles": ["salesperson"]}) is False


def test_ensure_invoice_visible_scope(db):
    mine = service.create_invoice(db, _create_payload(), user_id=5)
    db.flush()

    owner = {"sub": "5", "permissions": ["invoice:read"], "roles": []}
    stranger = {"sub": "6", "permissions": ["invoice:read"], "roles": []}
    reader_all = {"sub": "6", "permissions": ["invoice:read", "invoice:read_all"], "roles": []}

    _ensure_invoice_visible(mine, owner)       # 自己创建 → 可见
    _ensure_invoice_visible(mine, reader_all)  # read_all → 可见
    with pytest.raises(HTTPException) as exc:  # 他人 → 按不存在处理
        _ensure_invoice_visible(mine, stranger)
    assert exc.value.status_code == 404

    # created_by 为 NULL 的历史发票：只有全量范围可见
    mine.created_by = None
    db.flush()
    _ensure_invoice_visible(mine, reader_all)
    with pytest.raises(HTTPException):
        _ensure_invoice_visible(mine, owner)


# ── 列表口径 ─────────────────────────────────────────────


def test_list_invoices_created_by_filter(db):
    service.create_invoice(db, _create_payload(), user_id=5)
    service.create_invoice(db, _create_payload(), user_id=6)
    legacy = service.create_invoice(db, _create_payload(), user_id=None)  # 历史 NULL 票
    db.flush()
    assert legacy.created_by is None

    mine, mine_total = service.list_invoices(db, created_by=5)
    assert mine_total == 1 and len(mine) == 1

    everything, all_total = service.list_invoices(db, created_by=None)
    assert all_total == 3

    other, other_total = service.list_invoices(db, created_by=7)
    assert other_total == 0 and other == []


# ── 端点级集成：守卫接线不许回归 ─────────────────────────


def test_endpoint_scope_wiring(db):
    mine = service.create_invoice(db, _create_payload(), user_id=5)
    db.commit()

    # 创建者：列表见自己的，详情可达
    with _client(db, sub="5", permissions=["invoice:read"]) as client:
        data = client.get("/api/invoice/invoices").json()["data"]
        assert data["total"] == 1
        assert client.get(f"/api/invoice/invoices/{mine.id}").status_code == 200

    # 他人（无 read_all）：列表为空，详情/导出按不存在处理
    with _client(db, sub="6", permissions=["invoice:read"]) as client:
        data = client.get("/api/invoice/invoices").json()["data"]
        assert data["total"] == 0
        assert client.get(f"/api/invoice/invoices/{mine.id}").status_code == 404
        assert client.get(f"/api/invoice/invoices/{mine.id}/export/excel").status_code == 404

    # 他人（有 read_all）：全部可见
    with _client(db, sub="6", permissions=["invoice:read", "invoice:read_all"]) as client:
        data = client.get("/api/invoice/invoices").json()["data"]
        assert data["total"] == 1
        assert client.get(f"/api/invoice/invoices/{mine.id}").status_code == 200

    # super_admin：绕过数据范围
    with _client(db, sub="7", permissions=[], roles=["super_admin"]) as client:
        assert client.get(f"/api/invoice/invoices/{mine.id}").status_code == 200
