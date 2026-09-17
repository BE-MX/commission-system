"""Announcement transactions reuse knowledge revisions, ACL and approval logic."""
import hashlib
import json
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.time import beijing_now, to_beijing_naive
from app.knowledge import access, service as knowledge
from app.knowledge.managed import announcement_scope
from app.knowledge.models import KnowledgeLibrary, KnowledgeLibraryMember, KnowledgeDocument, KnowledgeRevision, KnowledgeApprovalRequest
from app.announcement.models import AnnouncementConfig, Announcement, AnnouncementMeta, Publication, Delivery
from app.announcement import rendering


def require(identity, action):
    permissions = set(identity.get('permissions', []))
    allowed = {'announcement:admin', f'announcement:{action}'}
    if action == 'read':
        allowed.add('announcement:write')
    if not access.is_super_admin(identity) and not permissions.intersection(allowed):
        raise knowledge.ForbiddenError('缺少公告操作权限')


def config_for(db, identity, capability='read', lock=False):
    require(identity, 'admin' if capability == 'admin' else 'read' if capability == 'review' else capability)
    row = db.query(AnnouncementConfig).filter_by(id=1).first()
    if not row:
        raise knowledge.ConflictError('请管理员先初始化公告库')
    with announcement_scope(row.library_id):
        knowledge._library(db, identity, row.library_id, capability, for_update=lock)
    if lock:
        db.refresh(row, with_for_update=True)
    return row


