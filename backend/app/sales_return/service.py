"""Atomic local sales-return drafts, activation and complete reversal."""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.core.time import beijing_now
from app.sales_return import access, guards, policy, read_service
from app.sales_return.models import (ReturnAllocation, ReturnEffect, ReturnEvent, ReturnItem, ReturnReceipt,
                                    ReturnReceiving, SalesReturn)


def log(db, row, action, user, data=None):
    db.add(ReturnEvent(return_id=row.id, action=action, actor_id=access.actor(user), data=data or {}))


def get(db, identity, user, *, lock=False):
    row = db.scalar(select(SalesReturn).where(SalesReturn.id == identity))
    access.ensure(db, row, user)
    if lock:
        guards.lock_order(db, row.order_id, row.invoice_id)
        row = db.scalar(select(SalesReturn).where(SalesReturn.id == identity).with_for_update()
                        .execution_options(populate_existing=True))
        access.ensure(db, row, user)
    return row


def preview(db, body, user, *, exclude=None):
    from app.sales_return import funding, source_consistency, sources
    snapshot = sources.snapshot(db, body.order_id, user)
    source_consistency.verify(db, snapshot)
    previous = read_service.history(db, body.order_id, exclude=exclude)
    snapshot = funding.constrain(db, snapshot, body, previous)
    return policy.price(snapshot, body, previous)


def _body_hash(body):
    return policy.digest(body.model_dump(mode="json", exclude={"version", "request_key"}))


def _set_draft(db, row, body, quote):
    snapshot = quote["order"]
    for name in ("order_id", "order_no", "customer_id", "customer_name", "owner_okki_user_id", "sales_user_id", "invoice_id", "currency"):
        setattr(row, name, snapshot.get(name))
    for name in ("return_type", "reason_code", "reason"):
        setattr(row, name, getattr(body, name))
    for name in ("reduction_amount", "refund_amount", "waived_amount"):
        setattr(row, name, policy.money(quote[name]))
    row.snapshot = snapshot
    row.request_hash = _body_hash(body)
    previous = db.scalars(select(ReturnItem).where(ReturnItem.return_id == row.id)).all() if row.id else []
    for item in previous:
        db.delete(item)
    db.flush()
    for line in quote["lines"]:
        db.add(ReturnItem(return_id=row.id, **{name: line[name] for name in
            ("source_key", "outbound_id", "outbound_line_id", "order_line_id", "product_id", "sku_id", "product_name",
             "quantity", "reduction_amount", "reduction_usd")}, specification=line.get("specification", ""), source_snapshot=line))
    db.flush()


def create(db, body, user):
    existing = db.scalar(select(SalesReturn).where(SalesReturn.request_key == body.request_key))
    if existing:
        access.ensure(db, existing, user)
        if existing.created_by != access.actor(user) or existing.request_hash != _body_hash(body):
            raise HTTPException(409, "提交标识已用于不同的退货单内容")
        return existing
    quote = preview(db, body, user)
    row = SalesReturn(return_no=f"TH{beijing_now():%Y%m%d}{uuid4().hex[:12].upper()}",
                      request_key=body.request_key, created_by=access.actor(user), status="draft", version=1)
    db.add(row)
    # Required header values are installed before the first INSERT.
    row.order_id = body.order_id
    _set_draft(db, row, body, quote)
    log(db, row, "created", user)
    return row


def update(db, identity, body, user):
    row = get(db, identity, user, lock=True)
    if row.status != "draft":
        raise HTTPException(409, "已生效退货单不能编辑，请通过反向更正处理")
    if row.version != body.version:
        if row.request_hash == _body_hash(body):
            return row
        raise HTTPException(409, "草稿已被修改，请刷新后重试")
    if row.order_id != body.order_id:
        raise HTTPException(409, "已保存草稿不能更换原订单，请重新建单")
    quote = preview(db, body, user, exclude=row.id)
    _set_draft(db, row, body, quote)
    row.version += 1
    log(db, row, "updated", user)
    return row


