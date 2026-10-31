"""Approved compensation conserves cash, AR and shipment faces."""
from datetime import date, datetime
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.aftersales.local_money import execute_money, ensure_money_completed
from app.aftersales.money_schemas import MoneyExecute
from app.aftersales.models import AfterSalesReview, AfterSalesExecution
from app.finance import service as money
from app.invoice.settlement_models import SettlementApplication, Receivable, ReceiptBatch
from app.receipt.models import Receipt
from tests.test_aftersales_local import shipped_case
from tests.test_invoice_commerce import buyer
from tests.test_finance_local import finance
from tests.test_inventory_local import stock


def prepared(db, stock, finance, action="order_credit", cap="20", *, currency='USD'):
    case, invoice, item, warehouse, user, _ = shipped_case(db, stock, finance, currency=currency)
    case.requires_return = False
    case.approved_at = datetime(2026, 10, 3)
    case.selected_actions_json = [dict(code=action, amount_usd=cap, currency="USD")]
    db.add(AfterSalesReview(case_id=case.id, workflow_round=case.workflow_round, reviewer_role="director",
        reviewer_user_id=int(user["sub"]), reviewer_name_snapshot="Director", decision="approve",
        compensation_snapshot_json={"actions": case.selected_actions_json}))
    app = db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == item.settlement_id,
        SettlementApplication.component == ("freight" if action == "freight_subsidy" else "goods")))
    db.flush()
    return case, invoice, item, user, app


def command(case, item, app, amount="20", key="money", **changes):
    values = dict(request_key=key, expected_version=case.version, settlement_item_id=item.id,
        application_id=app.id, quantity=3, action=case.selected_actions_json[0]["code"], amount=amount,
        currency="USD", disbursement="customer_credit", business_date=date(2026, 10, 3), reason="approved remedy")
    values.update(changes)
    return MoneyExecute(**values)


def test_credit_evidence_and_idempotency(db, stock, finance):
    case, invoice, item, user, app = prepared(db, stock, finance)
    receipt = db.get(Receipt, app.receipt_id)
    target = db.get(Receivable, receipt.receivable_id)
    batch = db.get(ReceiptBatch, receipt.batch_id)
    original = (app.amount, app.bank_charge, receipt.amount, receipt.bank_charge, invoice.total_amount)
    ar_before, paid_before, allocated = target.amount, target.paid_amount, batch.allocated_amount
    body = command(case, item, app)
    row = execute_money(db, case.id, body, user)
    assert execute_money(db, case.id, body, user).id == row.id
    assert (app.amount, app.bank_charge, receipt.amount, receipt.bank_charge, invoice.total_amount) == original
    assert app.released_amount == receipt.reversed_amount == 20
    assert target.amount + target.adjustment_amount == ar_before - 20 and target.paid_amount == paid_before - 20
    assert batch.allocated_amount == allocated - 20 and batch.refunded_amount == 0
    assert row.payload["reversal_event_id"] and row.payload["credit_event_id"] and not row.payload["refund_event_id"]
    ensure_money_completed(db, case)
    with pytest.raises(ValueError, match="幂等"):
        execute_money(db, case.id, body.model_copy(update={"amount": Decimal(1)}), user)


def test_refund_failure_rolls_back(db, stock, finance, monkeypatch):
    case, invoice, item, user, app = prepared(db, stock, finance, "cash_refund")
    receipt = db.get(Receipt, app.receipt_id)
    target = db.get(Receivable, receipt.receivable_id)
    original = (app.released_amount, receipt.reversed_amount, target.amount, target.paid_amount, case.version)
    def fail(*args, **kwargs):
        raise ValueError("bank failure")
    monkeypatch.setattr(money, "refund", fail)
    with pytest.raises(ValueError, match="bank failure"):
        execute_money(db, case.id, command(case, item, app, disbursement="bank_refund", bank_reference="BANK-REF"), user)
    assert (app.released_amount, receipt.reversed_amount, target.amount, target.paid_amount, case.version) == original
    assert not db.scalars(select(AfterSalesExecution)).all()


