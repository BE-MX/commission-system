"""The existing invoice editor delegates local contracts to the local ledger."""
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.service import get_live_user_authorization
from app.commerce_transition import service as ownership
from app.commerce_transition.models import InvoiceAuthority, PlatformPolicy, WriterReceipt
from app.invoice.commerce_schemas import LocalInvoiceDraft, LocalItem
from app.portal.upstream_authority import begin_employee_document_write


def current_actor(db, user_id):
    if not user_id:
        raise HTTPException(403, "无法确认当前操作人")
    claims = {"sub": str(user_id), "id": int(user_id)}
    begin_employee_document_write(db, claims, "invoice:write")
    roles, permissions = get_live_user_authorization(db, int(user_id))
    if not roles or ("super_admin" not in roles and "invoice:write" not in permissions):
        raise HTTPException(403, "当前账号无权编辑发票")
    return {**claims, "roles": roles, "permissions": permissions}


def local_body(body, user_id, *, invoice=None):
    if body.receipt_draft is not None or (body.internal_received or 0) != 0:
        raise ValueError("方舟独立订单请通过资金与应收登记收款，不能保存旧回款草稿或直接改已收金额")
    if body.source_type != 'manual':
        raise ValueError("非手工来源须先完成本地身份与来源核验，不能直接更换正式办理路线")
    customer_id = body.local_customer_id
    if customer_id is None and str(body.customer_id).startswith('ark:'):
        value = str(body.customer_id)[4:]
        if value.isdigit():
            customer_id = int(value)
    if not customer_id or not body.request_key:
        raise ValueError("本地客户身份和稳定请求键不能为空")
    if invoice is not None and body.expected_commerce_version is None:
        raise ValueError("本地订单业务版本不能为空，请重新读取")
    values = {key: getattr(body, key) for key in LocalInvoiceDraft.model_fields
              if hasattr(body, key) and key not in {'items', 'expected_version', 'sales_user_id', 'internal_accessory'}}
    values.update(local_customer_id=customer_id, sales_user_id=body.sales_user_id or user_id,
                  expected_version=body.expected_commerce_version or 0,
                  internal_accessory=body.internal_accessory or 0,
                  is_new_deal=None if body.okki_new_deal is None else bool(body.okki_new_deal),
                  is_first_return=None if body.okki_first_return is None else bool(body.okki_first_return))
    items = []
    for row in body.items:
        if row.local_sku_id is None or row.price_per_piece is None:
            raise ValueError("本地订单明细必须选择本地SKU并填写单价")
        if row.semifinished_enabled or row.semifinished_plan:
            raise ValueError("本地领料通过生产领退料办理，不能沿用小满同步扣料计划")
        items.append(LocalItem(id=row.id, local_sku_id=row.local_sku_id, quantity=row.quantity,
            price_per_piece=row.price_per_piece, discount_amount=row.discount_amount,
            commercial_kind=row.commercial_kind, group_key=row.group_key))
    return LocalInvoiceDraft(**{**values, 'items': items})


def create(db, body, user_id):
    user = current_actor(db, user_id)
    ownership.lock_policy(db)
    from app.invoice import commerce_service
    invoice = commerce_service.create_draft(db, local_body(body, user_id), user)
    ownership.ensure_authority(db, invoice, route='local',
        source_evidence={'new_draft': True, 'request_key': body.request_key, 'actor_id': user_id})
    return invoice


def update(db, invoice, body, user_id):
    user = current_actor(db, user_id)
    if body.transaction_route not in {None, 'local'}:
        raise ValueError("订单正式路线不能通过普通保存更换")
    ownership.require_route(db, invoice, 'local', body.expected_authority_epoch)
    if body.expected_authority_epoch is None:
        raise ValueError("订单办理权版本不能为空，请重新读取")
    from app.invoice import commerce_service
    return commerce_service.update_draft(db, invoice.id, local_body(body, user_id, invoice=invoice), user)


def describe(db, invoice, user=None):
    route = invoice.transaction_mode or 'legacy'
    authority = db.get(InvoiceAuthority, invoice.id) if db is not None else None
    current = db.get(PlatformPolicy, 1) if db is not None else None
    active = bool(authority and authority.state == 'active' and current and
                  current.phase in {'transition', f'{route}_only'} and authority.route == route)
    if active and current.phase != 'legacy_only':
        writers = db.scalars(select(WriterReceipt)).all()
        active = bool(current.writer_inventory_verified and current.inventory_evidence and writers
            and all(row.state == 'revoked' or (row.state == 'compatible'
                and row.protocol_version >= current.min_writer_version) for row in writers))
    roles, permissions = ([], [])
    if db is not None and user is not None:
        roles, permissions = get_live_user_authorization(db, int(user.get('sub') or user.get('id')))
    def allowed(permission):
        return 'super_admin' in roles or permission in permissions
    local = active and route == 'local'
    writable = local and allowed('invoice:write')
    status = invoice.commerce_status
    draft = status == 'draft' and invoice.status == 'draft'
    shadow_status = 'not_observed'
    if db is not None:
        from app.commerce_shadow.models import ShadowObservation, ShadowOutbox
        observation = db.scalar(select(ShadowObservation).where(ShadowObservation.invoice_id == invoice.id)
                                .order_by(ShadowObservation.id.desc()).limit(1))
        if observation:
            outbox = db.scalar(select(ShadowOutbox).where(ShadowOutbox.observation_id == observation.id))
            shadow_status = 'unknown' if observation.outcome == 'unknown' else 'lagging' if outbox and outbox.state != 'exported' else 'observed'
    return {'transaction_route': route, 'authority_epoch': authority.epoch if authority else None,
        'authority_state': authority.state if authority else 'unregistered', 'authority_operable': active,
        'commerce_status': status, 'commerce_version': invoice.commerce_version,
        'local_deposit_amount': str(invoice.local_deposit_amount or 0),
        'local_deposit_charge': str(invoice.local_deposit_charge or 0),
        'local_customer_id': invoice.local_customer_id, 'shadow_status': shadow_status,
        'capabilities': {'confirm': writable and draft, 'cancel': writable and status in {'draft', 'confirmed'},
            'amend': writable and status == 'confirmed',
            'change_route': active and allowed('invoice:write') and allowed('commerce_transition:write')
                and draft and authority.confirmed_at is None,
            'create_shipment': writable and allowed('shipment:write') and status in {'confirmed', 'partially_shipped'},
            'sync': active and route == 'legacy' and allowed('invoice:sync')
                and invoice.status not in {'cancelled', 'remote_deleted', 'sync_uncertain'}}}