def activate(db, identity, body, user):
    from app.sales_return import commission
    row = get(db, identity, user, lock=True)
    fingerprint = policy.digest(body.model_dump(exclude={"version"}))
    if row.activate_key:
        if row.activate_key == body.request_key and row.activate_hash == fingerprint:
            return row
        raise HTTPException(409, "该退货单已经提交，请核对原生效结果")
    if row.status != "draft" or row.version != body.version:
        raise HTTPException(409, "退货单状态或版本已变化，请刷新后重试")
    quote = preview(db, read_service.draft_body(db, row), user, exclude=row.id)
    from app.sales_return.activation_checks import ensure_idle
    ensure_idle(db, quote["order"])
    if quote["quote_version"] != body.quote_version:
        raise HTTPException(409, "出库数量、货款或回款额度已变化，请重新预览")
    for name in ("customer_id", "currency", "owner_okki_user_id", "invoice_id", "sales_user_id"):
        expected, observed = getattr(row, name), quote["order"].get(name)
        if (None if expected is None else str(expected)) != (None if observed is None else str(observed)):
            raise HTTPException(409, "原订单客户、币种、业务员或发票关联已变化，请先更新草稿再重新预览")
    # Save the final verified source and its cumulative USD tail allocation.
    for item, priced in zip(db.scalars(select(ReturnItem).where(ReturnItem.return_id == row.id)
                                      .order_by(ReturnItem.id)).all(), quote["lines"]):
        if item.source_key != priced["source_key"]:
            raise HTTPException(409, "退货明细顺序已变化，请重新预览")
        if any(str(getattr(item, key)) != str(priced[key]) for key in
               ("order_line_id", "outbound_id", "outbound_line_id", "product_id", "sku_id")):
            raise HTTPException(409, "原出库产品身份已变化，请更新草稿并重新核对明细")
        item.reduction_usd = policy.money(priced["reduction_usd"])
        item.source_snapshot = priced
    now = beijing_now()
    row.status, row.effective_at, row.effective_date = "effective", now, now.date()
    row.activated_by, row.activate_key, row.activate_hash = access.actor(user), body.request_key, fingerprint
    row.snapshot = quote["order"]
    row.version += 1
    effect = ReturnEffect(return_id=row.id, effect_kind="activate", order_id=row.order_id,
                          owner_okki_user_id=row.owner_okki_user_id, customer_id=row.customer_id,
                          currency=row.currency, amount=-policy.money(quote["reduction_amount"]),
                          amount_usd=-policy.money(quote["reduction_usd"]), effective_date=now.date(),
                          gmv_eligible=int(bool(row.snapshot["gmv_eligible"])),
                          order_role=row.snapshot.get("order_role", "pending"),
                          departments=row.snapshot.get("departments", []), snapshot=row.snapshot)
    db.add(effect)
    for values in quote["allocations"]:
        payment = next(item for item in row.snapshot["payments"]
                       if item["payment_id"] == values["original_payment_id"])
        basis = commission.freeze_basis(db, values["original_payment_id"], expected={
            "order_id": row.order_id, "customer_id": row.customer_id,
            "commission_basis_usd": payment.get("commission_basis_usd", values["original_principal_usd"])})
        db.add(ReturnAllocation(return_id=row.id, **values, basis=basis))
    db.flush()
    if row.refund_amount > 0:
        receipt = ReturnReceipt(return_id=row.id, effect_kind="activate", receipt_no=f"THHK-{row.return_no}",
                                order_id=row.order_id, customer_id=row.customer_id, currency=row.currency,
                                amount=-row.refund_amount, amount_usd=-policy.money(quote["refund_usd"]),
                                collection_date=now.date(), created_by=access.actor(user))
        db.add(receipt)
        db.flush()
        commission.project_receipt(db, receipt)
    if row.invoice_id is not None:
        from app.invoice.models import Invoice
        from app.invoice.presale_runtime import pool_lots
        invoice = db.get(Invoice, row.invoice_id)
        if invoice is not None and invoice.order_type == "presale":
            db.flush()
            pool_lots(db, invoice, current=True)
    guard = guards.lock_order(db, row.order_id)
    guard.version += 1
    log(db, row, "activated", user, {name: quote[name] for name in ("reduction_amount", "refund_amount", "waived_amount")})
    db.flush()
    return row


