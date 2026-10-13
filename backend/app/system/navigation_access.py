"""Validate additions against build-time navigation policy and live user permissions."""
import json
import logging
import hashlib
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.service import get_live_user_authorization

logger = logging.getLogger("commission")
MANIFEST_PATH = Path(__file__).with_name("navigation_access_manifest.json")
SOURCE_PATH = Path(__file__).resolve().parents[3] / "frontend" / "src" / "config" / "navigation.js"


def load_access_manifest() -> dict:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        source_hash = hashlib.sha256(SOURCE_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if manifest.get("source_sha256") != source_hash:
            raise ValueError("navigation access policy is out of date")
        policy = manifest.get("favorite_access")
        if not isinstance(policy, dict) or not policy:
            raise ValueError("missing favorite navigation access policy")
        for rules in policy.values():
            if not isinstance(rules, list) or not rules:
                raise ValueError("invalid navigation rules")
            for rule in rules:
                if not isinstance(rule, dict) or set(rule) - {"permission", "anyPermission"}:
                    raise ValueError("invalid navigation rule")
                if "permission" in rule and (not isinstance(rule["permission"], str) or not rule["permission"]):
                    raise ValueError("invalid navigation permission")
                if "anyPermission" in rule and (not isinstance(rule["anyPermission"], list) or not all(isinstance(code, str) and code for code in rule["anyPermission"])):
                    raise ValueError("invalid navigation permission list")
        return policy
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("navigation access manifest unavailable: %s", exc)
        print(f"[navigation] access manifest unavailable: {exc}", flush=True)
        raise HTTPException(503, "导航权限清单不可用，请联系管理员重新构建前端") from exc


def validate_additions(db: Session, user_id: int, existing: list[str], requested: list[str]) -> None:
    active = db.query(ArkUser.id).filter(
        ArkUser.id == user_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
    ).first()
    if active is None:
        raise HTTPException(403, "当前账号不可配置导航")
    additions = set(requested) - set(existing)
    if not additions:
        return  # Preserve previously saved hidden entries; do not grant access.
    policy = load_access_manifest()
    roles, permissions = get_live_user_authorization(db, user_id)
    permissions = set(permissions)
    for key in additions:
        rules = policy.get(key)
        if rules is None:
            raise HTTPException(403, "只能添加本人有权限访问的导航")
        if "super_admin" in roles:
            continue
        if not all(
            (not rule.get("permission") or rule["permission"] in permissions)
            and ("anyPermission" not in rule or any(code in permissions for code in rule["anyPermission"]))
            for rule in rules
        ):
            raise HTTPException(403, "只能添加本人有权限访问的导航")
