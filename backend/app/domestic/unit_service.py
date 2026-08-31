"""内贸订单逐件实体与报工流水映射。

累计数量仍是工序看板的快速口径；本模块记录这 N 件具体是哪 N 个二维码。
批量报工永远按 unit_no 从小到大挑选可流转单件，逐件扫码则只挑码指向的那一件。
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domestic.models import (
    DomesticItemProgress,
    DomesticItemUnit,
    DomesticOrder,
    DomesticOrderItem,
    DomesticReportLog,
    DomesticReportUnit,
)


def unit_display_code(item: DomesticOrderItem, unit_no: int) -> str:
    # 宽度不能取当前 order_qty：99 件增到 100 件时，已打印的
    # A1-01 不能突然变成 A1-001。两位是最小宽度，100 以上自然扩展。
    return f"A{item.line_no or 1}-{unit_no:02d}"


def ensure_item_line_no(db: Session, item: DomesticOrderItem) -> int:
    """兼容迁移前异常数据：用订单序号计数器在订单锁内补号。"""
    if item.line_no is not None:
        return item.line_no
    order = db.query(DomesticOrder).filter(
        DomesticOrder.id == item.order_id
    ).populate_existing().with_for_update().one()
    locked_item = db.query(DomesticOrderItem).filter(
        DomesticOrderItem.id == item.id
    ).populate_existing().with_for_update().one()
    if locked_item.line_no is not None:
        return locked_item.line_no
    locked_item.line_no = order.next_line_no or 1
    order.next_line_no = locked_item.line_no + 1
    db.flush()
    return locked_item.line_no


def ensure_item_units(db: Session, item: DomesticOrderItem) -> list[DomesticItemUnit]:
    ensure_item_line_no(db, item)
    sync_item_units(db, item, item.order_qty)
    return db.query(DomesticItemUnit).filter(
        DomesticItemUnit.item_id == item.id,
        DomesticItemUnit.status == 1,
    ).order_by(DomesticItemUnit.unit_no.asc()).all()


def _ensure_units_materialized(db: Session, item: DomesticOrderItem) -> None:
    """Fast-path normal scans without hydrating every unit ORM row."""
    count, maximum = db.query(
        func.count(DomesticItemUnit.id), func.max(DomesticItemUnit.unit_no),
    ).filter(
        DomesticItemUnit.item_id == item.id,
        DomesticItemUnit.status == 1,
    ).one()
    if int(count or 0) != item.order_qty or int(maximum or 0) != item.order_qty:
        sync_item_units(db, item, item.order_qty)


def sync_item_units(db: Session, item: DomesticOrderItem, new_qty: int) -> None:
    """Create/reactivate/deactivate unit rows to match quantity.

    Rows with audit history are never deleted. Reducing quantity is rejected when a unit
    above the new ceiling has an effective report at any process.
    """
    units = db.query(DomesticItemUnit).filter(
        DomesticItemUnit.item_id == item.id
    ).order_by(DomesticItemUnit.unit_no.asc()).all()
    by_no = {unit.unit_no: unit for unit in units}

    surplus_ids = [unit.id for unit in units if unit.unit_no > new_qty]
    if surplus_ids:
        active = db.query(DomesticReportUnit.unit_id).join(
            DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id
        ).filter(
            DomesticReportUnit.unit_id.in_(surplus_ids),
            DomesticReportLog.revoked == 0,
        ).first()
        if active:
            unit = next(u for u in units if u.id == active[0])
            raise ValueError(
                f"单件 {unit_display_code(item, unit.unit_no)} 已有有效报工，数量不能缩到 {new_qty}"
            )

    for unit_no in range(1, new_qty + 1):
        unit = by_no.get(unit_no)
        if unit:
            unit.status = 1
        else:
            db.add(DomesticItemUnit(item_id=item.id, unit_no=unit_no, status=1))
    for unit in units:
        if unit.unit_no > new_qty:
            unit.status = 0
    db.flush()


def completed_unit_ids(db: Session, progress_id: int) -> set[int]:
    return {
        unit_id for (unit_id,) in db.query(DomesticReportUnit.unit_id).join(
            DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id
        ).filter(
            DomesticReportUnit.progress_id == progress_id,
            DomesticReportLog.revoked == 0,
        ).all()
    }


def eligible_units(
    db: Session,
    item: DomesticOrderItem,
    progress: DomesticItemProgress,
    *,
    limit: int | None = None,
    unit_id: int | None = None,
) -> list[DomesticItemUnit]:
    _ensure_units_materialized(db, item)
    from app.domestic import routing_service

    rows = db.query(DomesticItemProgress).filter(
        DomesticItemProgress.item_id == item.id,
    ).order_by(DomesticItemProgress.step_order.asc()).all()
    active = db.query(DomesticItemUnit).filter(
        DomesticItemUnit.item_id == item.id,
        DomesticItemUnit.status == 1,
    ).order_by(DomesticItemUnit.unit_no.asc()).all()
    state = routing_service.load_passage_state(db, item)
    rules = routing_service.runtime_rule_map(db, item.route_id)
    ordered, _bypassable = routing_service.ordered_report_candidates(
        item, progress, rows, state, active, rules,
    )
    eligible_ids = {unit.id for unit in ordered}
    query = db.query(DomesticItemUnit).filter(DomesticItemUnit.id.in_(eligible_ids or {0}))
    if unit_id is not None:
        query = query.filter(DomesticItemUnit.id == unit_id)
    query = query.order_by(DomesticItemUnit.unit_no.asc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def select_units_for_report(
    db: Session,
    *,
    item: DomesticOrderItem,
    progress: DomesticItemProgress,
    qty: int,
    unit_id: int | None = None,
) -> list[DomesticItemUnit]:
    if unit_id is not None:
        selected = next(iter(eligible_units(
            db, item, progress, limit=1, unit_id=unit_id,
        )), None)
        if selected is None:
            unit = db.query(DomesticItemUnit).get(unit_id)
            if not unit or unit.item_id != item.id or unit.status != 1:
                raise ValueError("这个单件二维码不属于当前订单明细或已失效")
            current_done = completed_unit_ids(db, progress.id)
            if unit.id in current_done:
                raise ValueError(f"单件 {unit_display_code(item, unit.unit_no)} 的这道工序已经报过")
            raise ValueError(
                f"单件 {unit_display_code(item, unit.unit_no)} 的上一道工序还没完成"
            )
        if qty != 1:
            raise ValueError("逐件扫码模式每次只能报 1 件")
        return [selected]
    eligible = eligible_units(db, item, progress, limit=qty)
    if len(eligible) < qty:
        raise ValueError(f"最多还能报 {len(eligible)} 件，本次填了 {qty} 件")
    return eligible[:qty]


def add_report_units(
    db: Session,
    *,
    log: DomesticReportLog,
    units: list[DomesticItemUnit],
    outcome_by_unit: dict[int, str] | None = None,
) -> None:
    outcome_by_unit = outcome_by_unit or {}
    for unit in units:
        db.add(DomesticReportUnit(
            log_id=log.id,
            unit_id=unit.id,
            progress_id=log.progress_id,
            outcome_code=outcome_by_unit.get(unit.id),
            completed_at=log.reported_at,
        ))
    db.flush()


def units_for_log(
    db: Session,
    log_id: int,
    *,
    lock: bool = False,
) -> list[DomesticItemUnit]:
    query = db.query(DomesticItemUnit).join(
        DomesticReportUnit, DomesticReportUnit.unit_id == DomesticItemUnit.id
    ).filter(DomesticReportUnit.log_id == log_id).order_by(
        DomesticItemUnit.unit_no.asc()
    )
    if lock:
        query = query.populate_existing().with_for_update()
    return query.all()


def assert_log_units_not_consumed_downstream(
    db: Session,
    *,
    log: DomesticReportLog,
    item: DomesticOrderItem,
) -> None:
    unit_ids = {unit.id for unit in units_for_log(db, log.id)}
    if not unit_ids:
        return  # pre-116 revoked/audit-only record
    downstream = db.query(DomesticItemProgress).filter(
        DomesticItemProgress.item_id == item.id,
        DomesticItemProgress.step_order == log.step_order + 1,
    ).first()
    if not downstream:
        return
    consumed = unit_ids & completed_unit_ids(db, downstream.id)
    if consumed:
        units = db.query(DomesticItemUnit).filter(
            DomesticItemUnit.id.in_(consumed)
        ).order_by(DomesticItemUnit.unit_no.asc()).all()
        codes = "、".join(unit_display_code(item, unit.unit_no) for unit in units[:5])
        raise ValueError(f"下一道工序已使用单件 {codes}，请先撤销下一道的报工")


def assert_quantity_log_is_current_tail(
    db: Session,
    *,
    log: DomesticReportLog,
    item: DomesticOrderItem,
) -> None:
    """Quantity-mode revocation may only peel the current highest active batch.

    Otherwise revoking A1-01..03 while A1-04 is still active makes the cumulative
    quantity say one piece but the concrete identity set contain only piece 04.
    """
    if log.report_mode != "quantity":
        return
    units = units_for_log(db, log.id)
    if not units:
        return
    unit_ids = {unit.id for unit in units}
    first_no = min(unit.unit_no for unit in units)
    later = db.query(DomesticItemUnit.unit_no).join(
        DomesticReportUnit, DomesticReportUnit.unit_id == DomesticItemUnit.id
    ).join(
        DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id
    ).filter(
        DomesticReportUnit.progress_id == log.progress_id,
        DomesticReportLog.revoked == 0,
        DomesticItemUnit.id.not_in(unit_ids),
        DomesticItemUnit.unit_no > first_no,
    ).order_by(DomesticItemUnit.unit_no.asc()).first()
    if later:
        raise ValueError(
            f"数量报工只能从最新批次倒序撤销；请先撤销后续单件 "
            f"{unit_display_code(item, later[0])} 所在的报工"
        )


def list_item_units(
    db: Session,
    *,
    item: DomesticOrderItem,
    start_no: int,
    end_no: int,
) -> list[dict]:
    _ensure_units_materialized(db, item)
    order = db.query(DomesticOrder).get(item.order_id)
    units = db.query(DomesticItemUnit).filter(
        DomesticItemUnit.item_id == item.id,
        DomesticItemUnit.status == 1,
        DomesticItemUnit.unit_no >= start_no,
        DomesticItemUnit.unit_no <= end_no,
    ).order_by(DomesticItemUnit.unit_no.asc()).all()
    return [{
        "id": unit.id,
        "unit_no": unit.unit_no,
        "unit_code": unit_display_code(item, unit.unit_no),
        "domestic_no": order.domestic_no if order else None,
    } for unit in units]
