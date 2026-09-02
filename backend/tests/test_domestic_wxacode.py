"""内贸订单产品进度小程序码：scene 签名 / 免登录 track 端点 / 码生成端点

免登录端点的唯一授权凭证是 HMAC 签名——签名域隔离（track vs 流转卡，同一个
item_id 两个域）、伪签拒绝、软删单拦截、完整订单返回，都是这个
口子的安全边界，必须钉死。
"""

import hashlib
import hmac as hmac_mod
from contextlib import contextmanager
from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domestic import order_service, report_service
from app.domestic.models import (
    DomesticBasePrice,
    DomesticCustomer,
    DomesticOrder,
    DomesticOrderItem,
)
from app.domestic.schemas import OrderCreate, OrderItemInput, ProductAttrs
from app.domestic import constants as C
from app.system.models import SysDict

_DEFAULT_SECRET = Settings.model_fields["QR_SIGN_SECRET"].default


@pytest.fixture(autouse=True)
def _non_default_secret(monkeypatch):
    """密钥停在仓库默认值时生成/验证两侧都拒绝服务（F1 兜底）——
    功能测试先换成一个"已配置"的密钥，默认值行为单独测。"""
    monkeypatch.setattr(get_settings(), "QR_SIGN_SECRET", "unit-test-secret-not-default")


# ── fixtures ─────────────────────────────────────────


def _user(db, username="wxacode-user"):
    user = ArkUser(username=username, password_hash="x", real_name=username)
    db.add(user)
    db.flush()
    return user


def _attrs(craft="递针旋全头套"):
    return ProductAttrs(
        product_type="cap", craft=craft, net_color="呼吸红",
        size="s", length="15厘米", density="65%",
        hair_style_series="直发",
    )


def _create_order(db, user, item_count=1):
    attrs_list = [_attrs(f"递针旋全头套{i or ''}") for i in range(item_count)]
    values = {
        (C.ORDER_TYPE_DICT, "first_order"),
        (C.ORDER_CHANNEL_DICT, "wechat"),
    }
    for attrs in attrs_list:
        for field, dict_type in C.ATTR_DICTS[attrs.product_type].items():
            value = getattr(attrs, field)
            if value is not None:
                values.add((dict_type, value))
    for dict_type, code in values:
        if not db.query(SysDict.id).filter_by(type=dict_type, code=code).first():
            db.add(SysDict(type=dict_type, code=code, label=code, sort=1, is_active=True))
    db.flush()
    customer = DomesticCustomer(
        shop_name=f"马姐假发-{uuid4()}",
        membership_level="black",
        balance=0,
        created_by=user.id,
    )
    db.add(customer)
    db.flush()
    items = []
    for i, attrs in enumerate(attrs_list):
        base = DomesticBasePrice(
            product_type=attrs.product_type,
            craft=attrs.craft,
            length=attrs.length,
            original_price=120,
            version=1,
        )
        db.add(base)
        db.flush()
        items.append(OrderItemInput(
            client_key=f"wx-line-{i + 1}",
            attrs=attrs,
            order_qty=10 + i,
            expected_quote={
                "original_price": "120.00",
                "base_price_version": base.version,
                "discount_price": "0.00",
                "membership_level": "black",
                "pricing_rule": "member_reduction",
                "pricing_version": "domestic-member-v1",
            },
        ))
    payload = OrderCreate(
        request_id=str(uuid4()),
        order_no="710",
        order_date=date(2026, 7, 28),
        customer_id=customer.id,
        order_category="normal",
        order_type="first_order",
        order_channel="wechat",
        items=items,
    )
    return order_service.create_order(db, payload, user.id)


def _items_of(db, order_id):
    return (
        db.query(DomesticOrderItem)
        .filter(DomesticOrderItem.order_id == order_id)
        .order_by(DomesticOrderItem.id.asc())
        .all()
    )


@contextmanager
def _mini_client(db):
    """track 是免登录端点：client 不带任何 Authorization"""
    from app.mini.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/mini")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client


@contextmanager
def _domestic_client(db, user, permissions=("domestic:read",)):
    from app.domestic.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(user.id), "username": user.username,
        "roles": [], "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


# ── scene 签名 ────────────────────────────────────────


