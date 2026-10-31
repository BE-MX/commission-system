"""Transition policy and draft ownership, using live employee authorization."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.auth.service import get_live_user_authorization
from app.commerce_transition import service
from app.commerce_transition.models import BankAccountDomain, BankIdentity, ResourceScope, WriterReceipt
from app.commerce_transition.schemas import LegacyBankReconciliation
from app.commerce_transition.schemas import (BankDomainRegistration, DraftRouteChange,
                                             PolicyChange, ResourceRegistration, WriterAttestation)
from app.core.database import get_db
from app.core.response import ok
from app.invoice import delegation_service, read_authority
from app.invoice.models import Invoice
from app.portal.upstream_authority import begin_employee_document_write

router = APIRouter()
logger = logging.getLogger(__name__)


def _fresh_write(db, claims, *permissions):
    # Portal barrier before the first DB query, then live roles and scopes.
    begin_employee_document_write(db, claims, *permissions)
    actor_text = str(claims.get("id") or claims.get("sub") or "")
    if not actor_text.isdecimal() or int(actor_text) < 1:
        raise HTTPException(403, "无法确认当前操作人")
    actor = int(actor_text)
    roles, perms = get_live_user_authorization(db, actor)
    if not roles or ("super_admin" not in roles and not set(permissions).issubset(perms)):
        raise HTTPException(403, "当前账号无权执行此操作")
    return {"id": actor, "roles": roles, "permissions": perms}


def _invoice_scope(db, invoice_id, user):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "发票不存在")
    if ("super_admin" not in user["roles"] and "invoice:read_all" not in user["permissions"]
            and not delegation_service.can_access_invoice(db, user["id"], invoice)):
        raise HTTPException(404, "发票不存在")
    return invoice


def _row(row):
    return {("state" if attribute.key == "status" and hasattr(type(row), "state") else attribute.key):
            getattr(row, attribute.key) for attribute in row.__mapper__.column_attrs}


def _attested(body, user):
    values = body.model_dump()
    values["evidence"] = {**values["evidence"], "recorded_by": user["id"]}
    return values


def _write(db, function, **kwargs):
    try:
        row = function(db, **kwargs)
        db.flush()
        result = _row(row)
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as error:
        db.rollback()
        logger.warning("Commerce transition command rejected: %s", type(error).__name__)
        print(f"Commerce transition command rejected: {type(error).__name__}", flush=True)
        raise HTTPException(409, str(error) if isinstance(error, ValueError) else "身份或版本冲突，请重新读取") from None
    except Exception:
        db.rollback()
        logger.exception("Commerce transition transaction failed")
        print("Commerce transition transaction failed; rolled back", flush=True)
        raise


@router.get("/status")
def status(db: Session = Depends(get_db), user=Depends(require_any_permission(
        "commerce_transition:read", "commerce_transition:admin", "invoice:read", "invoice:write"))):
    read_authority.current_user(db, user, "commerce_transition:read", "commerce_transition:admin", "invoice:read", "invoice:write")
    current = service.policy(db)
    writers = db.query(WriterReceipt).order_by(WriterReceipt.writer_key).all()
    blockers = []
    if not current.writer_inventory_verified or not current.inventory_evidence or not writers:
        blockers.append("writer_inventory_unverified")
    if any(w.state != "revoked" and (w.state != "compatible" or w.protocol_version < current.min_writer_version) for w in writers):
        blockers.append("writer_incompatible")
    ready = not blockers
    return ok({"phase": current.phase, "version": current.version,
               "local_ever_effective": current.local_ever_effective,
               "writer_inventory_verified": current.writer_inventory_verified,
               "readiness": {"ready": ready, "blockers": blockers},
               "capabilities": {"legacy": current.phase in {"legacy_only", "transition"} and (ready or current.phase == "legacy_only"),
                                "local": current.phase in {"transition", "local_only"} and ready,
                                "local_new_orders": current.phase in {"transition", "local_only"} and ready,
                                "default_route": "local" if current.phase == "local_only" and ready else "legacy",
                                "confirmed_route_change": False}})


@router.get("/writers")
def writers(db: Session = Depends(get_db), user=Depends(require_permission("commerce_transition:admin"))):
    read_authority.current_user(db, user, "commerce_transition:admin")
    return ok([_row(w) for w in db.query(WriterReceipt).order_by(WriterReceipt.writer_key)])


@router.get("/invoices/{invoice_id}/authority")
def invoice_authority(invoice_id: int, db: Session = Depends(get_db),
                      user=Depends(require_permission("commerce_transition:read"))):
    user = read_authority.current_user(db, user, "commerce_transition:read")
    if "super_admin" not in user["roles"] and "invoice:read" not in user["permissions"]:
        raise HTTPException(403, "当前账号无权读取发票")
    _invoice_scope(db, invoice_id, user)
    return ok(service.authority_view(db, invoice_id))


@router.post("/invoices/{invoice_id}/route")
def draft_route(invoice_id: int, body: DraftRouteChange, db: Session = Depends(get_db),
                user=Depends(require_permission("commerce_transition:write"))):
    user = _fresh_write(db, user, "commerce_transition:write", "invoice:write")
    service._lock_policy(db)  # Policy before invoice or original business locks.
    invoice = _invoice_scope(db, invoice_id, user)
    return _write(db, service.set_draft_route, invoice=invoice, route=body.route,
                  expected_epoch=body.expected_authority_epoch,
                  evidence={**body.evidence, "recorded_by": user["id"]})


@router.post("/policy")
def change_policy(body: PolicyChange, db: Session = Depends(get_db),
                  user=Depends(require_permission("commerce_transition:admin"))):
    user = _fresh_write(db, user, "commerce_transition:admin")
    values = body.model_dump()
    if values["inventory_evidence"] is not None:
        values["inventory_evidence"] = {**values["inventory_evidence"], "recorded_by": user["id"]}
    return _write(db, service.set_policy, **values)


@router.post("/writers")
def writer_receipt(body: WriterAttestation, db: Session = Depends(get_db),
                   user=Depends(require_permission("commerce_transition:admin"))):
    user = _fresh_write(db, user, "commerce_transition:admin")
    return _write(db, service.set_writer_receipt, **_attested(body, user))


@router.get("/resources")
def resources(db: Session = Depends(get_db), user=Depends(require_permission("commerce_transition:read"))):
    read_authority.current_user(db, user, "commerce_transition:read")
    return ok([_row(r) for r in db.query(ResourceScope).order_by(ResourceScope.id).limit(500)])


@router.post("/resources")
def register_resource(body: ResourceRegistration, db: Session = Depends(get_db),
                      user=Depends(require_permission("commerce_transition:admin"))):
    user = _fresh_write(db, user, "commerce_transition:admin")
    return _write(db, service.register_resource_scope, **_attested(body, user))


@router.get("/bank-domains")
def bank_domains(db: Session = Depends(get_db), user=Depends(require_permission("commerce_transition:admin"))):
    read_authority.current_user(db, user, "commerce_transition:admin")
    return ok([_row(r) for r in db.query(BankAccountDomain).order_by(BankAccountDomain.id).limit(500)])


@router.post("/bank-domains")
def register_domain(body: BankDomainRegistration, db: Session = Depends(get_db),
                    user=Depends(require_permission("commerce_transition:admin"))):
    user = _fresh_write(db, user, "commerce_transition:admin")
    return _write(db, service.register_bank_domain, **_attested(body, user))


@router.get('/bank-identities')
def bank_identities(db: Session = Depends(get_db), user=Depends(require_permission('commerce_transition:admin'))):
    read_authority.current_user(db, user, 'commerce_transition:admin')
    from app.finance.transition_identity import unmapped_legacy_money
    return ok({'items': [_row(row) for row in db.query(BankIdentity).order_by(BankIdentity.id).limit(500)],
               'unmapped_legacy_money': unmapped_legacy_money(db)})


@router.post('/bank-identities/reconcile-legacy')
def reconcile_legacy_bank(body: LegacyBankReconciliation, db: Session = Depends(get_db),
                          user=Depends(require_permission('commerce_transition:admin'))):
    user = _fresh_write(db, user, 'commerce_transition:admin', 'receipt:admin')
    from app.finance.transition_identity import reconcile_legacy_identity
    return _write(db, reconcile_legacy_identity, **body.model_dump(), actor_id=user['id'])
