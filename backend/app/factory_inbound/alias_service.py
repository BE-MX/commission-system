from fastapi import HTTPException
from sqlalchemy import select

from app.core.time import beijing_now
from app.factory_inbound.matching_rules import color_key, compact
from app.factory_inbound.models import Alias, AliasSuggestion
from app.factory_inbound.presentation import actor_id


def aliases(db, kind):
    rows = db.scalars(select(Alias).where(Alias.kind == kind).order_by(Alias.factory_term))
    return [{"id": row.id, "factory_term": row.factory_term, "target": row.target,
             "enabled": row.enabled, "source": row.source} for row in rows]


def save_alias(db, kind, body, user, alias_id=None):
    key = color_key(body.factory_term) if kind == "color" else compact(body.factory_term)
    target = body.target.strip()
    if not key or not target:
        raise HTTPException(422, "词条两端均须填写")
    existing = db.scalar(select(Alias).where(Alias.kind == kind, Alias.factory_term == key).with_for_update())
    if existing and existing.id != alias_id:
        raise HTTPException(409, "该词条已存在")
    if alias_id is None:
        row = Alias(kind=kind, source="manual")
        db.add(row)
    else:
        row = db.scalar(select(Alias).where(Alias.kind == kind, Alias.id == alias_id).with_for_update())
        if not row:
            raise HTTPException(404, "词条不存在")
    row.factory_term, row.target, row.enabled = key, target, body.enabled
    row.updated_by = actor_id(user)
    db.commit()
    return aliases(db, kind)


def suggestions(db):
    rows = db.scalars(select(AliasSuggestion).where(AliasSuggestion.status == "pending").order_by(AliasSuggestion.id))
    return [{"id": row.id, "factory_term": row.factory_term, "target": row.target,
             "suggested_by": row.suggested_by, "created_at": row.created_at} for row in rows]


def review(db, suggestion_id, accept, user):
    row = db.scalar(select(AliasSuggestion).where(AliasSuggestion.id == suggestion_id).with_for_update())
    if not row or row.status != "pending":
        raise HTTPException(409, "待审核建议已变化")
    actor = actor_id(user)
    if accept:
        existing = db.scalar(select(Alias).where(
            Alias.kind == "color", Alias.factory_term == row.factory_term,
        ).with_for_update())
        if existing and (not existing.enabled or color_key(existing.target) != color_key(row.target)):
            raise HTTPException(409, "建议与现有词条冲突，请核对词表")
        if not existing:
            db.add(Alias(kind="color", factory_term=row.factory_term, target=row.target,
                         source="reviewed", updated_by=actor))
    row.status = "accepted" if accept else "rejected"
    row.reviewed_by = actor
    row.reviewed_at = beijing_now()
    db.commit()
    return suggestions(db)
