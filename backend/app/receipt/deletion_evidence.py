"""Positive soft-deletion evidence; readable details alone do not imply active receipts."""
from datetime import datetime

from app.invoice import lifecycle_remote
from app.receipt import remote


def _binding(detail):
    return tuple(str(detail.get(key) or "") for key in
                 ("cash_collection_id", "order_id", "currency", "update_time"))


def _window(db, stamp, removed):
    data = remote.read(db, "/v1/invoices/receipt/list", {
        "start_index": 1, "count": 100, "removed": removed,
        "start_time": stamp, "end_time": stamp})
    rows, total = data.get("list"), data.get("totalItem")
    if (not isinstance(rows, list) or not str(total).isdigit()
            or int(total) > 100 or len(rows) != int(total)):
        raise ValueError("小满回款删除核验列表不完整，请稍后核对")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("小满回款删除核验字段不完整")
        identity = str(row.get("cash_collection_id") or "")
        if (not identity.isdigit() or identity in indexed or row.get("update_time") != stamp
                or not str(row.get("order_id") or "").isdigit() or not row.get("currency")):
            raise ValueError("小满回款删除核验范围或单据身份不一致")
        indexed[identity] = _binding(row)
    return indexed


def absent(db, order_id, identity, currency):
    """Require a stable positive deleted membership plus absence from the active window."""
    detail = lifecycle_remote.read(db, "receipt", identity)
    if detail is None:
        # Retain the existing explicit Not Found + verified active-index check.
        return not any(str(row["cash_collection_id"]) == str(identity)
                       for row in remote.order_receipts(db, order_id))
    if (_binding(detail)[:3] != (str(identity), str(order_id), str(currency))):
        raise ValueError("远端回款关联订单或币种已变化，未确认删除")
    stamp = detail.get("update_time")
    try:
        if datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S") != stamp:
            raise ValueError("noncanonical timestamp")
    except (TypeError, ValueError) as exc:
        raise ValueError("小满回款缺少有效更新时间，无法核验删除") from exc
    first = (_window(db, stamp, 0), _window(db, stamp, 1))
    second = (_window(db, stamp, 0), _window(db, stamp, 1))
    if first != second:
        raise ValueError("小满回款删除核验列表发生变化，请稍后核对")
    after = lifecycle_remote.read(db, "receipt", identity)
    if after is None or _binding(after) != _binding(detail):
        raise ValueError("小满回款在删除核验期间变化，请重新核对")
    active, deleted = second
    key = str(identity)
    if key in active and key in deleted:
        raise ValueError("小满回款同时出现在有效与删除列表，证据不一致")
    if key in active or key not in deleted:
        return False
    if deleted[key] != _binding(detail):
        raise ValueError("小满已删除回款与原单关联不一致")
    return True
