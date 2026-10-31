"""收货回访扫描、回访过期、草稿清理（规格 4.4，决策 1）。由 02:10 维护任务在线程池调用。"""
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic.shipment_models import DomesticShipment, DomesticShipmentLine
from app.domestic_followup import config_service, task_service
from app.domestic_followup.constants import CLOSE_EXPIRED, DRAFT_TTL_DAYS, RECEIPT_EXPIRE_AFTER_DAYS
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupTask, DomesticFollowupTaskShipment

logger = logging.getLogger("commission")


def _active(db: Session, user_id: int | None) -> int | None:
    if not user_id:
        return None
    row = db.query(ArkUser.id).filter(ArkUser.id == user_id, ArkUser.is_active.is_(True),
                                      ArkUser.deleted_at.is_(None)).first()
    return row[0] if row else None


def _launch_date(db: Session, today: date) -> date:
    value = config_service.get_config(db)["receipt_launch_date"]
    if value:
        return date.fromisoformat(value)
    # 首次扫描在部署次日 02:10 跑：记成「今天 − 1」，部署当天白天的发货也能生成回访，更早的历史不补
    launch = today - timedelta(days=1)
    config_service.update_config(db, {"receipt_launch_date": launch.isoformat()}, None, commit=False)
    return launch


def scan(db: Session, *, today: date | None = None) -> int:
    """为到期的发货批次生成收货回访任务，返回新建任务数。调用方负责 commit。"""
    today = today or beijing_today()
    delay = config_service.get_config(db)["receipt_delay_days"]
    fallback = config_service.get_config(db)["fallback_assignee_user_id"]
    # 超过回访过期窗口的批次不再补建（例如刚配好兜底人时），免得一次冒出一批已过期的待办
    window_start = today - timedelta(days=delay + RECEIPT_EXPIRE_AFTER_DAYS)
    start = datetime.combine(max(_launch_date(db, today), window_start), time.min)
    end = datetime.combine(today - timedelta(days=delay - 1), time.min)
    if end <= start:
        return 0
    linked = select(DomesticFollowupTaskShipment.shipment_id)
    shipments = (db.query(DomesticShipment)
                 .filter(DomesticShipment.ship_time >= start, DomesticShipment.ship_time < end,
                         DomesticShipment.cancelled_at.is_(None), DomesticShipment.id.not_in(linked))
                 .order_by(DomesticShipment.ship_time, DomesticShipment.id).all())
    if not shipments:
        return 0
    quantities = dict(db.query(DomesticShipmentLine.shipment_id, func.sum(DomesticShipmentLine.quantity))
                      .filter(DomesticShipmentLine.shipment_id.in_([s.id for s in shipments]))
                      .group_by(DomesticShipmentLine.shipment_id).all())
    groups: dict[tuple[int, date], list[DomesticShipment]] = defaultdict(list)
    for shipment in shipments:
        groups[(shipment.customer_id, shipment.ship_time.date())].append(shipment)

    created = 0
    for (customer_id, ship_date), batch in groups.items():
        customer = db.get(DomesticCustomer, customer_id)
        assignee = (_active(db, customer.owner_user_id if customer else None)
                    or _active(db, batch[0].created_by) or _active(db, fallback))
        if assignee is None:
            logger.warning("receipt task skipped customer=%s: no active assignee", customer_id)
            print(f"[domestic_followup] receipt skipped customer={customer_id}: no active assignee", flush=True)
            continue
        qty = sum(int(quantities.get(s.id) or 0) for s in batch)
        savepoint = db.begin_nested()
        try:
            task, is_new = task_service.upsert_task(
                db, source_key=f"receipt:{customer_id}:{ship_date.isoformat()}:{min(s.id for s in batch)}",
                task_type="receipt", customer_id=customer_id, assignee_user_id=assignee,
                title=f"{customer.shop_name if customer else customer_id}：收货回访（{ship_date.month}/{ship_date.day} 发货 {len(batch)} 批 {qty} 件）",
                due_date=ship_date + timedelta(days=delay),
                payload={"ship_date": ship_date.isoformat(), "shipments": [
                    {"id": s.id, "shipment_no": s.shipment_no, "quantity": int(quantities.get(s.id) or 0)}
                    for s in batch]},
            )
            for shipment in batch:
                db.add(DomesticFollowupTaskShipment(task_id=task.id, shipment_id=shipment.id))
            db.flush()
            savepoint.commit()
            created += int(is_new)
        except Exception as exc:  # noqa: BLE001 — 单组失败（含并发撞唯一键）不影响其他组
            savepoint.rollback()
            logger.warning("receipt task failed customer=%s date=%s: %s: %s", customer_id, ship_date,
                           type(exc).__name__, str(exc)[:200])
            print(f"[domestic_followup] receipt task failed customer={customer_id} date={ship_date}: "
                  f"{type(exc).__name__}: {str(exc)[:200]}", flush=True)
    return created


def expire_tasks(db: Session, *, today: date | None = None) -> int:
    """带条件的 UPDATE：WHERE status='todo' 在写入时才判断，用户刚完成的回访不会被覆盖成过期。"""
    cutoff = (today or beijing_today()) - timedelta(days=RECEIPT_EXPIRE_AFTER_DAYS)
    Task = DomesticFollowupTask
    now = beijing_now()
    result = db.execute(
        update(Task)
        .where(Task.task_type == "receipt", Task.status == "todo", Task.due_date < cutoff)
        .values(status="expired", closed_reason=CLOSE_EXPIRED, closed_at=now, updated_at=now)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount


def cleanup_drafts(db: Session, *, now: datetime | None = None) -> int:
    """带条件的 UPDATE：WHERE status='draft' 在写入时才判断，业务员刚确认的草稿不会被作废。"""
    cutoff = (now or beijing_now()) - timedelta(days=DRAFT_TTL_DAYS)
    result = db.execute(
        update(DomesticFollowup)
        .where(DomesticFollowup.status == "draft", DomesticFollowup.created_at < cutoff)
        .values(status="discarded", version=DomesticFollowup.version + 1, updated_at=beijing_now())
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount
