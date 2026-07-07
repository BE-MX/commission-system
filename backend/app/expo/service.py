"""Expo try-on 业务逻辑：客户/会话/结果/反馈/发型库 CRUD 与序列化。"""

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.expo import ai_pipeline
from app.expo.models import (
    ExpoCustomer,
    ExpoFeedback,
    ExpoHairColor,
    ExpoResult,
    ExpoSession,
    ExpoWig,
)
from app.expo.schemas import CustomerRegister, FeedbackCreate, HairColorUpsert, WigUpsert


# ---------------- 客户 ----------------

def register_customer(db: Session, body: CustomerRegister) -> ExpoCustomer:
    customer = ExpoCustomer(
        name=body.name.strip(),
        phone=body.phone.strip(),
        wechat_id=(body.wechat_id or "").strip() or None,
        primary_need=body.primary_need,
        style_pref=body.style_pref,
        consent_at=datetime.utcnow() if body.consent else None,
        expo_code=body.expo_code,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def delete_customer(db: Session, customer_id: int) -> bool:
    """隐私合规：物理删除客户照片、效果图与全部记录。"""
    customer = db.get(ExpoCustomer, customer_id)
    if not customer:
        return False
    for session in customer.sessions:
        _remove_file(session.photo_path)
        for result in session.results:
            _remove_file(result.image_path)
    db.delete(customer)  # FK CASCADE 带走 sessions/results/feedback
    db.commit()
    return True


def _remove_file(path: str | None) -> None:
    if not path:
        return
    target = ai_pipeline.to_abs(path)
    if target.exists():
        target.unlink(missing_ok=True)


# ---------------- 会话 ----------------

def create_session(
    db: Session, customer_id: int, upload_file,
    operator_user_id: int | None, mode: str = "tryon",
) -> ExpoSession:
    customer = db.get(ExpoCustomer, customer_id)
    if not customer:
        raise ValueError("客户不存在")
    if not customer.consent_at:
        raise ValueError("客户未同意拍照存储，无法创建会话")

    ai_pipeline.ensure_dirs()
    suffix = Path(upload_file.filename or "photo.jpg").suffix.lower() or ".jpg"
    photo_path = ai_pipeline.PHOTO_DIR / f"c{customer_id}_{uuid.uuid4().hex[:10]}{suffix}"
    with open(photo_path, "wb") as f:
        shutil.copyfileobj(upload_file.file, f)

    session = ExpoSession(
        customer_id=customer_id,
        mode=mode,
        photo_path=ai_pipeline.to_rel(photo_path),
        # scene 模式不做面容分析，直接就绪等待选场景生成
        status="analyzed" if mode == "scene" else "pending",
        operator_user_id=operator_user_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: int) -> ExpoSession | None:
    return (
        db.query(ExpoSession)
        .options(selectinload(ExpoSession.results).selectinload(ExpoResult.wig))
        .filter(ExpoSession.id == session_id)
        .first()
    )


def pick_batch_wig_ids(session: ExpoSession, batch: int) -> list[int]:
    ranking = session.matched_wig_ids or []
    top_n = 3
    return [r["wig_id"] for r in ranking[batch * top_n : (batch + 1) * top_n]]


def serialize_session(db: Session, session: ExpoSession, include_internal: bool = False) -> dict:
    """轮询端点的统一载荷：status + 分析 + 匹配 + 效果图。

    include_internal=False 时剥掉 analysis_json.internal 与 strategy（隐私红线）。
    """
    ranking = session.matched_wig_ids or []
    wig_ids = [r["wig_id"] for r in ranking[:6]]
    wigs = {w.id: w for w in db.query(ExpoWig).filter(ExpoWig.id.in_(wig_ids)).all()} if wig_ids else {}

    matches = []
    for entry in ranking[:6]:
        wig = wigs.get(entry["wig_id"])
        if not wig:
            continue
        matches.append({
            "wig_id": wig.id,
            "model_no": wig.model_no,
            "name": wig.name,
            "series": wig.series,
            "cover_url": _to_url(wig.cover_path),
            "score": entry.get("score"),
            "reason": entry.get("reason"),
            "evidence_refs": wig.evidence_refs or [],
        })

    payload = {
        "id": session.id,
        "mode": session.mode,
        "status": session.status,
        "analysis": ai_pipeline.public_analysis(session.analysis_json),
        "matches": matches,
        "total_matches": len(ranking),
        "results": [
            {
                "id": r.id,
                "wig_id": r.wig_id,
                # scene 结果无关联发型，回退场景名保证线索台可读
                "wig_name": r.wig.name if r.wig else (r.scene_json or {}).get("label"),
                "model_no": r.wig.model_no if r.wig else None,
                "series": r.wig.series if r.wig else None,
                "hair_color": r.hair_color_json,
                "scene": r.scene_json,
                "status": r.status,
                "image_url": _to_url(r.image_path),
                "reaction": r.reaction,
                "short_code": r.short_code,
                "gen_ms": r.gen_ms,
            }
            for r in session.results
        ],
        "photo_url": _to_url(session.photo_path),
    }
    if include_internal:
        payload["analysis_internal"] = (session.analysis_json or {}).get("internal")
        payload["strategy"] = session.strategy_json
        payload["error_message"] = session.error_message
    return payload


def _to_url(path: str | None) -> str | None:
    if not path:
        return None
    normalized = str(path).replace("\\", "/")
    if normalized.startswith("uploads/"):
        return f"/{normalized}"
    return normalized


# ---------------- 发色库（048 迁移，参照发型库独立维护） ----------------

def list_hair_colors(db: Session, only_active: bool = True) -> list[ExpoHairColor]:
    q = db.query(ExpoHairColor)
    if only_active:
        q = q.filter(ExpoHairColor.is_active == 1)
    return q.order_by(ExpoHairColor.priority.desc(), ExpoHairColor.id).all()


def serialize_hair_color(row: ExpoHairColor) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "hex": row.hex_code,
        "swatch_path": row.swatch_path,
        "swatch_url": _to_url(row.swatch_path),
        "color_description": row.color_description,
        "priority": row.priority,
        "is_active": row.is_active,
    }


