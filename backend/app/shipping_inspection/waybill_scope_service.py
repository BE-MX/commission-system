"""Shared inspection visibility and exact invoice/customer evidence for waybills."""
from collections import defaultdict

from sqlalchemy import bindparam, text

from app.auth.models import ArkUserExternalBinding
from app.invoice.models import Invoice, InvoiceCustomerOverlay
from app.invoice.settlement_models import ShipmentOutbound
from app.shipping_inspection import outbound_service


def invoice_map(db, inspections):
    local_ids = [i.local_outbound_id for i in inspections if i.local_outbound_id]
    local = {out.id: inv for out, inv in db.query(ShipmentOutbound, Invoice).join(
        Invoice, Invoice.id == ShipmentOutbound.invoice_id).filter(ShipmentOutbound.id.in_(local_ids)).all()} if local_ids else {}
    legacy = [str(i.outbound_record_id) for i in inspections if not i.local_outbound_id]
    associations = outbound_service.order_ids_for_records(db, legacy) if legacy else {}
    customers = {}
    if legacy:
        columns = outbound_service._record_columns(db)
        if columns.get('company_id'):
            rows = db.execute(text(f"SELECT `{columns['id']}`, `{columns['company_id']}` "
                f"FROM `{outbound_service._schema()}`.`{outbound_service.RECORDS_TABLE}` WHERE `{columns['id']}` IN :ids"
            ).bindparams(bindparam('ids', expanding=True)), {'ids': legacy}).all()
            customers = {str(identity): str(customer or '') for identity, customer in rows}
    order_ids = {oid for group in associations.values() for oid in group}
    by_order = defaultdict(list)
    if order_ids:
        for invoice in db.query(Invoice).filter(Invoice.xiaoman_order_id.in_(order_ids)).all():
            by_order[str(invoice.xiaoman_order_id)].append(invoice)
    return {i.id: ([local[i.local_outbound_id]] if i.local_outbound_id in local else [])
            if i.local_outbound_id else [inv for oid in associations.get(str(i.outbound_record_id), [])
                                         for inv in by_order[oid]
                                         if str(inv.customer_id) == customers.get(str(i.outbound_record_id))] for i in inspections}


def okki_identity(db, user_id):
    row = db.query(ArkUserExternalBinding).filter(
        ArkUserExternalBinding.ark_user_id == user_id, ArkUserExternalBinding.provider == 'okki',
        ArkUserExternalBinding.binding_status == 'active', ArkUserExternalBinding.deleted_at.is_(None)
    ).order_by(ArkUserExternalBinding.is_primary.desc(), ArkUserExternalBinding.id).first()
    return str(row.external_account_id).strip() if row and row.external_account_id else None


def visible_ids(db, inspections, user_id, roles, permissions, invoices=None):
    if 'super_admin' in roles or 'shipping_inspection:inspection_read_all' in permissions:
        return {i.id for i in inspections}
    invoices = invoices if invoices is not None else invoice_map(db, inspections)
    visible = {i.id for i in inspections if any(
        inv.merchandiser_id == user_id or (i.local_outbound_id and inv.sales_user_id == user_id)
        for inv in invoices.get(i.id, []))}
    legacy = [i for i in inspections if not i.local_outbound_id and i.id not in visible]
    identity = okki_identity(db, user_id) if legacy else None
    if identity:
        from app.shipping_inspection.models import ShippingInspection
        visible.update(row[0] for row in db.query(ShippingInspection.id).filter(
            ShippingInspection.id.in_([i.id for i in legacy]), ShippingInspection.outbound_record_id.in_(
                outbound_service.scoped_record_ids_query(db, identity))).all())
    return visible


def require_scope(db, inspection, user_id, roles, permissions):
    if inspection.id not in visible_ids(db, [inspection], user_id, roles, permissions):
        raise ValueError('验货单不存在或不在当前授权范围内')


def customer_id(db, inspection):
    record = outbound_service.get_outbound_record(db, inspection.outbound_record_id, include_deleted=True)
    identity = str((record or {}).get('company_id') or '').strip()
    if not identity:
        raise ValueError('验货单客户身份不完整，请先核对出库单')
    return identity


def is_9610(invoice):
    return '便捷发货' in (invoice.internal_payment_method or '') and invoice.express_channel != 'FEDEX9610'


def countries(db, identities):
    identities = {identity for identity in identities if identity and not identity.startswith('ark:')}
    if not identities:
        return {}
    from app.invoice.product_service import _schema
    rows = db.execute(text(f'SELECT company_id, country_name FROM `{_schema()}`.customer_info WHERE company_id IN :ids')
                      .bindparams(bindparam('ids', expanding=True)), {'ids': sorted(identities)}).all()
    result = {str(cid): country or '' for cid, country in rows}
    for overlay in db.query(InvoiceCustomerOverlay).filter(InvoiceCustomerOverlay.company_id.in_(identities)).all():
        if overlay.country_name:
            result[str(overlay.company_id)] = overlay.country_name
    return result
