"""客户素材交付业务服务。"""

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta
from app.core.time import beijing_now

from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.asset.models import TagDimension, TagValue
from app.auth.models import ArkUser, ArkUserExternalBinding
from app.auth.utils import hash_password, verify_password
from app.customer_media.models import (
    CustomerMediaAsset, CustomerMediaAssetTag, CustomerMediaBatch,
    CustomerMediaDirectory, CustomerMediaDownload, CustomerMediaReview,
    CustomerPortalAccount, CustomerPortalSession,
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


def sales_portal_customer_detail(
    db: Session, payload: dict, customer_id: str, tag_value_ids: list[int] | None = None,
) -> dict:
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
        "matching_asset_ids": matching_asset_ids(db, batches, tag_value_ids),
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


def _normalize_directory_name(name: str | None) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise CustomerMediaConflict("目录名称不能为空")
    if len(normalized) > 128:
        raise CustomerMediaConflict("目录名称不能超过 128 个字符")
    return normalized


def _find_directory(db: Session, customer_id: str, name: str) -> CustomerMediaDirectory | None:
    # 显式 lower() 匹配：不依赖 MySQL ci 排序规则，SQLite 测试库行为一致
    return db.scalar(select(CustomerMediaDirectory).where(
        CustomerMediaDirectory.customer_id == customer_id,
        func.lower(CustomerMediaDirectory.name) == name.lower(),
    ))


def find_or_create_directory(db: Session, batch: CustomerMediaBatch, name: str, user_id: int) -> CustomerMediaDirectory:
    """按客户+目录名幂等获取目录：同名（数据库 ci 排序规则下忽略大小写）直接复用，否则新建。"""
    normalized = _normalize_directory_name(name)
    existing = _find_directory(db, batch.customer_id, normalized)
    if existing:
        return existing
    directory = CustomerMediaDirectory(customer_id=batch.customer_id, name=normalized, created_by=user_id)
    db.add(directory)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_directory(db, batch.customer_id, normalized)
        if existing:
            return existing
        raise
    db.refresh(directory)
    return directory


def _load_batch_for_write(db: Session, batch_id: int, payload: dict) -> CustomerMediaBatch:
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id))
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    task, _ = _load_task(db, batch.task_id)
    _assert_writer(db, payload, task)
    return batch


def list_batch_directories(db: Session, batch_id: int, payload: dict) -> list[dict]:
    batch = _load_batch_for_write(db, batch_id, payload)
    return batch_directory_summary(db, batch)


def create_directory(db: Session, batch_id: int, payload: dict, name: str) -> dict:
    user_id, _, _ = user_identity(db, payload)
    batch = _load_batch_for_write(db, batch_id, payload)
    directory = find_or_create_directory(db, batch, name, user_id)
    return {"id": directory.id, "name": directory.name, "asset_count": 0}


def rename_directory(db: Session, batch_id: int, directory_id: int, payload: dict, name: str) -> dict:
    batch = _load_batch_for_write(db, batch_id, payload)
    directory = db.scalar(select(CustomerMediaDirectory).where(
        CustomerMediaDirectory.id == directory_id,
    ).with_for_update())
    if not directory or directory.customer_id != batch.customer_id:
        raise CustomerMediaNotFound("素材目录不存在")
    normalized = _normalize_directory_name(name)
    if normalized.lower() != directory.name.lower():
        clash = _find_directory(db, batch.customer_id, normalized)
        if clash and clash.id != directory.id:
            raise CustomerMediaConflict("同名目录已存在")
    if normalized != directory.name:
        directory.name = normalized
        directory.updated_at = beijing_now()
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise CustomerMediaConflict("同名目录已存在") from exc
    return {"id": directory.id, "name": directory.name}


def batch_directory_summary(db: Session, batch: CustomerMediaBatch) -> list[dict]:
    """客户级目录列表 + 当前批次内各目录未删素材数。"""
    directories = list(db.scalars(select(CustomerMediaDirectory).where(
        CustomerMediaDirectory.customer_id == batch.customer_id,
    ).order_by(CustomerMediaDirectory.name, CustomerMediaDirectory.id)))
    count_rows = db.execute(select(
        CustomerMediaAsset.directory_id, func.count(CustomerMediaAsset.id),
    ).where(
        CustomerMediaAsset.batch_id == batch.id,
        CustomerMediaAsset.deleted_at.is_(None),
        CustomerMediaAsset.directory_id.is_not(None),
    ).group_by(CustomerMediaAsset.directory_id)).all()
    counts = {directory_id: count for directory_id, count in count_rows}
    total_counts = dict(db.execute(select(
        CustomerMediaAsset.directory_id, func.count(CustomerMediaAsset.id),
    ).join(CustomerMediaDirectory, CustomerMediaDirectory.id == CustomerMediaAsset.directory_id).where(
        CustomerMediaDirectory.customer_id == batch.customer_id,
        CustomerMediaAsset.deleted_at.is_(None),
    ).group_by(CustomerMediaAsset.directory_id)).all())
    return [
        {"id": directory.id, "name": directory.name, "asset_count": counts.get(directory.id, 0),
         "total_asset_count": total_counts.get(directory.id, 0)}
        for directory in directories
    ]


