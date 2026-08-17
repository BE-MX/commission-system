"""客户素材交付业务服务。"""

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.auth.utils import hash_password, verify_password
from app.customer_media.models import (
    CustomerMediaAsset, CustomerMediaBatch, CustomerMediaDownload,
    CustomerMediaReview, CustomerPortalAccount, CustomerPortalSession,
)
from app.customer_media.storage import StoredUpload, storage_for
from app.design.models import DesignDesigner, DesignScheduleRequest, DesignScheduleTask
from app.models.business import CustomerInfo
from app.models.customer import CustomerCommissionSnapshot


class CustomerMediaError(ValueError):
    pass


class CustomerMediaNotFound(CustomerMediaError):
    pass


class CustomerMediaForbidden(CustomerMediaError):
    pass


class CustomerMediaConflict(CustomerMediaError):
    pass


EDITABLE_STATUSES = {"draft", "changes_requested"}


def user_identity(db: Session, payload: dict) -> tuple[int, str, ArkUser]:
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise CustomerMediaForbidden("登录信息无效") from None
    user = db.get(ArkUser, user_id)
    if not user or not user.is_active or user.deleted_at:
        raise CustomerMediaForbidden("用户不存在或已停用")
    return user.id, user.real_name or user.username, user


def is_admin(payload: dict) -> bool:
    return "super_admin" in payload.get("roles", []) or "customer_media:admin" in payload.get("permissions", [])


def can_read_all_portals(payload: dict) -> bool:
    return is_admin(payload) or "customer_media_portal:read_all" in payload.get("permissions", [])


def _okki_account_id(db: Session, ark_user_id: int) -> str:
    external_ids = db.scalars(
        select(ArkUserExternalBinding.external_account_id).where(
            ArkUserExternalBinding.ark_user_id == ark_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        ).order_by(
            ArkUserExternalBinding.is_primary.desc(),
            ArkUserExternalBinding.id,
        )
    ).all()
    for external_id in external_ids:
        normalized = external_id.strip() if external_id else ""
        if normalized.isdigit():
            return normalized
    raise CustomerMediaConflict("请先在系统管理 -> 外部账号绑定中绑定 OKKI 账号")


def _sales_portal_account_statement(db: Session, payload: dict):
    user_id, _, _ = user_identity(db, payload)
    statement = select(CustomerPortalAccount)
    if can_read_all_portals(payload):
        return statement
    okki_user_id = _okki_account_id(db, user_id)
    assigned_customer_ids = select(CustomerCommissionSnapshot.customer_id).where(
        CustomerCommissionSnapshot.is_current.is_(True),
        CustomerCommissionSnapshot.salesperson_id == okki_user_id,
    )
    return statement.where(CustomerPortalAccount.customer_id.in_(assigned_customer_ids))


def _portal_status(account: CustomerPortalAccount, statuses: set[str]) -> str:
    if not account.is_active:
        return "disabled"
    for candidate in ("pending_review", "changes_requested", "published", "draft"):
        if candidate in statuses:
            return {
                "pending_review": "in_review",
                "changes_requested": "changes_requested",
                "published": "ready",
                "draft": "draft",
            }[candidate]
    return "empty"


