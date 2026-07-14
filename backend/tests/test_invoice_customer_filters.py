"""客户双筛选（公司名/联系人名 + 私海过滤）与发票号编辑/生成规则测试。"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.invoice import product_service, service
from app.invoice.models import Invoice
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload, InvoiceUpdate

OKKI_UID = 55411216


@contextmanager
def _client(db, *, sub: str, permissions: list[str]):
    from app.invoice.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": sub, "username": f"user{sub}", "roles": [], "permissions": permissions,
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


@pytest.fixture
def seed_customers(db):
    """私海客户 A（owner=OKKI_UID）、他人私海 B、公海 C，各配一个联系人"""
    conn = db.get_bind().raw_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO lsordertest.customer_info
        (company_id, company_name, country_name, owner_user_ids) VALUES
        ('9001', 'Alpha Hair Studio', 'US', '[55411216]'),
        ('9002', 'Beta Salon', 'DE', '[99999999]'),
        ('9003', 'Gamma Beauty', 'FR', '[]')
    """)
    cur.execute("""
        INSERT OR IGNORE INTO lsordertest.customer_contacts
        (id, company_id, customer_id, name, email, tel, is_main) VALUES
        (1, '9001', '80001', 'Alice Wang', 'alice@x.com', '111', 1),
        (2, '9001', '80002', 'Aaron Lee', NULL, NULL, 0),
        (3, '9002', '80003', 'Bob Miller', 'bob@x.com', '222', 1),
        (4, '9003', '80004', 'Alice Zhang', NULL, '333', 1)
    """)
    conn.commit()


@pytest.fixture
def bound_user(db):
    """id=5 的方舟用户 stella，绑定 OKKI 账号 OKKI_UID"""
    user = ArkUser(id=5, username="stella", password_hash="x", real_name="Stella")
    db.add(user)
    db.add(ArkUserExternalBinding(
        ark_user_id=5, provider="okki", external_account_id=str(OKKI_UID),
        binding_status="active", is_primary=True,
    ))
    db.flush()
    return user


def _payload(**overrides):
    base = dict(
        customer_id="9001",
        customer_name="Alpha Hair Studio",
        invoice_date=date(2026, 7, 14),
        items=[
            InvoiceItemPayload(
                product_id=1, sku_id=9001, product_name="Raw Hair/18/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="18", quantity=1, price_per_piece=Decimal("10.00"),
            ),
        ],
    )
    base.update(overrides)
    return base


# ── 私海过滤（service 层）─────────────────────────────────


def test_search_customers_private_only(db, seed_customers):
    everyone = product_service.search_customers(db, keyword="a")
    assert {c["company_id"] for c in everyone} >= {"9001", "9002", "9003"}

    mine = product_service.search_customers(db, keyword=None, owner_okki_id=OKKI_UID)
    assert [c["company_id"] for c in mine] == ["9001"]


def test_search_contacts_keyword_and_private(db, seed_customers):
    # 按联系人名跨公司搜
    alices = product_service.search_customer_contacts(db, keyword="Alice")
    assert {c["company_id"] for c in alices} == {"9001", "9003"}
    # 私海过滤后只剩自己客户的联系人
    mine = product_service.search_customer_contacts(db, keyword="Alice", owner_okki_id=OKKI_UID)
    assert [c["company_id"] for c in mine] == ["9001"]
    assert mine[0]["company_name"] == "Alpha Hair Studio"


def test_search_contacts_scoped_by_company(db, seed_customers):
    # 公司→联系人联动：主联系人排前
    scoped = product_service.search_customer_contacts(db, company_id="9001")
    assert [c["name"] for c in scoped] == ["Alice Wang", "Aaron Lee"]


# ── 私海过滤（端点级：绑定/未绑定）───────────────────────


def test_search_endpoint_private_only_with_binding(db, seed_customers, bound_user):
    with _client(db, sub="5", permissions=["invoice:read", "invoice:write"]) as client:
        data = client.get(
            "/api/invoice/customers/search", params={"private_only": True},
        ).json()["data"]
        assert data["okki_bound"] is True
        assert [c["company_id"] for c in data["items"]] == ["9001"]

        contacts = client.get(
            "/api/invoice/customers/contacts", params={"private_only": True},
        ).json()["data"]
        assert contacts["okki_bound"] is True
        assert {c["company_id"] for c in contacts["items"]} == {"9001"}


def test_search_endpoint_private_only_without_binding(db, seed_customers):
    # sub=6 没有 OKKI 绑定：私海无从判定 → 空列表 + okki_bound=False
    with _client(db, sub="6", permissions=["invoice:read", "invoice:write"]) as client:
        data = client.get(
            "/api/invoice/customers/search", params={"private_only": True},
        ).json()["data"]
        assert data == {"items": [], "okki_bound": False}
        # 不勾私海仍可全量搜
        data = client.get("/api/invoice/customers/search").json()["data"]
        assert len(data["items"]) >= 3


# ── 发票号生成规则：{用户名}-{KC|SC}-{本月序号} ─────────────


