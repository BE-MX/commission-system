"""色系派生规则 — color_family 托管维度的唯一写入方

色系由色号结构推导：P+数字=挑染 / 数字+T=渐变 / 含TP=双段渐变 / M+数字=混色 /
纯色查色表。被三处消费：上传打标后同步、标签编辑后同步、存量迁移脚本 retag.py。
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PURE_FAMILY: dict[str, str] = {}
for _codes, _fam in [
    (["1", "1A", "1B"], "黑色系"),
    (["2", "2A", "2B", "4", "5", "5A", "6", "7", "8", "9", "9A", "10", "30"], "棕色系"),
    (["14", "16A", "18", "18A", "18B", "22", "24", "27", "60", "60A", "62",
      "613", "1001", "1006", "ASHBLONDE", "COOKIESCREAM"], "金色系"),
    (["33", "530", "BURG", "99J"], "红色系"),
    (["PINK", "ROSEGOLDEN"], "时尚色"),
]:
    for _c in _codes:
        _PURE_FAMILY[_c] = _fam


def derive_family(code: str) -> str:
    """色号 → 色系。结构前缀必须是 字母+数字（#M2-60 / #P1B-2），
    否则 #Pink 会被误判成挑染。"""
    body = code.lstrip("#").upper().replace(" ", "")
    if re.match(r"^M\d", body):
        return "混色"
    if re.match(r"^P\d", body):
        return "挑染"
    if "TP" in body:
        return "双段渐变"
    if re.match(r"^\d+[AB]{0,2}T", body):
        return "渐变"
    return _PURE_FAMILY.get(body, "时尚色")


def sync_color_family(db: Session, asset_id: int, version_id: int | None) -> None:
    """按素材当前色号标签重算色系标签（覆盖式）。失败不阻断主流程但必须留痕。

    调用方负责 commit。color_code / color_family 维度不存在时静默返回
    （老体系环境无这两个维度）。
    """
    from app.asset.models import TagDimension, TagValue, asset_tag_association as ata

    try:
        dims = {d.name: d.id for d in db.query(TagDimension).filter(
            TagDimension.name.in_(["color_code", "color_family"]))}
        code_dim, family_dim = dims.get("color_code"), dims.get("color_family")
        if not code_dim or not family_dim:
            return

        codes = [r.value for r in (
            db.query(TagValue.value)
            .join(ata, ata.c.tag_value_id == TagValue.id)
            .filter(ata.c.asset_id == asset_id, ata.c.dimension_id == code_dim)
        )]
        families = sorted({derive_family(c) for c in codes})

        family_ids = {v.value: v.id for v in db.query(TagValue).filter(
            TagValue.dimension_id == family_dim)}

        db.execute(ata.delete().where(
            ata.c.asset_id == asset_id, ata.c.dimension_id == family_dim))
        for fam in families:
            vid = family_ids.get(fam)
            if vid is None:
                logger.warning("color_family 值缺失: %s (asset=%s)", fam, asset_id)
                print(f"[asset] color_family value missing: {fam} asset={asset_id}", flush=True)
                continue
            db.execute(ata.insert().values(
                asset_id=asset_id, version_id=version_id,
                dimension_id=family_dim, tag_value_id=vid))
    except Exception as exc:
        logger.warning("sync_color_family failed asset=%s err=%s", asset_id, exc)
        print(f"[asset] sync_color_family failed asset={asset_id} err={exc}", flush=True)
