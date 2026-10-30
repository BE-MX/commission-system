"""Physical receipt facts do not fabricate warehouse inventory movements."""
from fastapi import HTTPException
from sqlalchemy import func, select

from app.sales_return import access, policy, service
from app.sales_return.models import ReturnItem, ReturnReceiving


def receive(db, identity, body, user):
    row = service.get(db, identity, user, lock=True)
    fingerprint = policy.digest(body.model_dump())
    existing = db.scalar(select(ReturnReceiving).where(ReturnReceiving.request_key == body.request_key))
    if existing:
        if existing.return_id != row.id or existing.created_by != access.actor(user) or existing.request_hash != fingerprint:
            raise HTTPException(409, "收货标识已用于不同内容")
        return row
    if row.status != "effective" or row.return_type != "return_refund":
        raise HTTPException(409, "仅已生效的退货退款单可以登记实物收货")
    item = db.scalar(select(ReturnItem).where(ReturnItem.id == body.item_id, ReturnItem.return_id == row.id))
    if item is None:
        raise HTTPException(404, "退货产品明细不存在")
    received = db.scalar(select(func.coalesce(func.sum(ReturnReceiving.quantity), 0))
                         .where(ReturnReceiving.item_id == item.id))
    if received + body.quantity > item.quantity:
        raise HTTPException(409, "累计实收超过计划退货数量，请核对明细")
    event = ReturnReceiving(return_id=row.id, item_id=item.id, quantity=body.quantity,
        accepted_quantity=body.accepted_quantity, rejected_quantity=body.rejected_quantity,
        pending_quantity=body.pending_quantity, request_key=body.request_key, request_hash=fingerprint,
        created_by=access.actor(user), stock_status="not_stocked",
        evidence={"note": body.note, "inspection_actor_id": access.actor(user)})
    db.add(event)
    row.version += 1
    service.log(db, row, "received", user, {"item_id": item.id, "quantity": body.quantity,
                                          "accepted_quantity": body.accepted_quantity,
                                          "rejected_quantity": body.rejected_quantity,
                                          "pending_quantity": body.pending_quantity})
    db.flush()
    return row


def stock(db, identity, event_id, body, user):
    row = service.get(db, identity, user, lock=True)
    event = db.scalar(select(ReturnReceiving).where(ReturnReceiving.id == event_id,
                                                   ReturnReceiving.return_id == row.id).with_for_update())
    if row.status != "effective" or event is None or event.accepted_quantity <= 0:
        raise HTTPException(409, "只能核验已生效退货单中检验合格的实收件数")
    if event.stock_status == "stocked":
        if event.stock_reference != body.reference:
            raise HTTPException(409, "该批收货已关联另一张权威入库单")
        return row
    # The live mirror has inbound tables, but no verified return-in writer or
    # finance-effective status contract. A typed reference alone is not proof.
    raise HTTPException(409, "权威退货入库接口及生效状态尚未完成契约核验，已保留收货检验记录；可销售库存未增加")


def inspect_receiving(db, identity, event_id, body, user):
    row = service.get(db, identity, user, lock=True)
    event = db.scalar(select(ReturnReceiving).where(ReturnReceiving.id == event_id,
                                                   ReturnReceiving.return_id == row.id).with_for_update())
    if row.status != "effective" or row.return_type != "return_refund" or event is None:
        raise HTTPException(409, "该单没有可以继续检验的实收记录")
    quantities = (body.accepted_quantity, body.rejected_quantity, body.pending_quantity)
    previous = (event.accepted_quantity, event.rejected_quantity, event.pending_quantity)
    if event.version != body.version:
        if quantities == previous and event.evidence.get("inspection_note") == body.note:
            return row
        raise HTTPException(409, "收货检验结果已变化，请刷新后重试")
    if (sum(quantities) != event.quantity or body.accepted_quantity < event.accepted_quantity
            or body.rejected_quantity < event.rejected_quantity or body.pending_quantity > event.pending_quantity
            or event.stock_status == "stocked"):
        raise HTTPException(409, "只能将本次待检件数转为合格或不合格，不能增加实收或改已入库结果")
    event.accepted_quantity, event.rejected_quantity, event.pending_quantity = quantities
    event.evidence = {**event.evidence, "inspection_note": body.note, "inspection_actor_id": access.actor(user)}
    event.version += 1
    row.version += 1
    service.log(db, row, "inspected", user, {"receiving_id": event.id, "before": list(previous),
                                            "after": list(quantities), "note": body.note})
    return row
