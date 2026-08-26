"""采购节大屏取数服务（保底轨：lsordertest 小满同步数据）。

口径依据 docs/requirements/2026-07-24-procurement-festival-dashboard.md（v6）与
docs/requirements/2026-07-29-procurement-festival-data-layer.md：
- 新签 = 新成交"是"，不限产品类型，窗口内 COUNT(DISTINCT company_id)（A-4：同一客户只计一次）
- 新签积分按客户资源来源计：公司分配资源=1，社媒开发/转介绍=1.5
- okki_orders.score 列已弃用（D-3），不参与任何积分口径
- 公司 GMV = 名册内订单总额，不限订单类型（A-13：订单总额 GMV）
- 人员/阵营/个人目标唯一参数源 = lsordertest.user_rel_team

SQL 写法约束：业务表带 lsordertest. 前缀（测试态 SQLite ATTACH 同名 schema），
commission 库表不带前缀（生产默认 schema 即 commission_db）；聚合后的取整/系数
一律在 Python 层做（SQLite 无 FLOOR，且计算逻辑要可单测）。
"""

import json
import logging
from datetime import date, datetime
from app.core.time import beijing_today
from app.core.time import beijing_now

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _data_source(source: str | None = None) -> str:
    """取数轨道：okki（保底轨，默认）/ ark（主轨，方舟发票域）。?source= 可临时覆盖调试。"""
    s = (source or get_settings().FESTIVAL_DATA_SOURCE or "okki").lower()
    return s if s in ("okki", "ark") else "okki"


# 活动期离职人员仍保留在业务库历史表中，但必须从所有采购节口径统一排除。
# 不改 lsordertest（只读业务库），也不靠前端隐藏，避免公司总数/团队/阵营/事件仍计入。
EXCLUDED_FESTIVAL_USER_IDS = frozenset({"57130433"})  # 隋晓茹，2026-08-04 确认离职


def _active_roster_filter(alias: str = "t") -> str:
    ids = ", ".join(f"'{user_id}'" for user_id in sorted(EXCLUDED_FESTIVAL_USER_IDS))
    return f" AND {alias}.user_id NOT IN ({ids})" if ids else ""


# ── 主轨（commission_db.ark_invoices）公共件 ─────────────────────
# 统计范围（2026-07-30 决策②）：仅 sync_status='synced'（已推 OKKI 的发票）
# 金额口径（决策①）：总金额扣手续费（surcharge_amount 附加费/Paypal Surcharge）
_ARK_AMOUNT = "(i.total_amount - COALESCE(i.surcharge_amount, 0))"
_ARK_JOIN = (
    " FROM ark_invoices i"
    " JOIN ark_user_external_bindings b ON b.ark_user_id = i.sales_user_id"
    "   AND b.provider = 'okki' AND b.binding_status = 'active' AND b.deleted_at IS NULL"
    " JOIN lsordertest.user_rel_team t ON t.user_id = b.external_account_id"
    + _active_roster_filter("t") +
    " WHERE i.sync_status = 'synced'"
)
# 复购客户池（2025+ 新签）：老客历史看 lsordertest，方舟时代新客看自家发票，双通道 OR 自洽
_ARK_POOL = (
    "  AND ( EXISTS (SELECT 1 FROM lsordertest.okki_orders o"
    "               WHERE o.company_id = i.customer_id"
    "                 AND o.custom_fields LIKE :mn AND o.account_date >= '2025-01-01')"
    "     OR EXISTS (SELECT 1 FROM ark_invoices o2"
    "               WHERE o2.customer_id = i.customer_id AND o2.okki_new_deal = 1"
    "                 AND o2.sync_status = 'synced' AND o2.invoice_date >= '2025-01-01') )"
)

# 活动常量（规则文档 §1.1）
ACTIVITY_NEW_SIGN_WINDOW = ("2026-08-01", "2026-08-31")   # 新签窗口（B-1：只统计 8 月）
ACTIVITY_GMV_WINDOW = ("2026-08-01", "2026-09-30")        # GMV / 复购窗口
COMPANY_NEW_SIGN_TARGET = 143
COMPANY_GMV_TARGET = 3_260_000  # 326 万美金

# 新成交、复购和首返仅使用各自业务字段，不再按产品类型过滤（2026-08-05 调整）。
NEW_SIGN_MARK = '%"22595163468": "是"%'
RE_MARK = '%"22595163468": "否"%'
FIRST_RETURN_MARK = '%"20528142733548": "是"%'
NEW_ANY_MARK = NEW_SIGN_MARK

