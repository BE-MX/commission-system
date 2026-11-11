from datetime import date, timedelta
from decimal import Decimal
import hashlib

import pytest
from sqlalchemy import text

from app.core.time import beijing_now
from app.invoice.detail_receipt_snapshot import page_orders
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.screenshot_source import external_source_key
from app.invoice.service import list_invoices
from app.receipt import receipt_index
from app.receipt.models import Receipt, ReceiptIndexState
from app.sales_return.models import ReturnEffect, ReturnReceipt


DAY = date(2026, 11, 10)


def invoice(db, number, **fields):
    data = dict(invoice_no=number, customer_id="100", customer_name="Example",
                invoice_date=DAY, sales_user_id=5, currency="EUR", total_amount=100)
    db.add(row := Invoice(**(data | fields)))
    db.flush()
    return row


def receipt(db, inv, **fields):
    data = dict(invoice_id=inv.id, receipt_no=f"R-{inv.id}", source="manual",
                request_key=f"req-{inv.id}", request_hash="hash", amount=50,
                bank_charge=2, currency=inv.currency, collection_date=DAY, payment_type="bank",
                customer_id=inv.customer_id, xiaoman_order_id=inv.xiaoman_order_id, created_by=5)
    db.add(Receipt(**(data | fields)))


def remote_row(receipt_id, order_id, amount, collect_status, **fields):
    return dict(cash_collection_id=receipt_id, cash_collection_no=receipt_id, order_id=order_id,
                amount=amount, currency="EUR", collect_status=collect_status,
                collection_date=DAY.isoformat()) | fields


def snapshot(db, rows, *, age=0):
    stamp = (beijing_now() - timedelta(seconds=age)).strftime("%Y-%m-%d %H:%M:%S")
    source = receipt_index._source()
    payload = dict(version=1, source=source, watermark=stamp,
                   rows=[dict(row, update_time=stamp) for row in rows])
    state = db.get(ReceiptIndexState, source) or ReceiptIndexState(source=source)
    state.snapshot = dict(payload=payload, sha256=hashlib.sha256(receipt_index._encoded(payload)).hexdigest())
    db.add(state)
    db.flush()


def test_invoice_list_counts_current_rows_and_pieces_before_paging(db):
    current = invoice(db, "COUNT", order_type="presale")
    invoice(db, "EMPTY")
    for index, (kind, pieces, archived) in enumerate([("hair", 2, 0), ("accessory", 5, 0), ("hair", 30, 1)]):
        db.add(InvoiceItem(invoice_id=current.id, sort_order=index, product_kind=kind, presale_archived=archived, product_name=kind,
                           product_display=kind, color="Black", quantity=pieces, price_per_piece=1, total_price=pieces))
    db.flush()

    rows, total = list_invoices(db, page_size=1, sort_field="item_count", sort_order="desc")
    assert total == 2
    assert (rows[0]["invoice_no"], rows[0]["item_count"], rows[0]["total_quantity"]) == ("COUNT", 2, 7)
    rows, _ = list_invoices(db, page=2, page_size=1, sort_field="item_count", sort_order="desc")
    assert (rows[0]["invoice_no"], rows[0]["item_count"], rows[0]["total_quantity"]) == ("EMPTY", 0, 0)


def test_invoice_list_returns_confirmed_original_currency_without_counting_pending_or_freight(db):
    confirmed = invoice(db, "PAID", xiaoman_order_id="901")
    presale = invoice(db, "PRESALE", xiaoman_order_id="902", order_type="presale")
    zero = invoice(db, "ZERO", xiaoman_order_id="903")
    invoice(db, "MISMATCH", xiaoman_order_id="904")
    other = invoice(db, "OTHER", xiaoman_order_id="905", sales_user_id=7)
    invoice(db, "NATIVE", transaction_mode="local", internal_received=35)
    invoice(db, "WRONG-CUSTOMER", xiaoman_order_id="907")
    invoice(db, "COMPETING-BINDING", xiaoman_order_id="908")
    receipt(db, confirmed, receipt_no="HISTORY", request_key="history",
            status="voided", xiaoman_receipt_id="R9")
    receipt(db, confirmed, xiaoman_receipt_id="R1", sync_status="synced")
    receipt(db, presale, xiaoman_receipt_id="R3", sync_status="synced", purpose="presale_advance")
    receipt(db, presale, receipt_no="FREIGHT", request_key="freight", purpose="freight",
            xiaoman_order_id="906", xiaoman_receipt_id="R7", sync_status="synced")
    receipt(db, zero)
    db.add(ReturnReceipt(id=1, return_id=1, receipt_no="REFUND", effect_kind="apply", order_id="901",
                         customer_id="100", currency="EUR", amount=-8, amount_usd=-9,
                         collection_date=DAY, created_by=5))
    db.add(ReturnEffect(id=1, return_id=1, effect_kind="apply", order_id="901", owner_okki_user_id="5",
                        customer_id="100", currency="EUR", amount=-48, amount_usd=-50,
                        effective_date=DAY, gmv_eligible=1, order_role="repeat"))
    rows = [remote_row("R1", "901", "48", 1), remote_row("R2", "901", "20", 0),
            remote_row("R3", "902", "48", 1), remote_row("R4", "901", "10", 1),
            remote_row("R5", "904", "10", 1, currency="USD"), remote_row("R6", "905", "99", 1),
            remote_row("R7", "906", "48", 1), remote_row("R8", "907", "12", 1),
            remote_row("R9", "908", "12", 1)]
    db.execute(text("CREATE TABLE IF NOT EXISTS lsordertest.okki_receipts (cash_collection_id TEXT PRIMARY KEY, order_id TEXT, company_id TEXT)"))
    db.execute(text("""INSERT INTO lsordertest.okki_receipts (cash_collection_id, order_id, company_id) VALUES
        ('R2', '901', '100'), ('R4', '901', '100'), ('R6', '905', '100'),
        ('R8', '907', '999'), ('R9', '908', '100')"""))
    snapshot(db, rows)

    def paid(permissions):
        items, _ = list_invoices(db, user={"id": 5, "sub": "5", "permissions": permissions})
        return {item["invoice_no"]: item["received_amount"] for item in items}

    assert paid(["invoice:read", "invoice:read_all", "receipt:read"]) == {
        "PAID": Decimal("52"), "PRESALE": Decimal("50"), "ZERO": Decimal("0"), "MISMATCH": None, "OTHER": None,
        "WRONG-CUSTOMER": None, "COMPETING-BINDING": None, "NATIVE": Decimal("35"),
    }
    assert paid(["invoice:read", "receipt:read", "receipt:read_all"])["OTHER"] == Decimal("99")
    assert all(value is None for value in paid(["invoice:read", "invoice:read_all"]).values())

    receipt(db, other, batch_id=123)
    linked = db.query(Receipt).filter(Receipt.xiaoman_receipt_id == "R1").one()
    linked.batch_id = 123
    db.flush()
    assert paid(["invoice:read", "invoice:read_all", "receipt:read"])["PAID"] is None

    items, _ = list_invoices(db, keyword="PAID", user={"roles": ["super_admin"]})
    assert items[0]["total_amount"] == Decimal("100")
    assert items[0]["receipt_payable_amount"] == items[0]["received_amount"] == Decimal("52")

    snapshot(db, rows, age=121)
    assert all(value is None for value in paid(["invoice:read", "receipt:read"]).values())