def _summarize_sales_portal_accounts(
    db: Session, accounts: list[CustomerPortalAccount]
) -> list[dict]:
    customer_ids = [row.customer_id for row in accounts]
    if not customer_ids:
        return []

    batch_rows = db.execute(select(
        CustomerMediaBatch.customer_id,
        CustomerMediaBatch.status,
        CustomerMediaBatch.updated_at,
        CustomerMediaBatch.published_at,
    ).where(CustomerMediaBatch.customer_id.in_(customer_ids))).all()
    statuses: dict[str, set[str]] = {customer_id: set() for customer_id in customer_ids}
    last_updates: dict[str, datetime] = {}
    published_batches: dict[str, int] = {customer_id: 0 for customer_id in customer_ids}
    for customer_id, batch_status, updated_at, published_at in batch_rows:
        statuses.setdefault(customer_id, set()).add(batch_status)
        if batch_status == "published":
            published_batches[customer_id] = published_batches.get(customer_id, 0) + 1
            candidate = max(
                [value for value in (updated_at, published_at) if value is not None],
                default=None,
            )
            if candidate and (
                customer_id not in last_updates or candidate > last_updates[customer_id]
            ):
                last_updates[customer_id] = candidate

    asset_counts: dict[str, dict[str, int]] = {
        customer_id: {"image": 0, "video": 0} for customer_id in customer_ids
    }
    count_rows = db.execute(select(
        CustomerMediaBatch.customer_id,
        CustomerMediaAsset.media_type,
        func.count(CustomerMediaAsset.id),
    ).join(
        CustomerMediaAsset, CustomerMediaAsset.batch_id == CustomerMediaBatch.id,
    ).where(
        CustomerMediaBatch.customer_id.in_(customer_ids),
        CustomerMediaBatch.status == "published",
        CustomerMediaAsset.deleted_at.is_(None),
    ).group_by(
        CustomerMediaBatch.customer_id,
        CustomerMediaAsset.media_type,
    )).all()
    for customer_id, media_type, count in count_rows:
        asset_counts.setdefault(customer_id, {"image": 0, "video": 0})[media_type] = count

    summaries = []
    for account in accounts:
        counts = asset_counts.get(account.customer_id, {"image": 0, "video": 0})
        content_updated_at = last_updates.get(account.customer_id)
        summaries.append({
            "id": account.id,
            "customer_id": account.customer_id,
            "customer_name": account.customer_name_snapshot,
            "login_email": account.login_email,
            "is_active": account.is_active,
            "status": _portal_status(account, statuses.get(account.customer_id, set())),
            "asset_count": counts.get("image", 0) + counts.get("video", 0),
            "image_count": counts.get("image", 0),
            "video_count": counts.get("video", 0),
            "published_batch_count": published_batches.get(account.customer_id, 0),
            "last_login_at": account.last_login_at,
            "updated_at": content_updated_at or account.updated_at,
        })
    return summaries


def list_sales_portal_customers(db: Session, payload: dict, search: str = "") -> list[dict]:
    statement = _sales_portal_account_statement(db, payload)
    if search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(
            CustomerPortalAccount.customer_id.ilike(pattern),
            CustomerPortalAccount.customer_name_snapshot.ilike(pattern),
            CustomerPortalAccount.login_email.ilike(pattern),
        ))
    accounts = list(db.scalars(statement.order_by(
        CustomerPortalAccount.customer_name_snapshot,
        CustomerPortalAccount.id,
    )))
    return _summarize_sales_portal_accounts(db, accounts)


def sales_portal_customer_detail(db: Session, payload: dict, customer_id: str) -> dict:
    account = db.scalar(_sales_portal_account_statement(db, payload).where(
        CustomerPortalAccount.customer_id == customer_id,
    ))
    if not account:
        # 未授权与不存在统一 404，避免枚举其他业务员的客户门户。
        raise CustomerMediaNotFound("客户素材门户不存在")

    summaries = _summarize_sales_portal_accounts(db, [account])
    # 停用账号的真实客户体验是无法登录；业务预览不签发任何素材 URL。
    batches = portal_library(db, account) if account.is_active else []
    return {
        "customer": summaries[0],
        "batches": batches,
        "task_meta": portal_task_meta(db, batches),
    }


def list_customers(db: Session, payload: dict, search: str) -> list[dict]:
    from app.customer_image.service import CustomerScopeConflictError, list_available_customers
    user_id, _, _ = user_identity(db, payload)
    try:
        return list_available_customers(db, user_id, is_admin(payload), search, 20)
    except CustomerScopeConflictError as exc:
        raise CustomerMediaConflict(str(exc)) from exc


