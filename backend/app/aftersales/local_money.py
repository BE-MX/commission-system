"""Atomic approved compensation: release -> reverse -> credit -> optional refund.

Original application and receipt faces are immutable. Only released portions of
the case's shipped line can become a customer's available money again.
"""
import hashlib
import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.aftersales.models import AfterSalesCase, AfterSalesExecution, AfterSalesReview
from app.aftersales.money_schemas import MoneyExecute
from app.finance import service as finance, reversal_service
from app.finance.models import FinanceEvent
from app.finance.schemas import FinanceAction, AdjustmentCreate
from app.invoice.models import InvoiceItem
from app.invoice.settlement_models import Receivable, SettlementItem, ShipmentSettlement, SettlementApplication
from app.invoice.local_funding import ensure_event_date
from app.receipt.models import Receipt
from app.receipt.access import user_id

ZERO = Decimal("0")


def _context(db, case_id, body, user):
    finance.book(db)
    seed = db.get(AfterSalesCase, case_id)
    line_seed = db.get(InvoiceItem, seed.local_invoice_item_id) if seed and seed.local_invoice_item_id else None
    if line_seed is None:
        raise HTTPException(404, "本地售后单不存在")
    invoice = finance._invoice(db, line_seed.invoice_id, user)
    case = finance.lock(db, AfterSalesCase, case_id)
    if case.deleted_at is not None or case.local_invoice_item_id != line_seed.id:
        raise ValueError("售后商品关联已变化")
    seed_app = db.get(SettlementApplication, body.application_id)
    seed_receipt = db.get(Receipt, seed_app.receipt_id) if seed_app else None
    if seed_receipt is None or seed_receipt.invoice_id != invoice.id:
        raise ValueError("原发货资金不属于售后订单")
    batch = finance._payment(db, seed_receipt.batch_id, user)
    target = finance.lock(db, Receivable, seed_receipt.receivable_id)
    shipment = finance.lock(db, ShipmentSettlement, seed_app.settlement_id)
    item = finance.lock(db, SettlementItem, body.settlement_item_id)
    app = finance.lock(db, SettlementApplication, body.application_id)
    receipt = finance.lock(db, Receipt, seed_receipt.id)
    if (item is None or item.invoice_item_id != case.local_invoice_item_id or shipment is None
            or shipment.invoice_id != invoice.id or item.settlement_id != shipment.id or app.settlement_id != shipment.id
            or app.receipt_id != receipt.id or target is None or target.invoice_id != invoice.id
            or receipt.batch_id != batch.id or receipt.receivable_id != target.id):
        raise ValueError("售后商品、发货应用与原核销不一致")
    return invoice, case, batch, target, shipment, item, app, receipt


def _approval(db, case, body):
    review = db.scalar(select(AfterSalesReview).where(AfterSalesReview.case_id == case.id,
        AfterSalesReview.workflow_round == case.workflow_round, AfterSalesReview.decision == "approve")
        .order_by(AfterSalesReview.id.desc()).limit(1).with_for_update().execution_options(populate_existing=True))
    if review is None or not case.approved_at:
        raise ValueError("缺少当前审批轮次的金额批准凭证")
    actions = (review.compensation_snapshot_json or {}).get("actions") or []
    approved = [action for action in actions if action.get("code") == body.action]
    current = [action for action in case.selected_actions_json or [] if action.get("code") == body.action]
    if not approved or current != approved:
        raise ValueError("审批方案未包含该金额动作或方案已变化")
    cap, original_cap = ZERO, ZERO
    for action in approved:
        if action.get("currency") not in (None, body.currency):
            raise ValueError("执行币种与审批币种不一致")
        if body.action in {"cash_refund", "freight_subsidy"} and not action.get("currency"):
            raise ValueError("审批方案缺少明确币种")
        try:
            amount = Decimal(str(action["amount_usd"]))
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise ValueError("该方案须先审批明确的美元金额上限，不能直接执行百分比折扣") from exc
        if not amount.is_finite() or amount <= 0:
            raise ValueError("审批方案须有明确正数美元金额上限")
        cap += amount
        raw_original = action.get("amount_original")
        if raw_original is None and body.currency == "USD":
            raw_original = action.get("amount_usd")
        try:
            original_amount = Decimal(str(raw_original))
        except ArithmeticError as exc:
            raise ValueError("非美元审批须明确原币金额，请重新审批补齐 amount_original") from exc
        if not original_amount.is_finite() or original_amount <= 0 or original_amount != finance.money(original_amount):
            raise ValueError("批准原币金额必须为正数且最多两位小数")
        original_cap += original_amount
    return review, cap, original_cap


