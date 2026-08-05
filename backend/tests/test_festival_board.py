"""采购节大屏取数 service 测试（管钱计算：资源积分 / 同客户去重 / 名册限定 / GMV 口径）"""

import json
from datetime import date, datetime

from sqlalchemy import text

from app.festival import events_service, service
from app.festival.models import FestivalEvent  # noqa: F401 —— 注册进 Base.metadata 供 conftest 建表
from app.invoice.models import Invoice  # noqa: F401 —— 主轨测试建表（同上）
from app.auth.models import ArkUserExternalBinding  # noqa: F401
from app.models.employee import EmployeeAttributeHistory

DEPT = '[{"department_id": 24925, "rate": 100}]'
DEPT_JIASHU = '[{"name": "嘉树", "department_id": 309932, "rate": 100}]'


def _new_mark(source: str) -> str:
    return json.dumps({
        "22595163468": "是",
        "691123983470": "定制品",
        "20528142733548": "",
        service.RESOURCE_SOURCE_FIELD: source,
    }, ensure_ascii=False)


MARK_NEW = _new_mark("官网询盘 (OKKI Marketing)")
MARK_NEW_DEVELOP = _new_mark("Ins开发")
MARK_RE = '{"22595163468": "否", "691123983470": "定制品", "20528142733548": "是"}'
MARK_NEW_STANDARD = json.dumps({
    "22595163468": "是",
    "691123983470": "标准品",
    "20528142733548": "",
    service.RESOURCE_SOURCE_FIELD: "官网询盘 (OKKI Marketing)",
}, ensure_ascii=False)
MARK_RE_STANDARD = '{"22595163468": "否", "691123983470": "标准品", "20528142733548": "是"}'


def _setup(db):
    db.query(FestivalEvent).delete()  # 事件表跨测试隔离（commit 不受 fixture 回滚保护）
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
        # U2 人员属性是开发，此单也确实来自 Ins 开发：1.5 分
        ("O4", "C3", 2000, "U2", MARK_NEW_DEVELOP, "2026-08-10", "公司", "13972831656", None),
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


def test_new_sign_source_points():
    """新签积分跟资源来源：公司分配 1，社媒开发/转介绍 1.5。"""
    for source in ("阿里询盘", "官网询盘 (OKKI Marketing)", "Ins分配", "展会"):
        assert service.new_sign_source_points(_new_mark(source)) == 1
    for source in ("Ins开发", "社交平台", "Facebook", "TikTok", "开发客户熟人介绍", "转介绍"):
        assert service.new_sign_source_points(_new_mark(source)) == 1.5
    assert service.new_sign_source_points(None) == 1


def test_board_distinct_roster_and_sort(db):
    _setup(db)
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {i["user_id"]: i for i in board["items"]}

    # 名册限定：UX 不入榜；零单成员也要有 0 值卡
    assert set(by) == {"U1", "U2", "U3"}
    # A-4 同一客户只计一次：C1 拆两单计 1，加 C2 共 2；个人/状态不符排除
    assert by["U1"]["new_count"] == 2
    assert by["U1"]["new_points"] == 2
    # 人员属性不参与计分；U2 因此单来自 Ins 开发才计 1.5
    assert by["U2"]["new_count"] == 1
    assert by["U2"]["new_points"] == 1.5
    assert by["U3"]["new_count"] == 0
    # 排序：积分降序
    assert [i["user_id"] for i in board["items"]] == ["U1", "U2", "U3"]


def test_non_custom_new_sign_counts_in_personal_and_company_totals(db):
    """新成交只看“是”，标准品同样计入个人榜和公司新签总数。"""
    _setup(db)
    _insert_order(db, "O-STANDARD-NEW", "C-STANDARD", 1200, "U3", "2026-08-14",
                  custom_fields=MARK_NEW_STANDARD)

    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {item["user_id"]: item for item in board["items"]}

    assert by["U3"]["new_count"] == 1
    assert by["U3"]["new_points"] == 1
    assert service.get_company_new_total(db, "2026-08-01", "2026-08-31") == 4


