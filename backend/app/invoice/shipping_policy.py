"""Payment and express channel must agree before an invoice is saved."""


def validate_payment_channel(method: str | None, channel: str | None) -> None:
    convenient = alibaba_order_required(method)
    customs_9610 = "9610" in (channel or "")
    if convenient and not customs_9610:
        raise ValueError("付款方式包含“便捷发货”时，快递渠道必须包含“9610”，请修改快递渠道")
    if customs_9610 and not convenient:
        raise ValueError("快递渠道包含“9610”时，付款方式必须包含“便捷发货”，请选择对应付款方式")


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