def validate_customer_access(db: Session, payload: dict, customer_id: str) -> dict:
    from app.customer_image.service import CustomerScopeConflictError, get_available_customer
    user_id, _, _ = user_identity(db, payload)
    try:
        match = get_available_customer(db, user_id, is_admin(payload), customer_id)
    except CustomerScopeConflictError as exc:
        raise CustomerMediaConflict(str(exc)) from exc
    if not match:
        raise CustomerMediaForbidden("所选客户不存在或不在当前用户负责范围内")
    return match


def _load_task(db: Session, task_id: int) -> tuple[DesignScheduleTask, DesignScheduleRequest]:
    task = db.scalar(select(DesignScheduleTask).where(DesignScheduleTask.id == task_id))
    if not task:
        raise CustomerMediaNotFound("设计任务不存在")
    request = db.scalar(select(DesignScheduleRequest).where(
        DesignScheduleRequest.id == task.request_id,
        DesignScheduleRequest.deleted_at.is_(None),
    ))
    if not request:
        raise CustomerMediaNotFound("设计预约不存在")
    return task, request


def _assert_writer(db: Session, payload: dict, task: DesignScheduleTask) -> None:
    if is_admin(payload):
        return
    _, _, user = user_identity(db, payload)
    designer = db.get(DesignDesigner, task.designer_id)
    if not designer or not designer.email or not user.email:
        raise CustomerMediaForbidden("设计师档案需绑定与方舟账号一致的邮箱后才能上传")
    if designer.email.strip().lower() != user.email.strip().lower():
        raise CustomerMediaForbidden("只能维护分配给自己的拍摄任务")


def _batch_query():
    return select(CustomerMediaBatch).options(
        selectinload(CustomerMediaBatch.assets),
        selectinload(CustomerMediaBatch.reviews),
    )


def get_or_create_batch(db: Session, task_id: int, payload: dict) -> CustomerMediaBatch:
    task, request = _load_task(db, task_id)
    _assert_writer(db, payload, task)
    if not request.customer_id:
        raise CustomerMediaConflict("历史预约未绑定客户ID，请管理员先补齐后再上传")
    existing = db.scalar(_batch_query().where(CustomerMediaBatch.task_id == task.id))
    if existing:
        return existing
    batch = CustomerMediaBatch(
        task_id=task.id,
        request_id=request.id,
        customer_id=request.customer_id,
        customer_name_snapshot=request.customer_name,
        applicant_user_id=request.salesperson_id,
        designer_user_id=None,
        status="draft",
    )
    db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(_batch_query().where(CustomerMediaBatch.task_id == task.id))
        if existing:
            return existing
        raise
    return db.scalar(_batch_query().where(CustomerMediaBatch.id == batch.id))


def get_batch(db: Session, batch_id: int) -> CustomerMediaBatch:
    batch = db.scalar(_batch_query().where(CustomerMediaBatch.id == batch_id))
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    return batch


