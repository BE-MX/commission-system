"""采购节大屏事件检测与留档（摘要屏滚动流 + 弹窗触发源）。

设计要点：
- 事件由「当前状态」推导候选，靠 dedup_key 幂等落库——同一事实（某人首次进新签前三、
  某单大单等）只记一次，检测重跑/服务重启不重复；
- 真实活动窗口才落库；预览窗口只返回内存态候选（大屏演示用，不污染正式记录）；
- 阈值依据规则文档 B-11（≥$5000 大单来袭 / ≥$30000 超级大单）；
- 零态防护：0 分/0 单/0 金额不产生任何"进榜/达标"事件。
"""

import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.festival.models import FestivalEvent, FestivalState
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
    "daily_combo":     {"level": "L3", "label": "当日连击"},
    "company_milestone": {"level": "L4", "label": "公司目标里程碑"},
    "camp_over_target": {"level": "L4", "label": "阵营超额里程碑"},
    "rank_up_sign":    {"level": "L3", "label": "新签名次上升"},
    "rank_up_first":   {"level": "L3", "label": "首返名次上升"},
    "rank_up_re":      {"level": "L3", "label": "复购名次上升"},
    "rank_up_team":    {"level": "L3", "label": "团队名次上升"},
    "rank_up_camp":    {"level": "L3", "label": "阵营第一易主"},
}

# 2026-08-04 有效名册变化后，以下事件的“事实主体”会随全员口径一起变化。
# 给新事实换幂等命名空间，同时让 feed 隐藏旧命名空间；这样既保留审计历史，
# 又不会让旧 first_sign 唯一键挡住当前在职人员的正确首单事件。
ROSTER_EVENT_VERSION = "roster-20260804"
ROSTER_REBASED_EVENT_TYPES = frozenset({"first_sign", "team_top3", "camp_target"})


def _cand(event_type, subject_type, subject_id, subject_name,
          dedup_key, amount=None, detail=None):
    meta = EVENT_META[event_type]
    if event_type in ROSTER_REBASED_EVENT_TYPES:
        dedup_key = f"{ROSTER_EVENT_VERSION}:{dedup_key}"
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


def _deal_candidates(db: Session, date_from: str, date_to: str,
                     source: str | None = None) -> list:
    """大单/超级大单：任意订单单笔 ≥$5000。幂等键对齐 OKKI 订单号——
    主轨优先用 xiaoman_order_id（与保底轨同键，切轨不重报），未推单兜底发票号。"""
    out = []
    if fsvc._data_source(source) == "ark":
        rows = db.execute(text(
            "SELECT i.xiaoman_order_id, i.invoice_no,"
            f"       {fsvc._ARK_AMOUNT} AS amt, t.Name AS name, t.user_id AS user_id"
            + fsvc._ARK_JOIN +
            f"   AND {fsvc._ARK_AMOUNT} >= :thr"
            "   AND i.invoice_date >= :d1 AND i.invoice_date <= :d2"
        ), {"thr": BIG_DEAL_USD, "d1": date_from, "d2": date_to}).mappings().all()
        for r in rows:
            amt = float(r["amt"])
            key = r["xiaoman_order_id"] or f"ark:{r['invoice_no']}"
            etype = "super_deal" if amt >= SUPER_DEAL_USD else "big_deal"
            out.append(_cand(etype, "person", r["user_id"], r["name"],
                             f"deal:{key}", amount=amt, detail=f"${amt:,.0f}"))
        return out
    rows = db.execute(text(
        "SELECT a2.order_id, a2.amount_usd, t.Name AS name, t.user_id AS user_id "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
        + fsvc._active_roster_filter("t") +
        "WHERE a2.amount_usd >= :thr "
        "  AND a2.account_date >= :d1 AND a2.account_date <= :d2"
        + fsvc._common_filter("a2")
    ), {"thr": BIG_DEAL_USD, "d1": date_from, "d2": date_to}).mappings().all()
    for r in rows:
        amt = float(r["amount_usd"])
        etype = "super_deal" if amt >= SUPER_DEAL_USD else "big_deal"
        out.append(_cand(etype, "person", r["user_id"], r["name"],
                         f"deal:{r['order_id']}", amount=amt,
                         detail=f"${amt:,.0f}"))
    return out


