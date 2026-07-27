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
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.domestic import constants as C
from app.domestic import progress_service
from app.domestic.models import (
    DomesticCustomer,
    DomesticItemProgress,
    DomesticOrder,
    DomesticOrderItem,
    DomesticReportLog,
)
from app.production.models import Process, UserProcessBinding

logger = logging.getLogger("commission")
settings = get_settings()

_BJ_TZ = timezone(timedelta(hours=8))


def _bj_now() -> datetime:
    """北京时间，与外贸报工口径一致（存 naive datetime）"""
    return datetime.now(_BJ_TZ).replace(tzinfo=None)


# ── 二维码 ────────────────────────────────────────────


def generate_qr_sign(item_id: int, secret: str) -> str:
    message = f"{C.QR_PREFIX}:{item_id}"
    return hmac.new(key=secret.encode(), msg=message.encode(), digestmod=hashlib.sha256).hexdigest()[:8]


def generate_qr_data(item_id: int) -> str:
    return f"{C.QR_PREFIX}:{item_id}:{generate_qr_sign(item_id, settings.QR_SIGN_SECRET)}"


def verify_qr_data(qr_data: str) -> tuple[bool, int]:
    """校验内贸二维码，返回 (是否有效, item_id)。外贸的 ARK-P 码在这里一律无效。"""
    match = re.match(rf"^{C.QR_PREFIX}:(\d+):([a-f0-9]{{8}})$", qr_data or "")
    if not match:
        return False, 0
    item_id = int(match.group(1))
    expected = generate_qr_sign(item_id, settings.QR_SIGN_SECRET)
    return hmac.compare_digest(match.group(2), expected), item_id


# ── 扫码：工人看到什么 ────────────────────────────────


BLOCK_ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
BLOCK_NO_ROUTE = "NO_ROUTE"
BLOCK_ORDER_TERMINATED = "ORDER_TERMINATED"
BLOCK_ALL_DONE = "ALL_DONE"
BLOCK_NOT_ASSIGNED = "NOT_ASSIGNED"
BLOCK_NOTHING_REPORTABLE = "NOTHING_REPORTABLE"

BLOCK_MESSAGES = {
    BLOCK_ITEM_NOT_FOUND: "找不到这张卡对应的订单明细",
    BLOCK_NO_ROUTE: "这个产品还没配工艺路线，请联系跟单",
    BLOCK_ORDER_TERMINATED: "订单已终止，不能报工",
    BLOCK_ALL_DONE: "这批货所有工序都做完了",
    BLOCK_NOT_ASSIGNED: "你没有被分配到这道工序",
    BLOCK_NOTHING_REPORTABLE: "上一道工序还没做出可接的数量，请稍后再扫",
}


