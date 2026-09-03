"""OKKI 客户手动同步（按公司名）+ 客户搜索 overlay 合并测试。"""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.core.time import utc_now_naive
from app.invoice import customer_sync_service, okki_client, product_service, xiaoman_service
from app.invoice.models import InvoiceCustomerOverlay

OKKI_UID = 55411216
OTHER_UID = 99999999

QUERY_URL = "/api/invoice/customers/sync-from-okki"


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
def bound_user(db):
    """id=5 的方舟用户 stella，绑定 OKKI 账号 OKKI_UID；OKKI 人员镜像里有她的名字"""
    user = ArkUser(id=5, username="stella", password_hash="x", real_name="Stella")
    db.add(user)
    db.add(ArkUserExternalBinding(
        ark_user_id=5, provider="okki", external_account_id=str(OKKI_UID),
        binding_status="active", is_primary=True,
    ))
    db.flush()
    conn = db.get_bind().raw_connection()
    conn.cursor().execute(
        "INSERT OR IGNORE INTO lsordertest.user_basic (user_id, full_name, nickname) VALUES (?, ?, ?)",
        (str(OKKI_UID), "Stella Zhang", "stella"),
    )
    conn.commit()
    return user


def _seed_mirror_customer(db, company_id, name, owner_ids):
    conn = db.get_bind().raw_connection()
    conn.cursor().execute(
        "INSERT OR IGNORE INTO lsordertest.customer_info "
        "(company_id, company_name, country_name, owner_user_ids) VALUES (?, ?, ?, ?)",
        (str(company_id), name, "US", owner_ids),
    )
    conn.commit()


def _candidate(company_id, name, short_name=""):
    return {"company_id": company_id, "name": name, "short_name": short_name,
            "serial_id": f"S{company_id}", "is_public": 0}


def _info(company_id, name, owner_ids, update_time="2026-09-03 10:00:00"):
    return {
        "company_id": company_id,
        "name": name,
        "country": "US",
        "origin_name": "阿里询盘",
        "archive_type": 1,
        "trail_status": {"status_id": "1", "status_name": "成交"},
        "update_time": update_time,
        "owner": [{"user_id": oid, "nickname": f"u{oid}"} for oid in owner_ids],
    }


def _mock_okki(monkeypatch, candidates, infos):
    """infos: {company_id(int): info dict}；query 按名称子串过滤模拟模糊搜"""
    def _query(db, word, **kw):
        norm = str(word or "").lower()
        return [c for c in candidates if norm in str(c.get("name", "")).lower()]

    monkeypatch.setattr(okki_client, "query_companies_by_name", _query)
    monkeypatch.setattr(
        okki_client, "get_company_info", lambda db, company_id, **kw: infos[int(company_id)],
    )


# ── service：同步与落库 ──────────────────────────────────


def test_sync_creates_overlay_for_new_customer(db, bound_user, monkeypatch):
    _mock_okki(monkeypatch, [_candidate(88001, "Acme Hair Co")], {88001: _info(88001, "Acme Hair Co", [OKKI_UID])})

    result = customer_sync_service.sync_customer_from_okki(db, company_name=" Acme Hair Co ", operator_id=5)

    assert result["created"] is True
    assert result["company_id"] == "88001"
    assert result["company_name"] == "Acme Hair Co"
    assert result["country_name"] == "US"
    assert result["owner_user_ids"] == [str(OKKI_UID)]
    assert result["owner_names"] == ["Stella Zhang"]
    assert result["is_public_sea"] is False
    assert "Acme Hair Co" in result["message"]

    row = db.get(InvoiceCustomerOverlay, "88001")
    assert row is not None
    assert row.owner_user_ids == [str(OKKI_UID)]
    assert row.trail_status_name == "成交"
    assert row.source_update_time == "2026-09-03 10:00:00"
    assert row.synced_by == 5


def test_sync_updates_stale_owner_from_mirror(db, bound_user, monkeypatch):
    """镜像里客户 owner 还是别人（同步延迟）→ 同步后 overlay 纠正为最新负责人"""
    _seed_mirror_customer(db, 88002, "Beta Salon", f"[{OTHER_UID}]")
    _mock_okki(monkeypatch, [_candidate(88002, "Beta Salon")], {88002: _info(88002, "Beta Salon", [OKKI_UID])})

    result = customer_sync_service.sync_customer_from_okki(db, company_name="Beta Salon", operator_id=5)

    assert result["created"] is False  # 镜像已有，不是新客户
    assert "负责人" in result["changed_fields"]
    # 私海口径立即按新归属生效
    mine = product_service.search_customers(db, keyword="Beta", owner_okki_id=OKKI_UID)
    assert [c["company_id"] for c in mine] == ["88002"]
    # 旧 owner 不再能搜到（镜像的过期归属不得放行）
    other = product_service.search_customers(db, keyword="Beta", owner_okki_id=OTHER_UID)
    assert other == []