def reverse(db, identity, body, user):
    from app.sales_return import commission
    row = get(db, identity, user, lock=True)
    if row.reverse_key:
        event = db.scalar(select(ReturnEvent).where(ReturnEvent.return_id == row.id, ReturnEvent.action == "reversed"))
        if row.reverse_key == body.request_key and event and event.data.get("reason") == body.reason:
            return row
        raise HTTPException(409, "退货单已经冲销，请核对原结果")
    if row.status != "effective" or row.version != body.version:
        raise HTTPException(409, "仅当前版本的已生效退货单可以反向更正")
    if row.cash_status == "paid":
        raise HTTPException(409, "退款尚未核实收回，不能恢复已收金额；请先记录资金收回证据")
    if db.scalar(select(ReturnReceiving.id).where(ReturnReceiving.return_id == row.id).limit(1)):
        raise HTTPException(409, "已有实物收货记录，须先完成仓库反向处理，不能直接整单冲销")
    now = beijing_now()
    original = db.scalar(select(ReturnEffect).where(ReturnEffect.return_id == row.id, ReturnEffect.effect_kind == "activate"))
    db.add(ReturnEffect(return_id=row.id, effect_kind="reverse", order_id=row.order_id,
        owner_okki_user_id=original.owner_okki_user_id, customer_id=row.customer_id, currency=row.currency,
        amount=-original.amount, amount_usd=-original.amount_usd, effective_date=now.date(),
        gmv_eligible=original.gmv_eligible, order_role=original.order_role, departments=original.departments, snapshot=original.snapshot))
    previous = db.scalar(select(ReturnReceipt).where(ReturnReceipt.return_id == row.id, ReturnReceipt.effect_kind == "activate"))
    if previous:
        receipt = ReturnReceipt(return_id=row.id, effect_kind="reverse", original_receipt_id=previous.id,
            receipt_no=f"CZ-{previous.receipt_no}", order_id=row.order_id, customer_id=row.customer_id,
            currency=row.currency, amount=-previous.amount, amount_usd=-previous.amount_usd,
            collection_date=now.date(), created_by=access.actor(user))
        db.add(receipt)
        db.flush()
        commission.project_receipt(db, receipt)
    row.status, row.reversed_at, row.reverse_key = "reversed", now, body.request_key
    row.version += 1
    if row.invoice_id is not None:
        from app.invoice.models import Invoice
        from app.invoice.presale_runtime import pool_lots
        invoice = db.get(Invoice, row.invoice_id)
        if invoice is not None and invoice.order_type == "presale":
            db.flush()
            pool_lots(db, invoice, current=True)
    guards.lock_order(db, row.order_id).version += 1
    log(db, row, "reversed", user, {"reason": body.reason})
    db.flush()
    return row


def delete(db, identity, version, user):
    row = get(db, identity, user, lock=True)
    if row.status == "deleted" and row.version == version + 1:
        return row
    if row.status != "draft" or row.version != version:
        raise HTTPException(409, "只能删除当前版本的退货草稿")
    # Soft-delete keeps request identity and audit intact, including lost-response retries.
    row.status = "deleted"
    row.version += 1
    log(db, row, "deleted", user)
    return row


def cash(db, identity, body, user):
    row = get(db, identity, user, lock=True)
    if row.status != "effective" or row.refund_amount <= 0:
        raise HTTPException(409, "该单没有待核实的资金退款")
    if row.version != body.version:
        if row.cash_status == body.status and row.cash_evidence and row.cash_evidence[-1]["evidence"] == body.evidence:
            return row
        raise HTTPException(409, "资金状态已变化，请刷新后核对")
    expected = {"not_paid": "paid", "paid": "recovered"}
    if expected.get(row.cash_status) != body.status:
        raise HTTPException(409, "资金执行状态不能跳过实际退款或收回步骤")
    row.cash_status = body.status
    row.cash_evidence = [*row.cash_evidence, {"status": body.status, "evidence": body.evidence,
                                          "actor_id": access.actor(user), "at": beijing_now().isoformat()}]
    row.version += 1
    log(db, row, f"cash_{body.status}", user, {"evidence": body.evidence})
    return row
