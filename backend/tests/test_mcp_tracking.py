"""MCP 网关(物流)测试 — 安全边界为主:

- token 解析归属正确 / 无效 / 撤销 / 用户禁用 / 空 token
- claims dict 结构与登录一致
- Context 取 Authorization 头(Bearer / 缺失)
- 数据范围归属:token 身份经 list_shipments 只见本人运单(越权防线)
- carrier 归一化 / 权限判定

注:MCP 工具自开 SessionLocal，与 SQLite :memory: 多连接不兼容，故在服务层验证
复用链路(token→identity→apply_data_scope)——这正是安全关键路径。工具装配与注册
已在实现期通过 live 探针验证(server mount + list_tools)。
"""

import pytest

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.auth.utils import generate_refresh_token
from app.mcp.models import MCPToken
from app.mcp.auth import (
    resolve_token, build_current_user, require_identity,
    _extract_bearer_from_ctx, MCPAuthError,
)
from app.mcp.tools import _norm_carrier, _has_perm, _visible_under_scope, SUPPORTED_CARRIERS
from app.tracking.models import ShipmentTracking
from app.tracking import shipment_service


# ── fixtures ──────────────────────────────────────────────

def _make_user(db, uid, username, dingtalk_id, perm_codes):
    user = ArkUser(
        id=uid, username=username, password_hash="x", real_name=username,
        dingtalk_id=dingtalk_id, is_active=True,
    )
    db.add(user)
    role = ArkRole(id=uid, name=f"role_{username}", label=username)
    db.add(role)
    db.flush()
    db.add(ArkUserRole(user_id=uid, role_id=role.id))
    for code in perm_codes:
        perm = db.query(ArkPermission).filter(ArkPermission.code == code).first()
        if perm is None:
            module, action = code.split(":")
            perm = ArkPermission(code=code, module=module, action=action, label=code)
            db.add(perm)
            db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=perm.id))
    db.flush()
    return user


def _issue_token(db, user):
    plain, token_hash = generate_refresh_token()
    row = MCPToken(token_hash=token_hash, user_id=user.id, label="test")
    db.add(row)
    db.flush()
    return plain, row


def _make_shipment(db, waybill, dingtalk_id, dingtalk_name):
    db.add(ShipmentTracking(
        waybill_no=waybill, carrier="DHL", carrier_name="DHL",
        dingtalk_user_id=dingtalk_id, dingtalk_user_name=dingtalk_name,
        current_status="in_transit", is_active=True,
    ))
    db.flush()


class _FakeReq:
    def __init__(self, headers):
        self.headers = headers


class _FakeCtx:
    def __init__(self, headers):
        self.request_context = type("RC", (), {"request": _FakeReq(headers)})()


# ── token 解析 ────────────────────────────────────────────

def test_resolve_token_happy_and_claims(db):
    user = _make_user(db, 1, "spA", "ddA", ["tracking:read", "tracking:write"])
    plain, _ = _issue_token(db, user)

    identity = resolve_token(db, plain)
    assert identity["sub"] == "1"
    assert identity["username"] == "spA"
    assert set(identity["permissions"]) == {"tracking:read", "tracking:write"}
    assert identity["roles"] == ["role_spA"]


def test_resolve_token_invalid(db):
    with pytest.raises(MCPAuthError):
        resolve_token(db, "not-a-real-token")


def test_resolve_token_empty(db):
    with pytest.raises(MCPAuthError):
        resolve_token(db, "")


def test_resolve_token_revoked(db):
    user = _make_user(db, 2, "spB", "ddB", ["tracking:read"])
    plain, row = _issue_token(db, user)
    row.is_active = False
    db.flush()
    with pytest.raises(MCPAuthError):
        resolve_token(db, plain)


def test_resolve_token_disabled_user(db):
    user = _make_user(db, 3, "spC", "ddC", ["tracking:read"])
    plain, _ = _issue_token(db, user)
    user.is_active = False
    db.flush()
    with pytest.raises(MCPAuthError):
        resolve_token(db, plain)


def test_build_current_user_shape(db):
    user = _make_user(db, 4, "spD", "ddD", ["tracking:read"])
    cu = build_current_user(user)
    assert set(cu.keys()) == {"sub", "username", "roles", "permissions"}


# ── Context 取头 ──────────────────────────────────────────

def test_extract_bearer_variants():
    assert _extract_bearer_from_ctx(_FakeCtx({"authorization": "Bearer abc123"})) == "abc123"
    # 无 Bearer 前缀时取原值
    assert _extract_bearer_from_ctx(_FakeCtx({"authorization": "abc123"})) == "abc123"


def test_extract_bearer_missing_request_raises():
    class NoReq:
        request_context = type("RC", (), {"request": None})()
    with pytest.raises(MCPAuthError):
        _extract_bearer_from_ctx(NoReq())


def test_require_identity_end_to_end(db):
    user = _make_user(db, 5, "spE", "ddE", ["tracking:read"])
    plain, _ = _issue_token(db, user)
    ctx = _FakeCtx({"authorization": f"Bearer {plain}"})
    identity = require_identity(ctx, db)
    assert identity["username"] == "spE"


# ── 数据范围归属(越权防线)─────────────────────────────────

def test_data_scope_only_own_shipments(db):
    """token 身份经 list_shipments 只应见本人(dingtalk_user_id)运单。"""
    a = _make_user(db, 10, "salesA", "dtA", ["tracking:read"])
    _make_user(db, 11, "salesB", "dtB", ["tracking:read"])
    _make_shipment(db, "WBA001", "dtA", "salesA")
    _make_shipment(db, "WBB001", "dtB", "salesB")
    plain_a, _ = _issue_token(db, a)

    identity = resolve_token(db, plain_a)
    result = shipment_service.list_shipments(db, identity, page=1, page_size=50)
    waybills = {it["waybill_no"] for it in result["items"]}
    assert waybills == {"WBA001"}
    assert "WBB001" not in waybills


