"""素材标签体系 v2 定义 — 唯一真相源

被两处消费：
1. tag_service.seed_default_dimensions —— 空表新环境全量种入（is_visible=1）
2. scripts/tag_taxonomy/* —— 生产存量库建新维度（is_visible=0 并存期）

方案：docs/requirements/2026-07-22-asset-tag-taxonomy.md
维度 name 避开存量库已占用的 asset_type / asset_type_2 / color / others / year；
年份维度沿用存量 name=year，仅新环境种子时创建。
"""

# 每个值: {"value": 中文规范名, "name_en": 英文名, "aliases": [别名...], "parent": 父级值(仅 content_type)}
# 简写: 纯字符串 = 只有 value

TAXONOMY_V2 = [
    {
        "name": "content_category", "label": "内容大类",
        "is_single_select": 1, "is_required": 1, "sort_order": 1,
        "values": [
            {"value": "产品素材", "name_en": "Product"},
            {"value": "生产工艺", "name_en": "Production Process"},
            {"value": "公司实力", "name_en": "Company Profile"},
            {"value": "公司活动", "name_en": "Company Events"},
            {"value": "营销设计", "name_en": "Marketing Design"},
        ],
    },
    {
        "name": "content_type", "label": "内容子类",
        "is_single_select": 1, "is_required": 1, "sort_order": 2,
        "values": [
            # 产品素材
            {"value": "产品展示", "name_en": "Product Display", "parent": "产品素材"},
            {"value": "细节图", "name_en": "Detail Shot", "parent": "产品素材"},
            {"value": "产品对比", "name_en": "Product Comparison", "parent": "产品素材"},
            {"value": "佩戴效果", "name_en": "Wearing Effect", "parent": "产品素材"},
            {"value": "产品合集", "name_en": "Product Collection", "parent": "产品素材"},
            {"value": "清洗测试", "name_en": "Wash Test", "parent": "产品素材"},
            {"value": "色板色卡", "name_en": "Color Ring & Swatch", "parent": "产品素材"},
            {"value": "包装配件", "name_en": "Packaging & Accessories", "parent": "产品素材"},
            {"value": "原材料说明", "name_en": "Raw Material Info", "parent": "产品素材"},
            # 生产工艺
            {"value": "工艺流程记录", "name_en": "Process Documentation", "parent": "生产工艺"},
            {"value": "质检包装", "name_en": "QC & Packing", "parent": "生产工艺"},
            # 公司实力
            {"value": "工厂环境", "name_en": "Factory Environment", "parent": "公司实力"},
            {"value": "门头厂房", "name_en": "Facade & Plant", "parent": "公司实力"},
            {"value": "公司宣传片", "name_en": "Company Video", "parent": "公司实力"},
            {"value": "证书资质", "name_en": "Certificates", "parent": "公司实力"},
            # 公司活动
            {"value": "年会", "name_en": "Annual Party", "parent": "公司活动"},
            {"value": "启动会", "name_en": "Kickoff Meeting", "parent": "公司活动"},
            {"value": "复盘总结会", "name_en": "Review Meeting", "parent": "公司活动"},
            {"value": "团建聚餐", "name_en": "Team Building", "parent": "公司活动"},
            {"value": "节日福利", "name_en": "Festival Benefits", "parent": "公司活动"},
            {"value": "班会培训", "name_en": "Training Session", "parent": "公司活动"},
            {"value": "其他活动", "name_en": "Other Events", "parent": "公司活动"},
            # 营销设计
            {"value": "详情页", "name_en": "Detail Page", "parent": "营销设计"},
            {"value": "问候图", "name_en": "Greeting Card", "parent": "营销设计"},
            {"value": "节日海报", "name_en": "Festival Poster", "parent": "营销设计"},
            {"value": "倒计时物料", "name_en": "Countdown Material", "parent": "营销设计"},
            {"value": "内容号", "name_en": "Content Channel", "parent": "营销设计"},
            {"value": "优势图", "name_en": "Advantage Graphic", "parent": "营销设计"},
            {"value": "AI效果图", "name_en": "AI Render", "parent": "营销设计"},
            {"value": "其他设计", "name_en": "Other Design", "parent": "营销设计"},
        ],
    },
    {
        "name": "product_type", "label": "产品类型",
        "is_single_select": 0, "is_required": 0, "sort_order": 3,
        "values": [
            {"value": "天才发帘", "name_en": "Genius Weft"},
            {"value": "双层天才", "name_en": "Double Drawn Genius Weft"},
            {"value": "加丝天才", "name_en": "Silk Genius Weft", "aliases": ["加丝天才发帘"]},
            {"value": "机织发帘", "name_en": "Machine Weft"},
            {"value": "鱼线发帘", "name_en": "Halo Weft", "aliases": ["Halo", "Fish Line"]},
            {"value": "打孔发帘-天才+天才", "name_en": "Hole Weft (Genius+Genius)"},
            {"value": "打孔发帘-天才+PU", "name_en": "Hole Weft (Genius+PU)"},
            {"value": "打孔发帘-机织+PU", "name_en": "Hole Weft (Machine+PU)"},
            {"value": "打孔发帘-机织+机织", "name_en": "Hole Weft (Machine+Machine)"},
            {"value": "普通贴发", "name_en": "Tape-in", "aliases": ["Tape in", "贴发"]},
            {"value": "机织贴发", "name_en": "Machine Weft Tape-in"},
            {"value": "双层贴发", "name_en": "Double Sided Tape-in", "aliases": ["半片贴发"]},
            {"value": "迷你贴发", "name_en": "Mini Tape-in", "aliases": ["Mini贴发"]},
            {"value": "机织长条贴发", "name_en": "Long Tape Machine Weft"},
            {"value": "平型", "name_en": "Flat Tip"},
            {"value": "迷你平型", "name_en": "Mini Flat Tip"},
            {"value": "棒棒", "name_en": "I-Tip", "aliases": ["Stick Tip"]},
            {"value": "迷你哑光棒棒", "name_en": "Mini Matte I-Tip", "aliases": ["哑光棒棒"]},
            {"value": "铁丝", "name_en": "Nano Ring", "aliases": ["Nano Tip"]},
            {"value": "Y-tip", "name_en": "Y-Tip"},
            {"value": "指甲", "name_en": "U-Tip", "aliases": ["Nail Tip"]},
            {"value": "塑料头接发", "name_en": "Plastic Tip Extension"},
            {"value": "尼龙绳接发", "name_en": "Nylon Loop Extension"},
            {"value": "羽毛接发", "name_en": "Feather Extension"},
            {"value": "拉环双头接发", "name_en": "Pull-Loop Double Tip"},
            {"value": "普通卡子发", "name_en": "Clip-in", "aliases": ["卡子发"]},
            {"value": "机织卡子发", "name_en": "Machine Weft Clip-in"},
            {"value": "半片PU卡子发", "name_en": "Half PU Clip-in"},
            {"value": "蕾丝卡子发", "name_en": "Lace Clip-in"},
            {"value": "多品类", "name_en": "Multi-Category", "aliases": ["全品类"]},
            {"value": "色板", "name_en": "Color Ring"},
            {"value": "包装", "name_en": "Packaging"},
            {"value": "配件工具", "name_en": "Accessories & Tools", "aliases": ["接发工具"]},
        ],
    },
    {
        # 值域主要由存量色号规范化后灌入 + 后续从发色数字化色板库同步；
        # 此处只种 ark_color_palette 的 12 个行业基础色，保证新环境可用
        "name": "color_code", "label": "色号",
        "is_single_select": 0, "is_required": 0, "sort_order": 4,
        "values": [
            {"value": "#1", "name_en": "Jet Black"},
            {"value": "#1B", "name_en": "Off Black"},
            {"value": "#2", "name_en": "Darkest Brown"},
            {"value": "#4", "name_en": "Chocolate Brown"},
            {"value": "#6", "name_en": "Chestnut Brown"},
            {"value": "#8", "name_en": "Ash Brown"},
            {"value": "#18", "name_en": "Dirty Blonde"},
            {"value": "#27", "name_en": "Honey Blonde"},
            {"value": "#33", "name_en": "Dark Auburn"},
            {"value": "#60", "name_en": "Platinum Blonde"},
            {"value": "#613", "name_en": "Light Blonde"},
            {"value": "#99J", "name_en": "Burgundy"},
        ],
    },
    {
        # 系统托管：由色号按规则推导（scripts/tag_taxonomy/derive.py），禁人工编辑
        "name": "color_family", "label": "色系",
        "is_single_select": 0, "is_required": 0, "sort_order": 5, "is_managed": 1,
        "values": [
            {"value": "黑色系", "name_en": "Black"},
            {"value": "棕色系", "name_en": "Brown"},
            {"value": "金色系", "name_en": "Blonde"},
            {"value": "红色系", "name_en": "Red"},
            {"value": "银灰系", "name_en": "Silver", "aliases": ["Grey", "灰色系"]},
            {"value": "时尚色", "name_en": "Vibrant", "aliases": ["Fashion Color", "彩色"]},
            {"value": "挑染", "name_en": "Piano Highlight", "aliases": ["Piano", "Highlight"]},
            {"value": "渐变", "name_en": "Ombre", "aliases": ["Balayage"]},
            {"value": "双段渐变", "name_en": "Two-Tone Ombre", "aliases": ["TP"]},
            {"value": "混色", "name_en": "Mixed", "aliases": ["Blend"]},
        ],
    },
    {
        "name": "texture", "label": "纹理造型",
        "is_single_select": 0, "is_required": 0, "sort_order": 6,
        "values": [
            {"value": "直发", "name_en": "Straight", "aliases": ["直条"]},
            {"value": "自然曲", "name_en": "Natural Wave"},
            {"value": "Body Wave", "name_en": "Body Wave", "aliases": ["Body"]},
            {"value": "Curly", "name_en": "Curly"},
            {"value": "Deep Wave", "name_en": "Deep Wave", "aliases": ["Deep"]},
        ],
    },
    {
        "name": "shoot_style", "label": "拍摄风格",
        "is_single_select": 1, "is_required": 0, "sort_order": 7,
        "values": [
            {"value": "白底图", "name_en": "White Background"},
            {"value": "INS风", "name_en": "Instagram Style", "aliases": ["INS风格", "ins"]},
            {"value": "库存间实拍", "name_en": "Stockroom Shot"},
            {"value": "模特佩戴", "name_en": "Model Wearing"},
            {"value": "手持实拍", "name_en": "Handheld Shot"},
            {"value": "细节特写", "name_en": "Close-up"},
            {"value": "AI生成", "name_en": "AI Generated", "aliases": ["AI模特"]},
        ],
    },
    {
        # 顺序由 sort_order 表达，值名不带序号前缀
        "name": "process_step", "label": "工艺环节",
        "is_single_select": 1, "is_required": 0, "sort_order": 8,
        "values": [
            {"value": "原材料", "name_en": "Raw Material"},
            {"value": "拉档发", "name_en": "Hair Drawing"},
            {"value": "投料", "name_en": "Feeding"},
            {"value": "砸双针", "name_en": "Double Needle Sewing"},
            {"value": "洗头发", "name_en": "Washing"},
            {"value": "漂染", "name_en": "Bleaching & Dyeing", "aliases": ["漂色", "染色"]},
            {"value": "烘干", "name_en": "Drying"},
            {"value": "拆双针", "name_en": "Double Needle Removal"},
            {"value": "拉发熟料", "name_en": "Processed Hair Drawing", "aliases": ["熟料"]},
            {"value": "分把称重", "name_en": "Weighing & Bundling"},
            {"value": "跑帘子", "name_en": "Weft Running"},
            {"value": "成品制作", "name_en": "Product Assembly"},
            {"value": "后处理", "name_en": "Post Processing", "aliases": ["抹胶"]},
            {"value": "绑发包装", "name_en": "Binding & Packing"},
        ],
    },
    {
        "name": "theme", "label": "节日营销主题",
        "is_single_select": 1, "is_required": 0, "sort_order": 9,
        "values": [
            {"value": "春节", "name_en": "Chinese New Year"},
            {"value": "情人节", "name_en": "Valentine's Day"},
            {"value": "妇女节", "name_en": "Women's Day"},
            {"value": "儿童节", "name_en": "Children's Day", "aliases": ["六一儿童节"]},
            {"value": "端午节", "name_en": "Dragon Boat Festival"},
            {"value": "七夕", "name_en": "Qixi Festival"},
            {"value": "中秋节", "name_en": "Mid-Autumn Festival"},
            {"value": "万圣节", "name_en": "Halloween"},
            {"value": "感恩节黑五", "name_en": "Thanksgiving & Black Friday", "aliases": ["黑五"]},
            {"value": "圣诞节", "name_en": "Christmas", "aliases": ["平安夜"]},
            {"value": "新贸节", "name_en": "New Trade Festival"},
            {"value": "采购节", "name_en": "Sourcing Festival"},
            {"value": "夏日度假", "name_en": "Summer Vacation"},
            {"value": "熊猫主题", "name_en": "Panda Theme"},
        ],
    },
    {
        # 生产库沿用存量 name=year 维度（值为「2022年」格式），此定义仅新环境种子用
        "name": "year", "label": "年份",
        "is_single_select": 1, "is_required": 1, "sort_order": 10,
        "values": ["2022年", "2023年", "2024年", "2025年", "2026年"],
    },
    {
        # 画幅（横竖版）走 ark_assets.orientation 字段自动计算，不在此维度
        "name": "media_trait", "label": "媒体特性",
        "is_single_select": 0, "is_required": 0, "sort_order": 11,
        "values": [
            {"value": "带字幕", "name_en": "Subtitled", "aliases": ["加字幕"]},
            {"value": "带水印", "name_en": "Watermarked"},
            {"value": "未压缩原片", "name_en": "Uncompressed Original", "aliases": ["未压缩"]},
        ],
    },
]


def iter_values(dim_def: dict):
    """统一 value 定义为 dict 形式迭代。"""
    for i, v in enumerate(dim_def["values"]):
        if isinstance(v, str):
            yield i, {"value": v, "name_en": None, "aliases": None, "parent": None}
        else:
            yield i, {"value": v["value"], "name_en": v.get("name_en"),
                      "aliases": v.get("aliases"), "parent": v.get("parent")}
