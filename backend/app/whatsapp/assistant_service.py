"""Admission, current-source result access, and private checklist persistence."""
from copy import deepcopy
from datetime import timedelta
import re
import uuid

from app.ai.service import prepare_text_chat
from app.core.config import get_settings
from app.core.time import beijing_now
from app.knowledge.access import has_platform
from app.whatsapp import assistant_knowledge
from app.whatsapp.assistant_input import LIMITS, authorized_account, capture, chunks, normalize_range, prompt_messages
from app.whatsapp.assistant_models import WhatsAppAssistantRun


class AssistantConflict(ValueError):
    pass


ERRORS = {
    'SOURCE_CHANGED': '聊天记录或授权已变化，请重新选择范围分析。',
    'KNOWLEDGE_CHANGED': '知识版本或知识访问权限已变化，请重新分析。',
    'AUTH_CHANGED': '当前账号或员工授权已变化，分析已停止。',
    'PRESET_UNAVAILABLE': 'AI消息助手预设不可用，请联系管理员检查AI设置。',
    'MODEL_CALL_FAILED': '模型调用失败，本次结果未发布；可查看记录后重新发起。',
    'INVALID_MODEL_OUTPUT': '模型结果格式或引用无效，本次未发布跟进建议。',
    'ANALYSIS_TIMEOUT': '本次分析已超时或执行进程中断，请重新发起。',
    'LIMIT_EXCEEDED': '记录超出单次分析容量，请缩短范围后重试。',
    'PROCESSING_FAILED': '分析处理失败，本次结果未发布，请联系管理员。',
}


def preset_snapshot(db):
    return prepare_text_chat(db, get_settings().WHATSAPP_ASSISTANT_PRESET_NAME, 4096)


def options(db, user_id, account_uid):
    account, actor = authorized_account(db, user_id, account_uid)
    try:
        preset_snapshot(db)
        configured = True
    except ValueError:
        configured = False
    allowed = account.consent_state == 'active' and bool(account.ai_egress_allowed)
    reason = '' if allowed and configured else (
        '请由持有人在授权范围中开启AI分析外发。' if not allowed else ERRORS['PRESET_UNAVAILABLE'])
    return {'ai_allowed': allowed, 'knowledge_available': has_platform(actor, 'knowledge:read'),
        'preset_available': configured, 'can_analyze': allowed and configured, 'reason': reason, 'limits': LIMITS}


def expire(db, run):
    if run.status in {'pending', 'running'} and beijing_now() - run.created_at > timedelta(seconds=get_settings().WHATSAPP_ASSISTANT_TIMEOUT_SECONDS):
        finish(run, 'failed', 'ANALYSIS_TIMEOUT')
        db.commit()


def finish(run, status, code=None):
    run.status = status
    run.active_slot = None
    run.finished_at = beijing_now()
    run.error_code = code
    run.error_message = ERRORS.get(code)
    if status != 'succeeded':
        run.result_json = None


def create_run(db, user_id, *, account_uid, start_at, end_at, client_request_uid, conversation_uid=None):
    start, end = normalize_range(start_at, end_at)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', client_request_uid):
        raise ValueError('请求标识无效')
    account, _actor = authorized_account(db, user_id, account_uid, generate=True, fresh=True)
    previous = db.query(WhatsAppAssistantRun).filter_by(requested_by=user_id, client_request_uid=client_request_uid).populate_existing().with_for_update().first()
    if previous is not None:
        if (previous.account_uid, previous.start_at, previous.end_at, previous.conversation_uid) != (account_uid, start, end, conversation_uid):
            raise AssistantConflict('请求标识已用于另一分析范围')
        expire(db, previous)
        return previous
    active = db.query(WhatsAppAssistantRun).filter_by(requested_by=user_id, account_uid=account_uid, active_slot=1).populate_existing().with_for_update().first()
    if active is not None:
        expire(db, active)
        if active.active_slot:
            raise AssistantConflict('该账号已有分析进行中，请先查看已有记录')
        # expire() committed the old slot. Reacquire admission locks and check
        # another request did not claim the released slot during that commit.
        account, _actor = authorized_account(db, user_id, account_uid, generate=True, fresh=True)
        winner = db.query(WhatsAppAssistantRun).filter_by(requested_by=user_id,
            client_request_uid=client_request_uid).populate_existing().with_for_update().first()
        if winner is not None:
            if (winner.account_uid, winner.start_at, winner.end_at, winner.conversation_uid) != (account_uid, start, end, conversation_uid):
                raise AssistantConflict('请求标识已用于另一分析范围')
            return winner
        claimed = db.query(WhatsAppAssistantRun).filter_by(requested_by=user_id, account_uid=account_uid,
            active_slot=1).populate_existing().with_for_update().first()
        if claimed is not None:
            raise AssistantConflict('该账号已有分析进行中，请先查看已有记录')
    preset_snapshot(db)
    groups, input_hash, warnings = capture(db, account_uid, start, end, conversation_uid, fresh=True)
    if not groups:
        raise ValueError('所选时间段没有已同步消息，请调整时间范围')
    worst_calls = sum(2 * len(chunks(prompt_messages(group['messages']))) - 1 for group in groups)
    if worst_calls > LIMITS['max_calls']:
        raise ValueError('所选会话需要超过20次分段分析，请缩短时间范围；未截断聊天')
    run = WhatsAppAssistantRun(run_uid='wai_' + uuid.uuid4().hex, account_uid=account_uid, requested_by=user_id,
        client_request_uid=client_request_uid, conversation_uid=conversation_uid, start_at=start, end_at=end,
        session_generation=account.session_generation, consent_version=account.consent_version,
        message_count=sum(len(group['messages']) for group in groups), conversation_count=len(groups),
        input_manifest={'input_hash': input_hash, 'knowledge_sources': [], 'snapshot_mode': 'metadata'},
        warnings_json=warnings)
    db.add(run)
    db.commit()
    return run


