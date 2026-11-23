"""Desensitized BIFF samples and full API-to-file reconciliation, using only SQLite."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import openpyxl
import pytest
import xlrd

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core import time as platform_time
from app.cross_border.parser import BASE, FIELDS, HEAD, LABELS, LINE, RECEIPT, WorkbookError, parse
from app.cross_border.router import router
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentOutbound
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
from app.tracking.models import ShipmentTracking, TrackingEvent

FIXTURES = Path(__file__).parent / "fixtures" / "cross_border"
DAY = date(2026, 11, 23)
PREFIX = "/api/cross-border"


def sample(name):
    return (FIXTURES / (name + ".xls")).read_bytes()


def entries(name):
    return parse(name + ".xls", sample(name))[1]


def xlsx(sheets, *, reverse_columns=False):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, records in sheets.items():
        ws = book.create_sheet(name)
        cols = list(reversed(FIELDS[name])) if reverse_columns else FIELDS[name]
        ws.append([LABELS[name][FIELDS[name].index(k)] for k in cols])
        ws.append(cols)
        for record in records:
            ws.append([record[k] for k in cols])
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def order_book(rows):
    return {HEAD: [e.head.copy() for e in rows], LINE: [e.line.copy() for e in rows],
            BASE: [e.base.copy() for e in rows]}


def receipt_book(orders):
    template = entries("dhl-receipts")[0]
    return {RECEIPT: [dict(template.head, orderNo=e.head["orderNo"], charge=e.head["goodsValue"]) for e in orders],
            BASE: [template.base for _ in orders]}


def test_identity_is_independent_of_export_time_other_rows_and_column_order():
    original = entries("dhl-orders")
    assert len(original) == 37
    group = order_book([original[0], original[0], original[1]])
    for row in group[HEAD]:
        row["appTime"] = "20270101000001"
    _, current = parse("retry.xlsx", xlsx(group, reverse_columns=True))
    assert [e.occurrence for e in current] == [1, 2, 1]
    assert current[0].content_hash == original[0].content_hash != current[1].content_hash
    assert current[2].content_hash == original[1].content_hash


@pytest.mark.parametrize("bad,pattern", [("missing", "OrderList"), ("length", "第 3 行"),
                                           ("number", "goodsValue"), ("mismatch", "orderNo")])
def test_rejects_only_invalid_file_with_location(bad, pattern):
    group = order_book(entries("dhl-orders")[:1])
    if bad == "missing":
        del group[LINE]
    if bad == "length":
        group[LINE].clear()
    if bad == "number":
        group[HEAD][0]["goodsValue"] = "NaN"
    if bad == "mismatch":
        group[LINE][0]["orderNo"] = "12345678901234567"
    with pytest.raises(WorkbookError, match=pattern):
        parse("bad.xlsx", xlsx(group))


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "CROSS_BORDER_GO_LIVE_DATE", DAY)
    monkeypatch.setattr(get_settings(), "CROSS_BORDER_DXP_ID", "DXPTEST001")
    app = FastAPI()
    app.include_router(router, prefix=PREFIX)
    app.dependency_overrides[get_db] = lambda: db
    actor = {"sub": "1", "permissions": ["cross_border:read", "cross_border:write"]}
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as api:
        api.actor = actor
        yield api


def upload(client, *files):
    response = client.post(PREFIX + "/imports", files=[("files", f) for f in files])
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def listing(client, **filters):
    result = client.get(PREFIX + "/declarations", params={"view": "all", "page_size": 200, **filters})
    assert result.status_code == 200, result.text
    return result.json()["data"]


def seed_tickets(db, orders, *, sm=0):
    for i, row in enumerate(orders, 1):
        amount = Decimal(row.head["goodsValue"]).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        invoice = Invoice(invoice_no=f"TEST-{i}", customer_id="1", customer_name="测试", invoice_date=DAY,
                          created_at=datetime(2026, 11, 23), transaction_mode="local", total_amount=amount,
                          express_channel="DHL9610", internal_payment_method="小莱莎信保（便捷发货）",
                          alibaba_order_no=row.head["orderNo"], sales_user_name="测试业务员")
        item = InvoiceItem(product_name="Test", product_display="Test", color="1", quantity=1, total_price=amount)
        invoice.items = [item]
        track = ShipmentTracking(waybill_no=f"WB-{i}", carrier="DHL", carrier_name="DHL", dingtalk_user_id="test",
                                 dingtalk_user_name="Test", unified_status="in_transit")
        db.add_all([invoice, track])
        db.flush()
        outbound = ShipmentOutbound(invoice_id=invoice.id, settlement_id=i, outbound_no=f"OUT-{i}",
                                    status="local_shipped", payload_hash="test", payload={"transaction_mode": "local",
                                    "outbound_version": 1, "items": [{"invoice_item_id": item.id, "qty": 1}]})
        db.add(outbound)
        db.flush()
        inspection = ShippingInspection(outbound_record_id=f"LOCAL-{i}", local_outbound_id=outbound.id,
                                        local_outbound_version=1, status="submitted", shipment_tracking_id=track.id)
        db.add(inspection)
        db.flush()
        db.add(ShippingOperationEvent(scope="test", source="test", action="shipment_bound", login_user_id=1,
                    operator_user_id=1, operator_name="Test", login_name="Test", outbound_record_id=inspection.outbound_record_id,
                    inspection_id=inspection.id, created_at=datetime(2026, 11, 23, 0, 1), payload={"shipment_tracking_id": track.id}))
        db.add(TrackingEvent(waybill_no=track.waybill_no, carrier="DHL", event_time=datetime(2026, 11, 23),
                             status_code="SM" if i <= sm else "PU", description="测试"))
    db.commit()


def test_independent_cumulative_import_matching_and_hash_scoped_audit(client, db):
    original = entries("dhl-orders")
    # Rows covered by the 11/19 register and 11/20 customs sample, in DHL source order.
    selected = [original[i] for i in [1, 2, 4, 6, 9, 11, 14, 16, 18, 19, 20, 21, 23, 26, 27, 28, 30, 31, 32, 35]]
    seed_tickets(db, selected, sm=2)
    results = upload(client, ("broken.xls", b"bad"), ("orders.xls", sample("dhl-orders")))
    assert [r["status"] for r in results] == ["error", "imported"]
    assert upload(client, ("orders.xls", sample("dhl-orders")))[0]["status"] == "duplicate"
    assert upload(client, ("receipts.xls", sample("dhl-receipts")))[0]["added"] == 10
    result = listing(client)
    assert sum(r["row_type"] == "declaration" and bool(r["receipt_hash"]) for r in result["items"]) == 9
    assert sum(r["row_type"] == "receipt" for r in result["items"]) == 1
    upload(client, ("other-receipts.xlsx", xlsx(receipt_book(selected))))
    result = listing(client)
    ds = [r for r in result["items"] if r["row_type"] == "declaration"]
    assert sum(bool(r["ticket"]) for r in ds) == 20
    assert sum(any(i["code"] == "no_invoice" for i in r["issues"]) for r in ds) == 17
    assert sum(any(i["code"] == "not_picked_up" for i in r["issues"]) for r in ds) == 2
    assert len(result["ready_content_hashes"]) == 18
    assert listing(client, view="ready", page_size=1)["ready_content_hashes"] == result["ready_content_hashes"]
    assert listing(client, bound_date_from="2026-11-23", bound_date_to="2026-11-23")["total"] == 20

    first = selected[0].content_hash
    path = PREFIX + "/declarations/" + first
    assert client.post(path + "/reviews", json={"action": "confirm_shipped", "reason": " "}).status_code == 422
    assert client.post(path + "/reviews", json={"action": "confirm_shipped", "reason": "DHL 签收凭证已核对"}).status_code == 200
    assert listing(client)["summary"]["ready"] == 19
    assert client.get(path).json()["data"]["audit"][0]["created_by"] == 1
    refreshed = order_book(original)
    for head in refreshed[HEAD]:
        head["appTime"] = "20261125000000"
    result = upload(client, ("later.xlsx", xlsx(refreshed)))[0]
    assert result["added"] == result["suspected"] == 0
    assert listing(client, import_id=results[1]["id"])["total"] == 37
    changed = order_book(selected[:1])
    changed[HEAD][0]["goodsValue"] = "9999.99000"
    changed[LINE][0]["totalPrice"] = "9999.99"
    assert upload(client, ("changed.xlsx", xlsx(changed)))[0]["suspected"] == 1
    refreshed = client.get(path).json()["data"]
    assert refreshed["suspected_changed"] and refreshed["can_export"]
    assert client.post(PREFIX + "/exports", json={"content_hashes": [first]}).status_code == 409
    assert client.post(PREFIX + "/exports", json={"content_hashes": [first], "confirm_suspected": True, "reason": "已核对两条申报"}).status_code == 200
    assert client.post(path + "/reviews", json={"action": "void", "reason": "已确认被替换"}).status_code == 200
    assert client.get(path).json()["data"]["voided"]


def compare_golden(content, expected_name, stamp):
    output = openpyxl.load_workbook(BytesIO(content))
    expected = xlrd.open_workbook(file_contents=sample(expected_name))
    assert output.sheetnames == expected.sheet_names()
    cells = 0
    for sheet in expected.sheets():
        actual = output[sheet.name]
        assert (actual.max_row, actual.max_column) == (sheet.nrows, sheet.ncols)
        for i in range(sheet.nrows):
            for j in range(sheet.ncols):
                cell, original = actual.cell(i + 1, j + 1), sheet.cell(i, j)
                if i >= 2 and sheet.cell_value(1, j) == "appTime":
                    assert cell.value == stamp and cell.data_type == "s"
                elif original.ctype == xlrd.XL_CELL_NUMBER:
                    assert cell.data_type == "n" and cell.value == original.value
                else:
                    assert (cell.value or "") == original.value
                    if original.value:
                        assert cell.data_type == "s"
                cells += 1
    return cells


def test_two_export_files_match_every_golden_cell_and_require_permission(client, db, monkeypatch):
    orders = entries("customs-orders")
    seed_tickets(db, orders)
    upload(client, ("orders.xls", sample("dhl-orders")), ("receipts.xls", sample("customs-receipts")))
    chosen = [r.content_hash for r in orders]
    selection = {"content_hashes": chosen[::-1]}
    monkeypatch.setenv("TZ", "UTC")
    endpoint = PREFIX + "/exports"
    for hour, minute, stamp in [(15, 59, "20261123235900"), (16, 1, "20261124000100")]:
        instant = datetime(2026, 11, 23, hour, minute, tzinfo=timezone.utc)

        class UTCClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        monkeypatch.setattr(platform_time, "datetime", UTCClock)
        response = client.post(endpoint, json=selection)
        assert response.status_code == 200, response.text
        identity = response.json()["data"]["id"]
        for kind in ("order", "receipt"):
            response = client.get(f"{endpoint}/{identity}/files/{kind}")
            assert response.status_code == 200
            assert compare_golden(response.content, f"customs-{kind}s", stamp) > 200
        assert client.post(endpoint, json={"content_hashes": chosen}).status_code == 409
        selection["confirm_reexport"] = True
    assert listing(client, view="exported")["total"] == 10
    client.actor["permissions"] = ["cross_border:read"]
    assert client.post(endpoint, json=selection).status_code == 403
    client.actor["permissions"] = []
    assert client.get(f"{endpoint}/1/files/order").status_code == 403