RESOURCE_SOURCE_FIELD = "45285192666116"
# 资源来源是多选字段；命中任一开发/转介绍标签即按 1.5 分。
# 其余值（阿里询盘、官网、Ins分配、展会等）统一按公司分配资源 1 分。
DEVELOPMENT_SOURCE_MARKS = (
    "ins开发", "社媒开发", "社交平台", "facebook", "tiktok", "熟人介绍", "转介绍",
)

# 属性快照（附录 B，2026-07-29 查库核实、用户裁决"全程固定"——A-1 关闭结论）：
# 2026-08-04 起不参与新签积分，仅供个人目标/阵营门槛等规则展示与判定。
# employee_attribute_history 仅作快照外人员的兜底。
ATTR_SNAPSHOT_2026 = {
    # 开发类（×1.5）：刘行行 代晴玉 毕晓珍 张笑 李宝珠 周露露 尹德魁 夏新月
    "56506160": "develop", "55278725": "develop", "55278718": "develop",
    "56646975": "develop", "55369626": "develop", "55951723": "develop",
    "56046345": "develop", "55278716": "develop",
    # 分配类（×1）：刘也 宋化通 张心茹 田雯 翟佳盟 张砚斐 潘康衡
    #             胡宁宁 刘源 刘琳琳 罗馨瑜 宋皓月 高瑞杰 曲冉 凯丽
    "57125949": "distribute", "55303520": "distribute", "57180994": "distribute",
    "55531178": "distribute", "55411216": "distribute",
    "56158751": "distribute", "55296478": "distribute", "57010933": "distribute",
    "55497300": "distribute", "55278720": "distribute", "56843323": "distribute",
    "55298611": "distribute", "56786146": "distribute", "56653054": "distribute",
    "57130855": "distribute",
}


def _common_filter(a: str) -> str:
    """公共过滤：排除私人订单 + 状态限定。

    参赛范围由 user_rel_team 名册扣除离职排除表后限定，不再用历史部门 ID 二次过滤，
    避免嘉树等新部门或活动期调部门造成合法参赛人员漏算。
    """
    return (
        f" AND {a}.trail NOT LIKE '%个人%'"
        f" AND ({a}.status = '13972831656'"
        f"      OR ({a}.status = '13972831654' AND {a}.status_name = '已结清'))"
    )


def new_sign_source_points(custom_fields: str | None) -> float:
    """单个新签客户的积分：社媒开发/转介绍 1.5，其余来源 1。"""
    raw = custom_fields or ""
    try:
        source = str(json.loads(raw).get(RESOURCE_SOURCE_FIELD) or "")
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        # 历史同步数据偶有非法 JSON，仅在明确命中开发标签时计 1.5。
        source = raw
    normalized = source.casefold()
    return 1.5 if any(mark in normalized for mark in DEVELOPMENT_SOURCE_MARKS) else 1.0


def _aggregate_new_sign_rows(rows) -> dict[str, dict]:
    """按人聚合新签：同客户只计 1 个，多条来源时取该客户最高分值。"""
    stats: dict[str, dict] = {}
    customer_points: dict[tuple[str, str], float] = {}
    for row in rows:
        user_id = str(row["user_id"])
        customer_id = str(row["customer_id"])
        stat = stats.setdefault(user_id, {"cnt": 0, "points": 0.0, "amt": 0.0})
        stat["amt"] += float(row["amt"] or 0)
        key = (user_id, customer_id)
        points = float(row.get("source_points") or new_sign_source_points(row.get("custom_fields")))
        customer_points[key] = max(customer_points.get(key, 0.0), points)
    for (user_id, _customer_id), points in customer_points.items():
        stats[user_id]["cnt"] += 1
        stats[user_id]["points"] += points
    return stats


def _ark_invoice_source_points(db: Session, order_ids: list[str]) -> dict[str, float]:
    """方舟主轨按发票精确关联的小满订单补齐资源积分。"""
    if not order_ids:
        return {}
    stmt = text(
        "SELECT order_id, custom_fields FROM lsordertest.okki_orders "
        "WHERE order_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    return {
        str(row["order_id"]): new_sign_source_points(row["custom_fields"])
        for row in db.execute(stmt, {"ids": order_ids}).mappings()
    }


