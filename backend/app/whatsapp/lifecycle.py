"""Durable bind/rebind operations and explicit owner authorization."""
import logging
import uuid

from app.core.time import beijing_now
from app.whatsapp import access
from app.whatsapp.connector_client import ConnectorError, WhatsAppConnectorClient
from app.whatsapp.models import WhatsAppAccount, WhatsAppBindSession, WhatsAppBodyGrant

logger = logging.getLogger(__name__)


def owned_account(db, uid: str, actor: dict, *, allow_manager=False):
    live = access.live_actor(db, int(actor['sub']), 'whatsapp:write')
    account = db.query(WhatsAppAccount).filter_by(account_uid=uid).populate_existing().with_for_update().first()
    if account is None:
        raise LookupError('WhatsApp 账号不存在')
    if account.ark_user_id != int(live['sub']) and not (allow_manager and access.is_manager(live)):
        raise PermissionError('仅账号持有人可确认采集与正文授权')
    return account


def _read_operation(db, client, session):
    try:
        return client.get_bind_session(session.bind_session_uid)
    except ConnectorError as exc:
        if exc.status_code == 404:
            # Positive readback: no remote operation exists. Finish this failed
            # reservation; another explicit human request may create a new one.
            session.status = 'error'
            session.qr_code_url = None
            session.updated_at = beijing_now()
            db.commit()
            raise ValueError('连接器确认关联操作未建立，请重新点击关联') from exc
        raise


def bind(db, actor: dict, *, account_uid: str | None, company_account: bool, crm_shared: bool):
    from app.whatsapp.service import _upsert_bind_session, _audit
    user_id = int(access.live_actor(db, int(actor['sub']), 'whatsapp:write')['sub'])
    if not company_account:
        raise ValueError('请先确认这是公司专用业务号，允许同步全部业务会话')
    account = owned_account(db, account_uid, actor) if account_uid else None
    if account is None:
        pending = db.query(WhatsAppBindSession).filter_by(ark_user_id=user_id).filter(
            WhatsAppBindSession.status.in_(('pending', 'binding')),
        ).order_by(WhatsAppBindSession.id.desc()).first()
    else:
        pending = db.query(WhatsAppBindSession).filter_by(account_uid=account.account_uid).filter(
            WhatsAppBindSession.status.in_(('pending', 'binding')),
        ).order_by(WhatsAppBindSession.id.desc()).first()
    if pending:
        # A lost bind response is read back using the exact durable operation.
        payload = _read_operation(db, WhatsAppConnectorClient(), pending)
        return _upsert_bind_session(db, payload, user_id)
    if account is None:
        account = WhatsAppAccount(account_uid=f'wa_acc_{uuid.uuid4()}', ark_user_id=user_id)
        db.add(account)
        db.flush()
    account.provider = 'baileys'
    account.session_generation = (account.session_generation or 0) + 1
    account.consent_version = (account.consent_version or 0) + 1
    account.consent_state = 'active'
    account.crm_shared = crm_shared
    account.ai_egress_allowed = False
    account.status = 'binding'
    account.connector_status = 'initializing'
    db.query(WhatsAppBodyGrant).filter_by(account_uid=account.account_uid).delete()
    session = WhatsAppBindSession(
        bind_session_uid=f'bind_{uuid.uuid4()}', account_uid=account.account_uid,
        ark_user_id=user_id, status='pending', created_at=beijing_now(), updated_at=beijing_now(),
    )
    db.add(session)
    _audit(db, action='authorize_company_account', result='success', ark_user_id=user_id, account_uid=account.account_uid,
           detail=f'consent_version={account.consent_version},crm_shared={crm_shared}')
    # The callback must be able to see the reservation before the socket starts.
    db.commit()
    client = WhatsAppConnectorClient()
    try:
        payload = client.create_bind_session(user_id, account_uid=account.account_uid,
            bind_session_uid=session.bind_session_uid, provider='baileys', consent_version=account.consent_version,
            session_generation=account.session_generation)
    except ConnectorError:
        logger.warning('WhatsApp bind result uncertain; reading reserved operation')
        print('[WhatsApp] bind result uncertain; reading reserved operation', flush=True)
        # No retry POST. Keep the reservation if readback is also unavailable.
        payload = _read_operation(db, client, session)
    return _upsert_bind_session(db, payload, user_id)


