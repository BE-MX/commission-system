"""存量标签 → 新体系映射定义（2026-07-22 生产库快照逐值核对）

结构：
- MAPPING: (旧维度name, 旧值) → [(新维度name, 新值, priority), ...]
  priority 用于单选维度冲突裁决：同一素材多个来源映射到同一单选维度时，
  高优先级胜出；同优先级不同值 → 进冲突清单人工裁决。
  约定：5=明确具体值  4=较具体  3=一般  2=兜底  1=最弱兜底
- REVIEW_NOTES: 需设计部确认的条目备注（导出 Excel 时标黄）
- normalize_color(): 色号规范化（格式规则 + 显式修正 + 产品前缀拆分）

未出现在 MAPPING 里的旧值 = 明确放弃（零使用的活动场次名等），
retag 脚本执行时会重验使用量并把仍有使用的未映射值列入报告。
"""

# ── 素材类型 (asset_type) ────────────────────────────────
_ASSET_TYPE = {
    "产品图片": [("content_category", "产品素材", 3)],
    "产品视频": [("content_category", "产品素材", 3)],
    "活动图片": [("content_category", "公司活动", 3)],
    "活动视频": [("content_category", "公司活动", 3)],
    "工厂图片": [("content_category", "公司实力", 2)],
    "设计图片": [("content_category", "营销设计", 3)],
    "营销素材": [("content_category", "营销设计", 3)],
    # 国际站AI陪跑: 0 使用，放弃
}

# ── 素材子类 (asset_type_2) ──────────────────────────────
_ASSET_SUBTYPE = {
    "产品展示":     [("content_type", "产品展示", 4)],
    "公司活动":     [("content_type", "其他活动", 1)],   # 具体活动类型由综合标签给出，此为兜底
    "拍摄风格":     [],                                   # 分组文件夹无信息，风格由综合标签给出
    "生产流程":     [("content_category", "生产工艺", 5), ("content_type", "工艺流程记录", 4)],
    "产品制作流程": [("content_category", "生产工艺", 5), ("content_type", "工艺流程记录", 4)],
    "内容号":       [("content_category", "营销设计", 4), ("content_type", "内容号", 5)],
    "色块色板":     [("content_type", "色板色卡", 5)],
    "节日活动":     [("content_type", "其他活动", 2)],
    "问候图":       [("content_category", "营销设计", 4), ("content_type", "问候图", 5)],
    "新贸节":       [("theme", "新贸节", 5)],
    "产品合集":     [("content_type", "产品合集", 5)],
    "包装与工具":   [("content_type", "包装配件", 5)],
    "产品对比":     [("content_type", "产品对比", 5)],
    # content_type 优先级 4：与综合标签「门头+厂房」(p5) 同现时让更具体值胜出
    "工厂环境":     [("content_category", "公司实力", 4), ("content_type", "工厂环境", 4)],
    "详情页":       [("content_category", "营销设计", 4), ("content_type", "详情页", 5)],
    "产品佩戴":     [("content_type", "佩戴效果", 5)],
    "包装展示":     [("content_type", "包装配件", 4)],
    "证书":         [("content_category", "公司实力", 4), ("content_type", "证书资质", 5)],
    "公司宣传片":   [("content_category", "公司实力", 4), ("content_type", "公司宣传片", 5)],
    "清洗测试":     [("content_type", "清洗测试", 5)],
    "原材料说明":   [("content_type", "原材料说明", 5)],
    "其他设计":     [("content_category", "营销设计", 4), ("content_type", "其他设计", 2)],
}

