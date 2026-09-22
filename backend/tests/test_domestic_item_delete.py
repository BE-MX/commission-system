"""Persisted item deletion contract, independent of new-order pricing fixtures."""
from datetime import date
from decimal import Decimal

import pytest

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.domestic import order_service
from app.domestic.models import DomesticCustomer, DomesticCustomerLedger, DomesticOrder, DomesticOrderItem, DomesticProduct, DomesticItemProgress, DomesticReportLog, DomesticSkipLog
from app.production.models import Process, ProcessRoute


def saved_order(db, status=1, count=2):
    user = ArkUser(username="delete-owner", password_hash="test", real_name="Delete owner")
    db.add(user)
    db.flush()
    customer = DomesticCustomer(shop_name="Delete test", balance=100, created_by=user.id)
    product = DomesticProduct(attrs_key="delete-test", name="Delete product", product_type="cap", craft="test", length="15厘米")
    db.add_all([customer, product])
    db.flush()
    order = DomesticOrder(domestic_no="DO-DELETE", order_no="test", order_date=date(2026, 9, 22),
                          customer_id=customer.id, created_by=user.id, status=status,
                          total_amount=count * 100, charged_amount=count * 100 if status == 1 else 0,
                          item_count=count, total_unit_qty=count * 2, next_line_no=count + 1)
    db.add(order)
    db.flush()
    items = [DomesticOrderItem(order_id=order.id, line_no=i + 1, product_id=product.id,
                               product_name=product.name, order_qty=2, unit_price=50, original_price=50,
                               discount_amount=0, pricing_rule="base_price", pricing_version="test",
                               base_price_version_snapshot=1) for i in range(count)]
    db.add_all(items)
    db.commit()
    return user, customer, order, items


@pytest.mark.parametrize("status", [0, 1])
def test_delete_persists_totals_and_only_refunds_charged_orders(db, status):
    user, customer, order, items = saved_order(db, status)
    deleted_id = items[0].id
    order_service.delete_item(db, deleted_id, user.id)
    db.expire_all()
    assert db.get(DomesticOrderItem, deleted_id) is None
    assert order.item_count == 1
    assert order.total_unit_qty == 2
    assert order.total_amount == Decimal("100.00")
    assert order.charged_amount == (Decimal("100.00") if status else Decimal("0.00"))
    assert customer.balance == (Decimal("200.00") if status else Decimal("100.00"))
    assert items[1].line_no == 2
    assert db.query(DomesticCustomerLedger).count() == (1 if status else 0)
    with pytest.raises(ValueError):
        order_service.delete_item(db, deleted_id, user.id)
    db.rollback()
    assert customer.balance == (Decimal("200.00") if status else Decimal("100.00"))


@pytest.mark.parametrize("status", [3, 4, 5, 6])
def test_frozen_order_cannot_delete_or_refund(db, status):
    user, customer, order, items = saved_order(db, status)
    with pytest.raises(ValueError, match="不能删除明细"):
        order_service.delete_item(db, items[0].id, user.id)
    db.rollback()
    assert db.query(DomesticOrderItem).count() == 2
    assert customer.balance == Decimal("100.00")


def test_last_item_cannot_be_deleted(db):
    user, customer, order, items = saved_order(db, count=1)
    with pytest.raises(ValueError, match="至少保留"):
        order_service.delete_item(db, items[0].id, user.id)
    db.rollback()
    assert db.query(DomesticOrderItem).count() == 1
    assert customer.balance == Decimal("100.00")


def test_non_creator_cannot_delete(db):
    user, customer, order, items = saved_order(db)
    with pytest.raises(ValueError):
        order_service.delete_item(db, items[0].id, user.id + 1)
    db.rollback()
    assert db.query(DomesticOrderItem).count() == 2
    assert customer.balance == Decimal("100.00")


@pytest.mark.parametrize("history", ["report", "revoked_report", "skip", "revoked_skip"])
def test_work_history_blocks_deletion_even_after_revocation(db, history):
    user, customer, order, items = saved_order(db)
    process, route = Process(name="Delete process"), ProcessRoute(name="Delete route")
    db.add_all([process, route])
    db.flush()
    progress = DomesticItemProgress(item_id=items[0].id, route_id=route.id, process_id=process.id, step_order=1)
    db.add(progress)
    db.flush()
    common = dict(item_id=items[0].id, progress_id=progress.id, revoked=int(history.startswith("revoked")))
    if "report" in history:
        log = DomesticReportLog(**common, process_id=process.id, step_order=1, report_qty=1,
                                reported_by_user_id=user.id, reported_at=beijing_now())
    else:
        log = DomesticSkipLog(**common, skip_qty=1, source="manual", created_by_user_id=user.id)
    db.add(log)
    db.commit()
    with pytest.raises(ValueError, match="记录，不能删除"):
        order_service.delete_item(db, items[0].id, user.id)
    db.rollback()
    assert db.query(DomesticOrderItem).count() == 2
    assert db.get(type(log), log.id) is not None
    assert customer.balance == Decimal("100.00")