def upsert_hair_color(db: Session, body: HairColorUpsert, color_id: int | None = None) -> ExpoHairColor:
    dup = (
        db.query(ExpoHairColor)
        .filter(ExpoHairColor.code == body.code.strip(), ExpoHairColor.id != (color_id or 0))
        .first()
    )
    if dup:
        raise ValueError(f"色号 {body.code} 已存在")
    if color_id:
        row = db.get(ExpoHairColor, color_id)
        if not row:
            raise ValueError("发色不存在")
    else:
        row = ExpoHairColor()
        db.add(row)
    for field, value in body.model_dump().items():
        # 空串统一落 NULL，避免 '' 与 NULL 并存污染查询口径
        setattr(row, field, (value.strip() or None) if isinstance(value, str) and field != "code" else value)
    row.code = body.code.strip()
    try:
        db.commit()
    except IntegrityError:
        # 先查后写的竞态兜底：并发同 code 落到 DB UNIQUE 上
        db.rollback()
        raise ValueError(f"色号 {body.code} 已存在")
    db.refresh(row)
    return row


def snapshot_hair_color(db: Session, hair_color_id: int) -> dict:
    """选定发色 → 随 result 落库的快照（色板图 + 描述），与发色库后续变更解耦。"""
    row = db.get(ExpoHairColor, hair_color_id)
    if not row or not row.is_active:
        raise ValueError("发色不存在或已停用")
    return {
        "hair_color_id": row.id,
        "code": row.code,
        "name": row.name,
        "hex": row.hex_code,
        "swatch_path": row.swatch_path,
        "description": row.color_description,
    }


# ---------------- 反应 / 反馈 ----------------

def set_reaction(db: Session, result_id: int, reaction: str) -> ExpoResult | None:
    row = db.get(ExpoResult, result_id)
    if not row:
        return None
    row.reaction = reaction
    db.commit()
    return row


