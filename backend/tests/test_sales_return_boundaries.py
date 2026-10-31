from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core import time as business_time
from app.sales_return import read_service, receiving_service, schemas, service
from app.sales_return.models import ReturnEffect, ReturnReceipt, ReturnReceiving
from tests.test_sales_return_service import env, activate, draft, USER  # noqa: F401


def test_pending_inspection_can_finish_without_counting_another_receipt(env):
    db, _, _ = env
    row, _ = activate(db)
    item = read_service.describe(db, row)["items"][0]
    receiving_service.receive(db, row.id, schemas.Receiving(item_id=item["id"], quantity=10,
        accepted_quantity=0, rejected_quantity=0, pending_quantity=10, request_key="receiving-pending-0001"), USER)
    event = db.scalar(select(ReturnReceiving))
    command = schemas.Inspection(version=event.version, accepted_quantity=4, rejected_quantity=1,
                                 pending_quantity=5, note="First physical inspection")
    receiving_service.inspect_receiving(db, row.id, event.id, command, USER)
    assert receiving_service.inspect_receiving(db, row.id, event.id, command, USER).id == row.id
    assert event.quantity == 10 and event.pending_quantity == 5
    receiving_service.inspect_receiving(db, row.id, event.id, schemas.Inspection(version=event.version,
        accepted_quantity=9, rejected_quantity=1, pending_quantity=0, note="Remaining pieces inspected"), USER)
    assert db.query(ReturnReceiving).count() == 1
    assert read_service.describe(db, row)["receiving_status"] == "inspected"
    with pytest.raises(HTTPException):
        receiving_service.inspect_receiving(db, row.id, event.id, schemas.Inspection(version=event.version,
            accepted_quantity=8, rejected_quantity=1, pending_quantity=1, note="Cannot uninspect"), USER)


def test_warehouse_action_projection_has_no_financial_details(env):
    db, _, _ = env
    row, _ = activate(db)
    warehouse = {**USER, "permissions": ["sales_return_receiving:write"]}
    result = read_service.describe_receiving(db, row, warehouse)
    assert result["order_id"] == row.order_id
    assert not {"snapshot", "reduction_amount", "refund_amount", "waived_amount", "receipts", "effects", "allocations", "cash_evidence"}.intersection(result)
    assert all("reduction_amount" not in item and "reduction_usd" not in item for item in result["items"])


@pytest.mark.parametrize("key,value", [("net_amount", "1100.00"), ("net_amount_usd", "1100.00"), ("quantity", 11)])
def test_external_revaluation_of_an_already_returned_line_requires_reconciliation(env, key, value):
    db, snapshot, _ = env
    first = draft(lines=[{"source_key": "OUT-1:LINE-1", "quantity": 1, "reduction_amount": "100"}])
    activate(db, first)
    snapshot["lines"][0][key] = value
    with pytest.raises(HTTPException, match="外部|修改|差异"):
        service.preview(db, draft(request_key="unused-new-source-key"), USER)


def test_sync_timestamp_alone_does_not_change_economic_facts(env):
    db, snapshot, _ = env
    activate(db, draft(lines=[{"source_key": "OUT-1:LINE-1", "quantity": 1, "reduction_amount": "100"}]))
    snapshot["synced_at"] = "2026-10-30 18:00:00"
    quote = service.preview(db, draft(lines=[{"source_key": "OUT-1:LINE-1", "quantity": 1, "reduction_amount": "100"}]), USER)
    assert quote["refund_amount"] == "100.00"


@pytest.mark.parametrize("utc_hour,utc_minute,expected", [(15, 59, "2026-10-30"), (16, 0, "2026-10-31")])
def test_activation_day_is_beijing_at_midnight_on_a_non_beijing_host(env, monkeypatch, utc_hour, utc_minute, expected):
    db, _, _ = env
    instant = datetime(2026, 10, 30, utc_hour, utc_minute, tzinfo=timezone.utc)

    class NonBeijingHost(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant.astimezone(timezone(timedelta(hours=-7))).replace(tzinfo=None)

    monkeypatch.setattr(business_time, "datetime", NonBeijingHost)
    row, _ = activate(db)
    assert row.effective_date.isoformat() == expected
    assert db.scalar(select(ReturnReceipt.collection_date)).isoformat() == expected
    assert db.scalar(select(ReturnEffect.effective_date)).isoformat() == expected
    assert row.created_at.tzinfo is None


def test_financial_effects_cannot_be_edited_after_recording(env):
    db, _, _ = env
    activate(db)
    db.commit()
    effect = db.scalar(select(ReturnEffect))
    effect.amount_usd = Decimal("-1")
    with pytest.raises(ValueError, match="append-only"):
        db.flush()
    db.rollback()
    assert db.scalar(select(ReturnEffect.amount_usd)) == Decimal("-1000")


def test_three_physical_returns_absorb_only_price_rounding_tail(env):
    db, snapshot, _ = env
    snapshot.update(goods_amount="100", goods_amount_usd="100")
    snapshot["payments"][0].update(principal="100", principal_usd="100")
    snapshot["lines"][0].update(quantity=3, net_amount="100", net_amount_usd="100")
    for index, amount in enumerate(("33.33", "33.33", "33.34")):
        activate(db, draft(key=f"create-rounding-{index:04d}",
            lines=[{"source_key": "OUT-1:LINE-1", "quantity": 1, "reduction_amount": amount}]),
            key=f"activate-rounding-{index:04d}")
    assert sum(db.scalars(select(ReturnReceipt.amount)).all()) == Decimal("-100")
    assert read_service.history(db, "101")["quantities"]["OUT-1:LINE-1"] == 3


@pytest.mark.parametrize("key,value", [("account_date", "2024-01-01"), ("raw_new_deal", False)])
def test_original_accounting_date_and_role_cannot_drift_after_return(env, key, value):
    db, snapshot, _ = env
    snapshot.update(account_date="2025-12-01", raw_new_deal=True)
    activate(db, draft(lines=[{"source_key": "OUT-1:LINE-1", "quantity": 1, "reduction_amount": "100"}]))
    snapshot[key] = value
    with pytest.raises(HTTPException, match="核算日期|成交分类"):
        service.preview(db, draft(), USER)


def test_pending_registered_money_is_not_called_received_when_credit_exceeds_cap(env):
    from app.sales_return.balance import overlay
    db, _, _ = env
    activate(db)
    with pytest.raises(ValueError, match="未收预登记款.*更正原款"):
        overlay(db, "101", {"total_amount": "1000", "registered_amount": "1000", "effective_amount": "600",
                            "pending_amount": "400", "version": "before"})
