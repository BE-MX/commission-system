"""发色数字化 — API 路由

权限码:
- color:read  — 查看色板 / 趋势 / 色板图
- color:write — 编辑色号 / 混合色 / 生成色板图
- color:admin — 管理竞品监控 / 趋势数据源
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import require_permission
from app.core.response import ok as _ok
from app.color import (
    blend_service,
    calc_service,
    palette_service,
    swatch_service,
    trend_service,
)
from app.color.schemas import (
    BatchSwatchRequest,
    BlendCreate,
    BlendUpdate,
    ConvertRequest,
    DeltaERequest,
    MatchLeshineRequest,
    PantoneMatchRequest,
    PaletteCreate,
    PaletteUpdate,
    SwatchGenerateRequest,
)

logger = logging.getLogger("color.router")
router = APIRouter()


# ═════════════════════════════════════════════════════════
#  色号 CRUD
# ═════════════════════════════════════════════════════════


@router.get("/colors")
def get_colors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    color_family: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    luminance_level: Optional[str] = Query(None),
    is_leshine_stock: Optional[bool] = Query(None),
    keyword: Optional[str] = Query(None),
    sort_field: str = Query("color_family"),
    sort_order: str = Query("asc"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """色号列表（支持多维筛选）"""
    result = palette_service.list_palettes(
        db=db,
        page=page,
        page_size=page_size,
        color_family=color_family,
        source=source,
        luminance_level=luminance_level,
        is_leshine_stock=is_leshine_stock,
        keyword=keyword,
        sort_field=sort_field,
        sort_order=sort_order,
    )
    return _ok(result)


@router.get("/colors/{palette_id}")
def get_color_detail(
    palette_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """色号详情"""
    palette = palette_service.get_palette(db, palette_id)
    if not palette:
        raise HTTPException(status_code=404, detail="色号不存在")
    return _ok(palette)


@router.post("/colors")
def create_color(
    req: PaletteCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:write")),
):
    """新增色号"""
    palette = palette_service.create_palette(db, req.model_dump(exclude_unset=True))
    return _ok(palette, message="创建成功", code=201)


@router.put("/colors/{palette_id}")
def update_color(
    palette_id: int,
    req: PaletteUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:write")),
):
    """编辑色号"""
    palette = palette_service.update_palette(db, palette_id, req.model_dump(exclude_unset=True))
    return _ok(palette, message="更新成功")


@router.delete("/colors/{palette_id}")
def delete_color(
    palette_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:admin")),
):
    """删除色号"""
    palette_service.delete_palette(db, palette_id)
    return _ok(None, message="删除成功")


@router.get("/colors/filter-options")
def get_color_filter_options(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """色号筛选维度可选值"""
    return _ok(palette_service.get_palette_filter_options(db))


# ═════════════════════════════════════════════════════════
#  混合色 CRUD
# ═════════════════════════════════════════════════════════


@router.get("/blends")
def get_blends(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    blend_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    sort_field: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """混合色列表"""
    result = blend_service.list_blends(
        db=db, page=page, page_size=page_size,
        blend_type=blend_type, source=source, keyword=keyword,
        sort_field=sort_field, sort_order=sort_order,
    )
    return _ok(result)


@router.get("/blends/{blend_id}")
def get_blend_detail(
    blend_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """混合色详情（含成分）"""
    result = blend_service.get_blend_detail(db, blend_id)
    if not result:
        raise HTTPException(status_code=404, detail="混合色不存在")
    blend, components = result
    return _ok({
        "id": blend.id,
        "blend_code": blend.blend_code,
        "display_name": blend.display_name,
        "display_name_en": blend.display_name_en,
        "blend_type": blend.blend_type,
        "computed_hex": blend.computed_hex,
        "computed_lab_l": float(blend.computed_lab_l) if blend.computed_lab_l else None,
        "computed_lab_a": float(blend.computed_lab_a) if blend.computed_lab_a else None,
        "computed_lab_b": float(blend.computed_lab_b) if blend.computed_lab_b else None,
        "source": blend.source,
        "brand_name": blend.brand_name,
        "components": components,
        "created_at": blend.created_at.isoformat() if blend.created_at else None,
        "updated_at": blend.updated_at.isoformat() if blend.updated_at else None,
    })


@router.post("/blends")
def create_blend(
    req: BlendCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:write")),
):
    """新增混合色"""
    blend = blend_service.create_blend(db, req.model_dump())
    return _ok(blend, message="创建成功", code=201)


@router.put("/blends/{blend_id}")
def update_blend(
    blend_id: int,
    req: BlendUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:write")),
):
    """编辑混合色"""
    blend = blend_service.update_blend(db, blend_id, req.model_dump(exclude_unset=True))
    return _ok(blend, message="更新成功")


@router.delete("/blends/{blend_id}")
def delete_blend(
    blend_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:admin")),
):
    """删除混合色"""
    blend_service.delete_blend(db, blend_id)
    return _ok(None, message="删除成功")


@router.get("/blends/filter-options")
def get_blend_filter_options(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """混合色筛选维度"""
    return _ok(blend_service.get_blend_filter_options(db))


# ═════════════════════════════════════════════════════════
#  色彩计算 API
# ═════════════════════════════════════════════════════════


@router.post("/color-calc/convert")
def color_calc_convert(
    req: ConvertRequest,
    _user: dict = Depends(require_permission("color:read")),
):
    """色彩格式转换：输入任意格式，返回全格式"""
    try:
        result = calc_service.hex_to_all_formats(req.input)
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/color-calc/blend")
def color_calc_blend(
    req: dict,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """混色计算：输入色号+权重，返回混合结果"""
    components = req.get("components", [])
    if not components:
        raise HTTPException(status_code=400, detail="components is required")

    # 支持 color_id 或 hex 输入
    blend_input = []
    for c in components:
        if "color_id" in c:
            from app.color.models import ColorPalette
            palette = db.query(ColorPalette).filter(ColorPalette.id == c["color_id"]).first()
            if not palette:
                raise HTTPException(status_code=400, detail=f"色号不存在: {c['color_id']}")
            hex_code = palette.hex_code
        else:
            hex_code = c.get("hex", "")
        blend_input.append({"hex": hex_code, "weight": c.get("weight", 1.0)})

    result = calc_service.blend_colors_lab(blend_input)
    pantone = calc_service.find_nearest_pantone(result["hex"], db)
    return _ok({
        "computed_hex": result["hex"],
        "lab": result["lab"],
        "nearest_pantone": pantone,
    })


@router.post("/color-calc/delta-e")
def color_calc_delta_e(
    req: DeltaERequest,
    _user: dict = Depends(require_permission("color:read")),
):
    """计算两色 ΔE2000 色差"""
    try:
        de = calc_service.calculate_delta_e(req.color_a, req.color_b)
        return _ok(calc_service.delta_e_assessment(de))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/color-calc/pantone-match")
def color_calc_pantone_match(
    req: PantoneMatchRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """Pantone 最近匹配"""
    result = calc_service.find_nearest_pantone(req.hex, db)
    if not result:
        return _ok(None, message="Pantone 库为空")
    return _ok(result)


@router.post("/color-calc/match-leshine")
def color_calc_match_leshine(
    req: MatchLeshineRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """匹配莱莎最近色号"""
    result = calc_service.find_nearest_palette(req.hex, db)
    if not result:
        return _ok(None, message="色库为空")
    return _ok({"nearest": result})


@router.post("/color-calc/extract-from-image")
def color_extract_from_image(
    file: UploadFile = File(...),
    k: int = Query(5, ge=1, le=10),
    _user: dict = Depends(require_permission("color:read")),
):
    """上传图片，提取 Top-K 主色调"""
    import os
    import tempfile

    suffix = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        colors = calc_service.extract_dominant_colors(tmp_path, k=k)
        return _ok({"colors": colors})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        os.unlink(tmp_path)


# ═════════════════════════════════════════════════════════
#  色板图生成
# ═════════════════════════════════════════════════════════


@router.post("/swatch/generate")
def generate_swatch(
    req: SwatchGenerateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:write")),
):
    """触发生成色板图任务"""
    data = {"color_id": req.color_id, "blend_id": req.blend_id, "style": req.style}
    swatch = swatch_service.create_swatch_task(db, data)
    return _ok({"task_id": swatch.id, "status": swatch.status}, code=201)


@router.get("/swatch/{task_id}/status")
def get_swatch_status(
    task_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """查询生成任务状态"""
    swatch = swatch_service.get_swatch(db, task_id)
    if not swatch:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _ok({
        "id": swatch.id,
        "status": swatch.status,
        "target_hex": swatch.target_hex,
        "actual_hex": swatch.actual_hex,
        "delta_e": float(swatch.delta_e) if swatch.delta_e else None,
        "pass_check": bool(swatch.pass_check) if swatch.pass_check is not None else None,
        "retry_count": swatch.retry_count,
        "image_url": swatch.image_url,
    })


@router.post("/swatch/batch-generate")
def batch_generate_swatch(
    req: BatchSwatchRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:write")),
):
    """批量创建生成任务"""
    tasks = swatch_service.batch_generate_swatch(db, req.color_ids, req.style)
    return _ok({
        "task_count": len(tasks),
        "task_ids": [t.id for t in tasks],
    }, code=201)


@router.post("/swatch/{task_id}/verify")
def verify_swatch(
    task_id: int,
    db: Session = Depends(get_db),
    # 触发校验会更新任务记录，属写操作（2026-07-12 修正读写错位）
    _user: dict = Depends(require_permission("color:write")),
):
    """手动触发色差校验"""
    result = swatch_service.verify_swatch_task(db, task_id)
    return _ok(result)


@router.get("/swatches")
def get_swatches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    palette_id: Optional[int] = Query(None),
    blend_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """色板图生成记录列表"""
    result = swatch_service.list_swatches(
        db=db, page=page, page_size=page_size,
        status=status, palette_id=palette_id, blend_id=blend_id,
    )
    return _ok(result)


# ═════════════════════════════════════════════════════════
#  趋势数据（P2 预留）
# ═════════════════════════════════════════════════════════


@router.get("/color-trends/overview")
def get_trend_overview(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """色彩趋势概览"""
    result = trend_service.get_trend_overview(db)
    return _ok(result)


@router.get("/color-trends/history")
def get_trend_history(
    color_family: Optional[str] = Query(None),
    data_source: Optional[str] = Query(None),
    period_type: str = Query("weekly"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """历史趋势"""
    from datetime import date
    s = date.fromisoformat(start_date) if start_date else None
    e = date.fromisoformat(end_date) if end_date else None
    result = trend_service.get_trend_history(db, color_family, data_source, period_type, s, e)
    return _ok(result)


@router.get("/color-trends/prediction")
def get_trend_prediction(
    horizon: int = Query(30, ge=7, le=90),
    top_n: int = Query(5, ge=1, le=10),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """30天预测（当前为简单移动平均占位）"""
    result = trend_service.get_trend_prediction(db, horizon, top_n)
    return _ok(result)


@router.get("/color-trends/social-colors")
def get_social_colors(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("color:read")),
):
    """社媒色彩快照"""
    result = trend_service.get_trend_overview(db)
    return _ok(result)
