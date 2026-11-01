"""Administrator "confirm not created" for an uncertain replenishment outbound.

The outbound worker's original POST (claim operation outbound_create) can stay
unknown when OKKI's result never arrives and readback finds nothing. Its open
claim blocks every legacy send of the whole order; the pre-transition release
only blocked that task. This review restores the manual "timeout unlock =
human confirmation": it closes the original claim as not_sent with evidence,
finishes the original attempt and returns the task to the stock-checked queue.

Lock order: portal barrier -> policy -> invoice authority -> invoice -> task.
Nothing here sends or reads the supplier.
"""
import logging
from uuid import uuid4

from sqlalchemy import select

from app.commerce_transition import service as ownership
from app.core.time import beijing_now
from app.invoice import legacy_sending, outbound_create_facts as facts, outbound_worker as worker
from app.invoice.models import Invoice, OkkiOutboundTask
from app.portal.authority import lock_authority
from app.shipping_inspection import audit_service
from app.shipping_inspection.outbound_manual_review import ADMIN_PERMISSIONS
from app.shipping_inspection.outbound_prepare import reject

logger = logging.getLogger(__name__)

REVIEW = 'outbound-create-review'
RESOLUTIONS = ('confirm_not_created',)


def _admin(actor):
    if 'super_admin' not in actor['roles'] and not any(code in actor['permissions'] for code in ADMIN_PERMISSIONS):
        reject(403, '仅出库管理员或开票管理员可人工确认原补货出库结果')


def _note(reason):
    note = str(reason or '').strip()
    if not 8 <= len(note) <= 300:
        reject(400, '请填写8到300个字符的人工核对依据')
    return note


def confirm_not_created(db, task_id, actor, reason):
    """actor is the live principal (current()); the caller owns the executor fence."""
    note = _note(reason)
    _admin(actor)
    invoice_id = db.scalar(select(OkkiOutboundTask.invoice_id).where(OkkiOutboundTask.id == task_id))
    worker.clear(db)
    if invoice_id is None:
        reject(404, '待出库任务不存在')
    lock_authority(db, force=True)
    try:
        ownership.lock_recovery_scope(db, [invoice_id])
    except ownership.TransitionError as error:
        worker.clear(db)
        reject(409, str(error))
    db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.id == task_id)
                     .with_for_update().execution_options(populate_existing=True))
    pending = facts.unresolved(db, invoice_id)
    if len(pending) != 1 or task is None or pending[0].data['task_id'] != task.id:
        worker.clear(db)
        reject(409, '该出库任务当前没有待核对的补货提交，无需人工处理；请刷新后查看')
    attempt = pending[0]
    if not worker.expired(attempt):
        worker.clear(db)
        reject(409, '原补货提交仍在5分钟执行租约内，请稍后再核对，避免与仍在进行的发送冲突')
    if facts.get(db, facts.SEND, attempt.nonce) is None:
        worker.clear(db)
        reject(409, '原补货提交尚未发出，系统会在租约结束后自动释放，无需人工处理')
    fact = facts.get(db, facts.FACT, attempt.nonce)
    result_class = fact.result.get('result_class') if fact is not None else None
    if result_class == 'accepted':
        worker.clear(db)
        reject(409, '原补货提交已收到小满接受回执，不能确认未生成；请点「补货同步」读取原单核对')
    state = facts.get(db, facts.STATE, str(task.id))
    if state is None or (state.payload or {}).get('nonce') != attempt.nonce:
        worker.clear(db)
        reject(409, '原补货任务执行记录已变化，请刷新后核对')
    claim = legacy_sending.find(db, f'legacy:outbound-worker:{attempt.nonce}')
    if claim is not None and claim.state == 'succeeded':
        worker.clear(db)
        reject(409, '原补货提交已被小满受理，不能确认未生成；请点「补货同步」读取原单核对')
    remote_evidence = {'task_id': task.id, 'order_id': attempt.data['order_id'],
                       'original_result_class': result_class,
                       'facts_fingerprint': facts.fingerprint(db, attempt)}
    if claim is not None and claim.state in ownership.MANUALLY_RELEASABLE:
        try:
            ownership.confirm_not_sent(db, claim.id, operator_id=int(actor['id']), reason=note,
                                       source='outbound.replenishment_review', remote_evidence=remote_evidence)
        except ownership.TransitionError as error:
            logger.warning('Replenishment review refused by claim gate task=%s', task.id)
            print(f'[replenishment-review] claim gate refused task={task.id}', flush=True)
            worker.clear(db)
            reject(409, str(error))
    review = {'resolution': 'confirm_not_created', 'operator_id': actor['id'], 'reason': note,
              'task_id': task.id, 'nonce': attempt.nonce, 'previous_status': task.status,
              'reviewed_at': beijing_now().isoformat()}
    message = '管理员已确认原补货出库未生成，订单锁已释放；请点「补货同步」重新核库存并生成'
    # waiting_stock is the state both the manual replenishment and the worker re-check.
    worker.checkpoint(db, actor, task, state, attempt, 'waiting_stock', message, finished=True)
    audit_service.record(db, 'create_manual_review', actor['id'], 'create:' + str(invoice_id),
        context={'scope': REVIEW, 'source': 'pc'}, request_id=f'{task.id}:{uuid4().hex}',
        payload=review, result={'status': 'waiting_stock'})
    db.commit()
    worker.clear(db)
    return {'status': 'waiting_stock', 'message': message}
