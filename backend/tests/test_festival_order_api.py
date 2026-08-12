"""采购节订单明细：口径、分页与登录态数据范围。"""

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.models import ArkPermission, ArkUser, ArkUserExternalBinding
from app.auth.service import seed_role_permissions
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.festival import router as festival_router


NEW = '{"22595163468": "是"}'
NEW_SOCIAL = '{"22595163468": "是", "45285192666116": "社媒开发"}'
FIRST = '{"20528142733548": "是"}'
RE = '{"22595163468": "否"}'


def _setup(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lsordertest.user_rel_team (
            id INTEGER PRIMARY KEY, Name TEXT, user_id TEXT, En_name TEXT,
            Team TEXT, Camp TEXT, gmv_t INTEGER DEFAULT 0, newclient_t INTEGER DEFAULT 0
        )
    """))
    db.execute(text("DELETE FROM lsordertest.user_rel_team"))
    db.execute(text("DELETE FROM lsordertest.okki_orders"))
    db.execute(text("DELETE FROM lsordertest.customer_info"))
    db.execute(text("""
        INSERT INTO lsordertest.user_rel_team
          (id, Name, user_id, Team, Camp, newclient_t) VALUES
          (1, '张心茹', 'U1', '乘风破浪', '阵营一', 8),
          (2, '胡宁宁', 'U2', '星火', '阵营二', 6),
          (3, '隋晓茹', '57130433', '星火', '阵营一', 6)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_info (company_id, company_name) VALUES
          ('C1', 'Alpha Hair'), ('C2', 'Beta Beauty'), ('C3', 'Gamma Wigs')
    """))
    rows = [
        ("N1", "NO-N1", "C1", 1000, "U1", NEW, "2026-08-02"),
        ("N2", "NO-N2", "C1", 500, "U1", NEW_SOCIAL, "2026-08-03"),
        ("N3", "NO-N3", "C2", 900, "U2", NEW, "2026-08-04"),
        ("F1", "NO-F1", "C1", 800, "U1", FIRST, "2026-08-10"),
        ("F2", "NO-F2", "C1", 700, "U1", FIRST, "2026-09-10"),
        ("R1", "NO-R1", "C1", 2500, "U1", RE, "2026-09-15"),
        ("R2", "NO-R2", "C3", 4000, "U2", RE, "2026-09-16"),
        ("D1", "NO-D1", "C2", 9999, "57130433", NEW, "2026-08-05"),
    ]
    for row in rows:
        db.execute(text("""
            INSERT INTO lsordertest.okki_orders
              (order_id, order_no, company_id, amount_usd, user_id, custom_fields,
               account_date, trail, status, status_name, departments)
            VALUES (:oid, :ono, :cid, :amt, :uid, :cf, :day, '公司',
                    '13972831656', NULL, '{}')
        """), dict(zip(("oid", "ono", "cid", "amt", "uid", "cf", "day"), row)))
    user = ArkUser(username="sales", real_name="张心茹", password_hash="x")
    admin = ArkUser(username="manager", real_name="管理员", password_hash="x")
    unbound = ArkUser(username="unbound", real_name="未绑定", password_hash="x")
    db.add_all([user, admin, unbound])
    db.flush()
    db.add(ArkUserExternalBinding(
        ark_user_id=user.id, provider="okki", external_account_id="U1",
        binding_status="active", is_primary=True,
    ))
    db.commit()
    return user, admin, unbound


@contextmanager
def _client(db, user, permissions, roles=()):
    app = FastAPI()
    app.include_router(festival_router.router, prefix="/api/festival")
    app.dependency_overrides[get_db] = lambda: db
    token = create_access_token({
        "sub": str(user.id), "username": user.username,
        "roles": list(roles), "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def test_festival_order_permissions_are_seeded(db):
    seed_role_permissions(db)
    by_code = {
        row.code: row for row in db.query(ArkPermission).filter(
            ArkPermission.code.in_(("festival_order:read", "festival_order:read_all"))
        )
    }
    assert by_code["festival_order:read"].kind == "page"
    assert by_code["festival_order:read_all"].kind == "data"


def test_salesperson_scope_ignores_requested_user_and_scores_customer_once(db):
    salesperson, _, _ = _setup(db)
    with _client(db, salesperson, ("festival_order:read",)) as client:
        summary = client.get("/api/festival/orders/summary", params={"user_id": "U2"})
        assert summary.status_code == 200
        data = summary.json()["data"]
        assert data["scope"] == "self"
        assert data["selected_user_id"] == "U1"
        assert data["new_sign"] == {
            "count": 1, "target": 8, "progress_percent": 12.5, "points": 1.5,
        }
        assert data["first_return_count"] == 1
        assert data["repurchase_amount"] == 2500.0

        response = client.get("/api/festival/orders", params={
            "type": "new_sign", "user_id": "U2", "page": 1, "page_size": 20,
        })
        assert response.status_code == 200
        rows = response.json()["data"]["items"]
        assert [row["order_no"] for row in rows] == ["NO-N2", "NO-N1"]
        assert sum(row["points"] for row in rows) == 1.5
        by_order = {row["order_no"]: row for row in rows}
        assert by_order["NO-N1"]["points"] == 1.5
        assert by_order["NO-N2"]["points"] == 0
        assert by_order["NO-N2"]["points_note"] == "同客户已计分"


def test_read_all_defaults_company_and_can_filter_roster_user(db):
    _, admin, _ = _setup(db)
    permissions = ("festival_order:read", "festival_order:read_all")
    with _client(db, admin, permissions) as client:
        company = client.get("/api/festival/orders/summary").json()["data"]
        assert company["scope"] == "all"
        assert company["new_sign"]["count"] == 2
        assert company["new_sign"]["target"] == 143
        assert {row["user_id"] for row in company["users"]} == {"U1", "U2"}
        assert company["repurchase_amount"] == 2500.0  # C3 没有 2025+ 新签

        selected = client.get(
            "/api/festival/orders/summary", params={"user_id": "U2"}
        ).json()["data"]
        assert selected["scope"] == "user"
        assert selected["selected_user_name"] == "胡宁宁"
        assert selected["new_sign"]["target"] == 6

        invalid = client.get(
            "/api/festival/orders/summary", params={"user_id": "NOT-IN-ROSTER"}
        )
        assert invalid.status_code == 422


def test_unbound_salesperson_gets_actionable_error(db):
    _, _, unbound = _setup(db)
    with _client(db, unbound, ("festival_order:read",)) as client:
        response = client.get("/api/festival/orders/summary")
        assert response.status_code == 422
        assert "外部账号绑定" in response.text


def test_page_permission_is_required(db):
    _, admin, _ = _setup(db)
    with _client(db, admin, ("festival_order:read_all",)) as client:
        assert client.get("/api/festival/orders/summary").status_code == 403


def test_keyword_and_pagination_keep_required_columns(db):
    _, admin, _ = _setup(db)
    permissions = ("festival_order:read", "festival_order:read_all")
    with _client(db, admin, permissions) as client:
        response = client.get("/api/festival/orders", params={
            "type": "new_sign", "keyword": "Alpha", "page": 1, "page_size": 1,
        })
        data = response.json()["data"]
        assert data["total"] == 2
        assert data["page_size"] == 1
        assert set((
            "order_no", "account_date", "amount_usd", "company_name",
            "user_name", "team", "camp",
        )).issubset(data["items"][0])