def add_feedback(db: Session, customer_id: int, body: FeedbackCreate, sales_user_id: int) -> ExpoFeedback:
    if not db.get(ExpoCustomer, customer_id):
        raise ValueError("客户不存在")
    feedback = ExpoFeedback(
        customer_id=customer_id,
        session_id=body.session_id,
        sales_user_id=sales_user_id,
        intent_level=body.intent_level,
        notes=body.notes,
        next_action=body.next_action,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


# ---------------- 线索台 ----------------

def list_leads(
    db: Session,
    page: int,
    page_size: int,
    expo_code: str | None = None,
    intent_level: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict], int]:
    q = db.query(ExpoCustomer)
    if expo_code:
        q = q.filter(ExpoCustomer.expo_code == expo_code)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(ExpoCustomer.name.like(like) | ExpoCustomer.phone.like(like))

    customers = q.order_by(ExpoCustomer.id.desc()).all()
    ids = [c.id for c in customers]

    latest_feedback: dict[int, ExpoFeedback] = {}
    if ids:
        for fb in (
            db.query(ExpoFeedback)
            .filter(ExpoFeedback.customer_id.in_(ids))
            .order_by(ExpoFeedback.id.asc())
            .all()
        ):
            latest_feedback[fb.customer_id] = fb  # 后写覆盖 → 留下最新一条

    session_counts: dict[int, int] = {}
    result_counts: dict[int, int] = {}
    if ids:
        for s in db.query(ExpoSession).filter(ExpoSession.customer_id.in_(ids)).all():
            session_counts[s.customer_id] = session_counts.get(s.customer_id, 0) + 1
            result_counts[s.customer_id] = result_counts.get(s.customer_id, 0) + len(s.results)

    rows = []
    for c in customers:
        fb = latest_feedback.get(c.id)
        if intent_level and (not fb or fb.intent_level != intent_level):
            continue
        rows.append({
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "wechat_id": c.wechat_id,
            "primary_need": c.primary_need,
            "style_pref": c.style_pref,
            "expo_code": c.expo_code,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "session_count": session_counts.get(c.id, 0),
            "result_count": result_counts.get(c.id, 0),
            "intent_level": fb.intent_level if fb else None,
            "last_note": fb.notes if fb else None,
            "next_action": fb.next_action if fb else None,
        })

    total = len(rows)
    start = (page - 1) * page_size
    return rows[start : start + page_size], total


def get_lead_detail(db: Session, customer_id: int) -> dict | None:
    customer = db.get(ExpoCustomer, customer_id)
    if not customer:
        return None
    sessions = (
        db.query(ExpoSession)
        .options(selectinload(ExpoSession.results).selectinload(ExpoResult.wig))
        .filter(ExpoSession.customer_id == customer_id)
        .order_by(ExpoSession.id.desc())
        .all()
    )
    feedbacks = (
        db.query(ExpoFeedback)
        .filter(ExpoFeedback.customer_id == customer_id)
        .order_by(ExpoFeedback.id.desc())
        .all()
    )
    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "wechat_id": customer.wechat_id,
            "primary_need": customer.primary_need,
            "style_pref": customer.style_pref,
            "expo_code": customer.expo_code,
        },
        "sessions": [serialize_session(db, s, include_internal=True) for s in sessions],
        "feedbacks": [
            {
                "id": f.id,
                "intent_level": f.intent_level,
                "notes": f.notes,
                "next_action": f.next_action,
                "sales_user_id": f.sales_user_id,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in feedbacks
        ],
    }


# ---------------- 发型库 ----------------

def list_wigs(db: Session, only_active: bool = False) -> list[ExpoWig]:
    q = db.query(ExpoWig)
    if only_active:
        q = q.filter(ExpoWig.is_active == 1)
    return q.order_by(ExpoWig.priority.desc(), ExpoWig.id).all()


def upsert_wig(db: Session, body: WigUpsert, wig_id: int | None = None) -> ExpoWig:
    if wig_id:
        wig = db.get(ExpoWig, wig_id)
        if not wig:
            raise ValueError("发型不存在")
    else:
        wig = ExpoWig()
        db.add(wig)
    for field, value in body.model_dump().items():
        setattr(wig, field, value)
    db.commit()
    db.refresh(wig)
    return wig


def serialize_wig(wig: ExpoWig) -> dict:
    return {
        "id": wig.id,
        "model_no": wig.model_no,
        "name": wig.name,
        "series": wig.series,
        "product_id": wig.product_id,
        "cover_path": wig.cover_path,
        "cover_url": _to_url(wig.cover_path),
        "angle_photos": wig.angle_photos or [],
        "wig_description": wig.wig_description,
        "composite_prompt": wig.composite_prompt,
        "fit_tags": wig.fit_tags or {},
        "selling_points": wig.selling_points,
        "evidence_refs": wig.evidence_refs or [],
        "priority": wig.priority,
        "is_active": wig.is_active,
    }
