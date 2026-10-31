"""Install route gates before the existing invoice, money and stock locks."""
from sqlalchemy import select

from app.commerce_transition import service as authority
from app.commerce_transition.models import InvoiceAuthority


def lock_platform(db):
    return authority.lock_policy(db)


def require_invoice(db, invoice, route, expected_epoch=None):
    current = lock_platform(db)
    identity = invoice if isinstance(invoice, int) else invoice.id
    if not identity:
        raise ValueError("订单尚未持久保存，无法确认正式办理路线")
    row = db.scalar(select(InvoiceAuthority).where(InvoiceAuthority.invoice_id == identity)
                    .with_for_update().execution_options(populate_existing=True))
    if row is None:
        if isinstance(invoice, int):
            from app.invoice.models import Invoice
            invoice = db.scalar(select(Invoice).where(Invoice.id == identity)
                                .with_for_update().execution_options(populate_existing=True))
        if invoice is None or invoice.transaction_mode not in {'legacy', 'local'}:
            raise ValueError("订单来源不明确，须先核验后办理")
        row = authority.ensure_authority(db, invoice, route=invoice.transaction_mode,
            source_evidence={'explicit_transaction_mode': invoice.transaction_mode,
                             'created_by': invoice.created_by},
            confirmed=invoice.status != 'draft')
    return authority.require_route(db, identity, route, expected_epoch)


def allow_route(db, route):
    return authority.require_phase(db, route)


def assert_epoch(current, expected_epoch):
    if current.phase == 'transition' and expected_epoch is None:
        raise ValueError("过渡期操作须携带订单办理权版本，请重新读取")
