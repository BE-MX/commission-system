"""Expo try-on 业务逻辑：客户/会话/结果/反馈/发型库 CRUD 与序列化。"""

import logging
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

logger = logging.getLogger("commission.expo")

# 看门狗阈值：后台线程随进程重启丢失后，卡死状态在轮询读取时自愈
# 必须大于 ai/call_service.py 的 MIN_MULTIMODAL_CHAT_TIMEOUT_SEC(120)，否则会把仍在
# 正常等待模型的面容分析误判为卡死（正常 <30s，240 是刻意宽余量）
STALE_PENDING_SECS = 240
# 必须大于 ai/image_service.py 的 MIN_IMAGE_EDIT_TIMEOUT_SEC(300)，否则会把仍在
# 正常等待上游的合成误判为卡死（单场景模板实测 ~130s，420 是刻意宽余量）
STALE_GENERATING_SECS = 420


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


def update_customer(db: Session, customer_id: int, body: CustomerRegister) -> ExpoCustomer | None:
    """kiosk「返回上一步」修改登记信息：更新既有客户，不重复建档（线索台一客一档）。

    consent_at 只置不清：已同意过的客户改信息不撤销授权时间戳。返回 None=客户不存在。
    """
    customer = db.get(ExpoCustomer, customer_id)
    if not customer:
        return None
    customer.name = body.name.strip()
    customer.phone = body.phone.strip()
    customer.wechat_id = (body.wechat_id or "").strip() or None
    customer.primary_need = body.primary_need
    customer.style_pref = body.style_pref
    if body.consent and not customer.consent_at:
        customer.consent_at = datetime.utcnow()
    # 届次只在显式传值时覆写：schema 默认空串，漏传不擦掉已有 expo_code
    if body.expo_code and body.expo_code.strip():
        customer.expo_code = body.expo_code.strip()
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
    # 结果图的 kiosk 展示版（{stem}_disp.jpg）随原图一并清理，不留孤儿文件
    disp = target.with_name(target.stem + ai_pipeline.DISPLAY_SUFFIX)
    if disp.exists():
        disp.unlink(missing_ok=True)


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
    # kiosk 相机件已是 1080px（原样跳过）；顾问文件选择兜底传的手机原片在此压下来——
    # photo_url 会作为"佩戴前"对比图经 frp 隧道回源展示
    ai_pipeline.downscale_inplace(photo_path)

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
    session = (
        db.query(ExpoSession)
        .options(selectinload(ExpoSession.results).selectinload(ExpoResult.wig))
        .filter(ExpoSession.id == session_id)
        .first()
    )
    if session:
        _heal_stale_session(db, session)
    return session


def _heal_stale_session(db: Session, session: ExpoSession) -> None:
    """看门狗：pending/generating 卡死超阈值时自愈（线上 session=6 实case——
    后台合成线程随进程重启丢失，result 永远 generating，前端无限轮询）。"""
    ref = session.updated_at or session.created_at
    if not ref or session.status not in ("pending", "generating"):
        return
    age = (datetime.utcnow() - ref).total_seconds()

    if session.status == "pending" and age > STALE_PENDING_SECS:
        session.status = "failed"
        session.error_message = f"watchdog: analysis stale over {STALE_PENDING_SECS}s"
    elif session.status == "generating" and age > STALE_GENERATING_SECS:
        for r in session.results:
            if r.status in ("pending", "generating"):
                r.status = "failed"
        if any(r.status == "done" for r in session.results):
            session.status = "done"  # 有成品照常展示，只收掉卡死的
        else:
            session.status = "failed"
            session.error_message = f"watchdog: all composites stale over {STALE_GENERATING_SECS}s"
    else:
        return
    msg = f"[expo] watchdog healed session={session.id} -> {session.status} (age={int(age)}s)"
    logger.warning(msg)
    print(msg, flush=True)
    db.commit()


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
            "must_recommend": wig.must_recommend,
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
                # kiosk 展示版（压缩 JPEG）：历史结果/生成失败时为 None，前端回退 image_url
                "display_url": _to_url(ai_pipeline.display_rel_for(r.image_path)),
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


