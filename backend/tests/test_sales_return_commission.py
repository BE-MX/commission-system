from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.commission import CommissionBatch, CommissionDetail, SyncedPayment, PaymentCommissionStatus
from app.models.customer import CustomerCommissionSnapshot
from app.sales_return.models import SalesReturn, ReturnReceipt, ReturnAllocation
from app.sales_return.commission import freeze_basis, project_receipt, return_rows, PendingCommissionBasis
from app.services.commission_calculator import calculate_commission, confirm_batch, void_batch


def original(db, pid="original", principal="1000", sp="20", sv="15", sv2="5"):
    batch = CommissionBatch(batch_name="Original", period_start=date(2025, 1, 1),
                            period_end=date(2025, 3, 31), status="calculated")
    db.add(batch)
    db.flush()
    db.add(SyncedPayment(payment_id=pid, source="okki", order_id="old-order", customer_id="customer",
                         payment_date=date(2025, 2, 1), payment_amount=Decimal(principal), service_fee=0))
    db.add(CommissionDetail(batch_id=batch.id, payment_id=pid, order_id="old-order", customer_id="customer",
                            payment_amount=Decimal(principal), salesperson_id="old-A", salesperson_rate="0.0200",
                            salesperson_commission=sp, supervisor_id="old-S", supervisor_rate="0.0100",
                            supervisor_commission=sv, second_supervisor_id="old-T", second_supervisor_rate="0.0050",
                            second_supervisor_commission=sv2, calc_rule_note="Actual dual-develop 1.5%", status="pending"))
    db.add(PaymentCommissionStatus(payment_id=pid, batch_id=batch.id))
    db.flush()
    return batch


def refund(db, amount, pid="original", principal="1000", day=date(2026, 9, 1), total=None):
    key = f"return-{db.query(SalesReturn).count()}"
    document = SalesReturn(return_no=key, order_id="old-order", order_no="OLD", customer_id="customer",
                           customer_name="Customer", owner_okki_user_id="old-A", return_type="refund_only",
                           currency="USD", reason_code="quality", reason="quality", status="effective",
                           request_key=key, request_hash=key, created_by=1)
    db.add(document)
    db.flush()
    allocation = ReturnAllocation(return_id=document.id, original_payment_id=pid,
                                  original_principal=principal, original_principal_usd=principal,
                                  refund_amount=amount, refund_amount_usd=amount, basis=freeze_basis(db, pid))
    receipt = ReturnReceipt(return_id=document.id, receipt_no=f"receipt-{key}", effect_kind="activate", order_id="old-order", customer_id="customer",
                            currency="USD", amount=-Decimal(total or amount), amount_usd=-Decimal(total or amount), collection_date=day,
                            created_by=1)
    db.add_all([allocation, receipt])
    db.flush()
    return receipt, project_receipt(db, receipt)


def test_original_people_actual_rates_and_cross_period_late_event(db):
    original(db)
    receipt, payment = refund(db, "200")
    # Current assignee and rates have no bearing on return beneficiaries.
    db.add(CustomerCommissionSnapshot(customer_id="customer", salesperson_id="new-B", salesperson_rate="0.05",
                                       is_complete=True, is_current=True))
    batch = CommissionBatch(batch_name="Late Q4", period_start=date(2026, 10, 1), period_end=date(2026, 12, 31), status="draft")
    db.add(batch)
    db.flush()
    result = calculate_commission(db, batch.id)
    detail = db.query(CommissionDetail).filter_by(batch_id=batch.id).one()
    assert (detail.salesperson_id, detail.salesperson_commission) == ("old-A", Decimal("-4"))
    assert detail.supervisor_rate == Decimal("0.0100")
    assert detail.supervisor_commission == Decimal("-3")  # Actual original 15, not displayed 1%.
    assert detail.second_supervisor_commission == Decimal("-1")
    assert result.total_payments == 1
    assert project_receipt(db, receipt).id == payment.id
    assert db.query(SyncedPayment).filter_by(source="ark_return").count() == 1
    confirm_batch(db, batch.id, "admin")