def test_partial_completion_and_approval_cap(db, stock, finance):
    case, invoice, item, user, app = prepared(db, stock, finance)
    execute_money(db, case.id, command(case, item, app, "10"), user)
    with pytest.raises(ValueError, match="尚未完成"):
        ensure_money_completed(db, case)
    with pytest.raises(ValueError, match="审批美元上限"):
        execute_money(db, case.id, command(case, item, app, "11", "too-much"), user)
    execute_money(db, case.id, command(case, item, app, "10", "remaining"), user)
    ensure_money_completed(db, case)


def test_return_and_quantity_gates(db, stock, finance):
    case, invoice, item, user, app = prepared(db, stock, finance, cap="90")
    case.requires_return = True
    db.flush()
    with pytest.raises(ValueError, match="先收齐"):
        execute_money(db, case.id, command(case, item, app), user)
    case.requires_return = False
    db.flush()
    with pytest.raises(ValueError, match="金额份额"):
        execute_money(db, case.id, command(case, item, app, "40", quantity=1), user)


def test_freight_actual_refund(db, stock, finance):
    case, invoice, item, user, app = prepared(db, stock, finance, "freight_subsidy", "1")
    row = execute_money(db, case.id, command(case, item, app, "1", disbursement="bank_refund", bank_reference="FREIGHT-REF"), user)
    assert row.payload["refund_event_id"]
    assert db.get(ReceiptBatch, db.get(Receipt, app.receipt_id).batch_id).refunded_amount == 1
    assert app.status == "released" and app.effective_amount == 0
    ensure_money_completed(db, case)




def test_non_usd_uses_original_currency_completion_and_frozen_budget(db, stock, finance):
    # Construct the original CNY contract and bank principal before any posting;
    # a confirmed USD principal must never be converted by rewriting its row.
    finance[2].currency = 'CNY'
    case, invoice, item, user, app = prepared(db, stock, finance, cap="3", currency='CNY')
    receipt = db.get(Receipt, app.receipt_id)
    batch = db.get(ReceiptBatch, receipt.batch_id)
    assert invoice.currency == batch.currency == case.affected_goods_currency == 'CNY'
    assert batch.rate_to_usd == Decimal('0.14285714')
    case.selected_actions_json = [dict(code="order_credit", currency="CNY", amount_usd="3", amount_original="20")]
    db.scalar(select(AfterSalesReview).where(AfterSalesReview.case_id == case.id)).compensation_snapshot_json = {
        "actions": case.selected_actions_json}
    db.flush()
    row = execute_money(db, case.id, command(case, item, app, currency="CNY"), user)
    assert Decimal(row.payload["amount_usd"]) == Decimal("2.85714280")
    # Future FX configuration must not rewrite the original bank conversion.
    from app.finance.models import Currency
    db.get(Currency, 'USD').rate_to_cny = Decimal('8')
    assert Decimal(row.payload['rate_to_usd']) == Decimal('0.14285714')
    ensure_money_completed(db, case)
    with pytest.raises(ValueError, match="批准原币金额"):
        execute_money(db, case.id, command(case, item, app, "0.01", "extra", currency="CNY"), user)


def test_non_usd_requires_explicit_original_approval(db, stock, finance):
    from app.aftersales.local_money import _approval, validate_monetary_actions
    from types import SimpleNamespace
    case, invoice, item, user, app = prepared(db, stock, finance)
    case.affected_goods_currency = "CNY"
    case.selected_actions_json = [dict(code="order_credit", currency="CNY", amount_usd="20")]
    db.scalar(select(AfterSalesReview).where(AfterSalesReview.case_id == case.id)).compensation_snapshot_json = {
        "actions": case.selected_actions_json}
    db.flush()
    with pytest.raises(ValueError, match="amount_original"):
        _approval(db, case, SimpleNamespace(action="order_credit", currency="CNY"))
    with pytest.raises(ValueError, match="amount_original"):
        validate_monetary_actions(case, case.selected_actions_json)