def _first_sign_candidate(db: Session, date_from: str, date_to: str,
                          source: str | None = None) -> list:
    """首单新签：全活动第一单独享（B-6：日期最早，同日按主键兜底定序）。"""
    if fsvc._data_source(source) == "ark":
        row = db.execute(text(
            "SELECT t.Name AS name, t.user_id AS user_id,"
            f"       {fsvc._ARK_AMOUNT} AS amt"
            + fsvc._ARK_JOIN +
            "   AND i.okki_new_deal = 1"
            "   AND i.invoice_date >= :d1 AND i.invoice_date <= :d2"
            " ORDER BY i.invoice_date ASC, i.id ASC LIMIT 1"
        ), {"d1": date_from, "d2": date_to}).mappings().first()
        if not row:
            return []
        return [_cand("first_sign", "person", row["user_id"], row["name"],
                      "first_sign", amount=float(row["amt"] or 0),
                      detail="全活动第一单 · 红包 ¥66")]
    row = db.execute(text(
        "SELECT t.Name AS name, t.user_id AS user_id, a2.amount_usd "
        "FROM lsordertest.okki_orders a2 "
        "JOIN lsordertest.user_rel_team t ON t.user_id = a2.user_id "
        + fsvc._active_roster_filter("t") +
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
                      first_board: list, amount_board: list,
                      source: str | None = None) -> list:
    """从当前状态推导全部候选事件（零态不触发）。"""
    cands = []
    cands += _first_sign_candidate(db, ns[0], ns[1], source=source)
    cands += _deal_candidates(db, gmv[0], gmv[1], source=source)

    for c in camps:
        for m in c["members"]:
            if m["reached"]:
                cands.append(_cand("personal_target", "person", m["user_id"], m["name"],
                                   f"ptarget:{m['user_id']}",
                                   detail=f"新签 {m['new_count']}/{m['target']} 达标"))
        if c["done"] >= c["req"] > 0:
            cands.append(_cand("camp_target", "camp", c["name"], c["name"],
                               f"ctarget:{c['name']}",
                               detail=f"新签 {c['done']}/{c['req']} · 奖池 ¥{c['prize']}"))
    return cands


def _read_state(db: Session, key: str) -> dict | None:
    row = db.get(FestivalState, key)
    if not row:
        return None
    try:
        value = json.loads(row.value_json)
        if not isinstance(value, dict):
            raise ValueError("state JSON must be an object")
        return value
    except (TypeError, ValueError):
        logger.warning("[festival] 状态 %s JSON 损坏，按首次观察重建", key)
        print(f"[festival] 状态 {key} JSON 损坏，按首次观察重建", flush=True)
        return None


def _write_state(db: Session, key: str, value: dict) -> None:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    row = db.get(FestivalState, key)
    if row:
        row.value_json = raw
        row.updated_at = datetime.now()
    else:
        try:
            with db.begin_nested():
                db.add(FestivalState(state_key=key, value_json=raw))
        except IntegrityError:
            # 大屏与分钟任务可能同时做首次观察；唯一键冲突只说明另一请求先建了基线。
            row = db.get(FestivalState, key)
            if row:
                row.value_json = raw
                row.updated_at = datetime.now()
    db.flush()


def acquire_detector_lock(db: Session) -> None:
    """锁住正式事件检测事务，避免大屏请求与分钟任务并发覆盖快照。"""
    key = "detector:lock"
    row = (db.query(FestivalState)
           .filter(FestivalState.state_key == key)
           .with_for_update().one_or_none())
    if row:
        return
    _write_state(db, key, {"purpose": "serialize festival event detection"})
    (db.query(FestivalState)
     .filter(FestivalState.state_key == key)
     .with_for_update().one())


def filter_stateless_baseline(db: Session, candidates: list, state_scope: str) -> list:
    """首次启用投递时记住既有旧版事实，避免下一分钟把整段活动历史补发到群里。"""
    key = f"baseline:{state_scope}:stateless"
    previous = _read_state(db, key)
    if previous is None:
        _write_state(db, key, {"dedup_keys": [c["dedup_key"] for c in candidates]})
        return []
    ignored = set(previous.get("dedup_keys", []))
    return [candidate for candidate in candidates if candidate["dedup_key"] not in ignored]


def _ranking_candidates(db: Session, *, board: str, event_type: str,
                        rows: list, top_n: int, id_field: str,
                        name_field: str = "name", subject_type: str = "person",
                        score_detail=None, state_scope: str) -> list:
    """比较完整榜单，仅为进入目标区且名次上升的主体创建事件。"""
    current = [
        {"id": str(row[id_field]), "name": str(row[name_field]), "rank": idx}
        for idx, row in enumerate(rows, start=1)
    ]
    state_key = f"ranking:{state_scope}:{board}"
    previous = _read_state(db, state_key)
    if previous is None:
        _write_state(db, state_key, {"revision": 0, "rows": current})
        return []

    old_ranks = {row["id"]: int(row["rank"]) for row in previous.get("rows", [])}
    old_order = [row["id"] for row in previous.get("rows", [])]
    new_order = [row["id"] for row in current]
    revision = int(previous.get("revision", 0)) + (old_order != new_order)
    candidates = []
    for idx, row in enumerate(rows, start=1):
        subject_id = str(row[id_field])
        old_rank = old_ranks.get(subject_id)
        if idx > top_n or old_rank is None or idx >= old_rank:
            continue
        detail = f"第{old_rank}名 → 第{idx}名"
        if score_detail:
            extra = score_detail(row)
            if extra:
                detail += f" · {extra}"
        candidates.append(_cand(
            event_type, subject_type, subject_id, str(row[name_field]),
            f"rank:{state_scope}:{board}:{revision}:{subject_id}:{old_rank}-{idx}",
            detail=detail,
        ))
    _write_state(db, state_key, {"revision": revision, "rows": current})
    return candidates


def _camp_leader_candidates(db: Session, camps: list, state_scope: str) -> list:
    candidates = []
    for camp in camps:
        leaders = [m for m in camp.get("members", []) if m.get("is_first")]
        current = [{"id": str(m["user_id"]), "name": str(m["name"])} for m in leaders]
        state_key = f"camp_leader:{state_scope}:{camp['name']}"
        previous = _read_state(db, state_key)
        if previous is None:
            _write_state(db, state_key, {"revision": 0, "leaders": current})
            continue
        old_ids = {row["id"] for row in previous.get("leaders", [])}
        old_names = "、".join(row["name"] for row in previous.get("leaders", [])) or "暂无"
        new_ids = {row["id"] for row in current}
        changed = old_ids != new_ids
        revision = int(previous.get("revision", 0)) + changed
        if changed:
            for leader in current:
                if leader["id"] in old_ids:
                    continue
                candidates.append(_cand(
                    "rank_up_camp", "person", leader["id"], leader["name"],
                    f"rank:{state_scope}:camp:{camp['name']}:{revision}:{leader['id']}",
                    detail=f"成为{camp['name']}第一 · 原第一 {old_names}",
                ))
        _write_state(db, state_key, {"revision": revision, "leaders": current})
    return candidates


def _milestone_candidates(db: Session, summary: dict, camps: list,
                          state_scope: str) -> list:
    candidates = []
    target = int(summary.get("new_target") or fsvc.COMPANY_NEW_SIGN_TARGET)
    total = int(summary.get("new_total") or 0)
    current_step = min(100, total * 100 // target // 10 * 10) if target > 0 else 0
    company_state_key = f"milestone:{state_scope}:company_new"
    previous = _read_state(db, company_state_key)
    if previous is None:
        _write_state(db, company_state_key, {"max_step": current_step})
    else:
        old_step = int(previous.get("max_step", 0))
        for step in range(max(10, old_step + 10), current_step + 1, 10):
            candidates.append(_cand(
                "company_milestone", "company", "company", "莱莎采购节",
                f"company_milestone:{step}",
                detail=f"149 新签目标完成 {step}% · 当前 {total}/{target}",
            ))
        _write_state(db, company_state_key, {"max_step": max(old_step, current_step)})

    for camp in camps:
        req = int(camp.get("req") or 0)
        done = int(camp.get("done") or 0)
        step = done * 100 // req // 10 * 10 if req > 0 else 0
        state_key = f"milestone:{state_scope}:camp:{camp['name']}"
        previous = _read_state(db, state_key)
        if previous is None:
            _write_state(db, state_key, {"max_step": step})
            continue
        old_step = int(previous.get("max_step", 0))
        for reached in range(max(110, old_step + 10), step + 1, 10):
            candidates.append(_cand(
                "camp_over_target", "camp", str(camp["name"]), str(camp["name"]),
                f"camp_over:{camp['name']}:{reached}",
                detail=f"阵营目标完成 {reached}% · 新签 {done}/{req}",
            ))
        _write_state(db, state_key, {"max_step": max(old_step, step)})
    return candidates


def _combo_candidates(db: Session, daily_orders: dict, today: date,
                      state_scope: str) -> list:
    state_key = f"combo:{state_scope}:{today.isoformat()}"
    normalized = {
        str(user_id): [
            {"order_id": str(order["order_id"]), "amount": float(order.get("amount") or 0),
             "name": str(order.get("name") or user_id)}
            for order in orders
        ]
        for user_id, orders in daily_orders.items()
    }
    previous = _read_state(db, state_key)
    if previous is None:
        _write_state(db, state_key, {"orders": normalized})
        return []

    old_orders = previous.get("orders", {})
    candidates = []
    merged_orders = {str(user_id): list(orders) for user_id, orders in old_orders.items()}
    for user_id, orders in normalized.items():
        history = merged_orders.setdefault(user_id, [])
        seen = {row["order_id"] for row in history}
        additions = [order for order in orders if order["order_id"] not in seen]
        for offset, order in enumerate(additions, start=1):
            sequence = len(history) + offset
            if sequence < 2:
                continue
            name = str(order.get("name") or user_id)
            candidates.append(_cand(
                "daily_combo", "person", user_id, name,
                f"combo:{today.isoformat()}:{user_id}:{order['order_id']}",
                amount=order["amount"],
                detail=f"当日第 {sequence} 单 · ×{sequence} 连击",
            ))
        history.extend(additions)
    _write_state(db, state_key, {"orders": merged_orders})
    return candidates


def detect_stateful_candidates(db: Session, *, summary: dict, items: list,
                               camps: list, teams: list, first_board: list,
                               amount_board: list, daily_orders: dict,
                               state_scope: str,
                               today: date | None = None) -> list:
    """检测依赖前后状态的事件；首次观察只建基线，不补发历史。"""
    today = today or date.today()
    candidates = []
    candidates += _ranking_candidates(
        db, board="new_sign", event_type="rank_up_sign", rows=items, top_n=3,
        id_field="user_id", score_detail=lambda r: f"新签 {r['new_points']:g} 分",
        state_scope=state_scope)
    candidates += _ranking_candidates(
        db, board="first_return", event_type="rank_up_first", rows=first_board, top_n=2,
        id_field="user_id", score_detail=lambda r: f"首返 {r['first_count']} 个",
        state_scope=state_scope)
    candidates += _ranking_candidates(
        db, board="repurchase", event_type="rank_up_re", rows=amount_board, top_n=2,
        id_field="user_id", score_detail=lambda r: f"复购 ${r['re_amount']:,.0f}",
        state_scope=state_scope)
    candidates += _ranking_candidates(
        db, board="team", event_type="rank_up_team", rows=teams, top_n=3,
        id_field="name", subject_type="team",
        score_detail=lambda r: f"人均 {r['avg']:.1f} 分", state_scope=state_scope)
    candidates += _camp_leader_candidates(db, camps, state_scope)
    candidates += _milestone_candidates(db, summary, camps, state_scope)
    candidates += _combo_candidates(db, daily_orders, today, state_scope)
    return candidates


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


def feed(db: Session, limit: int = 40, within_hours: int = 48,
         after_id: int | None = None) -> list:
    """滚动流或未读批次。

    ``after_id`` 缺省时返回最新事件供底栏展示；传入游标时按正序返回最老的
    未读批次，避免一次同步超过 ``limit`` 条时跳过较早事件。
    """
    cutoff = datetime.now() - timedelta(hours=within_hours)
    query = db.query(FestivalEvent).filter(FestivalEvent.created_at >= cutoff)
    excluded_ids = tuple(fsvc.EXCLUDED_FESTIVAL_USER_IDS)
    if excluded_ids:
        query = query.filter(
            (FestivalEvent.subject_type != "person")
            | FestivalEvent.subject_id.notin_(excluded_ids)
        )
    query = query.filter(
        FestivalEvent.event_type.notin_(tuple(ROSTER_REBASED_EVENT_TYPES))
        | FestivalEvent.dedup_key.like(f"{ROSTER_EVENT_VERSION}:%")
    )
    if after_id is None:
        rows = query.order_by(FestivalEvent.id.desc()).limit(limit).all()
    else:
        rows = (query.filter(FestivalEvent.id > after_id)
                .order_by(FestivalEvent.id.asc()).limit(limit).all())
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
