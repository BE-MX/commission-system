"""报表中心 — API 路由

权限码:
- report:read   — 查看报表 / 获取数据
- report:design — 设计/编辑模板
- report:admin  — 管理模板（删除/启停）
"""

from __future__ import annotations

import io
import logging
from pathlib import Path as FilePath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import require_permission
from app.report.models import ReportTemplate, ReportTemplateVersion
from app.report.schemas import (
    ReportTemplateCreate,
    ReportTemplateDetailResponse,
    ReportTemplateResponse,
    ReportTemplateUpdate,
    ReportTemplateVersionResponse,
)
from app.report.data_service import get_report_data

logger = logging.getLogger("report")
router = APIRouter()

# Jinja2 环境
_TEMPLATES_DIR = FilePath(__file__).parent / "templates"
_ASSETS_DIR = _TEMPLATES_DIR / "assets"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


def _load_middle_punch_image_data_uri() -> str:
    """读取中间打孔要求图，返回 base64 data URI（懒加载并缓存）。"""
    cache = getattr(_load_middle_punch_image_data_uri, "_cache", None)
    if cache is not None:
        return cache
    import base64
    img_path = _ASSETS_DIR / "middle_punch_requirement.jpg"
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        data_uri = f"data:image/jpeg;base64,{b64}"
    except FileNotFoundError:
        logger.warning(f"中间打孔要求图未找到: {img_path}")
        data_uri = ""
    _load_middle_punch_image_data_uri._cache = data_uri  # type: ignore[attr-defined]
    return data_uri


def _ok(data, message: str = "ok", code: int = 200):
    return {"code": code, "message": message, "data": data}


def _get_user_id(user: dict) -> int:
    uid = int(user.get("sub") or user.get("user_id") or 0)
    if not uid:
        raise HTTPException(status_code=401, detail="无法识别当前用户")
    return uid


# ── 模板 CRUD ──────────────────────────────────────────────


@router.get("/templates")
def list_templates(
    _user: dict = Depends(require_permission("report:read")),
    db: Session = Depends(get_db),
):
    """模板列表（不含 content，轻量）"""
    templates = (
        db.query(ReportTemplate)
        .filter(ReportTemplate.status >= 0)
        .order_by(ReportTemplate.report_code)
        .all()
    )
    return _ok([ReportTemplateResponse.model_validate(t).model_dump() for t in templates])


@router.get("/templates/{report_code}")
def get_template(
    report_code: str,
    _user: dict = Depends(require_permission("report:read")),
    db: Session = Depends(get_db),
):
    """获取模板详情（含 .mrt 内容）"""
    t = db.query(ReportTemplate).filter(ReportTemplate.report_code == report_code).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {report_code}")
    return _ok(ReportTemplateDetailResponse.model_validate(t).model_dump())


