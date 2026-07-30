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

import logging
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 活动常量（规则文档 §1.1）
ACTIVITY_NEW_SIGN_WINDOW = ("2026-08-01", "2026-08-31")   # 新签窗口（B-1：只统计 8 月）
ACTIVITY_GMV_WINDOW = ("2026-08-01", "2026-09-30")        # GMV / 复购窗口
COMPANY_NEW_SIGN_TARGET = 149
COMPANY_GMV_TARGET = 3_260_000  # 326 万美金

# 新成交 + 定制品：两字段在 custom_fields 序列化中确实相邻（data-layer 文档 §3 实测），
# 首返字段不相邻，必须拆成两个独立 LIKE（邻接匹配实测 0 行）。
NEW_SIGN_MARK = '%"22595163468": "是", "691123983470": "定制品"%'
RE_MARK = '%"22595163468": "否", "691123983470": "定制品"%'
FIRST_RETURN_MARK = '%"20528142733548": "是"%'
CUSTOM_MARK = '%"691123983470": "定制品"%'
NEW_ANY_MARK = '%"22595163468": "是"%'

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


def _windows(date_from: str | None, date_to: str | None):
    """自定义窗口（预览用）时新签/GMV 同窗；否则用活动固定窗口。"""
    custom = bool(date_from and date_to)
    ns = (date_from, date_to) if custom else ACTIVITY_NEW_SIGN_WINDOW
    gmv = (date_from, date_to) if custom else ACTIVITY_GMV_WINDOW
    return ns, gmv, custom


def _summary(db: Session, ns, gmv, preview: bool) -> dict:
    return {
        "new_total": get_company_new_total(db, ns[0], ns[1]),
        "new_target": COMPANY_NEW_SIGN_TARGET,
        "gmv_total": get_gmv_total(db, gmv[0], gmv[1]),
        "gmv_target": COMPANY_GMV_TARGET,
        "window": {"from": ns[0], "to": ns[1], "preview": preview},
    }


def get_repurchase_stats(db: Session, date_from: str, date_to: str) -> dict:
    """每人复购口径：首返客户数（A-5 有史以来第一次返单，标记源自 OKKI 首返字段；
    拆分 LIKE）+ 复购金额（限 2025-01-01 起有新成交单的客户池，A-6/A-10 口径）。"""
    stats: dict = {}
    first_rows = db.execute(text(
        "SELECT a2.user_id, COUNT(DISTINCT a2.company_id) AS cnt "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
        "WHERE a2.custom_fields LIKE :m1 AND a2.custom_fields LIKE :m2 "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + _common_filter("a2") + " GROUP BY a2.user_id"
    ), {"m1": FIRST_RETURN_MARK, "m2": CUSTOM_MARK,
        "d1": date_from, "d2": date_to}).mappings().all()
    for r in first_rows:
        stats.setdefault(r["user_id"], {"first_count": 0, "re_amount": 0.0})
        stats[r["user_id"]]["first_count"] = int(r["cnt"])
    re_rows = db.execute(text(
        "SELECT a2.user_id, COALESCE(SUM(a2.amount_usd), 0) AS amt "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
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


def get_screen_payload(db: Session, date_from: str | None, date_to: str | None) -> dict:
    """个人新签积分榜：榜单 + 双目标进度。"""
    ns, gmv, custom = _windows(date_from, date_to)
    board = get_new_sign_board(db, ns[0], ns[1])
    return {
        "summary": _summary(db, ns, gmv, custom),
        "items": board["items"],
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── 阵营 PK（§1.6，口径全部 2026-07-29 确认）──────────────────────
CAMP_CONFIG = (
    {"name": "阵营一", "req": 40, "prize": 800},
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


def get_camps_payload(db: Session, date_from: str | None, date_to: str | None) -> dict:
    """阵营新签 PK 榜：三营进度/奖池/达标灯 + 成员芯片（含"阵营第一"标记）。"""
    ns, gmv, custom = _windows(date_from, date_to)
    items = get_new_sign_board(db, ns[0], ns[1])["items"]  # 已全局按积分/金额排序

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
        "summary": _summary(db, ns, gmv, custom),
        "camps": camps,
        "unassigned": unassigned,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── 团队（分队）积分榜（§1.5，周年加权；周年数以附录 C 权威表为准全程固定）──────
TEAM_NAMES = ("专治不服", "多财多亿", "稻乐偲", "星星之火", "行则将至", "乘风", "无名")
EXCLUDED_TEAMS = ("个人队",)  # 周露露个人参赛，不评团队奖（§1.7-5），刻意排除非脏值

# 周年权重快照（附录 C，B-8 关闭裁决：全程固定不随入职周年跨档切换）
# (新签权重, 复购权重)；未列出者 = 两周年及以上档 50/50
WEIGHT_SNAPSHOT_2026 = {
    "56786146": (0.6, 0.4), "56843323": (0.6, 0.4),                      # 1 周年：高瑞杰 罗馨瑜
    "57010933": (0.7, 0.3), "57125949": (0.7, 0.3), "57130433": (0.7, 0.3),  # 0 周年：胡宁宁 刘也 隋晓茹
    "57130855": (0.7, 0.3), "57180994": (0.7, 0.3),                      # 0 周年：凯丽 张心茹
}


def member_weights(user_id: str) -> tuple:
    return WEIGHT_SNAPSHOT_2026.get(user_id, (0.5, 0.5))


def get_teams_payload(db: Session, date_from: str | None, date_to: str | None) -> dict:
    """团队人均积分榜：团队积分 = Σ成员(新签积分×新签权重 + 复购积分×复购权重)，
    人均 = 团队积分÷人数（保留 1 位小数）；并列比人均复购金额（B-10）。"""
    ns, gmv, custom = _windows(date_from, date_to)
    items = get_new_sign_board(db, ns[0], ns[1])["items"]
    re_stats = get_repurchase_stats(db, gmv[0], gmv[1])

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
        "summary": _summary(db, ns, gmv, custom),
        "teams": teams,
        "unassigned": unassigned,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