def test_non_custom_first_return_and_repurchase_amount_are_counted(db):
    """首返/复购只看业务标记与客户池，不再要求订单为定制品。"""
    _setup(db)
    _insert_order(db, "O-STANDARD-POOL", "C-STANDARD", 500, "U3", "2026-07-20",
                  custom_fields=MARK_NEW_STANDARD)
    _insert_order(db, "O-STANDARD-RE", "C-STANDARD", 2500, "U3", "2026-08-20",
                  custom_fields=MARK_RE_STANDARD)

    stats = service.get_repurchase_stats(db, "2026-08-01", "2026-09-30")

    assert stats["U3"]["first_count"] == 1
    assert stats["U3"]["re_amount"] == 2500


def test_board_uses_resource_source_not_person_attribute(db):
    """分配类人员的社媒开发仍计 1.5，开发类人员的公司分配仍计 1。"""
    _setup(db)
    _insert_order(db, "O-SOCIAL", "C-SOCIAL", 400, "U1", "2026-08-15",
                  custom_fields=MARK_NEW_DEVELOP)
    _insert_order(db, "O-ALLOC", "C-ALLOC", 500, "U2", "2026-08-16",
                  custom_fields=MARK_NEW)
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {i["user_id"]: i for i in board["items"]}
    assert by["U1"]["attribute"] == "distribute"
    assert by["U1"]["new_points"] == 3.5  # C1/C2 各1 + 社媒开发 1.5
    assert by["U2"]["attribute"] == "develop"
    assert by["U2"]["new_points"] == 2.5  # Ins开发 1.5 + 官网分配 1


def test_board_counts_jiashu_department_by_roster(db):
    """参赛范围以 24 人名册为准，嘉树部门不得被硬编码部门表漏掉。"""
    _setup(db)
    _insert_order(db, "O-JIASHU", "C-JIASHU", 210.23, "U3", "2026-08-01",
                  departments=DEPT_JIASHU)
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {i["user_id"]: i for i in board["items"]}
    assert by["U3"]["new_count"] == 1
    assert by["U3"]["new_points"] == 1
    assert by["U3"]["new_amount"] == 210.23


def test_same_customer_counts_once_and_uses_development_source(db):
    """同客户多单仍只计 1 个；若来源标签有变化，取最高的 1.5 分。"""
    _setup(db)
    _insert_order(db, "O-MIX-1", "C-MIX", 100, "U3", "2026-08-17",
                  custom_fields=MARK_NEW)
    _insert_order(db, "O-MIX-2", "C-MIX", 200, "U3", "2026-08-18",
                  custom_fields=MARK_NEW_DEVELOP)
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    by = {i["user_id"]: i for i in board["items"]}
    assert by["U3"]["new_count"] == 1
    assert by["U3"]["new_points"] == 1.5
    assert by["U3"]["new_amount"] == 300


def test_gmv_total_order_amount_scope(db):
    _setup(db)
    gmv = service.get_gmv_total(db, "2026-08-01", "2026-09-30")
    # A-13 订单总额：新签单 + 复购单都计入；排除 trail个人 / 状态不符 / 名册外
    assert gmv == 1000 + 500 + 800 + 2000 + 3000


def _insert_order(db, oid, cid, amt, uid, ad, *, custom_fields=MARK_NEW, departments=DEPT):
    db.execute(text(
        "INSERT INTO lsordertest.okki_orders (order_id, company_id, amount_usd, user_id,"
        " custom_fields, account_date, trail, status, status_name, departments)"
        " VALUES (:oid, :cid, :amt, :uid, :cf, :ad, '公司', '13972831656', NULL, :dp)"),
        {"oid": oid, "cid": cid, "amt": amt, "uid": uid, "cf": custom_fields,
         "ad": ad, "dp": departments})


