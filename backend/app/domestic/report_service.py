"""内贸报工 service —— 按数量在工序间流转，支持拆批

与外贸报工（整行 0/1 流转）的根本差别：一次报工带数量。
大多数场景是整批一次报完（默认带出全部可报数量，一键确认）；
工序交接拆批时把数字改小即可，剩余量自然停在上一道，
之后任何人再扫**同一张码**继续报——不拆卡、不重打码。
"""

import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now
from app.domestic import constants as C
from app.domestic import progress_service, route_rule_service, routing_service, unit_service
from app.domestic.models import (
    DomesticCustomer,
    DomesticItemProgress,
    DomesticOrder,
    DomesticOrderItem,
    DomesticReportLog,
    DomesticItemUnit,
    DomesticReportUnit,
    DomesticSkipLog,
    DomesticSkipUnit,
)
from app.production.models import Process, UserProcessBinding

logger = logging.getLogger("commission")
settings = get_settings()

_BJ_TZ = timezone(timedelta(hours=8))


def _bj_now() -> datetime:
    """北京时间，与外贸报工口径一致（存 naive datetime）"""
    return beijing_now()


# ── 二维码 ────────────────────────────────────────────


def generate_qr_sign(item_id: int, secret: str) -> str:
    message = f"{C.QR_PREFIX}:{item_id}"
    return hmac.new(key=secret.encode(), msg=message.encode(), digestmod=hashlib.sha256).hexdigest()[:8]


def generate_qr_data(item_id: int) -> str:
    return f"{C.QR_PREFIX}:{item_id}:{generate_qr_sign(item_id, settings.QR_SIGN_SECRET)}"


def qr_sign_matches(item_id: int, sign: str) -> bool:
    """同外贸侧（production/report_service）：登录后报工扫码的密钥轮换兜底；
    免登录的进度码（verify_track_scene）不走这里，永远只认当前密钥。"""
    if hmac.compare_digest(sign, generate_qr_sign(item_id, settings.QR_SIGN_SECRET)):
        return True
    legacy = settings.QR_SIGN_SECRET_LEGACY
    return bool(legacy) and hmac.compare_digest(sign, generate_qr_sign(item_id, legacy))


def verify_qr_data(qr_data: str) -> tuple[bool, int]:
    """校验内贸二维码，返回 (是否有效, item_id)。外贸的 ARK-P 码在这里一律无效。"""
    match = re.match(rf"^{C.QR_PREFIX}:(\d+):([a-f0-9]{{8}})$", qr_data or "")
    if not match:
        return False, 0
    item_id = int(match.group(1))
    return qr_sign_matches(item_id, match.group(2)), item_id


def generate_unit_qr_sign(unit_id: int, secret: str) -> str:
    message = f"{C.UNIT_QR_PREFIX}:{unit_id}"
    return hmac.new(key=secret.encode(), msg=message.encode(), digestmod=hashlib.sha256).hexdigest()[:8]


def generate_unit_qr_data(unit_id: int) -> str:
    return f"{C.UNIT_QR_PREFIX}:{unit_id}:{generate_unit_qr_sign(unit_id, settings.QR_SIGN_SECRET)}"


def verify_unit_qr_data(qr_data: str) -> tuple[bool, int]:
    match = re.match(rf"^{C.UNIT_QR_PREFIX}:(\d+):([a-f0-9]{{8}})$", qr_data or "")
    if not match:
        return False, 0
    unit_id = int(match.group(1))
    sign = match.group(2)
    if hmac.compare_digest(sign, generate_unit_qr_sign(unit_id, settings.QR_SIGN_SECRET)):
        return True, unit_id
    legacy = settings.QR_SIGN_SECRET_LEGACY
    valid = bool(legacy) and hmac.compare_digest(sign, generate_unit_qr_sign(unit_id, legacy))
    return valid, unit_id


# ── 订单进度小程序码（微信扫码免登录查看完整订单）──
#
# scene 是微信小程序码的带参字段，限 32 个可见字符，格式 `i:<item_id>:<hmac16>`。
# 签名消息域用 ARK-DT:<item_id>（T=track），与流转卡的 ARK-D:<item_id> 严格隔离：
# 流转卡贴在车间墙上人尽可见且只截 8 hex——若共用消息域，一张流转卡
# 就泄露了 track 签名的前一半。
# 签名取 16 hex（64 bit）：这个口子完全免登录，8 hex 对在线遍历只是"贵"
# 不是"不可行"；scene 预算 32 字符足够放 16。


def qr_secret_is_default() -> bool:
    """QR_SIGN_SECRET 还是仓库里的默认字面量 = 任何能读代码的人都能离线伪造签名。

    免登录端点的整个授权模型压在这个密钥上，默认值等于没锁——
    生成和验证两侧都必须拒绝服务，逼着部署时配好 .env。
    """
    from app.core.config import Settings

    return settings.QR_SIGN_SECRET == Settings.model_fields["QR_SIGN_SECRET"].default


def generate_track_scene_sign(item_id: int, secret: str) -> str:
    message = f"{C.QR_PREFIX}T:{item_id}"
    return hmac.new(key=secret.encode(), msg=message.encode(), digestmod=hashlib.sha256).hexdigest()[:16]


def generate_track_scene(item_id: int) -> str:
    return f"i:{item_id}:{generate_track_scene_sign(item_id, settings.QR_SIGN_SECRET)}"


def verify_track_scene(scene: str) -> tuple[bool, int]:
    """校验小程序码 scene，返回 (是否有效, item_id)。

    这是免登录进度页的**唯一**授权凭证：签名对得上 = 拿到了主站有权限
    的人生成的码 = 被授权看该明细所属的完整订单。
    """
    match = re.match(r"^i:(\d+):([a-f0-9]{16})$", (scene or "").strip())
    if not match:
        return False, 0
    item_id = int(match.group(1))
    expected = generate_track_scene_sign(item_id, settings.QR_SIGN_SECRET)
    return hmac.compare_digest(match.group(2), expected), item_id