def test_sync_resync_without_changes_reports_latest(db, bound_user, monkeypatch):
    _mock_okki(monkeypatch, [_candidate(88001, "Acme Hair Co")], {88001: _info(88001, "Acme Hair Co", [OKKI_UID])})
    customer_sync_service.sync_customer_from_okki(db, company_name="Acme Hair Co")

    result = customer_sync_service.sync_customer_from_okki(db, company_name="Acme Hair Co")
    assert result["created"] is False
    assert result["changed_fields"] == []
    assert "已是最新" in result["message"]


def test_sync_exact_match_preferred_over_fuzzy(db, bound_user, monkeypatch):
    candidates = [_candidate(88002, "Acme Hair Co Ltd"), _candidate(88001, "Acme Hair Co")]
    infos = {88001: _info(88001, "Acme Hair Co", []), 88002: _info(88002, "Acme Hair Co Ltd", [])}
    _mock_okki(monkeypatch, candidates, infos)

    result = customer_sync_service.sync_customer_from_okki(db, company_name="acme hair co")
    assert result["company_id"] == "88001"
    assert result["is_public_sea"] is True  # owner 空 = 公海


def test_sync_ambiguous_requires_full_name(db, bound_user, monkeypatch):
    candidates = [_candidate(88001, "Acme Hair Co"), _candidate(88002, "Acme Beauty")]
    _mock_okki(monkeypatch, candidates, {})

    with pytest.raises(customer_sync_service.CustomerSyncError, match="相似客户"):
        customer_sync_service.sync_customer_from_okki(db, company_name="Acme")


def test_sync_not_found_and_blank_name(db, bound_user, monkeypatch):
    _mock_okki(monkeypatch, [], {})
    with pytest.raises(customer_sync_service.CustomerSyncError, match="未找到"):
        customer_sync_service.sync_customer_from_okki(db, company_name="Nobody Inc")
    with pytest.raises(customer_sync_service.CustomerSyncError, match="请输入"):
        customer_sync_service.sync_customer_from_okki(db, company_name="   ")


def test_sync_okki_failure_is_readable(db, bound_user, monkeypatch):
    def _boom(db, word, **kw):
        raise okki_client.OkkiApiError("OKKI 鉴权失败：invalid_client")

    monkeypatch.setattr(okki_client, "query_companies_by_name", _boom)
    with pytest.raises(customer_sync_service.CustomerSyncError, match="鉴权失败"):
        customer_sync_service.sync_customer_from_okki(db, company_name="Acme")


def test_sync_concurrent_insert_race_falls_back_to_update(db, bound_user, monkeypatch):
    """并发同步同一客户：检查窗口后另一请求已落库 → PK 冲突回退为更新，不抛 500"""
    _add_overlay(db, 88001, "Acme Hair Co", [OTHER_UID])  # 模拟并发请求已抢先落库
    _mock_okki(monkeypatch, [_candidate(88001, "Acme Hair Co")], {88001: _info(88001, "Acme Hair Co", [OKKI_UID])})

    real_get = db.get
    state = {"first": True}

    def flaky_get(model, pk, **kw):
        # 第一次查 overlay 时谎报不存在（模拟 check-then-insert 竞态窗口）
        if state["first"] and model is InvoiceCustomerOverlay:
            state["first"] = False
            return None
        return real_get(model, pk, **kw)

    monkeypatch.setattr(db, "get", flaky_get)
    result = customer_sync_service.sync_customer_from_okki(db, company_name="Acme Hair Co")
    assert result["company_id"] == "88001"
    assert result["created"] is False
    # 回退为更新：owner 已被纠正为最新
    assert db.get(InvoiceCustomerOverlay, "88001").owner_user_ids == [str(OKKI_UID)]


def test_sync_tolerates_malformed_okki_payload(db, bound_user, monkeypatch):
    """OKKI 字段形状漂移（owner 是 dict、trail_status 是 str）不抛 500"""
    info = _info(88001, "Acme Hair Co", [OKKI_UID])
    info["owner"] = {"user_id": OKKI_UID}  # 应为 list，故意给 dict
    info["trail_status"] = "成交"  # 应为 dict，故意给 str
    info["country_region"] = ["US"]  # 应为 dict，故意给 list
    _mock_okki(monkeypatch, [_candidate(88001, "Acme Hair Co")], {88001: info})

    result = customer_sync_service.sync_customer_from_okki(db, company_name="Acme Hair Co")
    assert result["company_id"] == "88001"
    assert result["is_public_sea"] is True  # 形状异常的 owner 按空处理，不崩
    assert result["country_name"] == "US"


# ── search_customers overlay 合并 ────────────────────────


