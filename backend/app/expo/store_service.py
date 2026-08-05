"""展会门店/展位配额主体的 CRUD 与人员绑定服务。"""

import logging
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth.models import ArkUser
from app.expo.models import ExpoStore, ExpoStoreUser

logger = logging.getLogger("commission.expo.store")


class StoreNotFound(Exception):
    """门店/展位不存在。"""


class UserAlreadyBound(Exception):
    """用户已与该门店绑定。"""


def _strip_or_none(value: Optional[str]) -> Optional[str]:
    """字符串去首尾空；空串落 NULL。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _check_code_duplicate(db: Session, code: str, exclude_id: Optional[int] = None) -> None:
    """检查门店编码是否已存在；exclude_id 用于更新时排除自身。"""
    q = db.query(ExpoStore).filter(ExpoStore.code == code)
    if exclude_id is not None:
        q = q.filter(ExpoStore.id != exclude_id)
    if q.first() is not None:
        raise ValueError(f"门店编码 {code} 已存在")


def get_store_by_id(db: Session, store_id: int) -> Optional[ExpoStore]:
    """按 ID 获取门店。"""
    return db.get(ExpoStore, store_id)


def list_stores(
    db: Session,
    *,
    keyword: str = "",
    status: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[ExpoStore], int]:
    """分页查询门店列表；支持按名称/编码关键字与状态过滤。"""
    q = db.query(ExpoStore)

    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter(ExpoStore.name.like(like) | ExpoStore.code.like(like))

    if status is not None:
        q = q.filter(ExpoStore.status == status)

    total = q.count()
    rows = (
        q.order_by(ExpoStore.status.desc(), ExpoStore.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def create_store(
    db: Session,
    *,
    name: str,
    code: str,
    contact_name: Optional[str] = None,
    contact_phone: Optional[str] = None,
    status: int = 1,
) -> ExpoStore:
    """创建门店；code 全局唯一。"""
    clean_code = code.strip()
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("门店名称不能为空")
    if not clean_code:
        raise ValueError("门店编码不能为空")

    _check_code_duplicate(db, clean_code)

    store = ExpoStore(
        name=clean_name,
        code=clean_code,
        contact_name=_strip_or_none(contact_name),
        contact_phone=_strip_or_none(contact_phone),
        status=status,
    )
    db.add(store)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = f"[expo] create_store conflict code={clean_code}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise ValueError(f"门店编码 {clean_code} 已存在") from None
    db.refresh(store)
    return store


def update_store(db: Session, store: ExpoStore, **kwargs) -> ExpoStore:
    """更新门店字段；只允许修改白名单内的字段，校验通过后再修改对象。"""
    if store is None:
        raise StoreNotFound("门店不存在")

    allowed = {"name", "code", "contact_name", "contact_phone", "status"}
    updates = {}
    for key, value in kwargs.items():
        if key not in allowed:
            continue
        if key in ("name", "code", "contact_name", "contact_phone"):
            value = _strip_or_none(value)
            if key in ("name", "code") and not value:
                raise ValueError(f"{key} 不能为空")
        updates[key] = value

    if "code" in updates and updates["code"] != store.code:
        _check_code_duplicate(db, updates["code"], exclude_id=store.id)

    for key, value in updates.items():
        setattr(store, key, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = f"[expo] update_store conflict store={store.id}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise ValueError(f"门店编码 {store.code} 已存在") from None

    db.refresh(store)
    return store


def get_active_store_by_user(db: Session, user_id: int) -> Optional[ExpoStore]:
    """查询用户当前绑定的启用中门店；优先返回主负责人绑定。"""
    su = (
        db.query(ExpoStoreUser)
        .join(ExpoStore)
        .filter(
            ExpoStoreUser.user_id == user_id,
            ExpoStore.status == 1,
        )
        .options(selectinload(ExpoStoreUser.store))
        .order_by(ExpoStoreUser.is_primary.desc(), ExpoStoreUser.id.asc())
        .first()
    )
    return su.store if su else None


def list_store_users(db: Session, store_id: int) -> List[ExpoStoreUser]:
    """列出某门店下所有绑定用户，并预加载用户信息。"""
    return (
        db.query(ExpoStoreUser)
        .filter(ExpoStoreUser.store_id == store_id)
        .options(selectinload(ExpoStoreUser.user))
        .order_by(ExpoStoreUser.is_primary.desc(), ExpoStoreUser.id.asc())
        .all()
    )


def bind_user_to_store(
    db: Session, store_id: int, user_id: int, is_primary: bool = False
) -> ExpoStoreUser:
    """将用户绑定到门店；store_id/user_id 任一不存在或已绑定均抛异常。"""
    store = db.get(ExpoStore, store_id)
    if store is None:
        raise StoreNotFound(f"门店 {store_id} 不存在")

    user = db.get(ArkUser, user_id)
    if user is None:
        raise ValueError(f"用户 {user_id} 不存在")

    existing = (
        db.query(ExpoStoreUser.id)
        .filter(ExpoStoreUser.store_id == store_id, ExpoStoreUser.user_id == user_id)
        .first()
    )
    if existing is not None:
        raise UserAlreadyBound(f"用户 {user_id} 已与门店 {store_id} 绑定")

    binding = ExpoStoreUser(
        store_id=store_id,
        user_id=user_id,
        is_primary=is_primary,
    )
    db.add(binding)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = f"[expo] bind_user_to_store 并发冲突 store={store_id} user={user_id}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise UserAlreadyBound(f"用户 {user_id} 已与门店 {store_id} 绑定") from None

    db.refresh(binding)
    return binding


def unbind_user_from_store(db: Session, store_id: int, user_id: int) -> None:
    """解除用户与门店的绑定关系；物理删除（该表无软删除字段）。"""
    binding = (
        db.query(ExpoStoreUser)
        .filter(ExpoStoreUser.store_id == store_id, ExpoStoreUser.user_id == user_id)
        .first()
    )
    if binding is None:
        return

    db.delete(binding)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = f"[expo] unbind_user_from_store 失败 store={store_id} user={user_id}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise
