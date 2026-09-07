"""Scene metadata and editable-field contract, with no generation prose."""

import json
from pathlib import Path

_CATALOG = json.loads(Path(__file__).with_name("scene_catalog.json").read_text(encoding="utf-8"))
TRYON_SCENES = _CATALOG["tryon"]
SCENES = _CATALOG["scene"]
SCENE_KEYS = frozenset(f"{mode}:{item['key']}" for mode, items in _CATALOG.items() for item in items)

# The names and allowed variables are the renderer's contract. Actual text is in DB.
PART_FIELDS = [
    {"key": "tryon_base", "label": "换发主体", "group": "main", "required": True,
     "variables": {"description": "所选发型描述", "extra": "发型库中的补充合成要求"}},
    {"key": "finish", "label": "面部与皮肤处理", "group": "main", "variables": {}},
    {"key": "keep_background", "label": "保持原背景", "group": "main", "variables": {}},
    {"key": "replace_background", "label": "换发场景与服装", "group": "main", "variables": {"scene": "所选场景描述"}},
    {"key": "framing", "label": "换发场景构图", "group": "main", "variables": {}},
    {"key": "tryon_tail", "label": "换发画质收尾", "group": "main", "variables": {}},
    {"key": "portrait_spec", "label": "换发输出规格说明", "group": "main", "variables": {}},
    {"key": "scene_base", "label": "佩戴实拍场景主体", "group": "main", "required": True,
     "variables": {"scene": "所选场景描述"}},
    {"key": "scene_tail", "label": "佩戴实拍画质收尾", "group": "main", "variables": {}},
    {"key": "color_text", "label": "文字发色要求", "group": "details",
     "variables": {"name": "发色名称", "code": "发色色号", "hex_part": "下方颜色数值片段", "description": "下方发色描述片段"}},
    {"key": "color_reference", "label": "从组合参考图取色", "group": "details", "variables": {}},
    {"key": "color_description", "label": "发色描述片段", "group": "details", "variables": {"description": "发色库中的描述"}},
    {"key": "color_hex", "label": "颜色数值片段", "group": "details", "variables": {"hex": "颜色数值"}},
    {"key": "wardrobe", "label": "随机穿搭要求", "group": "details", "variables": {"look": "本次随机选择的穿搭"}},
    {"key": "jewelry", "label": "随机首饰要求", "group": "details", "variables": {"jewelry": "本次随机选择的首饰"}},
]
PARTS_BY_KEY = {item["key"]: item for item in PART_FIELDS}


def editor_metadata() -> dict:
    return {
        "parts": PART_FIELDS,
        "scenes": [{"key": f"{mode}:{item['key']}", "label": item["label"], "mode": mode}
                   for mode, items in _CATALOG.items() for item in items],
    }
