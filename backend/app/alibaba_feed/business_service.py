"""Current-authority gates for manual-only v1 records; never infer identity."""
import logging
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.auth.models import ArkUser, ArkRole, ArkUserRole, ArkPermission, ArkRolePermission, ArkUserExternalBinding
from app.client_desk import private_scope
from app.core.time import beijing_now
from .canonical import digest
from .errors import FeedError
from .models import AlibabaFeedSource, AlibabaFeedItem, AlibabaFeedLink
from .pilot_service import active_pilot

logger = logging.getLogger(__name__)


def require_actor(db, user, action="read"):
    pilot = active_pilot(db)
    if pilot is None:
        raise HTTPException(503, "阿里业务资料尚未启用")
    uid = private_scope.user_id(user)
    if uid != pilot.user_id:
        raise HTTPException(403, "当前账号未加入 TM 资料试点")
    active = db.query(ArkUser.id).filter(ArkUser.id == uid, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)).with_for_update().first()
    roles = {r[0] for r in db.query(ArkRole.name).join(ArkUserRole, ArkUserRole.role_id == ArkRole.id).filter(ArkUserRole.user_id == uid).with_for_update().all()}
    permissions = {r[0] for r in db.query(ArkPermission.code).join(ArkRolePermission, ArkRolePermission.permission_id == ArkPermission.id).join(ArkUserRole, ArkUserRole.role_id == ArkRolePermission.role_id).filter(ArkUserRole.user_id == uid).with_for_update().all()}
    if active is None or ("super_admin" not in roles and f"client_desk:{action}" not in permissions):
        raise HTTPException(403, "当前账号无资料权限")
    return uid, pilot.source_id


def _missing():
    raise HTTPException(404, "资料不存在或已失效")