def test_data_scope_read_all_sees_all(db):
    a = _make_user(db, 20, "mgr", "dtM", ["tracking:read", "tracking:read_all"])
    _make_shipment(db, "WBX", "dtX", "x")
    _make_shipment(db, "WBY", "dtY", "y")
    plain, _ = _issue_token(db, a)
    identity = resolve_token(db, plain)
    result = shipment_service.list_shipments(db, identity, page=1, page_size=50)
    waybills = {it["waybill_no"] for it in result["items"]}
    assert {"WBX", "WBY"}.issubset(waybills)


# ── 纯函数 ────────────────────────────────────────────────

def test_norm_carrier_supported():
    assert _norm_carrier("dhl") == "DHL"
    assert _norm_carrier("FedEx") == "FEDEX"
    assert _norm_carrier(" FEDEX ") == "FEDEX"


def test_norm_carrier_unsupported():
    with pytest.raises(ValueError) as e:
        _norm_carrier("UPS")
    assert "UPS" in str(e.value)
    for c in SUPPORTED_CARRIERS:
        assert c in str(e.value)


def test_has_perm():
    assert _has_perm({"roles": ["super_admin"], "permissions": []}, "tracking:write")
    assert _has_perm({"roles": [], "permissions": ["tracking:read"]}, "tracking:read", "tracking:read_all")
    assert not _has_perm({"roles": [], "permissions": ["tracking:read"]}, "tracking:write")


# ── track 归属校验(S1 修复:track_shipment 不再跨归属读他人 PII)──────

def test_track_scope_owner_visible(db):
    a = _make_user(db, 30, "trkA", "trkDtA", ["tracking:read"])
    _make_shipment(db, "TRK-A", "trkDtA", "trkA")
    identity = build_current_user(a)
    assert _visible_under_scope(db, identity, "TRK-A") is True


def test_track_scope_other_user_blocked(db):
    _make_user(db, 31, "trkA2", "trkDtA2", ["tracking:read"])
    b = _make_user(db, 32, "trkB2", "trkDtB2", ["tracking:read"])
    _make_shipment(db, "TRK-A2", "trkDtA2", "trkA2")  # 归属 A
    identity_b = build_current_user(b)
    # B 明知运单号也查不到 A 的运单 → 不越权读 PII
    assert _visible_under_scope(db, identity_b, "TRK-A2") is False


def test_track_scope_read_all_sees_any(db):
    m = _make_user(db, 33, "trkMgr", "trkDtM", ["tracking:read", "tracking:read_all"])
    _make_shipment(db, "TRK-X", "someoneelse", "someone")
    identity = build_current_user(m)
    assert _visible_under_scope(db, identity, "TRK-X") is True


# ── B1 回归锁:工具 inputSchema 不得含 ctx(必须靠 Context 注解注入)──────

async def test_tools_schema_excludes_ctx():
    from app.mcp.server import mcp
    tools = await mcp.list_tools()
    assert {t.name for t in tools} == {"record_shipment", "track_shipment", "list_my_shipments", "list_asset_taxonomy", "search_assets"}
    for t in tools:
        schema = t.inputSchema or {}
        props = schema.get("properties", {})
        required = schema.get("required", [])
        assert "ctx" not in props, f"{t.name} 的 inputSchema 泄露了 ctx(Context 未被识别注入)"
        assert "ctx" not in required, f"{t.name} 把 ctx 列为必填(客户端无法调用)"
        assert "params" in props


# ── 真实 HTTP 端到端(锁 B1 + DNS-rebinding 配置 + 传输链路)──────

def _sse_or_json(resp):
    ct = resp.headers.get("content-type") or ""
    if "event-stream" in ct:
        import json as _j
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return _j.loads(line[5:].strip())
    return resp.json()


async def test_http_end_to_end_tools_and_auth():
    """经真实 streamable-HTTP 传输:工具可列出;无 token 调用被工具内鉴权优雅拦截。

    这条同时锁死:①Context 注入(工具真的跑起来而非被 schema 拒)②DNS-rebinding
    配置正确(localhost/生产域名不被 421)③无 token → _err 而非 500/崩溃。
    """
    import json
    import httpx
    from fastapi import FastAPI
    from app.mcp.server import mount_mcp, mcp

    app = FastAPI()
    mount_mcp(app)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
            H = {"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"}
            r = await c.post("/mcp/", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}, headers=H)
            assert r.status_code == 200, f"initialize 失败: {r.status_code} {r.text[:120]}"
            sid = r.headers.get("mcp-session-id")
            H2 = dict(H)
            if sid:
                H2["mcp-session-id"] = sid
            await c.post("/mcp/", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=H2)

            rl = await c.post("/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=H2)
            names = {t["name"] for t in (_sse_or_json(rl).get("result") or {}).get("tools", [])}
            assert names == {"record_shipment", "track_shipment", "list_my_shipments", "list_asset_taxonomy", "search_assets"}

            rc = await c.post("/mcp/", json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "list_my_shipments", "arguments": {"params": {"limit": 3}}}}, headers=H2)
            content = (_sse_or_json(rc).get("result") or {}).get("content") or []
            assert content, "tools/call 无返回内容(工具未执行?)"
            payload = json.loads(content[0]["text"])
            # 工具确实执行到了鉴权层:无 token → ok=False 且提示带 token
            assert payload["ok"] is False and "token" in payload["error"]
