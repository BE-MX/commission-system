"""colorwork 集成服务：SSO 令牌签发 + okki 实时库存状态计算。"""

from datetime import timedelta

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
    return settings.COLORWORK_SSO_SECRET or settings.JWT_SECRET_KEY


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


def build_sso_url(view: str, token: str) -> str:
    base = get_settings().COLORWORK_BASE_URL.rstrip("/")
    return f"{base}/api/auth/ark?token={token}&view={view}"


def compute_template_statuses(db: Session, template_id: str) -> dict:
    """按模板计算各规格的实时库存状态。

    口径：okki_products 按名称前缀（+克重尾段）选中产品集合，LEFT JOIN 聚合
    okki_inventory.enable_count（disable_flag=0），合计 > 0 → normal（到货正常），
    否则 restocking（正在补货）。与 stock/public_service 的有货口径一致。
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
                   COUNT(DISTINCT p.product_id) AS product_count
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
        statuses[f"{color}|{size}"] = "normal" if float(row["available"]) > 0 else "restocking"

    return {
        "template_id": template_id,
        "unmapped": False,
        "statuses": statuses,
        "matched_products": matched_products,
        "synced_at": utc_now().isoformat(),
    }
