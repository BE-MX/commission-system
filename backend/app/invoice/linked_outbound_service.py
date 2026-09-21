"""Live outbound reconciliation. No writes without a server-side state fence."""
from collections import defaultdict
from decimal import Decimal
from datetime import datetime

from app.receipt import remote


def find_related(db, order):
    stamp = str(order.get("create_time") or "")[:10]
    datetime.strptime(stamp, "%Y-%m-%d")
    # Match the existing managed creator: time_type=1 is update time, including
    # older outbound records that were subsequently linked to this order.
    params = dict(start_time=stamp + " 00:00:00", time_type=1, count=100, removed=0)
    seen, found, expected = set(), [], None
    for page in range(1, 501):
        data = remote.read(db, "/v1/invoices/outbound/list", {**params, "start_index": page})
        rows, count = data.get("list"), data.get("count")
        if not isinstance(rows, list) or not str(count).isdigit():
            raise ValueError("出库单列表不完整，请稍后重新核对")
        count = int(count)
        if expected is not None and count != expected:
            raise ValueError("出库单列表已变化，请重新核对")
        expected = count
        for row in rows:
            identity = str(row.get("outbound_invoice_id") or "")
            if not identity or identity in seen:
                raise ValueError("出库单分页重复或缺少ID，请重新核对")
            seen.add(identity)
            detail = remote.read(db, "/v1/invoices/outbound/info", {"outbound_invoice_id": identity})
            records = detail.get("record_list")
            if str(detail.get("outbound_invoice_id")) != identity or not isinstance(records, list):
                raise ValueError("出库单详情不完整")
            if any(str(r.get("order_id")) == str(order["order_id"]) for r in records):
                found.append(detail)
        if len(seen) == expected:
            latest = remote.read(db, "/v1/invoices/outbound/list", {**params, "start_index": 1})
            if int(latest.get("count", -1)) != expected:
                raise ValueError("出库单数量已变化，请重新核对")
            return found
        if not rows or len(seen) > expected:
            break
    raise ValueError("出库单扫描未完成，未判定关联状态")


def summarize(db, invoice, order):
    related = find_related(db, order)
    wanted, actual = defaultdict(Decimal), defaultdict(Decimal)
    from app.invoice import xiaoman_service
    rows, _, issues, _ = xiaoman_service._build_product_rows(
        db, invoice, xiaoman_service.get_settings_row(db), editing=True)
    if issues:
        raise ValueError("订单产品映射尚未完整核对")
    for item in rows:
        wanted[(str(item.get("unique_id") or ""), str(item["product_id"]), str(item["sku_id"]))] += Decimal(str(item["count"]))
    for document in related:
        for row in document["record_list"]:
            if str(row.get("order_id")) == str(order["order_id"]):
                actual[(str(row.get("order_record_id") or ""), str(row.get("product_id")), str(row.get("sku_id")))] += remote.money(row.get("outbound_count"))
    difference = [{"order_record_id": key[0], "product_id": key[1], "sku_id": key[2], "ordered": str(wanted[key]),
                   "outbound": str(actual[key]), "difference": str(wanted[key] - actual[key])}
                  for key in sorted(wanted.keys() | actual.keys()) if wanted[key] != actual[key]]
    documents = [{"id": str(d["outbound_invoice_id"]), "number": d.get("serial_id"), "status": d.get("status")}
                 for d in related]
    if not related:
        message = "尚无关联出库单；已存在的自动出库任务将在本次同步结束后继续处理，请稍后重新核对"
    elif difference:
        message = ("出库数量与新订单有差异；已出库部分请办理补发/退货，待出库部分请在小满核对后修改。"
                   "小满编辑接口尚未确认并发状态保护，未自动覆盖出库单")
    else:
        message = "已核对出库数量；价格、地址、备注等资料如有变更，仍需在小满确认。方舟正式出库单由镜像刷新"
    return {"status": "manual", "category": "documents_missing" if not related else "quantity_or_link_difference" if difference else "metadata_review",
            "message": message, "documents": documents, "differences": difference}
