"""内贸域常量。

产品类型与订单类型是**结构性枚举**，刻意不进 sys_dict：
它们驱动前端条件渲染和路线映射结构，加一个值必须改代码，
放进字典是假灵活。属性值域（工艺/网底色/尺寸/长度/发量）才走字典。
"""

# 产品类型 → 展示名
PRODUCT_TYPES = {"cap": "头套", "piece": "发片"}

# 订单类型 → 展示名
ORDER_TYPES = {"normal": "普货", "special": "特单"}

# 属性值域字典 type（前端下拉的数据源，初值见 081 迁移）
DICT_CAP_CRAFT = "domestic_cap_craft"
DICT_NET_COLOR = "domestic_net_color"
DICT_PIECE_CRAFT = "domestic_piece_craft"
DICT_CAP_SIZE = "domestic_cap_size"
DICT_PIECE_SIZE = "domestic_piece_size"
DICT_LENGTH = "domestic_length"
DICT_DENSITY = "domestic_density"

# 按产品类型给出该类型用到的字典 type，前端据此条件渲染
ATTR_DICTS = {
    "cap": {
        "craft": DICT_CAP_CRAFT,
        "net_color": DICT_NET_COLOR,
        "size": DICT_CAP_SIZE,
        "length": DICT_LENGTH,
        "density": DICT_DENSITY,
    },
    "piece": {
        "craft": DICT_PIECE_CRAFT,
        "size": DICT_PIECE_SIZE,
        "length": DICT_LENGTH,
        "density": DICT_DENSITY,
    },
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
