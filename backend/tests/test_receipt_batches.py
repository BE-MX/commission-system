"""Batch payments: isolated DB, private proof and no live OKKI access."""
import io
from datetime import date
from decimal import Decimal

import pytest
from PIL import Image
from pydantic import ValidationError

from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, BatchAttachment
from app.invoice.settlement_schemas import BatchCreate
from app.receipt import attachments, batch_create_service, batch_service, edit_service, remote, service, fees
from app.receipt.models import Receipt

USER = {"sub": "1", "roles": ["super_admin"], "permissions": []}


def financial_create(db, body, user):
    """Private algorithm tests; actual current employee identity is tested on MySQL."""
    existing = db.query(ReceiptBatch).filter_by(request_key=body.request_key).first()
    if existing:
        children = batch_service.ensure_batch_access(db, existing, user)
        batch_create_service._replay(db, existing, children, body, user)
        return existing
    invoices = {item.invoice_id:db.get(Invoice,item.invoice_id) for item in body.allocations}
    evidence = {identity:edit_service.OrderEvidence(tuple(remote.invoice_binding(invoice)),(),('TT',)) for identity,invoice in invoices.items()}
    fee_evidence = {identity:fees.FeeEvidence(tuple(remote.invoice_binding(invoice)),()) for identity,invoice in invoices.items()}
    files = attachments.verify_storage(attachments._bindings(batch_service._proof_rows(db,body.attachment_ids,1)))
    return batch_service._create_verified(db,body,invoices,1,evidence,fee_evidence,files)


@pytest.fixture
def orders(db, monkeypatch, tmp_path):
    monkeypatch.setattr(attachments, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachments, "origin", lambda: "")
    monkeypatch.setattr(remote, "receipt_types", lambda db: ["TT"])
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: {"rows": []})
    monkeypatch.setattr(fees, "allocate", lambda *a, **k: Decimal(0))
    def forbidden(*a, **k):
        raise AssertionError("Live remote IO forbidden")
    monkeypatch.setattr(remote, "read", forbidden)
    result = [Invoice(invoice_no=f"B-{n}", order_type="stock", customer_id="C1",
        customer_name="Customer", sales_user_id=1, invoice_date=date(2026,9,23),
        currency="USD", total_amount=1000, status="synced", sync_status="synced",
        xiaoman_order_id=str(100+n)) for n in range(2)]
    db.add_all(result); db.commit()
    return result


def fields(db, orders, key="batch_request_key_001"):
    data = io.BytesIO(); Image.new("RGB", (2,2), "white").save(data, format="PNG")
    proof = attachments.register_upload(db, attachments.store_upload(attachments.prepare_upload(data.getvalue(), "proof.png", 1)), 1)
    db.commit()
    return dict(amount="700", collection_date="2026-09-23", payment_type="TT",
        attachment_ids=[proof.id], request_key=key, allocations=[dict(invoice_id=x.id,
            amount="350", balance_version=service.order_balance(db,x)["version"]) for x in orders])


def test_batch_exact_once_shared_proof_and_single_order_children(db, orders):
    body = BatchCreate(**fields(db,orders))
    batch = financial_create(db,body,USER); db.commit()
    assert financial_create(db,body,USER).id == batch.id
    assert db.query(ReceiptBatch).count() == 1
    assert db.query(BatchAttachment).count() == 1
    children = db.query(Receipt).all()
    assert len(children) == 2
    assert sum(r.amount for r in children) == batch.gross_amount == Decimal(700)
    assert len({r.invoice_id for r in children}) == 2
    for child in children:
        batch_service.validate_bound_proofs(db,child)
    assert service.order_balance(db,orders[0])["remaining_amount"] == "650.00"


@pytest.mark.parametrize("field,value", [("customer_id","C2"),("currency","EUR")])
def test_cross_customer_or_currency_rejected_without_partial_rows(db,orders,field,value):
    setattr(orders[1],field,value); db.commit()
    body=BatchCreate(**fields(db,orders))
    with pytest.raises(ValueError,match="同一客户"):
        financial_create(db,body,USER)
    db.rollback()
    assert db.query(Receipt).count() == db.query(ReceiptBatch).count() == 0


