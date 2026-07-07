"""备货管理 — 库存状态判定回归测试（纯函数，无 DB）

覆盖范围说明：
- `app/stock/sku_query.py` 的 query_all_sku_status 中，状态判定逻辑本身没有内嵌在
  SQL 里，而是委托给 `app/stock/constants.py` 的纯函数 calc_status / calc_suggested_qty，
  输入为 effective_enable_count = enable_count + production_in_transit（生产在途口径，
  见 sku_query.py L120-124）。本文件直接测这些纯函数，并模拟 sku_query 的
  effective_enable_count 组合口径做边界断言。
- SQL 聚合部分（跨库 JOIN okki_orders/okki_inventory）不在本文件覆盖范围内，
  需要真实 MySQL 双库环境，无法在 SQLite 内存库中纯函数化测试。
"""

import pytest

# calc_status / calc_suggested_qty 即 sku_query.py 调用的判定函数（从 constants 导入）
from app.stock.constants import (
    SOURCE_FORMULA,
    SOURCE_MANUAL,
    SOURCE_TFT,
    calc_status,
    calc_suggested_qty,
    source_code,
    source_label,
)


class TestCalcStatus:
    """状态四态：unset / shortage / warning / sufficient"""

    def test_unset_when_no_safety_stock(self):
        assert calc_status(100, 0) == "unset"
        assert calc_status(0, 0) == "unset"
        assert calc_status(100, None) == "unset"

    def test_shortage_below_safety_stock(self):
        assert calc_status(99, 100) == "shortage"
        assert calc_status(0, 100) == "shortage"
        assert calc_status(99.9, 100) == "shortage"

    def test_boundary_equal_safety_stock_is_warning(self):
        # enable == safety_stock：不低于安全库存但 < 1.5 倍 → warning
        assert calc_status(100, 100) == "warning"

    def test_warning_between_1x_and_1_5x(self):
        assert calc_status(149, 100) == "warning"
        assert calc_status(149.99, 100) == "warning"

    def test_boundary_1_5x_is_sufficient(self):
        # enable == safety_stock * 1.5：闭区间落在 sufficient
        assert calc_status(150, 100) == "sufficient"

    def test_sufficient_above_1_5x(self):
        assert calc_status(151, 100) == "sufficient"
        assert calc_status(10000, 100) == "sufficient"

    def test_negative_enable_count_is_shortage(self):
        assert calc_status(-5, 100) == "shortage"


class TestEffectiveEnableCount:
    """sku_query 口径：effective_enable_count = enable_count + production_in_transit"""

    def test_in_transit_lifts_shortage_to_warning(self):
        enable, in_transit, ss = 80.0, 30, 100
        # 仅看现有库存是 shortage
        assert calc_status(enable, ss) == "shortage"
        # 纳入生产在途后 110 落入 [100, 150) → warning
        assert calc_status(enable + in_transit, ss) == "warning"

    def test_in_transit_lifts_warning_to_sufficient(self):
        enable, in_transit, ss = 120.0, 40, 100
        assert calc_status(enable, ss) == "warning"
        assert calc_status(enable + in_transit, ss) == "sufficient"

    def test_zero_in_transit_keeps_status(self):
        enable, ss = 50.0, 100
        assert calc_status(enable + 0, ss) == calc_status(enable, ss) == "shortage"

    def test_suggested_qty_uses_effective_count(self):
        # 建议备货量应扣减在途：safety_stock*2 - (enable + in_transit)
        enable, in_transit, ss = 80.0, 30, 100
        assert calc_suggested_qty(enable + in_transit, ss) == 90  # 200 - 110
        assert calc_suggested_qty(enable, ss) == 120              # 200 - 80


class TestCalcSuggestedQty:
    """建议备货量 = max(0, safety_stock × 2 - enable_count)"""

    def test_basic(self):
        assert calc_suggested_qty(50, 100) == 150

    def test_zero_when_stock_ample(self):
        assert calc_suggested_qty(300, 100) == 0
        assert calc_suggested_qty(200, 100) == 0  # 恰好 2 倍 → 0

    def test_float_enable_count_truncated(self):
        # int() 截断：enable 10.9 按 10 计
        assert calc_suggested_qty(10.9, 100) == 190

    def test_zero_safety_stock(self):
        assert calc_suggested_qty(50, 0) == 0


class TestSourceLabelRoundtrip:
    """安全库存来源码 ↔ 标签"""

    @pytest.mark.parametrize("code,label", [
        (0, SOURCE_MANUAL),
        (1, SOURCE_FORMULA),
        (2, SOURCE_TFT),
    ])
    def test_label_and_code(self, code, label):
        assert source_label(code) == label
        assert source_code(label) == code

    def test_unknown_code_falls_back_to_manual(self):
        assert source_label(99) == SOURCE_MANUAL
        assert source_label(None) == SOURCE_MANUAL

    def test_unknown_label_falls_back_to_zero(self):
        assert source_code("whatever") == 0