@router.post("/templates")
def create_template(
    body: ReportTemplateCreate,
    _user: dict = Depends(require_permission("report:design")),
    db: Session = Depends(get_db),
):
    """创建模板"""
    existing = db.query(ReportTemplate).filter(ReportTemplate.report_code == body.report_code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"模板编码已存在: {body.report_code}")

    t = ReportTemplate(
        report_code=body.report_code,
        name=body.name,
        description=body.description,
        template_content=body.template_content,
        version=1,
        status=1,
        created_by=_get_user_id(_user),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _ok(ReportTemplateResponse.model_validate(t).model_dump(), code=201)


@router.put("/templates/{report_code}")
def update_template(
    report_code: str,
    body: ReportTemplateUpdate,
    _user: dict = Depends(require_permission("report:design")),
    db: Session = Depends(get_db),
):
    """更新模板（更新内容时 version 自增）"""
    t = db.query(ReportTemplate).filter(ReportTemplate.report_code == report_code).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {report_code}")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    # 如果更新了 template_content，版本号自增 + 保存旧版本快照
    if "template_content" in update_data:
        # 快照当前版本
        snapshot = ReportTemplateVersion(
            template_id=t.id,
            version=t.version,
            template_content=t.template_content,
            change_summary=body.change_summary,
            created_by=_get_user_id(_user),
        )
        db.add(snapshot)
        t.version = (t.version or 0) + 1

    for key, value in update_data.items():
        setattr(t, key, value)

    t.updated_by = _get_user_id(_user)
    db.commit()
    db.refresh(t)
    return _ok(ReportTemplateResponse.model_validate(t).model_dump())


@router.delete("/templates/{report_code}")
def delete_template(
    report_code: str,
    _user: dict = Depends(require_permission("report:admin")),
    db: Session = Depends(get_db),
):
    """软删除模板（status=-1）"""
    t = db.query(ReportTemplate).filter(ReportTemplate.report_code == report_code).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {report_code}")

    t.status = -1
    t.updated_by = _get_user_id(_user)
    db.commit()
    return _ok(None, message="已删除")


# ── 模板版本历史 ──────────────────────────────────────────


@router.get("/templates/{report_code}/versions")
def list_template_versions(
    report_code: str,
    _user: dict = Depends(require_permission("report:design")),
    db: Session = Depends(get_db),
):
    """获取模板版本历史列表"""
    t = db.query(ReportTemplate).filter(ReportTemplate.report_code == report_code).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {report_code}")

    versions = (
        db.query(ReportTemplateVersion)
        .filter(ReportTemplateVersion.template_id == t.id)
        .order_by(ReportTemplateVersion.version.desc())
        .all()
    )
    return _ok([ReportTemplateVersionResponse.model_validate(v).model_dump() for v in versions])


@router.get("/templates/{report_code}/versions/{version}")
def get_template_version(
    report_code: str,
    version: int,
    _user: dict = Depends(require_permission("report:design")),
    db: Session = Depends(get_db),
):
    """获取指定版本的模板内容"""
    t = db.query(ReportTemplate).filter(ReportTemplate.report_code == report_code).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {report_code}")

    v = (
        db.query(ReportTemplateVersion)
        .filter(
            ReportTemplateVersion.template_id == t.id,
            ReportTemplateVersion.version == version,
        )
        .first()
    )
    if not v:
        raise HTTPException(status_code=404, detail=f"版本不存在: v{version}")

    return _ok({
        "id": v.id,
        "template_id": v.template_id,
        "version": v.version,
        "template_content": v.template_content,
        "change_summary": v.change_summary,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    })


@router.post("/templates/{report_code}/rollback/{version}")
def rollback_template(
    report_code: str,
    version: int,
    _user: dict = Depends(require_permission("report:design")),
    db: Session = Depends(get_db),
):
    """回滚模板到指定版本"""
    t = db.query(ReportTemplate).filter(ReportTemplate.report_code == report_code).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {report_code}")

    v = (
        db.query(ReportTemplateVersion)
        .filter(
            ReportTemplateVersion.template_id == t.id,
            ReportTemplateVersion.version == version,
        )
        .first()
    )
    if not v:
        raise HTTPException(status_code=404, detail=f"版本不存在: v{version}")

    # 先快照当前版本
    snapshot = ReportTemplateVersion(
        template_id=t.id,
        version=t.version,
        template_content=t.template_content,
        change_summary=f"回滚到 v{version}",
        created_by=_get_user_id(_user),
    )
    db.add(snapshot)

    # 恢复目标版本的内容
    t.template_content = v.template_content
    t.version = (t.version or 0) + 1
    t.updated_by = _get_user_id(_user)
    db.commit()
    db.refresh(t)
    return _ok(ReportTemplateResponse.model_validate(t).model_dump(), message=f"已回滚到 v{version}")


@router.patch("/templates/{report_code}/status")
def toggle_template_status(
    report_code: str,
    body: dict,
    _user: dict = Depends(require_permission("report:admin")),
    db: Session = Depends(get_db),
):
    """切换模板启用/禁用状态"""
    t = db.query(ReportTemplate).filter(ReportTemplate.report_code == report_code).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {report_code}")

    new_status = body.get("status")
    if new_status not in (0, 1):
        raise HTTPException(status_code=400, detail="status 必须为 0 或 1")

    t.status = new_status
    t.updated_by = _get_user_id(_user)
    db.commit()
    return _ok(ReportTemplateResponse.model_validate(t).model_dump())


# ── 报表数据 ───────────────────────────────────────────────


@router.get("/data/{report_code}")
def get_data(
    report_code: str,
    order_no: Optional[str] = Query(None),
    _user: dict = Depends(require_permission("report:read")),
    db: Session = Depends(get_db),
):
    """获取报表数据 JSON（前端传参 → 后端查询 → 返回结构化 JSON 供 Stimulsoft regData）"""
    # 检查模板是否存在且启用
    t = db.query(ReportTemplate).filter(
        ReportTemplate.report_code == report_code,
        ReportTemplate.status == 1,
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"报表模板不存在或未启用: {report_code}")

    try:
        params = {}
        if order_no:
            params["order_no"] = order_no

        data = get_report_data(db, report_code, params)
        return _ok(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取报表数据失败: report_code={report_code}, params={params}, error={e}")
        raise HTTPException(status_code=500, detail="获取报表数据失败")


# ── HTML 打印（方案 C：Jinja2 渲染）────────────────────────


@router.get("/print/production-order", response_class=HTMLResponse)
def print_production_order(
    order_no: str = Query(..., description="生产订单号"),
    reviewer: str = Query("", description="审核人姓名（当前打印用户）"),
    db: Session = Depends(get_db),
):
    """生产订单打印页（HTML，无需登录，供打印窗口直接访问）"""
    from datetime import date
    data = get_report_data(db, "production_order_print", {"order_no": order_no})

    if not data.get("header"):
        raise HTTPException(status_code=404, detail=f"订单不存在: {order_no}")

    data["header"]["reviewer_name"] = reviewer
    data["header"]["print_date"] = date.today().strftime("%Y-%m-%d")

    # 任一明细 model 含「中间打孔」时注入要求图（base64 data URI）
    if data.get("has_middle_punch"):
        data["middle_punch_image"] = _load_middle_punch_image_data_uri()
    else:
        data["middle_punch_image"] = ""

    template = _jinja_env.get_template("production_order_print.html")
    html = template.render(**data)
    return HTMLResponse(content=html)


@router.get("/export/production-order")
def export_production_order_docx(
    order_no: str = Query(..., description="生产订单号"),
    page_size: str = Query("A4", description="页面尺寸：A4/A3/A5/B5"),
    orientation: str = Query("portrait", description="方向：portrait/landscape"),
    reviewer: str = Query("", description="审核人姓名（当前导出用户）"),
    db: Session = Depends(get_db),
):
    """导出生产订单为 Word (.docx) 文件"""
    try:
        from app.report.docx_export import generate_production_order_docx, PAGE_SIZES
    except ImportError:
        raise HTTPException(status_code=500, detail="python-docx 未安装，请执行 pip install python-docx")

    if page_size.upper() not in PAGE_SIZES:
        raise HTTPException(status_code=400, detail=f"不支持的页面尺寸: {page_size}，可选: {', '.join(PAGE_SIZES)}")
    if orientation not in ("portrait", "landscape"):
        raise HTTPException(status_code=400, detail="方向必须为 portrait 或 landscape")

    data = get_report_data(db, "production_order_print", {"order_no": order_no})
    if not data.get("header"):
        raise HTTPException(status_code=404, detail=f"订单不存在: {order_no}")

    # 签字区补充字段（与 HTML 打印端点保持一致）
    from datetime import date
    data["header"]["reviewer_name"] = reviewer
    data["header"]["print_date"] = date.today().strftime("%Y-%m-%d")

    try:
        docx_bytes = generate_production_order_docx(
            data,
            page_size=page_size.upper(),
            orientation=orientation,
        )
    except Exception as e:
        logger.error(f"导出 Word 失败: order_no={order_no}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出 Word 失败: {e}")

    filename = f"production_order_{order_no}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