def get_new_sign_board(db: Session, date_from: str, date_to: str,
                       source: str | None = None) -> dict:
    """个人新签积分榜：在职参赛人员全员展示，按积分降序、新签金额决胜（B-10）。"""
    roster = db.execute(text(
        "SELECT user_id, Name AS name, En_name AS en_name, Team AS team, Camp AS camp,"
        "       newclient_t AS target "
        "FROM lsordertest.user_rel_team t WHERE 1=1"
        + _active_roster_filter("t") + " ORDER BY id"
    )).mappings().all()

    attrs = {
        r["employee_id"]: r["attribute_type"]
        for r in db.execute(text(
            "SELECT employee_id, attribute_type FROM employee_attribute_history "
            "WHERE is_current = 1"
        )).mappings()
    }

    if _data_source(source) == "ark":
        # 不做 order_type 过滤：主轨与保底轨均以新成交业务标记为准、全量订单计入。
        rows = db.execute(text(
            "SELECT t.user_id, i.customer_id, i.xiaoman_order_id,"
            f"       {_ARK_AMOUNT} AS amt"
            + _ARK_JOIN +
            "   AND i.okki_new_deal = 1"
            "   AND i.invoice_date >= :d1 AND i.invoice_date <= :d2"
        ), {"d1": date_from, "d2": date_to}).mappings().all()
        source_points = _ark_invoice_source_points(
            db, list({str(row["xiaoman_order_id"]) for row in rows if row["xiaoman_order_id"]})
        )
        rows = [
            {
                **dict(row),
                "source_points": source_points.get(str(row["xiaoman_order_id"]), 1.0),
            }
            for row in rows
        ]
    else:
        rows = db.execute(text(
            "SELECT a2.user_id, a2.company_id AS customer_id,"
            "       a2.amount_usd AS amt, a2.custom_fields "
            "FROM lsordertest.okki_orders a2 "
            "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
            + _active_roster_filter("t") +
            "WHERE a2.custom_fields LIKE :mark "
            "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
            + _common_filter("a2")
        ), {"mark": NEW_SIGN_MARK, "d1": date_from, "d2": date_to}).mappings().all()
    stats = _aggregate_new_sign_rows(rows)

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
            "new_points": round(float(stat["points"]), 1) if stat else 0.0,
            "new_amount": round(amount, 2),
            "reached": cnt >= int(m["target"] or 0) > 0,
        })
    # 排序：积分降序 → 新签金额降序（B-10 决胜口径）→ 姓名稳定兜底
    items.sort(key=lambda x: (-x["new_points"], -x["new_amount"], x["name"]))
    return {"items": items}


