"""跟进的可见与可写范围、客户搜索、快速建潜在客户（规格 3.6 / 第六节）。

current_user 是 JWT claims dict（sub/roles/permissions），和平台其他域一致。
"""
import logging
import re

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.domestic.models import DomesticCustomer, DomesticCustomerCommission
from app.domestic_followup.constants import PROSPECT_LIFECYCLE
from app.domestic_followup.models import DomesticCustomerAlias, DomesticFollowup, DomesticFollowupTask

SEARCH_LIMIT = 20
logger = logging.getLogger("commission")


def uid(current_user: dict) -> int:
    return int(current_user["sub"])


def can_read_all(current_user: dict) -> bool:
    if "super_admin" in (current_user.get("roles") or []):
        return True
    return "domestic_followup:read_all" in (current_user.get("permissions") or [])


def holder_ids(code: str):
    """持有权限 code 的在职用户 ID 子查询；super_admin 角色视同持有（与 require_permission 同口径）。

    查的是库里的当前授权，不是 JWT：选人、配置接收人时要看对方此刻有没有权限。
    """
    granted = (select(ArkUserRole.user_id)
               .join(ArkRolePermission, ArkRolePermission.role_id == ArkUserRole.role_id)
               .join(ArkPermission, ArkPermission.id == ArkRolePermission.permission_id)
               .where(ArkPermission.code == code))
    admins = (select(ArkUserRole.user_id)
              .join(ArkRole, ArkRole.id == ArkUserRole.role_id)
              .where(ArkRole.name == "super_admin"))
    return (select(ArkUser.id)
            .where(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
                   ArkUser.id.in_(granted.union(admins))))


def holds(db: Session, user_id: int, code: str) -> bool:
    return db.execute(holder_ids(code).where(ArkUser.id == user_id)).first() is not None


