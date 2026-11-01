"""Administrator manual review of an uncertain outbound invoice sync.

Restores the pre-transition manual recovery ("timeout unlock = human
confirmation") for two cases the automatic GET recovery cannot finish:

* a protocol-1 task whose committed send claim stayed sending/unknown;
* an office task written before protocol 1 (no durable send record).

Lock order is the normal capture order: portal barrier -> policy -> invoice
authority (route/state/frozen checked) -> lineage -> invoice -> task row. No
remote read happens while those locks are held, and nothing here sends.
"""
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from app.commerce_transition import service as ownership
from app.commerce_transition.models import SendingClaim
from app.core.time import beijing_now, to_beijing_naive
from app.invoice import legacy_sending, okki_client
from app.shipping_inspection import audit_service, outbound_facts as facts, outbound_prepare as prepare
from app.shipping_inspection import outbound_sync_plan as plans, outbound_sync_state as state
from app.shipping_inspection.models import ShippingOperationEvent

logger = logging.getLogger(__name__)

RESOLUTIONS = ('confirm_not_created', 'bind_existing')
ADMIN_PERMISSIONS = ('shipping_inspection:admin', 'invoice:admin')
LEGACY_GUIDANCE = '历史出库任务缺少可信原发送记录，请由仓库或开票管理员在出库单「人工核对」中确认未生成，或绑定已存在的小满出库结果'


def clear(db):
    db.rollback(); db.expire_all()


def legacy_pending(db, record):
    """Unlocked read-only peek used to guide users before the normal sync path."""
    record_id = record['outbound_record_id'] if isinstance(record, dict) else record
    try:
        event = db.query(ShippingOperationEvent).filter_by(scope=state.SCOPE, request_id=str(record_id)).first()
        return bool(event and event.action in state.ACTIVE and (event.payload or {}).get('protocol') != 1)
    finally:
        clear(db)


def _admin(actor):
    if 'super_admin' not in actor['roles'] and not any(code in actor['permissions'] for code in ADMIN_PERMISSIONS):
        prepare.reject(403, '仅出库管理员或开票管理员可人工确认原出库同步结果')


def _locked(db, record, user, warehouse):
    actor = prepare.current(db, user, warehouse)
    _admin(actor)
    original = prepare.mirror(db, record, actor, warehouse)
    try:
        invoice, event, _, _, _ = prepare.capture(db, original, actor)
    except ownership.TransitionError as error:
        clear(db)
        prepare.reject(409, f'{error}；出库同步待核对暂不能人工处理')
    if event is None or event.action not in state.ACTIVE:
        clear(db)
        prepare.reject(409, '出库单当前没有待核对的同步任务，无需人工处理；请刷新后查看')
    return actor, original, invoice, event


def _review(actor, resolution, reason, previous_action):
    return {'resolution': resolution, 'operator_id': actor['id'], 'reason': reason,
            'previous_action': previous_action, 'reviewed_at': beijing_now().isoformat()}


def resolve(db, record, user, warehouse, resolution, reason):
    note = str(reason or '').strip()
    if resolution not in RESOLUTIONS:
        prepare.reject(400, '人工核对方式只能为确认未生成或绑定已存在的小满结果')
    if len(note) < 8:
        prepare.reject(400, '请填写至少8个字符的人工核对依据')
    clear(db)  # End the request's read-only dependency snapshot; review starts fresh.
    actor, original, invoice, event = _locked(db, record, user, warehouse)
    if (event.payload or {}).get('protocol') == 1:
        return _resolve_attempt(db, actor, original, invoice, event, resolution, note)
    return _resolve_legacy(db, record, user, warehouse, actor, original, invoice, event, resolution, note)


def _resolve_attempt(db, actor, original, invoice, event, resolution, note):
    attempt = facts.load(db, event)
    # Even an already-uncertain POST may still land remotely right after a timeout.
    if not facts.expired(attempt):
        clear(db)
        prepare.reject(409, '原发送仍在5分钟执行租约内，请稍后再核对，避免与仍在进行的发送冲突')
    if resolution == 'bind_existing':
        clear(db)
        prepare.reject(409, '该任务有完整原发送记录，请直接点「同步」核对，系统会读取小满原单自动完成或补齐')
    fact = facts.get(db, facts.FACT, attempt.nonce)
    result_class = fact.result.get('result_class') if fact is not None else None
    if result_class == 'accepted':
        clear(db)
        prepare.reject(409, '原发送已收到小满接受回执，不能确认未生成；请点「同步」读取原单核对或补齐')
    key = f'legacy:outbound-sync:{attempt.nonce}'
    claim = legacy_sending.find(db, key)
    remote_evidence = {'outbound_invoice_id': str(original['outbound_invoice_id']),
                       'original_result_class': result_class,
                       'facts_fingerprint': facts.fingerprint(db, attempt)}
    if claim is not None and claim.state == 'succeeded':
        clear(db)
        prepare.reject(409, '原发送已被小满受理，不能确认未生成；请点「同步」读取原单核对')
    if claim is not None and claim.state in ownership.MANUALLY_RELEASABLE:
        try:
            ownership.confirm_not_sent(db, claim.id, operator_id=int(actor['id']), reason=note,
                                       source='outbound.sync_review', remote_evidence=remote_evidence)
        except ownership.TransitionError as error:
            logger.warning('Outbound manual review refused by claim gate record=%s', original['outbound_record_id'])
            print(f"[outbound-manual-review] claim gate refused record={original['outbound_record_id']}", flush=True)
            clear(db)
            prepare.reject(409, str(error))
    review = _review(actor, 'confirm_not_created', note, event.action)
    for item in facts.chain(db, attempt):
        if facts.get(db, facts.FINISH, item.nonce) is not None:
            continue
        facts.append(db, facts.FINISH, item.nonce, item, facts.identity(item),
            {'facts_fingerprint': facts.fingerprint(db, item, include_reads=False),
             'not_sent': item.nonce == attempt.nonce, 'manual_review': review})
    message = '管理员已确认原出库同步未生效，订单锁已释放；请重新预览后同步'
    event.action = 'sync_failed'
    event.result = {**(event.result or {}), 'message': message, 'manual_review': review}
    db.commit(); clear(db)
    return {'status': 'sync_failed', 'requires_preview': True, 'message': message}