async def upload_asset(db: Session, batch_id: int, payload: dict, upload) -> CustomerMediaBatch:
    user_id, _, _ = user_identity(db, payload)
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id))
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    task, _ = _load_task(db, batch.task_id)
    _assert_writer(db, payload, task)
    if batch.status not in EDITABLE_STATUSES:
        raise CustomerMediaConflict("当前状态不能上传素材")

    from app.core.config import get_settings
    settings = get_settings()
    max_batch_bytes = settings.CUSTOMER_MEDIA_MAX_BATCH_GB * 1024 * 1024 * 1024
    customer_id = batch.customer_id
    # 上传可能持续数分钟。先结束只读事务，文件落盘后再短暂锁批次做最终校验，
    # 避免上传期间占用数据库连接和行锁。
    db.rollback()

    stored: StoredUpload | None = None
    try:
        stored = await storage_for().save_upload(
            upload,
            customer_id=customer_id,
            batch_id=batch_id,
            max_bytes=settings.CUSTOMER_MEDIA_MAX_FILE_MB * 1024 * 1024,
        )
        batch = db.scalar(select(CustomerMediaBatch).where(
            CustomerMediaBatch.id == batch_id,
        ).with_for_update())
        if not batch:
            raise CustomerMediaNotFound("素材批次不存在")
        task, _ = _load_task(db, batch.task_id)
        _assert_writer(db, payload, task)
        if batch.status not in EDITABLE_STATUSES:
            raise CustomerMediaConflict("上传期间批次状态已变化，请刷新后重试")
        current_size = db.scalar(select(func.coalesce(func.sum(CustomerMediaAsset.file_size), 0)).where(
            CustomerMediaAsset.batch_id == batch.id,
            CustomerMediaAsset.deleted_at.is_(None),
        )) or 0
        if current_size + stored.file_size > max_batch_bytes:
            raise CustomerMediaConflict("该批次已达到容量上限")
        sort_order = db.scalar(select(func.count(CustomerMediaAsset.id)).where(
            CustomerMediaAsset.batch_id == batch.id,
            CustomerMediaAsset.deleted_at.is_(None),
        )) or 0
        asset = CustomerMediaAsset(
            batch_id=batch.id,
            file_name=stored.file_name,
            media_type=stored.media_type,
            content_type=stored.content_type,
            file_size=stored.file_size,
            sha256=stored.sha256,
            storage_provider=stored.provider,
            object_key=stored.object_key,
            width=stored.width,
            height=stored.height,
            sort_order=sort_order,
            uploaded_by=user_id,
        )
        db.add(asset)
        batch.updated_at = datetime.now()
        db.commit()
    except Exception:
        db.rollback()
        if stored:
            storage_for(stored.provider).delete(stored.object_key)
        raise
    return get_batch(db, batch.id)


def delete_asset(db: Session, batch_id: int, asset_id: int, payload: dict) -> CustomerMediaBatch:
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id).with_for_update())
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    task, _ = _load_task(db, batch.task_id)
    _assert_writer(db, payload, task)
    if batch.status not in EDITABLE_STATUSES:
        raise CustomerMediaConflict("当前状态不能删除素材")
    asset = db.scalar(select(CustomerMediaAsset).where(
        CustomerMediaAsset.id == asset_id,
        CustomerMediaAsset.batch_id == batch.id,
        CustomerMediaAsset.deleted_at.is_(None),
    ))
    if not asset:
        raise CustomerMediaNotFound("素材不存在")
    asset.deleted_at = datetime.now()
    batch.updated_at = datetime.now()
    db.commit()
    # 软删除提交成功后再删物理文件；失败会留下可清理孤儿，不会出现 DB 指向空文件。
    try:
        storage_for(asset.storage_provider).delete(asset.object_key)
    except Exception as exc:
        logger = __import__("logging").getLogger("commission")
        logger.warning("[customer-media] orphan after asset delete id=%s: %s", asset.id, exc)
        print(f"[customer-media] orphan after asset delete id={asset.id}: {exc}", flush=True)
    return get_batch(db, batch.id)


def submit_batch(db: Session, batch_id: int, payload: dict, lock_version: int) -> CustomerMediaBatch:
    user_id, _, _ = user_identity(db, payload)
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id).with_for_update())
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    task, request = _load_task(db, batch.task_id)
    _assert_writer(db, payload, task)
    if batch.lock_version != lock_version:
        raise CustomerMediaConflict("素材批次已被更新，请刷新后重试")
    if batch.status not in EDITABLE_STATUSES:
        raise CustomerMediaConflict("当前状态不能提交审核")
    asset_count = db.scalar(select(func.count(CustomerMediaAsset.id)).where(
        CustomerMediaAsset.batch_id == batch.id,
        CustomerMediaAsset.deleted_at.is_(None),
    )) or 0
    if asset_count < 1:
        raise CustomerMediaConflict("至少上传一个图片或视频后才能送审")
    if batch.status == "changes_requested":
        batch.revision += 1
    now = datetime.now()
    batch.status = "pending_review"
    batch.submitted_at = now
    batch.review_comment = None
    batch.lock_version += 1
    batch.updated_at = now
    task.status = "completed"
    task.actual_end_date = now.date()
    task.actual_end_period = "pm"
    task.updated_at = now
    request.status = "completed"
    request.actual_end_date = now.date()
    request.actual_end_period = "pm"
    request.updated_at = now
    db.add(CustomerMediaReview(
        batch_id=batch.id, revision=batch.revision, action="submit",
        actor_user_id=user_id,
    ))
    db.commit()
    return get_batch(db, batch.id)


