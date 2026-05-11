"""短链接生成工具（本地存储,基于 ark_short_links 表）"""

import hashlib
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.short_link import ArkShortLink

logger = logging.getLogger("commission.shortlink")
settings = get_settings()

_REUSE_WINDOW_DAYS = 7
_MAX_RETRIES = 5


def _compute_code(url: str, salt: str = "") -> str:
    raw = f"{url}|{salt}|{time.time_ns()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:6]


def generate_short_link(url: str) -> str:
    """生成短链。
    - 同 original_url 7 天内复用已有 short_code
    - 否则取 MD5(url + 当前时间戳) 前 6 位作为 short_code,冲突时重试
    - 返回完整短链 URL: {SHORT_LINK_BASE_URL}/s/{short_code}
    任何异常时回退返回原始 URL,不阻断业务流程。
    """
    base = settings.SHORT_LINK_BASE_URL.rstrip("/")
    if not url:
        return base

    db = SessionLocal()
    try:
        # 1. 同 URL 7 天内复用
        cutoff = datetime.now() - timedelta(days=_REUSE_WINDOW_DAYS)
        existing = (
            db.query(ArkShortLink)
            .filter(ArkShortLink.original_url == url)
            .filter(ArkShortLink.created_at >= cutoff)
            .order_by(ArkShortLink.created_at.desc())
            .first()
        )
        if existing:
            return f"{base}/s/{existing.short_code}"

        # 2. 生成新短码,冲突时换 salt 重试
        for attempt in range(_MAX_RETRIES):
            code = _compute_code(url, salt=str(attempt))
            row = ArkShortLink(short_code=code, original_url=url)
            db.add(row)
            try:
                db.commit()
                return f"{base}/s/{code}"
            except IntegrityError:
                db.rollback()
                continue

        logger.warning("生成短码连续 %d 次冲突,回退返回原始 URL", _MAX_RETRIES)
        return url
    except Exception as exc:
        db.rollback()
        logger.warning("生成短链失败,回退原始 URL: %s", exc)
        return url
    finally:
        db.close()