def test_track_scene_roundtrip():
    scene = report_service.generate_track_scene(123)
    assert scene.startswith("i:123:")
    assert len(scene) <= 32  # 微信 scene 上限
    sign = scene.rsplit(":", 1)[1]
    assert len(sign) == 16  # 免登录口子用 64-bit 签名，8 hex 不够
    valid, item_id = report_service.verify_track_scene(scene)
    assert valid and item_id == 123


def test_track_scene_rejects_tampering():
    scene = report_service.generate_track_scene(123)
    sign = scene.rsplit(":", 1)[1]
    # 换 item_id 不换签名 → 拒
    assert report_service.verify_track_scene(f"i:124:{sign}") == (False, 124)
    # 伪造签名（格式合法的 16 hex）→ 拒
    assert report_service.verify_track_scene("i:123:" + "0" * 16)[0] is False
    # 乱七八糟的输入（含旧版订单级 o: 格式）→ 拒且不炸
    for garbage in ("", None, "i:abc:" + "1" * 16, "o:123:" + "1" * 16,
                    "ARK-D:1:aaaaaaaa", "i:1:zzzzzzzz", "i:1:abcd1234"):
        assert report_service.verify_track_scene(garbage)[0] is False


def test_track_scene_domain_isolated_from_item_qr():
    """同一个 item_id 有两个签名域：流转卡 ARK-D:<id>（贴在车间人人可见）
    与进度码 ARK-DT:<id>。流转卡的 HMAC 拼不出进度码。"""
    secret = get_settings().QR_SIGN_SECRET.encode()
    card_domain_sign = hmac_mod.new(secret, b"ARK-D:5", hashlib.sha256).hexdigest()[:16]
    assert report_service.verify_track_scene(f"i:5:{card_domain_sign}")[0] is False


def test_default_secret_locks_generation_and_verification(db, monkeypatch):
    """QR_SIGN_SECRET 停在仓库默认值 = 谁都能离线伪造签名，两侧都必须拒绝服务"""
    creator = _user(db)
    order = _create_order(db, creator)
    item = _items_of(db, order["id"])[0]
    monkeypatch.setattr(get_settings(), "QR_SIGN_SECRET", _DEFAULT_SECRET)
    assert report_service.qr_secret_is_default() is True

    with _mini_client(db) as client:
        resp = client.get("/api/mini/domestic/track", params={"scene": "i:1:" + "a" * 16})
    assert resp.status_code == 503

    with _domestic_client(db, creator) as client:
        resp = client.get(f"/api/domestic/items/{item.id}/wxacode")
    assert resp.status_code == 503


# ── 免登录 track 端点 ─────────────────────────────────


def test_track_returns_complete_order(db):
    """任一进度码都返回其所属订单的全部明细。"""
    creator = _user(db)
    order = _create_order(db, creator, item_count=2)
    first, second = _items_of(db, order["id"])
    scene = report_service.generate_track_scene(first.id)

    with _mini_client(db) as client:
        resp = client.get("/api/mini/domestic/track", params={"scene": scene})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == order["id"]
    assert [i["id"] for i in data["items"]] == [first.id, second.id]
    assert data["items"][0]["order_qty"] == first.order_qty
    assert data["items"][1]["order_qty"] == second.order_qty
    assert "customer_balance" not in data
    assert "charged_amount" not in data
    assert "created_by_name" not in data


def test_track_image_allows_other_item_in_same_order_only(db, tmp_path, monkeypatch):
    creator = _user(db)
    order = _create_order(db, creator, item_count=2)
    first, second = _items_of(db, order["id"])
    second.style_images = ["refs/second.png"]
    db.flush()
    root = tmp_path / "domestic"
    image = root / "refs" / "second.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png-test")
    monkeypatch.setattr(get_settings(), "DOMESTIC_STORAGE_ROOT", str(root))
    scene = report_service.generate_track_scene(first.id)

    with _mini_client(db) as client:
        allowed = client.get(
            "/api/mini/domestic/track-image",
            params={"scene": scene, "rel_path": "refs/second.png"},
        )
        denied = client.get(
            "/api/mini/domestic/track-image",
            params={"scene": scene, "rel_path": "refs/not-referenced.png"},
        )
    assert allowed.status_code == 200
    assert allowed.content == b"png-test"
    assert denied.status_code == 403


def test_track_rejects_bad_signature(db):
    creator = _user(db)
    order = _create_order(db, creator)
    item = _items_of(db, order["id"])[0]

    with _mini_client(db) as client:
        resp = client.get("/api/mini/domestic/track", params={"scene": f"i:{item.id}:" + "0" * 16})
    assert resp.status_code == 403


