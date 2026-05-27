"""色号 CRUD 服务"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.color.calc_service import compute_color_data, find_nearest_pantone
from app.color.models import ColorPalette

logger = logging.getLogger("color.palette")


def list_palettes(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    color_family: Optional[str] = None,
    source: Optional[str] = None,
    luminance_level: Optional[str] = None,
    is_leshine_stock: Optional[bool] = None,
    keyword: Optional[str] = None,
    sort_field: str = "color_family",
    sort_order: str = "asc",
) -> dict:
    """色号列表（支持筛选）"""
    from sqlalchemy import desc as _desc
    q = db.query(ColorPalette)

    if color_family:
        q = q.filter(ColorPalette.color_family == color_family)
    if source:
        q = q.filter(ColorPalette.source == source)
    if luminance_level:
        q = q.filter(ColorPalette.luminance_level == luminance_level)
    if is_leshine_stock is not None:
        q = q.filter(ColorPalette.is_leshine_stock == (1 if is_leshine_stock else 0))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (ColorPalette.industry_code.ilike(like))
            | (ColorPalette.display_name.ilike(like))
            | (ColorPalette.display_name_en.ilike(like))
            | (ColorPalette.hex_code.ilike(like))
        )

    SORT_MAP = {
        "industry_code": ColorPalette.industry_code,
        "display_name": ColorPalette.display_name,
        "hex_code": ColorPalette.hex_code,
        "color_family": ColorPalette.color_family,
        "luminance_level": ColorPalette.luminance_level,
        "created_at": ColorPalette.created_at,
    }
    sort_col = SORT_MAP.get(sort_field, ColorPalette.color_family)
    order_fn = _desc if sort_order == "desc" else lambda c: c

    total = q.count()
    items = (
        q.order_by(order_fn(sort_col), ColorPalette.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": items}


def get_palette(db: Session, palette_id: int) -> Optional[ColorPalette]:
    return db.query(ColorPalette).filter(ColorPalette.id == palette_id).first()


def create_palette(db: Session, data: dict) -> ColorPalette:
    """新增色号，自动计算 RGB/LAB/HSL，匹配 Pantone"""
    hex_code = data.get("hex_code", "")
    if not hex_code:
        raise HTTPException(status_code=400, detail="hex_code is required")

    # 自动计算色彩数值
    computed = compute_color_data(hex_code)

    # 自动匹配 Pantone
    pantone_match = find_nearest_pantone(hex_code, db)
    if pantone_match:
        data["pantone_tcx"] = pantone_match["pantone_code"]
        data["pantone_delta_e"] = pantone_match["delta_e"]

    # 合并自动计算值
    for key in ["rgb_r", "rgb_g", "rgb_b", "lab_l", "lab_a", "lab_b_val", "hsl_h", "hsl_s", "hsl_l"]:
        if key not in data or data.get(key) is None:
            data[key] = computed.get(key)

    palette = ColorPalette(**data)
    db.add(palette)
    db.commit()
    db.refresh(palette)
    return palette


def update_palette(db: Session, palette_id: int, data: dict) -> ColorPalette:
    palette = get_palette(db, palette_id)
    if not palette:
        raise HTTPException(status_code=404, detail="色号不存在")

    # 如果 HEX 变了，重新计算
    new_hex = data.get("hex_code")
    if new_hex and new_hex.upper() != palette.hex_code.upper():
        computed = compute_color_data(new_hex)
        for key, val in computed.items():
            data.setdefault(key, val)
        # 重新匹配 Pantone
        pantone_match = find_nearest_pantone(new_hex, db)
        if pantone_match:
            data["pantone_tcx"] = pantone_match["pantone_code"]
            data["pantone_delta_e"] = pantone_match["delta_e"]

    for key, val in data.items():
        if val is not None and hasattr(palette, key):
            setattr(palette, key, val)

    db.commit()
    db.refresh(palette)
    return palette


def delete_palette(db: Session, palette_id: int) -> None:
    palette = get_palette(db, palette_id)
    if not palette:
        raise HTTPException(status_code=404, detail="色号不存在")

    # 检查是否被混合色引用
    count = palette.blend_components.count()
    if count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该色号被 {count} 个混合色引用，无法删除",
        )

    db.delete(palette)
    db.commit()


def get_palette_filter_options(db: Session) -> dict:
    """获取筛选维度可选值"""
    families = [
        r[0] for r in db.query(ColorPalette.color_family).distinct().all() if r[0]
    ]
    sources = [
        r[0] for r in db.query(ColorPalette.source).distinct().all() if r[0]
    ]
    luminance_levels = [
        r[0]
        for r in db.query(ColorPalette.luminance_level).distinct().all()
        if r[0]
    ]
    return {
        "color_families": sorted(families),
        "sources": sorted(sources),
        "luminance_levels": sorted(luminance_levels),
    }
