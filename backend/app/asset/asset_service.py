"""素材管理 — 素材上传/查询/更新/下载"""

import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("asset")

from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import Session, selectinload, joinedload

from app.asset.models import (
    Asset,
    AssetPermission,
    AssetVersion,
    DownloadLog,
    TagValue,
    asset_tag_association,
)
from app.asset.schemas import AssetPermissionIn, AssetTagItem

# 文件存储根目录（从环境变量读取，默认 D:\WORKSOURCE）
from app.core.config import get_settings

ASSET_STORAGE_ROOT = Path(get_settings().ASSET_STORAGE_ROOT)
ASSET_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

# 缩略图尺寸
THUMB_MAX_WIDTH = 600

# 签名 URL 有效期（秒）
SIGNED_URL_EXPIRY = 7200


def _build_storage_path(file_type: str, file_format: str) -> str:
    """生成存储路径: {root}/{year}/{month}/{uuid}.{ext}"""
    now = datetime.now()
    ext = file_format.lower().lstrip(".")
    uid = uuid.uuid4().hex[:16]
    rel_path = f"{now.year}/{now.month:02d}/{uid}.{ext}"
    return rel_path


def _ensure_dir(abs_path: Path) -> None:
    abs_path.parent.mkdir(parents=True, exist_ok=True)


def _save_upload_file(src_path: str, rel_path: str, *, copy: bool = False) -> str:
    """将上传的临时文件移到（或复制到）正式存储目录。返回绝对路径。"""
    abs_path = ASSET_STORAGE_ROOT / rel_path
    _ensure_dir(abs_path)
    if copy:
        shutil.copy2(src_path, str(abs_path))
    else:
        shutil.move(src_path, str(abs_path))
    return str(abs_path)


def _generate_thumbnail(image_path: str, rel_path: str) -> Optional[str]:
    """生成图片缩略图。返回相对路径或 None。"""
    try:
        from PIL import Image

        thumb_rel = rel_path.rsplit(".", 1)[0] + "_thumb.jpg"
        thumb_abs = ASSET_STORAGE_ROOT / thumb_rel
        _ensure_dir(thumb_abs)

        with Image.open(image_path) as im:
            im.thumbnail((THUMB_MAX_WIDTH, THUMB_MAX_WIDTH))
            im = im.convert("RGB")
            im.save(str(thumb_abs), "JPEG", quality=85)
        return thumb_rel
    except Exception:
        return None


