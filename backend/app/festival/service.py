"""采购节大屏取数服务（保底轨：lsordertest 小满同步数据）。

口径依据 docs/requirements/2026-07-24-procurement-festival-dashboard.md（v6）与
docs/requirements/2026-07-29-procurement-festival-data-layer.md：
- 新签 = 新成交"是" + 定制品，窗口内 COUNT(DISTINCT company_id)（A-4：同一客户只计一次）
- 新签积分 = 新签数 × 人员属性系数（A-15：积分跟人不跟单，distribute=1 / develop=1.5）
- okki_orders.score 列已弃用（D-3），不参与任何积分口径
- 公司 GMV = 名册内订单总额，不限订单类型（A-13：订单总额 GMV）
- 人员/阵营/个人目标唯一参数源 = lsordertest.user_rel_team

SQL 写法约束：业务表带 lsordertest. 前缀（测试态 SQLite ATTACH 同名 schema），
commission 库表不带前缀（生产默认 schema 即 commission_db）；聚合后的取整/系数
一律在 Python 层做（SQLite 无 FLOOR，且计算逻辑要可单测）。
"""

from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

# 活动常量（规则文档 §1.1）
ACTIVITY_NEW_SIGN_WINDOW = ("2026-08-01", "2026-08-31")   # 新签窗口（B-1：只统计 8 月）
ACTIVITY_GMV_WINDOW = ("2026-08-01", "2026-09-30")        # GMV / 复购窗口
COMPANY_NEW_SIGN_TARGET = 149
COMPANY_GMV_TARGET = 3_260_000  # 326 万美金

# 新成交 + 定制品：两字段在 custom_fields 序列化中确实相邻（data-layer 文档 §3 实测），
# 首返字段不相邻，未来做首返榜时必须拆成两个独立 LIKE。
NEW_SIGN_MARK = '%"22595163468": "是", "691123983470": "定制品"%'

_DEPT_IDS = ("24925", "24926", "25198", "258938", "258940", "258941", "258942")

# 属性快照（附录 B，2026-07-29 查库核实、用户裁决"全程固定"——A-1 关闭结论）：
# 计分一律以本快照为准；employee_attribute_history 仅作快照外人员的兜底。
# 活动期内 DB 属性变更不得影响积分（这张历史表本就是会变的）。
ATTR_SNAPSHOT_2026 = {
    # 开发类（×1.5）：刘行行 代晴玉 毕晓珍 张笑 李宝珠 周露露 尹德魁 夏新月
    "56506160": "develop", "55278725": "develop", "55278718": "develop",
    "56646975": "develop", "55369626": "develop", "55951723": "develop",
    "56046345": "develop", "55278716": "develop",
    # 分配类（×1）：隋晓茹 刘也 宋化通 张心茹 田雯 翟佳盟 张砚斐 潘康衡
    #             胡宁宁 刘源 刘琳琳 罗馨瑜 宋皓月 高瑞杰 曲冉 凯丽
    "57130433": "distribute", "57125949": "distribute", "55303520": "distribute",
    "57180994": "distribute", "55531178": "distribute", "55411216": "distribute",
    "56158751": "distribute", "55296478": "distribute", "57010933": "distribute",
    "55497300": "distribute", "55278720": "distribute", "56843323": "distribute",
    "55298611": "distribute", "56786146": "distribute", "56653054": "distribute",
    "57130855": "distribute",
}


def _common_filter(a: str) -> str:
    """公共过滤：排除私人订单 + 状态限定 + 销售部门范围（用户提供的保底 SQL 口径）。

    department_id 匹配补右界（`,` 或 `}`），防未来出现 249250 这类前缀撞号 id。
    """
    parts = []
    for d in _DEPT_IDS:
        parts.append(f"{a}.departments LIKE '%\"department_id\": {d},%'")
        parts.append(f"{a}.departments LIKE '%\"department_id\": {d}}}%'")
    depts = " OR ".join(parts)
    return (
        f" AND {a}.trail NOT LIKE '%个人%'"
        f" AND ({a}.status = '13972831656'"
        f"      OR ({a}.status = '13972831654' AND {a}.status_name = '已结清'))"
        f" AND ({depts})"
    )


def new_sign_points(count: int, attribute: str | None) -> float:
    """新签积分 = 新签数 × 属性系数（A-15）。属性缺失按分配类（×1）兜底。"""
    factor = 1.5 if attribute == "develop" else 1.0
    return count * factor


