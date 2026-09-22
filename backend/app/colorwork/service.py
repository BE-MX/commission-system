"""colorwork 集成服务：SSO 令牌签发 + okki 实时库存状态计算。"""

from datetime import timedelta
import hashlib
import hmac
import logging
from urllib.parse import parse_qs, urlsplit

import httpx

from fastapi import HTTPException, status
from jose import jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.utils import create_access_token  # noqa: F401  (re-export 便于测试定位)
from app.colorwork.constants import (
    _SSO_TTL_SECONDS,
    TEMPLATE_MATCH,
    VIEW_PERMISSIONS,
)
from app.core.config import get_settings
from app.core.time import utc_now


def _sso_secret() -> str:
    settings = get_settings()
    return settings.COLORWORK_SSO_SECRET or hmac.new(
        settings.JWT_SECRET_KEY.encode(), b"ark-colorwork-sso", hashlib.sha256,
    ).hexdigest()


def sync_secret() -> str:
    settings = get_settings()
    return settings.COLORWORK_SYNC_KEY or hmac.new(
        settings.JWT_SECRET_KEY.encode(), b"ark-colorwork-inventory-sync", hashlib.sha256,
    ).hexdigest()


def allowed_views_for(user: dict) -> list[str]:
    """根据 JWT payload 中的角色/权限码，算出用户可进入的工作台视图。"""
    roles = user.get("roles", [])
    perms = user.get("permissions", [])
    return [
        view
        for view, perm in VIEW_PERMISSIONS.items()
        if "super_admin" in roles or perm in perms
    ]


def issue_sso_token(user: dict, views: list[str], display_name: str | None = None) -> str:
    """签发短命 SSO 令牌（HS256，默认 120s），供工作台换取自己的会话 Cookie。"""
    now = utc_now()
    payload = {
        "sub": str(user.get("sub", "")),
        "username": user.get("username", ""),
        "name": display_name or user.get("real_name") or user.get("username") or "方舟用户",
        "views": views,
        "aud": "colorwork",
        "iat": now,
        "exp": now + timedelta(seconds=_SSO_TTL_SECONDS),
    }
    return jwt.encode(payload, _sso_secret(), algorithm="HS256")


WORKBENCH_PATH = "/api/colorwork/workbench"
RELAY_HEADER = "x-ark-colorwork-relay"
logger = logging.getLogger(__name__)


def gateway_origin(relay_header: str | None = None) -> str:
    """The office relays to a fixed HTTPS owner; Beijing uses its local runtime."""
    origin = get_settings().COLORWORK_GATEWAY_ORIGIN.rstrip("/")
    if not origin:
        return ""
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query
            or parsed.fragment or parsed.username or parsed.password):
        raise HTTPException(503, "库存色块图北京网关地址配置无效")
    if relay_header:
        raise HTTPException(503, "库存色块图代理形成循环，请检查北京服务配置")
    return origin


def gateway_sso_link(view: str, authorization: str, origin: str) -> dict:
    """Obtain SSO from the data owner using the already authenticated Ark bearer."""
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.get(origin + "/api/colorwork/sso", params={"view": view},
                                  headers={"authorization": authorization, RELAY_HEADER: "1"})
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        # Neither credentials nor SSO URLs belong in logs.
        logger.warning("Colorwork SSO gateway unavailable: %s", type(error).__name__)
        print("Colorwork SSO gateway unavailable: " + type(error).__name__, flush=True)
        raise HTTPException(503, "无法连接北京库存色块图工作台，请稍后重试") from None
    if response.status_code != 200:
        detail = data.get("detail") if isinstance(data, dict) else None
        code = response.status_code if 400 <= response.status_code < 500 else 503
        raise HTTPException(code, detail if isinstance(detail, str) else "北京库存色块图工作台暂不可用")
    value = data.get("url") if isinstance(data, dict) else None
    try:
        url = urlsplit(value if isinstance(value, str) else "")
    except ValueError:
        raise HTTPException(503, "北京库存色块图工作台返回了无效的进入链接") from None
    query = parse_qs(url.query)
    if (url.scheme or url.netloc or url.path != WORKBENCH_PATH + "/api/auth/ark"
            or query.get("view") != [view] or not query.get("token")):
        raise HTTPException(503, "北京库存色块图工作台返回了无效的进入链接")
    return data


