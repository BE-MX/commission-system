"""Shared-phone sessions; login identity authorizes, selected identity owns business writes."""
from datetime import timedelta
import hashlib
import logging
import uuid

from app.auth.models import ArkUser, ArkUserRole, ArkRole, ArkPermission, ArkRolePermission
from app.core.config import get_settings
from app.core.time import beijing_now
from app.shipping_inspection import audit_service, file_service, qr_service, service
from app.shipping_inspection.models import ShippingStationSession, ShippingOperationEvent, ShippingInspectionPhoto, ShippingInspection

logger = logging.getLogger('commission')


class StationError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def authorize(db, login_id):
    user = db.query(ArkUser).filter_by(id=login_id, is_active=True, deleted_at=None).with_for_update(read=True).populate_existing().first()
    if not user:
        raise StationError('LOGIN_INVALID', '登录账号已失效，请重新登录', 401)
    roles = db.query(ArkRole.name).join(ArkUserRole, ArkUserRole.role_id == ArkRole.id).filter(ArkUserRole.user_id == login_id).with_for_update(read=True).all()
    permissions = db.query(ArkPermission.code).join(ArkRolePermission, ArkRolePermission.permission_id == ArkPermission.id).join(ArkUserRole, ArkUserRole.role_id == ArkRolePermission.role_id).filter(ArkUserRole.user_id == login_id).with_for_update(read=True).all()
    if 'super_admin' not in {r[0] for r in roles} and 'shipping_station:write' not in {p[0] for p in permissions}:
        raise StationError('STATION_FORBIDDEN', '当前账号没有共用手机发货质检权限', 403)
    return user


def operator(db, login_id, operator_id):
    role_id = get_settings().SHIPPING_STATION_ROLE_ID
    if not role_id or not db.get(ArkRole, role_id):
        raise StationError('ROLE_NOT_CONFIGURED', '未配置发货质检角色，请联系管理员', 503)
    person = db.query(ArkUser).filter_by(id=operator_id, is_active=True, deleted_at=None).with_for_update(read=True).populate_existing().first()
    member = db.query(ArkUserRole).filter_by(user_id=operator_id, role_id=role_id).with_for_update(read=True).first()
    if operator_id == login_id or person is None or member is None:
        raise StationError('OPERATOR_INVALID', '所选人员已停用或不属于发货质检角色，请重新选择', 403)
    return person


def operators(db, login_id):
    authorize(db, login_id)
    role_id = get_settings().SHIPPING_STATION_ROLE_ID
    if not role_id or not db.get(ArkRole, role_id):
        raise StationError('ROLE_NOT_CONFIGURED', '未配置发货质检角色，请联系管理员', 503)
    people = db.query(ArkUser).join(ArkUserRole, ArkUserRole.user_id == ArkUser.id).filter(
        ArkUserRole.role_id == role_id, ArkUser.id != login_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
    ).order_by(ArkUser.real_name, ArkUser.id).all()
    names = [p.real_name for p in people]
    return [{'id': p.id, 'name': p.real_name, 'hint': p.username if names.count(p.real_name) > 1 else ''} for p in people]


def _active(session):
    now = beijing_now()
    if session.ended_at:
        raise StationError('SESSION_ENDED', '本次操作已结束，请重新选择人员并扫码')
    if now >= session.expires_at or now >= session.last_active_at + timedelta(minutes=get_settings().SHIPPING_STATION_IDLE_MINUTES):
        raise StationError('SESSION_EXPIRED', '操作身份已超时，请重新选择人员并扫码')


def session_for(db, login_id, session_id, *, allow_ended=False):
    authorize(db, login_id)
    session = db.query(ShippingStationSession).filter_by(id=session_id, login_user_id=login_id).with_for_update().populate_existing().first()
    if not session:
        raise StationError('SESSION_NOT_FOUND', '操作会话不存在，请重新扫码', 404)
    operator(db, login_id, session.operator_user_id)
    if not allow_ended:
        _active(session)
    return session


def _view(db, session):
    return dict(service.scan_payload(db, session.outbound_record_id), session_id=session.id,
                operator={'id': session.operator_user_id, 'name': session.operator_name},
                idle_minutes=get_settings().SHIPPING_STATION_IDLE_MINUTES)


def _context(session):
    return {'source': 'web_station', 'scope': session.id, 'login_user_id': session.login_user_id}


def _event(db, session, action, request_id, payload, result, *, inspection=None, media_id=None):
    session.last_active_at = beijing_now()
    return audit_service.record(db, action, session.operator_user_id, session.outbound_record_id,
        context=_context(session), request_id=request_id, payload=payload, result=result,
        inspection=inspection, media_id=media_id)


def _replay(db, session, action, request_id, payload):
    event = db.query(ShippingOperationEvent).filter_by(scope=session.id, request_id=request_id).with_for_update().first()
    if event:
        if event.action != action or event.payload != payload:
            raise StationError('REQUEST_CONFLICT', '请求编号已用于其他内容，请刷新后重试')
        return event.result
    return None


