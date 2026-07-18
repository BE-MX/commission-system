"""PM Hub 鉴权：白名单用户名换 HMAC token，无密码。

设计要点（docs/requirements/2026-07-17-pm-material-hub.md §3/§8）：
- token = base64url(username|exp|epoch) + "." + HMAC-SHA256 截断签名，30 天有效
- require_pm_member 每请求验签 + 回查 ark_pm_members.is_active——移除名单立即生效
- PM_TOKEN_EPOCH 是全局版本号 salt，极端情况 +1 全员重新验证
- entry 失败提示不区分原因（防枚举），限速双维度：用户名 5 次/分钟 + 真实 IP 20 次/分钟
  （IP 取云 Nginx 的 X-Real-IP——proxy_set_header 覆盖式写入不可伪造，2026-07-18 已核实
  pm.leshine.conf；XFF 只信末位；全办公室共享出口 IP，IP 阈值须容纳全员并发进入）
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
_ENTRY_RATE_LIMIT = 5  # 同一用户名每分钟最多失败次数
_ENTRY_IP_RATE_LIMIT = 20  # 同一真实 IP 每分钟最多失败次数（办公室全员共享一个出口 IP）
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


class EntryRateLimiter:
    """entry 接口内存滑动窗口限速，key 任意（用户名 / 真实 IP），单机单进程够用。

    只计失败尝试——合法用户不被自己历史的成功进入误伤；
    定期淘汰过期 key，防长期运行内存缓涨。"""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._last_gc = time.time()

    def _gc(self, now: float) -> None:
        if now - self._last_gc < _ENTRY_RATE_WINDOW * 5:
            return
        self._last_gc = now
        for key in [k for k, v in self._hits.items() if not v or v[-1] < now - _ENTRY_RATE_WINDOW]:
            self._hits.pop(key, None)

    def hit_and_check(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            self._gc(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] < now - _ENTRY_RATE_WINDOW:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    def exceeded(self, key: str) -> bool:
        """只读检查（不计数）：用于验证前预检。"""
        now = time.time()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return False
            while hits and hits[0] < now - _ENTRY_RATE_WINDOW:
                hits.popleft()
            return len(hits) >= self._limit


entry_rate_limiter = EntryRateLimiter(_ENTRY_RATE_LIMIT)
entry_ip_rate_limiter = EntryRateLimiter(_ENTRY_IP_RATE_LIMIT)


def client_ip(request: Request) -> str:
    """生产链路（云 Nginx → frp → 本地）后端直连 addr 恒为隧道地址，真实 IP 只能取头。

    X-Real-IP 由云 Nginx proxy_set_header 覆盖式写入（客户端伪造值到不了后端）；
    XFF 用 $proxy_add_x_forwarded_for 追加，只有末位可信；本地开发直连无头，落 client.host。"""
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"


def check_entry_rate(username: str, ip: str) -> None:
    """失败计数：双维度各记一次，任一维度到阈值抛 429（提示与验证失败一致，防枚举）。

    调用方只有在验证失败后才应调用本函数——由 router 保证只在失败路径调用。"""
    user_ok = entry_rate_limiter.hit_and_check(username)
    ip_ok = entry_ip_rate_limiter.hit_and_check(ip)
    if not user_ok or not ip_ok:
        logger.warning("[PM] entry rate limited: %s (ip=%s)", username, ip)
        print(f"[PM] entry rate limited: {username} (ip={ip})", flush=True)
        raise HTTPException(status_code=429, detail=_ENTRY_FAIL_MESSAGE)


def entry_rate_exceeded(username: str, ip: str) -> bool:
    """只读预检（不计数）：任一维度已达阈值即拦。"""
    return entry_rate_limiter.exceeded(username) or entry_ip_rate_limiter.exceeded(ip)


def entry_fail() -> HTTPException:
    """统一失败提示，不区分「用户名不存在」与限速（防枚举）。"""
    return HTTPException(status_code=401, detail=_ENTRY_FAIL_MESSAGE)
