"""Local outbound adapter uses a disjoint identity namespace and no mirrors."""
from datetime import timedelta
from sqlalchemy import select, or_, func
from app.auth.models import ArkUser, ArkUserExternalBinding
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound
from app.customer.transaction_identity import invoice_key


def is_local(identity):
    return str(identity).startswith("local-")


def _identity_predicate(identity):
    suffix = str(identity)[6:]
    if is_local(identity):
        if not suffix.isdigit() or suffix != str(int(suffix)) or int(suffix) <= 0:
            return None
        return ShipmentOutbound.id == int(suffix)
    return ((ShipmentOutbound.payload['original_outbound_record_id'].as_string() == str(identity))
            | (ShipmentOutbound.payload['original_outbound_invoice_id'].as_string() == str(identity)))


def locked(db, identity):
    """Reuse only a current parent resolved under this transaction's policy lock.

    A locking read does not refresh MySQL's earlier consistent-read snapshot.
    Downstream header/item adapters must therefore use the same locked object,
    rather than missing a newly adopted alias and falling back to the mirror.
    """
    transaction, rows = db.info.get('inspection_native_parents', (None, {}))
    return rows.get(str(identity)) if transaction is db.get_transaction() and transaction is not None else None


def get(db, identity, *, lock=False):
    parent = locked(db, identity)
    if parent is not None and not lock:
        return parent
    predicate = _identity_predicate(identity)
    if predicate is None:
        return None
    query = select(ShipmentOutbound).where(predicate,
        ShipmentOutbound.payload['transaction_mode'].as_string() == 'local')
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    rows = db.scalars(query.limit(2)).all()
    if len(rows) > 1:
        raise ValueError('历史出库身份关联不唯一，请核验来源租户')
    row = next(iter(rows), None)
    return row if row and (row.payload or {}).get("transaction_mode") == "local" else None


def lock_for_edit(db, identity):
    """Resolve adopted aliases by current read before any inspection/mirror access.

    The policy mutex serializes adoption and all economic writers. The joined
    locking locator takes the invoice parent along with its matching outbound;
    subsequent locks and adapters use that same current binding.
    """
    from app.invoice import transition_gate
    transition_gate.lock_platform(db)
    predicate = _identity_predicate(identity)
    if predicate is None:
        raise ValueError("本地出库已完成或取消，不能修改检验资料")
    parents = db.scalars(select(Invoice).join(ShipmentOutbound, ShipmentOutbound.invoice_id == Invoice.id)
        .where(predicate, ShipmentOutbound.payload['transaction_mode'].as_string() == 'local')
        .limit(2).with_for_update().execution_options(populate_existing=True)).all()
    if len(parents) > 1:
        raise ValueError('历史出库身份关联不唯一，请核验来源租户')
    if not parents:
        if is_local(identity):
            raise ValueError("本地出库已完成或取消，不能修改检验资料")
        transition_gate.allow_route(db, 'legacy')
        return None
    row = ensure_editable(db, identity)
    transition_gate.require_invoice(db, parents[0], 'local')
    transaction, rows = db.info.get('inspection_native_parents', (None, {}))
    rows = dict(rows) if transaction is db.get_transaction() else {}
    payload = row.payload or {}
    for alias in [identity, f'local-{row.id}', payload.get('original_outbound_record_id'),
                  payload.get('original_outbound_invoice_id')]:
        if alias is not None:
            rows[str(alias)] = row
    db.info['inspection_native_parents'] = (db.get_transaction(), rows)
    return row


def is_native(db, identity, *, lock=False):
    return is_local(identity) or get(db, identity, lock=lock) is not None


def ensure_editable(db, identity):
    row = get(db, identity, lock=True)
    if row is None or row.status not in {"local_pending", "local_ready"}:
        raise ValueError("本地出库已完成或取消，不能修改检验资料")
    return row


def header(db, identity, scope=None, *, include_deleted=False):
    row = get(db, identity)
    if row is None or (row.status == "local_cancelled" and not include_deleted):
        return None
    invoice = db.get(Invoice, row.invoice_id)
    if scope is not None and scope_user(db, scope) != invoice.sales_user_id:
        return None
    return dict(outbound_record_id=row.payload.get('original_outbound_record_id', f"local-{row.id}"),
        outbound_invoice_id=row.payload.get('original_outbound_invoice_id'), local_outbound_id=row.id,
        transaction_mode="local", outbound_no=row.outbound_no, outbound_date=str(row.created_at.date()),
        customer_name=row.payload["customer_name"], company_id=invoice_key(db, invoice), owner_name=row.payload["owner_name"],
        remark=invoice.remark, order_id=invoice.invoice_no, invoice_id=invoice.id, mirror_updated_at=None,
        item_count=len(row.payload["items"]), total_qty=sum(item["qty"] for item in row.payload["items"]),
        status=row.status, local_outbound_version=row.payload["outbound_version"])


def items(db, identity):
    row = get(db, identity)
    if row is None:
        return []
    return [{**item, "item_id": item.get('original_outbound_item_id', f"local-{row.id}-{item['invoice_item_id']}"), "product_id": None,
             "sku": str(item["local_sku_id"]), "spec": item.get("model"), "transaction_mode": "local"}
            for item in row.payload["items"]]


