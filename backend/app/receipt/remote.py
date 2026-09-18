"""OKKI receipt protocol, read-back and complete pagination. No mirror writes."""
from decimal import Decimal, InvalidOperation

from app.invoice import okki_client


def read(db, path, params=None):
    for force in (False, True):
        token = okki_client.ensure_access_token(db, force=force)
        data = okki_client._get_json(path, token, context="回款查询", params=params)
        if data is not None:
            return data
    raise okki_client.OkkiApiError("回款接口鉴权失败，请检查小满应用权限")


def receipt_types(db):
    data = read(db, "/v1/invoices/receipt/types")
    values = data.get("data") if isinstance(data, dict) else data
    if not isinstance(values, list) or not values or any(not isinstance(x, str) for x in values):
        raise ValueError("小满回款方式不可用，暂不能同步")
    return values


def receipt_info(db, receipt_id):
    data = read(db, "/v1/invoices/receipt/info", {"cash_collection_id": str(receipt_id)})
    if str(data.get("cash_collection_id")) != str(receipt_id):
        raise ValueError("小满回款详情缺少匹配 ID，需人工核对")
    return data


def order_receipts(db, order_id):
    # Official list has no order filter: exhaust pagination and filter locally.
    # Fail closed if the data changes during pagination or the scan is incomplete.
    found, seen, expected = [], set(), None
    for page in range(1, 501):
        data = read(db, "/v1/invoices/receipt/list", {"start_index": page, "count": 100, "removed": "0"})
        rows, total = data.get("list"), data.get("totalItem")
        if not isinstance(rows, list) or not str(total).isdigit():
            raise ValueError("小满回款列表不完整，余额待核验")
        total = int(total)
        if expected is not None and expected != total:
            raise ValueError("小满回款发生变动，请刷新余额重试")
        expected = total
        for row in rows:
            if not isinstance(row, dict) or "order_id" not in row:
                raise ValueError("小满回款列表缺少关联订单，余额待核验")
            identity = str(row.get("cash_collection_id") or "")
            if not identity or identity in seen:
                raise ValueError("小满回款分页重复或缺少 ID，余额待核验")
            seen.add(identity)
            if str(row.get("order_id")) == str(order_id):
                found.append(row)
        if len(seen) == total:
            return found
        if not rows or len(seen) > total:
            break
    raise ValueError("小满回款分页未完整读取，暂不能登记回款")


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal(".01")):
            raise ValueError("小满原币金额或精度异常，余额待核验")
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("小满原币金额无效，余额待核验") from exc
    return amount


def order_snapshot(db, invoice):
    if not invoice.xiaoman_order_id:
        return {"rows": [], "exchange_rate": None}
    data = read(db, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id})
    if (str(data.get("order_id")) != str(invoice.xiaoman_order_id)
            or str(data.get("company_id")) != str(invoice.customer_id)
            or data.get("currency") != invoice.currency
            or money(data.get("amount")) != invoice.total_amount):
        raise ValueError("小满订单客户、币种或金额与方舟不一致，请先核对订单")
    return {"rows": order_receipts(db, invoice.xiaoman_order_id), "exchange_rate": data.get("exchange_rate"),
            "invoice_binding": [invoice.xiaoman_order_id, invoice.customer_id, invoice.currency, str(invoice.total_amount)]}


def push(db, receipt, snapshot, before_send=None):
    if receipt.payment_type not in receipt_types(db):
        raise ValueError("回款方式已失效，请修改后重试")
    fields = read(db, "/v1/invoices/receipt/fields")
    fields = fields.get("data") if isinstance(fields, dict) and "data" in fields else fields
    if not isinstance(fields, list):
        raise ValueError("小满回款字段不可用，暂不能同步")
    payload = {
        "order_id": int(receipt.xiaoman_order_id), "amount": str(receipt.amount),
        "currency": receipt.currency, "collection_date": receipt.collection_date.isoformat(),
        "type": receipt.payment_type, "bank_charge": str(receipt.bank_charge),
        "cash_collection_no": receipt.receipt_no, "comment": receipt.remark or "",
        "collect_status": 1,
    }
    rate = Decimal(str(snapshot.get("exchange_rate") or "0"))
    if not rate.is_finite() or rate <= 0:
        raise ValueError("小满订单缺少有效汇率，请先完善订单")
    payload["exchange_rate"] = str(rate)
    missing = [str(f.get("name") or f.get("id")) for f in fields
               if str(f.get("require")) == "1" and str(f.get("disable_flag", 0)) not in {"1", "True", "true"}
               and str(f.get("id")) not in payload and str(f.get("id")) != "exchange_rate_usd" and f.get("default") in (None, "", [])]
    if missing:
        raise ValueError("小满回款存在尚未配置的必填字段：" + "、".join(missing))
    # file_list intentionally omitted until a supported private file-transfer contract exists.
    for force in (False, True):
        token = okki_client.ensure_access_token(db, force=force)
        if before_send:
            before_send()  # fence after ALL read-only preparation, immediately before POST
        result = okki_client._post_json("/v1/invoices/receipt/push", token, payload, context="回款推送")
        if result is not None:
            if not isinstance(result, dict) or not str(result.get("cash_collection_id") or "").isdigit() or not result.get("cash_collection_no"):
                raise okki_client.OkkiOutcomeUncertainError("回款响应缺少 ID 或编号，请核对小满，禁止重复创建")
            return result
    raise okki_client.OkkiApiError("小满回款鉴权被拒绝")