def get_new_sign_board(db: Session, date_from: str, date_to: str) -> dict:
    """个人新签积分榜：24 人全员（无单也出 0 值卡），按积分降序、新签金额决胜（B-10）。"""
    roster = db.execute(text(
        "SELECT user_id, Name AS name, En_name AS en_name, Team AS team, Camp AS camp,"
        "       newclient_t AS target "
        "FROM lsordertest.user_rel_team ORDER BY id"
    )).mappings().all()

    attrs = {
        r["employee_id"]: r["attribute_type"]
        for r in db.execute(text(
            "SELECT employee_id, attribute_type FROM employee_attribute_history "
            "WHERE is_current = 1"
        )).mappings()
    }

    rows = db.execute(text(
        "SELECT a2.user_id, COUNT(DISTINCT a2.company_id) AS cnt,"
        "       COALESCE(SUM(a2.amount_usd), 0) AS amt "
        "FROM lsordertest.okki_orders a2 "
        "WHERE a2.custom_fields LIKE :mark "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + _common_filter("a2") +
        " GROUP BY a2.user_id"
    ), {"mark": NEW_SIGN_MARK, "d1": date_from, "d2": date_to}).mappings().all()
    stats = {r["user_id"]: r for r in rows}

    items = []
    for m in roster:
        stat = stats.get(m["user_id"])
        cnt = int(stat["cnt"]) if stat else 0
        amount = float(stat["amt"]) if stat else 0.0
        attribute = ATTR_SNAPSHOT_2026.get(m["user_id"]) or attrs.get(m["user_id"])
        items.append({
            "user_id": m["user_id"],
            "name": m["name"],
            "en_name": m["en_name"],
            "team": m["team"],
            "camp": m["camp"],
            "attribute": attribute or "distribute",
            "target": int(m["target"] or 0),
            "new_count": cnt,
            "new_points": new_sign_points(cnt, attribute),
            "new_amount": round(amount, 2),
            "reached": cnt >= int(m["target"] or 0) > 0,
        })
    # 排序：积分降序 → 新签金额降序（B-10 决胜口径）→ 姓名稳定兜底
    items.sort(key=lambda x: (-x["new_points"], -x["new_amount"], x["name"]))
    return {"items": items}


def get_company_new_total(db: Session, date_from: str, date_to: str) -> int:
    """公司 149 进度：全局 COUNT(DISTINCT company_id)——A-4"同一客户只计一次"
    在公司口径同样成立（同一客户被两名业务员各报一单时，个人各计、公司只计一次）。"""
    roster_ids = [r[0] for r in db.execute(text(
        "SELECT user_id FROM lsordertest.user_rel_team"
    )).fetchall()]
    if not roster_ids:
        return 0
    stmt = text(
        "SELECT COUNT(DISTINCT a2.company_id) FROM lsordertest.okki_orders a2 "
        "WHERE a2.user_id IN :ids AND a2.custom_fields LIKE :mark "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + _common_filter("a2")
    ).bindparams(bindparam("ids", expanding=True))
    val = db.execute(stmt, {"ids": roster_ids, "mark": NEW_SIGN_MARK,
                            "d1": date_from, "d2": date_to}).scalar()
    return int(val or 0)


def get_gmv_total(db: Session, date_from: str, date_to: str) -> float:
    """公司业绩进度：名册内订单总额（A-13 GMV 口径，不限订单类型）。"""
    roster_ids = [r[0] for r in db.execute(text(
        "SELECT user_id FROM lsordertest.user_rel_team"
    )).fetchall()]
    if not roster_ids:
        return 0.0
    stmt = text(
        "SELECT COALESCE(SUM(a2.amount_usd), 0) FROM lsordertest.okki_orders a2 "
        "WHERE a2.user_id IN :ids "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + _common_filter("a2")
    ).bindparams(bindparam("ids", expanding=True))
    val = db.execute(stmt, {"ids": roster_ids, "d1": date_from, "d2": date_to}).scalar()
    return round(float(val or 0), 2)


def get_screen_payload(db: Session, date_from: str | None, date_to: str | None) -> dict:
    """大屏一次取全：榜单 + 双目标进度。自定义窗口（预览用）时 GMV 同窗。"""
    custom = bool(date_from and date_to)
    ns_from, ns_to = (date_from, date_to) if custom else ACTIVITY_NEW_SIGN_WINDOW
    gmv_from, gmv_to = (date_from, date_to) if custom else ACTIVITY_GMV_WINDOW

    board = get_new_sign_board(db, ns_from, ns_to)
    return {
        "summary": {
            "new_total": get_company_new_total(db, ns_from, ns_to),
            "new_target": COMPANY_NEW_SIGN_TARGET,
            "gmv_total": get_gmv_total(db, gmv_from, gmv_to),
            "gmv_target": COMPANY_GMV_TARGET,
            "window": {"from": ns_from, "to": ns_to, "preview": custom},
        },
        "items": board["items"],
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