def test_allocation_sum_and_duplicate_order_rejected(db,orders):
    data=fields(db,orders)
    with pytest.raises(ValidationError): BatchCreate(**dict(data,amount="701"))
    with pytest.raises(ValidationError): BatchCreate(**dict(data,allocations=[data["allocations"][0]]*2))


def test_stale_second_order_rolls_back_whole_payment(db,orders):
    data=fields(db,orders)
    orders[1].total_amount=900; db.commit()
    with pytest.raises(ValueError,match="余额已变化"):
        financial_create(db,BatchCreate(**data),USER)
    db.rollback()
    assert db.query(ReceiptBatch).count() == db.query(Receipt).count() == 0


def test_overpayment_rolls_back_whole_payment(db,orders):
    data=fields(db,orders); data["amount"]="1351"; data["allocations"][1]["amount"]="1001"
    with pytest.raises(ValueError,match="余额"):
        financial_create(db,BatchCreate(**data),USER)
    db.rollback()
    assert db.query(ReceiptBatch).count() == 0


def test_proof_cannot_be_reused_in_second_batch_or_single_receipt(db,orders):
    data=fields(db,orders)
    financial_create(db,BatchCreate(**data),USER); db.commit()
    data["request_key"]="batch_request_key_002"
    for allocation,order in zip(data["allocations"],orders):
        allocation["balance_version"]=service.order_balance(db,order)["version"]
    with pytest.raises(ValueError,match="凭证已用于"):
        financial_create(db,BatchCreate(**data),USER)
    db.rollback()
    with pytest.raises(ValueError): attachments.bind(db,data["attachment_ids"],1,orders[0].id)
    assert db.query(ReceiptBatch).count() == 1


def test_void_whole_local_batch_releases_balances_without_deleting_audit(db,orders):
    batch=financial_create(db,BatchCreate(**fields(db,orders)),USER); db.commit()
    batch_service._void_financial(db,batch,batch_service.ensure_batch_access(db,batch,USER),USER,batch.version,"录入金额错误"); db.commit()
    assert batch.status == "voided"
    assert {r.status for r in db.query(Receipt)} == {"voided"}
    assert service.order_balance(db,orders[0])["remaining_amount"] == "1000.00"
    assert db.query(BatchAttachment).count() == 1


def test_void_rejected_when_any_child_has_remote_effect(db,orders):
    batch=financial_create(db,BatchCreate(**fields(db,orders)),USER); db.commit()
    db.query(Receipt).first().xiaoman_receipt_id="999"; db.commit()
    with pytest.raises(ValueError,match="远端效果"):
        batch_service._void_financial(db,batch,batch_service.ensure_batch_access(db,batch,USER),USER,batch.version,"录入金额错误")
    db.rollback()
    assert {r.status for r in db.query(Receipt)} == {"active"}


def test_batch_proof_requires_receipt_permission_even_for_invoice_owner(db,orders):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.receipt.router import proof
    body=BatchCreate(**fields(db,orders))
    financial_create(db,body,USER); db.commit()
    # The route now rebuilds the employee from DB. Seed an actual invoice-only
    # role so this remains an object-policy test, not missing-user denial.
    from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkRolePermission, ArkUserRole
    db.add(ArkUser(id=1,username="batch-proof-reader",real_name="Batch proof reader",password_hash="unused",is_active=True))
    role=ArkRole(name="batch-invoice-reader",label="Invoice only")
    permission=ArkPermission(code="invoice:read",module="invoice",action="read",label="Invoice read",kind="action")
    db.add_all([role,permission]);db.flush()
    db.add_all([ArkUserRole(user_id=1,role_id=role.id),ArkRolePermission(role_id=role.id,permission_id=permission.id)])
    db.commit()
    invoice_only={"sub":"1", "roles":[], "permissions":["invoice:read"]}
    with pytest.raises(HTTPException) as caught:
        proof(body.attachment_ids[0],Request({"type":"http","headers":[]}),db,invoice_only)
    assert caught.value.status_code==404