def get_company_new_total(db: Session, date_from: str, date_to: str,
                          source: str | None = None) -> int:
    """公司 143 进度：全局 COUNT(DISTINCT company_id)——A-4"同一客户只计一次"
    在公司口径同样成立（同一客户被两名业务员各报一单时，个人各计、公司只计一次）。"""
    if _data_source(source) == "ark":
        val = db.execute(text(
            "SELECT COUNT(DISTINCT i.customer_id)"
            + _ARK_JOIN +
            "   AND i.okki_new_deal = 1"
            "   AND i.invoice_date >= :d1 AND i.invoice_date <= :d2"
        ), {"d1": date_from, "d2": date_to}).scalar()
        return int(val or 0)
    roster_ids = [r[0] for r in db.execute(text(
        "SELECT t.user_id FROM lsordertest.user_rel_team t WHERE 1=1"
        + _active_roster_filter("t")
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


def get_gmv_total(db: Session, date_from: str, date_to: str,
                  source: str | None = None) -> float:
    """公司业绩进度：名册内订单总额（A-13 GMV 口径，不限订单类型；主轨扣手续费）。"""
    if _data_source(source) == "ark":
        val = db.execute(text(
            f"SELECT COALESCE(SUM({_ARK_AMOUNT}), 0)"
            + _ARK_JOIN +
            "   AND i.invoice_date >= :d1 AND i.invoice_date <= :d2"
        ), {"d1": date_from, "d2": date_to}).scalar()
        return round(float(val or 0), 2)
    roster_ids = [r[0] for r in db.execute(text(
        "SELECT t.user_id FROM lsordertest.user_rel_team t WHERE 1=1"
        + _active_roster_filter("t")
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


def get_daily_orders(db: Session, target_date: date, source: str | None = None) -> dict:
    """返回名册内当天有效订单，供连击事件建立稳定订单序列。

    方舟一笔 OKKI 订单可能拆成多张发票，主轨按 xiaoman_order_id（无值时 invoice_no）
    聚合，避免把拆票误判成连击。
    """
    day = target_date.isoformat()
    if not (ACTIVITY_GMV_WINDOW[0] <= day <= ACTIVITY_GMV_WINDOW[1]):
        return {}
    if _data_source(source) == "ark":
        rows = db.execute(text(
            "SELECT COALESCE(i.xiaoman_order_id, i.invoice_no) AS order_id,"
            f"       SUM({_ARK_AMOUNT}) AS amount, t.user_id AS user_id, t.Name AS name,"
            "       MIN(i.id) AS sort_key"
            + _ARK_JOIN +
            "   AND i.invoice_date = :day"
            " GROUP BY COALESCE(i.xiaoman_order_id, i.invoice_no), t.user_id, t.Name"
            " ORDER BY sort_key, order_id"
        ), {"day": day}).mappings().all()
    else:
        rows = db.execute(text(
            "SELECT a2.order_id, a2.amount_usd AS amount, a2.user_id, t.Name AS name "
            "FROM lsordertest.okki_orders a2 "
            "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
            + _active_roster_filter("t") +
            "WHERE a2.account_date = :day"
            + _common_filter("a2") +
            " ORDER BY a2.order_id"
        ), {"day": day}).mappings().all()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(str(row["user_id"]), []).append({
            "order_id": str(row["order_id"]),
            "amount": float(row["amount"] or 0),
            "name": str(row["name"]),
        })
    return grouped


def _windows(date_from: str | None, date_to: str | None):
    """自定义窗口（预览用）时新签/GMV 同窗；否则用活动固定窗口。"""
    custom = bool(date_from and date_to)
    ns = (date_from, date_to) if custom else ACTIVITY_NEW_SIGN_WINDOW
    gmv = (date_from, date_to) if custom else ACTIVITY_GMV_WINDOW
    return ns, gmv, custom


def _summary(db: Session, ns, gmv, preview: bool, source: str | None = None) -> dict:
    return {
        "new_total": get_company_new_total(db, ns[0], ns[1], source=source),
        "new_target": COMPANY_NEW_SIGN_TARGET,
        "gmv_total": get_gmv_total(db, gmv[0], gmv[1], source=source),
        "gmv_target": COMPANY_GMV_TARGET,
        "source": _data_source(source),
        "window": {"from": ns[0], "to": ns[1], "preview": preview},
    }


def get_repurchase_stats(db: Session, date_from: str, date_to: str,
                         source: str | None = None) -> dict:
    """每人复购口径：首返客户数（A-5 有史以来第一次返单，标记源自 OKKI 首返字段；
    拆分 LIKE）+ 复购金额（限 2025-01-01 起有新成交单的客户池，A-6/A-10 口径）。"""
    stats: dict = {}
    if _data_source(source) == "ark":
        first_rows = db.execute(text(
            "SELECT t.user_id, COUNT(DISTINCT i.customer_id) AS cnt"
            + _ARK_JOIN +
            "   AND i.okki_first_return = 1"
            "   AND i.invoice_date >= :d1 AND i.invoice_date <= :d2"
            " GROUP BY t.user_id"
        ), {"d1": date_from, "d2": date_to}).mappings().all()
        for r in first_rows:
            stats.setdefault(r["user_id"], {"first_count": 0, "re_amount": 0.0})
            stats[r["user_id"]]["first_count"] = int(r["cnt"])
        re_rows = db.execute(text(
            f"SELECT t.user_id, COALESCE(SUM({_ARK_AMOUNT}), 0) AS amt"
            + _ARK_JOIN +
            "   AND i.okki_new_deal = 0"
            "   AND i.invoice_date >= :d1 AND i.invoice_date <= :d2"
            + _ARK_POOL +
            " GROUP BY t.user_id"
        ), {"mn": NEW_ANY_MARK, "d1": date_from, "d2": date_to}).mappings().all()
        for r in re_rows:
            stats.setdefault(r["user_id"], {"first_count": 0, "re_amount": 0.0})
            stats[r["user_id"]]["re_amount"] = float(r["amt"])
        return stats
    first_rows = db.execute(text(
        "SELECT a2.user_id, COUNT(DISTINCT a2.company_id) AS cnt "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
        + _active_roster_filter("t") +
        "WHERE a2.custom_fields LIKE :m1 "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + _common_filter("a2") + " GROUP BY a2.user_id"
    ), {"m1": FIRST_RETURN_MARK,
        "d1": date_from, "d2": date_to}).mappings().all()
    for r in first_rows:
        stats.setdefault(r["user_id"], {"first_count": 0, "re_amount": 0.0})
        stats[r["user_id"]]["first_count"] = int(r["cnt"])
    re_rows = db.execute(text(
        "SELECT a2.user_id, COALESCE(SUM(a2.amount_usd), 0) AS amt "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
        + _active_roster_filter("t") +
        "WHERE a2.custom_fields LIKE :mr "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + _common_filter("a2") +
        "  AND EXISTS (SELECT 1 FROM lsordertest.okki_orders o"
        "              WHERE o.company_id = a2.company_id"
        "                AND o.custom_fields LIKE :mn"
        "                AND o.account_date >= '2025-01-01')"
        " GROUP BY a2.user_id"
    ), {"mr": RE_MARK, "mn": NEW_ANY_MARK,
        "d1": date_from, "d2": date_to}).mappings().all()
    for r in re_rows:
        stats.setdefault(r["user_id"], {"first_count": 0, "re_amount": 0.0})
        stats[r["user_id"]]["re_amount"] = float(r["amt"])
    return stats


def repurchase_points(first_count: int, re_amount: float) -> float:
    """复购积分 = 首返 1.5 分/客户 + 每满 $1000 记 1 分（按人汇总向下取整，A-6/A-7 叠加口径）"""
    return first_count * 1.5 + int(re_amount // 1000)


def get_headline_payload(db: Session, date_from: str | None, date_to: str | None,
                         source: str | None = None) -> dict:
    """摘要头条屏一次取全：左屏排名汇总 + 右屏事件滚动流。

    事件检测在此入口顺带执行（真实窗口幂等落库；预览窗口只出内存候选不落库）。
    """
    from app.festival import events_service

    ns, gmv, custom = _windows(date_from, date_to)
    persist_events = not custom and source is None
    if persist_events:
        # 必须在任何业务快照查询前拿锁；否则等待锁期间已建立的旧事务快照会覆盖新状态。
        events_service.acquire_detector_lock(db)
    # 快照复用：board / 复购统计 / summary 各算一次，四个子 payload 共用（防冗余全表扫）
    items = get_new_sign_board(db, ns[0], ns[1], source=source)["items"]
    re_stats = get_repurchase_stats(db, gmv[0], gmv[1], source=source)
    summary = _summary(db, ns, gmv, custom, source=source)
    camps_payload = get_camps_payload(db, date_from, date_to, items=items, summary=summary)
    teams_payload = get_teams_payload(db, date_from, date_to,
                                      items=items, re_stats=re_stats, summary=summary)
    rep = get_repurchase_payload(db, date_from, date_to, re_stats=re_stats, summary=summary)

    sign_top3 = [
        {"user_id": i["user_id"], "name": i["name"],
         "new_count": i["new_count"], "new_points": i["new_points"]}
        for i in items[:3] if i["new_points"] > 0
    ]
    camps_mini = [
        {"name": c["name"], "pct": c["pct"], "done": c["done"], "req": c["req"],
         "prize": c["prize"],
         "first": next((m["name"] for m in c["members"] if m["is_first"]), None)}
        for c in camps_payload["camps"]
    ]
    teams_top3 = [
        {"name": t["name"], "avg": t["avg"], "rank": t["rank"], "count": t["count"]}
        for t in teams_payload["teams"][:3]
    ]

    if custom:
        candidates = events_service.detect_candidates(
            db, ns, gmv, items, camps_payload["camps"], teams_payload["teams"],
            rep["first_board"], rep["amount_board"], source=source)
        candidates += events_service._new_sign_order_candidates(
            db, ns[0], ns[1], source=source)
        # 预览窗口：内存候选倒序模拟事件流，不落库（无真实时间戳，占位显示）
        events = [{**c, "id": idx + 1, "created_at": "预览"}
                  for idx, c in enumerate(reversed(candidates))]
        events.reverse()
    elif persist_events:
        state_scope = _data_source(None)
        candidates = events_service.detect_candidates(
            db, ns, gmv, items, camps_payload["camps"], teams_payload["teams"],
            rep["first_board"], rep["amount_board"], source=None)
        candidates = events_service.filter_stateless_baseline(db, candidates, state_scope)
        new_sign_candidates = events_service._new_sign_order_candidates(
            db, ns[0], ns[1], source=None)
        candidates += events_service.filter_new_sign_order_baseline(
            db, new_sign_candidates, state_scope)
        candidates += events_service.detect_stateful_candidates(
            db,
            summary=summary,
            items=items,
            camps=camps_payload["camps"],
            teams=teams_payload["teams"],
            first_board=rep["first_board"],
            amount_board=rep["amount_board"],
            daily_orders=get_daily_orders(db, beijing_today(), source=None),
            state_scope=state_scope,
        )
        events_service.persist_new(db, candidates)
        db.commit()  # 首次仅建立状态基线、无候选事件时也必须持久化
        events = events_service.feed(db)
    else:
        # ?source= 调试只读，禁止污染正式轨的排名/里程碑/连击基线。
        events = events_service.feed(db)

    return {
        "summary": summary,
        "sign_top3": sign_top3,
        "first_top2": [r for r in rep["first_board"][:2] if r["first_count"] > 0],
        "amount_top2": [r for r in rep["amount_board"][:2] if r["re_amount"] > 0],
        "camps": camps_mini,
        "teams_top3": teams_top3,
        "events": events,
        "as_of": beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_reconcile(db: Session, date_from: str | None, date_to: str | None) -> dict:
    """双轨对账（§6.3）：okki vs ark 按人输出新签数/首返数/复购金额三列 diff。
    差异只有两种来源：没走方舟录入的单、未推单（synced 前）的滞后。"""
    ns, gmv, _ = _windows(date_from, date_to)
    per_track: dict = {}
    for src in ("okki", "ark"):
        board = {i["user_id"]: i for i in get_new_sign_board(db, ns[0], ns[1], source=src)["items"]}
        re_stats = get_repurchase_stats(db, gmv[0], gmv[1], source=src)
        per_track[src] = (board, re_stats)

    rows = []
    diff_count = 0
    for uid, base in per_track["okki"][0].items():
        ark_item = per_track["ark"][0].get(uid, {})
        re_o = per_track["okki"][1].get(uid, {"first_count": 0, "re_amount": 0.0})
        re_a = per_track["ark"][1].get(uid, {"first_count": 0, "re_amount": 0.0})
        row = {
            "user_id": uid,
            "name": base["name"],
            "sign_okki": base["new_count"], "sign_ark": ark_item.get("new_count", 0),
            "first_okki": re_o["first_count"], "first_ark": re_a["first_count"],
            "re_okki": round(re_o["re_amount"], 2), "re_ark": round(re_a["re_amount"], 2),
        }
        row["match"] = (row["sign_okki"] == row["sign_ark"]
                        and row["first_okki"] == row["first_ark"]
                        and abs(row["re_okki"] - row["re_ark"]) < 0.01)
        if not row["match"]:
            diff_count += 1
        rows.append(row)
    rows.sort(key=lambda r: (r["match"], r["name"]))  # 差异行置顶
    return {
        "window": {"sign": list(ns), "repurchase": list(gmv)},
        "rows": rows,
        "diff_count": diff_count,
        "verdict": "两轨一致，可切 ark" if diff_count == 0 else f"{diff_count} 人存在差异",
        "as_of": beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_ai_tip(db: Session, headline: dict) -> dict:
    """AI 赛事助手：基于当前排名/进度产出正向鼓励与预测（预设缺失/失败时规则兜底）。"""
    s = headline["summary"]
    lines = [
        f"公司进度：8月新签 {s['new_total']}/{s['new_target']} 个，"
        f"8+9月GMV ${s['gmv_total']:,.0f}/${s['gmv_target']:,.0f}。",
    ]
    if headline["sign_top3"]:
        lines.append("新签前三：" + "、".join(
            f"{i['name']}{i['new_points']:g}分" for i in headline["sign_top3"]))
    if headline["first_top2"]:
        lines.append("首返前二：" + "、".join(
            f"{r['name']}{r['first_count']}个" for r in headline["first_top2"]))
    if headline["amount_top2"]:
        lines.append("复购金额前二：" + "、".join(
            f"{r['name']}${r['re_amount']:,.0f}" for r in headline["amount_top2"]))
    lines.append("阵营进度：" + "、".join(
        f"{c['name']}{c['pct']}%" for c in headline["camps"]))
    if headline["teams_top3"]:
        lines.append("团队人均前三：" + "、".join(
            f"{t['name']}{t['avg']:.1f}分" for t in headline["teams_top3"]))
    status_text = "\n".join(lines)

    try:
        from app.ai.service import chat
        result = chat(
            db,
            preset_name="festival_screen_tip",
            messages=[{
                "role": "user",
                "content": (
                    "你是采购节大屏的 AI 赛事助手。以下是当前实时战况，请输出一句 40~70 字的"
                    "正向鼓励播报（可含预测或看点提示），面向全体销售，禁止批评任何个人或团队，"
                    "不要重复罗列数字，语气热烈专业：\n" + status_text
                ),
            }],
            caller_module="festival",
        )
        tip = (result.get("content") or "").strip()
        if tip:
            return {"tip": tip, "source": "ai"}
    except Exception as exc:  # 预设未配置/调用失败 → 规则兜底，屏上永不空窗
        logger.warning("[festival] AI 提示生成失败，走兜底: %s", exc)
        print(f"[festival] AI 提示生成失败，走兜底: {exc}", flush=True)

    pct = round(s["new_total"] / s["new_target"] * 100) if s["new_target"] else 0
    leader = headline["sign_top3"][0]["name"] if headline["sign_top3"] else None
    tip = (f"{s['new_target']} 个新签目标已完成 {pct}%，"
           + (f"{leader} 暂列新签榜首，" if leader else "")
           + "各阵营咬得很紧——每一单都可能改写榜单，冲！")
    return {"tip": tip, "source": "fallback"}


def get_repurchase_payload(db: Session, date_from: str | None, date_to: str | None,
                           re_stats: dict | None = None, summary: dict | None = None,
                           source: str | None = None) -> dict:
    """首返·复购双榜：在职参赛人员全员展示（周露露参与个人奖）。
    首返榜：个数降序，个数相同看复购金额（§1.4）；复购金额榜：金额降序，同额比首返数。"""
    ns, gmv, custom = _windows(date_from, date_to)
    roster = db.execute(text(
        "SELECT t.user_id, t.Name AS name FROM lsordertest.user_rel_team t WHERE 1=1"
        + _active_roster_filter("t") + " ORDER BY id"
    )).mappings().all()
    stats = re_stats if re_stats is not None else get_repurchase_stats(db, gmv[0], gmv[1], source=source)

    rows = []
    for m in roster:
        rs = stats.get(m["user_id"], {"first_count": 0, "re_amount": 0.0})
        rows.append({
            "user_id": m["user_id"],
            "name": m["name"],
            "first_count": rs["first_count"],
            "re_amount": round(rs["re_amount"], 2),
            "re_points": repurchase_points(rs["first_count"], rs["re_amount"]),
        })
    first_board = sorted(rows, key=lambda r: (-r["first_count"], -r["re_amount"], r["name"]))
    amount_board = sorted(rows, key=lambda r: (-r["re_amount"], -r["first_count"], r["name"]))
    return {
        "summary": summary if summary is not None else _summary(db, ns, gmv, custom, source=source),
        "first_board": first_board,
        "amount_board": amount_board,
        "as_of": beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_screen_payload(db: Session, date_from: str | None, date_to: str | None,
                       source: str | None = None) -> dict:
    """个人新签积分榜：榜单 + 双目标进度。"""
    ns, gmv, custom = _windows(date_from, date_to)
    board = get_new_sign_board(db, ns[0], ns[1], source=source)
    return {
        "summary": _summary(db, ns, gmv, custom, source=source),
        "items": board["items"],
        "as_of": beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── 阵营 PK（§1.6，口径全部 2026-07-29 确认）──────────────────────
CAMP_CONFIG = (
    {"name": "阵营一", "req": 34, "prize": 800},
    {"name": "阵营二", "req": 50, "prize": 1200},
    {"name": "阵营三", "req": 60, "prize": 2400},
)


def camp_prize(base: int, done: int, req: int) -> int:
    """当前奖池 = 基础 ×(1 + 10% × 超额档数)。

    超额档数按完成率**向下取整到 10% 整档**（超 15% 算 +10%），无封顶（A-2 已定）；
    未完成团队要求时不加成。"""
    if req <= 0 or done < req:
        return base
    steps = (done * 100 // req - 100) // 10
    return round(base * (1 + steps / 10))


def get_camps_payload(db: Session, date_from: str | None, date_to: str | None,
                      items: list | None = None, summary: dict | None = None,
                      source: str | None = None) -> dict:
    """阵营新签 PK 榜：三营进度/奖池/达标灯 + 成员芯片（含"阵营第一"标记）。

    items/summary 可由调用方传入预计算结果（headline 快照复用，避免重复全表扫）。"""
    ns, gmv, custom = _windows(date_from, date_to)
    if items is None:
        items = get_new_sign_board(db, ns[0], ns[1], source=source)["items"]

    # 全司新签积分前三（前三奖得主，§1.4 阵营第一奖将其排除；2026-07-30 二次裁决：
    # 屏上高亮同样按排除口径，前三成员卡片另加"全司前三"动效标识消歧义）。
    # 按 (积分, 金额) 展开并列：第 3/4 名完全并列时按 B-10 并列发奖，同为前三；0 分不占位。
    top3_ids: set = set()
    distinct_keys: list = []
    for i in items:
        if i["new_points"] <= 0:
            break  # 已排序，后面全是 0 分
        k = (i["new_points"], i["new_amount"])
        if k not in distinct_keys:
            if len(distinct_keys) == 3:
                break
            distinct_keys.append(k)
        top3_ids.add(i["user_id"])

    camps = []
    assigned = 0
    for cfg in CAMP_CONFIG:
        members = [i for i in items if (i["camp"] or "").strip() == cfg["name"]]
        assigned += len(members)
        # 阵营第一 = 排除全司前三后的阵营内积分第一；(积分,金额) 完全并列同标。
        # 该奖发放另有 6/4 门槛（全司统一），赛中领跑标记不预判门槛。
        leader_key = None
        for m in members:
            if m["user_id"] not in top3_ids and m["new_points"] > 0:
                leader_key = (m["new_points"], m["new_amount"])
                break
        done = sum(m["new_count"] for m in members)
        camps.append({
            "name": cfg["name"],
            "req": cfg["req"],
            "base_prize": cfg["prize"],
            "done": done,
            "pct": done * 100 // cfg["req"],  # 与奖池同用向下取整，杜绝"显示进档、奖池未进档"错位
            "prize": camp_prize(cfg["prize"], done, cfg["req"]),
            "reached_count": sum(1 for m in members if m["reached"]),
            "members": sorted(
                [{**m,
                  "is_first": (leader_key is not None
                               and m["user_id"] not in top3_ids
                               and (m["new_points"], m["new_amount"]) == leader_key),
                  "is_top3": m["user_id"] in top3_ids}
                 for m in members],
                key=lambda m: not m["is_first"],  # 阵营第一置顶（稳定排序，其余保持名次）
            ),
        })
    # 对账：user_rel_team.Camp 是手工维护列，脏值会让成员静默脱离三营口径（少算钱）。
    unassigned = len(items) - assigned
    if unassigned:
        msg = (f"[festival] {unassigned} 名成员的 Camp 值不在 CAMP_CONFIG，"
               f"未计入任何阵营进度——检查 lsordertest.user_rel_team.Camp 脏值")
        logger.warning(msg)
        print(msg, flush=True)
    return {
        "summary": summary if summary is not None else _summary(db, ns, gmv, custom, source=source),
        "camps": camps,
        "unassigned": unassigned,
        "as_of": beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── 团队（分队）积分榜（§1.5，周年加权；周年数以附录 C 权威表为准全程固定）──────
TEAM_NAMES = ("专治不服", "多财多亿", "稻乐偲", "星星之火", "行则将至", "乘风", "无名")
EXCLUDED_TEAMS = ("个人队",)  # 周露露个人参赛，不评团队奖（§1.7-5），刻意排除非脏值

# 周年权重快照（附录 C，B-8 关闭裁决：全程固定不随入职周年跨档切换）
# (新签权重, 复购权重)；未列出者 = 两周年及以上档 50/50
WEIGHT_SNAPSHOT_2026 = {
    "56786146": (0.6, 0.4), "56843323": (0.6, 0.4),                      # 1 周年：高瑞杰 罗馨瑜
    "57010933": (0.7, 0.3), "57125949": (0.7, 0.3),                     # 0 周年：胡宁宁 刘也
    "57130855": (0.7, 0.3), "57180994": (0.7, 0.3),                     # 0 周年：凯丽 张心茹
}


def member_weights(user_id: str) -> tuple:
    return WEIGHT_SNAPSHOT_2026.get(user_id, (0.5, 0.5))


def get_teams_payload(db: Session, date_from: str | None, date_to: str | None,
                      items: list | None = None, re_stats: dict | None = None,
                      summary: dict | None = None, source: str | None = None) -> dict:
    """团队人均积分榜：团队积分 = Σ成员(新签积分×新签权重 + 复购积分×复购权重)，
    人均 = 团队积分÷人数（保留 1 位小数）；并列比人均复购金额（B-10）。"""
    ns, gmv, custom = _windows(date_from, date_to)
    if items is None:
        items = get_new_sign_board(db, ns[0], ns[1], source=source)["items"]
    if re_stats is None:
        re_stats = get_repurchase_stats(db, gmv[0], gmv[1], source=source)

    grouped: dict = {name: [] for name in TEAM_NAMES}
    unassigned = 0
    for i in items:
        team = (i["team"] or "").strip()
        if team in EXCLUDED_TEAMS:
            continue
        if team not in grouped:
            unassigned += 1
            continue
        rs = re_stats.get(i["user_id"], {"first_count": 0, "re_amount": 0.0})
        rp = repurchase_points(rs["first_count"], rs["re_amount"])
        wn, wr = member_weights(i["user_id"])
        grouped[team].append({
            "user_id": i["user_id"],
            "name": i["name"],
            "new_points": i["new_points"],
            "re_points": rp,
            "re_amount": rs["re_amount"],
            "score": round(i["new_points"] * wn + rp * wr, 1),
        })
    if unassigned:
        msg = (f"[festival] {unassigned} 名成员的 Team 值不在 TEAM_NAMES，"
               f"未计入任何分队——检查 lsordertest.user_rel_team.Team 脏值")
        logger.warning(msg)
        print(msg, flush=True)

    teams = []
    for name in TEAM_NAMES:
        members = sorted(grouped[name], key=lambda m: (-m["score"], m["name"]))
        n = len(members)
        total = sum(m["score"] for m in members)
        per_re = (sum(m["re_amount"] for m in members) / n) if n else 0.0
        teams.append({
            "name": name,
            "count": n,
            "total": round(total, 1),
            "avg": round(total / n, 1) if n else 0.0,
            "per_capita_re_amount": round(per_re, 2),
            "members": members,
        })
    # 人均积分降序；并列比人均复购金额（B-10）；队名兜底保证确定性
    teams.sort(key=lambda t: (-t["avg"], -t["per_capita_re_amount"], t["name"]))
    for idx, t in enumerate(teams):
        t["rank"] = idx + 1
    return {
        "summary": summary if summary is not None else _summary(db, ns, gmv, custom, source=source),
        "teams": teams,
        "unassigned": unassigned,
        "as_of": beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
    }