def scope_user(db, scope):
    actor = getattr(scope, "ark_user_id", None)
    if str(scope).startswith("ark-user:"):
        actor = int(str(scope).split(":", 1)[1])
    if actor is None:
        actor = db.scalar(select(ArkUserExternalBinding.ark_user_id).where(
            ArkUserExternalBinding.provider == "okki", ArkUserExternalBinding.external_account_id == str(scope),
            ArkUserExternalBinding.binding_status == "active", ArkUserExternalBinding.deleted_at.is_(None)))
    return actor


def list_records(db, *, keyword=None, order_id=None, date_from=None, date_to=None, page=1, page_size=20,
                 okki_user_id=None, outbound_state=None, inspection_status=None, sort_field=None, sort_order=None):
    query = db.query(ShipmentOutbound).join(Invoice, Invoice.id == ShipmentOutbound.invoice_id).filter(
        Invoice.transaction_mode == "local", ShipmentOutbound.status != "local_cancelled",
        ShipmentOutbound.payload['transaction_mode'].as_string() == 'local')
    if okki_user_id is not None:
        actor = scope_user(db, okki_user_id)
        query = query.filter(Invoice.sales_user_id == actor) if actor is not None else query.filter(False)
    if keyword:
        query = query.filter(or_(ShipmentOutbound.outbound_no.contains(keyword, autoescape=True), Invoice.customer_name.contains(keyword, autoescape=True)))
    if order_id:
        query = query.filter(Invoice.id == int(order_id)) if str(order_id).isdigit() else query.filter(Invoice.invoice_no == str(order_id))
    if outbound_state:
        states = {'active': {'local_pending', 'local_ready', 'local_shipped'},
                  'awaiting_sync': {'local_pending'}, 'failed': set(), 'uncertain': set()}
        selected = states.get(outbound_state)
        if selected is None:
            raise ValueError('本地出库筛选状态不支持')
        query = query.filter(ShipmentOutbound.status.in_(selected))
    if inspection_status:
        from app.shipping_inspection.models import ShippingInspection
        present = select(ShippingInspection.id).where(ShippingInspection.local_outbound_id == ShipmentOutbound.id)
        if inspection_status == 'none':
            query = query.filter(~present.exists())
        else:
            query = query.filter(present.where(ShippingInspection.status == inspection_status).exists())
    if date_from:
        query = query.filter(ShipmentOutbound.created_at >= date_from)
    if date_to:
        query = query.filter(ShipmentOutbound.created_at < date_to + timedelta(days=1))
    total = query.count()
    from app.core.list_sort import apply_list_sort
    query = apply_list_sort(query, sort_field=sort_field, sort_order=sort_order,
        columns={'outbound_date': ShipmentOutbound.created_at, 'outbound_no': ShipmentOutbound.outbound_no,
                 'customer_name': Invoice.customer_name},
        default=[ShipmentOutbound.created_at.desc()], tie_breakers=[ShipmentOutbound.id.desc()])
    outbounds = query.offset((page-1)*page_size).limit(page_size).all()
    return [{**header(db, f"local-{row.id}"), "record_source": "ark_local", "outbound_state": row.status,
             "can_print": True} for row in outbounds], total


def list_inspections(db, *, keyword=None, order_id=None, salesperson_name=None, submitted_by_name=None,
                     date_from=None, date_to=None, page=1, page_size=20, okki_user_id=None):
    from app.shipping_inspection.models import ShippingInspection
    query = db.query(ShippingInspection, ArkUser.real_name, Invoice).join(ShipmentOutbound,
        ShipmentOutbound.id == ShippingInspection.local_outbound_id).join(Invoice, Invoice.id == ShipmentOutbound.invoice_id)
    query = query.outerjoin(ArkUser, ArkUser.id == ShippingInspection.submitted_by).filter(ShippingInspection.status == "submitted")
    if okki_user_id is not None:
        actor = scope_user(db, okki_user_id)
        query = query.filter(Invoice.sales_user_id == actor) if actor is not None else query.filter(False)
    if keyword:
        query = query.filter(or_(ShippingInspection.outbound_no.contains(keyword, autoescape=True), ShippingInspection.customer_name.contains(keyword, autoescape=True)))
    if order_id:
        query = query.filter(Invoice.id == int(order_id))
    if salesperson_name:
        query = query.filter(Invoice.sales_user_name.contains(salesperson_name.strip(), autoescape=True))
    if submitted_by_name:
        query = query.filter(ArkUser.real_name.contains(submitted_by_name.strip(), autoescape=True))
    if date_from:
        query = query.filter(ShippingInspection.submitted_at >= date_from)
    if date_to:
        query = query.filter(ShippingInspection.submitted_at < date_to + timedelta(days=1))
    total = query.count()
    rows = query.order_by(ShippingInspection.submitted_at.desc(), ShippingInspection.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return [dict(id=inspection.id, edit_version=inspection.edit_version, outbound_record_id=inspection.outbound_record_id,
        outbound_no=inspection.outbound_no, order_id=invoice.invoice_no, customer_name=inspection.customer_name,
        photo_count=inspection.photo_count, submitted_at=inspection.submitted_at, submitted_by_name=name,
        salesperson_name=invoice.sales_user_name, remark=inspection.remark) for inspection, name, invoice in rows], total