def review_batch(db: Session, batch_id: int, payload: dict, action: str, comment: str | None, lock_version: int) -> CustomerMediaBatch:
    user_id, _, _ = user_identity(db, payload)
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id).with_for_update())
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    if not is_admin(payload) and batch.applicant_user_id != user_id:
        raise CustomerMediaForbidden("只有预约发起人可以审核该批次")
    if batch.lock_version != lock_version:
        raise CustomerMediaConflict("素材批次已被其他人处理，请刷新后重试")
    if batch.status != "pending_review":
        raise CustomerMediaConflict("该批次已不在待审核状态")
    now = datetime.now()
    if action == "request_changes":
        if not (comment or "").strip():
            raise CustomerMediaConflict("退回时必须填写修改原因")
        batch.status = "changes_requested"
        batch.review_comment = comment.strip()
    elif action == "approve":
        batch.status = "published"
        batch.review_comment = comment.strip() if comment else None
        batch.published_at = now
        batch.unpublished_at = None
    else:
        raise CustomerMediaConflict("不支持的审核动作")
    batch.reviewed_by = user_id
    batch.reviewed_at = now
    batch.updated_at = now
    batch.lock_version += 1
    db.add(CustomerMediaReview(
        batch_id=batch.id, revision=batch.revision, action=action,
        remark=batch.review_comment, actor_user_id=user_id,
    ))
    db.commit()
    return get_batch(db, batch.id)


def unpublish_batch(db: Session, batch_id: int, payload: dict, comment: str | None) -> CustomerMediaBatch:
    user_id, _, _ = user_identity(db, payload)
    if not is_admin(payload):
        raise CustomerMediaForbidden("只有管理员可以下架素材")
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id).with_for_update())
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    if batch.status != "published":
        raise CustomerMediaConflict("只有已发布批次可以下架")
    batch.status = "unpublished"
    batch.unpublished_at = datetime.now()
    batch.lock_version += 1
    db.add(CustomerMediaReview(
        batch_id=batch.id, revision=batch.revision, action="unpublish",
        remark=(comment or "").strip() or None, actor_user_id=user_id,
    ))
    db.commit()
    return get_batch(db, batch.id)


def list_reviews(db: Session, payload: dict, status: str | None = None) -> list[CustomerMediaBatch]:
    user_id, _, _ = user_identity(db, payload)
    statement = _batch_query().order_by(CustomerMediaBatch.submitted_at.desc())
    if not is_admin(payload):
        statement = statement.where(CustomerMediaBatch.applicant_user_id == user_id)
    statement = statement.where(CustomerMediaBatch.status == (status or "pending_review"))
    return list(db.scalars(statement).unique())