def delete_directory(db: Session, batch_id: int, directory_id: int, payload: dict) -> CustomerMediaBatch:
    """删除客户共享目录；全部关联批次通过写权限/状态校验后才原子删除。"""
    try:
        current = _load_batch_for_write(db, batch_id, payload)
        directory = db.scalar(select(CustomerMediaDirectory).where(
            CustomerMediaDirectory.id == directory_id,
        ).with_for_update())
        if not directory or directory.customer_id != current.customer_id:
            raise CustomerMediaNotFound("素材目录不存在")
        # 上传最终入库也先锁目录，再锁批次，防止删除期间新增素材。
        # MySQL REPEATABLE READ 下普通 SELECT 可能保留等待目录锁前的快照。
        # 按目录→客户批次→素材顺序做当前读，兼容单素材删除的批次→素材顺序。
        batches = list(db.scalars(select(CustomerMediaBatch).where(
            CustomerMediaBatch.customer_id == current.customer_id,
        ).order_by(CustomerMediaBatch.id).with_for_update().execution_options(populate_existing=True)))
        assets = list(db.scalars(select(CustomerMediaAsset).where(
            CustomerMediaAsset.directory_id == directory_id,
        ).with_for_update().execution_options(populate_existing=True)))
        affected_ids = {asset.batch_id for asset in assets if asset.deleted_at is None} | {batch_id}
        batches = [batch for batch in batches if batch.id in affected_ids]
        for batch in batches:
            task, _ = _load_task(db, batch.task_id)
            _assert_writer(db, payload, task)
            if batch.status not in EDITABLE_STATUSES:
                raise CustomerMediaConflict("目录含审核中或已发布批次，请先退回或下架后再删除")
        files = [(asset.id, asset.storage_provider, asset.object_key) for asset in assets if asset.deleted_at is None]
        now = beijing_now()
        for asset in assets:
            if asset.deleted_at is None:
                asset.deleted_at = now
            asset.directory_id = None
        for batch in batches:
            batch.updated_at = now
        db.delete(directory)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for asset_id, provider, object_key in files:
        try:
            storage_for(provider).delete(object_key)
        except Exception as exc:
            logger = __import__("logging").getLogger("commission")
            logger.warning("[customer-media] orphan after directory delete asset=%s: %s", asset_id, exc)
            print(f"[customer-media] orphan after directory delete asset={asset_id}: {exc}", flush=True)
    return get_batch(db, batch_id)


async def upload_asset(
    db: Session, batch_id: int, payload: dict, upload,
    directory_id: int | None = None, directory_name: str | None = None,
    tags: list | None = None,
) -> CustomerMediaBatch:
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
        directory = None
        if directory_id is not None:
            directory = db.get(CustomerMediaDirectory, directory_id)
            if not directory or directory.customer_id != customer_id:
                raise CustomerMediaNotFound("素材目录不存在")
        elif directory_name and directory_name.strip():
            # 文件夹拖拽上传按顶层文件夹名归组：同名目录直接复用，否则自动新建。
            directory = find_or_create_directory(db, batch, directory_name, user_id)
        if directory is not None:
            directory = db.scalar(select(CustomerMediaDirectory).where(
                CustomerMediaDirectory.id == directory.id,
            ).with_for_update().execution_options(populate_existing=True))
            if directory is None:
                raise CustomerMediaNotFound("素材目录已删除，请刷新后重试")
        batch = db.scalar(select(CustomerMediaBatch).where(
            CustomerMediaBatch.id == batch_id,
        ).with_for_update().execution_options(populate_existing=True))
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
            directory_id=directory.id if directory else None,
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
        db.flush()
        if tags:
            # 客户标签与素材同事务写入：scope/单选校验失败整单回滚。
            _validate_customer_tag_items(db, tags)
            _insert_asset_tags(db, asset.id, tags)
        batch.updated_at = beijing_now()
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
    asset.deleted_at = beijing_now()
    batch.updated_at = beijing_now()
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
    now = beijing_now()
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


