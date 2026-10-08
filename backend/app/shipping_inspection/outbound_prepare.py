"""Current-authorized outbound preparation with provider evidence outside local locks."""
import logging
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import edit_authority, order_sync_execution, order_push_facts, xiaoman_service
from app.invoice.models import Invoice, OkkiOutboundTask
from app.portal import authority
from app.portal.access_policy import employee_principal
from app.portal.errors import PortalError
from app.portal.order_models import Conversion, OrderRequest
from app.shipping_inspection import outbound_service, outbound_sync_plan as plans, outbound_sync_state as state
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent

logger = logging.getLogger(__name__)


def reject(status, message):
    raise HTTPException(status, message, headers={'Cache-Control': 'private, no-store'}) from None


def current(db, user, warehouse=False):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        reject(409, '出库授权必须从新事务开始，请重新读取')
    db.expire_all()
    authority.lock_authority(db, force=True)
    try:
        permissions = ('invoice:sync', 'shipping_inspection:write') if warehouse else ('invoice:sync',)
        actor = employee_principal(db, int(user.get('id') or user.get('sub') or 0), *permissions)
    except (ValueError, TypeError, PortalError):
        reject(403, '当前账号无权执行此出库操作')
    return {**actor, 'sub': str(actor['id'])}


def mirror(db, record, actor, warehouse=False):
    from app.shipping_inspection.router import _outbound_scope
    record_id = record['outbound_record_id'] if isinstance(record, dict) else record
    scope = _outbound_scope(db, actor) if warehouse else None
    row = outbound_service.get_outbound_record(db, str(record_id), okki_user_id=scope)
    if not row or not row.get('outbound_invoice_id'):
        reject(404, '出库单不存在')
    if isinstance(record, dict) and str(row['outbound_invoice_id']) != str(record.get('outbound_invoice_id')):
        reject(409, '出库镜像原目标已变化')
    plans.canonical_identity(row['outbound_invoice_id'])
    return deepcopy(row)


def invoice_for(db, record, actor):
    order_id = plans.canonical_identity(record.get('order_id'))
    invoice_ids = db.scalars(select(Invoice.id).where(Invoice.xiaoman_order_id == order_id).limit(2)).all()
    if len(invoice_ids) > 1:
        reject(409, '原订单关联多张本地发票，请先核对')
    invoice_id = invoice_ids[0] if invoice_ids else None
    invoice = edit_authority.lock_document(db, invoice_id, force=True) if invoice_id is not None else None
    edit_authority._visible(db, invoice, actor)
    if str(invoice.xiaoman_order_id) != order_id or invoice.order_type == 'presale':
        reject(409, '原订单绑定不支持整单出库同步')
    return invoice


def row_state(row):
    return None if row is None else tuple(deepcopy(getattr(row, column.name)) for column in row.__table__.columns)


