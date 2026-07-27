"""内贸工序进度 —— 展开、口径计算、状态回算

被 order_service（下单/改量/发货）和 report_service（报工/撤销）共用，
放在这里两边都不用互相 import，避免循环依赖。

核心口径（全系统唯一定义处）：
    可报数量(第N道) = 累计完成(第N-1道) − 累计完成(第N道)
    首道的上游 = 明细下单数量
不存冗余的「待做数量」字段：推导值永远自洽，冗余字段必然漂移。
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domestic import constants as C
from app.domestic.models import (
    DomesticItemProgress,
    DomesticOrder,
    DomesticOrderItem,
    DomesticReportLog,
)
from app.domestic.product_service import get_route_steps
from app.production.models import Process


def init_item_progress(db: Session, item: DomesticOrderItem, route_id: int | None = None) -> int:
    """按工艺路线把明细展开成逐工序进度行。返回展开的工序数。

    有过报工痕迹（哪怕已全部撤销）就拒绝重建：进度行是报工流水的 FK 父，
    删掉会连带级联抹掉撤销记录，审计断档。
    """
    rid = route_id or item.route_id
    if not rid:
        return 0
    steps = get_route_steps(db, rid)
    if not steps:
        return 0

    log_count = db.query(func.count(DomesticReportLog.id)).filter(
        DomesticReportLog.item_id == item.id
    ).scalar() or 0
    if log_count:
        raise ValueError(f"该明细已有 {log_count} 条报工记录，不能重建工序进度")

    existing = db.query(DomesticItemProgress).filter(DomesticItemProgress.item_id == item.id).all()
    if any(p.completed_qty > 0 for p in existing):
        raise ValueError("该明细已有报工数量，不能重建工序进度")
    for p in existing:
        db.delete(p)
    db.flush()

    # 序号自己按位置重排，不沿用路线表的 step_order —— 全部数量口径都建立在
    # 「相邻序号 = 上下游」上，路线侧一旦出现跳号（那是另一个域的实现细节），
    # 上游就会算错。这里重排等于把这个假设焊死在自己域内。
    for idx, step in enumerate(steps, start=1):
        db.add(DomesticItemProgress(
            item_id=item.id,
            route_id=rid,
            process_id=step.process_id,
            step_order=idx,
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
    last_by = _last_reporter_map(db, item.id)

    view = []
    upstream = item.order_qty
    for r in rows:
        last = last_by.get(r.step_order) or {}
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
            # 最近一次有效报工是谁、什么时候 —— 车间查进度时最想知道的两件事
            "last_reported_by": last.get("name"),
            "last_report_qty": last.get("qty"),
        })
        upstream = r.completed_qty
    return view


def _last_reporter_map(db: Session, item_id: int) -> dict[int, dict]:
    """每道工序最近一次未撤销报工的人与数量。一条 SQL 取全部流水后在内存归并，
    不在工序循环里逐条查（那是 N+1）。单个明细的流水量级很小。"""
    logs = (
        db.query(
            DomesticReportLog.step_order,
            DomesticReportLog.reported_by_name,
            DomesticReportLog.report_qty,
            DomesticReportLog.reported_at,
        )
        .filter(DomesticReportLog.item_id == item_id, DomesticReportLog.revoked == 0)
        .order_by(DomesticReportLog.reported_at.asc(), DomesticReportLog.id.asc())
        .all()
    )
    out: dict[int, dict] = {}
    for step_order, name, qty, _at in logs:   # 升序遍历，后写的覆盖前面的 = 最近一次
        out[step_order] = {"name": name, "qty": qty}
    return out


def _get_step(db: Session, item_id: int, step_order: int, lock: bool = False):
    """取某道工序进度行。

    lock=True 走锁定读：MySQL 默认 REPEATABLE READ 下，普通 SELECT 读的是事务
    开头建立的快照（鉴权那次查库就已经建好了），拿着行锁也照样读到旧值。
    跨行的守恒校验必须用锁定读，否则上下游同时写会读到过期的邻道数量。
    """
    q = db.query(DomesticItemProgress).filter(
        DomesticItemProgress.item_id == item_id,
        DomesticItemProgress.step_order == step_order,
    )
    if lock:
        q = q.with_for_update()
    return q.first()


def reportable_qty(
    db: Session, progress: DomesticItemProgress, item: DomesticOrderItem, lock: bool = False
) -> int:
    """单道工序的可报数量。上游是上一道的累计完成数，首道是下单数量。"""
    if progress.step_order <= 1:
        upstream = item.order_qty
    else:
        prev = _get_step(db, item.id, progress.step_order - 1, lock=lock)
        upstream = prev.completed_qty if prev else 0
    return max(0, upstream - progress.completed_qty)


def downstream_completed_qty(db: Session, item_id: int, step_order: int, lock: bool = False) -> int:
    """下一道已完成多少 —— 撤销时不能把本道累计减到低于它。"""
    nxt = _get_step(db, item_id, step_order + 1, lock=lock)
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