# ── 扫码：工人看到什么 ────────────────────────────────


BLOCK_ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
BLOCK_NO_ROUTE = "NO_ROUTE"
BLOCK_ORDER_TERMINATED = "ORDER_TERMINATED"
BLOCK_ORDER_DRAFT = "ORDER_DRAFT"
BLOCK_ALL_DONE = "ALL_DONE"
BLOCK_NOT_ASSIGNED = "NOT_ASSIGNED"
BLOCK_NOTHING_REPORTABLE = "NOTHING_REPORTABLE"

BLOCK_MESSAGES = {
    BLOCK_ITEM_NOT_FOUND: "找不到这张卡对应的订单明细",
    BLOCK_NO_ROUTE: "这个产品还没配工艺路线，请联系跟单",
    BLOCK_ORDER_TERMINATED: "订单已终止或已删除，不能报工",
    BLOCK_ORDER_DRAFT: "订单还是草稿，请跟单提交后再报工",
    BLOCK_ALL_DONE: "这批货所有工序都做完了",
    BLOCK_NOT_ASSIGNED: "你没有被分配到这道工序",
    BLOCK_NOTHING_REPORTABLE: "上一道工序还没做出可接的数量，请稍后再扫",
}


def _user_process_ids(db: Session, user_id: int) -> set[int]:
    return {
        pid for (pid,) in db.query(UserProcessBinding.process_id)
        .filter(UserProcessBinding.user_id == user_id).all()
    }


def _assert_order_reportable(order: DomesticOrder) -> None:
    """终止或已软删的订单一律不能再报工。

    软删这条容易漏：卡片还贴在车间墙上，二维码不含时效也不含订单状态，
    删单之后工人照样扫得动——工时就会挂在一张查不到的订单上。
    """
    if order.deleted_flag:
        raise ValueError("订单已删除，不能报工")
    if order.status == C.ORDER_DRAFT:
        raise ValueError("订单还是草稿，不能报工")
    if order.status == C.ORDER_TERMINATED:
        raise ValueError("订单已终止，不能报工")


def _lock_order_then_item(
    db: Session, item_id: int
) -> tuple[DomesticOrder, DomesticOrderItem]:
    """Locate the parent, then acquire report mutation locks order-first."""
    order_id = db.query(DomesticOrderItem.order_id).filter(
        DomesticOrderItem.id == item_id
    ).scalar()
    if order_id is None:
        raise ValueError("订单明细不存在")
    order = db.query(DomesticOrder).filter(
        DomesticOrder.id == order_id
    ).populate_existing().with_for_update().first()
    if order is None:
        raise ValueError("订单不存在")
    item = db.query(DomesticOrderItem).filter(
        DomesticOrderItem.id == item_id
    ).populate_existing().with_for_update().first()
    if item is None:
        raise ValueError("订单明细不存在")
    if item.order_id != order.id:
        raise ValueError("订单明细所属订单已变化，请刷新后重试")
    return order, item


def _replay_result(db: Session, log: DomesticReportLog, *, lock: bool = False) -> dict:
    """幂等重放：同一个 request_id 再来一次，原样返回首次的结果。"""
    progress = db.query(DomesticItemProgress).get(log.progress_id)
    item = db.query(DomesticOrderItem).get(log.item_id)
    process_name = db.query(Process.name).filter(Process.id == log.process_id).scalar()
    units = unit_service.units_for_log(db, log.id, lock=lock)
    outcome_by_unit = dict(db.query(
        DomesticReportUnit.unit_id,
        DomesticReportUnit.outcome_code,
    ).filter(DomesticReportUnit.log_id == log.id).all())
    return {
        "log_id": log.id,
        "item_id": log.item_id,
        "process_name": process_name,
        "step_order": log.step_order,
        "reported_qty": log.report_qty,
        "step_completed_qty": progress.completed_qty if progress else 0,
        "order_qty": item.order_qty if item else 0,
        "step_finished": bool(progress and progress.status == 1),
        "item_finished": bool(item and item.status >= C.ITEM_DONE),
        "reported_at": log.reported_at,
        "unit_ids": [unit.id for unit in units],
        "unit_codes": [unit_service.unit_display_code(item, unit.unit_no) for unit in units] if item else [],
        "outcomes": log.outcome_json,
        "unit_outcomes": [
            {"unit_id": unit.id, "outcome_code": outcome_by_unit.get(unit.id)}
            for unit in units
        ],
        "replayed": True,
    }


def _report_replay_if_exists(
    db: Session,
    *,
    request_id: str | None,
    item_id: int,
    progress_id: int,
    qty: int,
    worker_id: int,
    unit_id: int | None,
    outcomes: dict[str, int] | None,
    lock: bool = False,
) -> dict | None:
    if not request_id:
        return None
    query = db.query(DomesticReportLog).filter(
        DomesticReportLog.request_id == request_id
    )
    if lock:
        query = query.with_for_update()
    existing = query.first()
    if not existing:
        return None
    same_request = (
        existing.item_id == item_id
        and existing.progress_id == progress_id
        and existing.report_qty == qty
        and existing.reported_by_user_id == worker_id
        and existing.report_mode == ("unit" if unit_id is not None else "quantity")
        and (existing.outcome_json or None) == outcomes
    )
    if unit_id is not None:
        same_request = same_request and any(
            unit.id == unit_id for unit in unit_service.units_for_log(
                db, existing.id, lock=lock,
            )
        )
    if not same_request:
        raise ValueError("该报工请求号已用于另一笔报工，请重新扫码")
    return _replay_result(db, existing, lock=lock)


