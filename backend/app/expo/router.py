"""FastAPI router for the expo AI wig try-on module (/api/expo)."""

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.expo import ai_pipeline, script_service, service
from app.expo.models import ExpoResult, ExpoScript, ExpoWig
from app.expo.schemas import (
    CustomerRegister,
    FeedbackCreate,
    GenerateRequest,
    HairColorUpsert,
    ReactionRequest,
    ScriptUpsert,
    WigUpsert,
)

logger = logging.getLogger("commission.expo")

router = APIRouter()

WIG_PHOTO_DIR = ai_pipeline.UPLOAD_ROOT / "wigs"
SWATCH_DIR = ai_pipeline.UPLOAD_ROOT / "hair_colors"


def _user_id(current_user) -> int | None:
    if isinstance(current_user, dict):
        return current_user.get("id")
    return getattr(current_user, "id", None)


# ---------------- 试戴主流程（展位设备，expo:write） ----------------

@router.post("/register", summary="客户注册（consent 必须为 true）")
def register(
    body: CustomerRegister,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    if not body.consent:
        raise HTTPException(400, "需同意拍照存储方可体验")
    customer = service.register_customer(db, body)
    return ok({"customer_id": customer.id}, code=201)


@router.post("/sessions", summary="上传照片建会话（tryon=异步分析+匹配 / scene=直接就绪）")
def create_session(
    customer_id: int = Query(...),
    mode: str = Query("tryon", pattern="^(tryon|scene)$"),
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("expo:write")),
):
    try:
        session = service.create_session(db, customer_id, photo, _user_id(current_user), mode=mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if mode == "tryon":
        ai_pipeline.start_analysis(session.id)
    return ok({"session_id": session.id}, code=201)


@router.get("/sessions/{session_id}", summary="轮询会话（status+分析+匹配+效果图）")
def get_session(
    session_id: int,
    internal: int = Query(0, ge=0, le=1, description="1=含内部发况与话术（销售面板用）"),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    session = service.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return ok(service.serialize_session(db, session, include_internal=bool(internal)))


@router.post("/sessions/{session_id}/generate", summary="触发效果图合成（tryon 换发/发色 · scene 场景大片）")
def generate(
    session_id: int,
    body: GenerateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    session = service.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    if session.status == "generating":
        raise HTTPException(400, "效果图正在生成中，请稍候")

    if session.mode == "scene":
        scenes = ai_pipeline.resolve_scenes(body.scene_keys)
        if not scenes:
            raise HTTPException(400, "场景选择无效")
        ai_pipeline.start_scene_composites(session_id, scenes)
        return ok({"scene_keys": [s["key"] for s in scenes]})

    if session.status == "pending":
        raise HTTPException(400, "面容分析尚未完成")
    hair_color = None
    if body.hair_color_id:
        try:
            hair_color = service.snapshot_hair_color(db, body.hair_color_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    tryon_scene = None
    if body.scene_key:
        tryon_scene = ai_pipeline.resolve_tryon_scene(body.scene_key)
        if not tryon_scene:
            raise HTTPException(400, "生成场景无效")
    wig_ids = body.wig_ids or service.pick_batch_wig_ids(session, body.batch)
    if not wig_ids:
        raise HTTPException(400, "没有可生成的匹配发型（检查发型库与匹配标签）")
    if body.wig_ids:
        found = {w.id for w in db.query(ExpoWig).filter(ExpoWig.id.in_(wig_ids)).all()}
        missing = [i for i in wig_ids if i not in found]
        if missing:
            raise HTTPException(400, f"发型不存在: {missing}")
    ai_pipeline.start_composites(session_id, wig_ids, hair_color=hair_color, scene=tryon_scene)
    return ok({"wig_ids": wig_ids})


@router.get("/hair-colors", summary="发色库列表（kiosk 默认只取启用项）")
def list_hair_colors(
    only_active: int = Query(1, ge=0, le=1),
    db: Session = Depends(get_db),
    # expo_hair_color:read=发色库页面码（063 拆分）；保留旧码兼容 kiosk 设备账号
    _user=Depends(require_any_permission("expo_hair_color:read", "expo:read", "expo:write", "expo:admin")),
):
    rows = service.list_hair_colors(db, only_active=bool(only_active))
    return ok([service.serialize_hair_color(r) for r in rows])


@router.get("/scenes", summary="可选场景列表（mode=scene 场景大片 / mode=tryon 试戴生成场景）")
def list_scenes(
    mode: str = Query("scene", pattern="^(scene|tryon)$"),
    # expo_scene:read=场景示意图页面码（063 拆分）；保留旧码兼容 kiosk 设备账号
    _user=Depends(require_any_permission("expo_scene:read", "expo:read", "expo:write", "expo:admin")),
):
    source = ai_pipeline.TRYON_SCENES if mode == "tryon" else ai_pipeline.SCENES
    # tryon 甄选页用滑动图片选择器，附示意图 URL（无图返回 None，前端退化为占位卡）+ 分类
    # （20 景分段展示，前端按 category 分组）；scene 模式仍是文字卡片，不带图/分类
    is_tryon = mode == "tryon"
    return ok([
        {
            "key": s["key"], "label": s["label"], "tagline": s["tagline"],
            "image": ai_pipeline.scene_image_url(s["key"]) if is_tryon else None,
            "category": ai_pipeline.tryon_scene_category(s["key"]) if is_tryon else None,
        }
        for s in source
    ])


@router.post("/scenes/{key}/image", summary="上传/替换场景示意图（存 uploads/expo/scenes/<key>.*）")
def upload_scene_image(
    key: str,
    photo: UploadFile = File(...),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        url = ai_pipeline.save_scene_image(key, photo)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok({"key": key, "url": url}, code=201)


@router.delete("/scenes/{key}/image", summary="删除场景示意图")
def remove_scene_image(
    key: str,
    _user=Depends(require_permission("expo:admin")),
):
    if ai_pipeline.resolve_tryon_scene(key) is None:
        raise HTTPException(404, "场景不存在")
    ai_pipeline.delete_scene_image(key)
    return ok()


@router.post("/results/{result_id}/reaction", summary="客户标记 心动/再看看")
def set_reaction(
    result_id: int,
    body: ReactionRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    row = service.set_reaction(db, result_id, body.reaction)
    if not row:
        raise HTTPException(404, "效果图不存在")
    return ok()


@router.post("/customers/{customer_id}/feedback", summary="销售反馈录入")
def add_feedback(
    customer_id: int,
    body: FeedbackCreate,
    db: Session = Depends(get_db),
    # 调用方是 kiosk 销售面板（useTryOnFlow.submitSales，展位设备账号持 expo:write）；
    # 线索台侧未来录入走 expo_lead:write——两码并存，收紧 expo_lead 不许砍 expo:write
    current_user=Depends(require_any_permission("expo_lead:write", "expo:write")),
):
    try:
        feedback = service.add_feedback(db, customer_id, body, _user_id(current_user) or 0)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return ok({"feedback_id": feedback.id}, code=201)


# ---------------- 分享落地页（无鉴权，短码即凭证） ----------------

@router.get("/share/{short_code}", summary="效果图分享落地页", response_class=HTMLResponse)
def share_page(short_code: str, db: Session = Depends(get_db)):
    row = (
        db.query(ExpoResult)
        .filter(ExpoResult.short_code == short_code, ExpoResult.status == "done")
        .first()
    )
    if not row:
        raise HTTPException(404, "分享不存在或已删除")
    image_url = service._to_url(row.image_path)
    wig_name = row.wig.name if row.wig else (row.scene_json or {}).get("label") or ""
    return HTMLResponse(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>莱莎健康假发 · 我的试戴效果</title>
<style>body{{margin:0;background:#0c0a08;color:#f3ead9;font-family:"PingFang SC",sans-serif;
text-align:center;padding:32px 20px}}img{{max-width:100%;border-radius:18px;
border:1px solid rgba(232,196,121,.35)}}h1{{font-size:16px;letter-spacing:.3em;color:#e8c479;font-weight:400}}
p{{color:#8d8371;font-size:13px;line-height:1.9}}.nm{{color:#f7e3b0;font-size:15px;margin-top:14px}}</style>
</head><body><h1>莱 莎 · 健 康 假 发</h1>
<img src="{image_url}" alt="试戴效果"/><div class="nm">{wig_name}</div>
<p>戴上那一刻，状态就回来了<br/>久戴如新 · SGS 安全认证</p></body></html>""")


# ---------------- 线索台（PC，expo_lead:*，2026-07-12 从 expo:read 拆出） ----------------

@router.get("/leads", summary="展会线索列表")
def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    expo_code: str | None = Query(None),
    intent_level: str | None = Query(None, pattern="^[ABCD]$"),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_lead:read", "expo_lead:write")),
):
    items, total = service.list_leads(
        db, page=page, page_size=page_size,
        expo_code=expo_code, intent_level=intent_level, keyword=keyword,
    )
    return ok(page_result(items, total, page, page_size))


@router.get("/leads/{customer_id}", summary="线索详情（会话回放，含内部发况）")
def lead_detail(
    customer_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_lead:read", "expo_lead:write")),
):
    detail = service.get_lead_detail(db, customer_id)
    if not detail:
        raise HTTPException(404, "客户不存在")
    return ok(detail)


@router.delete("/customers/{customer_id}", summary="删除客户数据（照片物理删除，隐私合规）")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    if not service.delete_customer(db, customer_id):
        raise HTTPException(404, "客户不存在")
    return ok()


# ---------------- 发型库（PC，expo:read/admin） ----------------

@router.get("/wigs", summary="发型库列表")
def list_wigs(
    only_active: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo:read", "expo:write", "expo:admin")),
):
    wigs = service.list_wigs(db, only_active=bool(only_active))
    return ok([service.serialize_wig(w) for w in wigs])


@router.get("/wigs/picker", summary="kiosk 从发型库选择：启用发型轻量列表")
def wig_picker(
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo:read", "expo:write", "expo:admin")),
):
    wigs = service.list_wigs(db, only_active=True)
    return ok([service.serialize_wig_picker(w) for w in wigs])


@router.post("/wigs", summary="新建发型")
def create_wig(
    body: WigUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        wig = service.upsert_wig(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(service.serialize_wig(wig), code=201)


@router.put("/wigs/{wig_id}", summary="更新发型")
def update_wig(
    wig_id: int,
    body: WigUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        wig = service.upsert_wig(db, body, wig_id=wig_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return ok(service.serialize_wig(wig))


@router.delete("/wigs/{wig_id}", summary="删除发型（已产生试戴记录则拒删，引导停用）")
def delete_wig(
    wig_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        deleted = service.delete_wig(db, wig_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not deleted:
        raise HTTPException(404, "发型不存在")
    return ok()


@router.post("/wigs/upload-photo", summary="上传发型参考图，返回相对路径")
def upload_wig_photo(
    photo: UploadFile = File(...),
    _user=Depends(require_permission("expo:admin")),
):
    WIG_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(photo.filename or "wig.jpg").suffix.lower() or ".jpg"
    target = WIG_PHOTO_DIR / f"wig_{uuid.uuid4().hex[:10]}{suffix}"
    with open(target, "wb") as f:
        shutil.copyfileobj(photo.file, f)
    rel = ai_pipeline.to_rel(target)
    return ok({"path": rel, "url": f"/{rel}"}, code=201)


# ---------------- 发色库（PC，expo:admin 管理；列表复用上方 GET /hair-colors） ----------------

@router.post("/hair-colors", summary="新建发色")
def create_hair_color(
    body: HairColorUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        row = service.upsert_hair_color(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(service.serialize_hair_color(row), code=201)


@router.put("/hair-colors/{color_id}", summary="更新发色")
def update_hair_color(
    color_id: int,
    body: HairColorUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        row = service.upsert_hair_color(db, body, color_id=color_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(service.serialize_hair_color(row))


@router.delete("/hair-colors/{color_id}", summary="删除发色（效果图存 JSON 快照，删除不影响历史）")
def delete_hair_color(
    color_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    if not service.delete_hair_color(db, color_id):
        raise HTTPException(404, "发色不存在")
    return ok()


@router.post("/hair-colors/upload-swatch", summary="上传色板图，返回相对路径并自动提取主色 hex")
def upload_hair_color_swatch(
    photo: UploadFile = File(...),
    _user=Depends(require_permission("expo:admin")),
):
    SWATCH_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(photo.filename or "swatch.jpg").suffix.lower() or ".jpg"
    target = SWATCH_DIR / f"swatch_{uuid.uuid4().hex[:10]}{suffix}"
    with open(target, "wb") as f:
        shutil.copyfileobj(photo.file, f)
    rel = ai_pipeline.to_rel(target)

    # 系统承担复杂性：色板图主色自动提取，管理员免手填 hex；失败不阻断上传。
    # k=4 + pick_swatch_hair_hex 跳过白底背景，取真实发色（直接取最大簇会得到白底）
    hex_code = None
    try:
        from app.color.calc_service import extract_dominant_colors

        dominant = extract_dominant_colors(str(target), k=4)
        hex_code = service.pick_swatch_hair_hex(dominant)
    except Exception as exc:
        msg = f"[expo] swatch dominant color extract failed: {exc}"
        logger.warning(msg)
        print(msg, flush=True)

    return ok({"path": rel, "url": f"/{rel}", "hex": hex_code}, code=201)


# ---------------- 话术卡库（PC，expo:read/admin） ----------------

@router.get("/scripts", summary="话术卡列表")
def list_scripts(
    script_type: str | None = Query(None),
    db: Session = Depends(get_db),
    # expo_script:read=话术卡库页面码（063 拆分）；保留旧码兼容线索台/历史调用
    _user=Depends(require_any_permission("expo_script:read", "expo:read", "expo:write", "expo:admin")),
):
    scripts = script_service.list_scripts(db, script_type=script_type, only_active=False)
    return ok([
        {
            "id": s.id,
            "script_type": s.script_type,
            "track": s.track,
            "title": s.title,
            "audience_tags": s.audience_tags or [],
            "content": s.content,
            "evidence_points": s.evidence_points or [],
            "source_version": s.source_version,
            "is_active": s.is_active,
        }
        for s in scripts
    ])


@router.post("/scripts", summary="新建话术卡（含禁用词校验）")
def create_script(
    body: ScriptUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    hit = script_service.check_forbidden(body.content)
    if hit:
        raise HTTPException(400, f"内容包含品牌禁用词：{hit}")
    script = ExpoScript(**body.model_dump())
    db.add(script)
    db.commit()
    db.refresh(script)
    return ok({"id": script.id}, code=201)


@router.put("/scripts/{script_id}", summary="更新话术卡（含禁用词校验）")
def update_script(
    script_id: int,
    body: ScriptUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    script = db.get(ExpoScript, script_id)
    if not script:
        raise HTTPException(404, "话术卡不存在")
    hit = script_service.check_forbidden(body.content)
    if hit:
        raise HTTPException(400, f"内容包含品牌禁用词：{hit}")
    for field, value in body.model_dump().items():
        setattr(script, field, value)
    db.commit()
    return ok()


@router.post("/scripts/seed", summary="导入营销文档种子话术卡（幂等）")
def seed_scripts(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    created = script_service.seed_default_scripts(db)
    return ok({"created": created})
