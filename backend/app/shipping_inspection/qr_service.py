"""发货检验出库单二维码 —— ARK-I:{outbound_record_id}:{hmac8}（仿 domestic report_service）

二维码承载出库单 id，HMAC-SHA256(QR_SIGN_SECRET) 截 8 位防伪造、防误扫他模块码。
"""

import hashlib
import hmac

from app.core.config import get_settings
from app.shipping_inspection import constants as C

settings = get_settings()


def generate_qr_sign(record_id: str, secret: str) -> str:
    message = f"{C.QR_PREFIX}:{record_id}"
    return hmac.new(key=secret.encode(), msg=message.encode(), digestmod=hashlib.sha256).hexdigest()[:8]


def generate_qr_data(record_id: str) -> str:
    return f"{C.QR_PREFIX}:{record_id}:{generate_qr_sign(record_id, settings.QR_SIGN_SECRET)}"


def qr_sign_matches(record_id: str, sign: str) -> bool:
    """当前密钥优先；轮换过渡期内用旧密钥兜底（同 domestic 的登录后扫码口径）。"""
    if hmac.compare_digest(sign, generate_qr_sign(record_id, settings.QR_SIGN_SECRET)):
        return True
    legacy = settings.QR_SIGN_SECRET_LEGACY
    return bool(legacy) and hmac.compare_digest(sign, generate_qr_sign(record_id, legacy))


def verify_qr_data(qr_raw: str) -> tuple[bool, str]:
    """校验出库单二维码，返回 (是否有效, outbound_record_id)。

    不是 ARK-I 前缀（外贸 ARK-P / 内贸 ARK-D 等他模块码）或签名不符一律无效。
    出库单 id 是字符串，用 rpartition 取最后一段签名，对 id 字符集不做假设。
    """
    raw = (qr_raw or "").strip()
    prefix = f"{C.QR_PREFIX}:"
    if not raw.startswith(prefix):
        return False, ""
    record_id, sep, sign = raw[len(prefix):].rpartition(":")
    if not sep or not record_id or len(sign) != 8:
        return False, ""
    return qr_sign_matches(record_id, sign), record_id