def _add_departed_member(db):
    user_id = "57130433"
    db.execute(text(
        "INSERT INTO lsordertest.user_rel_team"
        " (id, Name, user_id, En_name, Team, Camp, gmv_t, newclient_t) VALUES"
        " (99,'隋晓茹',:uid,'Kara','星星之火','阵营一',0,6)"
    ), {"uid": user_id})
    _insert_order(db, "O-DEPARTED-NEW", "C-DEPARTED", 6000, user_id, "2026-08-01")
    _insert_order(db, "O-DEPARTED-SECOND", "C-DEPARTED-2", 5000, user_id, "2026-08-01")
    _insert_order(db, "O-DEPARTED-RE", "C-DEPARTED", 4000, user_id, "2026-09-01",
                  custom_fields=MARK_RE)
    db.flush()


def test_departed_member_excluded_from_all_okki_dashboards(db):
    """离职人员不仅不出卡，订单也不进公司/复购/阵营/团队/事件口径。"""
    _setup(db)
    _add_departed_member(db)

    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31")
    assert service.EXCLUDED_FESTIVAL_USER_IDS.isdisjoint(
        {row["user_id"] for row in board["items"]}
    )
    assert service.get_company_new_total(db, "2026-08-01", "2026-08-31") == 3
    assert service.get_gmv_total(db, "2026-08-01", "2026-09-30") == 7300
    assert "57130433" not in service.get_repurchase_stats(
        db, "2026-08-01", "2026-09-30"
    )
    assert "57130433" not in service.get_daily_orders(db, date(2026, 8, 1), source="okki")

    repurchase = service.get_repurchase_payload(db, None, None)
    assert "57130433" not in {row["user_id"] for row in repurchase["first_board"]}
    camps = service.get_camps_payload(db, None, None)
    assert "57130433" not in {
        member["user_id"] for camp in camps["camps"] for member in camp["members"]
    }
    teams = service.get_teams_payload(db, None, None)
    assert "57130433" not in {
        member["user_id"] for team in teams["teams"] for member in team["members"]
    }

    deals = events_service._deal_candidates(db, "2026-08-01", "2026-09-30")
    assert "57130433" not in {event["subject_id"] for event in deals}
    first = events_service._first_sign_candidate(db, "2026-08-01", "2026-08-31")
    assert first and first[0]["subject_id"] == "U1"


def test_departed_member_historical_events_are_invalidated_and_first_sign_rebased(db):
    """旧事件保留审计记录，但不再展示，也不能挡住当前名册的正确首单。"""
    _setup(db)
    _add_departed_member(db)
    db.add_all([
        FestivalEvent(
            event_type="first_sign", level="L4", subject_type="person",
            subject_id="57130433", subject_name="隋晓茹", dedup_key="first_sign"),
        FestivalEvent(
            event_type="team_top3", level="L3", subject_type="team",
            subject_id="星星之火", subject_name="星星之火", dedup_key="ttop3:星星之火"),
        FestivalEvent(
            event_type="big_deal", level="L3", subject_type="person",
            subject_id="U1", subject_name="甲", dedup_key="deal:kept"),
    ])
    db.flush()

    before = events_service.feed(db)
    assert [(event["event_type"], event["subject_id"]) for event in before] == [
        ("big_deal", "U1")
    ]

    current = events_service._first_sign_candidate(db, "2026-08-01", "2026-08-31")
    assert current[0]["subject_id"] == "U1"
    assert current[0]["dedup_key"] == "roster-20260804:first_sign"
    assert events_service.persist_new(db, current) == 1
    after = events_service.feed(db)
    assert any(
        event["event_type"] == "first_sign" and event["subject_id"] == "U1"
        for event in after
    )
    assert db.query(FestivalEvent).filter_by(dedup_key="first_sign").count() == 1