def _line_share(db, shipment, item, bucket):
    lines = db.scalars(select(SettlementItem).where(SettlementItem.settlement_id == shipment.id)
        .order_by(SettlementItem.invoice_item_id).with_for_update().execution_options(populate_existing=True)).all()
    goods = Decimal(shipment.quote["goods_amount"])
    gross = (Decimal(shipment.quote["freight_amount"]) if bucket == "freight" else
             goods + Decimal(shipment.quote["packaging_amount"]) + Decimal(shipment.quote["handling_amount"]))
    if goods <= 0:
        raise ValueError("原发货商品价值异常，不能分摊售后金额")
    before = sum((line.line_amount for line in lines if line.invoice_item_id < item.invoice_item_id), ZERO)
    return finance.money(gross * (before + item.line_amount) / goods) - finance.money(gross * before / goods)


def _limits(db, case, body, batch, shipment, item, cap, original_cap):
    facts = db.scalars(select(AfterSalesExecution).where(
        or_(AfterSalesExecution.case_id == case.id, AfterSalesExecution.settlement_item_id == item.id))
        .order_by(AfterSalesExecution.id).with_for_update().execution_options(populate_existing=True)).all()
    if any(fact.business_date > body.business_date for fact in facts):
        raise ValueError("售后金额日期不能早于既有执行凭证")
    money_facts = [fact for fact in facts if fact.action == "money_execute"]
    case_facts = [fact for fact in money_facts if fact.case_id == case.id]
    quantities = {fact.settlement_item_id: fact.quantity for fact in case_facts}
    if item.id in quantities and quantities[item.id] != body.quantity:
        raise ValueError("分次金额执行必须沿用本案该发货行的受影响数量")
    quantities[item.id] = body.quantity
    if body.quantity > item.quantity or sum(quantities.values()) > case.quantity:
        raise ValueError("执行范围超过本批发货或售后批准数量")
    if case.requires_return:
        returned = sum(fact.quantity for fact in facts if fact.case_id == case.id
                       and fact.settlement_item_id == item.id and fact.action == "return_receive")
        if returned < body.quantity:
            raise ValueError("审批要求退货，需先收齐本次受影响数量")
    if batch.rate_to_usd is None or batch.rate_to_usd <= 0:
        raise ValueError("原付款缺少已冻结美元汇率，不能猜测币种换算")
    # Keep sub-cent USD precision in the approval budget. Rounding each tiny
    # execution down would let repeated requests spend beyond the approved cap.
    usd = body.amount * batch.rate_to_usd
    used_usd = sum((Decimal(fact.payload["amount_usd"]) for fact in case_facts
                    if fact.payload["body"]["action"] == body.action), ZERO)
    if usd + used_usd > cap:
        raise ValueError("累计执行超过该动作所有轮次共享的审批美元上限")
    used_original = sum((Decimal(fact.payload["amount"]) for fact in case_facts
                         if fact.payload["body"]["action"] == body.action), ZERO)
    if body.amount + used_original > original_cap:
        raise ValueError("累计执行超过批准原币金额")
    bucket = "freight" if body.action == "freight_subsidy" else "goods"
    share = _line_share(db, shipment, item, bucket)
    line_facts = [fact for fact in money_facts if fact.settlement_item_id == item.id and fact.payload["bucket"] == bucket]
    line_used = sum((Decimal(fact.payload["amount"]) for fact in line_facts), ZERO)
    case_used = sum((Decimal(fact.payload["amount"]) for fact in line_facts if fact.case_id == case.id), ZERO)
    if line_used + body.amount > share or case_used + body.amount > share * body.quantity / item.quantity:
        raise ValueError("累计执行超过本案受影响商品或原发货行的金额份额")
    return usd, bucket