def test_track_blocks_soft_deleted_order(db):
    """码贴在外面收不回来，删单后必须在服务端挡住"""
    creator = _user(db)
    order = _create_order(db, creator)
    item = _items_of(db, order["id"])[0]
    scene = report_service.generate_track_scene(item.id)
    db.query(DomesticOrder).filter(DomesticOrder.id == order["id"]).update({"deleted_flag": 1})
    db.flush()

    with _mini_client(db) as client:
        resp = client.get("/api/mini/domestic/track", params={"scene": scene})
    assert resp.status_code == 404


def test_track_404_on_missing_item(db):
    """签名合法但明细不存在（比如明细被删）→ 404 不炸"""
    scene = report_service.generate_track_scene(999999)
    with _mini_client(db) as client:
        resp = client.get("/api/mini/domestic/track", params={"scene": scene})
    assert resp.status_code == 404


# ── 码生成端点（微信接口 mock 掉）─────────────────────


def test_wxacode_endpoint_returns_image(db, monkeypatch):
    from app.mini import wx_client

    creator = _user(db)
    order = _create_order(db, creator)
    item = _items_of(db, order["id"])[0]
    captured = {}

    def fake_b64(scene, page):
        captured.update(scene=scene, page=page)
        return "data:image/jpeg;base64,ZmFrZQ=="  # 微信实际返回 jpeg

    monkeypatch.setattr(wx_client, "get_wxacode_base64", fake_b64)

    with _domestic_client(db, creator) as client:
        resp = client.get(f"/api/domestic/items/{item.id}/wxacode")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["image_base64"].startswith("data:image/jpeg;base64,")
    assert data["scene"] == report_service.generate_track_scene(item.id)
    assert data["product_name"] == item.product_name
    assert data["env_version"] in ("release", "trial", "develop")  # 前端据此提示「勿发客户」
    assert captured["page"] == "pages/domestic/track/track"


def test_wxacode_endpoint_404_on_deleted_order(db, monkeypatch):
    from app.mini import wx_client

    creator = _user(db)
    order = _create_order(db, creator)
    item = _items_of(db, order["id"])[0]
    db.query(DomesticOrder).filter(DomesticOrder.id == order["id"]).update({"deleted_flag": 1})
    db.flush()
    monkeypatch.setattr(wx_client, "get_wxacode_base64", lambda *a, **k: "unused")

    with _domestic_client(db, creator) as client:
        resp = client.get(f"/api/domestic/items/{item.id}/wxacode")
    assert resp.status_code == 404


def test_wxacode_endpoint_502_when_wx_fails(db, monkeypatch):
    """微信侧失败（正式版未发布 / IP 白名单）要把原因透传给前端，不吞"""
    from app.mini import wx_client

    creator = _user(db)
    order = _create_order(db, creator)
    item = _items_of(db, order["id"])[0]

    def boom(scene, page):
        raise wx_client.WxApiError("生成小程序码失败: 41030 invalid page")

    monkeypatch.setattr(wx_client, "get_wxacode_base64", boom)

    with _domestic_client(db, creator) as client:
        resp = client.get(f"/api/domestic/items/{item.id}/wxacode")
    assert resp.status_code == 502
    assert "41030" in resp.json()["detail"]


# ── wx_client：token 失效自动强刷重试 ─────────────────


def test_wxacode_retries_once_on_stale_token(monkeypatch):
    from app.mini import wx_client

    calls = {"token": 0, "post": 0}

    def fake_token(force_refresh=False):
        calls["token"] += 1
        return "fresh" if force_refresh else "stale"

    class FakeResponse:
        def __init__(self, ok):
            self.headers = {"content-type": "image/jpeg" if ok else "application/json"}
            self.content = b"jpeg-bytes"

        def json(self):
            return {"errcode": 40001, "errmsg": "invalid credential"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            calls["post"] += 1
            return FakeResponse(ok="fresh" in url)

    monkeypatch.setattr(wx_client, "get_access_token", fake_token)
    monkeypatch.setattr(wx_client.httpx, "Client", FakeClient)

    content, mime = wx_client.get_wxacode_image("i:1:" + "a" * 16, "pages/domestic/track/track")
    assert content == b"jpeg-bytes"
    assert mime == "image/jpeg"
    assert calls["post"] == 2  # 第一次 40001，强刷 token 后成功