def test_event_feed_cursor_returns_oldest_unread_batch_without_gaps(db):
    """超过展示上限时，弹框游标必须从最老未读继续，不能只截最新 40 条。"""
    for idx in range(45):
        db.add(FestivalEvent(
            event_type="big_deal", level="L3", subject_type="person",
            subject_id="U1", subject_name="甲", dedup_key=f"cursor:{idx}",
        ))
    db.commit()

    latest = events_service.feed(db, limit=40)
    unread = events_service.feed(db, limit=40, after_id=0)

    assert [row["id"] for row in latest] == list(range(45, 5, -1))
    assert [row["id"] for row in unread] == list(range(1, 41))
    assert [row["id"] for row in events_service.feed(db, limit=40, after_id=3)][:3] == [4, 5, 6]


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
    assert service.camp_prize(800, 48, 34) == 1120    # 141%：向下取整 +40%
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
    assert camps["阵营一"]["req"] == 34
    assert payload["summary"]["new_target"] == 143
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


def test_repurchase_points_floor():
    """A-6/A-7：首返 1.5/客户 + 每满 $1000 记 1 分（按人汇总向下取整）"""
    assert service.repurchase_points(0, 0) == 0
    assert service.repurchase_points(2, 2500) == 5.0    # 3.0 + 2
    assert service.repurchase_points(1, 999) == 1.5     # 金额不足 $1000 记 0
    assert service.repurchase_points(1, 3000) == 4.5


def test_teams_weighted_scoring(db):
    """§1.5 周年加权 + 人均排序 + 个人队排除"""
    _setup(db)
    # 换成真实分队名：U1/U2 乘风，U3 无名；快照外人员按 50/50 档
    db.execute(text("UPDATE lsordertest.user_rel_team SET Team='乘风' WHERE user_id IN ('U1','U2')"))
    db.execute(text("UPDATE lsordertest.user_rel_team SET Team='无名' WHERE user_id='U3'"))
    db.flush()

    payload = service.get_teams_payload(db, None, None)  # 默认活动窗口（测试数据在 8-9 月）
    teams = {t["name"]: t for t in payload["teams"]}

    # U1：新签 2 分、无复购 → 2×0.5 = 1.0
    # U2：新签 1.5 分；O8 复购单 $3000 且带首返标记（C3 有 2026-08 新成交单，池内）
    #     → 复购积分 = 1.5 + 3 = 4.5 → 加权 1.5×0.5 + 4.5×0.5 = 3.0
    cf = teams["乘风"]
    by = {m["user_id"]: m for m in cf["members"]}
    assert by["U2"]["re_points"] == 4.5
    assert by["U2"]["score"] == 3.0
    assert by["U1"]["score"] == 1.0
    assert cf["total"] == 4.0 and cf["avg"] == 2.0 and cf["count"] == 2
    assert cf["rank"] == 1
    # 成员按加权分降序：U2 在前
    assert [m["user_id"] for m in cf["members"]] == ["U2", "U1"]
    # 空队与零分队都在榜（7 队全出），无名 avg 0
    assert teams["无名"]["avg"] == 0.0
    assert len(payload["teams"]) == 7
    assert payload["unassigned"] == 0


def test_teams_weight_snapshot_applied(db):
    """0 周年档 70/30：快照内成员的新签权重更高"""
    _setup(db)
    # 把 U1 的 user_id 换成快照里的 0 周年 id 做不进去（FK 无），改为直接断言权重函数
    assert service.member_weights("57010933") == (0.7, 0.3)   # 胡宁宁 0 周年
    assert service.member_weights("56843323") == (0.6, 0.4)   # 罗馨瑜 1 周年
    assert service.member_weights("55278725") == (0.5, 0.5)   # 代晴玉 ≥2 周年默认档