def test_suggest_invoice_no_per_user_type_month(db, bound_user):
    assert service.suggest_invoice_no(db, 5, "stock") == "stella-KC-1"
    assert service.suggest_invoice_no(db, 5, "production") == "stella-SC-1"

    service.create_invoice(db, InvoiceCreate(**_payload()), user_id=5)
    db.flush()
    # 已有 stella-KC-1 → 下一单 2；SC 序号独立
    assert service.suggest_invoice_no(db, 5, "stock") == "stella-KC-2"
    assert service.suggest_invoice_no(db, 5, "production") == "stella-SC-1"


def test_suggest_invoice_no_cross_month_collision_bumps(db, bound_user):
    # 上月已有 stella-KC-1（不计入本月序号，但占用了全库唯一）
    last_month = datetime.now().replace(day=1) - timedelta(days=1)
    old = service.create_invoice(db, InvoiceCreate(**_payload(invoice_no="stella-KC-1")), user_id=5)
    db.flush()
    db.execute(
        text("UPDATE ark_invoices SET created_at = :ts WHERE id = :id"),
        {"ts": last_month, "id": old.id},
    )
    db.flush()
    # 本月第 1 单撞上月的号 → 顺延到 2
    assert service.suggest_invoice_no(db, 5, "stock") == "stella-KC-2"


def test_suggest_invoice_no_fallback_without_user(db):
    # 定位不到用户名退回旧 INV 规则（防御路径）
    assert service.suggest_invoice_no(db, None, "stock").startswith("INV")


# ── 发票号可编辑 + 唯一校验 ───────────────────────────────


def test_create_with_custom_no_and_duplicate_rejected(db, bound_user):
    inv = service.create_invoice(db, InvoiceCreate(**_payload(invoice_no=" MY-NO-1 ")), user_id=5)
    db.flush()
    assert inv.invoice_no == "MY-NO-1"  # 去首尾空白

    with pytest.raises(ValueError, match="已存在"):
        service.create_invoice(db, InvoiceCreate(**_payload(invoice_no="MY-NO-1")), user_id=5)


def test_update_invoice_no_unique_excluding_self(db, bound_user):
    a = service.create_invoice(db, InvoiceCreate(**_payload(invoice_no="NO-A")), user_id=5)
    b = service.create_invoice(db, InvoiceCreate(**_payload(invoice_no="NO-B")), user_id=5)
    db.flush()

    # 改成别人的号 → 拒绝
    with pytest.raises(ValueError, match="已存在"):
        service.update_invoice(db, b, InvoiceUpdate(**_payload(invoice_no="NO-A")), user_id=5)
    # 回传自己的号（未变）→ 放行
    service.update_invoice(db, a, InvoiceUpdate(**_payload(invoice_no="NO-A")), user_id=5)
    assert a.invoice_no == "NO-A"
    # 不传号 → 保持原号
    service.update_invoice(db, a, InvoiceUpdate(**_payload()), user_id=5)
    assert a.invoice_no == "NO-A"
    # 改成新号 → 生效
    service.update_invoice(db, a, InvoiceUpdate(**_payload(invoice_no="NO-A2")), user_id=5)
    assert a.invoice_no == "NO-A2"


def test_suggest_and_check_endpoints(db, bound_user):
    service.create_invoice(db, InvoiceCreate(**_payload(invoice_no="stella-KC-1")), user_id=5)
    db.commit()
    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        data = client.get(
            "/api/invoice/invoices/suggest-no", params={"order_type": "stock"},
        ).json()["data"]
        assert data["invoice_no"] == "stella-KC-2"

        taken = client.get(
            "/api/invoice/invoices/check-no", params={"invoice_no": "stella-KC-1"},
        ).json()["data"]
        assert taken["available"] is False

        free = client.get(
            "/api/invoice/invoices/check-no", params={"invoice_no": "stella-KC-9"},
        ).json()["data"]
        assert free["available"] is True

        # 编辑场景排除自身
        own = db.query(Invoice).filter(Invoice.invoice_no == "stella-KC-1").first()
        self_ok = client.get(
            "/api/invoice/invoices/check-no",
            params={"invoice_no": "stella-KC-1", "exclude_id": own.id},
        ).json()["data"]
        assert self_ok["available"] is True


def test_create_endpoint_duplicate_returns_400(db, bound_user):
    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        body = InvoiceCreate(**_payload(invoice_no="DUP-1")).model_dump(mode="json")
        assert client.post("/api/invoice/invoices", json=body).status_code == 201
        resp = client.post("/api/invoice/invoices", json=body)
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]


def test_create_endpoint_race_integrity_returns_400(db, bound_user, monkeypatch):
    """并发竞态：预查通过后另一会话先落库 → flush 撞 unique 约束必须回 400 而非 500。

    IntegrityError 在 service 内部 flush 处就抛（不是 commit），
    router 的兜底必须覆盖整个写入（2026-07-14 对抗性审查 P1）。
    """
    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        body = InvoiceCreate(**_payload(invoice_no="RACE-1")).model_dump(mode="json")
        assert client.post("/api/invoice/invoices", json=body).status_code == 201
        # 模拟预查窗口失效（另一会话在预查之后、flush 之前落库了同号）
        monkeypatch.setattr(service, "invoice_no_exists", lambda *a, **k: False)
        resp = client.post("/api/invoice/invoices", json=body)
        assert resp.status_code == 400
        assert "占用" in resp.json()["detail"]
