"""素材管理 — 标签维度/值 CRUD + 种子数据"""

import threading
import time

from sqlalchemy.orm import Session

from app.asset.models import TagDimension, TagValue
from app.asset.taxonomy_def import TAXONOMY_V2, iter_values

# ── 内置维度种子 ───────────────────────────────────────


def create_taxonomy_dimension(db: Session, dim_def: dict, is_visible: int = 1,
                              force_optional: bool = False) -> TagDimension:
    """按 taxonomy_def 定义创建单个维度及其值（含 parent 挂靠/name_en/aliases）。

    调用方负责 commit。存量库并存期用 is_visible=0 + force_optional=True
    （必填在前端切换日才生效，避免上传表单被新维度卡死）。
    """
    dim = TagDimension(
        name=dim_def["name"],
        label=dim_def["label"],
        is_single_select=dim_def["is_single_select"],
        is_system=1,
        is_required=0 if force_optional else dim_def["is_required"],
        is_visible=is_visible,
        is_managed=dim_def.get("is_managed", 0),
        sort_order=dim_def["sort_order"],
    )
    db.add(dim)
    db.flush()

    for i, v in iter_values(dim_def):
        tv = TagValue(
            dimension_id=dim.id,
            value=v["value"],
            name_en=v["name_en"],
            aliases=v["aliases"],
            sort_order=i,
            is_active=1,
        )
        db.add(tv)
    db.flush()
    # content_type 值的 parent_value_id 指向 content_category 的值，
    # 需两个维度都建完后由 _link_content_type_parents 统一回填
    return dim


def seed_default_dimensions(db: Session) -> None:
    """初始化内置标签维度（taxonomy v2）。仅在表为空时创建，后续由用户管理。

    生产存量库不会走到这里（表非空），存量库的新维度由
    scripts/tag_taxonomy/setup_dimensions.py 以 is_visible=0 创建。
    """
    if db.query(TagDimension).first() is not None:
        return

    for dim_def in TAXONOMY_V2:
        create_taxonomy_dimension(db, dim_def, is_visible=1)
    link_taxonomy_parents(db)
    db.commit()


def link_taxonomy_parents(db: Session) -> None:
    """按 taxonomy_def 回填 parent_value_id。

    两类挂靠：content_type 的 parent 在 content_category（跨维度）；
    product_type 的 parent 是同维度的产品族值。解析顺序：同维度优先，
    找不到再查 content_category。幂等，可重复执行。
    """
    dims = {d.name: d for d in db.query(TagDimension).all()}
    cat_dim = dims.get("content_category")
    cat_ids = ({v.value: v.id for v in db.query(TagValue).filter(TagValue.dimension_id == cat_dim.id)}
               if cat_dim else {})

    for dim_def in TAXONOMY_V2:
        parent_map = {v["value"]: v["parent"] for _, v in iter_values(dim_def) if v["parent"]}
        if not parent_map:
            continue
        dim = dims.get(dim_def["name"])
        if not dim:
            continue
        own_values = db.query(TagValue).filter(TagValue.dimension_id == dim.id).all()
        own_ids = {v.value: v.id for v in own_values}
        for tv in own_values:
            parent_name = parent_map.get(tv.value)
            if not parent_name:
                continue
            parent_id = own_ids.get(parent_name) or cat_ids.get(parent_name)
            if parent_id and tv.parent_value_id != parent_id:
                tv.parent_value_id = parent_id
    db.flush()


# ── 维度查询 ────────────────────────────────────────────

# 进程内缓存: 跨海 RDS 跑一次需要 1-2 秒,标签维度变更频率极低,值得缓存
# 任何写操作后调用 invalidate_dim_cache() 立即失效
_DIM_CACHE: dict = {"data": None, "expires_at": 0.0}
_DIM_CACHE_LOCK = threading.Lock()
_DIM_CACHE_TTL_SECONDS = 60


def _build_dim_payload(dims: list[TagDimension]) -> list[dict]:
    """把 ORM 序列化成纯 dict,缓存安全(无 session 绑定)。"""
    return [{
        "id": d.id,
        "name": d.name,
        "label": d.label,
        "is_single_select": d.is_single_select,
        "is_system": d.is_system,
        "is_required": d.is_required,
        "is_visible": d.is_visible,
        "is_managed": d.is_managed,
        "sort_order": d.sort_order,
        "values": [{
            "id": v.id,
            "dimension_id": v.dimension_id,
            "value": v.value,
            "name_en": v.name_en,
            "aliases": v.aliases,
            "parent_value_id": v.parent_value_id,
            "color_hex": v.color_hex,
            "image_path": v.image_path,
            "sort_order": v.sort_order,
            "is_active": v.is_active,
        } for v in d.values],
    } for d in dims]


def list_dimensions(db: Session) -> list[TagDimension]:
    """所有标签维度（含标签值）— 直接查库,返回 ORM 对象。"""
    from sqlalchemy.orm import selectinload
    return (
        db.query(TagDimension)
        .options(selectinload(TagDimension.values))
        .order_by(TagDimension.sort_order)
        .all()
    )