def _is_target_request_unique_error(exc: IntegrityError, *, target: str) -> bool:
    """只识别本次幂等键唯一约束，不能把其它数据完整性错误伪装成重放。"""
    message = f"{exc.orig or exc} {exc.statement or ''}".lower()
    if target == "report":
        return (
            "ark_domestic_report_logs.request_id" in message
            or (
                "duplicate entry" in message
                and "request_id" in message
                and "ark_domestic_report_logs" in message
            )
        )
    return (
        "ark_domestic_skip_logs.request_id" in message
        or "uq_dom_skip_request_id" in message
        or (
            "duplicate entry" in message
            and "request_id" in message
            and "ark_domestic_skip_logs" in message
        )
    )


def _is_mysql_deadlock(exc: OperationalError) -> bool:
    args = getattr(exc.orig, "args", ())
    return bool(args) and args[0] == 1213


def scan_item(db: Session, item_id: int, user_id: int) -> dict:
    """扫码后返回工人要看的一切：产品、图文要求、该报哪道、能报多少。

    定位规则：优先取「工人绑定的工序中，还有可报数量且序号最小的那道」——
    工人不用选工序，扫完直接确认数量即可。
    """
    item = db.query(DomesticOrderItem).get(item_id)
    if not item:
        return {"can_submit": False, "block_reason": BLOCK_ITEM_NOT_FOUND,
                "block_message": BLOCK_MESSAGES[BLOCK_ITEM_NOT_FOUND]}

    order = db.query(DomesticOrder).get(item.order_id)
    customer = db.query(DomesticCustomer).get(order.customer_id) if order else None
    steps = progress_service.build_progress_view(db, item)
    if order:
        from app.domestic.order_service import order_dimension_view

        dimensions = order_dimension_view(db, order)
    else:
        dimensions = {
            "order_category": None,
            "order_category_label": "未填写",
            "order_type": None,
            "order_type_label": "未填写",
            "order_channel": None,
            "order_channel_label": "未填写",
        }

    base = {
        "item_id": item.id,
        "order_id": item.order_id,
        "domestic_no": order.domestic_no if order else None,
        "order_no": order.order_no if order else None,
        **dimensions,
        "customer_name": customer.shop_name if customer else None,
        "product_name": item.product_name,
        "line_no": item.line_no,
        "line_code": f"A{item.line_no or 1}",
        "attrs": item.attrs_snapshot or {},
        "order_qty": item.order_qty,
        "unit_price": float(item.unit_price or 0),
        "line_amount": float((item.unit_price or 0) * item.order_qty),
        "hairstyle": item.hairstyle,
        "hairstyle_images": item.hairstyle_images or [],
        "color": item.color,
        "color_images": item.color_images or [],
        "style_requirement": item.style_requirement,
        "style_images": item.style_images or [],
        "remark": item.remark,
        "remark_images": item.remark_images or [],
        "steps": steps,
    }

    def blocked(reason):
        return {**base, "can_submit": False, "block_reason": reason,
                "block_message": BLOCK_MESSAGES[reason], "next_step": None}

    if not order or order.deleted_flag or order.status == C.ORDER_TERMINATED:
        return blocked(BLOCK_ORDER_TERMINATED)
    if order.status == C.ORDER_DRAFT:
        return blocked(BLOCK_ORDER_DRAFT)
    if not steps:
        return blocked(BLOCK_NO_ROUTE)
    if steps[-1]["passed_qty"] >= item.order_qty:
        return blocked(BLOCK_ALL_DONE)

    my_processes = _user_process_ids(db, user_id)
    mine = [s for s in steps if s["process_id"] in my_processes]
    if not mine:
        return blocked(BLOCK_NOT_ASSIGNED)

    target = next((s for s in mine if s["reportable_qty"] > 0), None)
    if target is None:
        return blocked(BLOCK_NOTHING_REPORTABLE)

    return {**base, "can_submit": True, "block_reason": None, "block_message": None,
            "next_step": target}


def scan_unit(db: Session, unit_id: int, user_id: int) -> dict:
    """逐件扫码：只允许码指向的这一件进入它实际可做的下一道工序。"""
    unit = db.query(DomesticItemUnit).get(unit_id)
    if not unit or unit.status != 1:
        return {
            "can_submit": False,
            "block_reason": BLOCK_ITEM_NOT_FOUND,
            "block_message": "找不到这个单件二维码，或该单件已因数量调整停用",
        }
    base = scan_item(db, unit.item_id, user_id)
    item = db.query(DomesticOrderItem).get(unit.item_id)
    base.update({
        "unit_id": unit.id,
        "unit_no": unit.unit_no,
        "unit_code": unit_service.unit_display_code(item, unit.unit_no),
        "report_mode": "unit",
    })
    if not item or base.get("block_reason") in {
        BLOCK_ITEM_NOT_FOUND, BLOCK_NO_ROUTE, BLOCK_ORDER_TERMINATED,
        BLOCK_ORDER_DRAFT, BLOCK_ALL_DONE, BLOCK_NOT_ASSIGNED,
    }:
        return base

    my_processes = _user_process_ids(db, user_id)
    target = None
    for step in base.get("steps") or []:
        if step["process_id"] not in my_processes:
            continue
        progress = db.query(DomesticItemProgress).get(step["progress_id"])
        if unit_service.eligible_units(
            db, item, progress, limit=1, unit_id=unit.id,
        ):
            target = {**step, "reportable_qty": 1}
            break
    if target is None:
        return {
            **base,
            "can_submit": False,
            "block_reason": BLOCK_NOTHING_REPORTABLE,
            "block_message": f"单件 {unit_service.unit_display_code(item, unit.unit_no)} 的上一道还没完成，或你负责的工序已报过",
            "next_step": None,
        }
    return {
        **base,
        "can_submit": True,
        "block_reason": None,
        "block_message": None,
        "next_step": target,
    }


