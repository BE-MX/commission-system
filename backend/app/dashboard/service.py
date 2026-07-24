"""工作台配置 — service 层

一人一行 upsert；并发 PUT 撞 unique(user_id) 时 rollback 后转 update 重试一次
（IntegrityError 兜底从查询盖到 commit，cerebrum 2026-07-14）。
"""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dashboard.models import DashboardPreference
from app.dashboard.schemas import DashboardPrefs

logger = logging.getLogger("commission")


def get_prefs(db: Session, user_id: int) -> dict | None:
    """读用户配置；无行返回 None（前端按注册表默认渲染）。"""
    row = (
        db.query(DashboardPreference)
        .filter(DashboardPreference.user_id == user_id)
        .first()
    )
    return row.prefs if row else None


def upsert_prefs(db: Session, user_id: int, prefs: DashboardPrefs) -> dict:
    """保存（覆盖）用户配置，返回落库后的 prefs。"""
    payload = prefs.model_dump()
    try:
        row = (
            db.query(DashboardPreference)
            .filter(DashboardPreference.user_id == user_id)
            .first()
        )
        if row:
            row.prefs = payload
        else:
            db.add(DashboardPreference(user_id=user_id, prefs=payload))
        db.commit()
    except IntegrityError:
        # 并发双端同时首次保存：后到者 INSERT 撞 unique(user_id)，转 update 重试
        db.rollback()
        logger.warning("dashboard prefs upsert race for user %s, retry as update", user_id)
        print(f"[dashboard] prefs upsert race user={user_id}, retry as update", flush=True)
        row = (
            db.query(DashboardPreference)
            .filter(DashboardPreference.user_id == user_id)
            .first()
        )
        if row is None:  # 理论不可达：撞 unique 说明行已存在
            raise
        row.prefs = payload
        db.commit()
    return payload


def reset_prefs(db: Session, user_id: int) -> None:
    """删行恢复默认——之后注册表的变更（新卡片）对该用户自然生效。"""
    (
        db.query(DashboardPreference)
        .filter(DashboardPreference.user_id == user_id)
        .delete()
    )
    db.commit()
