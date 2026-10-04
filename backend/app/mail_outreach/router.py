"""邮件触达人类接口（业务员/管理员 JWT）。

只挂 require_permission 体系，不接受任何 agent/worker token；
worker 受限接口在后续阶段以独立子路由提供（双向隔离）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.customer.access_service import (
    CustomerAccessDenied,
    apply_customer_scope,
    require_customer_access,
)
from app.customer.models import CustomerAccount, CustomerContact, CustomerContactPoint
from app.core.config import get_settings
from app.mail_outreach import event_service, recipient_service, worker_service
from app.mail_outreach.worker_router import router as worker_router
from app.mail_outreach.worker_schemas import ClassifyRequest
from app.mail_outreach import (
    approval_service,
    generation_service,
    job_service,
    schedule_client,
)
from app.mail_outreach.context_service import build_outreach_snapshot
from app.mail_outreach.errors import conflict, not_found
from app.mail_outreach.generation_service import _iso_bj, serialize_message
from app.mail_outreach.models import (
    MailMailboxBinding,
    MailOutreachMessage,
    MailOutreachRevision,
    MailOutreachSendJob, MailEvent, MailEventCheckpoint,
)
from app.mail_outreach.schemas import (
    ApproveRequest,
    DraftCreateRequest,
    JobCancelRequest,
    MailboxCreateRequest,
    MailboxUpdateRequest,
    RejectRequest,
    RevisionCreateRequest,
    RevokeRequest,
    SchedulePreviewRequest,
    RecipientPrepareRequest,
)
from app.core.list_sort import apply_list_sort

router = APIRouter()
router.include_router(worker_router)

# 客户 ACL：动作权限与管理权限口径与 customer-hub 保持一致
_READ_PERMS = ("customer:read", "customer:read_all", "customer:admin")
_WRITE_PERMS = ("customer:write", "customer:admin")
_MANAGE_PERMS = ("customer:admin",)


def _access(db: Session, customer_id: int, user: dict, *, write: bool = False):
    """客户访问收口：拒绝时一律 404，不泄露客户是否存在。"""
    try:
        return require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions=_WRITE_PERMS if write else _READ_PERMS,
            manage_permissions=_MANAGE_PERMS,
            allow_public_pool=False,
        )
    except CustomerAccessDenied as exc:
        raise not_found() from exc


def _get_message(db: Session, message_id: int) -> MailOutreachMessage:
    message = db.query(MailOutreachMessage).filter(
        MailOutreachMessage.id == message_id,
    ).one_or_none()
    if message is None:
        raise not_found("草稿不存在")
    return message


def _current_revision(db: Session, message: MailOutreachMessage) -> MailOutreachRevision | None:
    if message.current_revision_id is None:
        return None
    return db.query(MailOutreachRevision).filter(
        MailOutreachRevision.id == message.current_revision_id,
    ).one_or_none()


def _serialize_mailbox(row: MailMailboxBinding) -> dict:
    """永不返回 secret_ref（凭据只存受控保管位置引用，不进任何响应）。"""
    return {
        "id": row.id,
        "provider": row.provider,
        "sender_email": row.sender_email,
        "display_name": row.display_name,
        "owner_user_id": row.owner_user_id,
        "worker_identity": row.worker_identity,
        "cli_workspace": row.cli_workspace,
        "auth_status": row.auth_status,
        "daily_quota": row.daily_quota,
        "quota_timezone": row.quota_timezone,
        "pause_reason": row.pause_reason,
        "status": row.status,
        "created_at": _iso_bj(row.created_at),
        "updated_at": _iso_bj(row.updated_at),
    }


@router.get("/context/{customer_id}")
def get_context(
    customer_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
):
    access = _access(db, customer_id, user)
    return ok(build_outreach_snapshot(db, access, user=user))


@router.post("/customers/{customer_id}/recipients")
def prepare_recipient(customer_id: int, payload: RecipientPrepareRequest,
                     db: Session = Depends(get_db), user=Depends(require_permission("mail_outreach:write"))):
    access = _access(db, customer_id, user, write=True)
    return ok(recipient_service.prepare_recipient(db, access, user, payload))


@router.post("/drafts")
def create_draft(
    payload: DraftCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    access = _access(db, payload.customer_id, user, write=True)
    return ok(generation_service.generate_draft(
        db, access, user,
        customer_id=payload.customer_id,
        contact_id=payload.contact_id,
        contact_point_id=payload.contact_point_id,
        relationship_goal=payload.relationship_goal,
        request_key=payload.request_key,
        internal_test=payload.internal_test,
    ))


@router.get("/drafts")
def list_drafts(
    customer_id: int | None = Query(None, gt=0),
    status: str | None = Query(None, max_length=16),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
    sort_field: str | None = None,
    sort_order: str | None = None,
):
    query = db.query(MailOutreachMessage).join(
        CustomerAccount, CustomerAccount.id == MailOutreachMessage.customer_id,
    )
    if customer_id is not None:
        _access(db, customer_id, user)
        query = query.filter(MailOutreachMessage.customer_id == customer_id)
    else:
        try:
            query = apply_customer_scope(
                query, user=user, read_permissions=_READ_PERMS, include_public_pool=False,
            )
        except CustomerAccessDenied as exc:
            raise not_found() from exc
    if status:
        query = query.filter(MailOutreachMessage.status == status)
    total = query.count()
    messages = apply_list_sort(
        query, sort_field, sort_order, {
            "status": MailOutreachMessage.status,
            "relationship_goal": MailOutreachMessage.relationship_goal,
            "updated_at": MailOutreachMessage.updated_at,
            "language_tag": select(MailOutreachRevision.language_tag).where(MailOutreachRevision.id == MailOutreachMessage.current_revision_id).scalar_subquery(),
            "to_email": select(CustomerContactPoint.normalized_value).where(CustomerContactPoint.id == MailOutreachMessage.contact_point_id).scalar_subquery(),
        },
        default=(MailOutreachMessage.id.desc(),),
        tie_breakers=(MailOutreachMessage.id.asc(),),
    ).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    revision_ids = [m.current_revision_id for m in messages if m.current_revision_id]
    revisions = {
        row.id: row for row in db.query(MailOutreachRevision).filter(
            MailOutreachRevision.id.in_(revision_ids),
        ).all()
    } if revision_ids else {}
    point_ids = {message.contact_point_id for message in messages if message.contact_point_id}
    points = {point.id: point.normalized_value for point in db.query(CustomerContactPoint).filter(CustomerContactPoint.id.in_(point_ids)).all()} if point_ids else {}
    items = []
    for message in messages:
        revision = revisions.get(message.current_revision_id)
        item = serialize_message(message, revision)
        item["language_tag"] = revision.language_tag if revision else None
        item["to_email"] = points.get(message.contact_point_id)
        items.append(item)
    return ok(page_result(items, total, page, page_size))


@router.get("/drafts/{message_id}")
def get_draft(
    message_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
):
    message = _get_message(db, message_id)
    _access(db, message.customer_id, user)
    result = serialize_message(message, _current_revision(db, message))
    customer = db.get(CustomerAccount, message.customer_id)
    contact = db.get(CustomerContact, message.contact_id)
    point = db.get(CustomerContactPoint, message.contact_point_id)
    access = _access(db, message.customer_id, user)
    visible = point is not None and point.data_classification in access.allowed_classifications()
    result.update(customer_name=customer.display_name if customer else None,
        contact_name=contact.display_name if contact else None,
        to_email=point.normalized_value if visible else None,
        verification_status=point.verification_status if visible else None,
        contactability_status=point.contactability_status if visible else None)
    return ok(result)


@router.post("/drafts/{message_id}/revisions")
def create_revision(
    message_id: int,
    payload: RevisionCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    message = _get_message(db, message_id)
    access = _access(db, message.customer_id, user, write=True)
    return ok(generation_service.create_human_revision(
        db, access, user, message_id, payload.model_dump(),
    ))


@router.post("/drafts/{message_id}/schedule-preview")
def schedule_preview(
    message_id: int,
    payload: SchedulePreviewRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    message = _get_message(db, message_id)
    _access(db, message.customer_id, user, write=True)
    revision = _current_revision(db, message)
    if revision is None:
        raise not_found("草稿当前版本缺失")
    customer = db.query(CustomerAccount).filter(
        CustomerAccount.id == message.customer_id,
    ).one_or_none()
    contact = db.query(CustomerContact).filter(
        CustomerContact.id == message.contact_id,
    ).one_or_none()
    sidecar_payload = {
        "state": payload.state,
        "country": payload.country
        or (contact.country_code if contact else None)
        or (customer.primary_country_code if customer else None),
        "timezone": payload.timezone or revision.recipient_timezone,
        "language": payload.language or revision.language_tag,
        "languageSource": revision.language_source,
        "languageBasis": revision.language_basis,
        "officeStart": payload.office_start
        or (revision.schedule_policy_json or {}).get("office_start"),
    }
    return ok(schedule_client.preview_schedule(sidecar_payload))


@router.post("/drafts/{message_id}/approve")
def approve_draft(
    message_id: int,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    message = _get_message(db, message_id)
    access = _access(db, message.customer_id, user, write=True)
    return ok(approval_service.approve(db, access, user, message_id, payload))


@router.post("/drafts/{message_id}/reject")
def reject_draft(
    message_id: int,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    message = _get_message(db, message_id)
    access = _access(db, message.customer_id, user, write=True)
    return ok(approval_service.reject(db, access, user, message_id, payload.reason))


@router.post("/drafts/{message_id}/revoke")
def revoke_draft(
    message_id: int,
    payload: RevokeRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    message = _get_message(db, message_id)
    access = _access(db, message.customer_id, user, write=True)
    return ok(approval_service.revoke(db, access, user, message_id, payload.reason))


@router.get("/jobs")
def list_jobs_route(
    status: str | None = Query(None, max_length=24),
    mailbox_binding_id: int | None = Query(None, gt=0),
    customer_id: int | None = Query(None, gt=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
    sort_field: str | None = None,
    sort_order: str | None = None,
):
    items, total = job_service.list_jobs(
        db,
        status=status,
        mailbox_binding_id=mailbox_binding_id,
        customer_id=customer_id,
        page=page,
        page_size=page_size,
        user=user,
        sort_field=sort_field,
        sort_order=sort_order,
    )
    return ok(page_result(items, total, page, page_size))


@router.post("/jobs/{job_id}/cancel")
def cancel_job_route(
    job_id: int,
    payload: JobCancelRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    job = db.get(MailOutreachSendJob, job_id)
    if job is None:
        raise not_found("任务不存在")
    message = _get_message(db, job.message_id)
    _access(db, message.customer_id, user, write=True)
    return ok(job_service.cancel_job(db, job_id, payload.note))


@router.get("/mailboxes")
def list_mailboxes(
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
):
    rows = _mailbox_query(db, user).order_by(MailMailboxBinding.id).all()
    return ok([_serialize_mailbox(row) for row in rows])


def _mailbox_query(db, user):
    from sqlalchemy import select, or_
    query = db.query(MailMailboxBinding)
    if "super_admin" not in user.get("roles", []) and "mail_outreach:admin" not in user.get("permissions", []):
        query = query.filter(or_(MailMailboxBinding.owner_user_id == int(user["sub"]), MailMailboxBinding.owner_user_id.is_(None)))
    return query


@router.get("/status")
def get_status(db: Session = Depends(get_db), user=Depends(require_permission("mail_outreach:read"))):
    items = []
    for row in _mailbox_query(db, user).all():
        checkpoint = db.get(MailEventCheckpoint, row.id)
        item = _serialize_mailbox(row)
        item.update(worker_ready=worker_service.mailbox_ready(db, row),
            worker_last_seen_at=(checkpoint.last_polled_at_utc.isoformat() + "Z") if checkpoint and checkpoint.last_polled_at_utc else None,
            watch_health=checkpoint.watch_health if checkpoint else "unknown")
        items.append(item)
    return ok({"send_enabled": get_settings().MAIL_OUTREACH_SEND_ENABLED,
        "allowed_recipients": sorted(worker_service.allowed_recipients()), "mailboxes": items,
        "worker_ready": any(x["worker_ready"] for x in items)})


@router.get("/events")
def list_events(customer_id: int | None = Query(None, gt=0), page: int = Query(1, ge=1),
                classification: str | None = Query(None, max_length=24),
                page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
                user=Depends(require_permission("mail_outreach:read")),
    sort_field: str | None = None,
    sort_order: str | None = None,
):
    query = db.query(MailEvent).join(CustomerAccount, CustomerAccount.id == MailEvent.matched_customer_id)
    query = apply_customer_scope(query, user=user, read_permissions=_READ_PERMS, include_public_pool=False)
    if classification:
        query = query.filter(MailEvent.classification == classification)
    if customer_id:
        _access(db, customer_id, user)
        query = query.filter(MailEvent.matched_customer_id == customer_id)
    total = query.count()
    rows = apply_list_sort(
        query, sort_field, sort_order, {
            "from_address": MailEvent.from_address,
            "subject": MailEvent.subject,
            "classification": MailEvent.classification,
            "matched_customer_id": MailEvent.matched_customer_id,
            "received_at_utc": MailEvent.received_at_utc,
            "processed_status": MailEvent.processed_status,
        },
        default=(MailEvent.id.desc(),),
        tie_breakers=(MailEvent.id.asc(),),
    ).offset((page - 1) * page_size).limit(page_size).all()
    return ok(page_result([event_service.serialize_event(row) for row in rows], total, page, page_size))


@router.post("/events/{event_id}/classify")
def classify_event(event_id: int, payload: ClassifyRequest, db: Session = Depends(get_db),
                   user=Depends(require_permission("mail_outreach:write"))):
    event = db.get(MailEvent, event_id)
    if event is None or event.matched_customer_id is None:
        raise not_found("收件事件不存在")
    _access(db, event.matched_customer_id, user, write=True)
    return ok(event_service.classify(db, event_id, user, payload))


@router.post("/mailboxes")
def create_mailbox(
    payload: MailboxCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:admin")),
):
    row = MailMailboxBinding(**payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("该通道下发件地址已存在绑定", error_code="mailbox_exists") from exc
    return ok(_serialize_mailbox(row))


@router.put("/mailboxes/{mailbox_id}")
def update_mailbox(
    mailbox_id: int,
    payload: MailboxUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:admin")),
):
    row = db.query(MailMailboxBinding).filter(
        MailMailboxBinding.id == mailbox_id,
    ).one_or_none()
    if row is None:
        raise not_found("邮箱绑定不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    return ok(_serialize_mailbox(row))
