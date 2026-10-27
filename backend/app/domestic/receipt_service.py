"""Receipt applications share approval/voucher workflow, without recharge membership effects."""
from decimal import Decimal
from sqlalchemy import func
from app.domestic import balance_service
from app.domestic.models import DomesticCustomer, DomesticCustomerRequest, DomesticCustomerLedger
from app.domestic.shipment_models import DomesticShipment, DomesticReceiptAllocation
from app.domestic.shipment_service import payload_hash, paid_amount


def allocation_view(db, request_id):
    return [{"shipment_id": shipment_id, "shipment_no": number, "amount": float(amount)}
            for shipment_id, number, amount in db.query(DomesticReceiptAllocation.shipment_id, DomesticShipment.shipment_no, func.sum(DomesticReceiptAllocation.amount)).join(
                DomesticShipment, DomesticShipment.id == DomesticReceiptAllocation.shipment_id,
            ).filter(DomesticReceiptAllocation.request_id == request_id)
            .group_by(DomesticReceiptAllocation.shipment_id, DomesticShipment.shipment_no).order_by(DomesticReceiptAllocation.shipment_id).all()]


def _lock_and_validate_batches(db, customer_id, allocations):
    ids = sorted(row.shipment_id for row in allocations)
    batches = db.query(DomesticShipment).filter(DomesticShipment.id.in_(ids)).order_by(
        DomesticShipment.id,
    ).populate_existing().with_for_update().all()
    by_id = {batch.id: batch for batch in batches}
    if len(by_id) != len(ids) or any(batch.customer_id != customer_id for batch in batches):
        raise ValueError("只能核销同一客户的发货批次")
    if any(batch.cancelled_at for batch in batches):
        raise ValueError("发货批次已取消，不能登记收款核销")
    for row in allocations:
        # Locking allocation reads avoid a stale repeatable-read snapshot at approval.
        paid_rows = db.query(DomesticReceiptAllocation.amount).filter(
            DomesticReceiptAllocation.shipment_id == row.shipment_id,
            DomesticReceiptAllocation.ledger_id.isnot(None),
        ).with_for_update().all()
        paid = sum((balance_service.money(value) for (value,) in paid_rows), Decimal(0))
        if balance_service.money(row.amount) > balance_service.money(by_id[row.shipment_id].total_amount) - paid:
            raise ValueError("核销金额超过批次未结金额，请刷新后重试")


def _create_receipt_once(db, customer_id, payload, voucher_path, user_id, can_operate_all=False):
    from app.domestic.request_service import _lock_customer, _request_view
    db.info["domestic_actor_id"] = user_id
    customer = _lock_customer(db, customer_id, user_id, can_operate_all)
    if customer.settle_mode != "credit":
        raise ValueError("按批收款仅适用于先下单后付款客户")
    if not voucher_path:
        raise ValueError("请上传银行流水或转账截图")
    fingerprint = payload_hash(payload)
    existing = db.query(DomesticCustomerRequest).filter_by(request_id=payload.request_id).first()
    if existing:
        if existing.customer_id != customer_id or existing.created_by != user_id or existing.payload_hash != fingerprint:
            raise ValueError("该请求号已用于不同收款内容")
        return _request_view(existing, replayed=True)
    _lock_and_validate_batches(db, customer_id, payload.allocations)
    req = DomesticCustomerRequest(
        customer_id=customer_id, request_type="receipt", amount=payload.amount,
        receipt_date=payload.receipt_date, payload_hash=fingerprint,
        voucher_path=voucher_path, remark=payload.remark, change_membership=0,
        request_id=payload.request_id, business_key=f"receipt:{customer_id}:{payload.request_id}",
        created_by=user_id, status="pending",
    )
    db.add(req)
    db.flush()
    db.add_all([DomesticReceiptAllocation(request_id=req.id, shipment_id=row.shipment_id, amount=row.amount,
                    business_key=f"receipt-initial:{req.id}:{row.shipment_id}", created_by=user_id)
                for row in payload.allocations])
    db.commit()
    return _request_view(req)