def test_repurchase_boards_sorting(db):
    """首返榜个数同看金额；金额榜金额降序；全员在榜（零值也出）"""
    _setup(db)
    # U1 也造一个首返客户（金额小于 U2 的 3000）：C2 有 8 月新成交单（池内），9 月首返 $1200
    db.execute(text(
        "INSERT INTO lsordertest.okki_orders (order_id, company_id, amount_usd, user_id,"
        " custom_fields, account_date, trail, status, status_name, departments)"
        " VALUES ('O41', 'C2', 1200, 'U1', :cf, '2026-09-10', '公司', '13972831656', NULL, :dp)"),
        {"cf": MARK_RE, "dp": DEPT})
    payload = service.get_repurchase_payload(db, None, None)
    fb = payload["first_board"]
    ab = payload["amount_board"]
    # 首返数 U1=1 U2=1 并列 → 比复购金额：U2($3000) 在前
    assert [r["user_id"] for r in fb[:2]] == ["U2", "U1"]
    assert fb[0]["first_count"] == 1 and fb[0]["re_points"] == 4.5
    # 金额榜：U2 3000 > U1 1200 > U3 0
    assert [r["user_id"] for r in ab[:3]] == ["U2", "U1", "U3"]
    assert len(fb) == 3 and len(ab) == 3  # 全员在榜


def test_headline_events_dedup_and_thresholds(db):
    """首轮建基线后，B-11 阈值事件分级正确且同一事实重跑不重复。"""
    _setup(db)
    service.get_headline_payload(db, None, None)
    _insert_order(db, "O51", "C51", 6000, "U1", "2026-08-20")    # 大单
    _insert_order(db, "O52", "C52", 35000, "U2", "2026-08-21")   # 超级大单
    payload1 = service.get_headline_payload(db, None, None)      # 真实窗口 → 落库
    types = {e["event_type"] for e in payload1["events"]}
    assert {"big_deal", "super_deal"} <= types
    assert "first_sign" not in types  # 基线前的旧首单不得在启用钉钉后补发
    # 阈值边界：$2000/$3000 的单不产生 deal 事件
    deal_amts = {e["amount"] for e in payload1["events"] if e["event_type"].endswith("deal")}
    assert deal_amts == {6000.0, 35000.0}
    # 幂等：重跑事件数不变
    payload2 = service.get_headline_payload(db, None, None)
    assert len(payload2["events"]) == len(payload1["events"])


def test_first_sign_after_empty_baseline_is_emitted(db):
    _setup(db)
    db.execute(text("DELETE FROM lsordertest.okki_orders"))
    service.get_headline_payload(db, None, None)

    _insert_order(db, "FIRST", "CFIRST", 1000, "U1", "2026-08-02")
    payload = service.get_headline_payload(db, None, None)
    first = next(e for e in payload["events"] if e["event_type"] == "first_sign")

    assert first["subject_id"] == "U1"
    assert first["level"] == "L4"


def test_first_sign_candidate_includes_non_custom_orders(db):
    """取消产品类型限制后，更早的标准品新签应成为全活动第一单。"""
    _setup(db)
    db.execute(text("DELETE FROM lsordertest.okki_orders"))
    _insert_order(db, "CUSTOM-LATER", "C-CUSTOM", 1000, "U1", "2026-08-03")
    _insert_order(db, "STANDARD-FIRST", "C-STANDARD", 1200, "U2", "2026-08-01",
                  custom_fields=MARK_NEW_STANDARD)

    candidate = events_service._first_sign_candidate(
        db, "2026-08-01", "2026-08-31")[0]

    assert candidate["subject_id"] == "U2"
    assert candidate["amount"] == 1200


def test_existing_first_sign_event_is_reconciled_without_creating_a_duplicate(db):
    """口径变化导致首单得主变化时，校正原事件而不是新增/重发。"""
    old = events_service._cand(
        "first_sign", "person", "U1", "旧得主", "first_sign",
        amount=1000, detail="全活动第一单 · 红包 ¥66")
    corrected = events_service._cand(
        "first_sign", "person", "U2", "新得主", "first_sign",
        amount=1200, detail="全活动第一单 · 红包 ¥66")

    assert events_service.persist_new(db, [old]) == 1
    sent_at = datetime(2026, 8, 1, 9, 0)
    db.query(FestivalEvent).filter_by(event_type="first_sign").one().dingtalk_sent_at = sent_at
    db.commit()
    assert events_service.persist_new(db, [corrected]) == 0
    db.expire_all()

    rows = db.query(FestivalEvent).filter_by(event_type="first_sign").all()
    assert len(rows) == 1
    assert rows[0].subject_id == "U2"
    assert rows[0].subject_name == "新得主"
    assert float(rows[0].amount) == 1200
    assert rows[0].dingtalk_sent_at == sent_at


