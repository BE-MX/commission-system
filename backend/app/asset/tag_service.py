"""素材管理 — 标签维度/值 CRUD + 种子数据"""

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
    """初始化内置标签维度。幂等，已有则跳过。"""
    for dim_data in DEFAULT_DIMENSIONS:
        existing = db.query(TagDimension).filter(TagDimension.name == dim_data["name"]).first()
        if existing:
            continue
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

def list_dimensions(db: Session) -> list[TagDimension]:
    """所有标签维度（含标签值）"""
    return (
        db.query(TagDimension)
        .order_by(TagDimension.sort_order)
        .all()
    )


def get_dimension(db: Session, dim_id: int) -> TagDimension | None:
    return db.query(TagDimension).filter(TagDimension.id == dim_id).first()


# ── 标签值 CRUD ─────────────────────────────────────────

def create_dimension_value(
    db: Session,
    dimension_id: int,
    value: str,
    color_hex: str | None = None,
    sort_order: int = 0,
) -> TagValue:
    tv = TagValue(
        dimension_id=dimension_id,
        value=value,
        color_hex=color_hex,
        sort_order=sort_order,
        is_active=1,
    )
    db.add(tv)
    db.commit()
    db.refresh(tv)
    return tv


def update_dimension_value(
    db: Session,
    value_id: int,
    value: str | None = None,
    color_hex: str | None = None,
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
    if sort_order is not None:
        tv.sort_order = sort_order
    if is_active is not None:
        tv.is_active = is_active
    db.commit()
    db.refresh(tv)
    return tv


def delete_dimension_value(db: Session, value_id: int) -> bool:
    """删除标签值。返回是否成功。"""
    tv = db.query(TagValue).filter(TagValue.id == value_id).first()
    if not tv:
        return False
    db.delete(tv)
    db.commit()
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
    if dim.is_system:
        # 系统内置维度只允许修改 label/sort_order
        if label is not None:
            dim.label = label
        if sort_order is not None:
            dim.sort_order = sort_order
    else:
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
    return dim


def delete_dimension(db: Session, dim_id: int) -> bool:
    """删除维度（仅限非系统维度）。返回是否成功。"""
    dim = db.query(TagDimension).filter(TagDimension.id == dim_id).first()
    if not dim or dim.is_system:
        return False
    db.delete(dim)
    db.commit()
    return True
