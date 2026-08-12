"""订单发票 API 时间统一输出为北京时间。"""

from datetime import datetime, timedelta

from app.invoice import service
from app.invoice.models import Invoice


def test_invoice_list_created_at_treats_database_value_as_beijing_time():
    invoice = Invoice(
        id=1,
        invoice_no="TZ-1",
        order_type="stock",
        customer_id="1",
        customer_name="Customer",
        invoice_date=datetime(2026, 8, 12).date(),
        currency="USD",
        status="draft",
        sync_status="not_synced",
        created_at=datetime(2026, 8, 12, 11, 15),
    )

    value = service._invoice_list_row(invoice, 0)["created_at"]

    assert value.isoformat() == "2026-08-12T11:15:00+08:00"
    assert value.utcoffset() == timedelta(hours=8)


def test_invoice_detail_times_keep_database_beijing_clock_time():
    invoice = Invoice(
        id=2,
        invoice_no="TZ-2",
        order_type="stock",
        customer_id="2",
        customer_name="Customer",
        invoice_date=datetime(2026, 8, 12).date(),
        currency="USD",
        status="draft",
        sync_status="not_synced",
        created_at=datetime(2026, 8, 12, 8, 0),
        updated_at=datetime(2026, 8, 12, 9, 0),
        synced_at=datetime(2026, 8, 12, 10, 0),
        items=[],
    )

    detail = service.serialize_detail(invoice)

    assert detail["created_at"].isoformat() == "2026-08-12T08:00:00+08:00"
    assert detail["updated_at"].isoformat() == "2026-08-12T09:00:00+08:00"
    assert detail["synced_at"].isoformat() == "2026-08-12T10:00:00+08:00"
