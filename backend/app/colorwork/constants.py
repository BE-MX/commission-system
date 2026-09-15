"""库存色块图工作台（colorwork-workbench）集成常量。

工作台是独立部署的 vinext/Cloudflare Worker 子站点，方舟负责：
1. 功能入口 + 页面权限（本模块 SSO 签发）；
2. 实时库存状态数据源（okki_inventory.enable_count → 到货正常/正在补货）。

规格匹配口径（2026-09-14 与 lsordertest 实际数据核对）：
- 工作台模板 = 产品 + Radio（Regular/Super/Ultra Double Drawn）；
- okki_products.name 形如 ``Standard Double Drawn Genius Weft/16/#1B/20g``，
  即 ``{Drawn} {产品}/{尺寸}/{颜色}[/{克重}]``；Regular 在 okki 中记作 Standard；
- 规格状态按键 ``{颜色}|{尺寸}`` 下发（颜色带 # 前缀、尺寸为英寸整数字符串，
  与工作台 spec 的 color.code / length 一致）。
"""

# 工作台视图 → 方舟页面权限码（视图名与工作台前端 ?view= 参数一致）
VIEW_PERMISSIONS = {
    "library": "colorwork_download:read",   # 库存图直接下载
    "inventory": "colorwork_edit:read",     # 实时库存图修改
    "master": "colorwork_master:read",      # 原始库存图文件
}

VIEW_LABELS = {
    "library": "库存图直接下载",
    "inventory": "实时库存图修改",
    "master": "原始库存图文件",
}

_SSO_TTL_SECONDS = 120

# Radio → okki name 第一段可能写法（Regular 在 okki 记作 Standard，两种都匹配兜底）
_DRAWN_PREFIXES = {
    "regular": ["Standard Double Drawn", "Regular Double Drawn"],
    "super": ["Super Double Drawn"],
    "ultra": ["Ultra Double Drawn"],
}


def _rule(radio: str, *bases: str, weight: str | None = None) -> dict:
    """生成一个模板的匹配规则：prefixes = Drawn × 产品名，weight 为名尾克重段。"""
    return {
        "prefixes": [f"{drawn} {base}" for drawn in _DRAWN_PREFIXES[radio] for base in bases],
        "weight": weight,
    }


# 工作台 23 个模板（id 来自 colorwork-workbench/lib/generated-catalog.json）→ okki 匹配规则。
# 产品对应关系 2026-09-14 与业务确认：Butterfly Weft（Genius+Genius）= Double Genius Holes
# Weft，Injection Tape Hair = Invisible Tape Hair，Flex Weft = Volume Weft。
TEMPLATE_MATCH: dict[str, dict] = {
    "20g-genius-weft-regular": _rule("regular", "Genius Weft", weight="20g"),
    "20g-genius-weft-super": _rule("super", "Genius Weft", weight="20g"),
    "20g-genius-weft-ultra": _rule("ultra", "Genius Weft", weight="20g"),
    "50g-genius-weft-regular": _rule("regular", "Genius Weft", weight="50g"),
    "50g-genius-weft-super": _rule("super", "Genius Weft", weight="50g"),
    "50g-genius-weft-ultra": _rule("ultra", "Genius Weft", weight="50g"),
    "butterfly-weft-genius-genius-regular": _rule("regular", "Double Genius Holes Weft"),
    "butterfly-weft-genius-genius-super": _rule("super", "Double Genius Holes Weft"),
    "flex-weft-regular": _rule("regular", "Volume Weft"),
    "i-tip-hair-regular": _rule("regular", "I Tip Hair"),
    "i-tip-hair-ultra": _rule("ultra", "I Tip Hair"),
    "injection-tape-hair-super": _rule("super", "Invisible Tape Hair"),
    "invisible-tape-weft-super": _rule("super", "Invisible Tape Weft"),
    # K Tip Hair 按 okki 命名对应 Keratin Tip（前缀锚定，不会误匹配 Mini Keratin Tip）
    "k-tip-hair-regular": _rule("regular", "Keratin Tip Hair"),
    "k-tip-hair-super": _rule("super", "Keratin Tip Hair"),
    "k-tip-hair-ultra": _rule("ultra", "Keratin Tip Hair"),
    "nano-tip-hair-regular": _rule("regular", "Nano Tip Hair"),
    "nano-tip-hair-super": _rule("super", "Nano Tip Hair"),
    "nano-tip-hair-ultra": _rule("ultra", "Nano Tip Hair"),
    "silk-genius-weft-regular": _rule("regular", "Silk Genius Weft"),
    # 前缀锚定匹配，不会误伤 Invisible Tape Hair
    "tape-hair-regular": _rule("regular", "Tape Hair"),
    "tape-hair-super": _rule("super", "Tape Hair"),
    "tape-hair-ultra": _rule("ultra", "Tape Hair"),
}