def test_page_snapshot_reuses_only_current_validated_publication(db, monkeypatch):
    load = receipt_index._load
    reads = []

    def track_load(session, source):
        reads.append(source)
        return load(session, source)

    monkeypatch.setattr(receipt_index, "_load", track_load)
    snapshot(db, [remote_row("R1", "901", "50", 1)])
    assert page_orders(db, {"901"})["901"][0]["amount"] == "50"
    assert page_orders(db, {"other"}) == {}
    assert len(reads) == 1

    snapshot(db, [remote_row("R1", "901", "60", 1)])
    assert page_orders(db, {"901"})["901"][0]["amount"] == "60"
    assert len(reads) == 2

def test_invoice_list_does_not_show_zero_for_an_existing_screenshot_order_without_binding(db):
    invoice(db, "SCREENSHOT", source_type="okki_screenshot", source_order_id="901",
            sync_status="not_synced")
    invoice(db, "EXTERNAL", source_type="okki_screenshot",
            source_order_id=external_source_key("100", "External Order"), sync_status="not_synced")
    invoice(db, "ORDINARY", sync_status="not_synced")

    items, _ = list_invoices(db, user={"roles": ["super_admin"]})
    assert {item["invoice_no"]: item["received_amount"] for item in items} == {
        "SCREENSHOT": None,
        "EXTERNAL": Decimal("0"),
        "ORDINARY": Decimal("0"),
    }


@pytest.mark.parametrize(("sync_status", "send_phase"), [
    ("uncertain", "sending"),
    ("syncing", "sending"),
    ("syncing", None),
])
def test_invoice_list_hides_zero_and_partial_totals_when_unbound_receipt_is_uncertain(db, sync_status, send_phase):
    empty = invoice(db, "UNCERTAIN-EMPTY", xiaoman_order_id="901")
    partial = invoice(db, "UNCERTAIN-PARTIAL", xiaoman_order_id="902")
    pending = invoice(db, "PENDING", xiaoman_order_id="903")
    failed = invoice(db, "FAILED", xiaoman_order_id="904")
    freight = invoice(db, "FREIGHT", xiaoman_order_id="905")
    voided = invoice(db, "VOIDED", xiaoman_order_id="906")
    preparing = invoice(db, "PREPARING", xiaoman_order_id="907")
    receipt(db, empty, sync_status=sync_status, send_phase=send_phase)
    receipt(db, partial, sync_status=sync_status, send_phase=send_phase)
    receipt(db, partial, receipt_no="CONFIRMED", request_key="confirmed",
            sync_status="synced", xiaoman_receipt_id="R1")
    receipt(db, pending)
    receipt(db, failed, sync_status="failed", send_phase="rejected")
    receipt(db, freight, sync_status="uncertain", send_phase="sending", purpose="freight")
    receipt(db, voided, sync_status="uncertain", send_phase="sending", status="voided")
    receipt(db, preparing, sync_status="syncing", send_phase="preparing")
    snapshot(db, [remote_row("R1", "902", "48", 1)], age=30)

    items, _ = list_invoices(db, user={"roles": ["super_admin"]})
    assert {item["invoice_no"]: item["received_amount"] for item in items} == {
        "UNCERTAIN-EMPTY": None,
        "UNCERTAIN-PARTIAL": None,
        "PENDING": Decimal("0"),
        "FAILED": Decimal("0"),
        "FREIGHT": Decimal("0"),
        "VOIDED": Decimal("0"),
        "PREPARING": Decimal("0"),
    }