def capture(db, record, actor, *, executing=False):
    from app.shipping_inspection import outbound_sync_service as legacy
    invoice = invoice_for(db, record, actor)
    source_items = [{'unique_id': plans.canonical_identity(item.xiaoman_unique_id),
                     'model': item.model, 'size': item.length, 'color': item.color} for item in invoice.items]
    plans.index(source_items, 'unique_id')
    event = db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope == state.SCOPE,
        ShippingOperationEvent.request_id == str(record['outbound_record_id']))
        .with_for_update().execution_options(populate_existing=True))
    active = event is not None and event.action in state.ACTIVE
    if active:
        payload = event.payload or {}
        original = payload.get('plan') or {}
        if (payload.get('invoice_id') != invoice.id or original.get('invoice_id') != invoice.id
                or str((original.get('before') or {}).get('outbound_invoice_id')) != str(record['outbound_invoice_id'])):
            reject(409, '原出库执行任务不属于当前发票或目标')
    if not active:
        from app.shipping_inspection import outbound_facts
        if outbound_facts.unresolved(db,record['outbound_record_id']):
            if event is None or (event.payload or {}).get('protocol')!=1:
                reject(409,'原出库发送事实尚未完整核对，禁止新发送')
            active=True
    rows, bindings = [], []
    if not active or executing:
        legacy._idle(db, invoice, record['outbound_record_id'])
        if order_push_facts.unresolved(db, invoice):
            reject(409, '原推单事实尚未完整核对，不能同步出库')
        rows, bindings, issues, _ = xiaoman_service._build_product_rows(
            db, invoice, xiaoman_service.get_settings_row(db), editing=True)
        if issues or any(len(items) != 1 for items, _ in bindings):
            reject(409, '订单明细尚未完成唯一产品映射')
        plans.index([row for _, row in bindings], 'unique_id')
    inspection = db.scalar(select(ShippingInspection).where(
        ShippingInspection.outbound_record_id == str(record['outbound_record_id']))
        .with_for_update().execution_options(populate_existing=True))
    media = db.scalars(select(ShippingInspectionPhoto).where(ShippingInspectionPhoto.inspection_id == inspection.id)
        .order_by(ShippingInspectionPhoto.id).with_for_update().execution_options(populate_existing=True)).all() if inspection else []
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id == invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    deletion = db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope == 'outbound-delete',
        ShippingOperationEvent.outbound_record_id == str(record['outbound_record_id']))
        .with_for_update().execution_options(populate_existing=True))
    conversions=db.scalars(select(Conversion).where(Conversion.invoice_id==invoice.id)
        .order_by(Conversion.id).with_for_update().execution_options(populate_existing=True)).all()
    requests=db.scalars(select(OrderRequest).where(OrderRequest.id.in_([row.request_id for row in conversions]))
        .order_by(OrderRequest.id).with_for_update().execution_options(populate_existing=True)).all()
    lineage=(tuple(row_state(row) for row in requests),tuple(row_state(row) for row in conversions))
    business = (deepcopy(record), row_state(invoice), tuple(row_state(item) for item in invoice.items),
        order_sync_execution.capture(db, invoice, rows), row_state(task), row_state(deletion),
        row_state(inspection), tuple(row_state(photo) for photo in media), deepcopy(source_items), lineage)
    local = {'invoice_id': invoice.id, 'invoice_no': invoice.invoice_no,
        'invoice_version': legacy.edit_version(invoice), 'remark': invoice.remark or '',
        'source_items': deepcopy(source_items),
        'products': [{**deepcopy(row), 'product_name': items[0].product_name} for items, row in bindings],
        'inspection': {'id': inspection.id, 'status': inspection.status, 'edit_version': inspection.edit_version,
                       'media_ids': [photo.id for photo in media]} if inspection else None,
        'inspection_outbound_no': inspection.outbound_no if inspection else None, 'recover': active,
        'dto': SimpleNamespace(xiaoman_order_id=invoice.xiaoman_order_id, customer_id=invoice.customer_id,
                currency=invoice.currency, total_amount=invoice.total_amount, surcharge_amount=invoice.surcharge_amount)}
    return invoice, event, business, (business, row_state(event)), local



def read_outbound(db, identity):
    from app.shipping_inspection import outbound_sync_service as legacy
    try:
        before = legacy._read(db, identity)
        plans.canonical_identity(before['outbound_invoice_id'])
        company = before.get('company_info')
        customer_id = company.get('id') if isinstance(company, dict) else None
        scalar_customer = (type(customer_id) is int and customer_id > 0 or
                           isinstance(customer_id, str) and bool(customer_id.strip()))
        if (type(before.get('status')) is not int or not scalar_customer
                or not isinstance(before.get('currency'), str) or not before['currency']):
            raise ValueError('Incomplete outbound header')
        plans.index(before['record_list'], 'order_record_id')
        plans.index(before['record_list'], 'outbound_record_id')
        return before
    except (ValueError, KeyError, TypeError):
        reject(503, '原出库证据身份或明细不完整')