def execute_money(db, case_id: int, body: MoneyExecute, user):
    with db.begin_nested():
        invoice, case, batch, target, shipment, item, app, receipt = _context(db, case_id, body, user)
        payload = {"case_id": case.id, "actor_id": user_id(user), "body": body.model_dump(mode="json")}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prior = db.scalar(select(AfterSalesExecution).where(AfterSalesExecution.request_key == body.request_key)
                          .with_for_update().execution_options(populate_existing=True))
        if prior:
            if prior.request_hash != digest:
                raise ValueError("幂等键已用于不同售后执行")
            return prior
        finance.open_date(finance.book(db), body.business_date)
        if case.version != body.expected_version or case.current_status not in {"approved", "processing"}:
            raise ValueError("仅当前版本已审批售后可以执行金额动作")
        if (shipment.state != "shipped" or app.status != "applied" or receipt.status != "active"
                or receipt.source != "local" or batch.finance_status != "confirmed"):
            raise ValueError("必须关联有效本地核销及原已发货资金应用")
        if (body.currency != invoice.currency or body.currency != batch.currency or body.currency != case.affected_goods_currency
                or case.customer_id != invoice.customer_id or case.order_id != f"local:{invoice.id}"):
            raise ValueError("售后客户、订单或原币与付款不一致")
        if (body.action == "freight_subsidy") != (app.component == "freight"):
            raise ValueError("运费补贴必须关联运费应用；商品赔付必须关联货款或首款")
        if app.component == "deposit" and not shipment.is_final:
            raise ValueError("首款仅允许从最终已发货批次执行售后")
        ensure_event_date(db, invoice.id, body.business_date, shipment.id)
        review, cap, original_cap = _approval(db, case, body)
        if body.business_date < max(case.feedback_date, case.approved_at.date(), receipt.collection_date):
            raise ValueError("执行日期不能早于反馈、批准或原核销")
        usd, bucket = _limits(db, case, body, batch, shipment, item, cap, original_cap)
        if body.amount > app.effective_amount:
            raise ValueError("金额超过该原发货应用尚未释放余额")
        cumulative = finance.money(app.released_amount + body.amount)
        cumulative_fee = (app.bank_charge if cumulative == app.amount else
                          finance.money(app.bank_charge * cumulative / app.amount))
        fee = finance.money(cumulative_fee - app.released_bank_charge)
        original = db.scalar(select(FinanceEvent).where(FinanceEvent.receipt_id == receipt.id,
            FinanceEvent.action.in_(["allocate", "opening_allocation"])).with_for_update())
        if original is None:
            raise ValueError("缺少原核销资金事件")
        execution = AfterSalesExecution(case_id=case.id, settlement_item_id=item.id, action="money_execute",
            quantity=body.quantity, business_date=body.business_date, request_key=body.request_key, request_hash=digest,
            created_by=user_id(user), payload={**payload, "application_id": app.id, "receipt_id": receipt.id,
                "original_finance_event_id": original.id, "approval_review_id": review.id, "workflow_round": case.workflow_round,
                "bucket": bucket, "amount": str(body.amount), "amount_usd": str(usd), "currency": body.currency,
                "rate_to_usd": str(batch.rate_to_usd), "released_bank_charge": str(fee)})
        db.add(execution)
        db.flush()
        app.released_amount, app.released_bank_charge = cumulative, cumulative_fee
        if cumulative == app.amount:
            app.status = "released"
        release, _ = finance.claim(db, "aftersales_release", app.id,
            body.model_copy(update={"request_key": f"aftersales-release:{execution.id}"}), user, body.business_date)
        release.receipt_id, release.receivable_id, release.batch_id = receipt.id, target.id, batch.id
        release.payload = {**release.payload, "execution_id": execution.id, "released_amount": str(body.amount),
                           "released_bank_charge": str(fee)}
        execution.payload = {**execution.payload, "release_event_id": release.id}
        db.flush()
        reverse_body = FinanceAction(request_key=f"aftersales-reverse:{execution.id}", expected_version=receipt.version,
            business_date=body.business_date, reason=body.reason, amount=body.amount)
        reversal_service.reverse(db, receipt.id, reverse_body, user, release_execution_id=execution.id)
        finance.adjust_receivable(db, target.id, AdjustmentCreate(request_key=f"aftersales-credit:{execution.id}",
            expected_version=target.version, invoice_id=invoice.id, business_date=body.business_date,
            amount=-body.amount, reason=body.reason), user)
        if fee:
            target.handling_amount = finance.money(target.handling_amount - fee)
            target.version += 1
        if body.disbursement == "bank_refund":
            finance.refund(db, batch.id, FinanceAction(request_key=f"aftersales-refund:{execution.id}",
                expected_version=batch.version, business_date=body.business_date, reason=body.reason,
                amount=body.amount, bank_reference=body.bank_reference), user)
        links = {event.action: event.id for event in db.scalars(select(FinanceEvent).where(FinanceEvent.request_key.in_([
            f"aftersales-reverse:{execution.id}", f"aftersales-credit:{execution.id}", f"aftersales-refund:{execution.id}"]))).all()}
        execution.payload = {**execution.payload, "reversal_event_id": links["reverse_allocation"],
            "credit_event_id": links["adjust_receivable"], "refund_event_id": links.get("refund"),
            "net_handling_amount": str(target.handling_amount), "disbursement": body.disbursement}
        case.current_status, case.version = "processing", case.version + 1
        db.flush()
        return execution