def test_full_release_conserves_original_fee_and_usd_event(db, stock, finance):
    from app.finance.models import FinanceEvent
    case, invoice, item, user, app = prepared(db, stock, finance, cap="93")
    receipt = db.get(Receipt, app.receipt_id)
    original = db.scalar(select(FinanceEvent).where(FinanceEvent.receipt_id == receipt.id, FinanceEvent.action == "allocate"))
    execute_money(db, case.id, command(case, item, app, "40"), user)
    execute_money(db, case.id, command(case, item, app, "53", "tail"), user)
    reversals = db.scalars(select(FinanceEvent).where(FinanceEvent.receipt_id == receipt.id, FinanceEvent.action == "reverse_allocation")).all()
    assert app.released_amount == app.amount and app.released_bank_charge == app.bank_charge
    assert receipt.effective_amount == receipt.effective_bank_charge == 0
    assert sum(event.commission_amount_usd for event in reversals) == -original.commission_amount_usd
    ensure_money_completed(db, case)


def test_reapproval_does_not_reset_historical_spending(db, stock, finance):
    case, invoice, item, user, app = prepared(db, stock, finance)
    execute_money(db, case.id, command(case, item, app, "15"), user)
    case.workflow_round += 1
    db.add(AfterSalesReview(case_id=case.id, workflow_round=case.workflow_round, reviewer_role="director",
        reviewer_user_id=int(user["sub"]), reviewer_name_snapshot="Director", decision="approve",
        compensation_snapshot_json={"actions": case.selected_actions_json}))
    db.flush()
    with pytest.raises(ValueError, match="审批美元上限"):
        execute_money(db, case.id, command(case, item, app, "6", "new-round"), user)
    execute_money(db, case.id, command(case, item, app, "5", "finish-round"), user)
    ensure_money_completed(db, case)


def test_final_presale_deposit_requires_audited_release(db, stock, finance):
    from app.aftersales import service
    from app.auth.models import ArkUser
    from app.invoice.settlement_models import SettlementItem
    from tests.test_aftersales_workflow import _payload
    from tests.test_local_fulfillment import setup_order, allocate, create_batch, act, inspect
    from tests.test_finance_local import cmd
    invoice, batch, user, warehouse = setup_order(db, stock, finance, presale=True)
    target = db.scalar(select(Receivable).where(Receivable.kind == "goods"))
    deposit = allocate(db, invoice, batch, user, target, "21", "deposit", deposit=True)
    shipment = create_batch(db, invoice, user, warehouse, 3, "final")
    allocate(db, invoice, batch, user, target, shipment.quote["goods_payment_due"], "balance", settlement=shipment)
    act(db, shipment, user, "ready", "ready")
    inspection = inspect(db, shipment, user)
    act(db, shipment, user, "ship", "ship", inspection_version=inspection.edit_version)
    with pytest.raises(ValueError, match="预售首款"):
        money.reverse_allocation(db, deposit.id, cmd("ordinary-reverse", deposit.version, amount="1"), user)
    actor = db.get(ArkUser, int(user["sub"]))
    payload = _payload().model_copy(update={"product_id": None, "local_invoice_item_id": invoice.items[0].id,
        "order_id": f"local:{invoice.id}", "customer_id": invoice.customer_id, "purchase_date": invoice.invoice_date,
        "feedback_date": date(2026, 10, 3), "quantity": Decimal(3)})
    case = service.create_case(db, payload, actor, scope=user)
    case.current_status, case.approved_at = "approved", datetime(2026, 10, 3)
    case.selected_actions_json = [dict(code="order_credit", amount_usd="21", currency="USD")]
    db.add(AfterSalesReview(case_id=case.id, workflow_round=case.workflow_round, reviewer_role="director",
        reviewer_user_id=actor.id, reviewer_name_snapshot="Director", decision="approve",
        compensation_snapshot_json={"actions": case.selected_actions_json}))
    db.flush()
    item = db.scalar(select(SettlementItem).where(SettlementItem.settlement_id == shipment.id))
    app = db.scalar(select(SettlementApplication).where(SettlementApplication.receipt_id == deposit.id))
    execute_money(db, case.id, command(case, item, app, "21"), user)
    assert deposit.effective_amount == 0 and app.effective_amount == 0
    assert app.released_bank_charge == Decimal("1")
    ensure_money_completed(db, case)


