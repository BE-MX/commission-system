"""内贸工序进度 —— 展开、口径计算、状态回算

被 order_service（下单/改量/发货）和 report_service（报工/撤销）共用，
放在这里两边都不用互相 import，避免循环依赖。

核心口径（全系统唯一定义处）：
    可报数量(第N道) = 累计完成(第N-1道) − 累计完成(第N道)
    首道的上游 = 明细下单数量
不存冗余的「待做数量」字段：推导值永远自洽，冗余字段必然漂移。
"""

from sqlalchemy.orm import Session

from app.domestic import constants as C
from app.domestic.models import DomesticItemProgress, DomesticOrder, DomesticOrderItem
from app.domestic.product_service import get_route_steps
from app.production.models import Process


def init_item_progress(db: Session, item: DomesticOrderItem, route_id: int | None = None) -> int:
    """按工艺路线把明细展开成逐工序进度行。返回展开的工序数。

    已有报工数量时拒绝重建 —— 重建会抹掉车间已经做完的量。
    """
    rid = route_id or item.route_id
    if not rid:
        return 0
    steps = get_route_steps(db, rid)
    if not steps:
        return 0

    existing = db.query(DomesticItemProgress).filter(DomesticItemProgress.item_id == item.id).all()
    if any(p.completed_qty > 0 for p in existing):
        raise ValueError("该明细已有报工记录，不能重建工序进度")
    for p in existing:
        db.delete(p)
    db.flush()

    for step in steps:
        db.add(DomesticItemProgress(
            item_id=item.id,
            route_id=rid,
            process_id=step.process_id,
            step_order=step.step_order,
            completed_qty=0,
            status=0,
        ))
    item.route_id = rid
    db.flush()
    return len(steps)


def build_progress_view(db: Session, item: DomesticOrderItem) -> list[dict]:
    """逐工序视图，带每道的可报数量。工序名批量取，不在循环里单查。"""
    rows = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.item_id == item.id)
        .order_by(DomesticItemProgress.step_order.asc())
        .all()
    )
    if not rows:
        return []

    names = dict(
        db.query(Process.id, Process.name)
        .filter(Process.id.in_({r.process_id for r in rows}))
        .all()
    )

    view = []
    upstream = item.order_qty
    for r in rows:
        view.append({
            "progress_id": r.id,
            "step_order": r.step_order,
            "process_id": r.process_id,
            "process_name": names.get(r.process_id, f"工序{r.process_id}"),
            "order_qty": item.order_qty,
            "upstream_qty": upstream,
            "completed_qty": r.completed_qty,
            "reportable_qty": max(0, upstream - r.completed_qty),
            "status": r.status,
            "first_reported_at": r.first_reported_at,
            "last_reported_at": r.last_reported_at,
        })
        upstream = r.completed_qty
    return view


def reportable_qty(db: Session, progress: DomesticItemProgress, item: DomesticOrderItem) -> int:
    """单道工序的可报数量。上游是上一道的累计完成数，首道是下单数量。"""
    if progress.step_order <= 1:
        upstream = item.order_qty
    else:
        prev = (
            db.query(DomesticItemProgress)
            .filter(
                DomesticItemProgress.item_id == item.id,
                DomesticItemProgress.step_order == progress.step_order - 1,
            )
            .first()
        )
        upstream = prev.completed_qty if prev else 0
    return max(0, upstream - progress.completed_qty)


def downstream_completed_qty(db: Session, item_id: int, step_order: int) -> int:
    """下一道已完成多少 —— 撤销时不能把本道累计减到低于它。"""
    nxt = (
        db.query(DomesticItemProgress)
        .filter(
            DomesticItemProgress.item_id == item_id,
            DomesticItemProgress.step_order == step_order + 1,
        )
        .first()
    )
    return nxt.completed_qty if nxt else 0


def recalc_item_status(db: Session, item: DomesticOrderItem) -> None:
    """末道工序数量做齐 = 明细完工。已发货的明细不回退。"""
    if item.status == C.ITEM_SHIPPED:
        return
    last = (
        db.query(DomesticItemProgress)
        .filter(DomesticItemProgress.item_id == item.id)
        .order_by(DomesticItemProgress.step_order.desc())
        .first()
    )
    done = bool(last) and last.completed_qty >= item.order_qty
    item.status = C.ITEM_DONE if done else C.ITEM_PRODUCING


def sync_order_status(db: Session, order_id: int) -> None:
    """由明细状态回算订单状态。已终止的订单不受业务动作影响。"""
    order = db.query(DomesticOrder).get(order_id)
    if not order or order.status == C.ORDER_TERMINATED:
        return
    statuses = [
        s for (s,) in db.query(DomesticOrderItem.status)
        .filter(DomesticOrderItem.order_id == order_id).all()
    ]
    if not statuses:
        order.status = C.ORDER_PRODUCING
    elif all(s == C.ITEM_SHIPPED for s in statuses):
        order.status = C.ORDER_SHIPPED
    elif all(s >= C.ITEM_DONE for s in statuses):
        order.status = C.ORDER_DONE
    else:
        order.status = C.ORDER_PRODUCING


def sync_progress_row_status(progress: DomesticItemProgress, order_qty: int) -> None:
    """本道做满下单数量才算这道工序完成。"""
    progress.status = 1 if progress.completed_qty >= order_qty else 0