def _user_process_ids(db: Session, user_id: int) -> set[int]:
    return {
        pid for (pid,) in db.query(UserProcessBinding.process_id)
        .filter(UserProcessBinding.user_id == user_id).all()
    }


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

    base = {
        "item_id": item.id,
        "order_id": item.order_id,
        "domestic_no": order.domestic_no if order else None,
        "order_no": order.order_no if order else None,
        "customer_name": customer.shop_name if customer else None,
        "product_name": item.product_name,
        "attrs": item.attrs_snapshot or {},
        "order_qty": item.order_qty,
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

    if order and order.status == C.ORDER_TERMINATED:
        return blocked(BLOCK_ORDER_TERMINATED)
    if not steps:
        return blocked(BLOCK_NO_ROUTE)
    if all(s["completed_qty"] >= item.order_qty for s in steps):
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


# ── 报工提交 ──────────────────────────────────────────


def submit_report(
    db: Session,
    *,
    item_id: int,
    progress_id: int,
    qty: int,
    user_id: int,
    source: str = "mini",
) -> dict:
    """提交一次报工。数量守恒由「上游累计 − 本道累计」当场校验。

    并发用行锁：同一道工序两人同时报，后到者读到的是前者提交后的累计数，
    不会双写超发。计件数量算错比慢一点严重，所以用悲观锁而非乐观重试。
    """
    if qty <= 0:
        raise ValueError("报工数量必须大于 0")

    progress = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.id == progress_id)
        .with_for_update()
        .first()
    )
    if not progress or progress.item_id != item_id:
        raise ValueError("工序进度不存在或与这张卡不匹配")

    item = db.query(DomesticOrderItem).filter(DomesticOrderItem.id == item_id).with_for_update().first()
    if not item:
        raise ValueError("订单明细不存在")

    order = db.query(DomesticOrder).get(item.order_id)
    if order and order.status == C.ORDER_TERMINATED:
        raise ValueError("订单已终止，不能报工")

    if progress.process_id not in _user_process_ids(db, user_id):
        raise ValueError("你没有被分配到这道工序")

    available = progress_service.reportable_qty(db, progress, item)
    if available <= 0:
        raise ValueError("上一道工序还没做出可接的数量")
    if qty > available:
        raise ValueError(f"最多还能报 {available} 件，本次填了 {qty} 件")

    now = _bj_now()
    progress.completed_qty += qty
    progress.last_reported_at = now
    if progress.first_reported_at is None:
        progress.first_reported_at = now
    progress_service.sync_progress_row_status(progress, item.order_qty)

    user = db.query(ArkUser).get(user_id)
    log = DomesticReportLog(
        item_id=item.id,
        progress_id=progress.id,
        process_id=progress.process_id,
        step_order=progress.step_order,
        report_qty=qty,
        reported_by_user_id=user_id,
        reported_by_name=getattr(user, "real_name", None) or getattr(user, "username", None),
        source=source,
        reported_at=now,
        revoked=0,
    )
    db.add(log)
    db.flush()

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
    }


def revoke_report(db: Session, log_id: int, user_id: int, is_admin: bool = False) -> dict:
    """撤销一条报工流水。

    只能撤自己的（管理员例外）；撤销后本道累计不能低于下一道已完成的数量——
    否则下游就凭空多出了上游没交付的货。
    """
    log = db.query(DomesticReportLog).filter(DomesticReportLog.id == log_id).with_for_update().first()
    if not log:
        raise ValueError("报工记录不存在")
    if log.revoked:
        raise ValueError("这条记录已经撤销过了")
    if log.reported_by_user_id != user_id and not is_admin:
        raise ValueError("只能撤销自己的报工记录")

    progress = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.id == log.progress_id)
        .with_for_update()
        .first()
    )
    if not progress:
        raise ValueError("工序进度不存在")

    item = db.query(DomesticOrderItem).filter(DomesticOrderItem.id == log.item_id).with_for_update().first()
    if not item:
        raise ValueError("订单明细不存在")
    if item.status == C.ITEM_SHIPPED:
        raise ValueError("该明细已发货，不能撤销报工")

    remaining = progress.completed_qty - log.report_qty
    downstream = progress_service.downstream_completed_qty(db, item.id, progress.step_order)
    if remaining < downstream:
        raise ValueError(
            f"下一道工序已经做了 {downstream} 件，撤销后本道只剩 {remaining} 件，数量对不上；"
            "请先撤销下一道的报工"
        )

    log.revoked = 1
    log.revoked_at = _bj_now()
    progress.completed_qty = remaining
    progress_service.sync_progress_row_status(progress, item.order_qty)

    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return {
        "log_id": log.id,
        "item_id": item.id,
        "step_completed_qty": progress.completed_qty,
        "revoked_qty": log.report_qty,
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
    process_names = dict(
        db.query(Process.id, Process.name).filter(Process.id.in_({log.process_id for log in logs})).all()
    )
    view = []
    for log in logs:
        item = items.get(log.item_id)
        order = orders.get(item.order_id) if item else None
        view.append({
            "log_id": log.id,
            "item_id": log.item_id,
            "product_name": item.product_name if item else None,
            "domestic_no": order.domestic_no if order else None,
            "order_no": order.order_no if order else None,
            "process_id": log.process_id,
            "process_name": process_names.get(log.process_id),
            "step_order": log.step_order,
            "report_qty": log.report_qty,
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
