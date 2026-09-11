"""邮件触达人类接口（业务员/管理员 JWT）。

只挂 require_permission 体系，不接受任何 agent/worker token；
worker 受限接口在后续阶段以独立子路由提供（双向隔离）。
"""

from fastapi import APIRouter, Depends, Query
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
from app.customer.models import CustomerAccount, CustomerContact
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
)

router = APIRouter()

# 客户 ACL：动作权限与管理权限口径与 customer-hub 保持一致
_READ_PERMS = ("customer:read", "customer:read_all", "customer:admin")
_WRITE_PERMS = ("customer:write", "customer:admin")
_MANAGE_PERMS = ("customer:write", "customer:admin")


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
    return ok(build_outreach_snapshot(db, access))


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
    ))


@router.get("/drafts")
def list_drafts(
    customer_id: int | None = Query(None, gt=0),
    status: str | None = Query(None, max_length=16),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
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
    messages = query.order_by(MailOutreachMessage.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    revision_ids = [m.current_revision_id for m in messages if m.current_revision_id]
    revisions = {
        row.id: row for row in db.query(MailOutreachRevision).filter(
            MailOutreachRevision.id.in_(revision_ids),
        ).all()
    } if revision_ids else {}
    items = [
        serialize_message(m, revisions.get(m.current_revision_id)) for m in messages
    ]
    return ok(page_result(items, total, page, page_size))


@router.get("/drafts/{message_id}")
def get_draft(
    message_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
):
    message = _get_message(db, message_id)
    _access(db, message.customer_id, user)
    return ok(serialize_message(message, _current_revision(db, message)))


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
):
    items, total = job_service.list_jobs(
        db,
        status=status,
        mailbox_binding_id=mailbox_binding_id,
        customer_id=customer_id,
        page=page,
        page_size=page_size,
    )
    return ok(page_result(items, total, page, page_size))


@router.post("/jobs/{job_id}/cancel")
def cancel_job_route(
    job_id: int,
    payload: JobCancelRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:write")),
):
    return ok(job_service.cancel_job(db, job_id, payload.note))


@router.get("/mailboxes")
def list_mailboxes(
    db: Session = Depends(get_db),
    user=Depends(require_permission("mail_outreach:read")),
):
    rows = db.query(MailMailboxBinding).order_by(MailMailboxBinding.id).all()
    return ok([_serialize_mailbox(row) for row in rows])


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
