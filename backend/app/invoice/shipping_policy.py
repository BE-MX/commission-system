"""Payment and express channel must agree before an invoice is saved.

Rule table (2026-11-24) is mirrored in the frontend
``views/invoice/composables/invoiceSettlement.js`` (PAYMENT_CHANNEL_GROUPS);
tests keep both copies identical.
"""

ANY_CHANNEL = "其他快递"
PAYMENT_CHANNEL_GROUPS = (
    {"key": "normal", "label": "普通付款",
     "methods": ("PayPal", "TT", "现金", "支付宝", "微信"),
     "channels": ("DHL普货", "FEDEX普货", "顺丰", "自提", "货代/海运")},
    {"key": "convenient", "label": "信保便捷发货",
     "methods": ("大莱莎信保（便捷发货）", "小莱莎信保（便捷发货）", "新莱莎信保（便捷发货）"),
     "channels": ("DHL9610", "FEDEX9610")},
    {"key": "customs", "label": "信保报关 / 对公转账",
     "methods": ("大莱莎信保（报关）", "小莱莎信保（报关）", "新莱莎信保（报关）", "对公转账（莱莎）", "对公转账（旭和）"),
     "channels": ("DHL报关", "FEDEX报关")},
)
# Values stored before 2026-11-04 mean the 普货 channel.
LEGACY_CHANNEL_ALIASES = {"DHL": "DHL普货", "FEDEX": "FEDEX普货"}


def _group_of_method(method: str | None) -> dict | None:
    for group in PAYMENT_CHANNEL_GROUPS:
        if method in group["methods"]:
            return group
    # Unregistered methods keep the original keyword contract for 便捷发货.
    if alibaba_order_required(method):
        return PAYMENT_CHANNEL_GROUPS[1]
    return None


def _group_of_channel(channel: str, *, keywords: bool = True) -> dict | None:
    channel = LEGACY_CHANNEL_ALIASES.get(channel, channel)
    for group in PAYMENT_CHANNEL_GROUPS:
        if channel in group["channels"]:
            return group
    # "9610" text has always required 便捷发货; "报关" free text only counts
    # when a registered payment method is present (keywords=True).
    if "9610" in channel:
        return PAYMENT_CHANNEL_GROUPS[1]
    if keywords and "报关" in channel:
        return PAYMENT_CHANNEL_GROUPS[2]
    return None


def _allowed_text(group: dict) -> str:
    return "、".join((*group["channels"], ANY_CHANNEL))


def validate_payment_channel(method: str | None, channel: str | None) -> None:
    method = (method or "").strip() or None
    channel = (channel or "").strip() or None
    method_group = _group_of_method(method)
    if channel is None:
        if method_group is PAYMENT_CHANNEL_GROUPS[1]:
            raise ValueError(f"付款方式「{method}」须选择快递渠道：{_allowed_text(method_group)}")
        return
    if channel == ANY_CHANNEL:
        return
    channel_group = _group_of_channel(channel, keywords=method_group is not None)
    if method_group is not None:
        # Registered payment: the channel must come from its own group.
        if channel_group is not method_group:
            raise ValueError(f"付款方式「{method}」只能选择快递渠道：{_allowed_text(method_group)}，请修改快递渠道")
        return
    # Missing/unregistered payment (portal, integrations): only the declaration
    # channels are bound to a payment group.
    if channel_group is not None and channel_group["key"] != "normal":
        raise ValueError(f"快递渠道「{channel}」须配合付款方式「{channel_group['label']}」，请选择对应付款方式")


def normalize_alibaba_order_no(value: str | None) -> str | None:
    """Store identifiers as text, retaining leading zeroes."""
    import re
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("阿里信保订单号须为文本数字")
    value = re.sub(r"\s+", "", value)
    if not value:
        return None
    if not re.fullmatch(r"[0-9]{15,20}", value):
        raise ValueError("阿里信保订单号须为15~20位数字")
    return value


def alibaba_order_required(method: str | None) -> bool:
    return "便捷发货" in (method or "")


def validate_alibaba_order(method: str | None, value: str | None) -> None:
    normalized = normalize_alibaba_order_no(value)
    if alibaba_order_required(method) and not normalized:
        raise ValueError("便捷发货必须填写阿里信保订单号")
