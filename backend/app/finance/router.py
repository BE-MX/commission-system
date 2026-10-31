"""Local finance API; financial confirmation/admin actions have separate RBAC."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission, require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.customer.access_service import apply_customer_scope
from app.customer.models import CustomerAccount
from app.finance import service, reference_service, query_service
from app.finance.models import BankAccount, Currency, FinanceBook, FinanceEvent
from app.finance.schemas import PaymentCreate, FinanceAction, AllocationCreate, AdjustmentCreate, CurrencyWrite, BankAccountWrite, ReceivableTerms
from app.invoice.settlement_models import ReceiptBatch, Receivable, ShipmentSettlement
from app.invoice.models import Invoice
from app.receipt import access
from app.invoice.native_authority import require_write
from app.invoice.read_authority import current_user as current_reader

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/customer-options")
def customer_options(keyword: str | None = Query(None, max_length=200), page: int = Query(1, ge=1),
                     page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db),
                     user=Depends(require_any_permission("receipt:read", "receipt:write"))):
    user = current_reader(db, user, "receipt:read", "receipt:write")
    from app.customer.option_service import options
    return ok(options(db, user, permissions=["receipt:read", "receipt:write"], manage_permissions=["customer:admin"],
                      keyword=keyword, page=page, page_size=page_size))


@router.get("/order-options")
def order_options(keyword: str | None = Query(None, max_length=200), customer_id: int | None = Query(None, gt=0),
                  currency: str | None = Query(None, max_length=16), page: int = Query(1, ge=1),
                  page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db),
                  user=Depends(require_any_permission("receipt:read", "receipt:write"))):
    user = current_reader(db, user, "receipt:read", "receipt:write")
    return ok(query_service.order_options(db, user, keyword=keyword, customer_id=customer_id, currency=currency,
                                         page=page, page_size=page_size))


def write(db, command, serialize):
    try:
        row = command()
        result = serialize(row)
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        from app.commerce_shadow.hooks import record_after_rollback
        record_after_rollback(db, exc)
        logger.warning("Local finance command rejected: %s", type(exc).__name__)
        print(f"Local finance command rejected: {type(exc).__name__}", flush=True)
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "银行流水或关联数据冲突，请刷新核对") from exc
    except Exception as exc:
        db.rollback()
        from app.commerce_shadow.hooks import record_after_rollback
        record_after_rollback(db, exc)
        logger.exception("Local finance command failed")
        print("Local finance command failed; rolled back", flush=True)
        raise


@router.get("/reference-data")
def reference(db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin"))):
    user = current_reader(db, user, "receipt:read", "receipt:write", "receipt:admin")
    ledger = db.get(FinanceBook, 1)
    return ok({"currencies": [{"code": x.code, "name": x.name, "rate_to_cny": str(x.rate_to_cny), "active": bool(x.active)}
                              for x in db.scalars(select(Currency).order_by(Currency.code))],
               "accounts": [{"id": x.id, "code": x.code, "name": x.name, "currency": x.currency, "active": bool(x.active)}
                            for x in db.scalars(select(BankAccount).order_by(BankAccount.id))],
               "closed_through": ledger.closed_through if ledger else None, "book_version": ledger.version if ledger else 1})


@router.get("/aging")
def aging(db: Session = Depends(get_db), user=Depends(require_permission("receipt:read"))):
    user = current_reader(db, user, "receipt:read")
    return ok(query_service.aging(db, user))


@router.get("/reconciliation")
def reconcile(db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = current_reader(db, user, "receipt:admin")
    return ok(query_service.reconcile(db, user))


@router.put("/currencies")
def currency(body: CurrencyWrite, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: reference_service.write_currency(db, body, user), lambda row: {"code": row.code})


@router.put("/bank-accounts")
def account(body: BankAccountWrite, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: reference_service.write_account(db, body, user), lambda row: {"id": row.id})


@router.post("/close-period")
def close_period(body: FinanceAction, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: reference_service.close_period(db, body, user),
                 lambda row: {"closed_through": row.closed_through, "version": row.version})


@router.get("/payments")
def payments(customer_id: int | None = None, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
             db: Session = Depends(get_db), user=Depends(require_permission("receipt:read"))):
    user = current_reader(db, user, "receipt:read")
    query = select(ReceiptBatch).where(ReceiptBatch.transaction_mode == "local")
    from app.invoice.native_visibility import customer_scope_predicate
    query = query.where(customer_scope_predicate(db, user, ReceiptBatch.local_customer_id, read_permissions=("receipt:read",)))
    if customer_id is not None:
        scope = service.customer_access(db, customer_id, user)
        query = query.where(ReceiptBatch.local_customer_id == scope.customer_id)
    rows = db.scalars(query.order_by(ReceiptBatch.id.desc()).offset(offset).limit(limit)).all()
    return ok({"items": [service.describe(db, row, user) for row in rows]})


@router.get("/payments/{batch_id}")
def payment(batch_id: int, db: Session = Depends(get_db), user=Depends(require_permission("receipt:read"))):
    user = current_reader(db, user, "receipt:read")
    row = db.get(ReceiptBatch, batch_id)
    service.ensure_batch_access(db, row, user)
    events = db.scalars(select(FinanceEvent).where(FinanceEvent.batch_id == batch_id).order_by(FinanceEvent.id)).all()
    return ok({**service.describe(db, row, user), "allocations": query_service.allocations(db, batch_id, user), "events": [
        {"id": x.id, "action": x.action, "business_date": x.business_date, "amount": str(x.amount),
         "receipt_id": x.receipt_id, "created_at": x.created_at, "created_by": x.created_by} for x in events]})


@router.post("/payments", status_code=201)
def register(body: PaymentCreate, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    user = require_write(db, user, "receipt:write")
    return write(db, lambda: service.register(db, body, user), lambda row: service.describe(db, row, user))


@router.post("/payments/{batch_id}/confirm")
def confirm(batch_id: int, body: FinanceAction, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: service.confirm(db, batch_id, body, user), lambda row: service.describe(db, row, user))


@router.post("/payments/{batch_id}/void")
def void(batch_id: int, body: FinanceAction, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    user = require_write(db, user, "receipt:write")
    return write(db, lambda: service.void_registration(db, batch_id, body, user), lambda row: service.describe(db, row, user))


@router.post("/payments/{batch_id}/allocations")
def allocate(batch_id: int, body: AllocationCreate, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    user = require_write(db, user, "receipt:write")
    return write(db, lambda: service.allocate(db, batch_id, body, user), lambda row: {"id": row.id, "version": row.version})


@router.post("/allocations/{receipt_id}/reverse")
def reverse(receipt_id: int, body: FinanceAction, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: service.reverse_allocation(db, receipt_id, body, user), lambda row: {
        "id": row.id, "version": row.version, "status": row.status,
        "reversed_amount": str(row.reversed_amount), "reversed_bank_charge": str(row.reversed_bank_charge),
        "effective_amount": str(row.effective_amount), "effective_bank_charge": str(row.effective_bank_charge)})


@router.post("/payments/{batch_id}/refund")
def refund(batch_id: int, body: FinanceAction, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: service.refund(db, batch_id, body, user), lambda row: service.describe(db, row, user))


@router.get("/invoices/{invoice_id}/receivables")
def receivables(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_permission("receipt:read"))):
    user = current_reader(db, user, "receipt:read")
    invoice = db.get(Invoice, invoice_id)
    access.ensure_invoice(db, invoice, user)
    if invoice.transaction_mode != "local":
        raise HTTPException(409, "历史订单尚未承接本地应收账")
    rows = db.scalars(select(Receivable).where(Receivable.invoice_id == invoice_id).order_by(Receivable.id)).all()
    settlements = db.scalars(select(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice.id,
        ShipmentSettlement.state != "cancelled").order_by(ShipmentSettlement.sequence)).all()
    return ok({"invoice": {"id": invoice.id, "invoice_no": invoice.invoice_no, "customer_name": invoice.customer_name,
                           "currency": invoice.currency, "order_type": invoice.order_type, "commerce_status": invoice.commerce_status},
               "settlements": [{"id": x.id, "settlement_no": x.settlement_no, "state": x.state, "version": x.version,
                                "quote": x.quote} for x in settlements],
               "items": [{"id": x.id, "settlement_id": x.settlement_id, "kind": x.kind, "currency": x.currency, "amount": str(x.amount),
             "adjustment_amount": str(x.adjustment_amount), "paid_amount": str(x.paid_amount),
             "remaining_amount": str(service.money(x.amount + x.adjustment_amount - x.paid_amount)),
             "due_date": x.due_date, "version": x.version, "cancelled": invoice.commerce_status == "cancelled"} for x in rows]})


@router.post("/receivables/{receivable_id}/adjust")
def adjust(receivable_id: int, body: AdjustmentCreate, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: service.adjust_receivable(db, receivable_id, body, user), lambda row: {"id": row.id, "version": row.version})


@router.put("/receivables/{receivable_id}/due-date")
def due_date(receivable_id: int, body: ReceivableTerms, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    user = require_write(db, user, "receipt:admin")
    return write(db, lambda: service.set_due_date(db, receivable_id, body, user), lambda row: {"id": row.id, "version": row.version})