def test_cumulative_rounding_full_refund_and_reversal(db):
    original(db, principal="3", sp="0.02", sv="0.01", sv2="0.01")
    receipts = [refund(db, "1", principal="3")[0] for _ in range(3)]
    rows = [return_rows(db, db.query(SyncedPayment).filter_by(payment_id=f"ark_return:{r.id}").one())[0] for r in receipts]
    assert [r["salesperson_commission"] for r in rows] == [Decimal("-0.01"), Decimal("0"), Decimal("-0.01")]
    assert sum(r["supervisor_commission"] for r in rows) == Decimal("-0.01")
    reverse = ReturnReceipt(return_id=receipts[0].return_id, receipt_no="reverse-1", effect_kind="reverse", original_receipt_id=receipts[0].id,
                            order_id="old-order", customer_id="customer", currency="USD", amount=1, amount_usd=1,
                            collection_date=date(2026, 10, 1), created_by=1)
    db.add(reverse)
    db.flush()
    reversal_rows = return_rows(db, project_receipt(db, reverse))
    assert reversal_rows[0]["salesperson_commission"] == Decimal("0.01")
    assert sum(r["salesperson_commission"] for r in rows + reversal_rows) == Decimal("-0.01")


def test_pending_basis_blocks_confirmation_and_later_arrival_requires_recalc(db):
    receipt, _ = refund(db, "20", pid="unknown", principal="100")
    batch = CommissionBatch(batch_name="Q4", period_start=date(2026, 10, 1), period_end=date(2026, 12, 31), status="draft")
    db.add(batch)
    db.flush()
    result = calculate_commission(db, batch.id)
    assert result.errors and result.total_payments == 0
    assert not db.query(PaymentCommissionStatus).count()
    with pytest.raises(PendingCommissionBasis, match="尚未完整"):
        confirm_batch(db, batch.id, "admin")
    original(db, pid="unknown", principal="100")
    void_batch(db, batch.id)
    batch2 = CommissionBatch(batch_name="Q4 retry", period_start=batch.period_start, period_end=batch.period_end, status="draft")
    db.add(batch2)
    db.flush()
    assert calculate_commission(db, batch2.id).total_payments == 1
    refund(db, "10", pid="unknown", principal="100", day=date(2026, 10, 2))
    with pytest.raises(PendingCommissionBasis):
        confirm_batch(db, batch2.id, "admin")


def test_void_original_and_refund_replay_preserves_frozen_people(db):
    old_batch = original(db)
    _, payment = refund(db, "200")
    b = CommissionBatch(batch_name="Return", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), status="draft")
    db.add(b)
    db.flush()
    calculate_commission(db, b.id)
    void_batch(db, b.id)
    void_batch(db, old_batch.id)
    db.add(CustomerCommissionSnapshot(customer_id="customer", salesperson_id="new-B", salesperson_rate="0.09",
                                       is_current=True, is_complete=True))
    replay = CommissionBatch(batch_name="Replayed", period_start=date(2025, 1, 1), period_end=date(2026, 12, 31), status="draft")
    db.add(replay)
    db.flush()
    result = calculate_commission(db, replay.id)
    assert result.total_payments == 2
    details = db.query(CommissionDetail).filter_by(batch_id=replay.id).all()
    assert {d.salesperson_id for d in details} == {"old-A"}
    assert sum(d.salesperson_commission for d in details) == Decimal("16")
    assert db.query(PaymentCommissionStatus).filter_by(payment_id=payment.payment_id).count() == 1