def _add_overlay(db, company_id, name, owner_ids, source_update_time="2026-09-03 10:00:00"):
    db.add(InvoiceCustomerOverlay(
        company_id=str(company_id), company_name=name, country_name="US",
        owner_user_ids=[str(v) for v in owner_ids], source_update_time=source_update_time,
    ))
    db.flush()


def test_search_overlay_only_customer_visible(db):
    _add_overlay(db, 88003, "Overlay Only Salon", [OKKI_UID])

    everyone = product_service.search_customers(db, keyword="Overlay")
    assert [c["company_id"] for c in everyone] == ["88003"]

    mine = product_service.search_customers(db, keyword="Overlay", owner_okki_id=OKKI_UID)
    assert [c["company_id"] for c in mine] == ["88003"]

    other = product_service.search_customers(db, keyword="Overlay", owner_okki_id=OTHER_UID)
    assert other == []


def test_search_mirror_wins_when_fresher(db):
    """镜像 update_time 已追上（不旧于 overlay 同步时的 OKKI 版本）→ 以镜像为准"""
    db.execute(text("ALTER TABLE lsordertest.customer_info ADD COLUMN update_time TEXT"))
    conn = db.get_bind().raw_connection()
    conn.cursor().execute(
        "INSERT OR IGNORE INTO lsordertest.customer_info "
        "(company_id, company_name, country_name, owner_user_ids, update_time) VALUES (?, ?, ?, ?, ?)",
        ("88004", "Mirror Fresh Name", "DE", f"[{OTHER_UID}]", "2026-09-03 12:00:00"),
    )
    conn.commit()
    _add_overlay(db, 88004, "Overlay Stale Name", [OKKI_UID], source_update_time="2026-09-03 10:00:00")

    rows = product_service.search_customers(db, keyword="88004")
    assert [r["company_name"] for r in rows] == ["Mirror Fresh Name"]
    # 镜像 owner（最新）是别人 → 我的私海搜不到
    mine = product_service.search_customers(db, keyword="88004", owner_okki_id=OKKI_UID)
    assert mine == []


# ── okki_client：客户查询 401 自愈重试 ───────────────────


def test_query_companies_retries_once_on_auth_failure(db, monkeypatch):
    monkeypatch.setattr(
        okki_client, "get_settings",
        lambda: SimpleNamespace(
            OKKI_CLIENT_ID="cid", OKKI_CLIENT_SECRET="sec", OKKI_API_BASE="https://okki.test",
        ),
    )
    row = xiaoman_service.get_or_create_settings(db)
    row.access_token = "stale_token"
    row.token_expires_at = utc_now_naive() + timedelta(hours=2)
    db.commit()

    calls = []

    class _Resp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def json(self):
            return self._payload

    def _fake_get(url, headers=None, params=None, timeout=None):
        calls.append(params)
        if headers["Authorization"] == "Bearer stale_token":
            return _Resp({"error": "access_denied"}, status_code=401)
        return _Resp({"code": 0, "data": {"list": [{"company_id": 1, "name": "Acme"}], "totalItem": 1}})

    monkeypatch.setattr(okki_client.httpx, "get", _fake_get)
    monkeypatch.setattr(
        okki_client, "fetch_token",
        lambda: ("renewed_token", utc_now_naive() + timedelta(hours=8)),
    )

    items = okki_client.query_companies_by_name(db, "Acme")
    assert items == [{"company_id": 1, "name": "Acme"}]
    assert len(calls) == 2
    # 查重参数：按公司名搜 + 关键词透传
    assert calls[0] == {"word": "Acme", "search_field": "name", "count": 20}


# ── 端点级 ──────────────────────────────────────────────


def test_sync_endpoint_success_and_errors(db, bound_user, monkeypatch):
    _mock_okki(monkeypatch, [_candidate(88001, "Acme Hair Co")], {88001: _info(88001, "Acme Hair Co", [OKKI_UID])})

    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        resp = client.post(QUERY_URL, json={"company_name": "Acme Hair Co"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["company_id"] == "88001"
        assert data["created"] is True
        # 同步后客户搜索（私海）立即可见
        found = client.get(
            "/api/invoice/customers/search",
            params={"keyword": "Acme", "private_only": True},
        ).json()["data"]
        assert [c["company_id"] for c in found["items"]] == ["88001"]

    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        missing = client.post(QUERY_URL, json={"company_name": "Nobody Inc"})
        assert missing.status_code == 400
        assert "未找到" in missing.json()["detail"]


def test_sync_endpoint_requires_invoice_write(db, bound_user, monkeypatch):
    _mock_okki(monkeypatch, [_candidate(88001, "Acme Hair Co")], {88001: _info(88001, "Acme Hair Co", [])})
    with _client(db, sub="5", permissions=["invoice:read"]) as client:
        resp = client.post(QUERY_URL, json={"company_name": "Acme Hair Co"})
        assert resp.status_code == 403
