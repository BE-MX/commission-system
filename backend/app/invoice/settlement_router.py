"""Authenticated settlement APIs. All financial mutations are service-owned."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission, require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import settlement_service as service, shipment_delivery, freight_delivery
from app.invoice.settlement_policy import capabilities
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, ReceiptBatch, Receivable, SettlementEvent
from app.invoice.settlement_schemas import ShipmentQuote, ShipmentCreate, SettlementAction, SettlementRemoteReview, BatchCreate
from app.receipt import batch_service
from app.receipt import access
from app.receipt.router import execute

router = APIRouter()


@router.get("/shipments/capabilities")
def capability(user=Depends(require_any_permission("invoice:read", "invoice:write", "receipt:write", "shipment:read"))):
    return ok(capabilities())


@router.post("/invoices/{identity}/shipment-quotes")
def quote(identity: int, body: ShipmentQuote, db: Session = Depends(get_db),
          user=Depends(require_any_permission("invoice:read", "invoice:write"))):
    return execute(db, lambda: service.quote(db, identity, body, user))


@router.post("/invoices/{identity}/shipment-settlements", dependencies=[Depends(require_permission("invoice:write"))])
def create(identity: int, body: ShipmentCreate, db: Session = Depends(get_db),
           user=Depends(require_permission("shipment:write"))):
    if body.payment and "super_admin" not in user.get("roles", []) and "receipt:write" not in user.get("permissions", []):
        raise HTTPException(403, "登记新付款需要回款写权限")
    return execute(db, lambda: service.describe(db, service.create(db, identity, body, user)))


@router.get("/shipments/order/{identity}")
def for_order(identity: int, db: Session = Depends(get_db),
              user=Depends(require_any_permission("shipment:read", "shipment:write"))):
    service.get_order(db, identity, user, writable=False)
    rows = db.query(ShipmentSettlement).filter_by(invoice_id=identity).order_by(ShipmentSettlement.sequence.desc()).all()
    return ok({"items": [service.describe(db, row) for row in rows]})


@router.get("/shipments/{identity}")
def detail(identity: int, db: Session = Depends(get_db),
           user=Depends(require_any_permission("shipment:read", "shipment:write"))):
    return ok(service.describe(db, service.get(db, identity, user)))


@router.post("/shipments/{identity}/cancel")
def cancel(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(require_permission("shipment:write"))):
    return _change(db, identity, body, user, "cancel")


@router.post("/shipments/{identity}/pause")
def pause(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(require_permission("shipment:write"))):
    return _change(db, identity, body, user, "pause")


@router.post("/shipments/{identity}/resume")
def resume(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(require_permission("shipment:write"))):
    return _change(db, identity, body, user, "resume")


def _change(db, identity, body, user, action):
    def apply():
        row = service.get(db, identity, user, lock=True)
        service.change_state(db, row, user, action, body.version, body.reason)
        return service.describe(db, row)
    return execute(db, apply)


@router.post("/shipments/{identity}/confirm-outbound")
def confirm_outbound(identity: int, body: SettlementAction, db: Session = Depends(get_db),
                     user=Depends(require_permission("shipment:write"))):
    def apply():
        row = service.get(db, identity, user)
        outbound = db.query(ShipmentOutbound).filter_by(settlement_id=row.id).one_or_none()
        if not outbound:
            raise ValueError("本批尚无待确认的出库单")
        outbound_id = outbound.id
        db.commit()
        shipment_delivery.confirm(db, outbound_id, body.version, access.user_id(user), body.reason)
        return service.describe(db, service.get(db, identity, user))
    return execute(db, apply)


@router.post("/shipments/{identity}/reconcile-freight")
def reconcile_freight(identity: int, body: SettlementRemoteReview,
                      db: Session = Depends(get_db), user=Depends(require_permission("shipment:write"))):
    if body.remote_id and "super_admin" not in user.get("roles", []) and "shipment:admin" not in user.get("permissions", []):
        raise HTTPException(403, "绑定小满运费订单需要发货结算管理权限")
    def apply():
        row = service.get(db, identity, user)
        target = db.query(Receivable).filter_by(settlement_id=row.id, kind="freight").one_or_none()
        if not target or row.version != body.version:
            raise ValueError("运费目标已变化，请刷新")
        target_id, known_id = target.id, target.remote_order_id
        db.commit()
        if body.remote_id:
            freight_delivery.bind_exact(db, target_id, body.remote_id, body.version)
        elif known_id:
            freight_delivery.refresh(db, target_id)
        else:
            raise ValueError("请从小满查到原运费订单 ID 后输入，禁止重新创建")
        db.add(SettlementEvent(settlement_id=identity, action="reconcile_freight",
                               actor_id=access.user_id(user), reason=body.reason))
        return service.describe(db, service.get(db, identity, user))
    return execute(db, apply)


@router.post("/shipments/{identity}/retry-freight")
def retry_freight(identity: int, body: SettlementAction,
                  db: Session = Depends(get_db), user=Depends(require_permission("shipment:write"))):
    def apply():
        row = service.get(db, identity, user)
        target = db.query(Receivable).filter_by(settlement_id=row.id, kind="freight").one_or_none()
        if not target:
            raise ValueError("本批没有运费目标")
        target_id = target.id
        db.commit()
        freight_delivery.retry_failed(db, target_id, body.version)
        db.add(SettlementEvent(settlement_id=identity, action="retry_freight",
                               actor_id=access.user_id(user), reason=body.reason))
        return service.describe(db, service.get(db, identity, user))
    return execute(db, apply)


@router.post("/shipments/{identity}/reconcile-outbound")
def reconcile_outbound(identity: int, body: SettlementRemoteReview,
                       db: Session = Depends(get_db), user=Depends(require_permission("shipment:write"))):
    if body.remote_id and "super_admin" not in user.get("roles", []) and "shipment:admin" not in user.get("permissions", []):
        raise HTTPException(403, "绑定小满出库单需要发货结算管理权限")
    def apply():
        row = service.get(db, identity, user)
        outbound = db.query(ShipmentOutbound).filter_by(settlement_id=row.id).one_or_none()
        if not outbound or row.version != body.version:
            raise ValueError("出库任务已变化，请刷新")
        outbound_id, known_id = outbound.id, outbound.remote_id
        db.commit()
        if body.remote_id:
            shipment_delivery.bind_exact(db, outbound_id, body.remote_id, body.version)
        elif known_id:
            shipment_delivery.refresh(db, outbound_id)
        else:
            raise ValueError("请从小满查到原出库单 ID 后输入，禁止重新创建")
        db.add(SettlementEvent(settlement_id=identity, action="reconcile_outbound",
                               actor_id=access.user_id(user), reason=body.reason))
        return service.describe(db, service.get(db, identity, user))
    return execute(db, apply)


@router.post("/shipments/{identity}/retry-outbound")
def retry_outbound(identity: int, body: SettlementAction,
                   db: Session = Depends(get_db), user=Depends(require_permission("shipment:write"))):
    def apply():
        row = service.get(db, identity, user)
        outbound = db.query(ShipmentOutbound).filter_by(settlement_id=row.id).one_or_none()
        if not outbound:
            raise ValueError("本批没有出库任务")
        outbound_id = outbound.id
        db.commit()
        shipment_delivery.retry_failed(db, outbound_id, body.version)
        db.add(SettlementEvent(settlement_id=identity, action="retry_outbound",
                               actor_id=access.user_id(user), reason=body.reason))
        return service.describe(db, service.get(db, identity, user))
    return execute(db, apply)


@router.post("/receipts/batches")
def create_batch(body: BatchCreate, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    return execute(db, lambda: batch_service.describe(db, batch_service.create(db, body, user), user))


@router.get("/receipts/batches/{identity}")
def batch_detail(identity: int, db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin"))):
    row = db.get(ReceiptBatch, identity)
    if not row:
        raise HTTPException(404, "回款批次不存在")
    return ok(batch_service.describe(db, row, user))


@router.post("/receipts/batches/{identity}/void-entry")
def void_entry(identity: int, body: SettlementAction, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    def apply():
        row = db.get(ReceiptBatch, identity)
        if not row:
            raise HTTPException(404, "回款批次不存在")
        batch_service.void_entry(db, row, user, body.version, body.reason)
        return batch_service.describe(db, row, user)
    return execute(db, apply)