def pick_swatch_hair_hex(dominant: list[dict]) -> str | None:
    """从色板图主色簇里挑真实发色 hex：跳过近白背景（色板普遍白底，K-means 最大簇
    往往是背景，直接取 [0] 会得到 #fcfcfc 这种白，见 2026-07-08 实case）。

    策略：滤掉近白簇（三通道均 >=232），取剩余占比最大的；全被滤光则回退占比最大的原簇。
    近黑不滤——自然黑是有效发色。dominant 为 extract_dominant_colors 输出（按占比降序）。
    """
    def is_near_white(rgb: list[int]) -> bool:
        return all(c >= 232 for c in rgb)

    if not dominant:
        return None
    candidates = [c for c in dominant if not is_near_white(c.get("rgb") or [0, 0, 0])]
    chosen = candidates[0] if candidates else dominant[0]
    return chosen.get("hex")


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


def delete_hair_color(db: Session, color_id: int) -> bool:
    """物理删除发色。发色在效果图里是 JSON 快照（非外键），删除不影响历史效果图，
    可直接硬删。返回 False=不存在。

    注意：历史 result 的 hair_color_json.swatch_path 仍指向这里删掉的色板图文件，
    但该字段仅作快照溯源——展示只用 hex+name，合成自 2026-07-14 起也只用文本色锚点
    （色板图不再随图送模型），删文件无任何运行时影响。
    """
    row = db.get(ExpoHairColor, color_id)
    if not row:
        return False
    _remove_file(row.swatch_path)
    db.delete(row)
    db.commit()
    return True


def snapshot_hair_color(db: Session, hair_color_id: int) -> dict:
    """选定发色 → 随 result 落库的快照，与发色库后续变更解耦。
    swatch_path 仅溯源用：合成只用 name/code/hex/description 文本锚点（2026-07-14 起）。"""
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


# ---------------- kiosk 销售面板（展位设备 expo:write，2026-07-13） ----------------
# 与 web 线索台（expo_lead:*）区分：共享屏最小暴露面——手机号脱敏、不带备注/微信号，
# 话术载荷只出 strategy 与试戴款，internal 发况一律不出（2026-07-07 隐私红线保留）

def mask_phone(phone: str | None) -> str:
    """共享屏脱敏：138****1234。检索仍走服务端全量号码，展示永不出全号。

    门槛取 11（手机号标准长度）：phone 是自由文本，8~10 位座机/短号若走
    留3+留4 分支只藏 1~2 位形同裸奔，一律走重脱敏。
    """
    p = (phone or "").strip()
    if len(p) >= 11:
        return f"{p[:3]}****{p[-4:]}"
    return f"{p[:1]}***" if p else ""


def serialize_kiosk_lead(row: dict) -> dict:
    """kiosk 线索列表行：与 web 线索台同源（list_leads 输出），裁剪+脱敏。"""
    return {
        "customer_id": row["id"],
        "name": row["name"],
        "phone_masked": mask_phone(row["phone"]),
        "intent_level": row["intent_level"],
        "session_count": row["session_count"],
        "result_count": row["result_count"],
        "created_at": row["created_at"],
    }


