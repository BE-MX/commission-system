"""Copy a reviewed access template to a distinct, independently bound Ark customer."""
from sqlalchemy import select

from app.core.time import beijing_now
from app.portal import admin_service as admin, password_service
from app.portal.catalog_access_service import granted_items
from app.portal.domain import content_hash, normalize_email, require_version
from app.portal.errors import reject
from app.portal.models import CommandReceipt
from app.portal.schemas import AccountCreate, CustomerCreate, CustomerUpdate
from app.portal.security import keyed_digest


def source(db, actor_id, public_id, body):
    actor = admin.begin(db, actor_id)
    access = admin.scoped_access(db, public_id, actor)
    require_version(access.row_version, body.source_version)
    require_version(access.catalog_version, body.source_catalog_version)
    if access.status != 'enabled':
        reject('ACCESS_NOT_ENABLED', '只能复制当前已启用的客户访问权限。')
    admin.validate_binding(db, access)
    return actor, access


def copy(db, actor_id, public_id, command_key, body, password_hash):
    actor = admin.begin(db, actor_id)
    template = admin.scoped_access(db, public_id, actor)
    payload = body.model_dump(exclude={'password'})
    payload['email'] = normalize_email(body.email)
    payload['password_digest'] = keyed_digest(admin.get_settings().PORTAL_AUTH_SECRET,
        'copy-access', body.password.get_secret_value())
    digest = content_hash(payload)
    receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.action == 'access.copy',
        CommandReceipt.object_public_id == template.public_id, CommandReceipt.command_key == str(command_key)))
    if receipt:
        if receipt.payload_hash != digest:
            reject('IDEMPOTENCY_CONFLICT', '同一操作标识不能复制不同客户或账号。')
        admin.scoped_access(db, receipt.result_reference_json['id'], actor)
        return {**receipt.result_reference_json, 'replayed': True}
    _, template = source(db, actor_id, public_id, body)
    items = granted_items(db, template)
    if len(items) > 5000 or any(item.status != 'published' for item in items):
        reject('CATALOG_REVIEW_REQUIRED', '原客户商品授权含已下架商品或超过上限，请先整理后再复制。', 422)
    capabilities = {'can_view_price': template.can_view_price, 'can_order': template.can_order}
    target = admin.create_customer(db, actor_id, CustomerCreate(
        **body.model_dump(include={'binding_fingerprint', 'canonical_customer_id', 'assignment_id', 'okki_identity_id'}),
        capabilities=capabilities, catalog_item_ids=[item.public_id for item in items]))
    target = admin.update_customer(db, actor_id, target['id'], target['row_version'],
        CustomerUpdate(status='enabled', capabilities=capabilities, reason='Copied reviewed customer access'))
    account = password_service.create_account(db, actor_id, target['id'], command_key,
        AccountCreate(email=payload['email'], password=body.password,
            contact_name=payload['email'].split('@')[0][:100]), password_hash)
    access = admin.scoped_access(db, target['id'], actor)
    admin.audit(db, actor, access, access, 'access_copied', changes={'source_access_id': template.public_id})
    result = {**target, 'account_id': account['id']}
    db.add(CommandReceipt(action='access.copy', object_public_id=template.public_id,
        command_key=str(command_key), payload_hash=digest, result_reference_json=result,
        first_actor_type='employee', first_actor_id=actor_id, completed_at=beijing_now()))
    db.flush()
    return {**result, 'replayed': False}
