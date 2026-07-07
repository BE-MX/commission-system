"""物流跟踪 — 统一状态映射回归测试（纯函数，无 DB）

覆盖 app/tracking/status.py：
- normalize_status: FedEx / DHL typeCode / DHL 高层状态 → unified_status
- 未知承运商 / 未知状态码的兜底行为
- PUSH_TRIGGER_STATUSES 推送触发集合成员
- get_status_label 中文标签
"""

import pytest

from app.tracking.status import (
    DHL_HIGHLEVEL_MAP,
    DHL_STATUS_MAP,
    FEDEX_STATUS_MAP,
    PUSH_TRIGGER_STATUSES,
    STATUS_LABELS,
    get_status_label,
    normalize_status,
)


class TestFedexNormalize:
    """FedEx scanEvent 事件码归一化"""

    @pytest.mark.parametrize("raw,expected", [
        ("PU", "picked_up"),
        ("OC", "picked_up"),
        ("IT", "in_transit"),
        ("DP", "in_transit"),
        ("AR", "in_transit"),
        ("OD", "out_for_delivery"),
        ("CC", "customs_hold"),
        ("CD", "customs_hold"),
        ("CU", "customs_hold"),
        ("OH", "customs_hold"),
        ("HP", "customs_hold"),
        ("DL", "delivered"),
        ("RS", "returned"),
        ("HL", "returned"),
        ("DE", "exception"),
        ("SE", "exception"),
        ("CA", "exception"),
        ("XP", "exception"),
    ])
    def test_known_codes(self, raw, expected):
        assert normalize_status("fedex", raw) == expected

    def test_lowercase_code_and_carrier_case_insensitive(self):
        # 状态码转大写匹配，承运商名大小写不敏感
        assert normalize_status("FedEx", "dl") == "delivered"
        assert normalize_status("FEDEX", "od") == "out_for_delivery"

    def test_unknown_code_falls_back_to_in_transit(self):
        assert normalize_status("fedex", "ZZ") == "in_transit"

    def test_empty_raw_returns_pending(self):
        assert normalize_status("fedex", "") == "pending"
        assert normalize_status("fedex", None) == "pending"


class TestDhlNormalize:
    """DHL typeCode + 高层状态归一化"""

    @pytest.mark.parametrize("raw,expected", [
        ("PU", "picked_up"),
        ("PL", "in_transit"),
        ("DF", "in_transit"),
        ("AF", "in_transit"),
        ("TR", "in_transit"),
        ("SM", "in_transit"),
        ("WC", "out_for_delivery"),
        ("OH", "customs_hold"),
        ("HP", "customs_hold"),
        ("RR", "customs_hold"),
        ("PY", "in_transit"),   # 付款完成恢复运输
        ("CR", "in_transit"),   # 清关完成恢复运输
        ("OK", "delivered"),
        ("DL", "delivered"),
        ("RS", "returned"),
        ("RT", "returned"),
        ("NU", "exception"),
        ("MS", "exception"),
    ])
    def test_type_codes(self, raw, expected):
        assert normalize_status("dhl", raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("pre-transit", "picked_up"),
        ("transit", "in_transit"),
        ("delivered", "delivered"),
        ("failure", "exception"),
        ("unknown", "in_transit"),
    ])
    def test_highlevel_status_compat(self, raw, expected):
        """兼容旧数据的高层状态（小写匹配）"""
        assert normalize_status("dhl", raw) == expected

    def test_typecode_takes_priority_over_highlevel(self):
        # "OK" 是 typeCode 命中 delivered；同名高层状态不存在，验证优先级路径
        assert normalize_status("DHL", "ok") == "delivered"

    def test_unknown_dhl_status_falls_back_to_in_transit(self):
        assert normalize_status("dhl", "whatever") == "in_transit"

    def test_empty_raw_returns_pending(self):
        assert normalize_status("dhl", "") == "pending"


class TestUnknownCarrier:
    """未知承运商的兜底行为"""

    def test_unified_status_passthrough(self):
        # 传入已是统一状态码 → 原样返回
        for code in STATUS_LABELS:
            assert normalize_status("ups", code) == code

    def test_unknown_status_falls_back_to_in_transit(self):
        assert normalize_status("ups", "SOME_RAW") == "in_transit"

    def test_empty_carrier_and_status(self):
        assert normalize_status(None, None) == "pending"
        assert normalize_status("", "delivered") == "delivered"


class TestPushTriggerStatuses:
    """钉钉推送触发集合：派送中/清关扣押/已签收/异常"""

    def test_exact_members(self):
        assert PUSH_TRIGGER_STATUSES == {
            "out_for_delivery", "customs_hold", "delivered", "exception",
        }

    def test_non_trigger_statuses_excluded(self):
        for status in ("picked_up", "in_transit", "returned", "pending"):
            assert status not in PUSH_TRIGGER_STATUSES

    def test_all_triggers_are_valid_unified_statuses(self):
        # 触发集合必须是 STATUS_LABELS 的子集，否则推送文案会缺标签
        assert PUSH_TRIGGER_STATUSES <= set(STATUS_LABELS)

    def test_all_map_targets_are_valid_unified_statuses(self):
        # 三张映射表的目标值都必须有中文标签
        targets = set(FEDEX_STATUS_MAP.values()) | set(DHL_STATUS_MAP.values()) | set(DHL_HIGHLEVEL_MAP.values())
        assert targets <= set(STATUS_LABELS)


class TestStatusLabel:
    def test_known_labels(self):
        assert get_status_label("delivered") == "已签收"
        assert get_status_label("customs_hold") == "清关/扣押"
        assert get_status_label("pending") == "待查询"

    def test_unknown_returns_input(self):
        assert get_status_label("mystery") == "mystery"

    def test_empty_returns_unknown_label(self):
        assert get_status_label("") == "未知"
        assert get_status_label(None) == "未知"