def ensure_money_completed(db, case):
    """Close only after the currently approved monetary promises are fulfilled."""
    codes = {action.get("code") for action in case.selected_actions_json or []} & {
        "cash_refund", "discount", "order_credit", "freight_subsidy"}
    facts = db.scalars(select(AfterSalesExecution).where(AfterSalesExecution.case_id == case.id,
        AfterSalesExecution.action == "money_execute").with_for_update().execution_options(populate_existing=True)).all()
    from types import SimpleNamespace
    for code in sorted(codes):
        _, usd_cap, cap = _approval(db, case, SimpleNamespace(action=code, currency=case.affected_goods_currency))
        matching = [fact for fact in facts if fact.payload["body"]["action"] == code]
        if any(not fact.payload.get("release_event_id") or not fact.payload.get("reversal_event_id") or not fact.payload.get("credit_event_id")
               or (fact.payload.get("disbursement") == "bank_refund" and not fact.payload.get("refund_event_id"))
               for fact in matching):
            raise ValueError("金额执行缺少完整财务凭证，不能结案")
        done = sum((Decimal(fact.payload["amount"]) for fact in matching), ZERO)
        used_usd = sum((Decimal(fact.payload["amount_usd"]) for fact in matching), ZERO)
        if used_usd > usd_cap:
            raise ValueError("历史金额执行已超过当前批准美元预算，请重新审批调整预算")
        if done != cap:
            raise ValueError(f"{code} 尚未完成批准金额：批准 {case.affected_goods_currency} {cap}，已执行 {case.affected_goods_currency} {done}；请完成执行或重新审批调整金额")


def validate_monetary_actions(case, actions):
    """Validate executable budgets before an approval decision is persisted."""
    if not case.local_invoice_item_id:
        return
    codes = {"cash_refund", "discount", "order_credit", "freight_subsidy"}
    for action in actions:
        if action.get("code") not in codes:
            continue
        if action.get("currency") != case.affected_goods_currency:
            raise ValueError("金额审批必须明确填写售后原币 currency")
        for field in ("amount_usd", "amount_original"):
            value = action.get(field)
            if field == "amount_original" and value is None and case.affected_goods_currency == "USD":
                value = action.get("amount_usd")
            try:
                amount = Decimal(str(value))
            except ArithmeticError as exc:
                raise ValueError(f"金额审批必须填写明确的 {field}") from exc
            if not amount.is_finite() or amount <= 0 or amount != finance.money(amount):
                raise ValueError(f"{field} 必须为正数且最多两位小数")
