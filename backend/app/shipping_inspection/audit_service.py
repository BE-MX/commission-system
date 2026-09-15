"""Transactional actor attribution; no credentials or media bytes in audit rows."""
from app.auth.models import ArkUser
from app.shipping_inspection.models import ShippingOperationEvent


def record(db, action, user_id, outbound_record_id, *, inspection=None, media_id=None,
           context=None, request_id=None, payload=None, result=None):
    context = context or {}
    login_id = context.get('login_user_id', user_id)
    operator = db.get(ArkUser, user_id)
    login = db.get(ArkUser, login_id)
    event = ShippingOperationEvent(
        scope=context.get('scope', f'mini:{user_id}'), request_id=request_id,
        source=context.get('source', 'mini'), action=action,
        login_user_id=login_id, operator_user_id=user_id,
        operator_name=operator.real_name if operator else str(user_id),
        login_name=login.real_name if login else str(login_id),
        outbound_record_id=outbound_record_id,
        inspection_id=inspection.id if inspection else None,
        media_id=media_id, edit_version=inspection.edit_version if inspection else None,
        payload=payload, result=result,
    )
    db.add(event)
    return event


def list_events(db, outbound_record_id, *, include_login=False):
    rows = db.query(ShippingOperationEvent).filter_by(outbound_record_id=outbound_record_id).order_by(ShippingOperationEvent.id.desc()).limit(200).all()
    return [dict(id=row.id, action=row.action, source=row.source, operator_name=row.operator_name,
                 created_at=row.created_at, media_id=row.media_id,
                 **({'login_name': row.login_name} if include_login else {})) for row in rows]
