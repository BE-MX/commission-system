"""采购节大屏事件检测与留档（摘要屏滚动流 + 弹窗触发源）。

设计要点：
- 事件由「当前状态」推导候选，靠 dedup_key 幂等落库——同一事实（某人首次进新签前三、
  某单大单等）只记一次，检测重跑/服务重启不重复；
- 真实活动窗口才落库；预览窗口只返回内存态候选（大屏演示用，不污染正式记录）；
- 阈值依据规则文档 B-11（≥$5000 大单来袭 / ≥$30000 超级大单）；
- 零态防护：0 分/0 单/0 金额不产生任何"进榜/达标"事件。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.festival.models import FestivalEvent
from app.festival import service as fsvc

logger = logging.getLogger(__name__)

BIG_DEAL_USD = 5000
SUPER_DEAL_USD = 30000

# 事件类型登记表：level 决定大屏表现（L4 全屏弹窗 / L3 插播条）
EVENT_META = {
    "first_sign":      {"level": "L4", "label": "首单新签"},
    "super_deal":      {"level": "L4", "label": "超级大单"},
    "camp_target":     {"level": "L4", "label": "达成阵营目标"},
    "big_deal":        {"level": "L3", "label": "大单来袭"},
    "top3_sign":       {"level": "L3", "label": "进入新签前3"},
    "top2_first":      {"level": "L3", "label": "进入首返前2"},
    "top2_re":         {"level": "L3", "label": "进入复购前2"},
    "personal_target": {"level": "L3", "label": "达成个人新签目标"},
    "team_top3":       {"level": "L3", "label": "进入团队前三"},
    "camp_first":      {"level": "L3", "label": "成为阵营第一"},
}


def _cand(event_type, subject_type, subject_id, subject_name,
          dedup_key, amount=None, detail=None):
    meta = EVENT_META[event_type]
    return {
        "event_type": event_type,
        "level": meta["level"],
        "label": meta["label"],
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_name": subject_name,
        "amount": float(amount) if amount is not None else None,
        "detail": detail,
        "dedup_key": dedup_key,
    }


def _deal_candidates(db: Session, date_from: str, date_to: str) -> list:
    """大单/超级大单：任意订单（新签或复购，公共过滤内）单笔 ≥$5000，按 order_id 幂等。"""
    rows = db.execute(text(
        "SELECT a2.order_id, a2.amount_usd, t.Name AS name, t.user_id AS user_id "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
        "WHERE a2.amount_usd >= :thr "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + fsvc._common_filter("a2")
    ), {"thr": BIG_DEAL_USD, "d1": date_from, "d2": date_to}).mappings().all()
    out = []
    for r in rows:
        amt = float(r["amount_usd"])
        etype = "super_deal" if amt >= SUPER_DEAL_USD else "big_deal"
        out.append(_cand(etype, "person", r["user_id"], r["name"],
                         f"deal:{r['order_id']}", amount=amt,
                         detail=f"${amt:,.0f}"))
    return out


def _first_sign_candidate(db: Session, date_from: str, date_to: str) -> list:
    """首单新签：全活动第一单独享（B-6：account_date 最早，同日按 order_id 兜底定序）。"""
    row = db.execute(text(
        "SELECT t.Name AS name, t.user_id AS user_id, a2.amount_usd "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
        "WHERE a2.custom_fields LIKE :mark "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + fsvc._common_filter("a2") +
        " ORDER BY a2.account_date ASC, a2.order_id ASC LIMIT 1"
    ), {"mark": fsvc.NEW_SIGN_MARK, "d1": date_from, "d2": date_to}).mappings().first()
    if not row:
        return []
    return [_cand("first_sign", "person", row["user_id"], row["name"],
                  "first_sign", amount=float(row["amount_usd"] or 0),
                  detail="全活动第一单 · 红包 ¥66")]


def detect_candidates(db: Session, ns: tuple, gmv: tuple,
                      items: list, camps: list, teams: list,
                      first_board: list, amount_board: list) -> list:
    """从当前状态推导全部候选事件（零态不触发）。"""
    cands = []
    cands += _first_sign_candidate(db, ns[0], ns[1])
    cands += _deal_candidates(db, gmv[0], gmv[1])

    for i in items[:3]:
        if i["new_points"] > 0:
            cands.append(_cand("top3_sign", "person", i["user_id"], i["name"],
                               f"top3_sign:{i['user_id']}",
                               detail=f"新签积分 {i['new_points']:g} 分"))
    for r in first_board[:2]:
        if r["first_count"] > 0:
            cands.append(_cand("top2_first", "person", r["user_id"], r["name"],
                               f"top2_first:{r['user_id']}",
                               detail=f"首返 {r['first_count']} 个"))
    for r in amount_board[:2]:
        if r["re_amount"] > 0:
            cands.append(_cand("top2_re", "person", r["user_id"], r["name"],
                               f"top2_re:{r['user_id']}",
                               amount=r["re_amount"],
                               detail=f"复购 ${r['re_amount']:,.0f}"))
    for c in camps:
        for m in c["members"]:
            if m["reached"]:
                cands.append(_cand("personal_target", "person", m["user_id"], m["name"],
                                   f"ptarget:{m['user_id']}",
                                   detail=f"新签 {m['new_count']}/{m['target']} 达标"))
            if m["is_first"]:
                cands.append(_cand("camp_first", "person", m["user_id"], m["name"],
                                   f"cfirst:{c['name']}:{m['user_id']}",
                                   detail=f"{c['name']}第一"))
        if c["done"] >= c["req"] > 0:
            cands.append(_cand("camp_target", "camp", c["name"], c["name"],
                               f"ctarget:{c['name']}",
                               detail=f"新签 {c['done']}/{c['req']} · 奖池 ¥{c['prize']}"))
    for t in teams[:3]:
        if t["total"] > 0:
            cands.append(_cand("team_top3", "team", t["name"], t["name"],
                               f"ttop3:{t['name']}",
                               detail=f"人均 {t['avg']:.1f} 分 · 第{t['rank']}名"))
    return cands


def persist_new(db: Session, candidates: list) -> int:
    """按 dedup_key 幂等落库，返回本轮新增数。"""
    if not candidates:
        return 0
    keys = [c["dedup_key"] for c in candidates]
    existing = {r[0] for r in db.query(FestivalEvent.dedup_key)
                .filter(FestivalEvent.dedup_key.in_(keys)).all()}
    fresh = [c for c in candidates if c["dedup_key"] not in existing]
    if not fresh:
        return 0
    added = 0
    for c in fresh:
        # 宪法 6：批量循环用 savepoint 隔离单条失败——并发轮询撞唯一键只丢该条，不连坐整批
        try:
            with db.begin_nested():
                db.add(FestivalEvent(
                    event_type=c["event_type"], level=c["level"],
                    subject_type=c["subject_type"], subject_id=c["subject_id"],
                    subject_name=c["subject_name"], amount=c["amount"],
                    detail=c["detail"], dedup_key=c["dedup_key"],
                ))
            added += 1
        except IntegrityError:
            logger.warning("[festival] 事件 %s 撞唯一键，跳过（并发轮询）", c["dedup_key"])
            print(f"[festival] 事件 {c['dedup_key']} 撞唯一键，跳过（并发轮询）", flush=True)
    db.commit()
    return added


def feed(db: Session, limit: int = 40, within_hours: int = 48) -> list:
    """滚动流：最新在前，只出 48 小时内的播报（留档不删，只是屏上不再滚旧闻）。"""
    cutoff = datetime.now() - timedelta(hours=within_hours)
    rows = (db.query(FestivalEvent)
            .filter(FestivalEvent.created_at >= cutoff)
            .order_by(FestivalEvent.id.desc()).limit(limit).all())
    return [{
        "id": r.id,
        "event_type": r.event_type,
        "level": r.level,
        "label": EVENT_META.get(r.event_type, {}).get("label", r.event_type),
        "subject_type": r.subject_type,
        "subject_id": r.subject_id,
        "subject_name": r.subject_name,
        "amount": float(r.amount) if r.amount is not None else None,
        "detail": r.detail,
        "created_at": r.created_at.strftime("%m-%d %H:%M") if r.created_at else "",
    } for r in rows]