def test_partial_aftersales_first_shipment_does_not_block_remaining_dispatch(db, stock, finance):
    from app.aftersales import service
    from app.auth.models import ArkUser
    from app.invoice.settlement_models import SettlementItem
    from tests.test_aftersales_workflow import _payload
    from tests.test_local_fulfillment import setup_order, allocate, create_batch, act, inspect
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    for target in db.scalars(select(Receivable)).all():
        allocate(db, invoice, batch, user, target, target.amount, target.kind)
    first = create_batch(db, invoice, user, warehouse, 1, "first")
    act(db, first, user, "first-ready", "ready")
    inspection = inspect(db, first, user)
    act(db, first, user, "first-shipped", "ship", inspection_version=inspection.edit_version)
    actor = db.get(ArkUser, int(user["sub"]))
    payload = _payload().model_copy(update={"product_id": None, "local_invoice_item_id": invoice.items[0].id,
        "order_id": f"local:{invoice.id}", "customer_id": invoice.customer_id, "purchase_date": invoice.invoice_date,
        "feedback_date": date(2026, 10, 3), "quantity": Decimal(1)})
    case = service.create_case(db, payload, actor, scope=user)
    case.current_status, case.approved_at = "approved", datetime(2026, 10, 3)
    case.selected_actions_json = [dict(code="order_credit", amount_usd="10", currency="USD")]
    db.add(AfterSalesReview(case_id=case.id, workflow_round=case.workflow_round, reviewer_role="director",
        reviewer_user_id=actor.id, reviewer_name_snapshot="Director", decision="approve",
        compensation_snapshot_json={"actions": case.selected_actions_json}))
    db.flush()
    item = db.scalar(select(SettlementItem).where(SettlementItem.settlement_id == first.id))
    app = db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id == first.id,
        SettlementApplication.component == "goods"))
    execute_money(db, case.id, command(case, item, app, "10", quantity=1), user)
    assert app.amount == 31 and app.effective_amount == 21
    assert app.effective_bank_charge == Decimal("0.68")
    second = create_batch(db, invoice, user, warehouse, 2, "second")
    assert second.quote["goods_payment_due"] == "62.00"
    act(db, second, user, "second-ready", "ready")
    inspection = inspect(db, second, user)
    act(db, second, user, "second-shipped", "ship", inspection_version=inspection.edit_version)
    assert invoice.commerce_status == "shipped" and invoice.items[0].stock_shipped_quantity == 3
    assert sum(app.effective_amount for app in db.scalars(select(SettlementApplication)).all()) == 84


def test_usd_explicit_null_original_amount_approval_execution_completion(db, stock, finance):
    from app.aftersales.local_money import validate_monetary_actions
    case, invoice, item, user, app = prepared(db, stock, finance)
    actions = [dict(code="order_credit", currency="USD", amount_usd="20", amount_original=None)]
    validate_monetary_actions(case, actions)
    case.selected_actions_json = actions
    db.scalar(select(AfterSalesReview).where(AfterSalesReview.case_id == case.id)).compensation_snapshot_json = {"actions": actions}
    db.flush()
    execute_money(db, case.id, command(case, item, app), user)
    ensure_money_completed(db, case)