def create_receipt_request(db, customer_id, payload, voucher_path, user_id, can_operate_all=False):
    from sqlalchemy.exc import IntegrityError
    from app.domestic.request_service import _request_view
    try:
        return _create_receipt_once(db, customer_id, payload, voucher_path, user_id, can_operate_all)
    except IntegrityError as exc:
        db.rollback()
        existing = db.query(DomesticCustomerRequest).filter_by(request_id=payload.request_id).first()
        if existing and existing.customer_id == customer_id and existing.created_by == user_id and existing.payload_hash == payload_hash(payload):
            return _request_view(existing, replayed=True)
        raise ValueError("收款请求发生冲突，请核对原申请") from exc


def approve_receipt(db, req):
    # request -> customer -> batch; this path never takes an order lock.
    customer = db.query(DomesticCustomer).filter_by(id=req.customer_id).populate_existing().with_for_update().one()
    allocations = db.query(DomesticReceiptAllocation).filter_by(request_id=req.id).with_for_update().all()
    _lock_and_validate_batches(db, req.customer_id, allocations)
    ledger = balance_service.apply_balance_change(
        db, customer_id=req.customer_id, amount=req.amount, transaction_type="receipt",
        user_id=req.created_by, remark=req.remark, business_key=req.business_key,
    )
    for allocation in allocations:
        allocation.ledger_id = ledger.id
    return {"ledger_id": ledger.id, "current_balance": float(customer.balance),
            "allocations": allocation_view(db, req.id)}


def allocate_approved_receipt(db, request_id, allocations, user_id, can_operate_all=False):
    from app.domestic.request_service import _lock_customer
    # All approval/allocation writers use request -> customer -> batch.
    req = db.query(DomesticCustomerRequest).filter_by(id=request_id).populate_existing().with_for_update().first()
    if not req or req.request_type != "receipt" or req.status != "approved":
        raise ValueError("只能核销已审核通过的收款")
    _lock_customer(db, req.customer_id, user_id, can_operate_all)
    existing = {}
    for r in db.query(DomesticReceiptAllocation).filter_by(request_id=req.id).with_for_update().all():
        existing[r.shipment_id] = existing.get(r.shipment_id, Decimal(0)) + r.amount
    from types import SimpleNamespace
    new_rows = []
    for row in allocations:
        before = existing.get(row.shipment_id, Decimal(0))
        target = balance_service.money(row.amount)
        if target < before:
            raise ValueError("累计核销金额不能减少，历史核销记录保留")
        if target > before:
            new_rows.append(SimpleNamespace(shipment_id=row.shipment_id, amount=target-before, target=target))
    total = sum(existing.values(), Decimal(0)) + sum((r.amount for r in new_rows), Decimal(0))
    if total > req.amount:
        raise ValueError("核销合计不能超过收款金额")
    _lock_and_validate_batches(db, req.customer_id, new_rows)
    ledger = db.query(DomesticCustomerLedger).filter_by(business_key=req.business_key).with_for_update().one()
    db.add_all([DomesticReceiptAllocation(request_id=req.id, shipment_id=row.shipment_id, amount=row.amount,
        ledger_id=ledger.id, business_key=f"receipt-allocate:{req.id}:{row.shipment_id}:{row.target}", created_by=user_id) for row in new_rows])
    db.commit()
    return allocation_view(db, req.id)

def list_receipts(db, customer_id, user_id=None):
    from app.domestic.models import DomesticCustomerRequest
    query = db.query(DomesticCustomerRequest).filter_by(customer_id=customer_id, request_type="receipt")
    if user_id is not None:
        query = query.filter_by(created_by=user_id)
    return [{"id": r.id, "amount": float(r.amount), "receipt_date": r.receipt_date, "status": r.status,
             "request_id": r.request_id, "unallocated_amount": float(r.amount) - sum(a["amount"] for a in allocation_view(db, r.id)),
             "allocations": allocation_view(db, r.id)}
            for r in query.order_by(DomesticCustomerRequest.id.desc()).all()]
