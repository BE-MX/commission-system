"""Shipment, receipt, and customer delivery reconciliation endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic import shipment_service, receipt_service, file_service
from app.domestic.shipment_schemas import ShipmentCreate, ShipmentReceive, ReceiptCreate, ReceiptAllocationInput

router = APIRouter()


def _scope(user):
    return "super_admin" in (user.get("roles") or []) or "domestic:read_all" in (user.get("permissions") or [])


def _customer_scope(db, customer_id, user):
    from app.domestic.models import DomesticCustomer, DomesticOrder
    customer = db.get(DomesticCustomer, customer_id)
    uid = int(user["sub"])
    if not customer:
        raise HTTPException(404, "客户不存在")
    full_scope = _scope(user) or "domestic_customer:admin" in (user.get("permissions") or []) or customer.owner_user_id == uid
    if not full_scope and not db.query(DomesticOrder.id).filter_by(customer_id=customer_id, created_by=uid, deleted_flag=0).first():
        raise HTTPException(404, "客户不存在")
    return full_scope


@router.get("/delivery-customers")
def delivery_customers(keyword: str = "", db: Session = Depends(get_db),
                       user: dict = Depends(require_any_permission("domestic:read", "domestic:write", "domestic:recharge", "domestic:admin"))):
    from sqlalchemy import or_
    from app.domestic.models import DomesticCustomer, DomesticOrder
    uid = int(user["sub"])
    q = db.query(DomesticCustomer).filter(DomesticCustomer.status == 1)
    if not _scope(user) and "domestic_customer:admin" not in (user.get("permissions") or []):
        own_orders = db.query(DomesticOrder.id).filter(DomesticOrder.customer_id == DomesticCustomer.id, DomesticOrder.created_by == uid, DomesticOrder.deleted_flag == 0).exists()
        q = q.filter(or_(DomesticCustomer.owner_user_id == uid, own_orders))
    if keyword:
        q = q.filter(DomesticCustomer.shop_name.contains(keyword[:120]))
    return ok([{"id": c.id, "shop_name": c.shop_name, "settle_mode": c.settle_mode, "can_operate_funds": c.owner_user_id == uid or "super_admin" in (user.get("roles") or []) or "domestic_customer:admin" in (user.get("permissions") or [])} for c in q.order_by(DomesticCustomer.shop_name).limit(100).all()])


def _run(db, operation):
    try:
        return ok(operation())
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.get("/shipment-candidates")
def shipment_candidates(customer_id: int, db: Session = Depends(get_db),
                        user: dict = Depends(require_any_permission("domestic:read", "domestic:write", "domestic:admin", "domestic:recharge"))):
    # Candidate picker offers only writable orders, even for read_all users.
    return ok(shipment_service.candidate_rows(db, customer_id, int(user["sub"])))


@router.post("/shipments")
def create_shipment(payload: ShipmentCreate, db: Session = Depends(get_db),
                    user: dict = Depends(require_any_permission("domestic:write", "domestic:admin"))):
    return _run(db, lambda: shipment_service.create_shipment(db, payload, int(user["sub"])))


@router.get("/customers/{customer_id}/delivery")
def customer_delivery(customer_id: int, db: Session = Depends(get_db),
                      user: dict = Depends(require_any_permission("domestic:read", "domestic:write", "domestic:recharge", "domestic:admin"))):
    full_scope = _customer_scope(db, customer_id, user)
    # Customer owner can reconcile all their customer's shipments.
    return ok({"items": shipment_service.list_shipments(db, customer_id, int(user["sub"]), full_scope),
               "summary": shipment_service.customer_summary(db, customer_id, None if full_scope else int(user["sub"])),
               "scope": "customer" if full_scope else "own_orders",
               "receipts": receipt_service.list_receipts(db, customer_id, None if full_scope else int(user["sub"]))})



@router.post("/shipments/{shipment_id}/receive")
def receive_shipment(shipment_id: int, payload: ShipmentReceive, db: Session = Depends(get_db),
                     user: dict = Depends(require_any_permission("domestic:write", "domestic:admin"))):
    return _run(db, lambda: shipment_service.confirm_received(db, shipment_id, payload, int(user["sub"])))


@router.post("/shipments/{shipment_id}/cancel")
def cancel_shipment(shipment_id: int, db: Session = Depends(get_db),
                    user: dict = Depends(require_any_permission("domestic:write", "domestic:admin"))):
    return _run(db, lambda: shipment_service.cancel_shipment(db, shipment_id, int(user["sub"])))


@router.post("/customers/{customer_id}/receipts")
async def create_receipt(customer_id: int, data: str = Form(..., max_length=20000), file: UploadFile = File(...),
                         db: Session = Depends(get_db),
                         user: dict = Depends(require_any_permission("domestic:recharge", "domestic:admin"))):
    from app.domestic.router import _can_operate_all_customers, _ensure_customer_owner
    _ensure_customer_owner(db, customer_id, user)
    try:
        payload = ReceiptCreate.model_validate_json(data)
        content = await file.read()
        file_service.validate_voucher_upload(file.filename, file.content_type or "", len(content))
        path = file_service.store_bytes(file.filename, content)
        result = receipt_service.create_receipt_request(db, customer_id, payload, path, int(user["sub"]),
                                                       _can_operate_all_customers(user))
    except (ValueError, ValidationError, file_service.FileValidationError) as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    # Existing fund review badge/list discovers this request; no new delivery channel.
    return ok(result, message="收款申请已提交，审核通过后入账并核销")


@router.post("/customer-requests/{request_id}/allocate")
def allocate_receipt(request_id: int, payload: list[ReceiptAllocationInput], db: Session = Depends(get_db),
                     user: dict = Depends(require_any_permission("domestic:recharge", "domestic:admin"))):
    from app.domestic.router import _can_operate_all_customers
    if not payload or len(payload) > 200 or len({r.shipment_id for r in payload}) != len(payload):
        raise HTTPException(400, "请选择不重复的核销批次")
    return _run(db, lambda: receipt_service.allocate_approved_receipt(
        db, request_id, payload, int(user["sub"]), _can_operate_all_customers(user)))