def initialize(db, identity):
    require(identity, 'admin')
    row = db.get(AnnouncementConfig, 1)
    if row:
        return config_for(db, identity, 'admin')
    library = KnowledgeLibrary(name='公告库', category='company', managed_by='announcement', created_by=access.user_id(identity))
    db.add(library)
    db.flush()
    db.add(KnowledgeLibraryMember(library_id=library.id, user_id=access.user_id(identity), role='admin', created_by=access.user_id(identity)))
    row = AnnouncementConfig(id=1, library_id=library.id, executor_id=access.user_id(identity))
    db.add(row)
    knowledge._audit(db, identity, library.id, 'announcement_initialize', 'library', library.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return config_for(db, identity, 'admin')
    return row


def save_category(db, identity, *, title, category_id=None, active=True):
    config = config_for(db, identity, 'admin', lock=True)
    title = knowledge._clean_title(title)
    with announcement_scope(config.library_id):
        if category_id:
            row = knowledge._document(db, identity, category_id, 'admin')
            if row.library_id != config.library_id or row.node_type != 'folder' or row.parent_id:
                raise knowledge.ValidationError('请选择公告类别')
            row.title, row.status = title, 'active' if active else 'inactive'
        else:
            row = knowledge.create_folder(db, identity, config.library_id, title=title, commit=False)
            row.status = 'active'
    knowledge._audit(db, identity, config.library_id, 'announcement_category', 'folder', row.id)
    db.commit()
    return row


def categories(db, identity):
    config = config_for(db, identity)
    return [{'id': r.id, 'title': r.title, 'active': r.status != 'inactive'} for r in db.query(KnowledgeDocument).filter_by(
        library_id=config.library_id, node_type='folder', parent_id=None, deleted_at=None).order_by(KnowledgeDocument.sort_order, KnowledgeDocument.id)]


def _item(db, identity, document_id, capability='read', lock=False):
    config = config_for(db, identity, capability, lock)
    with announcement_scope(config.library_id):
        document = knowledge._document(db, identity, document_id, capability, lock_library=lock)
    item = db.get(Announcement, document_id)
    if not item:
        raise knowledge.NotFoundError('公告不存在')
    return config, document, item


def save_announcement(db, identity, *, title, content, category_id, document_id=None, base_revision_id=None,
                      important=False, effective_at=None, expires_at=None, change_note=''):
    config = config_for(db, identity, 'write', lock=True)
    effective_at, expires_at = to_beijing_naive(effective_at), to_beijing_naive(expires_at)
    if effective_at and expires_at and effective_at >= expires_at:
        raise knowledge.ValidationError('截止时间须晚于生效时间')
    with announcement_scope(config.library_id):
        category = knowledge._document(db, identity, category_id, 'read')
        if category.node_type != 'folder' or category.parent_id or category.status == 'inactive':
            raise knowledge.ValidationError('请选择启用中的公告类别')
        if document_id:
            _, document, item = _item(db, identity, document_id, 'write', True)
            if item.withdrawn_at or document.pending_approval_id:
                raise knowledge.ConflictError('撤回或待审核公告不能编辑')
            if document.draft_revision_id != base_revision_id:
                raise knowledge.ConflictError('公告已被其他人修改，请刷新后重试')
            revision = knowledge.save_document(db, identity, document_id, title=title, content=content, commit=False)
        else:
            document = knowledge.create_document(db, identity, config.library_id, title=title, content=content, parent_id=category.id, commit=False)
            item = Announcement(document_id=document.id)
            db.add(item)
            revision = db.get(KnowledgeRevision, document.draft_revision_id)
        # Published folder placement changes only when this revision is approved.
        if not document.published_revision_id:
            document.parent_id = category.id
        db.add(AnnouncementMeta(revision_id=revision.id, category_id=category.id, category_name=category.title,
                                important=important, effective_at=effective_at, expires_at=expires_at, change_note=change_note))
        db.commit()
        return item


def channel_ready(config):
    if not (config.delivery_enabled and config.channel_verified and config.conversation_id and config.robot_code):
        raise knowledge.ConflictError('请先配置并验证公告群图文通道，再启用自动推送')


def submit(db, identity, document_id):
    config, document, item = _item(db, identity, document_id, 'write', True)
    channel_ready(config)
    if item.withdrawn_at or document.draft_revision_id == document.published_revision_id:
        raise knowledge.ConflictError('没有可发布的新草稿')
    revision = db.get(KnowledgeRevision, document.draft_revision_id)
    if not revision or not revision.content_text.strip():
        raise knowledge.ValidationError('请填写公告正文；图片公告也需提供文字说明')
    with announcement_scope(config.library_id):
        result = knowledge.submit_document(db, identity, document_id, commit=False)
    db.commit()
    return result


def enqueue(db, config, parts, *, publication=None, weekly=None):
    source_key = f'publication:{publication.id}' if publication else f'weekly:{weekly.id}:{weekly.generation}'
    for index, part in enumerate(parts, 1):
        db.add(Delivery(source_key=source_key, publication_id=publication.id if publication else None,
                        weekly_id=weekly.id if weekly else None, sequence=index, target=config.conversation_id,
                        robot_code=config.robot_code, config_version=config.version,
                        payload={**part, 'sequence': index, 'total': len(parts), 'acl': acl_fingerprint(db, config.library_id)}))


def acl_fingerprint(db, library_id):
    members = db.query(KnowledgeLibraryMember.user_id, KnowledgeLibraryMember.role).filter_by(library_id=library_id).order_by(KnowledgeLibraryMember.user_id).all()
    return hashlib.sha256(json.dumps([list(m) for m in members]).encode()).hexdigest()


def review(db, identity, document_id, *, approve, remark=''):
    config, document, item = _item(db, identity, document_id, 'review', True)
    if not document.pending_approval_id or item.withdrawn_at:
        raise knowledge.ConflictError('公告不在待审核状态')
    with announcement_scope(config.library_id):
        if not approve:
            knowledge.reject_request(db, identity, document.pending_approval_id, remark=remark, commit=False)
        else:
            channel_ready(config)
            kind = 'update' if document.published_revision_id else 'publish'
            approval = knowledge.approve_request(db, identity, document.pending_approval_id, remark=remark, commit=False)
            revision = db.get(KnowledgeRevision, approval.revision_id)
            meta = db.get(AnnouncementMeta, revision.id)
            if not meta:
                raise knowledge.ConflictError('公告修订缺少类别和有效期信息')
            category = knowledge._document(db, identity, meta.category_id, 'read')
            if category.status == 'inactive':
                raise knowledge.ConflictError('公告类别已停用')
            item.published_at, item.published_by = beijing_now(), access.user_id(identity)
            document.parent_id = meta.category_id
            event = Publication(document_id=document.id, revision_id=revision.id, kind=kind, title=revision.title, actor_id=item.published_by)
            db.add(event)
            db.flush()
            _cancel_pending(db, document.id)
            enqueue(db, config, rendering.publication_parts(event, revision, meta), publication=event)
    db.commit()
    return {'id': document.id, 'status': document.status}


def _cancel_pending(db, document_id):
    ids = db.query(Publication.id).filter_by(document_id=document_id)
    for task in db.query(Delivery).filter(Delivery.publication_id.in_(ids), Delivery.status.in_(['queued', 'retry', 'failed'])):
        task.status, task.error = 'cancelled', '公告已更新或撤回'


def withdraw(db, identity, document_id, reason):
    config, document, item = _item(db, identity, document_id, 'admin', True)
    if item.withdrawn_at or not document.published_revision_id:
        raise knowledge.ConflictError('只有已发布公告可以撤回')
    reason = reason.strip()
    if not reason:
        raise knowledge.ValidationError('请填写撤回原因')
    revision = db.get(KnowledgeRevision, document.published_revision_id)
    event = Publication(document_id=document.id, revision_id=revision.id, title=revision.title, kind='withdraw', reason=reason, actor_id=access.user_id(identity))
    db.add(event)
    db.flush()
    knowledge._cancel_pending_approvals(db, identity, [document], beijing_now())
    item.withdrawn_at, item.withdrawal_reason = beijing_now(), reason
    document.published_revision_id = None  # shared search/MCP/image paths no longer expose it
    document.status = 'withdrawn'
    _cancel_pending(db, document_id)
    parts = rendering.text_parts(f'【公告撤回】{rendering.escape(revision.title)}\n{rendering.escape(reason)}\n[查看说明]({rendering.link(document_id)})')
    enqueue(db, config, [{'title': '公告撤回', **p} for p in parts], publication=event)
    knowledge._audit(db, identity, config.library_id, 'announcement_withdraw', 'document', document.id, revision.id)
    db.commit()


def delete_draft(db, identity, document_id):
    config, document, item = _item(db, identity, document_id, 'write', True)
    if item.published_at or document.pending_approval_id:
        raise knowledge.ConflictError('已发布或待审核公告不可删除，请使用撤回')
    with announcement_scope(config.library_id):
        return knowledge.delete_node(db, identity, document_id)


def detail(db, identity, document_id, *, edit=False):
    config, document, item = _item(db, identity, document_id)
    can_write = access.can(db, identity, config.library_id, 'write') and (access.is_super_admin(identity) or bool(set(identity.get('permissions', [])) & {'announcement:write', 'announcement:admin'}))
    can_review = access.can(db, identity, config.library_id, 'review') and (access.is_super_admin(identity) or bool(set(identity.get('permissions', [])) & {'knowledge:review', 'knowledge:admin', 'announcement:admin'}))
    if item.withdrawn_at:
        return {'id': document.id, 'title': '公告已撤回', 'status': 'withdrawn', 'withdrawal_reason': item.withdrawal_reason, 'can_edit': False}
    revision_id = document.published_revision_id
    if edit:
        if not can_write and not can_review:
            raise knowledge.NotFoundError('公告不存在')
        revision_id = (db.get(KnowledgeApprovalRequest, document.pending_approval_id).revision_id if document.pending_approval_id else document.draft_revision_id)
    if not revision_id:
        if can_write or can_review:
            revision_id = document.draft_revision_id
        else:
            raise knowledge.NotFoundError('公告不存在')
    revision, meta = db.get(KnowledgeRevision, revision_id), db.get(AnnouncementMeta, revision_id)
    return {'id': document.id, 'library_id': config.library_id, 'title': revision.title, 'content_json': revision.content_json,
            'revision_id': revision.id, 'version_no': revision.version_no, 'status': document.status if edit or not document.published_revision_id else 'published',
            'pending_approval_id': document.pending_approval_id if edit else None, 'can_edit': can_write and edit and not document.pending_approval_id,
            'can_review': can_review, 'published_at': item.published_at, 'published_by': item.published_by, 'pinned': item.pinned,
            'category_id': meta.category_id, 'category_name': meta.category_name, 'important': meta.important,
            'effective_at': meta.effective_at, 'expires_at': meta.expires_at, 'change_note': meta.change_note}


def list_announcements(db, identity, *, q='', category_id=None, status=None, page=1, page_size=20):
    config = config_for(db, identity)
    permissions = set(identity.get('permissions', []))
    manager = access.is_super_admin(identity) or (
        access.can(db, identity, config.library_id, 'write') and bool(permissions & {'announcement:write', 'announcement:admin'})
    ) or (
        access.can(db, identity, config.library_id, 'review') and bool(permissions & {'knowledge:review', 'knowledge:admin', 'announcement:admin'})
    )
    query = db.query(Announcement, KnowledgeDocument).join(KnowledgeDocument, KnowledgeDocument.id == Announcement.document_id).filter(
        KnowledgeDocument.library_id == config.library_id, KnowledgeDocument.deleted_at.is_(None))
    if not manager:
        query = query.filter(KnowledgeDocument.published_revision_id.is_not(None), Announcement.withdrawn_at.is_(None))
    # Search the displayed revision; draft titles must never leak to readers.
    revision_key = KnowledgeDocument.draft_revision_id if manager else KnowledgeDocument.published_revision_id
    query = query.join(KnowledgeRevision, KnowledgeRevision.id == revision_key).join(AnnouncementMeta, AnnouncementMeta.revision_id == revision_key)
    if q.strip():
        query = query.filter(or_(KnowledgeRevision.title.contains(q.strip()), KnowledgeRevision.content_text.contains(q.strip())))
    if category_id:
        query = query.filter(AnnouncementMeta.category_id == category_id)
    if status:
        if manager:
            query = query.filter(KnowledgeDocument.status == status)
        elif status != 'published':
            return {'items': [], 'total': 0}
    total = query.count()
    rows = query.order_by(Announcement.pinned.desc(), Announcement.published_at.desc(), KnowledgeDocument.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for item, document in rows:
        data = detail(db, identity, document.id, edit=manager)
        data.pop('content_json', None)
        data['deliveries'] = delivery_history(db, identity, document.id) if manager else []
        items.append(data)
    return {'items': items, 'total': total}


def delivery_history(db, identity, document_id):
    config_for(db, identity)
    ids = db.query(Publication.id).filter_by(document_id=document_id)
    return [{'id': r.id, 'sequence': r.sequence, 'status': r.status, 'error': r.error, 'attempts': r.attempts,
             'sent_at': r.sent_at, 'source_key': r.source_key} for r in db.query(Delivery).filter(Delivery.publication_id.in_(ids)).order_by(Delivery.id.desc()).limit(100)]


def preview(db, identity, document_id):
    data = detail(db, identity, document_id, edit=True)
    if data['status'] == 'withdrawn':
        raise knowledge.ConflictError('公告已撤回')
    revision = db.get(KnowledgeRevision, data['revision_id'])
    meta = db.get(AnnouncementMeta, revision.id)
    event = Publication(document_id=document_id, kind='publish')
    return rendering.publication_parts(event, revision, meta)


def list_deliveries(db, identity):
    config_for(db, identity, 'admin')
    return [{'id': r.id, 'source_key': r.source_key, 'sequence': r.sequence, 'status': r.status,
             'attempts': r.attempts, 'error': r.error, 'sent_at': r.sent_at}
            for r in db.query(Delivery).order_by(Delivery.id.desc()).limit(200)]