def scan(db, login_id, operator_id, qr_raw, request_id):
    # Serialize initial scan receipts per login; no inspection row is created by reading.
    db.query(ArkUser.id).filter_by(id=login_id).with_for_update().first()
    authorize(db, login_id)
    person = operator(db, login_id, operator_id)
    valid, record_id = qr_service.verify_qr_data(qr_raw)
    if not valid:
        raise StationError('SIGN_INVALID', '二维码无效，请扫描出库单右上角二维码', 400)
    session = db.query(ShippingStationSession).filter_by(login_user_id=login_id, scan_request_id=request_id).with_for_update().first()
    if session:
        if session.operator_user_id != operator_id or session.outbound_record_id != record_id:
            raise StationError('REQUEST_CONFLICT', '扫码请求内容已变化，请重新扫码')
        _active(session)
        return _view(db, session)
    now = beijing_now()
    session = ShippingStationSession(id=str(uuid.uuid4()), login_user_id=login_id,
        operator_user_id=person.id, operator_name=person.real_name, outbound_record_id=record_id,
        scan_request_id=request_id, created_at=now, last_active_at=now,
        expires_at=now + timedelta(hours=get_settings().SHIPPING_STATION_MAX_HOURS))
    view = _view(db, session)  # Verify source data exists before writing any scan event.
    db.add(session)
    _event(db, session, 'scan', request_id, {'operator_id': operator_id}, {'session_id': session.id})
    service._commit(db)
    return view


def refresh(db, login_id, session_id):
    session = session_for(db, login_id, session_id)
    result = _view(db, session)
    session.last_active_at = beijing_now()
    service._commit(db)
    return result


def media_for(db, session, media_id):
    media = db.query(ShippingInspectionPhoto).join(ShippingInspection, ShippingInspection.id == ShippingInspectionPhoto.inspection_id).filter(
        ShippingInspectionPhoto.id == media_id, ShippingInspection.outbound_record_id == session.outbound_record_id,
    ).first()
    if not media:
        raise StationError('MEDIA_NOT_FOUND', '该单据中没有此照片或视频', 404)
    return media


async def upload(db, login_id, session_id, file, item_id, edit_version, request_id, media_type):
    # Never keep authorization/session locks while receiving a large file.
    session_for(db, login_id, session_id)
    db.rollback()
    rel_path = None
    try:
        if media_type == 'video':
            rel_path = await file_service.store_video(file)
        else:
            content = await file.read(20 * 1024 * 1024 + 1)
            file_service.validate_upload(file.filename, file.content_type or '', len(content))
            rel_path = file_service.store_bytes(file.filename, content)
        digest = hashlib.sha256()
        with file_service.resolve_path(rel_path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        session = session_for(db, login_id, session_id)
        payload = {'item_id': item_id or None, 'edit_version': edit_version, 'type': media_type, 'sha256': digest.hexdigest()}
        prior = _replay(db, session, 'upload', request_id, payload)
        if prior is not None:
            file_service.remove_file(rel_path)
            return prior
        photo = service.add_photo(db, outbound_record_id=session.outbound_record_id, item_id=item_id,
            user_id=session.operator_user_id, file_path=rel_path, media_type=media_type, edit_version=edit_version, commit=False)
        result = {'id': photo.id, 'file_path': photo.file_path, 'media_type': photo.media_type,
                  'storage_state': getattr(photo, '_storage_state', 'local')}
        _event(db, session, 'upload', request_id, payload, result, inspection=db.get(ShippingInspection, photo.inspection_id), media_id=photo.id)
        service._commit(db)
        return result
    except Exception:
        db.rollback()
        if rel_path:
            # An uncertain commit must not delete an already referenced object.
            if not db.query(ShippingInspectionPhoto.id).filter_by(file_path=rel_path).first():
                file_service.remove_file(rel_path)
        raise


def delete_media(db, login_id, session_id, media_id, edit_version, request_id):
    session = session_for(db, login_id, session_id)
    payload = {'media_id': media_id, 'edit_version': edit_version}
    prior = _replay(db, session, 'delete', request_id, payload)
    if prior is not None:
        return prior
    media = media_for(db, session, media_id)
    inspection = db.get(ShippingInspection, media.inspection_id)
    path = service.delete_photo(db, media.id, session.operator_user_id, edit_version=edit_version, media_type=media.media_type, commit=False)
    result = {'deleted': True}
    _event(db, session, 'delete', request_id, payload, result, inspection=inspection, media_id=media_id)
    service._commit(db)
    if not service.transfers.managed('shipping-inspection'):
        file_service.remove_file(path)
    return result


def submit(db, login_id, session_id, edit_version, request_id, remark, submitted_ids=None):
    session = session_for(db, login_id, session_id, allow_ended=True)
    payload = {'edit_version': edit_version, 'remark': remark}
    prior = _replay(db, session, 'submit', request_id, payload)
    if prior is not None:
        return prior
    _active(session)
    inspection = service._get_by_outbound_id(db, session.outbound_record_id)
    if inspection:
        inspection = service._lock_inspection(db, inspection.id)
        if inspection.status == 'submitted':
            raise StationError('ALREADY_SUBMITTED', '本单已由其他操作提交，请刷新查看')
    inspection = service.submit(db, outbound_record_id=session.outbound_record_id, user_id=session.operator_user_id,
                                edit_version=edit_version, remark=remark, commit=False, submitted_ids=submitted_ids)
    result = {'id': inspection.id, 'status': inspection.status, 'operator_name': session.operator_name,
              'outbound_no': inspection.outbound_no, 'submitted_at': inspection.submitted_at.isoformat()}
    session.ended_at = beijing_now()
    _event(db, session, 'submit', request_id, payload, result, inspection=inspection)
    service._commit(db)
    return result


def end(db, login_id, session_id):
    session = session_for(db, login_id, session_id, allow_ended=True)
    if not session.ended_at:
        session.ended_at = beijing_now()
        _event(db, session, 'end', None, None, {'ended': True})
        service._commit(db)
    return {'ended': True}
