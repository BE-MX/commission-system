"""Live outbound reconciliation. No writes without a server-side state fence."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime
import httpx

from app.invoice import okki_client
from app.receipt import remote


MAX_CONCURRENT_DETAIL_READS = 4


def _read_details(db, identities, **transport):
    """Read every listed document without sharing the SQLAlchemy session across threads."""
    if not identities:
        return []
    token = okki_client.ensure_access_token(db)

    def fetch(identity):
        for attempt in range(2):
            try:
                return okki_client._get_json("/v1/invoices/outbound/info", token,
                    context="关联出库详情", params={"outbound_invoice_id": identity}, client=client, **transport)
            except okki_client.OkkiApiError as exc:
                if attempt or not isinstance(exc.__cause__, (
                    httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError,
                )):
                    raise

    limits = httpx.Limits(max_connections=MAX_CONCURRENT_DETAIL_READS,
                          max_keepalive_connections=MAX_CONCURRENT_DETAIL_READS)
    with (
        httpx.Client(limits=limits) as client,
        ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DETAIL_READS) as pool,
    ):
        rows = list(pool.map(fetch, identities))
    # One token refresh is safe here because these are GETs. A failed result
    # still stops the entire scan rather than treating a document as absent.
    return [remote.read(db, "/v1/invoices/outbound/info", {"outbound_invoice_id": identity}, **transport)
            if row is None else row for identity, row in zip(identities, rows)]


class OutboundListChanged(ValueError):
    """Concurrent supplier edits require a fresh quote, never an absence result."""


def _list_rows(db, params, *, read=None):
    read = read or remote.read
    seen, expected = {}, None
    for page in range(1, 501):
        data = read(db, "/v1/invoices/outbound/list", {**params, "start_index": page})
        if not isinstance(data, dict):
            raise ValueError("出库单列表格式不完整")
        rows, count = data.get("list"), data.get("count")
        if not isinstance(rows, list) or not str(count).isdigit():
            raise ValueError("出库单列表不完整，请稍后重新核对")
        count = int(count)
        if expected is not None and count != expected:
            raise OutboundListChanged("出库单列表已变化，请重新核对")
        expected = count
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("出库单列表记录无效")
            identity = str(row.get("outbound_invoice_id") or "")
            if not identity:
                raise ValueError("出库单列表缺少ID，请重新核对")
            if identity in seen:
                raise OutboundListChanged("出库单分页已变化，请重新核对")
            seen[identity] = row
        if len(seen) == expected:
            return seen
        if not rows or len(seen) > expected:
            break
    raise ValueError("出库单扫描未完成，未判定关联状态")


def find_related(db, order):
    if not isinstance(order, dict) or not order.get("order_id"):
        raise ValueError("关联订单身份不完整")
    stamp = str(order.get("create_time") or "")[:10]
    datetime.strptime(stamp, "%Y-%m-%d")
    # Enumerate consecutive pages before slow detail reads. Interleaving them
    # let ordinary updates move IDs across page boundaries during long scans.
    # Keep update-time coverage and cross-customer links; neither is filterable.
    params = dict(start_time=stamp + " 00:00:00", time_type=1, count=100, removed=0)
    identities = list(_list_rows(db, params))
    found = []
    for offset in range(0, len(identities), 100):
        batch = identities[offset:offset + 100]
        details = _read_details(db, batch)
        if len(details) != len(batch):
            raise ValueError("出库单详情未完整读取")
        for identity, detail in zip(batch, details):
            if not isinstance(detail, dict):
                raise ValueError("出库单详情格式不完整")
            records = detail.get("record_list")
            if str(detail.get("outbound_invoice_id")) != identity or not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
                raise ValueError("出库单详情不完整")
            if any("order_id" not in record or not str(record["order_id"]).isdigit() for record in records):
                raise ValueError("出库明细关联订单身份不完整，不能判定无关联")
            if any(str(r["order_id"]) == str(order["order_id"]) for r in records):
                found.append(detail)
    # A matching count alone misses a delete plus insert. Ordering may change
    # after an ordinary update, but membership must remain complete and equal.
    if set(_list_rows(db, params)) != set(identities):
        raise OutboundListChanged("出库单列表已变化，请重新核对")
    return found


def summarize(db, invoice, order):
    related = find_related(db, order)
    from app.invoice import xiaoman_service
    rows, _, issues, _ = xiaoman_service._build_product_rows(
        db, invoice, xiaoman_service.get_settings_row(db), editing=True)
    if issues:
        raise ValueError("订单产品映射尚未完整核对")
    return summarize_documents(rows, related, order["order_id"])


def summarize_documents(rows, related, order_id):
    """Compare frozen local lines with verified external documents, without DB I/O."""
    wanted, actual = defaultdict(Decimal), defaultdict(Decimal)
    for item in rows:
        wanted[(str(item.get("unique_id") or ""), str(item["product_id"]), str(item["sku_id"]))] += Decimal(str(item["count"]))
    for document in related:
        for row in document["record_list"]:
            if str(row.get("order_id")) == str(order_id):
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