def _generate_video_thumbnail(video_path: str, rel_path: str) -> Optional[str]:
    """从视频抽取第一帧生成缩略图。返回相对路径或 None。"""
    try:
        import cv2

        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return None

        h, w = frame.shape[:2]
        if w > THUMB_MAX_WIDTH:
            scale = THUMB_MAX_WIDTH / w
            frame = cv2.resize(frame, (THUMB_MAX_WIDTH, int(h * scale)))

        thumb_rel = rel_path.rsplit(".", 1)[0] + "_thumb.jpg"
        thumb_abs = ASSET_STORAGE_ROOT / thumb_rel
        _ensure_dir(thumb_abs)
        cv2.imwrite(str(thumb_abs), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return thumb_rel
    except Exception:
        return None


def _delete_file(rel_path: Optional[str]) -> None:
    if not rel_path:
        return
    try:
        (ASSET_STORAGE_ROOT / rel_path).unlink(missing_ok=True)
    except Exception as exc:
        # 文件删除失败不阻断业务，但必须留痕（B-2：吞掉可以，无声不行）
        logger.warning("asset file delete failed: %s err=%s", rel_path, exc)
        print(f"[asset] file delete failed: {rel_path} err={exc}", flush=True)


def _compute_orientation(abs_path, file_type: str) -> Optional[str]:
    """从文件宽高计算画幅（landscape/portrait/square）。失败不阻断上传。"""
    try:
        w = h = None
        if file_type == "image":
            from PIL import Image
            with Image.open(abs_path) as im:
                w, h = im.size
        elif file_type == "video":
            import cv2
            cap = cv2.VideoCapture(str(abs_path))
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
        if not w or not h:
            return None
        if w > h * 1.05:
            return "landscape"
        if h > w * 1.05:
            return "portrait"
        return "square"
    except Exception as exc:
        logger.warning("orientation compute failed: %s err=%s", abs_path, exc)
        print(f"[asset] orientation compute failed: {abs_path} err={exc}", flush=True)
        return None


# ── 创建素材 ────────────────────────────────────────────

def create_asset(
    db: Session,
    *,
    file_name: str,
    file_type: str,
    file_format: str,
    file_size: int,
    temp_storage_path: str,
    uploader_id: int,
    tags: list[AssetTagItem],
    permission: AssetPermissionIn,
    remark: Optional[str] = None,
    copy: bool = False,
) -> Asset:
    """创建素材（含第一版版本记录）。"""
    # 校验先于落盘：否则 400 回滚后存储区留孤儿文件+缩略图
    _validate_single_select(db, tags)

    rel_path = _build_storage_path(file_type, file_format)
    abs_path = _save_upload_file(temp_storage_path, rel_path, copy=copy)

    # 缩略图
    thumbnail_path: Optional[str] = None
    if file_type == "image":
        thumbnail_path = _generate_thumbnail(abs_path, rel_path)
    elif file_type == "video":
        thumbnail_path = _generate_video_thumbnail(abs_path, rel_path)

    # 创建素材主记录
    asset = Asset(
        file_name=file_name,
        file_type=file_type,
        file_format=file_format,
        storage_path=rel_path,
        file_size=file_size,
        thumbnail_path=thumbnail_path,
        orientation=_compute_orientation(abs_path, file_type),
        uploader_id=uploader_id,
        status="latest",
        remark=remark,
    )
    db.add(asset)
    db.flush()

    # 创建版本记录
    version = AssetVersion(
        asset_id=asset.id,
        version_number=1,
        storage_path=rel_path,
        file_size=file_size,
        uploader_id=uploader_id,
    )
    db.add(version)
    db.flush()

    # 更新当前版本
    asset.current_version_id = version.id

    # 写入标签 + 色系派生（color_family 托管维度唯一常态写入路径）
    _apply_tags(db, asset.id, version.id, tags)
    from app.asset.color_rules import sync_color_family
    sync_color_family(db, asset.id, version.id)

    # 写入权限
    perm = AssetPermission(
        asset_id=asset.id,
        permission_group=permission.permission_group,
        allow_preview=permission.allow_preview,
        allow_download=permission.allow_download,
        specified_user_ids=permission.specified_user_ids,
    )
    db.add(perm)

    db.commit()
    db.refresh(asset)
    return asset


class SingleSelectViolation(Exception):
    """单选维度收到多个标签值。"""


def _validate_single_select(db: Session, tags: list[AssetTagItem]) -> None:
    """单选维度每素材至多一个值，违反抛 SingleSelectViolation（router 转 400）。"""
    from app.asset.models import TagDimension

    multi = {item.dimension_id for item in tags if len(item.tag_value_ids) > 1}
    if not multi:
        return
    rows = (
        db.query(TagDimension)
        .filter(TagDimension.id.in_(multi), TagDimension.is_single_select == 1)
        .all()
    )
    if rows:
        labels = "、".join(d.label for d in rows)
        raise SingleSelectViolation(f"单选维度[{labels}]只能选择一个标签值")


def _apply_tags(
    db: Session,
    asset_id: int,
    version_id: int,
    tags: list[AssetTagItem],
) -> None:
    """将标签关联写入 asset_tag_association。

    托管维度（色系）由派生脚本独占写入，用户侧提交的托管维度项跳过并留痕。
    """
    from app.asset.models import TagDimension

    _validate_single_select(db, tags)
    managed_ids = {d.id for d in db.query(TagDimension).filter(
        TagDimension.id.in_({t.dimension_id for t in tags} or {0}),
        TagDimension.is_managed == 1)}
    for item in tags:
        if item.dimension_id in managed_ids:
            logger.warning("skip managed dimension tag write: dim=%s asset=%s", item.dimension_id, asset_id)
            print(f"[asset] skip managed dim tag write dim={item.dimension_id} asset={asset_id}", flush=True)
            continue
        for tv_id in item.tag_value_ids:
            db.execute(
                asset_tag_association.insert().values(
                    asset_id=asset_id,
                    version_id=version_id,
                    dimension_id=item.dimension_id,
                    tag_value_id=tv_id,
                )
            )


def _clear_tags(
    db: Session,
    asset_id: int,
    version_id: Optional[int] = None,
    dimension_ids: Optional[list[int]] = None,
) -> None:
    """清除素材标签关联。

    dimension_ids 给定时只清这些维度（按维度合并语义——编辑请求未提及的
    维度保持原样，避免并存期一次保存抹掉另一套体系的标签）；
    None = 全清（仅供内部工具使用）。version_id 保留参数兼容，实际已忽略。
    """
    stmt = asset_tag_association.delete().where(
        asset_tag_association.c.asset_id == asset_id,
    )
    if dimension_ids is not None:
        stmt = stmt.where(asset_tag_association.c.dimension_id.in_(dimension_ids))
    db.execute(stmt)


# ── 查询素材 ────────────────────────────────────────────

def query_assets(
    db: Session,
    *,
    file_type: Optional[str] = None,
    tag_filters: Optional[dict[str, list[int]]] = None,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 24,
) -> tuple[int, list[Asset], list[int]]:
    """返回 (total, items, available_tag_ids)。

    优化策略 (2026-05-28):
      - 标签筛选用 INNER JOIN tag_subquery 替代 Asset.id IN (...) 子查询
      - 列表加载用 selectinload 替代 joinedload，避免 LIMIT + JOIN 笛卡尔积
      - total / available_tag_ids 共用同一个 tag_subquery,只算一次
    """
    q = db.query(Asset)

    if file_type:
        q = q.filter(Asset.file_type == file_type)
    if status:
        q = q.filter(or_(Asset.status == status, Asset.status.is_(None)))

    # 关键词检索（文件名/备注）
    if keyword:
        like_kw = f"%{keyword}%"
        q = q.filter(
            or_(
                Asset.file_name.ilike(like_kw),
                Asset.remark.ilike(like_kw),
            )
        )

    # 标签筛选: 命中所有维度的素材 ID 子查询
    _tag_subquery = None
    if tag_filters:
        from app.asset.models import TagDimension

        dim_names = [name for name, ids in tag_filters.items() if ids]
        if dim_names:
            dims = (
                db.query(TagDimension.id, TagDimension.name)
                .filter(TagDimension.name.in_(dim_names))
                .all()
            )
            dim_name_to_id = {d.name: d.id for d in dims}

            or_conditions = []
            active_dim_count = 0
            for dim_name, tv_ids in tag_filters.items():
                if not tv_ids:
                    continue
                dim_id = dim_name_to_id.get(dim_name)
                if dim_id is None:
                    continue
                active_dim_count += 1
                or_conditions.append(
                    and_(
                        asset_tag_association.c.dimension_id == dim_id,
                        asset_tag_association.c.tag_value_id.in_(tv_ids),
                    )
                )

            if or_conditions:
                _tag_subquery = (
                    db.query(asset_tag_association.c.asset_id.label("asset_id"))
                    .filter(or_(*or_conditions))
                    .group_by(asset_tag_association.c.asset_id)
                    .having(
                        func.count(func.distinct(asset_tag_association.c.dimension_id))
                        == active_dim_count
                    )
                    .subquery()
                )
                # INNER JOIN 比 Asset.id IN (subquery) 在 MySQL 上选计划更稳
                q = q.join(_tag_subquery, Asset.id == _tag_subquery.c.asset_id)

    # total: 主查询的 COUNT(*)
    total = q.with_entities(func.count(Asset.id)).scalar() or 0
    if total == 0:
        return 0, [], []

    # 联动筛选 available_tag_ids:
    #   命中 tag_subquery 的所有素材关联的全部标签集合,前端用来灰显不可选的 chips
    available_tag_ids: list[int] = []
    if _tag_subquery is not None and total <= 2000:
        available_tag_ids = [
            tid
            for (tid,) in db.query(asset_tag_association.c.tag_value_id.distinct())
            .join(_tag_subquery, asset_tag_association.c.asset_id == _tag_subquery.c.asset_id)
            .all()
            if tid is not None
        ]

    sort_col = getattr(Asset, sort_by, Asset.created_at)
    if sort_order == "desc":
        q = q.order_by(desc(sort_col))
    else:
        q = q.order_by(sort_col)

    # 分页 + selectinload tags (selectinload 比 joinedload 在 LIMIT 场景下快 6 倍)
    # permissions 也加载, 移动端 quick-search 端点会访问 a.permissions.allow_preview 等字段
    items = (
        q.options(
            selectinload(Asset.tags).joinedload(TagValue.dimension),
            selectinload(Asset.permissions),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items, available_tag_ids


def get_asset_detail(db: Session, asset_id: int) -> Optional[Asset]:
    return (
        db.query(Asset)
        .options(
            joinedload(Asset.tags).joinedload(TagValue.dimension),
            joinedload(Asset.versions),
            joinedload(Asset.permissions),
        )
        .filter(Asset.id == asset_id)
        .first()
    )


# ── 更新素材 ────────────────────────────────────────────

def update_asset_tags(
    db: Session,
    asset_id: int,
    tags: list[AssetTagItem],
) -> Optional[Asset]:
    """按维度合并更新标签：只覆盖请求中出现的维度（含空列表=清空该维度），
    未出现的维度保持原样。前端清空某维度需显式传 tag_value_ids=[]。"""
    asset = get_asset_detail(db, asset_id)
    if not asset:
        return None

    version_id = asset.current_version_id
    touched_dims = [item.dimension_id for item in tags]
    _clear_tags(db, asset_id, version_id, dimension_ids=touched_dims)
    _apply_tags(db, asset_id, version_id, tags)
    from app.asset.color_rules import sync_color_family
    sync_color_family(db, asset_id, version_id)
    db.commit()
    db.refresh(asset)
    return asset


def update_asset_status(
    db: Session,
    asset_id: int,
    status: str,
) -> Optional[Asset]:
    asset = get_asset_detail(db, asset_id)
    if not asset:
        return None
    asset.status = status
    db.commit()
    db.refresh(asset)
    return asset


def upload_new_version(
    db: Session,
    asset_id: int,
    file_name: str,
    file_size: int,
    temp_storage_path: str,
    uploader_id: int,
    remark: Optional[str] = None,
    copy: bool = False,
) -> Optional[AssetVersion]:
    """上传新版本。旧版标记为 history，新版标记为 latest。"""
    asset = get_asset_detail(db, asset_id)
    if not asset:
        return None

    # 旧版标记为 history
    asset.status = "history"

    # 生成新存储路径
    rel_path = _build_storage_path(asset.file_type, asset.file_format)
    _save_upload_file(temp_storage_path, rel_path, copy=copy)

    # 缩略图
    thumbnail_path: Optional[str] = None
    if asset.file_type == "image":
        thumbnail_path = _generate_thumbnail(
            str(ASSET_STORAGE_ROOT / rel_path), rel_path
        )
    elif asset.file_type == "video":
        thumbnail_path = _generate_video_thumbnail(
            str(ASSET_STORAGE_ROOT / rel_path), rel_path
        )

    # 文件被替换，画幅重算
    asset.orientation = _compute_orientation(str(ASSET_STORAGE_ROOT / rel_path), asset.file_type)

    # 计算版本号
    max_ver = (
        db.query(func.max(AssetVersion.version_number))
        .filter(AssetVersion.asset_id == asset_id)
        .scalar()
        or 0
    )

    version = AssetVersion(
        asset_id=asset_id,
        version_number=max_ver + 1,
        storage_path=rel_path,
        file_size=file_size,
        uploader_id=uploader_id,
        remark=remark,
    )
    db.add(version)
    db.flush()

    # 更新素材主记录
    asset.current_version_id = version.id
    asset.status = "latest"
    asset.file_name = file_name
    asset.file_size = file_size
    asset.storage_path = rel_path
    asset.thumbnail_path = thumbnail_path

    # 复制旧版标签到新版本
    _copy_tags_to_version(db, asset_id, version.id)

    db.commit()
    db.refresh(version)
    return version


def _copy_tags_to_version(db: Session, asset_id: int, new_version_id: int) -> None:
    """将素材当前版本的标签复制到新版本。"""
    asset = get_asset_detail(db, asset_id)
    if not asset or not asset.current_version_id:
        return

    rows = db.execute(
        asset_tag_association.select().where(
            asset_tag_association.c.asset_id == asset_id,
            asset_tag_association.c.version_id == asset.current_version_id,
        )
    ).fetchall()

    for row in rows:
        db.execute(
            asset_tag_association.insert().values(
                asset_id=asset_id,
                version_id=new_version_id,
                dimension_id=row.dimension_id,
                tag_value_id=row.tag_value_id,
            )
        )


# ── 删除素材 ────────────────────────────────────────────

def delete_asset(db: Session, asset_id: int) -> bool:
    asset = get_asset_detail(db, asset_id)
    if not asset:
        return False

    # 删除物理文件
    _delete_file(asset.storage_path)
    _delete_file(asset.thumbnail_path)
    for v in asset.versions:
        _delete_file(v.storage_path)

    db.delete(asset)
    db.commit()
    return True


# ── 下载 ────────────────────────────────────────────────

def build_download_filename(asset: Asset) -> str:
    """按标签生成语义化下载名：产品_色号_内容_原名。

    只改下载时的 Content-Disposition，物理文件与 file_name 字段不动
    （方案第六节：不改名，下载动态命名）。标签取可见维度；无标签时退回原名。
    """
    parts: list[str] = []
    try:
        picks = {"product_type": None, "color_code": None, "content_type": None, "shoot_style": None}
        for tv in (asset.tags or []):
            dim = tv.dimension
            if dim is None or not getattr(dim, "is_visible", 1):
                continue
            if dim.name in picks and picks[dim.name] is None:
                # 产品维度跳过族级值（带"类"后缀的父级），优先具体产品
                if dim.name == "product_type" and tv.parent_value_id is None and tv.value.endswith("类"):
                    continue
                picks[dim.name] = tv.value
        parts = [picks["product_type"], picks["color_code"],
                 picks["content_type"] or picks["shoot_style"]]
        parts = [p for p in parts if p]
    except Exception:
        parts = []
    if not parts:
        return asset.file_name
    base = "_".join(parts)
    # 去掉文件系统危险字符，限长
    for ch in '\\/:*?"<>|':
        base = base.replace(ch, "-")
    return f"{base}_{asset.file_name}"[:150]


def get_asset_download_url(asset: Asset, expiry_seconds: int = SIGNED_URL_EXPIRY) -> str:
    """生成签名下载 URL。"""
    import time as _time
    expires = int(_time.time()) + expiry_seconds
    token = _make_sign_token(asset.storage_path, expires)
    return f"/api/assets/{asset.id}/download?token={token}&expires={expires}"


def _make_sign_token(path: str, expires: int) -> str:
    import hashlib
    import hmac

    secret = get_settings().ASSET_SIGN_SECRET
    msg = f"{path}:{expires}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def verify_sign_token(path: str, expires: int, token: str) -> bool:
    """验证签名 token 是否有效。"""
    import time

    if int(expires) < time.time():
        return False
    return token == _make_sign_token(path, expires)


def increment_download_count(db: Session, asset_id: int) -> None:
    asset = get_asset_detail(db, asset_id)
    if asset:
        asset.download_count += 1
        db.commit()


def log_download(db: Session, asset_id: int, user_id: int, version_number: Optional[int]) -> None:
    log = DownloadLog(
        asset_id=asset_id,
        user_id=user_id,
        version_number=version_number,
    )
    db.add(log)
    db.commit()