def build_sso_url(view: str, token: str) -> str:
    """Same-origin URL: browser must never connect to the internal runtime address."""
    return f"{WORKBENCH_PATH}/api/auth/ark?token={token}&view={view}"


def compute_template_statuses(db: Session, template_id: str) -> dict:
    """按模板计算各规格的实时库存状态。

    口径：okki_products 按名称前缀（+克重尾段）选中产品集合，LEFT JOIN 聚合
    okki_inventory.enable_count（disable_flag=0）按颜色和尺寸汇总：
    合计为 0 → restocking（正在补货），1–19 → low_stock（低库存），
    合计 ≥ 20 → normal（到货正常）。
    """
    rule = TEMPLATE_MATCH.get(template_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知的工作台模板: {template_id}",
        )
    if not rule["prefixes"]:
        return {
            "template_id": template_id,
            "unmapped": True,
            "statuses": {},
            "matched_products": 0,
            "source_synced_at": None,
            "synced_at": utc_now().isoformat(),
        }

    business_db = get_settings().BUSINESS_DB_NAME
    like_clauses = []
    params: dict = {}
    for index, prefix in enumerate(rule["prefixes"]):
        key = f"prefix_{index}"
        like_clauses.append(f"p.name LIKE :{key}")
        params[key] = f"{prefix}/%"
    weight_clause = ""
    if rule["weight"]:
        weight_clause = "AND p.name LIKE :weight_suffix"
        params["weight_suffix"] = f"%/{rule['weight']}"

    rows = db.execute(
        text(f"""
            SELECT p.color AS color, p.size AS size,
                   COALESCE(SUM(inv.enable_count), 0) AS available,
                   COUNT(DISTINCT p.product_id) AS product_count,
                   MAX(p.synced_at) AS product_synced_at
            FROM `{business_db}`.okki_products p
            LEFT JOIN (
                SELECT product_id, SUM(enable_count) AS enable_count
                FROM `{business_db}`.okki_inventory
                WHERE disable_flag = 0
                GROUP BY product_id
            ) inv ON inv.product_id = p.product_id
            WHERE p.disable_flag = 0
              AND ({" OR ".join(like_clauses)})
              {weight_clause}
            GROUP BY p.color, p.size
        """),
        params,
    ).mappings().all()

    statuses: dict[str, str] = {}
    matched_products = 0
    source_synced_at = None
    for row in rows:
        color = (row["color"] or "").strip()
        size = (row["size"] or "").strip()
        if not color or not size:
            continue
        # 尺寸统一去掉英寸后缀/小数（okki 实测为 '16' 纯数字字符串，防御性处理）
        size = size.replace('"', "").replace("inch", "").strip()
        if size.endswith(".0"):
            size = size[:-2]
        matched_products += int(row["product_count"])
        available = float(row["available"])
        statuses[f"{color}|{size}"] = (
            "restocking" if available <= 0
            else "low_stock" if available < 20
            else "normal"
        )
        product_synced_at = row["product_synced_at"]
        if product_synced_at is not None:
            # SQLite 测试库可能回字符串，MySQL 回 datetime；统一成可比较的 ISO 文本
            stamp = (
                product_synced_at.isoformat()
                if hasattr(product_synced_at, "isoformat")
                else str(product_synced_at)
            )
            if source_synced_at is None or stamp > source_synced_at:
                source_synced_at = stamp

    return {
        "template_id": template_id,
        "unmapped": False,
        "statuses": statuses,
        "matched_products": matched_products,
        "source_synced_at": source_synced_at,
        "synced_at": utc_now().isoformat(),
    }