def test_explicit_source_override_is_read_only(db):
    _setup(db)
    service.get_headline_payload(db, None, None)
    _insert_order(db, "DEBUG_BIG", "CDEBUG", 9000, "U1", "2026-08-22")

    debug_payload = service.get_headline_payload(db, None, None, source="okki")
    assert not any(e["dedup_key"] == "deal:DEBUG_BIG" for e in db.query(FestivalEvent).all())
    assert not any(e["event_type"] == "big_deal" for e in debug_payload["events"])

    service.get_headline_payload(db, None, None)
    assert any(e.dedup_key == "deal:DEBUG_BIG" for e in db.query(FestivalEvent).all())


def test_headline_preview_not_persisted(db):
    """预览窗口只出内存候选，不落库"""
    _setup(db)
    payload = service.get_headline_payload(db, "2026-08-01", "2026-08-31")
    assert payload["events"], "预览应有内存态候选"
    assert db.query(FestivalEvent).count() == 0


def _setup_ark(db):
    """主轨测试基座：绑定桥 + 发票。U1↔ark101、U2↔ark102"""
    _setup(db)
    from app.auth.models import ArkUserExternalBinding
    from app.invoice.models import Invoice
    for ark_id, okki_id in ((101, "U1"), (102, "U2")):
        db.add(ArkUserExternalBinding(
            ark_user_id=ark_id, provider="okki", external_account_id=okki_id,
            binding_status="active"))
    def inv(no, cust, user, d, total, fee=0, otype="production",
            new_deal=0, first_ret=0, sync="synced", xo=None):
        return Invoice(
            invoice_no=no, order_type=otype, customer_id=cust, customer_name=cust,
            sales_user_id=user, invoice_date=d, currency="USD",
            total_amount=total, surcharge_amount=fee,
            okki_new_deal=new_deal, okki_first_return=first_ret,
            sync_status=sync, xiaoman_order_id=xo)
    from datetime import date as D
    db.add_all([
        # U1：新签 2 客户（K1 含 $100 手续费）；K3 未推单（决策②应排除）
        inv("AK1", "K1", 101, D(2026, 8, 2), 6100, fee=100, new_deal=1, xo="XO1"),
        inv("AK2", "K2", 101, D(2026, 8, 5), 2000, new_deal=1, xo="XO2"),
        inv("AK3", "K3", 101, D(2026, 8, 6), 9000, new_deal=1, sync="not_synced"),
        # U1：库存单新签同样计入（2026-07-30 裁决：不做 order_type 过滤）
        inv("AK4", "K4", 101, D(2026, 8, 7), 500, otype="stock", new_deal=1, xo="XO4"),
        # U2：首返单（K1 池内：K1 有 8 月方舟新成交）$3200，同时是复购金额
        inv("AK5", "K1", 102, D(2026, 9, 3), 3200, new_deal=0, first_ret=1, xo="XO5"),
        # U2：池外客户 K9 复购（lsordertest 与方舟都无 2025+ 新成交）→ 金额不计
        inv("AK6", "K9", 102, D(2026, 9, 5), 8000, new_deal=0, xo="XO6"),
    ])
    # 主轨资源积分必须按 xiaoman_order_id 精确关联：
    # XO1=Ins开发 1.5，XO2=官网分配 1，XO4 暂无同步单则兜底 1。
    _insert_order(db, "XO1", "K1", 1, "U1", "2026-07-31",
                  custom_fields=MARK_NEW_DEVELOP)
    _insert_order(db, "XO2", "K2", 1, "U1", "2026-07-31",
                  custom_fields=MARK_NEW)
    # 同客户历史社媒单不能污染当前 XO2 的官网分配来源。
    _insert_order(db, "OLD-K2", "K2", 1, "U1", "2026-07-30",
                  custom_fields=MARK_NEW_DEVELOP)
    db.flush()