def create_portal_account(db: Session, payload: dict, customer_id: str, email: str, password: str) -> CustomerPortalAccount:
    user_id, _, _ = user_identity(db, payload)
    customer_name = db.scalar(select(CustomerInfo.company_name).where(CustomerInfo.company_id == customer_id))
    if not customer_name:
        raise CustomerMediaNotFound("客户不存在")
    account = CustomerPortalAccount(
        customer_id=customer_id,
        customer_name_snapshot=customer_name,
        login_email=email.strip().lower(),
        password_hash=hash_password(password),
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CustomerMediaConflict("该客户或登录邮箱已配置门户账号") from exc
    db.refresh(account)
    return account


def update_portal_account(db: Session, payload: dict, account_id: int, *, email=None, password=None, active=None) -> CustomerPortalAccount:
    user_id, _, _ = user_identity(db, payload)
    account = db.scalar(select(CustomerPortalAccount).where(CustomerPortalAccount.id == account_id).with_for_update())
    if not account:
        raise CustomerMediaNotFound("门户账号不存在")
    if email is not None:
        account.login_email = str(email).strip().lower()
    if password is not None:
        account.password_hash = hash_password(password)
    if active is not None:
        account.is_active = active
    account.session_version += 1
    account.updated_by = user_id
    account.updated_at = datetime.now()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CustomerMediaConflict("登录邮箱已被其他客户使用") from exc
    db.refresh(account)
    return account


def list_portal_accounts(db: Session, search: str = "") -> list[CustomerPortalAccount]:
    statement = select(CustomerPortalAccount).order_by(CustomerPortalAccount.customer_name_snapshot)
    if search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(
            CustomerPortalAccount.customer_id.ilike(pattern),
            CustomerPortalAccount.customer_name_snapshot.ilike(pattern),
            CustomerPortalAccount.login_email.ilike(pattern),
        ))
    return list(db.scalars(statement.limit(200)))


def authenticate_portal(db: Session, email: str, password: str, ip: str, user_agent: str, session_days: int) -> tuple[CustomerPortalAccount, str, datetime]:
    account = db.scalar(select(CustomerPortalAccount).where(
        func.lower(CustomerPortalAccount.login_email) == email.strip().lower(),
    ))
    # 对不存在/禁用账号也执行一次哈希校验，缩小账号枚举的时间差。
    dummy = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.oufnZrY8T9i9Zf2D5M0jM9l0JfY2v7W"
    if not account or not account.is_active:
        verify_password(password, dummy)
        raise CustomerMediaForbidden("邮箱或密码错误")
    if not verify_password(password, account.password_hash):
        raise CustomerMediaForbidden("邮箱或密码错误")
    token = secrets.token_urlsafe(48)
    expires = datetime.now() + timedelta(days=session_days)
    db.add(CustomerPortalSession(
        account_id=account.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        session_version=account.session_version,
        ip_address=ip[:45],
        user_agent=user_agent[:500],
        expires_at=expires,
    ))
    account.last_login_at = datetime.now()
    account.last_login_ip = ip[:45]
    db.commit()
    return account, token, expires


def portal_session(db: Session, token: str | None) -> CustomerPortalAccount:
    if not token:
        raise CustomerMediaForbidden("请先登录")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = db.scalar(select(CustomerPortalSession).options(
        selectinload(CustomerPortalSession.account),
    ).where(
        CustomerPortalSession.token_hash == token_hash,
        CustomerPortalSession.revoked_at.is_(None),
        CustomerPortalSession.expires_at > datetime.now(),
    ))
    if not session or not session.account.is_active or session.session_version != session.account.session_version:
        raise CustomerMediaForbidden("登录已失效")
    return session.account


