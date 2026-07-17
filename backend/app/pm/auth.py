"""PM Hub 鉴权：白名单用户名换 HMAC token，无密码。

设计要点（docs/requirements/2026-07-17-pm-material-hub.md §3/§8）：
- token = base64url(username|exp|epoch) + "." + HMAC-SHA256 截断签名，30 天有效
- require_pm_member 每请求验签 + 回查 ark_pm_members.is_active——移除名单立即生效
- PM_TOKEN_EPOCH 是全局版本号 salt，极端情况 +1 全员重新验证
- entry 失败提示不区分原因（防枚举），按用户名维度限速 5 次/分钟
  （生产链路 frp 隧道全员同 IP，IP 维度限速待 X-Forwarded-For 确认后再启用）
"""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.pm.models import PmMember

logger = logging.getLogger("commission")

_ENTRY_FAIL_MESSAGE = "无法验证，请联系亮哥"
_ENTRY_RATE_LIMIT = 5  # 同一用户名每分钟最多尝试次数
_ENTRY_RATE_WINDOW = 60


def _secret() -> str:
    settings = get_settings()
    return settings.PM_TOKEN_SECRET or settings.JWT_SECRET_KEY


def _sign(payload_b64: str) -> str:
    return hmac.new(_secret().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:32]


def issue_pm_token(username: str) -> str:
    """签发 token：payload 含用户名 + 过期时间 + 全局 epoch。"""
    settings = get_settings()
    exp = int(time.time()) + settings.PM_TOKEN_TTL_DAYS * 86400
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps({"u": username, "exp": exp, "e": settings.PM_TOKEN_EPOCH}, separators=(",", ":")).encode()
    ).decode()
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_pm_token(token: str) -> str | None:
    """验签 + 过期 + epoch 校验。通过返回 username，否则 None。"""
    if not token or "." not in token:
        return None
    payload_b64, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("u"):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    if int(payload.get("e", 0)) != get_settings().PM_TOKEN_EPOCH:
        return None
    return str(payload["u"])


@dataclass
class PmIdentity:
    """注入端点的当前身份。审计一律用 username，展示用 display_name。"""

    username: str
    display_name: str


def require_pm_member(request: Request, db: Session = Depends(get_db)) -> PmIdentity:
    """端点鉴权依赖：验签 + 每请求回查白名单（移除名单立即生效）。"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    username = verify_pm_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="验证已失效，请重新进入")
    member = (
        db.query(PmMember)
        .filter(PmMember.username == username, PmMember.is_active == 1)
        .first()
    )
    if not member:
        raise HTTPException(status_code=401, detail="验证已失效，请重新进入")
    return PmIdentity(username=member.username, display_name=member.display_name)


class _EntryRateLimiter:
    """entry 接口按用户名维度的内存滑动窗口限速（单机单进程够用）。"""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, username: str) -> bool:
        now = time.time()
        with self._lock:
            hits = self._hits.setdefault(username, deque())
            while hits and hits[0] < now - _ENTRY_RATE_WINDOW:
                hits.popleft()
            if len(hits) >= _ENTRY_RATE_LIMIT:
                return False
            hits.append(now)
            return True


entry_rate_limiter = _EntryRateLimiter()


def check_entry_rate(username: str) -> None:
    if not entry_rate_limiter.allow(username):
        logger.warning("[PM] entry rate limited: %s", username)
        print(f"[PM] entry rate limited: {username}", flush=True)
        raise HTTPException(status_code=429, detail=_ENTRY_FAIL_MESSAGE)


def entry_fail() -> HTTPException:
    """统一失败提示，不区分「用户名不存在」与限速（防枚举）。"""
    return HTTPException(status_code=401, detail=_ENTRY_FAIL_MESSAGE)
