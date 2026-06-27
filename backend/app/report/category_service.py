"""报表中心 — 产品分类规则服务

分类规则是业务规则（源自《发帘与贴发产品清单.xlsx》），
供打印订单、打印工作台、Word/Excel 导出共享同一套分类。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List


# ── 型号分类规则 ─────────────────────────────────────────
# 规则源：发帘与贴发产品清单.xlsx（2026-06-15 更新）
# 每条规则按 Excel 顺序，先命中先胜出（model_includes / model_excludes / unit_includes / unit_excludes 同时满足）
# unit_includes / unit_excludes 为空 = 不限制 unit 字段
# label 中的 \n 在 HTML / Word 中均被渲染为换行
CATEGORY_RULES: List[Dict[str, Any]] = [
    {  # 1
        "model_includes": ["Deep"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "Deep天才发帘 帘宽12\"\n20g\n扁头银线3条/包",
    },
    {  # 2
        "model_includes": ["棒棒"], "model_excludes": ["哑光"],
        "unit_includes": [], "unit_excludes": [],
        "label": "棒棒\n1g\n25根/捆 50根/包",
    },
    {  # 3
        "model_includes": ["打孔"], "model_excludes": [],
        "unit_includes": ["60"], "unit_excludes": [],
        "label": "打孔发帘 帘宽33cm\n60g\n扁头银线1条/包",
    },
    {  # 4
        "model_includes": ["打孔"], "model_excludes": [],
        "unit_includes": ["50"], "unit_excludes": [],
        "label": "打孔发帘 帘宽33cm\n50g\n扁头银线1条/包",
    },
    {  # 5
        "model_includes": ["卡子"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "机织卡子发\n100g\n银线一套/包",
    },
    {  # 6
        "model_includes": ["机织贴发"], "model_excludes": ["长条"],
        "unit_includes": [], "unit_excludes": [],
        "label": "机织贴发 4*0.8cm\n2.5g\n20片/包",
    },
    {  # 7
        "model_includes": ["贴发", "长条"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "机织长条贴发 帘宽14\" 规格：0.8cm\n50g\n1条/包",
    },
    {  # 8
        "model_includes": ["加纱"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "加纱天才 帘宽12\"\n20g\n扁头银线3条/包",
    },
    {  # 9
        "model_includes": ["迷你", "平型"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "迷你平型 0.6*0.6cm\n0.8g\n25根/捆 50根/包",
    },
    {  # 10
        "model_includes": ["平型"], "model_excludes": ["迷你"],
        "unit_includes": [], "unit_excludes": [],
        "label": "平型接发 \n1g\n25根/捆 50根/包",
    },
    {  # 11
        "model_includes": ["三合片"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "三合片发帘 先花纹后齐边，帘宽90cm\n150g\n扁头银线1条/包",
    },
    {  # 12
        "model_includes": ["天才", "双层"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "双层天才发帘 帘宽12\"\n50g\n扁头银线1条/包",
    },
    {  # 13
        "model_includes": ["天才", "12"], "model_excludes": ["双层"],
        "unit_includes": [], "unit_excludes": [],
        "label": "天才发帘 帘宽12\"\n20g\n扁头银线3条/包",
    },
    {  # 14
        "model_includes": ["天才", "24"], "model_excludes": ["双层"],
        "unit_includes": [], "unit_excludes": [],
        "label": "天才发帘 帘宽24\"\n50g\n扁头银线1条/包",
    },
    {  # 15
        "model_includes": ["贴发"], "model_excludes": ["机织", "长条"],
        "unit_includes": [], "unit_excludes": [],
        "label": "贴发 4*0.8cm\n2.5g\n20片/包",
    },
    {  # 16
        "model_includes": ["铁丝"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "铁丝 \n1g\n25根/捆 50根/包",
    },
    {  # 17
        "model_includes": ["哑光棒棒"], "model_excludes": [],
        "unit_includes": [], "unit_excludes": [],
        "label": "哑光棒棒\n1g\n25根/捆 50根/包",
    },
]

OTHER_CATEGORY_INDEX = -1
OTHER_LABEL = "其他"


def classify(model: str, unit: str) -> tuple:
    """按 model + unit 关键字匹配规则，返回 (category_index, category_label)。

    优先级 = Excel 列表顺序，第一条命中即返回。全部不匹配归入 (-1, "其他")。
    """
    model = model or ""
    unit = unit or ""
    for idx, rule in enumerate(CATEGORY_RULES):
        if (
            all(s in model for s in rule["model_includes"])
            and not any(s in model for s in rule["model_excludes"])
            and all(s in unit for s in rule["unit_includes"])
            and not any(s in unit for s in rule["unit_excludes"])
        ):
            return idx, rule["label"]
    return OTHER_CATEGORY_INDEX, OTHER_LABEL


def split_by_category(long_items: List[Dict]) -> List[tuple]:
    """将长格式 rows 按 (model, unit) 双键分类，返回 [(cat_idx, label, items)]。

    输出顺序：Excel 规则顺序（cat_idx 升序），未匹配的 "其他" 永远放最后。
    """
    buckets: Dict[int, Dict[str, Any]] = {}
    for item in long_items:
        cat_idx, cat_label = classify(item.get("model", ""), item.get("unit", ""))
        if cat_idx not in buckets:
            buckets[cat_idx] = {"label": cat_label, "items": []}
        buckets[cat_idx]["items"].append(item)
    sorted_keys = sorted(buckets.keys(), key=lambda k: (k == OTHER_CATEGORY_INDEX, k))
    return [(k, buckets[k]["label"], buckets[k]["items"]) for k in sorted_keys]
