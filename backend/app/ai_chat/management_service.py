"""Metadata-only chat observability and role-based daily admission limits."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import case, func

from app.ai.models import AiCallLog
from app.ai_chat.billing import estimate_cost
from app.ai_chat.models import AiChatMessage, AiChatRoleLimit, AiChatSession
from app.auth.models import ArkRole, ArkUser, ArkUserRole
from app.core.config import get_settings
from app.core.time import beijing_now, beijing_today


def effective_limit(db, owner_id):
    limits = db.query(AiChatRoleLimit.daily_limit).join(ArkUserRole,
        ArkUserRole.role_id == AiChatRoleLimit.role_id).filter(ArkUserRole.user_id == owner_id).with_for_update(read=True).all()
    return min(value for (value,) in limits) if limits else get_settings().AI_CHAT_DAILY_TURN_LIMIT


def role_limits(db):
    rows = db.query(ArkRole, AiChatRoleLimit).outerjoin(AiChatRoleLimit, AiChatRoleLimit.role_id == ArkRole.id).order_by(ArkRole.id).all()
    return {'default_limit': get_settings().AI_CHAT_DAILY_TURN_LIMIT,
            'items': [{'role_id': role.id, 'name': role.name, 'label': role.label,
                       'daily_limit': limit.daily_limit if limit else None} for role, limit in rows]}


def set_role_limit(db, role_id, daily_limit, actor_id):
    from app.ai_chat.service import ResourceNotFoundError
    try:
        role = db.query(ArkRole).filter(ArkRole.id == role_id).with_for_update().first()
        if role is None:
            raise ResourceNotFoundError('角色不存在')
        existing = db.query(AiChatRoleLimit).filter_by(role_id=role_id).populate_existing().with_for_update().first()
        if daily_limit is None:
            if existing is not None:
                db.delete(existing)
        else:
            if type(daily_limit) is not int or not 0 <= daily_limit <= 10000:
                raise ValueError('每日额度须为 0–10000')
            if existing is None:
                existing = AiChatRoleLimit(role_id=role_id)
                db.add(existing)
            existing.daily_limit = daily_limit
            existing.updated_by = actor_id
            existing.updated_at = beijing_now()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return role_limits(db)


def _bucket():
    return dict(requests=0, completed=0, failed=0, stopped=0, streaming=0, token_requests=0,
                input_tokens=0, output_tokens=0, latency_count=0, duration_sum=0,
                first_token_count=0, first_token_sum=0, priced_requests=0, estimated_costs={})


def _add(target, row, pricing):
    count = row.requests
    target['requests'] += count
    target[row.status] += count
    for key in ('token_requests', 'input_tokens', 'output_tokens', 'latency_count', 'duration_sum',
                'first_token_count', 'first_token_sum'):
        target[key] += getattr(row, key) or 0
    cost = estimate_cost(pricing, row.priced_input or 0, row.priced_output or 0)
    if cost is not None and row.token_requests:
        target['priced_requests'] += row.token_requests
        currency = pricing['currency']
        target['estimated_costs'][currency] = target['estimated_costs'].get(currency, Decimal(0)) + cost


def _finish(bucket):
    result = dict(bucket)
    result['avg_duration_ms'] = round(result.pop('duration_sum') / result['latency_count']) if result['latency_count'] else None
    result['avg_first_token_ms'] = round(result.pop('first_token_sum') / result['first_token_count']) if result['first_token_count'] else None
    terminal = result['completed'] + result['failed']
    result['failure_rate'] = round(result['failed'] / terminal, 4) if terminal else None
    result['estimated_costs'] = {key: str(value.quantize(Decimal('0.000001'))) for key, value in result['estimated_costs'].items()}
    result['unpriced_requests'] = result['requests'] - result['priced_requests']
    return result


def usage_report(db, start=None, end=None, *, preset_id=None, owner_id=None):
    from app.ai_chat.generation_service import live_condition
    end = end or beijing_today()
    start = start or end - timedelta(days=6)
    if end < start or (end - start).days > 92:
        raise ValueError('统计范围须为连续 1–93 天')
    message, log = AiChatMessage, AiCallLog
    # Midstream usage (notably Anthropic message_start output_tokens) is only a
    # partial counter. Retain it, but never label or price it as complete usage.
    known = (log.tokens_prompt >= 0) & (log.tokens_completion >= 0) & (
        (log.usage_detail['complete'].as_boolean() == True) | (log.status == 'success'))  # noqa: E712
    status = case(((message.status == 'streaming') & ~live_condition(), 'failed'), else_=message.status)
    day = func.date(message.created_at)
    query = db.query(day.label('day'), AiChatSession.owner_user_id.label('owner_id'),
        message.model_snapshot.label('snapshot'), status.label('status'), func.count(message.id).label('requests'),
        func.sum(case((known, 1), else_=0)).label('token_requests'),
        func.sum(case((log.tokens_prompt >= 0, log.tokens_prompt), else_=0)).label('input_tokens'),
        func.sum(case((log.tokens_completion >= 0, log.tokens_completion), else_=0)).label('output_tokens'),
        func.sum(case((known, log.tokens_prompt), else_=0)).label('priced_input'),
        func.sum(case((known, log.tokens_completion), else_=0)).label('priced_output'),
        func.sum(case((log.duration_ms >= 0, 1), else_=0)).label('latency_count'),
        func.sum(case((log.duration_ms >= 0, log.duration_ms), else_=0)).label('duration_sum'),
        func.sum(case((message.first_token_ms >= 0, 1), else_=0)).label('first_token_count'),
        func.sum(case((message.first_token_ms >= 0, message.first_token_ms), else_=0)).label('first_token_sum'),
    ).join(AiChatSession, message.session_id == AiChatSession.id).outerjoin(log, message.ai_call_log_id == log.id).filter(
        message.role == 'assistant', message.created_at >= start, message.created_at < end + timedelta(days=1))
    if preset_id is not None:
        query = query.filter(message.model_snapshot['preset_id'].as_integer() == preset_id)
    if owner_id is not None:
        query = query.filter(AiChatSession.owner_user_id == owner_id)
    rows = query.group_by(day, AiChatSession.owner_user_id, message.model_snapshot, status).all()
    total, models, users, days = _bucket(), {}, {}, {}
    for row in rows:
        snapshot = row.snapshot or {}
        model_key = (snapshot.get('preset_id'), snapshot.get('model'), snapshot.get('label'))
        for target in (total, models.setdefault(model_key, _bucket()), users.setdefault(row.owner_id, _bucket()), days.setdefault(str(row.day), _bucket())):
            _add(target, row, snapshot.get('pricing'))
    names = dict(db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.id.in_(users)).all()) if users else {}
    return {'start': start.isoformat(), 'end': end.isoformat(), 'totals': _finish(total),
        'models': [dict(preset_id=key[0], model=key[1], label=key[2] or '历史未知模型', **_finish(value)) for key, value in models.items()],
        'users': [dict(user_id=key, name=names.get(key, f'用户 {key}'), **_finish(value)) for key, value in users.items()],
        'days': [dict(day=key, **_finish(days[key])) for key in sorted(days)]}
