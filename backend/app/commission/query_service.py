"""Native detail presentation reads its frozen source, not remote mirrors."""
from sqlalchemy import or_, select
from app.commission.models import CommissionBasis, CommissionEventProjection
from app.customer.models import CustomerAccount
from app.finance.models import FinanceEvent
from app.invoice.models import Invoice
from app.models.commission import CommissionDetail, SyncedPayment
from app.receipt.models import Receipt


def detail_rows(db, batch_id, user_ids=None, role="", *, include_voided=False):
    query = select(CommissionDetail, SyncedPayment, CommissionBasis, Invoice, Receipt, CustomerAccount.primary_country_code, CommissionEventProjection).join(
        CommissionEventProjection, CommissionEventProjection.payment_id == CommissionDetail.payment_id).join(
        CommissionBasis, CommissionBasis.id == CommissionEventProjection.basis_id).join(
        FinanceEvent, FinanceEvent.id == CommissionEventProjection.event_id).join(
        Receipt, Receipt.id == FinanceEvent.receipt_id).join(
        Invoice, Invoice.id == Receipt.invoice_id).join(
        SyncedPayment, SyncedPayment.payment_id == CommissionDetail.payment_id).outerjoin(
        CustomerAccount, CustomerAccount.id == Invoice.local_customer_id).where(CommissionDetail.batch_id == batch_id)
    if not include_voided:
        query = query.where(CommissionDetail.status != "voided")
    if user_ids is not None:
        columns = [getattr(CommissionDetail, f"{name}_id") for name in ((role,) if role else ("salesperson", "supervisor", "second_supervisor"))]
        query = query.where(or_(*(column.in_(user_ids) for column in columns)))
    result = []
    for detail, payment, basis, invoice, receipt, country, projection in db.execute(query):
        frozen = basis.snapshot
        result.append((detail, invoice.customer_name, country,
            frozen.get("salesperson_name"), frozen.get("supervisor_name"), frozen.get("second_supervisor_name"),
            payment.payment_date, payment.exchange_rate, payment.payment_date, receipt.payment_type, None,
            invoice.invoice_no, invoice.invoice_no, payment.service_fee, None, None,
            {role: getattr(projection, f'{role}_commission_rmb') for role in ('salesperson', 'supervisor', 'second_supervisor')}))
    return result