# ── 报工提交 ──────────────────────────────────────────


def _submit_report_once(
    db: Session,
    *,
    item_id: int,
    progress_id: int,
    qty: int,
    user_id: int,
    source: str = "mini",
    request_id: str | None = None,
    on_behalf_user_id: int | None = None,
    unit_id: int | None = None,
    outcomes: dict[str, int] | None = None,
) -> dict:
    """提交一次报工。数量守恒由「上游累计 − 本道累计」当场校验。

    并发：先锁明细行，把同一明细上的所有数量变更串行化；跨行读上游用锁定读
    （RR 隔离级别下普通读拿的是旧快照，见 progress_service._get_step）。

    幂等：带 request_id 时同一个 id 重复提交返回首次结果，不重复累加——
    车间弱网下"提交成功但响应丢了"是常态，工人再点一次不能变成报两次。
    """
    if qty <= 0:
        raise ValueError("报工数量必须大于 0")

    worker_id = on_behalf_user_id or user_id
    replay_outcomes = routing_service.normalize_replay_outcomes(outcomes)
    replay = _report_replay_if_exists(
        db, request_id=request_id, item_id=item_id, progress_id=progress_id,
        qty=qty, worker_id=worker_id, unit_id=unit_id, outcomes=replay_outcomes,
    )
    if replay:
        return replay

    preview_item = db.query(DomesticOrderItem).get(item_id)
    preview_progress = db.query(DomesticItemProgress).get(progress_id)
    preview_rule = None
    if preview_item and preview_progress and preview_item.route_id:
        preview_rule = routing_service.runtime_rule_map(db, preview_item.route_id).get(
            preview_progress.process_id
        )
    normalized_outcomes = routing_service.normalize_outcomes(
        preview_rule,
        outcomes,
        qty=qty,
        unit_mode=unit_id is not None,
    )
    order, item = _lock_order_then_item(db, item_id)

    # 首次快查可能在 MySQL RR 快照里看不到刚提交的并发请求。同一明细已由
    # item 行锁串行化，此处 locking read 必须重查一次再动累计数。
    replay = _report_replay_if_exists(
        db, request_id=request_id, item_id=item_id, progress_id=progress_id,
        qty=qty, worker_id=worker_id, unit_id=unit_id,
        outcomes=replay_outcomes, lock=True,
    )
    if replay:
        db.rollback()
        return replay

    _assert_order_reportable(order)

    progress = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.id == progress_id)
        .with_for_update()
        .first()
    )
    if not progress or progress.item_id != item_id:
        raise ValueError("工序进度不存在或与这张卡不匹配")

    # 代报工：件数记到实际做活的人头上，不是记到操作电脑的人头上（计件工资口径）
    if progress.process_id not in _user_process_ids(db, worker_id):
        who = "该工人" if on_behalf_user_id else "你"
        raise ValueError(f"{who}没有被分配到这道工序")

    rows = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.item_id == item.id)
        .order_by(DomesticItemProgress.step_order.asc())
        .with_for_update()
        .all()
    )
    unit_service.ensure_item_units(db, item)
    units = routing_service.active_units(db, item)
    state = routing_service.load_passage_state(db, item)
    rules = routing_service.runtime_rule_map(db, item.route_id)
    rule = rules.get(progress.process_id)
    normalized_outcomes = routing_service.normalize_outcomes(
        rule, outcomes, qty=qty, unit_mode=unit_id is not None,
    )
    candidates, bypassable = routing_service.ordered_report_candidates(
        item, progress, rows, state, units, rules,
    )
    available = len(candidates)
    if available <= 0:
        raise ValueError("上一道工序还没做出可接的数量")
    if qty > available:
        raise ValueError(f"最多还能报 {available} 件，本次填了 {qty} 件")
    if unit_id is not None:
        if qty != 1:
            raise ValueError("逐件扫码模式每次只能报 1 件")
        selected = next((unit for unit in candidates if unit.id == unit_id), None)
        if selected is None:
            unit = db.query(DomesticItemUnit).get(unit_id)
            if not unit or unit.item_id != item.id or unit.status != 1:
                raise ValueError("这个单件二维码不属于当前订单明细或已失效")
            if unit.id in state.passed(progress.id):
                raise ValueError(f"单件 {unit_service.unit_display_code(item, unit.unit_no)} 的这道工序已经报过")
            raise ValueError(f"单件 {unit_service.unit_display_code(item, unit.unit_no)} 的上一道工序还没完成")
        selected_units = [selected]
    else:
        selected_units = candidates[:qty]

    outcome_by_unit, assigned_by_code = routing_service.allocate_outcomes(
        selected_units, normalized_outcomes,
    )

    now = _bj_now()
    progress.completed_qty += qty
    progress.last_reported_at = now
    if progress.first_reported_at is None:
        progress.first_reported_at = now
    progress_service.sync_progress_row_status(progress, item.order_qty)

    worker = db.query(ArkUser).get(worker_id)
    log = DomesticReportLog(
        item_id=item.id,
        progress_id=progress.id,
        process_id=progress.process_id,
        step_order=progress.step_order,
        report_qty=qty,
        reported_by_user_id=worker_id,
        reported_by_name=getattr(worker, "real_name", None) or getattr(worker, "username", None),
        source=source,
        report_mode="unit" if unit_id is not None else "quantity",
        outcome_json=normalized_outcomes,
        request_id=request_id,
        reported_at=now,
        revoked=0,
    )
    db.add(log)
    db.flush()
    unit_service.add_report_units(
        db, log=log, units=selected_units, outcome_by_unit=outcome_by_unit,
    )
    if rule and rule["rule_type"] == route_rule_service.RULE_DECISION:
        routing_service.create_decision_skips(
            db,
            item=item,
            rows=rows,
            rule=rule,
            assigned_by_code=assigned_by_code,
            trigger_log=log,
            user_id=worker_id,
        )
    bypass_units = [unit for unit in selected_units if unit.id in bypassable]
    if bypass_units:
        previous = rows[rows.index(progress) - 1]
        routing_service.create_skip_log(
            db,
            item=item,
            progress=previous,
            units=bypass_units,
            source="optional_bypass",
            reason="下一道报工自动绕过可选工序",
            trigger_report_log_id=log.id,
            user_id=worker_id,
        )

    progress_service.sync_progress_statuses(db, item)
    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()

    process_name = db.query(Process.name).filter(Process.id == progress.process_id).scalar()
    return {
        "log_id": log.id,
        "item_id": item.id,
        "process_name": process_name,
        "step_order": progress.step_order,
        "reported_qty": qty,
        "step_completed_qty": progress.completed_qty,
        "order_qty": item.order_qty,
        "step_finished": progress.status == 1,
        "item_finished": item.status >= C.ITEM_DONE,
        "reported_at": now,
        "unit_ids": [unit.id for unit in selected_units],
        "unit_codes": [unit_service.unit_display_code(item, unit.unit_no) for unit in selected_units],
        "outcomes": normalized_outcomes,
        "unit_outcomes": [
            {"unit_id": unit.id, "outcome_code": outcome_by_unit.get(unit.id)}
            for unit in selected_units
        ],
    }