def revoke_portal_session(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.scalar(select(CustomerPortalSession).where(
        CustomerPortalSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        CustomerPortalSession.revoked_at.is_(None),
    ))
    if row:
        row.revoked_at = datetime.now()
        db.commit()


def portal_library(db: Session, account: CustomerPortalAccount) -> list[CustomerMediaBatch]:
    return list(db.scalars(_batch_query().where(
        CustomerMediaBatch.customer_id == account.customer_id,
        CustomerMediaBatch.status == "published",
    ).order_by(CustomerMediaBatch.published_at.desc())).unique())


def portal_task_meta(
    db: Session, batches: list[CustomerMediaBatch]
) -> dict[int, dict]:
    task_ids = [row.task_id for row in batches]
    if not task_ids:
        return {}
    task_rows = db.execute(select(
        DesignScheduleTask.id,
        DesignScheduleTask.task_name,
        DesignScheduleTask.shoot_type,
    ).where(DesignScheduleTask.id.in_(task_ids))).all()
    return {
        task_id: {"task_name": task_name, "shoot_type": shoot_type}
        for task_id, task_name, shoot_type in task_rows
    }


def portal_asset(db: Session, account: CustomerPortalAccount, asset_id: int) -> CustomerMediaAsset:
    asset = db.scalar(select(CustomerMediaAsset).join(
        CustomerMediaBatch, CustomerMediaBatch.id == CustomerMediaAsset.batch_id,
    ).where(
        CustomerMediaAsset.id == asset_id,
        CustomerMediaAsset.deleted_at.is_(None),
        CustomerMediaBatch.customer_id == account.customer_id,
        CustomerMediaBatch.status == "published",
    ))
    if not asset:
        raise CustomerMediaNotFound("素材不存在")
    return asset


def sales_portal_asset(db: Session, asset_id: int) -> CustomerMediaAsset:
    """业务预览素材每次读取都重验门户启用与发布状态。"""
    asset = db.scalar(select(CustomerMediaAsset).join(
        CustomerMediaBatch, CustomerMediaBatch.id == CustomerMediaAsset.batch_id,
    ).join(
        CustomerPortalAccount,
        CustomerPortalAccount.customer_id == CustomerMediaBatch.customer_id,
    ).where(
        CustomerMediaAsset.id == asset_id,
        CustomerMediaAsset.deleted_at.is_(None),
        CustomerMediaBatch.status == "published",
        CustomerPortalAccount.is_active.is_(True),
    ))
    if not asset:
        raise CustomerMediaNotFound("素材不存在或已下架")
    return asset


def log_download(db: Session, asset_id: int, account_id: int, ip: str) -> None:
    db.add(CustomerMediaDownload(asset_id=asset_id, account_id=account_id, ip_address=ip[:45]))
    db.commit()


def _preview_signature(asset_id: int, expires: int) -> str:
    from app.core.config import get_settings
    settings = get_settings()
    secret = settings.CUSTOMER_MEDIA_SIGN_SECRET or settings.JWT_SECRET_KEY
    message = f"customer-media:{asset_id}:{expires}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def internal_preview_url(asset_id: int, ttl_seconds: int = 3600) -> str:
    from app.core.config import get_settings
    settings = get_settings()
    expires = int(time.time()) + ttl_seconds
    token = _preview_signature(asset_id, expires)
    origin = settings.CUSTOMER_MEDIA_PORTAL_ORIGIN.rstrip("/")
    return f"{origin}/api/customer-media/assets/{asset_id}/content?expires={expires}&token={token}"


def verify_internal_preview(asset_id: int, expires: int, token: str) -> bool:
    if expires < int(time.time()) or expires > int(time.time()) + 3900:
        return False
    expected = _preview_signature(asset_id, expires)
    return hmac.compare_digest(expected, token)


def _sales_portal_preview_signature(asset_id: int, expires: int) -> str:
    from app.core.config import get_settings
    settings = get_settings()
    secret = settings.CUSTOMER_MEDIA_SIGN_SECRET or settings.JWT_SECRET_KEY
    message = f"customer-media:sales-portal:{asset_id}:{expires}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def sales_portal_preview_url(asset_id: int, ttl_seconds: int = 3600) -> str:
    from app.core.config import get_settings
    settings = get_settings()
    expires = int(time.time()) + ttl_seconds
    token = _sales_portal_preview_signature(asset_id, expires)
    origin = settings.CUSTOMER_MEDIA_PORTAL_ORIGIN.rstrip("/")
    return (
        f"{origin}/api/customer-media/sales-portal/assets/{asset_id}/content"
        f"?expires={expires}&token={token}"
    )


def verify_sales_portal_preview(asset_id: int, expires: int, token: str) -> bool:
    if expires < int(time.time()) or expires > int(time.time()) + 3900:
        return False
    expected = _sales_portal_preview_signature(asset_id, expires)
    return hmac.compare_digest(expected, token)