def _assert_batch_reviewer(db: Session, payload: dict, batch: CustomerMediaBatch, user_id: int) -> None:
    """审核人与素材标签编辑共用：预约发起人或 customer_media:admin 才能操作。"""
    if not is_admin(payload) and batch.applicant_user_id != user_id:
        raise CustomerMediaForbidden("只有预约发起人可以操作该批次")


def review_batch(db: Session, batch_id: int, payload: dict, action: str, comment: str | None, lock_version: int) -> CustomerMediaBatch:
    user_id, _, _ = user_identity(db, payload)
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id).with_for_update())
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    _assert_batch_reviewer(db, payload, batch, user_id)
    if batch.lock_version != lock_version:
        raise CustomerMediaConflict("素材批次已被其他人处理，请刷新后重试")
    if batch.status != "pending_review":
        raise CustomerMediaConflict("该批次已不在待审核状态")
    now = beijing_now()
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
    batch.unpublished_at = beijing_now()
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


# ── 客户标签 ────────────────────────────────────────────

CUSTOMER_TAG_SCOPE = "customer"


def list_customer_tag_dimensions(db: Session) -> list[dict]:
    """上传页/审核页可选的客户标签维度（可见的 customer scope）。"""
    from app.asset.tag_service import list_dimensions_cached
    return [d for d in list_dimensions_cached(db, CUSTOMER_TAG_SCOPE) if d.get("is_visible", 1)]


def validate_tags(db: Session, tag_names: list[str]):
    """文件夹名候选与客户标签库匹配 —— 薄封装素材库匹配核心，限定 customer scope。"""
    from app.asset.folder_upload_service import validate_folder_tags
    return validate_folder_tags(db, tag_names, scope=CUSTOMER_TAG_SCOPE)


def resolve_auto_create_tags(db: Session, payload: dict, auto_create_tags: dict[str, int]) -> dict:
    """幂等创建缺失的客户标签（确认动作在前端完成），返回带 created 标记的 tag_mapping。"""
    user_identity(db, payload)
    if not auto_create_tags:
        return {}
    from app.asset.folder_upload_service import _resolve_auto_create_tags
    from app.asset.tag_service import invalidate_dim_cache
    try:
        mapping, created = _resolve_auto_create_tags(db, {}, auto_create_tags, scope=CUSTOMER_TAG_SCOPE)
    except ValueError as exc:
        db.rollback()
        raise CustomerMediaError(str(exc)) from exc
    db.commit()
    if created:
        invalidate_dim_cache()
    created_keys = {(c["dimension_id"], c["tag_value_id"]) for c in created}
    return {
        name: {**entry, "created": (entry["dimension_id"], entry["tag_value_id"]) in created_keys}
        for name, entry in mapping.items()
    }


def create_customer_tag_value(
    db: Session, payload: dict, dimension_id: int, value: str,
    name_en: str | None = None, aliases: list[str] | None = None,
) -> dict:
    """审核页/上传页现场新建客户标签；同名（忽略大小写）直接复用。"""
    user_identity(db, payload)
    dim = db.get(TagDimension, dimension_id)
    if not dim or dim.tag_scope != CUSTOMER_TAG_SCOPE:
        raise CustomerMediaNotFound("客户标签维度不存在")
    if dim.is_managed:
        raise CustomerMediaError(f"维度[{dim.label}]由系统维护，不能新建标签")
    clean = (value or "").strip()
    if not clean:
        raise CustomerMediaError("标签名不能为空")
    existing = db.scalar(select(TagValue).where(
        TagValue.dimension_id == dimension_id,
        func.lower(TagValue.value) == clean.lower(),
        TagValue.is_active == 1,
    ))
    if existing:
        return {"id": existing.id, "value": existing.value, "dimension_id": dimension_id, "created": False}
    from app.asset.tag_service import ManagedDimensionError, create_dimension_value
    try:
        tv = create_dimension_value(db, dimension_id, clean, name_en=name_en, aliases=aliases)
    except ManagedDimensionError as exc:
        raise CustomerMediaError(str(exc)) from exc
    return {"id": tv.id, "value": tv.value, "dimension_id": dimension_id, "created": True}


def _tag_item_fields(item) -> tuple[int, list[int]]:
    """兼容 pydantic 模型与 dict 的 tags_json 项读取。"""
    if isinstance(item, dict):
        return item.get("dimension_id"), list(item.get("tag_value_ids") or [])
    return getattr(item, "dimension_id", None), list(getattr(item, "tag_value_ids", None) or [])