def submit_report(
    db: Session,
    *,
    item_id: int,
    progress_id: int,
    qty: int,
    user_id: int,
    source: str = "mini",
    request_id: str | None = None,
    on_behalf_user_id: int | None = None,
    unit_id: int | None = None,
    outcomes: dict[str, int] | None = None,
) -> dict:
    try:
        return _submit_report_once(
            db,
            item_id=item_id,
            progress_id=progress_id,
            qty=qty,
            user_id=user_id,
            source=source,
            request_id=request_id,
            on_behalf_user_id=on_behalf_user_id,
            unit_id=unit_id,
            outcomes=outcomes,
        )
    except (IntegrityError, OperationalError) as exc:
        recoverable = (
            isinstance(exc, IntegrityError)
            and _is_target_request_unique_error(exc, target="report")
        ) or (
            isinstance(exc, OperationalError) and _is_mysql_deadlock(exc)
        )
        if not request_id or not recoverable:
            raise
        db.rollback()
        replay = _report_replay_if_exists(
            db,
            request_id=request_id,
            item_id=item_id,
            progress_id=progress_id,
            qty=qty,
            worker_id=on_behalf_user_id or user_id,
            unit_id=unit_id,
            outcomes=routing_service.normalize_replay_outcomes(outcomes),
        )
        if replay:
            return replay
        raise ValueError("该报工请求正在并发处理，请使用同一请求号重试") from None


def _manual_skip_result(
    db: Session,
    skip_log: DomesticSkipLog,
    item: DomesticOrderItem,
    *,
    replayed: bool = False,
) -> dict:
    units = routing_service.skip_units(db, skip_log.id)
    process_name = db.query(Process.name).join(
        DomesticItemProgress,
        DomesticItemProgress.process_id == Process.id,
    ).filter(DomesticItemProgress.id == skip_log.progress_id).scalar()
    return {
        "skip_log_id": skip_log.id,
        "item_id": skip_log.item_id,
        "progress_id": skip_log.progress_id,
        "process_name": process_name,
        "skipped_qty": skip_log.skip_qty,
        "skip_mode": skip_log.skip_mode,
        "reason": skip_log.reason,
        "unit_ids": [unit.id for unit in units],
        "unit_codes": [unit_service.unit_display_code(item, unit.unit_no) for unit in units],
        "created_at": skip_log.created_at,
        "revoked": bool(skip_log.revoked),
        "revoked_at": skip_log.revoked_at,
        "replayed": replayed,
    }


def _validate_manual_skip_input(
    *,
    qty: int | None,
    unit_id: int | None,
    reason: str,
    request_id: str,
) -> tuple[int, str, str]:
    clean_reason = (reason or "").strip()
    clean_request_id = (request_id or "").strip()
    if not 5 <= len(clean_reason) <= 500:
        raise ValueError("跳过原因去除首尾空格后必须为 5 到 500 个字符")
    if not 8 <= len(clean_request_id) <= 64:
        raise ValueError("人工跳过必须提供 8 到 64 个字符的请求号")
    if unit_id is None:
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError("数量跳过必须填写大于 0 的数量")
        normalized_qty = qty
    else:
        if isinstance(unit_id, bool) or not isinstance(unit_id, int) or unit_id <= 0:
            raise ValueError("单件 ID 不合法")
        if qty is not None:
            raise ValueError("数量和单件二维码只能选择一种跳过方式")
        normalized_qty = 1
    return normalized_qty, clean_reason, clean_request_id


