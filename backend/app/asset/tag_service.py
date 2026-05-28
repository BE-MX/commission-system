"""素材管理 — 标签维度/值 CRUD + 种子数据"""

import threading
import time

from sqlalchemy.orm import Session

from app.asset.models import TagDimension, TagValue

# ── 内置维度定义 ───────────────────────────────────────

DEFAULT_DIMENSIONS = [
    {"name": "asset_type",     "label": "素材类型",  "is_single_select": 1, "is_system": 1, "is_required": 1, "sort_order": 1,
     "values": ["产品图", "场景图", "证书", "工艺流程", "活动图", "教程", "营销物料", "价格表"]},
    {"name": "product_line",   "label": "产品线",    "is_single_select": 1, "is_system": 1, "is_required": 1, "sort_order": 2,
     "values": ["天才发帘", "贴发", "接发", "打孔发帘", "其他"]},
    {"name": "product_model",  "label": "产品型号",  "is_single_select": 0, "is_system": 1, "is_required": 0, "sort_order": 3,
     "values": ["K-Tip", "V-Tip", "U-Tip", "I-Tip", "Flat Tip", "Tape-in", "Clip-in"]},
    {"name": "color",          "label": "颜色",      "is_single_select": 0, "is_system": 1, "is_required": 0, "sort_order": 4,
     "values": ["#1", "#1B", "#2", "#4", "#613", "Balayage", "Ombre", "Ash Blonde", "Copper"]},
    {"name": "length",         "label": "长度",      "is_single_select": 0, "is_system": 1, "is_required": 0, "sort_order": 5,
     "values": ["12\"", "14\"", "16\"", "18\"", "20\"", "22\"", "24\""]},
    {"name": "weight",         "label": "克重",      "is_single_select": 0, "is_system": 1, "is_required": 0, "sort_order": 6,
     "values": ["50g", "100g", "150g", "200g", "220g"]},
    {"name": "craft",          "label": "工艺",      "is_single_select": 0, "is_system": 1, "is_required": 0, "sort_order": 7,
     "values": ["保鳞", "低温慢漂", "Remy", "Virgin"]},
    {"name": "scene",          "label": "用途场景",  "is_single_select": 0, "is_system": 1, "is_required": 0, "sort_order": 8,
     "values": ["阿里巴巴主图", "A+页面", "详情页", "社媒推广", "展会", "客户报价"]},
    {"name": "market",         "label": "市场地区",  "is_single_select": 0, "is_system": 1, "is_required": 0, "sort_order": 9,
     "values": ["美国", "英国", "德国", "澳大利亚", "通用"]},
]


def seed_default_dimensions(db: Session) -> None:
    """初始化内置标签维度。仅在表为空时创建，后续由用户管理。"""
    if db.query(TagDimension).first() is not None:
        return

    for dim_data in DEFAULT_DIMENSIONS:
        dim = TagDimension(
            name=dim_data["name"],
            label=dim_data["label"],
            is_single_select=dim_data["is_single_select"],
            is_system=dim_data["is_system"],
            is_required=dim_data["is_required"],
            sort_order=dim_data["sort_order"],
        )
        db.add(dim)
        db.flush()

        for i, val in enumerate(dim_data["values"]):
            tv = TagValue(
                dimension_id=dim.id,
                value=val,
                sort_order=i,
                is_active=1,
            )
            db.add(tv)
    db.commit()


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
        "sort_order": d.sort_order,
        "values": [{
            "id": v.id,
            "dimension_id": v.dimension_id,
            "value": v.value,
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

def create_dimension_value(
    db: Session,
    dimension_id: int,
    value: str,
    color_hex: str | None = None,
    image_path: str | None = None,
    sort_order: int = 0,
) -> TagValue:
    tv = TagValue(
        dimension_id=dimension_id,
        value=value,
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
) -> TagValue | None:
    tv = db.query(TagValue).filter(TagValue.id == value_id).first()
    if not tv:
        return None
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
    db.commit()
    db.refresh(tv)
    invalidate_dim_cache()
    return tv


def delete_dimension_value(db: Session, value_id: int) -> bool:
    """删除标签值。返回是否成功。"""
    tv = db.query(TagValue).filter(TagValue.id == value_id).first()
    if not tv:
        return False
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