def test_uncomputed_original_uses_verifiable_historical_snapshot(db):
    db.add(SyncedPayment(payment_id="historic", order_id="old-order", customer_id="customer", source="okki",
                         payment_date=date(2025, 2, 1), payment_amount=100, service_fee=0))
    db.add(CustomerCommissionSnapshot(customer_id="customer", salesperson_id="historic-A", salesperson_rate="0.02",
                                       is_complete=True, is_current=False, created_at=datetime(2025, 1, 1),
                                       updated_at=datetime(2025, 1, 1),
                                       supervisor_id="historic-A", supervisor_rate="0.01"))
    db.flush()
    _, payment = refund(db, "100", pid="historic", principal="100")
    row = return_rows(db, payment)[0]
    assert row["salesperson_id"] == "historic-A" and row["salesperson_commission"] == Decimal("-2")
    assert row["supervisor_commission"] == 0
    batch = CommissionBatch(batch_name="Original catchup and refund", period_start=date(2026, 9, 1),
                            period_end=date(2026, 9, 30), status="draft")
    db.add(batch)
    db.flush()
    result = calculate_commission(db, batch.id)
    assert result.total_payments == 2  # Catch up the original even outside this batch's business dates.
    assert result.total_salesperson_commission == 0


def test_one_refund_allocates_different_original_people_and_actual_rates(db):
    original(db, pid="first", principal="100", sp="2", sv="0", sv2="0")
    original(db, pid="second", principal="200", sp="6", sv="4", sv2="0")
    second = db.query(CommissionDetail).filter_by(payment_id="second").one()
    second.salesperson_id = "another-original-person"
    receipt, payment = refund(db, "50", pid="first", principal="100", total="150")
    db.add(ReturnAllocation(return_id=receipt.return_id, original_payment_id="second", original_principal=200,
                            original_principal_usd=200, refund_amount=100, refund_amount_usd=100,
                            basis=freeze_basis(db, "second")))
    db.flush()
    rows = return_rows(db, payment)
    assert {(r["salesperson_id"], r["salesperson_commission"]) for r in rows} == {
        ("old-A", Decimal("-1")), ("another-original-person", Decimal("-3"))}
    assert sum(r["supervisor_commission"] for r in rows) == Decimal("-2")


def test_cash_principal_below_original_commission_basis_preserves_effective_rate(db):
    original(db, principal="80", sp="1.60", sv="1.20", sv2="0.40")
    first_receipt, first_payment = refund(db, "20", principal="79")
    first = return_rows(db, first_payment)[0]
    assert first["salesperson_commission"] == Decimal("-0.40")
    assert first["supervisor_commission"] == Decimal("-0.30")
    second_receipt, second_payment = refund(db, "59", principal="79")
    second = return_rows(db, second_payment)[0]
    assert second["salesperson_commission"] == Decimal("-1.18")
    assert first["supervisor_commission"] + second["supervisor_commission"] == Decimal("-1.19")
    assert first["second_supervisor_commission"] + second["second_supervisor_commission"] == Decimal("-0.40")
    assert first["salesperson_commission"] + second["salesperson_commission"] == Decimal("-1.58")
    reverse = ReturnReceipt(return_id=second_receipt.return_id, receipt_no="basis-cash-reverse", effect_kind="reverse",
                            original_receipt_id=second_receipt.id, order_id="old-order", customer_id="customer",
                            currency="USD", amount=59, amount_usd=59, collection_date=date(2026, 10, 1), created_by=1)
    db.add(reverse)
    db.flush()
    restored = return_rows(db, project_receipt(db, reverse))[0]
    assert restored["salesperson_commission"] == Decimal("1.18")
    assert restored["supervisor_commission"] == -second["supervisor_commission"]


def test_all_cash_refund_and_full_reversal_do_not_refund_bank_fee_commission(db):
    original(db, principal="80", sp="1.60", sv="1.20", sv2="0.40")
    receipt, payment = refund(db, "79", principal="79")
    row = return_rows(db, payment)[0]
    assert row["salesperson_commission"] == Decimal("-1.58")
    assert row["supervisor_commission"] == Decimal("-1.19")
    reverse = ReturnReceipt(return_id=receipt.return_id, receipt_no="all-cash-reverse", effect_kind="reverse",
                            original_receipt_id=receipt.id, order_id="old-order", customer_id="customer",
                            currency="USD", amount=79, amount_usd=79, collection_date=date(2026, 10, 1), created_by=1)
    db.add(reverse)
    db.flush()
    restored = return_rows(db, project_receipt(db, reverse))[0]
    for role in ("salesperson", "supervisor", "second_supervisor"):
        assert restored[f"{role}_commission"] == -row[f"{role}_commission"]


