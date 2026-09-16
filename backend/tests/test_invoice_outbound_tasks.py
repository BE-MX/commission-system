"""发票首推成功后自动生成 OKKI 出库单的任务队列测试。

覆盖：首推入队 / 编辑重推不入队 / 部分受理不入队 / 非标合并行落 skipped /
同 order_id 幂等 / 总开关关闭 / 对账补入队窗口口径。okki_client.push_order
一律 monkeypatch，不打真实接口。
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.invoice import okki_client, outbound_task_service, product_service, xiaoman_service
from app.invoice.models import CustomProduct, Invoice, InvoiceItem, InvoiceSyncLog, OkkiOutboundTask, XiaomanSettings
from app.invoice.time_utils import beijing_now


# ── 数据工厂（口径同 test_invoice_okki_push.py）───────────────


def _seed_settings(db):
    row = XiaomanSettings(
        id=1,
        generic_product_no="GENERIC-PROD",
        generic_product_id=888,
        generic_sku_id=999,
        default_order_status="13972831654",
        default_currency="USD",
    )
    db.add(row)
    db.flush()
    return row


def _seed_binding(db, ark_user_id=1):
    if db.get(ArkUser, ark_user_id) is None:
        db.add(ArkUser(
            id=ark_user_id, username=f"sales{ark_user_id}", password_hash="x", real_name="张三",
            okki_department_id=24925, okki_department_name="多财多亿",
        ))
    db.add(ArkUserExternalBinding(
        ark_user_id=ark_user_id,
        provider="okki",
        external_account_id="777001",
        binding_status="active",
    ))
    db.flush()


def _make_invoice(db, **overrides):
    from datetime import date

    invoice = Invoice(
        invoice_no=overrides.pop("invoice_no", "INV20260916-001"),
        order_type="production",
        customer_id="123456",
        customer_name="Customer A",
        sales_user_id=1,
        sales_user_name="张三",
        invoice_date=date(2026, 9, 16),
        currency="USD",
    )
    for key, value in overrides.items():
        setattr(invoice, key, value)
    db.add(invoice)
    db.flush()
    return invoice


def _stock_item(**overrides):
    item = InvoiceItem(
        sort_order=1,
        item_type="stock",
        product_id=1,
        sku_id=9001,
        product_name="Raw Hair/18/#1/100g",
        product_display="Raw Hair",
        net_weight_grams="100g",
        color="#1",
        length="18",
        quantity=3,
        price_per_piece=Decimal("12.50"),
        total_price=Decimal("37.50"),
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


def _custom_item(custom_product_id, **overrides):
    item = InvoiceItem(
        sort_order=2,
        item_type="custom",
        custom_product_id=custom_product_id,
        product_name="Genius Weft/18/#1/20g",
        product_display="Genius Weft",
        net_weight_grams="20g",
        model="B1",
        color="#1",
        length="18",
        quantity=2,
        price_per_piece=Decimal("8.00"),
        total_price=Decimal("16.00"),
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


def _make_custom_product(db, match_key, **overrides):
    row = CustomProduct(
        match_key=match_key,
        product_display="Genius Weft",
        product_name="Genius Weft/18/#1/20g",
        color="#1",
        size="18",
        unit="20g",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def no_reconcile(monkeypatch):
    """跳过推单前对账（测试库无 okki_products 投影表）"""
    monkeypatch.setattr(product_service, "reconcile_custom_products", lambda db: {"checked": 0, "linked": 0})


def _tasks(db):
    return db.query(OkkiOutboundTask).order_by(OkkiOutboundTask.id).all()


def _fake_push_stock_only(_db, _payload):
    return {
        "order_id": 424242,
        "product_list": [{"unique_id": 111, "product_id": "1", "sku_id": "9001"}],
    }


def _fake_push_with_merged(_db, _payload):
    return {
        "order_id": 424242,
        "product_list": [
            {"unique_id": 111, "product_id": "1", "sku_id": "9001"},
            {"unique_id": 222, "product_id": "888", "sku_id": "999"},
        ],
    }


# ── 同步钩子 ──────────────────────────────────────────────


def test_first_sync_success_enqueues_pending_task(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)

    result = xiaoman_service.sync_invoice(db, invoice, operator_id=7)

    assert result["ok"] is True
    tasks = _tasks(db)
    assert len(tasks) == 1
    assert tasks[0].order_id == "424242"
    assert tasks[0].invoice_id == invoice.id
    assert tasks[0].status == outbound_task_service.STATUS_PENDING
    assert tasks[0].attempts == 0


def test_first_sync_with_unbackfilled_custom_marks_task_skipped(db, monkeypatch, no_reconcile):
    # 未回填非标行合并成通用产品行推送：出库无拣货意义 → skipped，不生成
    _seed_settings(db)
    _seed_binding(db)
    cp = _make_custom_product(db, "key-skip")
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    invoice.items.append(_custom_item(cp.id))
    db.flush()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_with_merged)

    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is True
    tasks = _tasks(db)
    assert len(tasks) == 1
    assert tasks[0].status == outbound_task_service.STATUS_SKIPPED
    assert "非标" in tasks[0].reason


def test_backfilled_custom_lines_still_enqueue_pending(db, monkeypatch, no_reconcile):
    # 已回填转正的 custom 行按真实 OKKI 产品推送，出库有意义 → pending
    _seed_settings(db)
    _seed_binding(db)
    cp = _make_custom_product(db, "key-promoted", okki_product_id=555, okki_sku_id=556)
    invoice = _make_invoice(db)
    invoice.items.append(_custom_item(cp.id))
    db.flush()

    def fake_push(_db, _payload):
        return {
            "order_id": 424242,
            "product_list": [{"unique_id": 111, "product_id": "555", "sku_id": "556"}],
        }

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is True
    assert [t.status for t in _tasks(db)] == [outbound_task_service.STATUS_PENDING]


def test_edit_repush_does_not_enqueue(db, monkeypatch, no_reconcile):
    # 编辑重推（action=update）：出库单首张已建，数量变化走 --remaining 人工补
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    db.flush()

    def fake_push(_db, _payload):
        return {
            "order_id": 424242,
            "product_list": [{"unique_id": 111, "product_id": "1", "sku_id": "9001"}],
        }

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is True
    assert _tasks(db) == []


def test_partial_accept_does_not_enqueue(db, monkeypatch, no_reconcile):
    # OKKI 静默丢行（okki_accepted）：明细不完整，绝不能按残缺订单建出库
    _seed_settings(db)
    _seed_binding(db)
    cp = _make_custom_product(db, "key-partial")
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    invoice.items.append(_custom_item(cp.id))
    db.flush()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)

    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is False and result["okki_accepted"] is True
    assert _tasks(db) == []


def test_failed_sync_does_not_enqueue(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()

    def fake_push(_db, _payload):
        raise okki_client.OkkiApiError("OKKI 订单推送失败：boom")

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is False
    assert _tasks(db) == []


def test_auto_trigger_disabled_by_flag(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)
    monkeypatch.setattr(
        xiaoman_service, "get_settings",
        lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=False),
    )

    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is True
    assert _tasks(db) == []


def test_enqueue_failure_never_breaks_sync(db, monkeypatch, no_reconcile):
    # 出库入队是尽力而为：异常只记日志，同步结果与落库不受影响，对账 job 兜底
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)

    def boom(_db, _invoice):
        raise RuntimeError("task table unavailable")

    monkeypatch.setattr(outbound_task_service, "enqueue_outbound_task", boom)
    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is True
    assert invoice.sync_status == "synced"
    assert invoice.xiaoman_order_id == "424242"
    assert _tasks(db) == []
    # 会话未被毒化：异常后仍可正常提交后续写入
    db.commit()


def test_enqueue_idempotent_per_order_id(db):
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item())
    db.flush()

    first = outbound_task_service.enqueue_outbound_task(db, invoice)
    second = outbound_task_service.enqueue_outbound_task(db, invoice)

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(_tasks(db)) == 1


def test_enqueue_returns_none_without_order_id(db):
    invoice = _make_invoice(db)
    assert outbound_task_service.enqueue_outbound_task(db, invoice) is None
    assert _tasks(db) == []


# ── 对账补入队 ──────────────────────────────────────────────


def _seed_create_log(db, invoice, *, hours_ago=1, success=1):
    db.add(InvoiceSyncLog(
        invoice_id=invoice.id,
        action="create",
        success=success,
        created_at=beijing_now() - timedelta(hours=hours_ago),
    ))
    db.flush()


def test_reconcile_backfills_task_for_recent_first_push(db):
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced")
    invoice.items.append(_stock_item())
    _seed_create_log(db, invoice, hours_ago=2)

    stats = outbound_task_service.reconcile_missing_outbound_tasks(db, window_hours=24)

    assert stats == {"scanned": 1, "enqueued": 1, "skipped": 0}
    assert [t.order_id for t in _tasks(db)] == ["424242"]


def test_reconcile_ignores_first_push_outside_window(db):
    # 功能上线前的历史订单（首推日志在窗口外）不补，避免回头建出库单
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced")
    invoice.items.append(_stock_item())
    _seed_create_log(db, invoice, hours_ago=72)

    stats = outbound_task_service.reconcile_missing_outbound_tasks(db, window_hours=24)

    assert stats == {"scanned": 0, "enqueued": 0, "skipped": 0}
    assert _tasks(db) == []


def test_reconcile_ignores_non_synced_and_failed_logs(db):
    # 首推部分受理/失败的发票保持人工核对，不自动补
    failed = _make_invoice(db, invoice_no="INV20260916-002", xiaoman_order_id="111111", sync_status="sync_failed")
    failed.items.append(_stock_item())
    _seed_create_log(db, failed, hours_ago=2, success=1)
    no_success_log = _make_invoice(db, invoice_no="INV20260916-003", xiaoman_order_id="222222", sync_status="synced")
    no_success_log.items.append(_stock_item(sort_order=1))
    _seed_create_log(db, no_success_log, hours_ago=2, success=0)

    stats = outbound_task_service.reconcile_missing_outbound_tasks(db, window_hours=24)

    assert stats == {"scanned": 0, "enqueued": 0, "skipped": 0}
    assert _tasks(db) == []


def test_reconcile_keeps_existing_task_and_marks_generic_merge_skipped(db):
    # 已有任务行的不重复补；含未建品非标行的补入队时落 skipped
    cp = _make_custom_product(db, "key-recon-skip")
    with_custom = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced")
    with_custom.items.append(_stock_item())
    with_custom.items.append(_custom_item(cp.id))
    _seed_create_log(db, with_custom, hours_ago=2)
    existing = _make_invoice(db, invoice_no="INV20260916-004", xiaoman_order_id="333333", sync_status="synced")
    existing.items.append(_stock_item())
    _seed_create_log(db, existing, hours_ago=2)
    outbound_task_service.enqueue_outbound_task(db, existing)
    db.flush()

    stats = outbound_task_service.reconcile_missing_outbound_tasks(db, window_hours=24)

    assert stats == {"scanned": 1, "enqueued": 0, "skipped": 1}
    tasks = _tasks(db)
    assert len(tasks) == 2
    by_order = {t.order_id: t for t in tasks}
    assert by_order["424242"].status == outbound_task_service.STATUS_SKIPPED
    assert by_order["333333"].status == outbound_task_service.STATUS_PENDING