# ── 综合标签 (others)，仅使用量 >0 的值 ──────────────────
_PROCESS_COMMON = [("content_category", "生产工艺", 4), ("content_type", "工艺流程记录", 3)]
_OTHERS = {
    # 产品（族级/具体）
    "天才发帘": [("product_type", "天才发帘", 5)],
    "天才":     [("product_type", "天才发帘", 5)],
    "双层天才": [("product_type", "双层天才", 5)],
    "接发":     [("product_type", "接发条类", 5)],
    "贴发":     [("product_type", "贴发类", 5)],
    "发帘":     [("product_type", "发帘类", 5)],
    "卡子发":   [("product_type", "卡子发类", 5)],
    "打孔发帘": [("product_type", "发帘类", 4)],
    "自然色mini发帘": [("product_type", "发帘类", 4)],
    "各品类视频重新剪辑": [("product_type", "多品类", 5), ("content_type", "产品展示", 2)],
    "接发工具": [("product_type", "配件工具", 5), ("content_type", "包装配件", 3)],
    "包装":     [("product_type", "包装", 5), ("content_type", "包装配件", 3)],
    "色板":     [("product_type", "色板", 5), ("content_type", "色板色卡", 4)],
    # 公司活动
    "年会":     [("content_type", "年会", 5)],
    "启动会":   [("content_type", "启动会", 5)],
    "复盘会":   [("content_type", "复盘总结会", 5)],
    "团建聚餐": [("content_type", "团建聚餐", 5)],
    "节日福利": [("content_type", "节日福利", 5)],
    "其他活动": [("content_type", "其他活动", 2)],
    # 拍摄风格
    "INS风格":  [("shoot_style", "INS风", 5)],
    "白底图":   [("shoot_style", "白底图", 5)],
    "AI模特佩戴图": [("shoot_style", "AI生成", 5), ("content_type", "佩戴效果", 4)],
    "库存产品色块图": [("shoot_style", "库存间实拍", 5), ("content_type", "色板色卡", 4)],
    "库存相近色对比": [("shoot_style", "库存间实拍", 5), ("content_type", "产品对比", 4)],
    # 营销设计
    "内容号短视频": [("content_type", "内容号", 5)],
    "内容号视频":   [("content_type", "内容号", 5)],
    "周末问候":     [("content_type", "问候图", 5)],
    "节日问候":     [("content_type", "问候图", 5)],
    "节日主题":     [("content_type", "节日海报", 2)],
    "倒计时视频":   [("content_type", "倒计时物料", 5)],
    "倒计时图片":   [("content_type", "倒计时物料", 5)],
    # 节日
    "圣诞活动":       [("theme", "圣诞节", 5), ("content_type", "其他活动", 2)],
    "七夕":           [("theme", "七夕", 5)],
    "情人节":         [("theme", "情人节", 5)],
    "万圣节":         [("theme", "万圣节", 5)],
    "万圣节派送糖果": [("theme", "万圣节", 5), ("content_type", "其他活动", 2)],
    "六一儿童节":     [("theme", "儿童节", 5)],
    "妇女节":         [("theme", "妇女节", 5)],
    # 工艺环节（序号前缀去除；产品专属步骤拆成 环节+产品 两维）
    "01-原材料":   [("process_step", "原材料", 5)] + _PROCESS_COMMON,
    "02-拉档发":   [("process_step", "拉档发", 5)] + _PROCESS_COMMON,
    "03-档发":     [("process_step", "投料", 4)] + _PROCESS_COMMON,
    "04-砸双针":   [("process_step", "砸双针", 5)] + _PROCESS_COMMON,
    "05-洗头发":   [("process_step", "洗头发", 5)] + _PROCESS_COMMON,
    "06-漂染":     [("process_step", "漂染", 5)] + _PROCESS_COMMON,
    "07-烘干":     [("process_step", "烘干", 5)] + _PROCESS_COMMON,
    "08-拆双针":   [("process_step", "拆双针", 5)] + _PROCESS_COMMON,
    "09-熟料":     [("process_step", "拉发熟料", 5)] + _PROCESS_COMMON,
    "09-拉发-熟料": [("process_step", "拉发熟料", 5)] + _PROCESS_COMMON,
    "10-机织":     [("process_step", "成品制作", 4), ("product_type", "机织发帘", 4)] + _PROCESS_COMMON,
    "11-跑帘子":   [("process_step", "跑帘子", 5)] + _PROCESS_COMMON,
    "12-抹胶":     [("process_step", "成品制作", 4), ("product_type", "贴发类", 4)] + _PROCESS_COMMON,
    "13-砸贴发":   [("process_step", "成品制作", 4), ("product_type", "贴发类", 4)] + _PROCESS_COMMON,
    "14-包装":     [("process_step", "绑发包装", 5)] + _PROCESS_COMMON,
    "工艺流程":    _PROCESS_COMMON,
    "跟单质检和包装过程": [("content_category", "生产工艺", 4), ("content_type", "质检包装", 5)],
    # 公司实力
    "门头+厂房": [("content_category", "公司实力", 4), ("content_type", "门头厂房", 5)],
    # 其他
    "接发详情页": [("content_type", "详情页", 5), ("product_type", "接发条类", 5)],
    "清洗Curly":  [("content_type", "清洗测试", 4), ("texture", "Curly", 5)],
    "天才清洗":   [("content_type", "清洗测试", 4), ("product_type", "天才发帘", 5)],
    "未压缩":     [("media_trait", "未压缩原片", 5)],
    "发型纹理":   [("content_type", "产品展示", 1)],
    # 明确放弃（有使用量但信息已由他处承载或无检索价值）：
    "横版": [],       # orientation 字段自动计算
    "竖版": [],       # orientation 字段自动计算
    "已压缩": [],     # 默认态，无检索价值
    "视频": [],       # file_type 字段已承载
    "其他产品": [],   # 无具体产品信息，content_category 已由素材类型给出
}