def update_consent(db, uid: str, actor: dict, *, crm_shared: bool, reader_user_ids: list[int], enabled: bool, ai_egress_allowed: bool = False):
    from app.whatsapp.service import _audit
    account = owned_account(db, uid, actor)
    for user_id in reader_user_ids:
        access.live_actor(db, user_id, 'whatsapp:read')
    account.consent_version = (account.consent_version or 0) + 1
    account.consent_state = 'active' if enabled else 'paused'
    account.crm_shared = bool(crm_shared and enabled)
    account.ai_egress_allowed = bool(ai_egress_allowed and enabled)
    if not enabled:
        account.status = 'paused'
    db.query(WhatsAppBodyGrant).filter_by(account_uid=uid).delete()
    if enabled:
        for user_id in set(reader_user_ids):
            if user_id != account.ark_user_id:
                db.add(WhatsAppBodyGrant(account_uid=uid, user_id=user_id, consent_version=account.consent_version))
        if account.status == 'paused':
            account.status = 'active'
    _audit(db, action='update_consent', result='success', ark_user_id=int(actor['sub']), account_uid=uid,
           detail=f'consent_version={account.consent_version},enabled={enabled},readers={len(reader_user_ids)}')
    db.commit()
    # Changing consent fences the old worker. The explicit owner operation can
    # adopt the new version while keeping registered encrypted credentials.
    try:
        client = WhatsAppConnectorClient()
        payload = client.reauthorize_account(uid) if enabled else client.pause_account(uid)
        account.connector_status = payload.get('connector_status') or payload.get('connection_state')
    except ConnectorError:
        logger.warning('WhatsApp pause acknowledgement unavailable; callback fences collection')
        print('[WhatsApp] pause acknowledgement unavailable; callback fences collection', flush=True)
        account.connector_status = 'pause_unconfirmed'
    return account


def revoke(db, uid: str, actor: dict):
    from app.whatsapp.service import _audit
    account = owned_account(db, uid, actor, allow_manager=True)
    if account.consent_state == 'revoked' and account.status in ('revoked', 'revoke_pending'):
        return account  # Repeating an uncertain logout is not evidence of removal.
    account.consent_state = 'revoked'
    account.consent_version = (account.consent_version or 0) + 1
    account.status = 'revoking'
    account.crm_shared = False
    account.ai_egress_allowed = False
    db.query(WhatsAppBodyGrant).filter_by(account_uid=uid).delete()
    _audit(db, action='revoke_account', result='pending', ark_user_id=int(actor['sub']), account_uid=uid)
    db.commit()  # Deny reads and new writes before the external logout attempt.
    client = WhatsAppConnectorClient()
    try:
        payload = client.revoke_account(uid)
    except ConnectorError:
        logger.warning('WhatsApp logout result uncertain; reading account status')
        print('[WhatsApp] logout result uncertain; reading account status', flush=True)
        try:
            payload = client.get_account(uid)
        except ConnectorError:
            payload = {'status': 'revoke_pending', 'connector_status': 'remote_unconfirmed', 'revoke_state': 'remote_unconfirmed'}
            logger.warning('WhatsApp logout status unavailable; remote result remains unconfirmed')
            print('[WhatsApp] logout status unavailable; remote result remains unconfirmed', flush=True)
    confirmed = payload.get('revoke_state') in {'revoked_confirmed', 'remote_confirmed'}
    account.status = 'revoked' if confirmed else 'revoke_pending'
    account.connector_status = payload.get('revoke_state') or 'remote_unconfirmed'
    account.raw_payload = payload
    return account


def confirm_phone_removal(db, uid: str, actor: dict, *, phone_device_removed: bool):
    from app.whatsapp.service import _audit
    account = owned_account(db, uid, actor)
    if not phone_device_removed or account.status != 'revoke_pending' or account.consent_state != 'revoked':
        raise ValueError('仅能确认已停止采集且持有人已核对手机移除的设备')
    # Explicit human attestation is labeled separately from a protocol ACK.
    account.status = 'revoked'
    account.connector_status = 'owner_confirmed'
    account.raw_payload = {**(account.raw_payload or {}), 'revoke_state': 'owner_confirmed', 'confirmation_source': 'account_owner_phone_check'}
    _audit(db, action='confirm_phone_removal', result='owner_confirmed', ark_user_id=int(actor['sub']), account_uid=uid)
    return account
