"""Persisted coordination timestamps use Beijing time across UTC midnight."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.commerce_transition import service
from app.commerce_transition.models import InvoiceAuthority
from app.core import time as platform_time
from tests.test_commerce_transition_authority import install, invoice


@pytest.mark.parametrize(("utc_clock", "expected"), [
    (datetime(2026, 10, 26, 15, 59, tzinfo=timezone.utc), datetime(2026, 10, 26, 23, 59)),
    (datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc), datetime(2026, 10, 27, 0, 0)),
])
def test_confirmation_clock_ignores_non_beijing_host_and_crosses_beijing_midnight(db, monkeypatch, utc_clock, expected):
    class ExternalClock(datetime):
        @classmethod
        def now(cls, tz=None):
            # A non-East-8 host would still be on the preceding local business
            # date. Every tested business default must request Beijing explicitly.
            return utc_clock.astimezone(tz or ZoneInfo("America/Los_Angeles"))

    monkeypatch.setattr(platform_time, "datetime", ExternalClock)
    install(db)
    row = invoice(db, confirmed=False)
    service.confirm_authority(db, row, "legacy", 1, {"contract": "clock-boundary"})
    authority = db.get(InvoiceAuthority, row.id)
    assert authority.confirmed_at == expected
    assert authority.created_at == expected
    assert row.invoice_date == expected.date()