@pytest.mark.parametrize("changed", ["order_id", "customer_id", "commission_basis_usd"])
def test_expected_original_drift_stays_pending_on_retry(db, changed):
    original(db)
    expected = {"order_id": "old-order", "customer_id": "customer", "commission_basis_usd": "1000"}
    expected[changed] = "1001" if changed == "commission_basis_usd" else "changed-source"
    pending = freeze_basis(db, "original", expected=expected)
    assert pending["status"] == "pending_basis" and pending["expected"] == expected
    receipt, payment = refund(db, "20")
    allocation = db.query(ReturnAllocation).filter_by(return_id=receipt.return_id).one()
    allocation.basis = pending
    db.flush()
    assert freeze_basis(db, "original")["status"] == "pending_basis"
    with pytest.raises(PendingCommissionBasis, match="不一致"):
        return_rows(db, payment)
    assert allocation.basis["expected"] == expected


@pytest.mark.parametrize("changed", ["order_id", "customer_id", "commission_basis_usd"])
def test_existing_frozen_basis_cannot_be_reused_after_identity_or_principal_drift(db, changed):
    original(db)
    receipt, payment = refund(db, "20")
    original_payment = db.query(SyncedPayment).filter_by(payment_id="original").one()
    detail = db.query(CommissionDetail).filter_by(payment_id="original").one()
    expected = {"order_id": "old-order", "customer_id": "customer", "commission_basis_usd": "1000"}
    expected[changed] = "1001" if changed == "commission_basis_usd" else "changed-source"
    # Both mutable local inputs now match the new mirror. The old frozen
    # identity and base still prevent applying A's commission to B's refund.
    if changed == "commission_basis_usd":
        original_payment.payment_amount = detail.payment_amount = Decimal("1001")
    else:
        setattr(original_payment, changed, "changed-source")
        setattr(detail, changed, "changed-source")
    db.flush()
    pending = freeze_basis(db, "original", expected=expected)
    assert pending["status"] == "pending_basis" and "已有冻结" in pending["reason"]
    assert pending["expected"] == expected
    with pytest.raises(PendingCommissionBasis):
        return_rows(db, payment)


@pytest.mark.parametrize("changed", ["order_id", "customer_id", "payment_amount"])
def test_effective_original_detail_must_match_expected_identity_and_base(db, changed):
    original(db)
    detail = db.query(CommissionDetail).filter_by(payment_id="original").one()
    setattr(detail, changed, Decimal("999") if changed == "payment_amount" else "different-detail")
    db.flush()
    expected = {"order_id": "old-order", "customer_id": "customer", "commission_basis_usd": "1000"}
    pending = freeze_basis(db, "original", expected=expected)
    assert pending["status"] == "pending_basis" and "原有效提成明细" in pending["reason"]
    assert pending["expected"] == expected


def test_valid_frozen_refund_does_not_overwrite_another_pending_expected_identity(db):
    from app.sales_return.commission import frozen_positive_rows
    original(db)
    first_receipt, first_payment = refund(db, "20")
    expected_b = {"order_id": "old-order", "customer_id": "new-customer-B", "commission_basis_usd": "1000"}
    pending_b = freeze_basis(db, "original", expected=expected_b)
    second_receipt, second_payment = refund(db, "20")
    second_allocation = db.query(ReturnAllocation).filter_by(return_id=second_receipt.return_id).one()
    second_allocation.basis = pending_b
    db.flush()
    assert return_rows(db, first_payment)[0]["salesperson_commission"] == Decimal("-0.40")
    original_payment = db.query(SyncedPayment).filter_by(payment_id="original").one()
    assert frozen_positive_rows(db, original_payment)[0]["salesperson_id"] == "old-A"
    assert second_allocation.basis["status"] == "pending_basis"
    assert second_allocation.basis["expected"] == expected_b
    with pytest.raises(PendingCommissionBasis):
        return_rows(db, second_payment)
