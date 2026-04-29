"""短链接生成与物流商查询 URL 映射"""

import secrets
import string
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tracking import ShipmentTracking

_ALPHABET = string.ascii_letters + string.digits  # base62
_CODE_LENGTH = 8

settings = get_settings()

# 物流商官网查询 URL 模板，{waybill_no} 会被替换为实际运单号
CARRIER_TRACKING_URLS: dict[str, str] = {
    "DHL": "https://www.dhl.com/cn-zh/home/tracking/tracking-parcel.html?submit=1&tracking-id={waybill_no}",
    "FEDEX": "https://www.fedex.com/fedextrack/?trknbr={waybill_no}",
    "UPS": "https://www.ups.com/track?tracknum={waybill_no}&loc=zh_CN",
    "TNT": "https://www.tnt.com/express/zh_cn/site/shipping-tools/tracking.html?searchType=con&cons={waybill_no}",
}


def generate_short_code(db: Session, max_retries: int = 10) -> str:
    """生成唯一的 8 位短码，冲突时自动重试"""
    for _ in range(max_retries):
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
        exists = (
            db.query(ShipmentTracking.id)
            .filter(ShipmentTracking.short_code == code)
            .first()
        )
        if not exists:
            return code
    raise RuntimeError("Failed to generate unique short code after max retries")


def build_carrier_tracking_url(carrier: str, waybill_no: str) -> str:
    """根据物流商和运单号构建官网查询 URL"""
    template = CARRIER_TRACKING_URLS.get(carrier.upper())
    if template:
        return template.format(waybill_no=quote(waybill_no, safe=""))
    # 回退：Google 搜索
    return f"https://www.google.com/search?q={quote(carrier + ' tracking ' + waybill_no)}"


def build_short_link(short_code: str) -> str:
    """拼接完整的短链接 URL"""
    base = settings.SHORT_LINK_BASE_URL.rstrip("/")
    return f"{base}/s/{short_code}"
