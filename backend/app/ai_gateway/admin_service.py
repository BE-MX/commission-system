"""Admin lifecycle and metadata-only visibility."""

from datetime import timedelta
from sqlalchemy import func, select

from app.ai.models import AiPreset, AiProvider
from app.ai.service import prepare_text_chat
from app.ai_gateway.auth import issue_key
from app.ai_gateway.errors import GatewayError
from app.ai_gateway.models import GatewayApp, GatewayAppPreset, GatewayRequest
from app.ai_gateway.service import OCCUPIED, day_window, lock_app, require_owner
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now


def validate_presets(db, preset_ids):
    ids = set(preset_ids)
    rows = db.execute(select(AiPreset.id, AiPreset.preset_name).where(AiPreset.id.in_(ids))
                      .order_by(AiPreset.id).with_for_update(read=True)).all()
    if len(rows) != len(ids):
        raise GatewayError(422, "invalid_presets", "所选能力不存在")
    for row in rows:
        try:
            prepare_text_chat(db, row.preset_name, get_settings().AI_GATEWAY_MAX_OUTPUT_TOKENS)
        except ValueError:
            raise GatewayError(422, "invalid_presets", "只能授权已启用且参数兼容的 direct 文本能力") from None


def set_presets(db, app_id, ids):
    db.query(GatewayAppPreset).filter_by(app_id=app_id).delete(synchronize_session=False)
    db.add_all(GatewayAppPreset(app_id=app_id, preset_id=p) for p in sorted(set(ids)))


def app_dict(db, app):
    result = {c.name: getattr(app, c.name) for c in app.__table__.columns if c.name != "key_hash"}
    result["preset_ids"] = list(db.execute(select(GatewayAppPreset.preset_id)
                                          .where(GatewayAppPreset.app_id == app.id)).scalars())
    result["owner_name"] = db.execute(select(ArkUser.real_name).where(ArkUser.id == app.owner_user_id)).scalar()
    result["preset_names"] = list(db.execute(select(AiPreset.preset_name).where(AiPreset.id.in_(result["preset_ids"]))).scalars())
    return result


def create_app(db, data, actor):
    values = data.model_dump(exclude={"preset_ids"})
    require_owner(db, data.owner_user_id)
    validate_presets(db, data.preset_ids)
    raw, key_hash, hint = issue_key()
    app = GatewayApp(**values, key_hash=key_hash, key_hint=hint, created_by=actor, updated_by=actor)
    db.add(app)
    db.flush()
    set_presets(db, app.id, data.preset_ids)
    db.flush()
    result = app_dict(db, app)
    db.commit()
    return {**result, "api_key": raw}


def update_app(db, app_id, data, actor):
    app = lock_app(db, app_id)
    values = data.model_dump(exclude_unset=True)
    if "owner_user_id" in values:
        require_owner(db, values["owner_user_id"])
    if "preset_ids" in values:
        ids = values.pop("preset_ids")
        validate_presets(db, ids)
        set_presets(db, app_id, ids)
    for key, value in values.items():
        setattr(app, key, value)
    app.updated_by = actor
    app.updated_at = beijing_now()
    db.flush()
    result = app_dict(db, app)
    db.commit()
    return result


def rotate_key(db, app_id, actor):
    app = lock_app(db, app_id)
    raw, app.key_hash, app.key_hint = issue_key()
    app.updated_by = actor
    app.key_rotated_at = app.updated_at = beijing_now()
    result = {"id": app.id, "api_key": raw, "key_hint": app.key_hint}
    db.commit()
    return result


def get_app(db, app_id):
    app = db.get(GatewayApp, app_id)
    if not app:
        raise GatewayError(404, "app_not_found", "站点应用不存在")
    return app_dict(db, app)


def list_apps(db, page, page_size, search=""):
    query = db.query(GatewayApp)
    if search:
        query = query.filter(GatewayApp.name.contains(search, autoescape=True))
    total = query.count()
    now = beijing_now()
    start, end = day_window(now)
    items = []
    for app in query.order_by(GatewayApp.id.desc()).offset((page - 1) * page_size).limit(page_size):
        item = app_dict(db, app)
        today = db.query(GatewayRequest).filter(GatewayRequest.app_id == app.id,
                                               GatewayRequest.created_at >= start, GatewayRequest.created_at < end).all()
        occupied = db.query(GatewayRequest).filter(GatewayRequest.app_id == app.id, GatewayRequest.status.in_(OCCUPIED)).all()
        item.update(today_calls=len(today),
                    tokens_prompt=sum(r.tokens_prompt or 0 for r in today),
                    tokens_completion=sum(r.tokens_completion or 0 for r in today),
                    unknown_usage=sum(r.usage_status != "known" for r in today),
                    failures=sum(r.status in ("error", "timeout", "unknown") for r in today),
                    occupied=len(occupied),
                    needs_review=sum(now - r.created_at >= timedelta(seconds=75) for r in occupied),
                    last_used_at=db.execute(select(func.max(GatewayRequest.created_at)).where(GatewayRequest.app_id == app.id)).scalar())
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_requests(db, app_id, page, page_size, status=None, date_from=None, date_to=None):
    get_app(db, app_id)
    query = db.query(GatewayRequest).filter_by(app_id=app_id)
    if status:
        query = query.filter(GatewayRequest.status == status)
    if date_from:
        query = query.filter(GatewayRequest.created_at >= date_from)
    if date_to:
        query = query.filter(GatewayRequest.created_at < date_to + timedelta(days=1))
    total = query.count()
    now = beijing_now()
    items = []
    for row in query.order_by(GatewayRequest.id.desc()).offset((page - 1) * page_size).limit(page_size):
        item = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        item["can_resolve"] = row.status in OCCUPIED and now - row.created_at >= timedelta(seconds=75)
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def resolve_request(db, app_id, request_id, reason, actor):
    lock_app(db, app_id)
    row = db.execute(select(GatewayRequest).where(GatewayRequest.app_id == app_id,
        GatewayRequest.request_id == request_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    now = beijing_now()
    if row is None:
        raise GatewayError(404, "request_not_found", "调用记录不存在")
    if row.status not in OCCUPIED or now - row.created_at < timedelta(seconds=75):
        raise GatewayError(409, "request_not_resolvable", "请求仍在执行时限内或已处理")
    row.status = "timeout"
    row.resolved_at = now
    row.resolved_by = actor
    row.resolution_reason = reason
    row.finished_at = row.finished_at or now
    db.commit()
    return {"request_id": request_id, "status": "timeout"}


def options(db):
    owners = db.execute(select(ArkUser.id, ArkUser.real_name).where(
        ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)).order_by(ArkUser.real_name)).all()
    candidates = db.execute(select(AiPreset.preset_name).join(AiProvider, AiProvider.id == AiPreset.provider_id).where(
        AiPreset.is_enabled.is_(True), AiPreset.deleted_at.is_(None),
        AiProvider.is_enabled.is_(True), AiProvider.deleted_at.is_(None), AiProvider.provider_type == "direct",
    ).order_by(AiPreset.id)).scalars().all()
    presets = []
    for name in candidates:
        try:
            snapshot = prepare_text_chat(db, name, get_settings().AI_GATEWAY_MAX_OUTPUT_TOKENS)
        except ValueError:
            continue  # Configuration filtering, not an operational failure.
        presets.append({"id": snapshot.preset.id, "name": name, "model": snapshot.preset.model})
    return {"owners": [{"id": r.id, "name": r.real_name} for r in owners], "presets": presets}