def _open_legacy_claim(db, invoice, record_id):
    claims = db.query(SendingClaim).filter(SendingClaim.invoice_id == invoice.id,
        SendingClaim.operation == 'outbound_update',
        SendingClaim.state.in_(sorted(ownership.MANUALLY_RELEASABLE))).with_for_update().all()
    return any(str((claim.responsibilities or {}).get('outbound_record_id')) == str(record_id) for claim in claims)


def _audit(db, actor, record_id, review, result):
    audit_service.record(db, 'sync_manual_review', actor['id'], str(record_id),
        context={'scope': facts.LEGACY_REVIEW, 'source': 'pc'}, request_id=f'{record_id}:{uuid4().hex}',
        payload=deepcopy(review), result=deepcopy(result))


def _legacy_checks(db, original, invoice, event):
    record_id = original['outbound_record_id']
    if _open_legacy_claim(db, invoice, record_id):
        clear(db)
        prepare.reject(409, '该出库单存在原发送责任，请按当前出库核对入口处理')
    if event.action in state.ACTIVE:
        stamp = (event.result or {}).get('started_at')
        try:
            if to_beijing_naive(datetime.fromisoformat(stamp)) + timedelta(minutes=5) > beijing_now():
                clear(db)
                prepare.reject(409, '旧同步任务仍在5分钟执行租约内，请稍后再核对')
        except (TypeError, ValueError):
            logger.warning('Legacy outbound task has no valid lease timestamp record=%s', record_id)
            print(f'[outbound-manual-review] legacy lease timestamp invalid record={record_id}', flush=True)
    plan = (event.payload or {}).get('plan') or {}
    if not isinstance(plan.get('before'), dict) or not plan['before'].get('outbound_invoice_id'):
        clear(db)
        prepare.reject(409, '旧同步任务缺少原出库目标，请联系管理员核对数据')
    return plan


def _resolve_legacy(db, record, user, warehouse, actor, original, invoice, event, resolution, note):
    record_id = original['outbound_record_id']
    plan = _legacy_checks(db, original, invoice, event)
    review = _review(actor, resolution, note, event.action)
    if resolution == 'confirm_not_created':
        message = '管理员已确认旧出库同步任务未生效；请重新预览后同步'
        event.action = 'sync_failed'
        event.result = {**(event.result or {}), 'message': message, 'manual_review': review}
        _audit(db, actor, record_id, review, {'status': 'sync_failed'})
        db.commit(); clear(db)
        return {'status': 'sync_failed', 'requires_preview': True, 'message': message}
    baseline = prepare.row_state(event)
    db.commit(); clear(db)  # Never hold authority or business locks across the supplier read.
    try:
        after = prepare.read_outbound(db, plan['before']['outbound_invoice_id'])
        plans.verify(plan['before'], after, plan)
        after = deepcopy(after)
    except (ValueError, KeyError, TypeError):
        logger.warning('Legacy outbound task readback does not match its plan record=%s', record_id)
        print(f'[outbound-manual-review] legacy readback mismatch record={record_id}', flush=True)
        prepare.reject(409, '小满出库单与旧同步计划不一致，不能按已完成处理；如确认本次同步未生效，请选择「确认未生成」')
    except okki_client.OkkiApiError:
        logger.warning('Legacy outbound task readback unavailable record=%s', record_id)
        print(f'[outbound-manual-review] legacy readback unavailable record={record_id}', flush=True)
        prepare.reject(503, '小满出库单暂不可读取，请稍后再核对')
    finally:
        clear(db)
    actor, original, invoice, event = _locked(db, record, user, warehouse)
    if prepare.row_state(event) != baseline:
        clear(db)
        prepare.reject(409, '核对期间原出库任务已变化，请刷新后重新核对')
    _legacy_checks(db, original, invoice, event)
    from app.shipping_inspection import outbound_sync_service as legacy
    result = legacy._finish_verified(db, event, plan, after, commit_result=False, finisher_id=actor['id'])
    _audit(db, actor, record_id, review, {'status': result['status'], 'readback_sha256': plans.digest(after)})
    db.commit(); clear(db)
    return result
