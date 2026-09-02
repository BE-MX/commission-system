"""内贸域常量。

产品类型与订单类别是**结构性枚举**，刻意不进 sys_dict：
它们驱动前端条件渲染和路线映射结构，加一个值必须改代码，
放进字典是假灵活。属性值域（工艺/网底色/尺寸/长度/发量）才走字典。
"""

# 产品类型 → 展示名
PRODUCT_TYPES = {"cap": "头套", "piece": "发片"}

# 订单类别 → 展示名
ORDER_CATEGORIES = {"normal": "普货", "special": "特单"}

# 订单类型/渠道是描述性值域，由 sys_dict 维护
ORDER_TYPE_DICT = "domestic_order_type"
ORDER_CHANNEL_DICT = "domestic_order_channel"

# 客户档案值域（客户表单下拉数据源，由 sys_dict 维护）
CUSTOMER_SOURCE_DICT = "domestic_customer_source"
CUSTOMER_STORE_TYPE_DICT = "domestic_store_type"
CUSTOMER_LEVEL_DICT = "domestic_customer_level"
CUSTOMER_LIFECYCLE_DICT = "domestic_customer_lifecycle"

# 属性值域字典 type（前端下拉的数据源，由内贸属性切换命令维护）
DICT_CAP_CRAFT = "domestic_cap_craft"
DICT_CAP_NET_COLOR = "domestic_cap_net_color"
DICT_CAP_SIZE = "domestic_cap_size"
DICT_CAP_LENGTH = "domestic_cap_length"
DICT_CAP_DENSITY = "domestic_cap_density"
DICT_CAP_HAIR_STYLE_SERIES = "domestic_cap_hair_style_series"
DICT_PIECE_CRAFT_SIZE = "domestic_piece_craft_size"
DICT_PIECE_LENGTH = "domestic_piece_length"

# 按产品类型给出该类型用到的字典 type，前端据此条件渲染
ATTR_DICTS = {
    "cap": {
        "craft": DICT_CAP_CRAFT,
        "net_color": DICT_CAP_NET_COLOR,
        "size": DICT_CAP_SIZE,
        "length": DICT_CAP_LENGTH,
        "density": DICT_CAP_DENSITY,
        "hair_style_series": DICT_CAP_HAIR_STYLE_SERIES,
    },
    "piece": {
        "craft": DICT_PIECE_CRAFT_SIZE,
        "length": DICT_PIECE_LENGTH,
    },
}

# 特单自定义工艺只能继承这两条固定路线，不能让下单人临时选择路线。
DEFAULT_ROUTE_NAMES = {
    "cap": "头套网帽（递针）",
    "piece": "发片网底（递针）",
}

# 订单状态
ORDER_DRAFT = 0
ORDER_PRODUCING = 1
ORDER_DONE = 2
ORDER_SHIPPED = 3
ORDER_TERMINATED = 4
ORDER_STATUS_LABELS = {0: "草稿", 1: "生产中", 2: "已完工", 3: "已发货", 4: "已终止"}

# 明细状态
ITEM_PRODUCING = 0
ITEM_DONE = 1
ITEM_SHIPPED = 2
ITEM_STATUS_LABELS = {0: "生产中", 1: "已完工", 2: "已发货"}

# 二维码前缀。外贸是 ARK-P，内贸 ARK-D，小程序按前缀分流互不干扰
QR_PREFIX = "ARK-D"
# 逐件码。明细码继续用于兼容批量报工，逐件码用于精确到 A1-01 的模式。
UNIT_QR_PREFIX = "ARK-DU"

# 普通角色用两项权限二选一；两项都有（如 super_admin）时批量模式优先。
REPORT_QUANTITY_PERMISSION = "domestic_quantity_report:write"
REPORT_UNIT_PERMISSION = "domestic_unit_report:write"

# 逐件二维码会按数量物化数据库行，给单据设置双层上限，避免误录或恶意请求
# 一次创建数万/数十万行拖垮 API。追加和改单也必须复用同一口径。
MAX_ORDER_ITEMS = 50
MAX_ORDER_UNITS = 5000
# 小程序免登录进度页路径（订单进度小程序码 page 参数）
TRACK_PAGE = "pages/domestic/track/track"
