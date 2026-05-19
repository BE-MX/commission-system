"""素材管理 — 收藏夹/收藏项 CRUD"""

from sqlalchemy.orm import Session

from app.asset.models import FavoriteFolder, FavoriteItem


# ── 收藏夹 ──────────────────────────────────────────────

def list_favorite_folders(db: Session, user_id: int) -> list[FavoriteFolder]:
    return (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.user_id == user_id)
        .order_by(FavoriteFolder.sort_order)
        .all()
    )


def create_favorite_folder(db: Session, user_id: int, name: str) -> FavoriteFolder:
    # 自动分配 sort_order
    max_sort = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.user_id == user_id)
        .count()
    )
    folder = FavoriteFolder(
        user_id=user_id,
        name=name,
        sort_order=max_sort,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def update_favorite_folder(
    db: Session,
    folder_id: int,
    user_id: int,
    name: str | None = None,
    sort_order: int | None = None,
) -> FavoriteFolder | None:
    folder = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.id == folder_id, FavoriteFolder.user_id == user_id)
        .first()
    )
    if not folder:
        return None
    if name is not None:
        folder.name = name
    if sort_order is not None:
        folder.sort_order = sort_order
    db.commit()
    db.refresh(folder)
    return folder


def delete_favorite_folder(db: Session, folder_id: int, user_id: int) -> bool:
    folder = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.id == folder_id, FavoriteFolder.user_id == user_id)
        .first()
    )
    if not folder:
        return False
    db.delete(folder)
    db.commit()
    return True


# ── 收藏项 ──────────────────────────────────────────────

def list_favorite_items(db: Session, folder_id: int, user_id: int) -> list[FavoriteItem]:
    """返回收藏项（含素材详情）。"""
    from app.asset.models import Asset

    items = (
        db.query(FavoriteItem)
        .join(FavoriteFolder)
        .filter(
            FavoriteItem.folder_id == folder_id,
            FavoriteFolder.user_id == user_id,
        )
        .order_by(FavoriteItem.sort_order)
        .all()
    )
    # 预加载素材
    asset_ids = [i.asset_id for i in items]
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids)).all()}
    for item in items:
        item.asset = assets.get(item.asset_id)
    return items


def add_favorite_item(db: Session, folder_id: int, user_id: int, asset_id: int) -> FavoriteItem | None:
    """添加收藏项。已存在则返回 None。"""
    folder = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.id == folder_id, FavoriteFolder.user_id == user_id)
        .first()
    )
    if not folder:
        return None

    existing = (
        db.query(FavoriteItem)
        .filter(FavoriteItem.folder_id == folder_id, FavoriteItem.asset_id == asset_id)
        .first()
    )
    if existing:
        return existing

    max_sort = (
        db.query(FavoriteItem)
        .filter(FavoriteItem.folder_id == folder_id)
        .count()
    )
    item = FavoriteItem(
        folder_id=folder_id,
        asset_id=asset_id,
        sort_order=max_sort,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def remove_favorite_item(db: Session, folder_id: int, user_id: int, item_id: int) -> bool:
    folder = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.id == folder_id, FavoriteFolder.user_id == user_id)
        .first()
    )
    if not folder:
        return False

    item = (
        db.query(FavoriteItem)
        .filter(FavoriteItem.id == item_id, FavoriteItem.folder_id == folder_id)
        .first()
    )
    if not item:
        return False

    db.delete(item)
    db.commit()
    return True


# ── 分享 ────────────────────────────────────────────────

import secrets
from datetime import datetime, timedelta


def share_folder(
    db: Session,
    folder_id: int,
    user_id: int,
    expires_hours: int = 168,  # 默认 7 天
) -> FavoriteFolder | None:
    """生成分享 token。返回更新后的 folder。"""
    folder = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.id == folder_id, FavoriteFolder.user_id == user_id)
        .first()
    )
    if not folder:
        return None

    folder.share_token = secrets.token_urlsafe(16)
    folder.share_expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
    db.commit()
    db.refresh(folder)
    return folder


def get_shared_folder(db: Session, token: str) -> FavoriteFolder | None:
    """通过分享 token 获取收藏夹（不校验用户）。"""
    folder = (
        db.query(FavoriteFolder)
        .filter(
            FavoriteFolder.share_token == token,
            FavoriteFolder.share_expires_at > datetime.utcnow(),
        )
        .first()
    )
    return folder


def revoke_share(db: Session, folder_id: int, user_id: int) -> bool:
    """取消分享。"""
    folder = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.id == folder_id, FavoriteFolder.user_id == user_id)
        .first()
    )
    if not folder:
        return False
    folder.share_token = None
    folder.share_expires_at = None
    db.commit()
    return True
