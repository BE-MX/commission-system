"""Retail-mall-only AI try-on endpoints.

Retail grants are valid only below this router.  They cannot reach the kiosk
sales panel, store quota, lead search, or any Ark administration endpoint.
"""

import hashlib
import logging
from contextlib import contextmanager

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.expo import ai_pipeline, beautify_prompt_service, beautify_service, prompt_service, service, upload_service
from app.expo.ai_pipeline import build_composite_rows, launch_composite_threads, prepare_composite_batch
from app.expo.models import ExpoCustomer, ExpoResult, ExpoSession, ExpoWig
from app.expo.retail_auth import RetailGrant, claim_retail_tryon_generation, require_retail_tryon_grant
from app.expo.schemas import CustomerRegister, GenerateRequest, ReactionRequest


logger = logging.getLogger("commission.expo.retail")
router = APIRouter()


def _grant_tag(grant: RetailGrant) -> str:
    return f"retail-{hashlib.sha256(grant.token.encode()).hexdigest()[:48]}"


def _owned_customer(db: Session, customer_id: int, grant: RetailGrant) -> ExpoCustomer:
    customer = db.get(ExpoCustomer, customer_id)
    if not customer or customer.expo_code != _grant_tag(grant):
        raise HTTPException(404, "客户不存在")
    return customer


def _owned_session(db: Session, session_id: int, grant: RetailGrant) -> ExpoSession:
    session = service.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    _owned_customer(db, session.customer_id, grant)
    return session


def _commit_or_500(db: Session, context: str) -> None:
    try:
        db.commit()
    except (IntegrityError, SQLAlchemyError) as exc:
        db.rollback()
        logger.warning("[expo-retail] %s commit failed: %s", context, exc)
        raise HTTPException(500, "提交失败，请稍后重试") from None


@contextmanager
def _prompt_transaction(db: Session):
    """Customer-flow subset of the prompt transaction error boundary."""
    try:
        yield
    except prompt_service.PromptError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "生成配置已变化，请刷新后重试") from None
    except OperationalError:
        db.rollback()
        raise HTTPException(503, "提示词配置暂时不可用，请稍后重试") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "提示词配置暂时不可用，请稍后重试") from None
    except HTTPException:
        db.rollback()
        raise