def _owner_evidence(db, source, item, uid):
    external_id = item.snapshot.get("assignee_external_user_id")
    if external_id:
        candidates = db.query(ArkUserExternalBinding).filter_by(provider="alibaba_icbu", external_account_id=external_id,
            binding_status="active", deleted_at=None).populate_existing().with_for_update().all()
        # Existing binding columns use legacy case-insensitive collation. Never
        # allow SQL comparison to turn a similar account ID into authorization.
        bindings = [row for row in candidates if row.provider == "alibaba_icbu" and row.external_account_id == external_id]
        if len(bindings) != 1 or bindings[0].ark_user_id != uid:
            _missing()
        row = bindings[0]
        return {"kind": "external_binding", "id": row.id, "external_account_id": external_id,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    if (source.owner_aliases or {}).get(item.snapshot.get("assignee_name")) != uid:
        _missing()
    return {"kind": "source_alias", "mapping_version": source.mapping_version}


def _source_item(db, uid, source_id, item_id):
    # Lock order follows worker source -> item. Current reads avoid ORM and MySQL
    # repeatable-read snapshots after a previous authorization lookup.
    identity = db.query(AlibabaFeedItem.source_account_uid).filter_by(id=item_id).first()
    if identity is None:
        _missing()
    source = db.query(AlibabaFeedSource).filter_by(id=source_id, source_account_uid=identity[0]).populate_existing().with_for_update().first()
    if source is None:
        _missing()
    item = db.query(AlibabaFeedItem).filter_by(id=item_id).populate_existing().with_for_update().first()
    if (item is None or source.consent_state != "authorized" or not source.crm_shared
            or item.collection_generation != source.collection_generation or not item.is_current):
        _missing()
    _owner_evidence(db, source, item, uid)
    if source.legacy_identity_blocked and (item.schema_version == "ark_alibaba_feed_v1" or not item.conversation_id or any(not m.get("message_id") for m in item.snapshot.get("messages", []))):
        from .errors import FeedError
        raise FeedError(404, "LEGACY_IDENTITY_UNRESOLVED")
    return source, item


def _link(db, uid, item):
    return db.query(AlibabaFeedLink).filter_by(user_id=uid, source_account_uid=item.source_account_uid,
        collection_generation=item.collection_generation, record_type=item.record_type,
        inquiry_id=item.inquiry_id, deleted_at=None).populate_existing().with_for_update().first()


def _access(db, user, uid, source_id, item_id, *, company_id=None, ai=False, allow_redacted=False):
    source, item = _source_item(db, uid, source_id, item_id)
    link = _link(db, uid, item)
    visibility = "visible"
    if link:
        private_scope.assert_company_access(db, user, link.company_id)
        if link.mapping_version != source.mapping_version:
            visibility = "mapping_changed"
            link = None
    else:
        prior = db.query(AlibabaFeedLink).filter_by(user_id=uid, source_account_uid=item.source_account_uid,
            collection_generation=item.collection_generation, record_type=item.record_type, inquiry_id=item.inquiry_id).filter(
            AlibabaFeedLink.deleted_at.is_not(None)).order_by(AlibabaFeedLink.id.desc()).populate_existing().with_for_update().first()
        if prior:
            # Revocation is not a route back into the never-linked owner grant.
            # Even a redacted repair row requires the old customer's live scope.
            private_scope.assert_company_access(db, user, prior.company_id)
            visibility = "link_revoked"
    if visibility != "visible" and not allow_redacted:
        _missing()
    if company_id is not None and (link is None or str(link.company_id) != str(company_id)):
        _missing()
    if ai and (not source.ai_egress_allowed or not source.private_feed_enabled or link is None
            or item.window_result not in ("in_window", "uncertain")
            or set(item.issues or []) - {"WINDOW_PRECISION_INSUFFICIENT"}
            or item.snapshot.get("detail_scraped") is not True or item.snapshot.get("scrape_status") != "success"):
        _missing()
    return source, item, link, visibility


def _link_payload(link):
    return {"id": link.id, "company_id": str(link.company_id), "version": link.version, "mapping_version": link.mapping_version}


def _messages(db, item):
    from .normalization import safe_messages
    messages = safe_messages(db, item)
    return [{"key": f"AF-{item.id}-{message.get('_original_position', pos - 1) + 1}", "event_key": f"alibaba_feed:{item.id}:{message.get('_original_position', pos - 1) + 1}",
             "source": "alibaba_feed", "source_account_uid": item.source_account_uid, "item_id": item.id,
             "text": str(message.get("text") or ""), "at": str(message.get("at") or ""), "dir": str(message.get("dir") or "unknown")}
            for pos, message in enumerate(messages, 1)]


def _record(db, source, item, link, visibility="visible", *, detail=False):
    if visibility != "visible":
        return {"id": item.id, "source_account_uid": source.source_account_uid, "source_name": source.name,
                "record_type": item.record_type, "inquiry_id": item.inquiry_id, "schema_version": item.schema_version,
                "buyer": {"name": "资料待重新确认"}, "assignee_name": None, "reply_status": None,
                "observed_at": item.observed_at, "is_current": item.is_current, "window_result": None,
                "issues": [], "mapping_version": source.mapping_version, "link": None, "ai_eligible": False,
                "visibility_state": visibility, "rule_gates": {}}
    from .eligibility import rule_eligibility
    row = {"visibility_state": "visible", "schema_version": item.schema_version,
           "rule_gates": rule_eligibility(db, item, source, user_id=link.user_id if link else None),
           "id": item.id, "source_account_uid": source.source_account_uid, "source_name": source.name,
           "record_type": item.record_type, "inquiry_id": item.inquiry_id, "buyer": item.snapshot.get("buyer") or {},
           "assignee_name": item.snapshot.get("assignee_name"), "reply_status": item.snapshot.get("reply_status"),
           "observed_at": item.observed_at, "is_current": item.is_current, "window_result": item.window_result,
           "issues": item.issues or [], "mapping_version": source.mapping_version, "link": _link_payload(link) if link else None,
           "ai_eligible": bool(link and source.ai_egress_allowed and source.private_feed_enabled
                and item.window_result in ("in_window", "uncertain") and not (set(item.issues or []) - {"WINDOW_PRECISION_INSUFFICIENT"})
                and item.snapshot.get("detail_scraped") is True and item.snapshot.get("scrape_status") == "success")}
    if detail:
        safe = _messages(db, item)
        snapshot = {**item.snapshot, "messages": safe}
        row.update(snapshot=snapshot, messages=safe, coverage_gaps=["历史快照，不能推断全量沟通状态"] + (["商机日期精度不足，窗口归属不确定"] if item.window_result == "uncertain" else []))
    return row


def list_records(db, user, *, page=1, page_size=20, linked="all", keyword="", company_id=None):
    uid, source_id = require_actor(db, user)
    if company_id is not None:
        private_scope.assert_company_access(db, user, company_id)
    source_uid = db.query(AlibabaFeedSource.source_account_uid).filter_by(id=source_id).scalar_subquery()
    candidates = (db.query(AlibabaFeedItem.id).filter_by(is_current=True)
                  .filter(AlibabaFeedItem.source_account_uid == source_uid)
                  .order_by(AlibabaFeedItem.observed_at.desc(), AlibabaFeedItem.id.desc()).all())
    rows = []
    for (item_id,) in candidates:
        try:
            source, item, link, visibility = _access(db, user, uid, source_id, item_id, company_id=company_id, allow_redacted=True)
        except (HTTPException, FeedError) as exc:
            if exc.status_code == 404:
                continue
            raise
        if (linked == "linked" and link is None) or (linked == "unlinked" and link is not None):
            continue
        row = _record(db, source, item, link, visibility)
        if keyword and keyword.casefold() not in " ".join(str(row.get(k) or "") for k in ("buyer", "inquiry_id", "assignee_name", "source_name")).casefold():
            continue
        rows.append(row)
    return {"items": rows[(page-1)*page_size:page*page_size], "total": len(rows), "page": page, "page_size": page_size}


def get_record(db, user, item_id):
    uid, source_id = require_actor(db, user)
    return _record(db, *_access(db, user, uid, source_id, item_id), detail=True)


def list_customers(db, user, keyword="", page=1, page_size=20):
    require_actor(db, user)
    rows = [row for row in private_scope.list_private_companies(db, user)
            if not keyword or keyword.casefold() in (str(row["name"]) + str(row["company_id"])).casefold()]
    return {"items": rows[(page-1)*page_size:page*page_size], "total": len(rows), "page": page, "page_size": page_size}


def _commit(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Alibaba manual link commit failed")
        print("[alibaba_feed] manual link commit failed", flush=True)
        raise


def create_link(db, user, request):
    uid, source_id = require_actor(db, user, "write")
    source, item = _source_item(db, uid, source_id, request.item_id)
    private_scope.assert_company_access(db, user, request.company_id)
    if source.mapping_version != request.expected_mapping_version:
        raise HTTPException(409, "负责人映射已变化，请刷新后重试")
    request_hash = digest(request.model_dump(exclude={"client_request_id"}))
    prior = db.query(AlibabaFeedLink).filter_by(user_id=uid, client_request_id=request.client_request_id).populate_existing().with_for_update().first()
    if prior:
        if prior.request_hash != request_hash or prior.deleted_at is not None:
            raise HTTPException(409, "关联请求已使用或已撤销")
        return {**_link_payload(prior), "replayed": True}
    existing = _link(db, uid, item)
    if existing:
        if existing.mapping_version == source.mapping_version:
            raise HTTPException(409, "记录已关联，请先撤销原关联")
        # A newly reviewed mapping must be explicitly confirmed in a new link.
        existing.deleted_at = beijing_now()
        existing.version += 1
        existing.updated_by = uid
        db.flush()
    link = AlibabaFeedLink(user_id=uid, source_account_uid=source.source_account_uid,
        collection_generation=source.collection_generation, record_type=item.record_type,
        inquiry_id=item.inquiry_id, item_id=item.id, company_id=request.company_id,
        mapping_version=source.mapping_version, client_request_id=request.client_request_id,
        request_hash=request_hash, created_by=uid, updated_by=uid)
    db.add(link)
    try:
        _commit(db)
    except IntegrityError as exc:
        raise HTTPException(409, "关联已更新，请刷新后重试") from exc
    db.refresh(link)
    return {**_link_payload(link), "replayed": False}


def delete_link(db, user, link_id, expected_version):
    uid, source_id = require_actor(db, user, "write")
    identity = db.query(AlibabaFeedLink.source_account_uid).filter_by(id=link_id, user_id=uid).first()
    if identity is None:
        _missing()
    # Same source-before-link lock order as creation.
    if db.query(AlibabaFeedSource.id).filter_by(id=source_id, source_account_uid=identity[0]).with_for_update().first() is None:
        _missing()
    link = db.query(AlibabaFeedLink).filter_by(id=link_id, user_id=uid).populate_existing().with_for_update().first()
    private_scope.assert_company_access(db, user, link.company_id)
    if link.version != expected_version:
        raise HTTPException(409, "关联已更新，请刷新后重试")
    if link.deleted_at is None:
        link.deleted_at = beijing_now()
        link.updated_by = uid
        link.version += 1
        _commit(db)
    return {"id": link.id, "deleted": True, "version": link.version}


def select_for_analysis(db, user, company_id, item_ids):
    uid, source_id = require_actor(db, user)
    if not item_ids or len(item_ids) > 50 or len(set(item_ids)) != len(item_ids):
        raise HTTPException(422, "请选择不重复的阿里资料")
    private_scope.assert_company_access(db, user, company_id)
    refs, messages, dependencies = {}, [], []
    seen_message_identities = set()
    gaps = {"本次仅供显式人工分析，自动经营保持关闭"}
    for item_id in sorted(item_ids):
        source, item, link, _ = _access(db, user, uid, source_id, item_id, company_id=company_id, ai=True)
        if item.schema_version != "ark_alibaba_feed_v1.1" or not item.conversation_id:
            gaps.add("v1历史快照：没有稳定消息身份，不保证跨记录去重或同分钟顺序")
        if (item.coverage or {}).get("selection", "created_window") == "created_window":
            gaps.add("创建窗不覆盖旧商机的新活动，不能推断全量沟通状态")
        selected = _messages(db, item)
        # v1 refs are snapshot positions, never stable message identities. Only
        # v1.1's source/generation/conversation/message tuple can deduplicate
        # the same conversation observed under both inquiry and TM records.
        stable_ids = {}
        if item.schema_version == "ark_alibaba_feed_v1.1" and item.conversation_id:
            stable_ids = {
                f"AF-{item.id}-{position + 1}": (item.source_account_uid, item.collection_generation,
                    item.conversation_id, message["message_id"])
                for position, message in enumerate(item.snapshot.get("messages") or [])
                if message.get("message_id")
            }
        for message in selected:
            identity = stable_ids.get(message["key"])
            if identity is not None:
                if identity in seen_message_identities:
                    continue
                seen_message_identities.add(identity)
            messages.append(message)
            refs[message["key"]] = message
        # Preserve full per-item evidence dependencies even when its body was
        # already selected through another record; either grant can invalidate it.
        dependencies.append({"item_id": item.id, "source_account_uid": source.source_account_uid,
            "collection_generation": source.collection_generation, "source_version": source.version,
            "consent_version": source.consent_version, "mapping_version": source.mapping_version,
            "snapshot_hash": item.snapshot_hash, "owner_evidence": _owner_evidence(db, source, item, uid), "messages_hash": digest(selected), "capability_version": source.capability_version, "link_id": link.id, "link_version": link.version,
            "company_id": str(company_id), "user_id": uid})
        if item.window_result == "uncertain":
            gaps.add("商机日期精度不足，窗口归属不确定")
    return {"refs": refs, "messages": messages, "dependencies": {"policy": "manual_only_v1", "items": dependencies}, "coverage_gaps": sorted(gaps)}


def dependencies_valid(db, user, company_id, dependencies):
    if not isinstance(dependencies, dict) or dependencies.get("policy") != "manual_only_v1":
        return False
    try:
        items = dependencies.get("items") or []
        current = select_for_analysis(db, user, company_id, [item["item_id"] for item in items])
        return current["dependencies"] == dependencies
    except (HTTPException, FeedError, KeyError, TypeError, ValueError):
        return False