def _manual_skip_replay_if_exists(
    db: Session,
    *,
    request_id: str,
    item_id: int,
    progress_id: int,
    normalized_qty: int,
    skip_mode: str,
    reason: str,
    user_id: int,
    unit_id: int | None,
    item: DomesticOrderItem | None = None,
    lock: bool = False,
) -> dict | None:
    query = db.query(DomesticSkipLog).filter(
        DomesticSkipLog.request_id == request_id,
    )
    if lock:
        query = query.with_for_update()
    existing = query.first()
    if not existing:
        return None
    existing_units = routing_service.skip_units(db, existing.id)
    same_request = (
        existing.source == "manual"
        and existing.item_id == item_id
        and existing.progress_id == progress_id
        and existing.skip_qty == normalized_qty
        and existing.skip_mode == skip_mode
        and existing.reason == reason
        and existing.created_by_user_id == user_id
        and (
            (unit_id is None and len(existing_units) == normalized_qty)
            or (
                unit_id is not None
                and len(existing_units) == 1
                and existing_units[0].id == unit_id
            )
        )
    )
    if not same_request:
        raise ValueError("该请求号已用于另一笔跳过，请重新操作")
    replay_item = item if item and item.id == existing.item_id else db.get(
        DomesticOrderItem, existing.item_id,
    )
    if not replay_item:
        raise ValueError("订单明细不存在")
    return _manual_skip_result(db, existing, replay_item, replayed=True)


def _submit_manual_skip_once(
    db: Session,
    *,
    item_id: int,
    progress_id: int,
    qty: int | None,
    unit_id: int | None,
    reason: str,
    request_id: str,
    user_id: int,
) -> dict:
    """主管人工放行；只写跳过审计，不生成报工和计件工作量。"""
    normalized_qty, clean_reason, clean_request_id = _validate_manual_skip_input(
        qty=qty, unit_id=unit_id, reason=reason, request_id=request_id,
    )
    skip_mode = "unit" if unit_id is not None else "quantity"

    order, item = _lock_order_then_item(db, item_id)

    replay = _manual_skip_replay_if_exists(
        db,
        request_id=clean_request_id,
        item_id=item_id,
        progress_id=progress_id,
        normalized_qty=normalized_qty,
        skip_mode=skip_mode,
        reason=clean_reason,
        user_id=user_id,
        unit_id=unit_id,
        item=item,
        lock=True,
    )
    if replay:
        db.rollback()
        return replay

    if item.status == C.ITEM_SHIPPED:
        raise ValueError("该明细已发货，不能跳过工序")
    _assert_order_reportable(order)

    progress = db.query(DomesticItemProgress).filter(
        DomesticItemProgress.id == progress_id,
    ).with_for_update().first()
    if not progress or progress.item_id != item.id:
        raise ValueError("工序进度不存在或与该订单明细不匹配")

    rows = db.query(DomesticItemProgress).filter(
        DomesticItemProgress.item_id == item.id,
    ).order_by(DomesticItemProgress.step_order.asc()).with_for_update().all()
    unit_service.ensure_item_units(db, item)
    units = routing_service.active_units(db, item)
    state = routing_service.load_passage_state(db, item)
    rules = routing_service.runtime_rule_map(db, item.route_id)
    eligible_ids = routing_service.eligible_unit_ids(
        item, progress, rows, state, {unit.id for unit in units}, rules,
    )
    eligible_units = [unit for unit in units if unit.id in eligible_ids]

    if unit_id is not None:
        selected = next((unit for unit in eligible_units if unit.id == unit_id), None)
        if selected is None:
            unit = db.query(DomesticItemUnit).filter(
                DomesticItemUnit.id == unit_id,
            ).first()
            if not unit or unit.item_id != item.id or unit.status != 1:
                raise ValueError("这个单件二维码不属于当前订单明细或已失效")
            raise ValueError(
                f"单件 {unit_service.unit_display_code(item, unit.unit_no)} 当前不能跳过这道工序"
            )
        selected_units = [selected]
    else:
        if normalized_qty > len(eligible_units):
            raise ValueError(
                f"当前最多只能跳过 {len(eligible_units)} 件，本次填了 {normalized_qty} 件"
            )
        selected_units = eligible_units[:normalized_qty]

    skip_log = routing_service.create_skip_log(
        db,
        item=item,
        progress=progress,
        units=selected_units,
        source="manual",
        reason=clean_reason,
        trigger_report_log_id=None,
        user_id=user_id,
        skip_mode=skip_mode,
        request_id=clean_request_id,
    )
    if not skip_log:
        raise ValueError("当前没有可跳过的单件")
    progress_service.sync_progress_statuses(db, item)
    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return _manual_skip_result(db, skip_log, item)


def submit_manual_skip(
    db: Session,
    *,
    item_id: int,
    progress_id: int,
    qty: int | None,
    unit_id: int | None,
    reason: str,
    request_id: str,
    user_id: int,
) -> dict:
    try:
        return _submit_manual_skip_once(
            db,
            item_id=item_id,
            progress_id=progress_id,
            qty=qty,
            unit_id=unit_id,
            reason=reason,
            request_id=request_id,
            user_id=user_id,
        )
    except (IntegrityError, OperationalError) as exc:
        recoverable = (
            isinstance(exc, IntegrityError)
            and _is_target_request_unique_error(exc, target="skip")
        ) or (
            isinstance(exc, OperationalError) and _is_mysql_deadlock(exc)
        )
        if not recoverable:
            raise
        db.rollback()
        normalized_qty, clean_reason, clean_request_id = _validate_manual_skip_input(
            qty=qty, unit_id=unit_id, reason=reason, request_id=request_id,
        )
        replay = _manual_skip_replay_if_exists(
            db,
            request_id=clean_request_id,
            item_id=item_id,
            progress_id=progress_id,
            normalized_qty=normalized_qty,
            skip_mode="unit" if unit_id is not None else "quantity",
            reason=clean_reason,
            user_id=user_id,
            unit_id=unit_id,
        )
        if replay:
            return replay
        raise ValueError("该跳过请求正在并发处理，请使用同一请求号重试") from None


