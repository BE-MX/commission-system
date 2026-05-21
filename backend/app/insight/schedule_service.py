"""方舟洞见 — 定时生成规则管理"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.insight.models import InsightScheduleRule
from app.insight.schemas import ScheduleRuleCreate, ScheduleRuleUpdate

logger = logging.getLogger("insight")


def list_rules(db: Session, is_active: Optional[bool] = None) -> list[InsightScheduleRule]:
    query = db.query(InsightScheduleRule)
    if is_active is not None:
        query = query.filter(InsightScheduleRule.is_active == is_active)
    return query.order_by(desc(InsightScheduleRule.created_at)).all()


def get_rule(db: Session, rule_id: int) -> InsightScheduleRule:
    r = db.query(InsightScheduleRule).filter(InsightScheduleRule.id == rule_id).first()
    if not r:
        raise ValueError(f"规则不存在: id={rule_id}")
    return r


def create_rule(db: Session, data: ScheduleRuleCreate) -> InsightScheduleRule:
    r = InsightScheduleRule(**data.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    logger.info("Created schedule rule id=%s name=%s", r.id, r.rule_name)
    return r


def update_rule(db: Session, rule_id: int, data: ScheduleRuleUpdate) -> InsightScheduleRule:
    r = get_rule(db, rule_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(r, field, value)
    db.commit()
    db.refresh(r)
    return r


def toggle_rule(db: Session, rule_id: int) -> InsightScheduleRule:
    r = get_rule(db, rule_id)
    r.is_active = not r.is_active
    db.commit()
    db.refresh(r)
    return r


def delete_rule(db: Session, rule_id: int) -> None:
    r = get_rule(db, rule_id)
    db.delete(r)
    db.commit()


def update_last_run(db: Session, rule_id: int) -> None:
    r = get_rule(db, rule_id)
    r.last_run_at = datetime.utcnow()
    db.commit()