def normalize_alias(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").lower()[:120]


def scoped_customer_ids(user_id: int):
    """归属人或提成人的客户 ID 子查询。"""
    owned = select(DomesticCustomer.id).where(DomesticCustomer.owner_user_id == user_id)
    commission = select(DomesticCustomerCommission.customer_id).where(DomesticCustomerCommission.user_id == user_id)
    return owned.union(commission)


def potential_customer_ids():
    return select(DomesticCustomer.id).where(DomesticCustomer.lifecycle_status == PROSPECT_LIFECYCLE)


def followup_filter(current_user: dict):
    """确认记录的可见条件；read_all 返回 None 表示不加过滤。"""
    if can_read_all(current_user):
        return None
    user_id = uid(current_user)
    task_followups = select(DomesticFollowupTask.source_followup_id).where(
        DomesticFollowupTask.assignee_user_id == user_id,
        DomesticFollowupTask.source_followup_id.is_not(None),
    )
    # 草稿与作废记录只对作者可见；客户范围和任务来源只放行已确认记录
    return or_(
        DomesticFollowup.author_user_id == user_id,
        and_(
            DomesticFollowup.status == "confirmed",
            or_(DomesticFollowup.customer_id.in_(scoped_customer_ids(user_id)),
                DomesticFollowup.id.in_(task_followups)),
        ),
    )


def task_filter(current_user: dict):
    if can_read_all(current_user):
        return None
    user_id = uid(current_user)
    return or_(
        DomesticFollowupTask.assignee_user_id == user_id,
        DomesticFollowupTask.customer_id.in_(scoped_customer_ids(user_id)),
    )


def in_customer_scope(db: Session, current_user: dict, customer_id: int) -> bool:
    if can_read_all(current_user):
        return True
    user_id = uid(current_user)
    if db.query(DomesticCustomer.id).filter(
        DomesticCustomer.id == customer_id, DomesticCustomer.owner_user_id == user_id
    ).first():
        return True
    return db.query(DomesticCustomerCommission.id).filter(
        DomesticCustomerCommission.customer_id == customer_id, DomesticCustomerCommission.user_id == user_id
    ).first() is not None


def can_write_customer(db: Session, current_user: dict, customer: DomesticCustomer) -> bool:
    if customer.owner_user_id is None or in_customer_scope(db, current_user, customer.id):
        return True
    return db.query(DomesticFollowupTask.id).filter(
        DomesticFollowupTask.customer_id == customer.id,
        DomesticFollowupTask.assignee_user_id == uid(current_user),
        DomesticFollowupTask.status == "todo",
    ).first() is not None


def _owner_name(db: Session, owner_user_id: int | None) -> str:
    if owner_user_id is None:
        return "公海"
    row = db.query(ArkUser.real_name).filter(ArkUser.id == owner_user_id).first()
    return row[0] if row else f"用户{owner_user_id}"


def ensure_customer_writable(db: Session, current_user: dict, customer_id: int) -> DomesticCustomer:
    customer = db.get(DomesticCustomer, customer_id)
    if customer is None:
        raise LookupError("客户不存在")
    if customer.status != 1:
        raise PermissionError("该客户已停用，不能记录跟进")
    if not can_write_customer(db, current_user, customer):
        raise PermissionError(f"该客户归属 {_owner_name(db, customer.owner_user_id)}，不能记录跟进")
    return customer


def _customer_row(db: Session, current_user: dict, customer: DomesticCustomer, matched_alias=None) -> dict:
    return {
        "id": customer.id,
        "shop_name": customer.shop_name,
        "custom_code": customer.custom_code,
        "contact": customer.contact,
        "province": customer.province,
        "customer_level": customer.customer_level,
        "lifecycle_status": customer.lifecycle_status,
        "owner_user_id": customer.owner_user_id,
        "owner_name": _owner_name(db, customer.owner_user_id),
        "writable": can_write_customer(db, current_user, customer),
        "matched_alias": matched_alias,
    }


def _like(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_customers(db: Session, current_user: dict, q: str) -> list[dict]:
    keyword = (q or "").strip()
    if not keyword:
        return []
    like = _like(keyword)
    query = db.query(DomesticCustomer).filter(DomesticCustomer.status == 1)
    if not can_read_all(current_user):
        query = query.filter(or_(
            DomesticCustomer.id.in_(scoped_customer_ids(uid(current_user))),
            DomesticCustomer.owner_user_id.is_(None),
        ))
    direct = query.filter(or_(
        DomesticCustomer.shop_name.like(like, escape="\\"),
        DomesticCustomer.contact.like(like, escape="\\"),
        DomesticCustomer.custom_code.like(like, escape="\\"),
    )).order_by(DomesticCustomer.shop_name).limit(SEARCH_LIMIT).all()
    results = [_customer_row(db, current_user, c) for c in direct]
    seen = {c.id for c in direct}

    # 别名先套可见范围再 limit，避免范围外的高频别名把结果挤掉
    alias_rows = (
        query.join(DomesticCustomerAlias, DomesticCustomerAlias.customer_id == DomesticCustomer.id)
        .filter(DomesticCustomerAlias.alias_norm.like(_like(normalize_alias(keyword)), escape="\\"))
        .with_entities(DomesticCustomer, DomesticCustomerAlias.alias)
        .order_by(DomesticCustomerAlias.hit_count.desc())
        .limit(SEARCH_LIMIT)
        .all()
    )
    for customer, alias in alias_rows:
        if customer.id in seen:
            continue
        results.append(_customer_row(db, current_user, customer, matched_alias=alias))
        seen.add(customer.id)
    return results[:SEARCH_LIMIT]


def match_alias(db: Session, current_user: dict, chat_title: str | None) -> dict | None:
    """聊天标题精确命中别名时返回客户行（供 AI 结果后置校正）。

    可见范围与 status==1 放进查询条件再按 hit_count 取首条，和 search_customers 一致：
    范围外的高频别名不应遮住范围内的同名别名（第 2 批对抗性审查，2026-10-31）。
    """
    norm = normalize_alias(chat_title)
    if not norm:
        return None
    query = (
        db.query(DomesticCustomerAlias, DomesticCustomer)
        .join(DomesticCustomer, DomesticCustomer.id == DomesticCustomerAlias.customer_id)
        .filter(DomesticCustomerAlias.alias_norm == norm, DomesticCustomer.status == 1)
    )
    if not can_read_all(current_user):
        query = query.filter(or_(
            DomesticCustomer.owner_user_id.is_(None),
            DomesticCustomer.id.in_(scoped_customer_ids(uid(current_user))),
        ))
    row = query.order_by(DomesticCustomerAlias.hit_count.desc()).first()
    if row is None:
        return None
    alias, customer = row
    return _customer_row(db, current_user, customer, matched_alias=alias.alias)


def _find_alias(db: Session, norm: str, customer_id: int) -> DomesticCustomerAlias | None:
    return db.query(DomesticCustomerAlias).filter(
        DomesticCustomerAlias.alias_norm == norm, DomesticCustomerAlias.customer_id == customer_id
    ).first()


def _bump_alias(db: Session, norm: str, customer_id: int) -> None:
    db.execute(update(DomesticCustomerAlias)
               .where(DomesticCustomerAlias.alias_norm == norm, DomesticCustomerAlias.customer_id == customer_id)
               .values(hit_count=DomesticCustomerAlias.hit_count + 1)
               .execution_options(synchronize_session=False))


def learn_alias(db: Session, customer_id: int, chat_title: str | None, user_id: int) -> None:
    norm = normalize_alias(chat_title)
    if not norm:
        return
    alias = _find_alias(db, norm, customer_id)
    if alias:
        alias.hit_count += 1
        return
    savepoint = db.begin_nested()
    try:
        db.add(DomesticCustomerAlias(customer_id=customer_id, alias=chat_title.strip()[:120],
                                     alias_norm=norm, created_by=user_id))
        db.flush()
        savepoint.commit()
    except IntegrityError as exc:
        # 两个人同时确认同一聊天标题：另一事务先插了这条别名，改成命中 +1，不能让整条跟进确认失败
        savepoint.rollback()
        logger.warning("followup alias insert conflict customer=%s: %s", customer_id, type(exc.orig).__name__)
        print(f"[domestic_followup] alias insert conflict customer={customer_id}", flush=True)
        _bump_alias(db, norm, customer_id)


def create_prospect(db: Session, current_user: dict, shop_name: str) -> dict:
    """在内贸客户主档建「潜在」档，只要店名（决策 2）。撞名给出归属提示。"""
    from app.domestic import customer_service
    from app.domestic.schemas import CustomerCreate
    from app.system.models import SysDict

    name = (shop_name or "").strip()
    if not name:
        raise ValueError("请填写客户店名")
    lifecycle_ok = db.query(SysDict.id).filter(
        SysDict.type == "domestic_customer_lifecycle", SysDict.is_active.is_(True),
        or_(SysDict.code == PROSPECT_LIFECYCLE, SysDict.label == PROSPECT_LIFECYCLE),
    ).first()
    if lifecycle_ok is None:
        raise ValueError(f"客户状态字典里没有「{PROSPECT_LIFECYCLE}」，请先在字典管理恢复该项")
    existing = db.query(DomesticCustomer).filter(DomesticCustomer.shop_name == name).first()
    if existing:
        if existing.owner_user_id is None:
            raise ValueError("该客户已存在，目前在公海，请先在客户管理认领")
        raise ValueError(f"该客户已存在（归属：{_owner_name(db, existing.owner_user_id)}）")
    customer = customer_service.create_customer(
        db, CustomerCreate(shop_name=name, lifecycle_status=PROSPECT_LIFECYCLE), uid(current_user),
    )
    return _customer_row(db, current_user, customer)