def revoke_manual_skip(db: Session, skip_log_id: int, user_id: int) -> dict:
    """撤销人工放行；路由层仅向 domestic:admin 暴露。"""
    preview = db.query(DomesticSkipLog.item_id).filter(
        DomesticSkipLog.id == skip_log_id,
    ).first()
    if not preview:
        raise ValueError("跳过记录不存在")
    order, item = _lock_order_then_item(db, preview[0])
    if item.status == C.ITEM_SHIPPED:
        raise ValueError("该明细已发货，不能撤销跳过")

    skip_log = db.query(DomesticSkipLog).filter(
        DomesticSkipLog.id == skip_log_id,
    ).populate_existing().with_for_update().first()
    if not skip_log or skip_log.item_id != item.id:
        raise ValueError("跳过记录不存在")
    if skip_log.source != "manual":
        raise ValueError("只有人工跳过记录可以单独撤销")
    if skip_log.revoked:
        raise ValueError("这条跳过记录已经撤销过了")

    progress = db.query(DomesticItemProgress).filter(
        DomesticItemProgress.id == skip_log.progress_id,
    ).with_for_update().first()
    if not progress:
        raise ValueError("工序进度不存在")
    units = routing_service.skip_units(db, skip_log.id)
    routing_service.assert_no_downstream_actual_work(
        db,
        item=item,
        step_order=progress.step_order,
        unit_ids={unit.id for unit in units},
    )
    skip_log.revoked = 1
    skip_log.revoked_at = _bj_now()
    progress_service.sync_progress_statuses(db, item)
    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return {
        "skip_log_id": skip_log.id,
        "item_id": item.id,
        "revoked_qty": skip_log.skip_qty,
    }


def revoke_report(db: Session, log_id: int, user_id: int, is_admin: bool = False) -> dict:
    """撤销一条报工流水。

    只能撤自己的（管理员例外）；任一具体单件已有更后工序的实际报工时阻断。
    """
    preview = db.query(DomesticReportLog.item_id).filter(
        DomesticReportLog.id == log_id,
    ).first()
    if not preview:
        raise ValueError("报工记录不存在")
    order, item = _lock_order_then_item(db, preview[0])
    if item.status == C.ITEM_SHIPPED:
        raise ValueError("该明细已发货，不能撤销报工")

    log = db.query(DomesticReportLog).filter(
        DomesticReportLog.id == log_id,
    ).populate_existing().with_for_update().first()
    if not log or log.item_id != item.id:
        raise ValueError("报工记录不存在")
    if log.revoked:
        raise ValueError("这条记录已经撤销过了")
    if log.reported_by_user_id != user_id and not is_admin:
        raise ValueError("只能撤销自己的报工记录")
    triggered_skips = routing_service.lock_triggered_skips(
        db, trigger_report_log_id=log.id,
    )

    progress = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.id == log.progress_id)
        .with_for_update()
        .first()
    )
    if not progress:
        raise ValueError("工序进度不存在")

    units = unit_service.units_for_log(db, log.id)
    routing_service.assert_no_downstream_actual_work(
        db,
        item=item,
        step_order=progress.step_order,
        unit_ids={unit.id for unit in units},
    )
    unit_service.assert_quantity_log_is_current_tail(db, log=log, item=item)

    remaining = progress.completed_qty - log.report_qty
    now = _bj_now()
    log.revoked = 1
    log.revoked_at = now
    revoked_skip_ids = routing_service.revoke_locked_skips(
        triggered_skips, revoked_at=now,
    )
    progress.completed_qty = remaining
    progress_service.sync_progress_statuses(db, item)
    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return {
        "log_id": log.id,
        "item_id": item.id,
        "step_completed_qty": progress.completed_qty,
        "revoked_qty": log.report_qty,
        "revoked_skip_log_ids": revoked_skip_ids,
    }


# ── 报工记录查询 ──────────────────────────────────────


def _log_rows_to_view(db: Session, logs: list[DomesticReportLog]) -> list[dict]:
    if not logs:
        return []
    item_ids = {log.item_id for log in logs}
    items = {
        i.id: i for i in db.query(DomesticOrderItem).filter(DomesticOrderItem.id.in_(item_ids)).all()
    }
    order_ids = {i.order_id for i in items.values()}
    orders = {
        o.id: o for o in db.query(DomesticOrder).filter(DomesticOrder.id.in_(order_ids or {0})).all()
    }
    from app.domestic.order_service import dimension_label_maps, order_dimension_view

    resolved_dimension_labels = dimension_label_maps(db, list(orders.values()))
    process_names = dict(
        db.query(Process.id, Process.name).filter(Process.id.in_({log.process_id for log in logs})).all()
    )
    unit_rows = db.query(
        DomesticReportUnit.log_id,
        DomesticItemUnit.unit_no,
    ).join(
        DomesticItemUnit, DomesticItemUnit.id == DomesticReportUnit.unit_id
    ).filter(DomesticReportUnit.log_id.in_({log.id for log in logs})).order_by(
        DomesticReportUnit.log_id.asc(), DomesticItemUnit.unit_no.asc()
    ).all()
    units_by_log: dict[int, list[int]] = {}
    for log_id, unit_no in unit_rows:
        units_by_log.setdefault(log_id, []).append(unit_no)
    view = []
    for log in logs:
        item = items.get(log.item_id)
        order = orders.get(item.order_id) if item else None
        unit_nos = units_by_log.get(log.id, [])
        view.append({
            "log_id": log.id,
            "item_id": log.item_id,
            "product_name": item.product_name if item else None,
            "domestic_no": order.domestic_no if order else None,
            "order_no": order.order_no if order else None,
            **(
                order_dimension_view(db, order, resolved_dimension_labels)
                if order else {
                    "order_category": None,
                    "order_category_label": "未填写",
                    "order_type": None,
                    "order_type_label": "未填写",
                    "order_channel": None,
                    "order_channel_label": "未填写",
                }
            ),
            "process_id": log.process_id,
            "process_name": process_names.get(log.process_id),
            "step_order": log.step_order,
            "report_qty": log.report_qty,
            "unit_codes": [
                unit_service.unit_display_code(item, unit_no) for unit_no in unit_nos
            ] if item else [],
            "reported_by_name": log.reported_by_name,
            "reported_at": log.reported_at,
            "revoked": log.revoked,
        })
    return view


