"""Seed the WhatsApp translation glossary dictionary type.

Type `whatsapp_glossary_<lang>` is consumed by
`app.whatsapp_translation.glossary_service`. The generic dict management page
already provides editing, so we only insert starter rows when the type is
empty (idempotent; admin edits are never overwritten).
"""

import logging

from app.core.database import SessionLocal
from app.system.models import SysDict
from app.whatsapp_translation.constants import SUPPORTED_TARGET_LANGUAGES
from app.whatsapp_translation.glossary_service import glossary_dict_type

logger = logging.getLogger("commission")

# (lang, chinese term, foreign term, remark)
_START = [
    ("en", "最小起订量", "MOQ", "minimum order quantity；日常可写成 MOQ"),
    ("en", "交期", "lead time", "production lead time；勿写成 delivery time 混淆物流时效"),
    ("en", "物流时效", "shipping time", "transit time；与 lead time 区分"),
    ("en", "形式发票", "proforma invoice", "PI；正式发票用 commercial invoice"),
    ("en", "电汇", "T/T", "telegraphic transfer；付款方式"),
    ("en", "信用证", "L/C", "letter of credit；付款方式"),
    ("en", "到岸价", "CIF", "cost, insurance and freight；贸易术语"),
    ("en", "离岸价", "FOB", "free on board；贸易术语"),
    ("en", "出厂价", "EXW", "ex works；贸易术语"),
    ("en", "样品费", "sample fee", "sample charge"),
    ("en", "免费样品", "free sample", "free sample"),
    ("en", "按样做货", "make to sample", "按客户样品定制"),
    ("en", "起订量", "MOQ", "常用；与最小起订量一致"),
    ("en", "大货", "bulk order", "bulk production / bulk order"),
    ("en", "补货", "restock", "replenishment / restock"),
    ("en", "色号", "color number", "如 #1B；国外也常用 shade"),
    ("en", "发色", "hair color", "hair color"),
    ("en", "发质", "hair grade", "如 Remy / Virgin 分档"),
    ("en", "顺发", "remy", "hair cuticle aligned"),
    ("en", "女士边幅", "weft", "weft hair；也称 hair weft"),
    ("en", "贴片", "clip-in", "clip-in hair extensions"),
    ("en", "接发", "hair extensions", "统称"),
    ("en", "假发", "wig", "wig；与 hair extensions 区分"),
    ("en", "头套", "wig cap", "网帽 base"),
    ("en", "发网", "lace cap", "lace base / lace cap"),
    ("en", "克重", "weight", "克重；如 100g"),
    ("en", "长度", "length", "英寸 inch；发长"),
    ("en", "订单", "order", "order"),
    ("en", "下单", "place an order", "place an order"),
]


def seed_whatsapp_translation_glossary() -> None:
    """启动时初始化术语表种子（幂等，失败不阻塞启动）。"""
    try:
        _seed()
    except Exception as e:
        logger.warning("whatsapp translation glossary seed skipped: %s", e)
        print(f"whatsapp translation glossary seed skipped: {e}", flush=True)


def _seed() -> None:
    to_seed = [row for row in _START if row[0] in SUPPORTED_TARGET_LANGUAGES]
    with SessionLocal() as db:
        for lang in SUPPORTED_TARGET_LANGUAGES:
            if lang == "zh-CN":
                continue
            dict_type = glossary_dict_type(lang)
            exists = (
                db.query(SysDict.id)
                .filter(SysDict.type == dict_type)
                .first()
            )
            if exists is not None:
                continue
            rows = [row for row in to_seed if row[0] == lang]
            if not rows:
                continue
            for sort, (_, code, label, remark) in enumerate(rows):
                db.add(SysDict(
                    type=dict_type,
                    code=code,
                    label=label,
                    sort=sort,
                    is_active=True,
                    remark=remark,
                ))
            db.commit()
            logger.info("seeded whatsapp translation glossary type=%s rows=%d", dict_type, len(rows))
