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


def test_camp_prize_steps():
    """A-2：超额向下取整到 10% 整档，无封顶；未达标不加成"""
    assert service.camp_prize(2400, 59, 60) == 2400   # 未达标
    assert service.camp_prize(2400, 60, 60) == 2400   # 100% 无超额
    assert service.camp_prize(2400, 65, 60) == 2400   # 108%：不足一档
    assert service.camp_prize(2400, 66, 60) == 2640   # 110%：+10%
    assert service.camp_prize(800, 56, 40) == 1120    # 140%：+40%
    assert service.camp_prize(1200, 100, 50) == 2400  # 200%：+100%（无封顶）


def _add_camp2_pair(db, amt4, amt5):
    """增补 U4/U5（阵营二，开发类），各 1 单，金额可配"""
    db.execute(text(
        "INSERT INTO lsordertest.user_rel_team"
        " (id, Name, user_id, En_name, Team, Camp, gmv_t, newclient_t) VALUES"
        " (4,'赵四','U4','D4','队四','阵营二',0,7), (5,'钱五','U5','E5','队五','阵营二',0,7)"))
    for emp in ("U4", "U5"):
        db.add(EmployeeAttributeHistory(
            employee_id=emp, attribute_type="develop",
            effective_start=date(2025, 1, 1), is_current=True))
    db.flush()
    _insert_order(db, "O21", "C21", amt4, "U4", "2026-08-16")
    _insert_order(db, "O22", "C22", amt5, "U5", "2026-08-17")


def test_camps_payload_leader_and_aggregation(db):
    """阵营第一 = 排除全司前三后的阵营内第一且置顶；前三成员带 is_top3；聚合口径正确"""
    _setup(db)
    _add_camp2_pair(db, 9000, 100)

    payload = service.get_camps_payload(db, "2026-08-01", "2026-08-31")
    camps = {c["name"]: c for c in payload["camps"]}

    # 全司前三 = U1(2分)、U4(1.5分/$9000)、U2(1.5分/$2000)
    c2 = camps["阵营二"]
    assert [m["user_id"] for m in c2["members"] if m["is_first"]] == ["U5"]
    assert c2["members"][0]["user_id"] == "U5"                     # 阵营第一置顶
    flags = {m["user_id"]: m["is_top3"] for m in c2["members"]}
    assert flags == {"U5": False, "U4": True, "U3": False}         # 前三标识
    # 阵营一/三全员都在全司前三 → 无阵营第一标记，但有 is_top3
    assert not any(m["is_first"] for m in camps["阵营一"]["members"])
    assert camps["阵营一"]["members"][0]["is_top3"] is True
    assert not any(m["is_first"] for m in camps["阵营三"]["members"])
    # 聚合口径
    assert camps["阵营一"]["done"] == 2 and camps["阵营一"]["prize"] == 800
    assert c2["done"] == 2 and c2["reached_count"] == 0
    assert payload["unassigned"] == 0
    assert [c["name"] for c in payload["camps"]] == ["阵营一", "阵营二", "阵营三"]


def test_camps_top3_tie_expansion(db):
    """第 3/4 名 (积分,金额) 完全并列 → 同为全司前三（并列发奖），同不参与阵营第一"""
    _setup(db)
    _add_camp2_pair(db, 500, 500)
    payload = service.get_camps_payload(db, "2026-08-01", "2026-08-31")
    c2 = {c["name"]: c for c in payload["camps"]}["阵营二"]
    top3 = {m["user_id"] for m in c2["members"] if m["is_top3"]}
    assert top3 == {"U4", "U5"}
    assert not any(m["is_first"] for m in c2["members"])


def test_camps_dirty_camp_value_reconciliation(db):
    """Camp 脏值：尾随空格归位、未知值计入 unassigned 上报而非静默丢失"""
    _setup(db)
    db.execute(text(
        "INSERT INTO lsordertest.user_rel_team"
        " (id, Name, user_id, En_name, Team, Camp, gmv_t, newclient_t) VALUES"
        " (6,'孙六','U6','F6','队六','阵营一 ',0,6), (7,'周七','U7','G7','队七','阵营X',0,6)"))
    db.flush()
    payload = service.get_camps_payload(db, "2026-08-01", "2026-08-31")
    camps = {c["name"]: c for c in payload["camps"]}
    assert "U6" in [m["user_id"] for m in camps["阵营一"]["members"]]  # 空格 strip 归位
    assert payload["unassigned"] == 1                                   # 阵营X 上报不静默


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
