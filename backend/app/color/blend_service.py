"""混合色 CRUD 服务"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.color.calc_service import blend_colors_lab
from app.color.models import ColorBlend, ColorBlendComponent, ColorPalette

logger = logging.getLogger("color.blend")


def list_blends(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    blend_type: Optional[str] = None,
    source: Optional[str] = None,
    keyword: Optional[str] = None,
    sort_field: str = "created_at",
    sort_order: str = "desc",
) -> dict:
    """混合色列表"""
    from sqlalchemy import desc as _desc
    q = db.query(ColorBlend)

    if blend_type:
        q = q.filter(ColorBlend.blend_type == blend_type)
    if source:
        q = q.filter(ColorBlend.source == source)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (ColorBlend.blend_code.ilike(like))
            | (ColorBlend.display_name.ilike(like))
            | (ColorBlend.brand_name.ilike(like))
        )

    SORT_MAP = {
        "blend_code": ColorBlend.blend_code,
        "display_name": ColorBlend.display_name,
        "blend_type": ColorBlend.blend_type,
        "created_at": ColorBlend.created_at,
    }
    sort_col = SORT_MAP.get(sort_field, ColorBlend.created_at)
    order_fn = _desc if sort_order == "desc" else lambda c: c

    total = q.count()
    items = (
        q.order_by(order_fn(sort_col))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


def get_blend(db: Session, blend_id: int) -> Optional[ColorBlend]:
    return db.query(ColorBlend).filter(ColorBlend.id == blend_id).first()


def get_blend_detail(db: Session, blend_id: int) -> Optional[ColorBlend]:
    """获取混合色详情（含成分和关联的 palette 信息）"""
    blend = get_blend(db, blend_id)
    if not blend:
        return None

    # 预加载 component 的 palette 信息
    components = []
    for c in blend.components:
        palette = db.query(ColorPalette).filter(ColorPalette.id == c.palette_id).first()
        components.append({
            "id": c.id,
            "palette_id": c.palette_id,
            "position": c.position,
            "weight": float(c.weight),
            "sort_order": c.sort_order,
            "palette": {
                "id": palette.id,
                "industry_code": palette.industry_code,
                "display_name": palette.display_name,
                "hex_code": palette.hex_code,
            } if palette else None,
        })

    return blend, components


def create_blend(db: Session, data: dict) -> ColorBlend:
    """新增混合色，自动计算综合 HEX"""
    components_data = data.pop("components", [])
    if not components_data:
        raise HTTPException(status_code=400, detail="混合色成分不能为空")

    # 验证成分权重总和
    total_weight = sum(c.get("weight", 0) for c in components_data)
    if abs(total_weight - 1.0) > 0.02:
        raise HTTPException(status_code=400, detail=f"混合权重总和必须等于1，当前: {total_weight}")

    # 验证 palette_id 存在
    palette_ids = [c["palette_id"] for c in components_data]
    existing = db.query(ColorPalette).filter(ColorPalette.id.in_(palette_ids)).all()
    existing_ids = {p.id for p in existing}
    missing = set(palette_ids) - existing_ids
    if missing:
        raise HTTPException(status_code=400, detail=f"基础色号不存在: {missing}")

    # 计算综合 HEX
    blend_input = []
    for c in components_data:
        palette = next(p for p in existing if p.id == c["palette_id"])
        blend_input.append({"hex": palette.hex_code, "weight": c["weight"]})

    result = blend_colors_lab(blend_input)

    # 创建混合色主记录
    blend = ColorBlend(
        **data,
        computed_hex=result["hex"],
        computed_lab_l=result["lab"][0],
        computed_lab_a=result["lab"][1],
        computed_lab_b=result["lab"][2],
    )
    db.add(blend)
    db.flush()  # 获取 blend.id

    # 创建成分关联
    for i, c in enumerate(components_data):
        comp = ColorBlendComponent(
            blend_id=blend.id,
            palette_id=c["palette_id"],
            position=c.get("position", "even"),
            weight=c["weight"],
            sort_order=c.get("sort_order", i),
        )
        db.add(comp)

    db.commit()
    db.refresh(blend)
    return blend


def update_blend(db: Session, blend_id: int, data: dict) -> ColorBlend:
    blend = get_blend(db, blend_id)
    if not blend:
        raise HTTPException(status_code=404, detail="混合色不存在")

    components_data = data.pop("components", None)

    # 更新基础字段
    for key, val in data.items():
        if val is not None and hasattr(blend, key):
            setattr(blend, key, val)

    # 如果提供了成分，重新计算
    if components_data:
        # 删除旧成分
        db.query(ColorBlendComponent).filter(
            ColorBlendComponent.blend_id == blend_id
        ).delete(synchronize_session=False)

        # 验证
        total_weight = sum(c.get("weight", 0) for c in components_data)
        if abs(total_weight - 1.0) > 0.02:
            raise HTTPException(status_code=400, detail=f"混合权重总和必须等于1，当前: {total_weight}")

        palette_ids = [c["palette_id"] for c in components_data]
        existing = db.query(ColorPalette).filter(ColorPalette.id.in_(palette_ids)).all()
        existing_ids = {p.id for p in existing}
        missing = set(palette_ids) - existing_ids
        if missing:
            raise HTTPException(status_code=400, detail=f"基础色号不存在: {missing}")

        # 重新计算
        blend_input = []
        for c in components_data:
            palette = next(p for p in existing if p.id == c["palette_id"])
            blend_input.append({"hex": palette.hex_code, "weight": c["weight"]})
        result = blend_colors_lab(blend_input)

        blend.computed_hex = result["hex"]
        blend.computed_lab_l = result["lab"][0]
        blend.computed_lab_a = result["lab"][1]
        blend.computed_lab_b = result["lab"][2]

        # 创建新成分
        for i, c in enumerate(components_data):
            comp = ColorBlendComponent(
                blend_id=blend_id,
                palette_id=c["palette_id"],
                position=c.get("position", "even"),
                weight=c["weight"],
                sort_order=c.get("sort_order", i),
            )
            db.add(comp)

    db.commit()
    db.refresh(blend)
    return blend


def delete_blend(db: Session, blend_id: int) -> None:
    blend = get_blend(db, blend_id)
    if not blend:
        raise HTTPException(status_code=404, detail="混合色不存在")

    db.delete(blend)
    db.commit()


def get_blend_filter_options(db: Session) -> dict:
    """获取混合色筛选维度"""
    types = [r[0] for r in db.query(ColorBlend.blend_type).distinct().all() if r[0]]
    sources = [r[0] for r in db.query(ColorBlend.source).distinct().all() if r[0]]
    return {
        "blend_types": sorted(types),
        "sources": sorted(sources),
    }
