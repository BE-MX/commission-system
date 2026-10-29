"""发货检验域常量。"""

from datetime import date

# 检验单状态
STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"

# 历史单据分界：出库日期早于该日的出库单发生在验货流程上线前，不再要求验货。
# 列表按「已提交」展示，不补建验货单记录（验货单列表与照片仍只统计真实提交）。
LEGACY_OUTBOUND_BEFORE = date(2026, 10, 1)

# 二维码前缀。外贸 ARK-P、内贸 ARK-D/ARK-DU、发货检验 ARK-I，小程序按前缀分流互不干扰
QR_PREFIX = "ARK-I"