def list_today_reports(db: Session, user_id: int) -> list[dict]:
    """当天本人报工记录（小程序首页），含已撤销的以便工人确认撤销生效。"""
    start = _bj_now().replace(hour=0, minute=0, second=0, microsecond=0)
    logs = (
        db.query(DomesticReportLog)
        .filter(
            DomesticReportLog.reported_by_user_id == user_id,
            DomesticReportLog.reported_at >= start,
        )
        .order_by(DomesticReportLog.id.desc())
        .all()
    )
    return _log_rows_to_view(db, logs)


def list_manual_skip_audits(db: Session, *, item_id: int) -> list[dict]:
    """返回某明细的人工跳过审计，自动分流/可选跳过不属于人工审计。"""
    item = db.get(DomesticOrderItem, item_id)
    if not item:
        raise ValueError("订单明细不存在")

    rows = (
        db.query(
            DomesticSkipLog,
            DomesticItemProgress.process_id,
            Process.name,
            ArkUser.real_name,
        )
        .join(
            DomesticItemProgress,
            DomesticItemProgress.id == DomesticSkipLog.progress_id,
        )
        .join(Process, Process.id == DomesticItemProgress.process_id)
        .join(ArkUser, ArkUser.id == DomesticSkipLog.created_by_user_id)
        .filter(
            DomesticSkipLog.item_id == item_id,
            DomesticSkipLog.source == "manual",
        )
        .order_by(DomesticSkipLog.created_at.desc(), DomesticSkipLog.id.desc())
        .all()
    )
    if not rows:
        return []

    log_ids = [log.id for log, _process_id, _process_name, _operator_name in rows]
    unit_rows = (
        db.query(
            DomesticSkipUnit.skip_log_id,
            DomesticItemUnit.id,
            DomesticItemUnit.unit_no,
        )
        .join(DomesticItemUnit, DomesticItemUnit.id == DomesticSkipUnit.unit_id)
        .filter(DomesticSkipUnit.skip_log_id.in_(log_ids))
        .order_by(DomesticSkipUnit.skip_log_id.asc(), DomesticItemUnit.unit_no.asc())
        .all()
    )
    units_by_log: dict[int, list[tuple[int, int]]] = {}
    for skip_log_id, unit_id, unit_no in unit_rows:
        units_by_log.setdefault(skip_log_id, []).append((unit_id, unit_no))

    result = []
    for log, process_id, process_name, operator_name in rows:
        units = units_by_log.get(log.id, [])
        result.append({
            "skip_log_id": log.id,
            "item_id": log.item_id,
            "progress_id": log.progress_id,
            "process_id": process_id,
            "process_name": process_name,
            "skip_mode": log.skip_mode,
            "skipped_qty": log.skip_qty,
            "reason": log.reason,
            "request_id": log.request_id,
            "operator_id": log.created_by_user_id,
            "operator_name": operator_name,
            "unit_ids": [unit_id for unit_id, _unit_no in units],
            "unit_codes": [
                unit_service.unit_display_code(item, unit_no)
                for _unit_id, unit_no in units
            ],
            "created_at": log.created_at,
            "revoked": bool(log.revoked),
            "revoked_at": log.revoked_at,
        })
    return result


def list_reports(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    user_id: int | None = None,
    item_id: int | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    include_revoked: bool = True,
) -> tuple[list[dict], int]:
    q = db.query(DomesticReportLog)
    if user_id:
        q = q.filter(DomesticReportLog.reported_by_user_id == user_id)
    if item_id:
        q = q.filter(DomesticReportLog.item_id == item_id)
    if date_start:
        q = q.filter(DomesticReportLog.reported_at >= date_start)
    if date_end:
        q = q.filter(DomesticReportLog.reported_at <= date_end)
    if not include_revoked:
        q = q.filter(DomesticReportLog.revoked == 0)

    total = q.count()
    logs = q.order_by(DomesticReportLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return _log_rows_to_view(db, logs), total


def get_workload_summary(db: Session, *, date_start: datetime, date_end: datetime) -> list[dict]:
    """按人×工序汇总有效报工数量（计件统计的基础）。"""
    rows = (
        db.query(
            DomesticReportLog.reported_by_user_id,
            DomesticReportLog.reported_by_name,
            DomesticReportLog.process_id,
            func.sum(DomesticReportLog.report_qty),
            func.count(DomesticReportLog.id),
        )
        .filter(
            DomesticReportLog.revoked == 0,
            DomesticReportLog.reported_at >= date_start,
            DomesticReportLog.reported_at <= date_end,
        )
        .group_by(
            DomesticReportLog.reported_by_user_id,
            DomesticReportLog.reported_by_name,
            DomesticReportLog.process_id,
        )
        .all()
    )
    process_names = dict(db.query(Process.id, Process.name).all())
    return [{
        "user_id": uid,
        "user_name": name,
        "process_id": pid,
        "process_name": process_names.get(pid),
        "total_qty": int(total or 0),
        "report_count": cnt,
    } for uid, name, pid, total, cnt in rows]
