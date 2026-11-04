"""Payment and express channel must agree before an invoice is saved."""


def validate_payment_channel(method: str | None, channel: str | None) -> None:
    convenient = "便捷发货" in (method or "")
    customs_9610 = "9610" in (channel or "")
    if convenient and not customs_9610:
        raise ValueError("付款方式包含“便捷发货”时，快递渠道必须包含“9610”，请修改快递渠道")
    if customs_9610 and not convenient:
        raise ValueError("快递渠道包含“9610”时，付款方式必须包含“便捷发货”，请选择对应付款方式")
