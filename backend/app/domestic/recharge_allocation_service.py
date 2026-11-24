"""Reconcile posted recharge funds without changing the cash ledger or membership."""
from decimal import Decimal

from sqlalchemy import func

from app.domestic import balance_service
from app.domestic.models import DomesticCustomerLedger
from app.domestic.receipt_service import _lock_and_validate_batches, allocation_increments
from app.domestic.request_service import _lock_customer
from app.domestic.shipment_models import DomesticReceiptAllocation, DomesticShipment


def allocation_view(db, ledger_id):
    rows = db.query(
        DomesticReceiptAllocation.shipment_id, DomesticShipment.shipment_no,
        func.sum(DomesticReceiptAllocation.amount),
    ).join(DomesticShipment, DomesticShipment.id == DomesticReceiptAllocation.shipment_id).filter(
        DomesticReceiptAllocation.ledger_id == ledger_id,
    ).group_by(DomesticReceiptAllocation.shipment_id, DomesticShipment.shipment_no).order_by(
        DomesticReceiptAllocation.shipment_id,
    ).all()
    return [{"shipment_id": sid, "shipment_no": number, "amount": float(amount)}
            for sid, number, amount in rows]


def list_recharges(db, customer_id):
    ledgers = db.query(DomesticCustomerLedger).filter(
        DomesticCustomerLedger.customer_id == customer_id,
        DomesticCustomerLedger.transaction_type == "recharge",
        DomesticCustomerLedger.amount > 0,
    ).order_by(DomesticCustomerLedger.id.desc()).all()
    if not ledgers:
        return []
    grouped = {}
    rows = db.query(
        DomesticReceiptAllocation.ledger_id, DomesticReceiptAllocation.shipment_id,
        DomesticShipment.shipment_no, func.sum(DomesticReceiptAllocation.amount),
    ).join(DomesticShipment, DomesticShipment.id == DomesticReceiptAllocation.shipment_id).join(
        DomesticCustomerLedger, DomesticCustomerLedger.id == DomesticReceiptAllocation.ledger_id,
    ).filter(
        DomesticCustomerLedger.customer_id == customer_id,
        DomesticCustomerLedger.transaction_type == "recharge", DomesticCustomerLedger.amount > 0,
    ).group_by(DomesticReceiptAllocation.ledger_id, DomesticReceiptAllocation.shipment_id,
               DomesticShipment.shipment_no).order_by(DomesticReceiptAllocation.shipment_id).all()
    for ledger_id, shipment_id, shipment_no, amount in rows:
        grouped.setdefault(ledger_id, []).append({"shipment_id": shipment_id,
                                                 "shipment_no": shipment_no, "amount": float(amount)})
    result = []
    for ledger in ledgers:
        allocations = grouped.get(ledger.id, [])
        allocated = sum((balance_service.money(row["amount"]) for row in allocations), Decimal(0))
        result.append({"id": ledger.id, "created_at": ledger.created_at,
                       "amount": float(ledger.amount), "allocated_amount": float(allocated),
                       "unallocated_amount": float(balance_service.money(ledger.amount) - allocated),
                       "allocations": allocations})
    return result


def allocate_recharge(db, customer_id, ledger_id, allocations, user_id, can_operate_all=False):
    # Receipt approval, recharge allocation and batch cancellation all serialize on
    # the customer row. Do not acquire a request lock after acquiring this lock.
    _lock_customer(db, customer_id, user_id, can_operate_all)
    ledger = db.query(DomesticCustomerLedger).filter(
        DomesticCustomerLedger.id == ledger_id, DomesticCustomerLedger.customer_id == customer_id,
        DomesticCustomerLedger.transaction_type == "recharge", DomesticCustomerLedger.amount > 0,
    ).populate_existing().with_for_update().first()
    if not ledger:
        raise ValueError("只能核销该客户已入账的正数充值")
    existing = {}
    for row in db.query(DomesticReceiptAllocation).filter_by(ledger_id=ledger.id).populate_existing().with_for_update().all():
        existing[row.shipment_id] = existing.get(row.shipment_id, Decimal(0)) + row.amount
    increments = allocation_increments(existing, allocations, ledger.amount, "充值")
    _lock_and_validate_batches(db, customer_id, increments)
    db.add_all([DomesticReceiptAllocation(
        request_id=None, ledger_id=ledger.id, shipment_id=row.shipment_id, amount=row.amount,
        business_key=f"recharge-allocate:{ledger.id}:{row.shipment_id}:{row.target}", created_by=user_id,
    ) for row in increments])
    db.commit()
    return allocation_view(db, ledger.id)