def _validate_customer_tag_items(db: Session, tags: list) -> None:
    """校验 tags_json：仅可见非托管的 customer scope 维度；单选维度 ≤1 值；值属于维度且启用。"""
    if not tags:
        return
    parsed = [_tag_item_fields(item) for item in tags]
    dim_ids = [dim_id for dim_id, _ in parsed]
    if len(set(dim_ids)) != len(dim_ids):
        raise CustomerMediaError("同一维度只能提交一次（标签按维度全量覆盖）")
    dims = {d.id: d for d in db.scalars(select(TagDimension).where(TagDimension.id.in_(dim_ids)))}
    value_ids: list[int] = []
    for dim_id, tv_ids in parsed:
        dim = dims.get(dim_id)
        if dim is None or dim.tag_scope != CUSTOMER_TAG_SCOPE or not dim.is_visible or dim.is_managed:
            raise CustomerMediaError("仅支持可见的客户标签维度")
        unique_ids = list(dict.fromkeys(tv_ids))
        if dim.is_single_select and len(unique_ids) > 1:
            raise CustomerMediaError(f"维度[{dim.label}]为单选，最多选择 1 个标签")
        value_ids.extend(unique_ids)
    if not value_ids:
        return
    values = {v.id: v for v in db.scalars(select(TagValue).where(TagValue.id.in_(value_ids)))}
    for dim_id, tv_ids in parsed:
        for tv_id in dict.fromkeys(tv_ids):
            value = values.get(tv_id)
            if value is None or value.dimension_id != dim_id or not value.is_active:
                raise CustomerMediaError("标签值不存在、已停用或不属于所选维度")


def _insert_asset_tags(db: Session, asset_id: int, tags: list) -> None:
    for item in tags:
        dim_id, tv_ids = _tag_item_fields(item)
        for tv_id in dict.fromkeys(tv_ids):
            db.add(CustomerMediaAssetTag(asset_id=asset_id, dimension_id=dim_id, tag_value_id=tv_id))


def update_asset_tags(db: Session, batch_id: int, asset_id: int, payload: dict, tags: list) -> CustomerMediaBatch:
    """按维度全量覆盖素材的客户标签（空数组=清该维度）。

    权限与审核一致（预约发起人或 admin）；标签是资产属性，不走批次状态机，写后即时生效。
    """
    user_id, _, _ = user_identity(db, payload)
    batch = db.scalar(select(CustomerMediaBatch).where(CustomerMediaBatch.id == batch_id).with_for_update())
    if not batch:
        raise CustomerMediaNotFound("素材批次不存在")
    _assert_batch_reviewer(db, payload, batch, user_id)
    asset = db.scalar(select(CustomerMediaAsset).where(
        CustomerMediaAsset.id == asset_id,
        CustomerMediaAsset.batch_id == batch.id,
        CustomerMediaAsset.deleted_at.is_(None),
    ))
    if not asset:
        raise CustomerMediaNotFound("素材不存在")
    _validate_customer_tag_items(db, tags)
    dim_ids = [_tag_item_fields(item)[0] for item in tags]
    if dim_ids:
        db.execute(delete(CustomerMediaAssetTag).where(
            CustomerMediaAssetTag.asset_id == asset.id,
            CustomerMediaAssetTag.dimension_id.in_(dim_ids),
        ))
        _insert_asset_tags(db, asset.id, tags)
        db.add(CustomerMediaReview(
            batch_id=batch.id, revision=batch.revision, action="update_tags",
            remark=f"更新素材[{asset.file_name}]客户标签", actor_user_id=user_id,
        ))
    db.commit()
    return get_batch(db, batch.id)


def asset_tags_map(db: Session, asset_ids: list[int]) -> dict[int, list[dict]]:
    """批量拼装素材的客户标签（customer scope），避免 N+1。

    返回 {asset_id: [{dimension_id, dimension_label, tag_value_id, value}]}，
    供审核列表/内部预览/客户门户三处复用。
    """
    result: dict[int, list[dict]] = {asset_id: [] for asset_id in asset_ids}
    if not asset_ids:
        return result
    rows = db.execute(select(
        CustomerMediaAssetTag.asset_id,
        CustomerMediaAssetTag.dimension_id,
        TagDimension.label,
        CustomerMediaAssetTag.tag_value_id,
        TagValue.value,
    ).join(
        TagDimension, TagDimension.id == CustomerMediaAssetTag.dimension_id,
    ).join(
        TagValue, TagValue.id == CustomerMediaAssetTag.tag_value_id,
    ).where(
        CustomerMediaAssetTag.asset_id.in_(asset_ids),
        TagDimension.tag_scope == CUSTOMER_TAG_SCOPE,
    ).order_by(
        CustomerMediaAssetTag.asset_id,
        TagDimension.sort_order, TagDimension.id,
        TagValue.sort_order, TagValue.id,
    )).all()
    for asset_id, dimension_id, label, tag_value_id, value in rows:
        result.setdefault(asset_id, []).append({
            "dimension_id": dimension_id,
            "dimension_label": label,
            "tag_value_id": tag_value_id,
            "value": value,
        })
    return result


