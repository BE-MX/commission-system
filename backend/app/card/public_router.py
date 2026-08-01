"""业务员电子名片公开路由（/api/card/{slug}/...）。

无 JWT 鉴权（宪法 3 白名单场景，已登记 scripts/check_conventions.py AUTH_EXEMPT_FILES）：
消费方是扫名片二维码的海外客户手机（leshine.work/card/<slug>/ 静态页），无任何登录态。

- /unlock：口令本身就是凭证——客户输入自己的邮箱或 WhatsApp 号，只解锁「该业务员名下、
  该联系方式」的档案；未命中一律同一句 404 文案，不暴露存在性。
- /inquiries：公开联系表单（等价 mailto），Pydantic 长度上限封顶；v1 不做限流，
  滥用时优先在云 Nginx 层加 limit_req（该路径独立、不影响其他 API）。
"""

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.card import service
from app.card.schemas import InquiryCreate, UnlockRequest
from app.core.database import get_db
from app.core.response import ok

logger = logging.getLogger("commission.card")

router = APIRouter()

_NOT_FOUND = "No file found for this passcode yet. Please check with your butler."
_RATE_MSG = "Too many attempts — please wait a minute and try again."

# 进程内滑窗限流（对抗性审查 P2-2 的应用层兜底；单 worker NSSM 部署下有效）。
# 生产链路 IP 可能被 nginx/frp 聚合成同一来源（XFF 优先，仍可能共享），阈值放宽到
# 30/分钟：足够展会现场多客户同时用，也把字典爆破压到无利可图。更硬的 per-IP
# 限流在云 nginx limit_req 做（见 docs/handoff.md 名片套件条目）。
_WINDOW_SECS = 60
_MAX_ATTEMPTS = 30
_attempts: dict[str, deque] = defaultdict(deque)


def _rate_limited(request: Request, bucket: str) -> bool:
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "?")
    key = f"{bucket}:{ip}"
    now = time.monotonic()
    dq = _attempts[key]
    while dq and now - dq[0] > _WINDOW_SECS:
        dq.popleft()
    if len(dq) >= _MAX_ATTEMPTS:
        return True
    dq.append(now)
    if len(_attempts) > 10000:  # 长期运行防字典无限膨胀
        _attempts.clear()
    return False


@router.post("/{slug}/unlock", summary="客户口令解锁展会档案")
def unlock(slug: str, payload: UnlockRequest, request: Request, db: Session = Depends(get_db)):
    if _rate_limited(request, "unlock"):
        return ok(code=429, message=_RATE_MSG)
    data = service.unlock(db, slug, payload.passcode)
    if data is None:
        # 统一文案：slug 不存在 / 口令无效 / 未命中 全部同响应，防枚举
        return ok(code=404, message=_NOT_FOUND)
    return ok(data)


@router.post("/{slug}/inquiries", summary="客户提交需求/问题")
def create_inquiry(slug: str, payload: InquiryCreate, request: Request, db: Session = Depends(get_db)):
    if _rate_limited(request, "inq"):
        return ok(code=429, message=_RATE_MSG)
    inquiry = service.create_inquiry(db, slug, payload.contact, payload.message)
    if inquiry is None:
        return ok(code=404, message="This page is not available.")
    return ok({"id": inquiry.id})