def list_dimensions_cached(db: Session) -> list[dict]:
    """缓存版本 — 返回纯 dict,直接喂给 router 的 JSON 响应。

    TTL 60 秒,任何写操作会调用 invalidate_dim_cache() 立即失效。
    """
    now = time.time()
    cached = _DIM_CACHE
    if cached["data"] is not None and now < cached["expires_at"]:
        return cached["data"]

    with _DIM_CACHE_LOCK:
        # double check 防止并发重复刷新
        cached = _DIM_CACHE
        if cached["data"] is not None and now < cached["expires_at"]:
            return cached["data"]

        dims = list_dimensions(db)
        payload = _build_dim_payload(dims)
        _DIM_CACHE["data"] = payload
        _DIM_CACHE["expires_at"] = now + _DIM_CACHE_TTL_SECONDS
        return payload


def invalidate_dim_cache() -> None:
    """清空标签维度缓存,在任何 CRUD 写操作之后调用。"""
    _DIM_CACHE["data"] = None
    _DIM_CACHE["expires_at"] = 0.0


def get_dimension(db: Session, dim_id: int) -> TagDimension | None:
    return db.query(TagDimension).filter(TagDimension.id == dim_id).first()


# ── 标签值 CRUD ─────────────────────────────────────────

class ManagedDimensionError(Exception):
    """托管维度（is_managed=1，如色系）的值由派生脚本独占写入，禁止人工增删改。"""


def _guard_managed(db: Session, dimension_id: int) -> None:
    dim = db.query(TagDimension).filter(TagDimension.id == dimension_id).first()
    if dim and dim.is_managed:
        raise ManagedDimensionError(f"维度[{dim.label}]为系统托管，值由系统自动维护")


def create_dimension_value(
    db: Session,
    dimension_id: int,
    value: str,
    color_hex: str | None = None,
    image_path: str | None = None,
    sort_order: int = 0,
    name_en: str | None = None,
    aliases: list[str] | None = None,
    parent_value_id: int | None = None,
) -> TagValue:
    _guard_managed(db, dimension_id)
    tv = TagValue(
        dimension_id=dimension_id,
        value=value,
        name_en=name_en,
        aliases=aliases,
        parent_value_id=parent_value_id,
        color_hex=color_hex,
        image_path=image_path,
        sort_order=sort_order,
        is_active=1,
    )
    db.add(tv)
    db.commit()
    db.refresh(tv)
    invalidate_dim_cache()
    return tv


def update_dimension_value(
    db: Session,
    value_id: int,
    value: str | None = None,
    color_hex: str | None = None,
    image_path: str | None = None,
    sort_order: int | None = None,
    is_active: int | None = None,
    name_en: str | None = None,
    aliases: list[str] | None = None,
    parent_value_id: int | None = None,
) -> TagValue | None:
    tv = db.query(TagValue).filter(TagValue.id == value_id).first()
    if not tv:
        return None
    _guard_managed(db, tv.dimension_id)
    if value is not None:
        tv.value = value
    if color_hex is not None:
        tv.color_hex = color_hex
    if image_path is not None:
        tv.image_path = image_path
    if sort_order is not None:
        tv.sort_order = sort_order
    if is_active is not None:
        tv.is_active = is_active
    if name_en is not None:
        tv.name_en = name_en
    if aliases is not None:
        tv.aliases = aliases
    if parent_value_id is not None:
        tv.parent_value_id = parent_value_id
    db.commit()
    db.refresh(tv)
    invalidate_dim_cache()
    return tv


def delete_dimension_value(db: Session, value_id: int) -> bool:
    """删除标签值。返回是否成功。托管维度与仍有子级挂靠的值拒删。"""
    tv = db.query(TagValue).filter(TagValue.id == value_id).first()
    if not tv:
        return False
    _guard_managed(db, tv.dimension_id)
    children = db.query(TagValue).filter(TagValue.parent_value_id == value_id).count()
    if children:
        raise ManagedDimensionError(f"标签值[{tv.value}]仍有 {children} 个子级挂靠，先解除挂靠再删除")
    db.delete(tv)
    db.commit()
    invalidate_dim_cache()
    return True


# ── 维度 CRUD（管理员）───────────────────────────────────

def create_dimension(
    db: Session,
    name: str,
    label: str,
    is_single_select: int = 0,
    is_system: int = 0,
    is_required: int = 0,
    sort_order: int = 0,
) -> TagDimension:
    dim = TagDimension(
        name=name,
        label=label,
        is_single_select=is_single_select,
        is_system=is_system,
        is_required=is_required,
        sort_order=sort_order,
    )
    db.add(dim)
    db.commit()
    db.refresh(dim)
    invalidate_dim_cache()
    return dim


def update_dimension(
    db: Session,
    dim_id: int,
    label: str | None = None,
    is_single_select: int | None = None,
    is_required: int | None = None,
    sort_order: int | None = None,
    is_visible: int | None = None,
) -> TagDimension | None:
    dim = db.query(TagDimension).filter(TagDimension.id == dim_id).first()
    if not dim:
        return None
    if label is not None:
        dim.label = label
    if is_single_select is not None:
        dim.is_single_select = is_single_select
    if is_required is not None:
        dim.is_required = is_required
    if sort_order is not None:
        dim.sort_order = sort_order
    if is_visible is not None:
        dim.is_visible = is_visible
    db.commit()
    db.refresh(dim)
    invalidate_dim_cache()
    return dim


def delete_dimension(db: Session, dim_id: int) -> bool:
    """删除维度（仅限非系统维度）。返回是否成功。"""
    dim = db.query(TagDimension).filter(TagDimension.id == dim_id).first()
    if not dim or dim.is_system:
        return False
    db.delete(dim)
    db.commit()
    invalidate_dim_cache()
    return True
