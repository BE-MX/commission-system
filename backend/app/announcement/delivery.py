"""Database outbox; ambiguous external writes never blindly retry."""
import logging
from datetime import timedelta
from uuid import uuid4
from sqlalchemy.orm import aliased

from app.core.time import beijing_now
from app.knowledge import access, service as knowledge
from app.knowledge.ai_job_service import identity_for_user
from app.knowledge.models import KnowledgeDocument
from app.knowledge.managed import announcement_scope
from app.announcement.models import AnnouncementConfig, Publication, Delivery, WeeklyReport
from app.announcement import service
from app.dingtalk import announcement_sender as transport

logger = logging.getLogger(__name__)


def allowed(db, task):
    config = db.get(AnnouncementConfig, 1)
    identity = identity_for_user(db, config.executor_id)
    service.config_for(db, identity)
    if not task.source_key.startswith('test:'):
        service.channel_ready(config)
    if task.payload.get('acl') != service.acl_fingerprint(db, config.library_id):
        raise knowledge.ConflictError('公告库成员权限已变化，请重新确认披露范围')
    if (task.target, task.robot_code) != (config.conversation_id, config.robot_code):
        raise knowledge.ConflictError('目标群已改变，旧任务停止投递')
    if task.publication_id:
        event = db.get(Publication, task.publication_id)
        document = db.get(KnowledgeDocument, event.document_id)
        if not document or document.deleted_at:
            raise knowledge.ConflictError('公告已删除')
        if event.kind != 'withdraw' and document.published_revision_id != event.revision_id:
            raise knowledge.ConflictError('公告已更新或撤回')
    if task.weekly_id:
        from app.announcement.weekly import sources_valid
        report = db.get(WeeklyReport, task.weekly_id)
        if task.payload['generation'] != report.generation or not sources_valid(db, report.sources):
            raise knowledge.ConflictError('周报来源已撤回，请重新生成')
    return config


def recover(db):
    for row in db.query(Delivery).filter(Delivery.status.in_(['preparing', 'sending']), Delivery.lease_until < beijing_now()).with_for_update():
        row.status = 'uncertain' if row.status == 'sending' else 'retry'
        row.error = '进程中断，请核对群内消息' if row.status == 'uncertain' else '准备阶段中断，将重试'
        row.lease_token = None
    db.commit()


def claim(db):
    # One part per tick keeps group rate low; predecessors block subsequent parts.
    prior = aliased(Delivery)
    blocked = db.query(prior.id).filter(prior.source_key == Delivery.source_key,
        prior.sequence < Delivery.sequence, prior.status != 'sent').exists()
    candidates = db.query(Delivery).filter(Delivery.status.in_(['queued', 'retry']),
        Delivery.next_attempt_at <= beijing_now(), ~blocked).order_by(Delivery.id).limit(100).all()
    for candidate in candidates:
        token = uuid4().hex
        updated = db.query(Delivery).filter(Delivery.id == candidate.id, Delivery.status.in_(['queued', 'retry'])).update({
            Delivery.status: 'preparing', Delivery.lease_token: token, Delivery.lease_until: beijing_now() + timedelta(minutes=3),
            Delivery.attempts: Delivery.attempts + 1}, synchronize_session=False)
        db.commit()
        if updated:
            return candidate.id, token
    return None


def execute(db, task_id, token):
    row = db.query(Delivery).populate_existing().filter_by(id=task_id, lease_token=token, status='preparing').first()
    if not row:
        return
    try:
        config = allowed(db, row)
        library_id = config.library_id
        prepared = transport.prepare_message(db, row.payload)
        # End the MySQL repeatable-read snapshot opened before media upload.
        db.rollback()
        from app.knowledge.models import KnowledgeLibrary
        db.query(KnowledgeLibrary).filter_by(id=library_id).with_for_update().first()
        db.query(AnnouncementConfig).filter_by(id=1).with_for_update().first()
        row = db.query(Delivery).populate_existing().filter_by(id=task_id, lease_token=token, status='preparing').with_for_update().first()
        if not row or row.lease_until <= beijing_now():
            db.rollback()
            return
        allowed(db, row)
        target, robot = row.target, row.robot_code
        row.status = 'sending'
        db.commit()
        receipt = transport.send_message(prepared, target, robot)
        updated = db.query(Delivery).filter_by(id=task_id, lease_token=token, status='sending').update({
            Delivery.status: 'sent', Delivery.receipt: receipt, Delivery.sent_at: beijing_now(),
            Delivery.error: None, Delivery.lease_token: None, Delivery.lease_until: None}, synchronize_session=False)
        db.commit()
        if not updated:
            logger.warning('announcement delivery %s lost lease after submission', task_id)
            print(f'announcement delivery {task_id} lost lease after submission', flush=True)
        return
    except Exception as exc:
        db.rollback()
        row = db.query(Delivery).filter(Delivery.id == task_id, Delivery.lease_token == token,
            Delivery.status.in_(['preparing', 'sending'])).with_for_update().first()
        if not row:
            db.rollback()
            return  # stale workers cannot overwrite recovery or operator decisions
        if isinstance(exc, knowledge.KnowledgeError):
            state, error = 'cancelled', str(exc)[:200]
        elif isinstance(exc, transport.AnnouncementSendError):
            state = 'uncertain' if exc.uncertain else ('retry' if exc.retryable and row.attempts < 3 else 'failed')
            error = exc.code
        else:
            state = 'uncertain' if row.status == 'sending' else ('retry' if row.attempts < 3 else 'failed')
            error = type(exc).__name__
        row.status, row.error = state, error
        row.next_attempt_at = beijing_now() + timedelta(minutes=2 ** min(row.attempts, 3))
        row.lease_token, row.lease_until = None, None
        db.commit()
        logger.warning('announcement delivery %s: %s', task_id, error)
        print(f'announcement delivery {task_id}: {error}', flush=True)


def retry(db, identity, task_id, *, confirm_uncertain=False, mark_delivered=False, cancel=False):
    config = service.config_for(db, identity, 'admin', True)
    row = db.query(Delivery).filter_by(id=task_id).with_for_update().first()
    if not row or row.status not in {'failed', 'uncertain'}:
        raise knowledge.ConflictError('该任务不能重试')
    if row.status == 'uncertain' and not confirm_uncertain:
        raise knowledge.ConflictError('请先核对钉钉群，重发可能产生重复消息')
    if mark_delivered and row.status != 'uncertain':
        raise knowledge.ConflictError('仅不确定任务允许人工核实为已送达')
    if mark_delivered and cancel:
        raise knowledge.ValidationError('请选择一种处理方式')
    if not mark_delivered and not cancel:
        allowed(db, row)
    row.status = 'sent' if mark_delivered else 'cancelled' if cancel else 'queued'
    row.error = '管理员已核对群消息' if mark_delivered else '管理员确认取消投递' if cancel else None
    row.next_attempt_at = beijing_now()
    if mark_delivered:
        row.sent_at = beijing_now()
    knowledge._audit(db, identity, config.library_id, 'announcement_delivery_resolve', 'delivery', row.id,
                     detail={'mark_delivered': mark_delivered, 'confirm_uncertain': confirm_uncertain, 'cancel': cancel})
    db.commit()