def test_ark_track_new_sign_synced_only_and_fee(db):
    """主轨：仅 synced（决策②）、金额扣手续费（决策①）、不做 order_type 过滤"""
    _setup_ark(db)
    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31", source="ark")
    by = {i["user_id"]: i for i in board["items"]}
    assert by["U1"]["new_count"] == 3            # K1+K2+K4（库存单也计）；K3 未推单排除
    assert by["U1"]["new_points"] == 3.5         # XO1 1.5 + XO2 1 + XO4 无来源兜底 1
    assert by["U1"]["new_amount"] == 8500.0      # 6100-100 + 2000 + 500
    assert by["U2"]["new_count"] == 0
    assert service.get_company_new_total(db, "2026-08-01", "2026-08-31", source="ark") == 3
    # GMV 全 order_type（含 K4 规格品与 9 月复购单），扣手续费、仅 synced
    gmv = service.get_gmv_total(db, "2026-08-01", "2026-09-30", source="ark")
    assert gmv == 8000 + 500 + 3200 + 8000


def test_departed_member_excluded_from_ark_dashboards(db):
    """方舟主轨通过绑定表进名册时，同样排除离职人员和其金额。"""
    _setup_ark(db)
    _add_departed_member(db)
    db.add(ArkUserExternalBinding(
        ark_user_id=103, provider="okki", external_account_id="57130433",
        binding_status="active"))
    db.add(Invoice(
        invoice_no="AK-DEPARTED", order_type="production",
        customer_id="K-DEPARTED", customer_name="K-DEPARTED",
        sales_user_id=103, invoice_date=date(2026, 8, 3), currency="USD",
        total_amount=10000, surcharge_amount=0, okki_new_deal=1,
        sync_status="synced", xiaoman_order_id="XO-DEPARTED"))
    db.flush()

    board = service.get_new_sign_board(db, "2026-08-01", "2026-08-31", source="ark")
    assert "57130433" not in {row["user_id"] for row in board["items"]}
    assert service.get_company_new_total(
        db, "2026-08-01", "2026-08-31", source="ark"
    ) == 3
    assert service.get_gmv_total(
        db, "2026-08-01", "2026-09-30", source="ark"
    ) == 19700


def test_ark_track_repurchase_pool(db):
    """主轨：首返计数 + 复购金额限 2025+ 客户池（方舟自家新成交也算池内）"""
    _setup_ark(db)
    stats = service.get_repurchase_stats(db, "2026-08-01", "2026-09-30", source="ark")
    assert stats["U2"]["first_count"] == 1       # AK5 首返
    assert stats["U2"]["re_amount"] == 3200.0    # K1 池内；K9 池外 $8000 不计


def test_reconcile_diff_rows(db):
    """双轨对账：差异行置顶并计数"""
    _setup_ark(db)
    rec = service.get_reconcile(db, None, None)
    by = {r["user_id"]: r for r in rec["rows"]}
    # okki 轨 U1 新签 2（C1/C2），ark 轨 3（K1/K2/K4，库存单也计）→ 两轨口径差可被对账捕捉
    assert by["U1"]["sign_okki"] == 2 and by["U1"]["sign_ark"] == 3
    assert by["U2"]["first_okki"] == 1 and by["U2"]["first_ark"] == 1
    # 复购金额两轨不同（okki 3000 vs ark 3200）→ 必有差异计数
    assert rec["diff_count"] >= 1
    assert rec["rows"][0]["match"] is False      # 差异行置顶


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