def get_kiosk_strategy(db: Session, customer_id: int) -> dict | None:
    """kiosk 销售面板线索详情：话术 + 试戴款 + 原图/效果图（2026-07-13 亮哥指令加图）。

    照片随载荷下发（客户建会话前已签拍照同意）；internal 发况仍不出 kiosk。
    返回 None=客户不存在；strategy=None 且 strategy_pending=True 表示话术
    正在随合成并行生成（前端 5s 静默轮询），两者都 False 则该客户不会有话术。
    """
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
    raw = next((s.strategy_json for s in sessions if s.strategy_json), None)
    # 键白名单：模型输出/回落路径可能夹带多余键（如 fallback 标记），收敛到三段话术
    strategy = (
        {k: raw.get(k) for k in ("opener", "followup", "objections")} if raw else None
    )
    # scene 会话不生成话术，不计入"生成中"（否则纯场景客户会假显"话术生成中"空转轮询）
    generating = any(
        s.status in ("pending", "generating") and s.mode != "scene" for s in sessions
    )
    tried_wigs: list[str] = []
    for s in sessions:
        for r in s.results:
            name = r.wig.name if r.wig else None
            if name and name not in tried_wigs:
                tried_wigs.append(name)
    # 原图 + 已完成效果图（sessions 倒序=最新在前；失败/生成中的结果不出图）
    sessions_payload = [
        {
            "id": s.id,
            "mode": s.mode,
            "photo_url": _to_url(s.photo_path),
            "results": [
                {
                    "id": r.id,
                    "wig_name": r.wig.name if r.wig else (r.scene_json or {}).get("label"),
                    "image_url": _to_url(r.image_path),
                    # 销售面板图集也在展位设备上看，走展示版；缺失回退原图
                    "display_url": _to_url(ai_pipeline.display_rel_for(r.image_path)),
                    "reaction": r.reaction,
                }
                for r in s.results
                if r.status == "done" and r.image_path
            ],
        }
        for s in sessions
    ]
    return {
        "customer": {
            "customer_id": customer.id,
            "name": customer.name,
            "phone_masked": mask_phone(customer.phone),
            "primary_need": customer.primary_need,
            "style_pref": customer.style_pref,
        },
        "strategy": strategy,
        "strategy_pending": strategy is None and generating,
        "tried_wigs": tried_wigs,
        "sessions": sessions_payload,
    }


# ---------------- 发型库 ----------------

def list_wigs(db: Session, only_active: bool = False) -> list[ExpoWig]:
    q = db.query(ExpoWig)
    if only_active:
        q = q.filter(ExpoWig.is_active == 1)
    # 主推置顶：管理列表与 kiosk「从发型库选择」picker 共用此排序
    return q.order_by(ExpoWig.must_recommend.desc(), ExpoWig.priority.desc(), ExpoWig.id).all()


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


def delete_wig(db: Session, wig_id: int) -> bool:
    """物理删除发型。已产生试戴记录的发型拒删（保护线索台复盘数据），
    引导改用「停用」。返回 False=不存在；被引用抛 ValueError（router 转 409）。"""
    wig = db.get(ExpoWig, wig_id)
    if not wig:
        return False
    used = db.query(ExpoResult.id).filter(ExpoResult.wig_id == wig_id).count()
    if used:
        raise ValueError(f"该发型已产生 {used} 条试戴记录，无法删除；如需下架请改用「停用」")
    # 无引用才删：清掉该发型独占的封面与多角度图（不影响任何效果图）
    _remove_file(wig.cover_path)
    for path in wig.angle_photos or []:
        _remove_file(path)
    db.delete(wig)
    try:
        db.commit()
    except IntegrityError:
        # 应用层查引用与删除之间的竞态：并发插入 result 引用该 wig，DB FK(RESTRICT) 兜底。
        # 归一为 ValueError → router 转 409，与"已被引用"给用户同一提示，不冒 500
        db.rollback()
        raise ValueError("该发型刚产生了新的试戴记录，无法删除；如需下架请改用「停用」")
    return True


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
        # angle_urls：加前导 / 的可访问 URL，供编辑页预览（angle_photos 存的是裸相对路径，
        # 直接当 src 会被浏览器按当前路由解析成 /expo/uploads/... → 404，与 cover_url 同理）
        "angle_urls": [_to_url(p) for p in (wig.angle_photos or [])],
        "wig_description": wig.wig_description,
        "composite_prompt": wig.composite_prompt,
        "fit_tags": wig.fit_tags or {},
        "selling_points": wig.selling_points,
        "evidence_refs": wig.evidence_refs or [],
        "priority": wig.priority,
        "must_recommend": wig.must_recommend,
        "is_active": wig.is_active,
    }


def serialize_wig_picker(wig: ExpoWig) -> dict:
    """kiosk「从发型库选择」用的轻量载荷：只给挑款需要的字段，不暴露管理端数据。"""
    return {
        "wig_id": wig.id,
        "model_no": wig.model_no,
        "name": wig.name,
        "series": wig.series,
        "cover_url": _to_url(wig.cover_path),
    }
