"""Authenticated, progress-ID-idempotent local scanner with auditable revocation."""
from sqlalchemy import select
from app.core.time import beijing_now
from app.production.models import OrderProductProcessProgress, UserProcessBinding, Process
from app.production.local_models import ProductionEvent
from app.production.local_schemas import Action
from app.production.local_service import get_item, _lock, claim, _sync_status


def _steps(db, item_id):
    return db.scalars(select(OrderProductProcessProgress).where(OrderProductProcessProgress.order_product_id == item_id)
                      .order_by(OrderProductProcessProgress.step_order).with_for_update().execution_options(populate_existing=True)).all()


def submit(db, progress_id, item_id, user):
    with db.begin_nested():
        order, item = get_item(db, item_id)
        progress = _lock(db, OrderProductProcessProgress, progress_id)
        if progress is None or progress.order_product_id != item.id:
            return {"success": False, "message": "工序与生产明细不匹配"}
        binding = db.scalar(select(UserProcessBinding.id).where(UserProcessBinding.user_id == user.id,
                            UserProcessBinding.process_id == progress.process_id).with_for_update())
        if not user.is_active or binding is None:
            return {"success": False, "message": "您未被分配此工序"}
        steps = _steps(db, item.id)
        if progress.status == 1:
            return {"success": True, "message": "工序已记录完成", "all_done": all(x.status == 1 for x in steps)}
        if item.status == 1 or order.deleted_flag:
            return {"success": False, "message": "生产已终止或删除"}
        pending = next((step for step in steps if step.status == 0), None)
        if pending is None or pending.id != progress.id:
            return {"success": False, "message": "请先完成上一道工序"}
        body = Action(request_key=f"step:{progress.id}:{item.local_version}", expected_version=item.local_version, reason="认证工人扫码报工")
        event, _ = claim(db, "step_complete", progress.id, body, {"sub": str(user.id)})
        progress.status = 1
        progress.completed_at = beijing_now()
        progress.completed_by_user_id, progress.completed_by_wx_id = user.id, user.wx_id
        progress.local_event_id = event.id
        all_done = all(step.status == 1 for step in steps)
        completed_delta = item.order_qty - item.completed_qty if all_done else 0
        item.completed_qty += completed_delta
        item.status = 2 if item.completed_qty == item.order_qty else 0
        item.local_version += 1
        event.order_id, event.item_id = order.id, item.id
        event.payload = {**event.payload, "completed_quantity_delta": completed_delta,
                         "process_id": progress.process_id, "step_order": progress.step_order}
        db.flush()
        _sync_status(db, order)
        next_pending = next((step for step in steps if step.status == 0), None)
        next_process = db.get(Process, next_pending.process_id) if next_pending else None
        return {"success": True, "message": "工序已记录完成" + ("，等待仓库验收入库" if all_done else ""),
                "all_done": all_done, "next_process": next_process.name if next_process else None}


def revoke(db, progress_id, user):
    with db.begin_nested():
        identity = db.get(OrderProductProcessProgress, progress_id)
        if identity is None:
            return {"success": False, "message": "工序不存在"}
        order, item = get_item(db, identity.order_product_id)
        progress = _lock(db, OrderProductProcessProgress, progress_id)
        if progress.status != 1:
            return {"success": False, "message": "工序尚未完成或已撤销"}
        if progress.completed_by_user_id != user.id or not user.is_active:
            return {"success": False, "message": "只能撤销自己的报工记录"}
        if item.status == 1:
            return {"success": False, "message": "生产已终止"}
        steps = _steps(db, item.id)
        if any(step.step_order > progress.step_order and step.status == 1 for step in steps):
            return {"success": False, "message": "已有后续工序完成，不能撤销"}
        original = _lock(db, ProductionEvent, progress.local_event_id)
        if original is None or original.action != "step_complete":
            return {"success": False, "message": "报工缺少本地事件，请核对历史记录"}
        delta = original.payload["completed_quantity_delta"]
        if item.completed_qty - delta < item.received_qty:
            return {"success": False, "message": "产品已验收入库，请先冲销对应验收再撤销报工"}
        body = Action(request_key=f"step-revoke:{original.id}", expected_version=item.local_version, reason="工人撤销本人报工")
        event, _ = claim(db, "step_revoke", progress.id, body, {"sub": str(user.id)}, reverses_event_id=original.id)
        progress.status, progress.completed_at = 0, None
        progress.completed_by_user_id, progress.completed_by_wx_id = None, None
        item.completed_qty -= delta
        item.status = 2 if item.completed_qty == item.order_qty else 0
        item.local_version += 1
        event.order_id, event.item_id = order.id, item.id
        event.payload = {**event.payload, "completed_quantity_delta": -delta}
        db.flush()
        _sync_status(db, order)
        return {"success": True, "message": "工序已撤销，原报工与撤销记录已保留"}