def owned_run(db, user_id, run_uid, *, generate=False):
    row = db.query(WhatsAppAssistantRun).filter_by(run_uid=run_uid, requested_by=user_id).first()
    if row is None:
        raise LookupError('分析记录不存在')
    account, actor = authorized_account(db, user_id, row.account_uid, generate=generate, fresh=True)
    run = db.query(WhatsAppAssistantRun).filter_by(id=row.id).populate_existing().with_for_update().one()
    return run, account, actor


def check_sources(db, run, account, actor):
    if (account.session_generation, account.consent_version) != (run.session_generation, run.consent_version):
        return 'SOURCE_CHANGED'
    try:
        _groups, current_hash, _warnings = capture(db, run.account_uid, run.start_at, run.end_at, run.conversation_uid, fresh=True)
    except (ValueError, LookupError):
        return 'SOURCE_CHANGED'
    if current_hash != run.input_manifest['input_hash']:
        return 'SOURCE_CHANGED'
    if not assistant_knowledge.revalidate_sources(db, actor, run.input_manifest.get('knowledge_sources', []), fresh=True):
        return 'KNOWLEDGE_CHANGED'
    return None


def serialize(run, *, results=False):
    output = deepcopy(run.result_json or []) if results and run.status == 'succeeded' else []
    for group in output:
        for task in group['tasks']:
            task['completed'] = bool((run.task_state or {}).get(task['task_uid'], False))
    return {'run_uid': run.run_uid, 'account_uid': run.account_uid, 'status': run.status,
        'start_at': run.start_at, 'end_at': run.end_at, 'message_count': run.message_count,
        'conversation_count': run.conversation_count, 'processed_conversations': run.processed_conversations,
        'created_at': run.created_at, 'error_code': run.error_code, 'error_message': run.error_message,
        'warnings': run.warnings_json or [], 'results': output, 'audit': {'snapshot_mode': 'metadata'}}


def get_run(db, user_id, run_uid):
    run, account, actor = owned_run(db, user_id, run_uid)
    expire(db, run)
    if run.status == 'succeeded':
        reason = check_sources(db, run, account, actor)
        if reason:
            finish(run, 'stale', reason)
            db.commit()
    return serialize(run, results=True)


def list_runs(db, user_id, account_uid):
    authorized_account(db, user_id, account_uid)
    rows = db.query(WhatsAppAssistantRun).filter_by(account_uid=account_uid, requested_by=user_id).order_by(
        WhatsAppAssistantRun.created_at.desc(), WhatsAppAssistantRun.id.desc()).limit(10).all()
    return {'items': [serialize(row) for row in rows]}


def find_request(db, user_id, account_uid, request_uid):
    authorized_account(db, user_id, account_uid)
    row = db.query(WhatsAppAssistantRun).filter_by(account_uid=account_uid, requested_by=user_id, client_request_uid=request_uid).first()
    if row is None:
        raise LookupError('未找到本次分析记录')
    return get_run(db, user_id, row.run_uid)


def update_task(db, user_id, run_uid, task_uid, *, completed):
    run, account, actor = owned_run(db, user_id, run_uid)
    if run.status != 'succeeded':
        raise AssistantConflict('本次分析结果已失效，不能更新清单')
    reason = check_sources(db, run, account, actor)
    if reason:
        finish(run, 'stale', reason); db.commit()
        raise AssistantConflict(ERRORS[reason])
    task_ids = {task['task_uid'] for group in run.result_json for task in group['tasks']}
    if task_uid not in task_ids:
        raise LookupError('跟进项不存在')
    run.task_state = {**(run.task_state or {}), task_uid: bool(completed)}
    db.commit()
    return serialize(run, results=True)


def execute_run(db, run_uid, *, chat_fn=None):
    from app.whatsapp.assistant_runner import execute
    return execute(db, run_uid, chat_fn=chat_fn)
