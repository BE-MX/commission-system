"""Administrative configuration and ACL. Credentials stay in DingTalk settings."""
from app.ai.models import AiPreset
from app.knowledge import service as knowledge
from app.knowledge.managed import announcement_scope
from app.announcement.models import AnnouncementConfig
from app.announcement import service


def get_config(db, identity):
    service.require(identity, 'read')
    row = db.get(AnnouncementConfig, 1)
    if not row:
        return {'initialized': False}
    service.config_for(db, identity)
    return {'initialized': True, **{key: getattr(row, key) for key in (
        'library_id', 'group_name', 'conversation_id', 'robot_code', 'delivery_enabled', 'channel_verified',
        'weekly_enabled', 'weekly_hour', 'weekly_minute', 'preset_name', 'executor_id', 'version')}}


def update_config(db, identity, data):
    row = service.config_for(db, identity, 'admin', True)
    if data.pop('version') != row.version:
        raise knowledge.ConflictError('设置已变更，请刷新后重试')
    changed_target = any(data[k] != getattr(row, k) for k in ('conversation_id', 'robot_code'))
    if changed_target:
        from app.knowledge.models import KnowledgeDocument
        from app.announcement.models import Delivery
        active = db.query(KnowledgeDocument.id).filter(KnowledgeDocument.library_id == row.library_id,
            KnowledgeDocument.published_revision_id.is_not(None)).first()
        outstanding = db.query(Delivery.id).filter(Delivery.status.notin_(['sent', 'cancelled'])).first()
        if active or outstanding:
            raise knowledge.ConflictError('请先撤回原群的已发布公告并处理完投递记录，再更换目标群')
        row.channel_verified = False
    if data['delivery_enabled'] and (not row.channel_verified or not data['conversation_id'] or not data['robot_code']):
        raise knowledge.ValidationError('请先保存目标群并完成图文测试，再启用自动推送')
    if data['weekly_enabled']:
        if not data['delivery_enabled']:
            raise knowledge.ValidationError('请先启用自动推送')
        preset = db.query(AiPreset).filter_by(preset_name=data['preset_name'], is_enabled=True, deleted_at=None).first()
        if not preset:
            raise knowledge.ValidationError('请选择已启用的 AI Preset')
    for key, value in data.items():
        setattr(row, key, value)
    from app.knowledge.ai_job_service import identity_for_user
    executor = identity_for_user(db, row.executor_id)
    service.config_for(db, executor)
    row.version += 1
    knowledge._audit(db, identity, row.library_id, 'announcement_config', 'library', row.library_id, detail={'version': row.version})
    db.commit()
    return get_config(db, identity)


def members(db, identity, values=None, query=None):
    config = service.config_for(db, identity, 'admin', lock=values is not None)
    with announcement_scope(config.library_id):
        if values is not None:
            return knowledge.replace_members(db, identity, config.library_id, values)
        if query is not None:
            return knowledge.search_member_candidates(db, identity, config.library_id, query)
        return knowledge.list_members(db, identity, config.library_id)


def pin(db, identity, document_id, pinned):
    config, document, row = service._item(db, identity, document_id, 'admin', True)
    row.pinned = pinned
    knowledge._audit(db, identity, config.library_id, 'announcement_pin', 'document', document.id, detail={'pinned': pinned})
    db.commit()