MAPPING: dict[tuple[str, str], list[tuple[str, str, int]]] = {}
for _old_dim, _table in (("asset_type", _ASSET_TYPE), ("asset_type_2", _ASSET_SUBTYPE), ("others", _OTHERS)):
    for _old_val, _targets in _table.items():
        MAPPING[(_old_dim, _old_val)] = _targets

# 年份维度沿用，不参与映射；颜色维度走 normalize_color()

# ── 需设计部确认的条目（Excel 导出标黄） ─────────────────
REVIEW_NOTES = {
    ("others", "03-档发"): "旧值无对应新环节，建议归「投料」，请确认",
    ("others", "10-机织"): "按「成品制作+机织发帘」拆分，请确认",
    ("others", "12-抹胶"): "抹胶是贴发制程，按「成品制作+贴发类」拆分，请确认",
    ("others", "13-砸贴发"): "按「成品制作+贴发类」拆分，请确认",
    ("others", "打孔发帘"): "旧值未区分4个变体，只能归到「发帘类」族级，请确认",
    ("others", "自然色mini发帘"): "无法确定是天才/机织，归「发帘类」族级，请确认",
    ("others", "其他产品"): "无具体产品信息，建议不映射（内容大类已保留），请确认",
    ("others", "节日主题"): "无法确定具体节日，暂归「节日海报」，请确认",
    ("others", "发型纹理"): "具体纹理需看图判断（二期AI补标），暂归「产品展示」，请确认",
    ("color", "#5ATTP5A-1006"): "疑似 #5ATP5A-1006 的笔误（TT），未自动合并，请确认",
    ("color", "#5AP9A-1001"): "疑似 #5ATP9A-1001 的笔误（缺T），未自动合并，请确认",
}

# ── 色号规范化 ───────────────────────────────────────────

# 显式修正（规则处理不了的个案）：旧值 → 规范值
COLOR_FIXES = {
    "#Cookie cream": "#Cookies Cream",
    "#Cookie Cream": "#Cookies Cream",
    "#RoseGolden": "#Rose Golden",
    "#pink": "#Pink",
    "#burg": "#Burg",
    "#M2-60（混色比例2：8）": "#M2-60(2:8)",
}

# 产品前缀混写值：旧值 → (product_type值, 色号原值)
COLOR_PRODUCT_SPLIT = {
    "半片PU卡子发-#2": ("半片PU卡子发", "#2"),
    "蕾丝卡子发-#2": ("蕾丝卡子发", "#2"),
    "尼龙绳接发-#5A": ("尼龙绳接发", "#5A"),
    "普通机织发帘卡子发-#P14A-613": ("机织卡子发", "#P14A-613"),
    "鱼线发帘-#24": ("鱼线发帘", "#24"),
}


def normalize_color(raw: str) -> list[tuple[str, str, int]]:
    """旧颜色值 → [(新维度, 新值, priority), ...]

    规则：产品前缀拆分 → 显式修正 → 通用格式化
    （去空格、双连字符并一、比例统一半角冒号、`+` 组合拆多色）。
    """
    raw = raw.strip()
    targets: list[tuple[str, str, int]] = []

    if raw in COLOR_PRODUCT_SPLIT:
        product, color = COLOR_PRODUCT_SPLIT[raw]
        targets.append(("product_type", product, 5))
        raw = color

    if raw in COLOR_FIXES:
        targets.append(("color_code", COLOR_FIXES[raw], 5))
        return targets

    # `+` 组合色拆开（如 #4TP8-18+2TP2-8 是双色组合素材）
    parts = raw.split("+") if "+" in raw else [raw]
    for part in parts:
        code = part.strip()
        if not code:
            continue
        if not code.startswith("#"):
            code = "#" + code
        code = code.replace("比", ":").replace("：", ":")
        code = code.replace(" ", "")          # "#5ATP18B 62"→"#5ATP18B62"? 先去空格再修连字符
        # 空格原本是连字符位（#5ATP18B 62 → #5ATP18B-62）：字母后紧跟数字段无分隔时不好判断，
        # 用启发式：去空格后若形如 …[A-Z]数字段 且原值含空格，补连字符
        if " " in part.strip():
            import re
            m = re.match(r"^(#.*[A-Z])(\d+)$", code)
            if m:
                code = f"{m.group(1)}-{m.group(2)}"
        while "--" in code:
            code = code.replace("--", "-")
        targets.append(("color_code", code, 5))
    return targets
