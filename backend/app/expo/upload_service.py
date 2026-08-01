"""展会扫码上传：令牌签发/校验 + 待取照片读写（2026-08-01）。

刻意不落库：令牌的两个职责——绑定到哪个客户、什么时候作废——都能用密码学表达。
若另立 ticket 表，「照片有没有传上来」就有两份真相（表里的 status 与磁盘上的文件），
必须保持同步；本项目已在这类不同步上栽过（素材域 folder_upload 静默失败）。
代价是令牌在有效期内可重复使用，靠 10 分钟短有效期 + kiosk 顾问预览兜住。

本模块不碰数据库，只处理令牌与文件，可脱离 DB 单测。
"""

import hashlib
import hmac
import logging
import re
import time
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.expo import ai_pipeline

logger = logging.getLogger("commission.expo")

TICKET_TTL_SECONDS = 600          # 10 分钟：够客户翻相册，又限制二维码被拍走后的滥用窗口
PENDING_DIR = ai_pipeline.UPLOAD_ROOT / "pending"
STALE_AFTER_SECONDS = 2 * 3600    # 待取照片留存上界
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# 免登录端点统一话术：不区分「格式错」与「签名错」——对客户来说都只有一个可行动作
# （回去重新扫码），暴露更细的原因没有意义，只会多一处需要翻译/维护的文案。
_INVALID_TOKEN_MSG = "上传链接无效，请回到展位屏幕重新扫码"
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{16}$")


def _sign(customer_id: int, exp: int) -> str:
    secret = get_settings().EXPO_UPLOAD_SIGN_SECRET
    msg = f"{customer_id}:{exp}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def secret_is_default() -> bool:
    """密钥还是仓库里的默认字面量 = 任何能读代码的人都能离线伪造上传令牌。

    上传页完全免登录，整个授权模型压在这个密钥上，默认值等于没锁。照 domestic
    的 qr_secret_is_default 办（app/domestic/report_service.py）：由调用方在发码
    端点上拒绝服务，逼着部署时配好 .env——而不是像 ASSET_SIGN_SECRET 那样
    留一句注释，然后一直跑在默认值上。
    """
    from app.core.config import Settings

    return get_settings().EXPO_UPLOAD_SIGN_SECRET == Settings.model_fields[
        "EXPO_UPLOAD_SIGN_SECRET"].default


def make_token(customer_id: int, ttl_seconds: int = TICKET_TTL_SECONDS) -> str:
    """签发上传令牌：{customer_id}-{过期时间戳}-{签名}。"""
    exp = int(time.time()) + ttl_seconds
    return f"{customer_id}-{exp}-{_sign(customer_id, exp)}"


def parse_token(token: str | None) -> int:
    """校验令牌并返回 customer_id；非法或过期抛 ValueError（文案直接面向客户）。

    从右往左只切两刀（customer_id 允许负数，本身可能带 "-"）；签名段先做
    形状校验再进 hmac.compare_digest —— 后者只接受可比较的 ASCII 字节串，
    非法字符（如中文、emoji）传进去会抛 TypeError 而不是 ValueError，在一个
    连鉴权都没有的公开端点上，这种未捕获的类型错误会变成 500。
    """
    parts = (token or "").rsplit("-", 2)
    if len(parts) != 3 or not _SIGNATURE_RE.match(parts[2]):
        raise ValueError(_INVALID_TOKEN_MSG)
    try:
        customer_id, exp = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(_INVALID_TOKEN_MSG) from None
    # 过期先于签名校验：过期的码无需再暴露签名是否正确
    if exp < time.time():
        raise ValueError("上传码已过期，请回到展位屏幕重新获取")
    if not hmac.compare_digest(parts[2], _sign(customer_id, exp)):
        raise ValueError(_INVALID_TOKEN_MSG)
    return customer_id