def parse_tag_value_ids(raw: str | None) -> list[int] | None:
    """逗号分隔的 tag_value_ids 查询参数；空=不筛选，非法片段忽略。"""
    if not raw:
        return None
    ids = [int(chunk) for chunk in (part.strip() for part in raw.split(",")) if chunk.isdigit()]
    return ids or None


def matching_asset_ids(
    db: Session, batches: list[CustomerMediaBatch], tag_value_ids: list[int] | None,
) -> set[int] | None:
    """门户筛选：同维度 OR、跨维度 AND。返回 None 表示不筛选。"""
    if not tag_value_ids:
        return None
    values = list(db.scalars(select(TagValue).join(
        TagDimension, TagDimension.id == TagValue.dimension_id,
    ).where(
        TagValue.id.in_(tag_value_ids),
        TagDimension.tag_scope == CUSTOMER_TAG_SCOPE,
    )))
    by_dimension: dict[int, list[int]] = {}
    for value in values:
        by_dimension.setdefault(value.dimension_id, []).append(value.id)
    if not by_dimension:
        return None
    candidate_ids = [asset.id for batch in batches for asset in batch.assets if asset.deleted_at is None]
    if not candidate_ids:
        return set()
    matching: set[int] | None = None
    for dimension_id, ids in by_dimension.items():
        hit = set(db.scalars(select(CustomerMediaAssetTag.asset_id).where(
            CustomerMediaAssetTag.asset_id.in_(candidate_ids),
            CustomerMediaAssetTag.dimension_id == dimension_id,
            CustomerMediaAssetTag.tag_value_id.in_(ids),
        )))
        matching = hit if matching is None else (matching & hit)
    return matching or set()


def portal_used_tags(db: Session, account: CustomerPortalAccount) -> list[dict]:
    """该客户已发布素材实际用到的客户标签，按维度分组（含每个值的素材数）。"""
    rows = db.execute(select(
        TagDimension.id, TagDimension.label, TagDimension.sort_order,
        TagValue.id, TagValue.value, TagValue.sort_order,
        func.count(distinct(CustomerMediaAssetTag.asset_id)),
    ).select_from(CustomerMediaAssetTag).join(
        TagValue, TagValue.id == CustomerMediaAssetTag.tag_value_id,
    ).join(
        TagDimension, TagDimension.id == CustomerMediaAssetTag.dimension_id,
    ).join(
        CustomerMediaAsset, CustomerMediaAsset.id == CustomerMediaAssetTag.asset_id,
    ).join(
        CustomerMediaBatch, CustomerMediaBatch.id == CustomerMediaAsset.batch_id,
    ).where(
        CustomerMediaBatch.customer_id == account.customer_id,
        CustomerMediaBatch.status == "published",
        CustomerMediaAsset.deleted_at.is_(None),
        TagDimension.tag_scope == CUSTOMER_TAG_SCOPE,
    ).group_by(
        TagDimension.id, TagDimension.label, TagDimension.sort_order,
        TagValue.id, TagValue.value, TagValue.sort_order,
    ).order_by(
        TagDimension.sort_order, TagDimension.id, TagValue.sort_order, TagValue.id,
    )).all()
    dimensions: dict[int, dict] = {}
    for dim_id, label, _dim_sort, value_id, value, _value_sort, count in rows:
        entry = dimensions.setdefault(dim_id, {"dimension_id": dim_id, "label": label, "values": []})
        entry["values"].append({"id": value_id, "value": value, "count": count})
    return list(dimensions.values())


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
    account.updated_at = beijing_now()
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
    expires = beijing_now() + timedelta(days=session_days)
    db.add(CustomerPortalSession(
        account_id=account.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        session_version=account.session_version,
        ip_address=ip[:45],
        user_agent=user_agent[:500],
        expires_at=expires,
    ))
    account.last_login_at = beijing_now()
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
        CustomerPortalSession.expires_at > beijing_now(),
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
        row.revoked_at = beijing_now()
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
    expires = int(time.time()) + ttl_seconds
    token = _preview_signature(asset_id, expires)
    return f"/api/customer-media/assets/{asset_id}/content?expires={expires}&token={token}"


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