def evidence(db, record, local, business, desired_serial_id, number_only):
    from app.invoice.outbound_followup_execution import read_order
    from app.shipping_inspection import outbound_sync_service as legacy
    try:
        before = read_outbound(db, record['outbound_invoice_id'])
        if str(before.get('company_info', {}).get('id')) != str(record.get('company_id')):
            reject(409, '原出库客户归属已变化')
        order = read_order(db, local['dto'], local['products'])
        try:
            related = legacy.linked_outbound_service.find_related(db, order)
        except (ValueError, KeyError, TypeError):
            reject(503, '关联出库扫描证据不完整')
        if not isinstance(related, list) or any(not isinstance(row, dict) or not row.get('outbound_invoice_id') for row in related):
            reject(503, '关联出库证据不完整')
        if len(related) != 1 or str(related[0]['outbound_invoice_id']) != str(before['outbound_invoice_id']):
            reject(409, '订单不再唯一关联原出库单')
        live = plans.index(order['product_list'], 'unique_id')
        products = [{**live[plans.canonical_identity(row['unique_id'])], **row} for row in local['products']]
        plan = plans.build(before, order, products, local['remark'], serial_id=desired_serial_id)
        if number_only and (plan['changes'] or plan['remark_changed']):
            reject(409, '出库明细或备注尚未完成核对，不能仅改号')
        if plan['serial_changed']:
            occupant = legacy.okki_client.find_outbound_by_serial(db, desired_serial_id)
            if occupant and str(occupant['outbound_invoice_id']) != str(before['outbound_invoice_id']):
                reject(409, '新出库单号已被其他原单占用')
        inspection = local['inspection']
        if not plan['serial_changed'] and local['inspection_outbound_no'] and local['inspection_outbound_no'] != before.get('serial_id'):
            reject(409, '出库单号与原验货资料不同，请先核对')
        plan['inspection'] = deepcopy(inspection)
        plan['requires_recheck'] = bool(plan['material_changed'] and inspection and inspection['media_ids'])
        if read_outbound(db, record['outbound_invoice_id']) != before or read_order(db, local['dto'], local['products']) != order:
            reject(409, '取证期间原订单或出库单已变化')
        plan.update(before=deepcopy(before), invoice_id=local['invoice_id'], invoice_no=local['invoice_no'],
            invoice_version=local['invoice_version'], order=deepcopy(order), source_items=local['source_items'],
            local_binding_fingerprint=plans.digest(business))
        plan['version'] = plans.digest(plan)
        return plan
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError):
        reject(409, '原订单或出库资料不一致，请核对原单')
    except Exception:
        logger.warning('Outbound preparation supplier evidence unavailable')
        print('[outbound-prepare] supplier evidence unavailable', flush=True)
        reject(503, '出库证据暂不可用，请稍后核对原单')
    finally:
        db.rollback(); db.expire_all()


def prepare(db, record, user, *, desired_serial_id=None, number_only=False, warehouse=False, expected_binding=None):
    try:
        actor = current(db, user, warehouse)
        original = mirror(db, record, actor, warehouse)
        invoice, event, business, binding, local = capture(db, original, actor, executing=expected_binding is not None)
        if expected_binding is not None and binding != expected_binding:
            reject(409, '前置授权后原任务或完整本地绑定已变化，请重新读取')
        active = local['recover']
        db.commit()  # Read-only local capture, never a pending event or recheck change.
        plan = None if active else evidence(db, original, local, business, desired_serial_id, number_only)
        db.rollback(); db.expire_all()
        actor = current(db, user, warehouse)
        latest = mirror(db, record, actor, warehouse)
        invoice, event, _, after, _ = capture(db, latest, actor, executing=expected_binding is not None)
        if after != binding:
            reject(409, '取证期间发票、任务或验货资料已变化')
        if event is None:
            event = state.lock(db, latest['outbound_record_id'], actor['id'])
        if plan is not None:
            if plan['requires_recheck']:
                event.action = state.RECHECK
                event.payload = {'invoice_id': invoice.id, 'plan': plan}
                event.result = {**(event.result or {}), 'message': '订单已更新，出库单待仓库同步并重新验货'}
            elif event.action == state.RECHECK:
                event.action = 'sync_idle'
        return invoice, event, plan
    except HTTPException as error:
        db.rollback(); db.expire_all()
        reject(error.status_code, error.detail)
    except (ValueError, KeyError, TypeError):
        db.rollback(); db.expire_all()
        reject(409, '本地出库绑定或产品身份无效，请核对原单')
    except SQLAlchemyError:
        db.rollback(); db.expire_all()
        logger.warning('Outbound preparation transaction unavailable')
        print('[outbound-prepare] transaction unavailable', flush=True)
        reject(503, '出库准备暂不可确认，请读取原任务后重试')


def authorize_response(db, record, user, invoice_id, warehouse=False):
    try:
        actor = current(db, user, warehouse)
        row = mirror(db, record, actor, warehouse)
        if invoice_for(db, row, actor).id != invoice_id:
            reject(409, '出库原订单绑定已变化')
    finally:
        db.rollback(); db.expire_all()