@router.post("/register", summary="零售商城客户登记（短期 grant）")
def register(
    body: CustomerRegister,
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    if not body.consent:
        raise HTTPException(400, "需同意拍照存储方可体验")
    tag = _grant_tag(grant)
    existing = db.query(ExpoCustomer).filter(ExpoCustomer.expo_code == tag).first()
    if existing:
        return ok({"customer_id": existing.id})
    scoped = body.model_copy(update={"phone": grant.phone, "expo_code": tag})
    customer = service.register_customer(db, scoped, operator_user_id=None)
    return ok({"customer_id": customer.id}, code=201)


@router.put("/customers/{customer_id}", summary="更新本次零售试戴登记")
def update_customer(
    customer_id: int,
    body: CustomerRegister,
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    _owned_customer(db, customer_id, grant)
    scoped = body.model_copy(update={"phone": grant.phone, "expo_code": _grant_tag(grant)})
    customer = service.update_customer(db, customer_id, scoped)
    return ok({"customer_id": customer.id})


@router.post("/sessions", summary="创建零售试戴会话（仅 tryon）")
def create_session(
    customer_id: int = Query(...),
    mode: str = Query("tryon"),
    photo: UploadFile | None = File(None),
    pending_photo: str | None = Form(None),
    photo_processing_mode: str = Form("original", pattern="^(original|beauty)$"),
    client_request_id: str | None = Form(None, max_length=64),
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    if mode != "tryon":
        raise HTTPException(400, "零售免费体验仅开放 AI 发型试戴")
    _owned_customer(db, customer_id, grant)
    pending_photo = (pending_photo or "").strip() or None
    try:
        session = service.create_session(
            db, customer_id, photo, None, mode="tryon", pending_name=pending_photo,
            photo_processing_mode=photo_processing_mode, client_request_id=client_request_id,
        )
    except service.SessionRequestConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except prompt_service.PromptError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    upload_service.sweep_stale()
    replay = bool(getattr(session, "_idempotent_replay", False))
    if not replay:
        ai_pipeline.start_analysis(session.id)
    if photo_processing_mode == "beauty" and not replay:
        beautify_service.start(session.id)
    return ok({"session_id": session.id}, code=200 if replay else 201)


@router.get("/beautify-availability", summary="零售试戴美颜可用性")
def beautify_availability(
    db: Session = Depends(get_db),
    _grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    return ok(beautify_prompt_service.availability(db))


@router.post("/sessions/{session_id}/beautify/retry", summary="重试本次零售试戴美颜")
def retry_beautify(
    session_id: int,
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    session = _owned_session(db, session_id, grant)
    try:
        session = beautify_service.retry(db, session)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return ok({"beautify_status": session.beautify_status})


@router.get("/sessions/{session_id}", summary="轮询本次零售试戴会话")
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    session = _owned_session(db, session_id, grant)
    return ok(service.serialize_session(db, session, include_internal=False))


@router.post("/sessions/{session_id}/contact-admin", summary="零售试戴人工支持提示")
def contact_support(
    session_id: int,
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    _owned_session(db, session_id, grant)
    return ok({"sent": False, "in_progress": False})


@router.post("/sessions/{session_id}/generate", summary="生成一次零售免费试戴效果")
def generate(
    session_id: int,
    body: GenerateRequest,
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    session = _owned_session(db, session_id, grant)
    customer = (db.query(ExpoCustomer).filter(ExpoCustomer.id == session.customer_id)
                .with_for_update().one())
    already_generated = (db.query(ExpoResult.id).join(ExpoSession)
                         .filter(ExpoSession.customer_id == customer.id, ExpoResult.status != "failed").first())
    if already_generated:
        raise HTTPException(409, "本次免费试戴已经生成过效果，如需再次体验请联系专属客服")
    if session.status == "generating":
        raise HTTPException(400, "效果图正在生成中，请稍候")
    if session.photo_processing_mode == "beauty":
        if session.beautify_status in ("pending", "processing"):
            raise HTTPException(409, "照片正在美颜精修，请稍候")
        if session.beautify_status != "ready" or not session.beautified_photo_path:
            raise HTTPException(409, "美颜精修未成功，请重试或改用原照片生成")
    if session.status == "pending":
        raise HTTPException(400, "面容分析尚未完成")

    hair_color = None
    if body.hair_color_id:
        try:
            hair_color = service.snapshot_hair_color(db, body.hair_color_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    tryon_scene = None
    if body.scene_key:
        tryon_scene = ai_pipeline.resolve_tryon_scene(body.scene_key)
        if not tryon_scene:
            raise HTTPException(400, "生成场景无效")
    wig_ids = body.wig_ids or service.pick_batch_wig_ids(session, body.batch)[:1]
    if len(wig_ids) != 1:
        raise HTTPException(400, "每次免费体验请选择一款发型")
    if not db.query(ExpoWig.id).filter(ExpoWig.id == wig_ids[0]).first():
        raise HTTPException(400, "所选发型不存在")
    rows = build_composite_rows(
        session_id, wig_ids, hair_color=hair_color, scene=tryon_scene, db=db,
        quality=body.quality,
    )
    with _prompt_transaction(db):
        version = prompt_service.capture_batch(db, session, rows, None)
        version_summary = prompt_service.serialize_version(version)
        result_ids, start_strategy = prepare_composite_batch(session_id, rows, db)
        claim_retail_tryon_generation(grant, f"expo-session:{session.id}")
    if not result_ids:
        raise HTTPException(500, "生成任务创建失败")
    _commit_or_500(db, "generate")
    launch_composite_threads(session_id, result_ids, start_strategy)
    return ok({"wig_ids": wig_ids, "prompt_version": version_summary})


@router.get("/hair-colors", summary="零售试戴发色列表")
def list_hair_colors(
    only_active: int = Query(1, ge=0, le=1),
    db: Session = Depends(get_db),
    _grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    rows = service.list_hair_colors(db, only_active=bool(only_active))
    return ok([service.serialize_hair_color(row) for row in rows])


@router.get("/scenes", summary="零售试戴场景列表")
def list_scenes(
    mode: str = Query("tryon"),
    _grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    if mode != "tryon":
        raise HTTPException(400, "零售免费体验仅开放 AI 发型试戴")
    return ok([{
        "key": scene["key"], "label": scene["label"], "tagline": scene["tagline"],
        "image": ai_pipeline.scene_image_url(scene["key"]),
        "category": ai_pipeline.tryon_scene_category(scene["key"]),
    } for scene in ai_pipeline.TRYON_SCENES])


@router.get("/wigs/picker", summary="零售试戴启用发型")
def wig_picker(
    db: Session = Depends(get_db),
    _grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    wigs = service.list_wigs(db, only_active=True)
    return ok([service.serialize_wig_picker(wig) for wig in wigs])


@router.get("/wigs/{wig_id}/colors", summary="零售试戴发型可选发色")
def list_wig_colors(
    wig_id: int,
    db: Session = Depends(get_db),
    _grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    return ok(service.list_wig_color_options(db, wig_id))


@router.post("/results/{result_id}/reaction", summary="零售客户标记试戴效果")
def set_reaction(
    result_id: int,
    body: ReactionRequest,
    db: Session = Depends(get_db),
    grant: RetailGrant = Depends(require_retail_tryon_grant),
):
    result = db.get(ExpoResult, result_id)
    if not result:
        raise HTTPException(404, "效果图不存在")
    _owned_session(db, result.session_id, grant)
    row = service.set_reaction(db, result_id, body.reaction)
    if not row:
        raise HTTPException(404, "效果图不存在")
    return ok()
