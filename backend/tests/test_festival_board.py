"""采购节大屏取数 service 测试（管钱计算：积分系数 / 同客户去重 / 名册限定 / GMV 口径）"""

from datetime import date

from sqlalchemy import text

from app.festival import service
from app.models.employee import EmployeeAttributeHistory

DEPT = '[{"department_id": 24925, "rate": 100}]'
MARK_NEW = '{"22595163468": "是", "691123983470": "定制品", "20528142733548": ""}'
MARK_RE = '{"22595163468": "否", "691123983470": "定制品", "20528142733548": "是"}'


def _setup(db):
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS lsordertest.user_rel_team ("
        " id INTEGER PRIMARY KEY, Name TEXT, user_id TEXT, En_name TEXT,"
        " Team TEXT, Camp TEXT, gmv_t INTEGER DEFAULT 0, newclient_t INTEGER DEFAULT 0)"))
    db.execute(text("DELETE FROM lsordertest.user_rel_team"))
    db.execute(text("DELETE FROM lsordertest.okki_orders"))
    db.execute(text(
        "INSERT INTO lsordertest.user_rel_team"
        " (id, Name, user_id, En_name, Team, Camp, gmv_t, newclient_t) VALUES"
        " (1,'张分配','U1','A1','队一','阵营一',0,6),"
        " (2,'李开发','U2','B2','队二','阵营三',0,7),"
        " (3,'王零单','U3','C3','队三','阵营二',0,7)"))
    for emp, attr in (("U1", "distribute"), ("U2", "develop")):
        db.add(EmployeeAttributeHistory(
            employee_id=emp, attribute_type=attr,
            effective_start=date(2025, 1, 1), is_current=True))
    db.flush()
    orders = [
        # U1 分配：C1 拆两单只计一次 + C2 一单 → 2 个新签客户
        ("O1", "C1", 1000, "U1", MARK_NEW, "2026-08-02", "公司", "13972831656", None),
        ("O2", "C1", 500, "U1", MARK_NEW, "2026-08-03", "公司", "13972831656", None),
        ("O3", "C2", 800, "U1", MARK_NEW, "2026-08-05", "公司", "13972831654", "已结清"),
        # U2 开发：1 个新签客户
        ("O4", "C3", 2000, "U2", MARK_NEW, "2026-08-10", "公司", "13972831656", None),
        # 名册外用户：不应出现在任何口径
        ("O5", "C4", 999, "UX", MARK_NEW, "2026-08-11", "公司", "13972831656", None),
        # trail 含"个人"：排除
        ("O6", "C5", 700, "U1", MARK_NEW, "2026-08-12", "个人订单", "13972831656", None),
        # 13972831654 但非"已结清"：排除
        ("O7", "C6", 600, "U1", MARK_NEW, "2026-08-13", "公司", "13972831654", "未结清"),
        # U2 复购单：不入新签，但计入 GMV（订单总额口径）
        ("O8", "C3", 3000, "U2", MARK_RE, "2026-09-05", "公司", "13972831656", None),
    ]
    for o in orders:
        db.execute(text(
            "INSERT INTO lsordertest.okki_orders (order_id, company_id, amount_usd, user_id,"
            " custom_fields, account_date, trail, status, status_name, departments)"
            " VALUES (:oid, :cid, :amt, :uid, :cf, :ad, :tr, :st, :sn, :dp)"),
            {"oid": o[0], "cid": o[1], "amt": o[2], "uid": o[3], "cf": o[4],
             "ad": o[5], "tr": o[6], "st": o[7], "sn": o[8], "dp": DEPT})


def test_new_sign_points_factor():
    """A-15：积分跟人不跟单——distribute ×1、develop ×1.5、属性缺失按分配兜底"""
    assert service.new_sign_points(4, "distribute") == 4
    assert service.new_sign_points(4, "develop") == 6.0
    assert service.new_sign_points(3, None) == 3


def test_board_distinct_roster_and_sort(db):
    _setup(db)
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {i["user_id"]: i for i in board["items"]}

    # 名册限定：UX 不入榜；零单成员也要有 0 值卡
    assert set(by) == {"U1", "U2", "U3"}
    # A-4 同一客户只计一次：C1 拆两单计 1，加 C2 共 2；个人/状态不符排除
    assert by["U1"]["new_count"] == 2
    assert by["U1"]["new_points"] == 2
    # develop ×1.5
    assert by["U2"]["new_count"] == 1
    assert by["U2"]["new_points"] == 1.5
    assert by["U3"]["new_count"] == 0
    # 排序：积分降序
    assert [i["user_id"] for i in board["items"]] == ["U1", "U2", "U3"]


def test_gmv_total_order_amount_scope(db):
    _setup(db)
    gmv = service.get_gmv_total(db, "2026-08-01", "2026-09-30")
    # A-13 订单总额：新签单 + 复购单都计入；排除 trail个人 / 状态不符 / 名册外
    assert gmv == 1000 + 500 + 800 + 2000 + 3000


def _insert_order(db, oid, cid, amt, uid, ad):
    db.execute(text(
        "INSERT INTO lsordertest.okki_orders (order_id, company_id, amount_usd, user_id,"
        " custom_fields, account_date, trail, status, status_name, departments)"
        " VALUES (:oid, :cid, :amt, :uid, :cf, :ad, '公司', '13972831656', NULL, :dp)"),
        {"oid": oid, "cid": cid, "amt": amt, "uid": uid, "cf": MARK_NEW, "ad": ad, "dp": DEPT})


def test_company_total_distinct_across_people(db):
    """A-4 公司口径：同一客户被两名业务员各报一单，个人各计、公司只计一次"""
    _setup(db)
    _insert_order(db, "O9", "C1", 400, "U2", "2026-08-15")  # C1 已在 U1 名下报过
    assert service.get_company_new_total(db, "2026-08-01", "2026-08-31") == 3  # C1/C2/C3
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {i["user_id"]: i for i in board["items"]}
    assert by["U1"]["new_count"] == 2 and by["U2"]["new_count"] == 2  # 个人口径各计


def test_window_boundary_excludes_september(db):
    """B-1：9 月新签不入 8 月榜"""
    _setup(db)
    _insert_order(db, "O10", "C9", 5000, "U1", "2026-09-01")
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {i["user_id"]: i for i in board["items"]}
    assert by["U1"]["new_count"] == 2  # 不含 9/1 的 C9


def test_sort_tiebreak_by_amount(db):
    """B-10 决胜：积分同则新签金额高者在前"""
    _setup(db)
    _insert_order(db, "O11", "C7", 3000, "U3", "2026-08-20")
    _insert_order(db, "O12", "C8", 2000, "U3", "2026-08-21")
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    order = [i["user_id"] for i in board["items"]]
    # U3 与 U1 同 2 分，U3 金额 5000 > U1 2300
    assert order[:2] == ["U3", "U1"]


def test_require_key_fail_closed(monkeypatch):
    """未配置 key 时端点整体关闭；配置后必须匹配"""
    import pytest
    from fastapi import HTTPException
    from app.festival import public_router

    class FakeSettings:
        FESTIVAL_SCREEN_KEYS = ""

    monkeypatch.setattr(public_router, "get_settings", lambda: FakeSettings)
    with pytest.raises(HTTPException):
        public_router._require_key(None)          # 未配置 → 关闭
    FakeSettings.FESTIVAL_SCREEN_KEYS = "k1, k2"
    public_router._require_key("k2")              # 配置且匹配 → 放行
    with pytest.raises(HTTPException):
        public_router._require_key("bad")         # 配置但不匹配 → 拒绝
