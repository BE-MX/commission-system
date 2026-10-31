"""发票首推成功后自动生成 OKKI 出库单的任务队列测试。

覆盖：首推入队 / 编辑重推唤醒等待库存 / 部分受理不入队 / 非标合并行落 skipped /
同 order_id 幂等 / 总开关关闭 / 对账补入队窗口口径。okki_client.push_order
一律 monkeypatch，不打真实接口。
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from tests.current_order_sync_helpers import install_transport, sync_current, current_order_readback


@pytest.fixture(autouse=True)
def current_order_transport(db, monkeypatch):
    install_transport(db, monkeypatch)

from sqlalchemy import text

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.invoice import okki_client, outbound_followup_service, outbound_task_service, product_service, xiaoman_service
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
    if "total_price" not in overrides:
        item.total_price = item.price_per_piece * item.quantity
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


def _fake_push_stock_only(_db, _payload, *, before_send=None):
    return {
        "order_id": 424242,
        "product_list": [{**_payload["product_list"][0], "unique_id": 111}],
    }


def _fake_push_with_merged(_db, _payload, *, before_send=None):
    return {
        "order_id": 424242,
        "product_list": [
            {**_payload["product_list"][0], "unique_id": 111},
            {**_payload["product_list"][1], "unique_id": 222},
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

    result = sync_current(db, invoice, operator_id=7)

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

    result = sync_current(db, invoice)

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

    def fake_push(_db, _payload, *, before_send=None):
        return {
            "order_id": 424242,
            "product_list": [{**_payload["product_list"][0], "unique_id": 111}],
        }

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = sync_current(db, invoice)

    assert result["ok"] is True
    assert [t.status for t in _tasks(db)] == [outbound_task_service.STATUS_PENDING]


def test_edit_repush_does_not_enqueue(db, monkeypatch, no_reconcile):
    # 编辑重推（action=update）：不为已建单创建新任务
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    db.flush()

    def fake_push(_db, _payload, *, before_send=None):
        return {
            "order_id": 424242,
            "product_list": [{**_payload["product_list"][0], "unique_id": 111}],
        }

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = sync_current(db, invoice)

    assert result["ok"] is True
    assert _tasks(db) == []


@pytest.mark.parametrize("regeneration", [False, True])
def test_successful_edit_requeues_waiting_stock_for_current_order(db, monkeypatch, no_reconcile, regeneration):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item(xiaoman_unique_id="111", quantity=2))
    db.flush()
    old_log = InvoiceSyncLog(invoice_id=invoice.id, action="update", success=1)
    db.add(old_log)
    db.flush()
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="424242", status="waiting_stock",
                            reason=(f"regenerate:{old_log.id} " if regeneration else "") + "Insufficient warehouse stock",
                            attempts=5, last_error='{"shortages":[{"sku_id":"old-sku"}]}')
    db.add(task)
    db.commit()

    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)
    result = sync_current(db, invoice)
    assert result["ok"] is True
    db.commit()
    db.refresh(task)
    newest = db.query(InvoiceSyncLog).filter_by(invoice_id=invoice.id, action="update", success=1).order_by(InvoiceSyncLog.id.desc()).first()
    assert task.status == "pending"
    assert task.attempts == 0
    assert task.last_error is None
    assert task.reason == (f"regenerate:{newest.id}" if regeneration else None)
    monkeypatch.setattr(outbound_followup_service.remote, "read", lambda *_args: current_order_readback(db, invoice))
    monkeypatch.setattr(outbound_followup_service.linked_outbound_service, "find_related", lambda *_args: [])
    monkeypatch.setattr(outbound_followup_service, "_stock_shortages",
                        lambda *_args: pytest.fail("backend stock API must not block the queued task"))
    reference = SimpleNamespace(id=invoice.id)
    db.rollback()
    assert outbound_followup_service.run(db, reference, {"sub": "1", "permissions": [], "roles": []})["status"] == "pending"


@pytest.mark.parametrize("status", ["running", "uncertain", "done", "skipped"])
def test_successful_edit_does_not_requeue_other_outbound_states(db, monkeypatch, no_reconcile, status):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242", outbound_auto_requested=1)
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="424242", status=status,
                            reason="preserve", attempts=3, last_error="preserve")
    db.add(task)
    db.commit()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)

    if status in {'running', 'uncertain'}:
        from fastapi import HTTPException
        monkeypatch.setattr(okki_client, 'push_order', lambda *args, **kwargs: pytest.fail('In-flight task forbids another POST'))
        with pytest.raises(HTTPException) as blocked:
            sync_current(db, invoice)
        assert blocked.value.status_code == 409
        db.rollback()
    else:
        assert sync_current(db, invoice)["ok"] is True
    db.commit()
    db.refresh(task)
    assert (task.status, task.reason, task.attempts, task.last_error) == (
        status, "preserve", 3, "preserve")


def test_incomplete_edit_does_not_requeue_waiting_stock(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item())
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="424242", status="waiting_stock",
                            reason="Insufficient warehouse stock", attempts=4, last_error="old shortage")
    db.add(task)
    db.commit()
    monkeypatch.setattr(okki_client, "push_order", lambda *args, **kwargs: {"order_id": 424242, "product_list": []})

    result = sync_current(db, invoice)
    assert result["ok"] is False and result["okki_accepted"] is True
    db.refresh(task)
    assert (task.status, task.attempts, task.last_error) == ("waiting_stock", 4, "old shortage")


def test_waiting_stock_requeue_rolls_back_with_incomplete_invoice_finalize(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="424242", status="waiting_stock",
                            reason="Insufficient warehouse stock", attempts=4, last_error="old shortage")
    db.add(task)
    db.commit()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)
    from app.invoice import order_sync_execution
    def incomplete(*args, **kwargs):
        raise RuntimeError('Injected actual finalization failure before the economic commit')
    monkeypatch.setattr(order_sync_execution.inventory, 'finalize_invoice_sync', incomplete)
    result = sync_current(db, invoice)
    assert result['ok'] is False and result['okki_accepted'] is True
    db.rollback()
    db.refresh(task)
    assert (task.status, task.attempts, task.last_error) == ("waiting_stock", 4, "old shortage")


def test_edited_order_with_unbackfilled_custom_line_skips_old_stock_task(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    custom = _make_custom_product(db, "new-custom-after-stock-wait")
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    invoice.items.append(_custom_item(custom.id))
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="424242", status="waiting_stock",
                            reason="Insufficient warehouse stock", attempts=4, last_error="old shortage")
    db.add(task)
    db.commit()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_with_merged)

    assert sync_current(db, invoice)["ok"] is True
    db.commit()
    db.refresh(task)
    assert task.status == "skipped"
    assert task.reason == outbound_task_service.SKIP_REASON_GENERIC_MERGE
    assert task.last_error is None


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

    result = sync_current(db, invoice)

    assert result["ok"] is False and result["okki_accepted"] is True
    assert _tasks(db) == []


def test_failed_sync_does_not_enqueue(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()

    def fake_push(_db, _payload, *, before_send=None):
        raise okki_client.OkkiApiError("OKKI 订单推送失败：boom")

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = sync_current(db, invoice)

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

    result = sync_current(db, invoice)

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
    result = sync_current(db, invoice)

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
    invoice.outbound_auto_requested = 1
    _seed_create_log(db, invoice, hours_ago=2)

    stats = outbound_task_service._reconcile_missing_outbound_tasks(db)

    assert stats == {"scanned": 1, "enqueued": 1, "skipped": 0}
    assert [t.order_id for t in _tasks(db)] == ["424242"]


def test_reconcile_ignores_first_push_outside_window(db):
    # 功能上线前的历史订单（首推日志在窗口外）不补，避免回头建出库单
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced")
    invoice.items.append(_stock_item())
    _seed_create_log(db, invoice, hours_ago=72)

    stats = outbound_task_service._reconcile_missing_outbound_tasks(db)

    assert stats == {"scanned": 0, "enqueued": 0, "skipped": 0}
    assert _tasks(db) == []


def test_reconcile_ignores_non_synced_and_failed_logs(db):
    # 首推部分受理/失败的发票保持人工核对，不自动补
    failed = _make_invoice(db, invoice_no="INV20260916-002", xiaoman_order_id="111111", sync_status="sync_failed")
    failed.outbound_auto_requested = 1
    failed.items.append(_stock_item())
    _seed_create_log(db, failed, hours_ago=2, success=1)
    no_success_log = _make_invoice(db, invoice_no="INV20260916-003", xiaoman_order_id="222222", sync_status="synced")
    no_success_log.outbound_auto_requested = 1
    no_success_log.items.append(_stock_item(sort_order=1))
    _seed_create_log(db, no_success_log, hours_ago=2, success=0)

    stats = outbound_task_service._reconcile_missing_outbound_tasks(db)

    assert stats == {"scanned": 0, "enqueued": 0, "skipped": 0}
    assert _tasks(db) == []


def test_reconcile_keeps_existing_task_and_marks_generic_merge_skipped(db):
    # 已有任务行的不重复补；含未建品非标行的补入队时落 skipped
    cp = _make_custom_product(db, "key-recon-skip")
    with_custom = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced")
    with_custom.items.append(_stock_item())
    with_custom.items.append(_custom_item(cp.id))
    with_custom.outbound_auto_requested = 1
    _seed_create_log(db, with_custom, hours_ago=2)
    existing = _make_invoice(db, invoice_no="INV20260916-004", xiaoman_order_id="333333", sync_status="synced")
    existing.items.append(_stock_item())
    _seed_create_log(db, existing, hours_ago=2)
    outbound_task_service.enqueue_outbound_task(db, existing)
    db.flush()

    stats = outbound_task_service._reconcile_missing_outbound_tasks(db)

    assert stats == {"scanned": 1, "enqueued": 0, "skipped": 1}
    tasks = _tasks(db)
    assert len(tasks) == 2
    by_order = {t.order_id: t for t in tasks}
    assert by_order["424242"].status == outbound_task_service.STATUS_SKIPPED
    assert by_order["333333"].status == outbound_task_service.STATUS_PENDING


def test_explicit_enrollment_survives_long_outage(db):
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced", outbound_auto_requested=1)
    invoice.items.append(_stock_item())
    _seed_create_log(db, invoice, hours_ago=240)
    assert outbound_task_service._reconcile_missing_outbound_tasks(db)["enqueued"] == 1


def test_cancellation_never_backfills_even_enrolled(db):
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced", status="cancelled", outbound_auto_requested=1)
    _seed_create_log(db, invoice)
    assert outbound_task_service._reconcile_missing_outbound_tasks(db)["enqueued"] == 0


@pytest.mark.parametrize("interrupted", [False, True])
def test_first_create_persists_outbound_intent_before_timeout_or_process_exit(db, monkeypatch, no_reconcile, interrupted):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.commit()
    def failed_push(*args, **kwargs):
        if interrupted:
            raise SystemExit("process interrupted during POST")
        raise okki_client.OkkiOutcomeUncertainError("order POST timed out")
    monkeypatch.setattr(okki_client, "push_order", failed_push)
    if interrupted:
        with pytest.raises(SystemExit):
            sync_current(db, invoice)
    else:
        assert sync_current(db, invoice)["ok"] is False
    db.rollback()
    db.refresh(invoice)
    assert invoice.sync_status == "sync_uncertain"
    assert invoice.outbound_auto_requested == 1
    assert _tasks(db) == []


@pytest.mark.parametrize("order_type,enabled,wanted", [("stock", True, 1), ("production", True, 1),
    ("presale", True, 0), ("stock", False, 0)])
def test_bound_uncertain_first_order_enrolls_only_after_full_sync(db, monkeypatch, no_reconcile, order_type, enabled, wanted):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, order_type=order_type, sync_status="sync_uncertain", status="sync_uncertain")
    invoice.items.append(_stock_item())
    db.execute(text("INSERT INTO lsordertest.okki_orders (order_id,order_no,name,company_id) VALUES (:id,:no,:name,:customer)"),
        {"id": "424242", "no": "SO-261008-001", "name": invoice.invoice_no, "customer": invoice.customer_id})
    db.commit()
    monkeypatch.setattr(xiaoman_service, "get_settings", lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=enabled))
    xiaoman_service.resolve_sync_uncertain(db, invoice, resolution="bind_order", reason="已核对小满原单号",
        operator_id=1, xiaoman_order_no=" SO-261008-001 ")
    db.commit()
    assert invoice.xiaoman_order_id == "424242" and invoice.xiaoman_order_no == "SO-261008-001"
    assert invoice.outbound_auto_requested == wanted
    assert invoice.sync_status == "not_synced" and _tasks(db) == []
    if order_type == "presale":
        assert outbound_task_service._reconcile_missing_outbound_tasks(db)["enqueued"] == 0
        return  # Presale has its own settlement and receipt preflight.
    # Receipt evidence has separate integration coverage; isolate outbound enrollment.
    from app.receipt import invoice_link
    monkeypatch.setattr(invoice_link, "preflight", lambda *args: None)
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)
    assert sync_current(db, invoice)["ok"] is True
    db.commit()
    assert len(_tasks(db)) == wanted
    assert sync_current(db, invoice)["ok"] is True
    db.commit()
    assert len(_tasks(db)) == wanted


def test_partial_first_acceptance_enqueues_after_lines_are_restored(db, monkeypatch, no_reconcile):
    from app.invoice import uncertain_recovery
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, total_amount=Decimal('37.50'), product_amount=Decimal('37.50'))
    invoice.items.append(_stock_item())
    db.commit()
    monkeypatch.setattr(okki_client, "push_order", lambda *a, **kw: {"order_id": 424242, "product_list": []})
    assert sync_current(db, invoice)["okki_accepted"] is True
    db.commit()
    assert invoice.outbound_auto_requested == 1 and _tasks(db) == []
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as blocked:
        sync_current(db, invoice)
    assert blocked.value.status_code == 409
    db.rollback()
    assert _tasks(db) == []
    rows, _, _, _ = xiaoman_service._build_product_rows(db, invoice, None, editing=True, reconciling=True)
    evidence = {
        'order_id':'424242', 'company_id':invoice.customer_id, 'currency':'USD',
        'amount': invoice.total_amount - invoice.surcharge_amount,
        'product_list':[{**rows[0], 'unique_id':111}],
    }
    from app.invoice import sync_recovery
    identity = invoice.id
    # The original request remains protected until its lease has elapsed, even
    # though this test already has the provider's complete, same-order proof.
    invoice.sync_attempt = {**invoice.sync_attempt,
        'lease_until': (beijing_now() - timedelta(seconds=1)).isoformat()}
    db.commit()
    monkeypatch.setattr(sync_recovery.lifecycle_remote, 'read', lambda *args: evidence)
    sync_recovery.resolve(db, identity, {'id': 1}, resolution='confirm_existing', reason='已独立核对原单明细与金额一致')
    assert sync_current(db, invoice)["ok"] is True
    db.commit()
    assert len(_tasks(db)) == 1 and _tasks(db)[0].status == "pending"


def test_current_executor_success_survives_later_caller_rollback(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242", outbound_auto_requested=1)
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    db.commit()
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)
    assert sync_current(db, invoice)["ok"] is True
    assert len(_tasks(db)) == 1
    db.rollback()
    db.refresh(invoice)
    assert invoice.sync_status == "synced" and len(_tasks(db)) == 1
    assert outbound_task_service._reconcile_missing_outbound_tasks(db)["enqueued"] == 0


def test_reconcile_restores_recovered_order_without_successful_create_log(db):
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced", outbound_auto_requested=1)
    invoice.items.append(_stock_item())
    db.add_all([InvoiceSyncLog(invoice_id=invoice.id, action="create", success=0),
        InvoiceSyncLog(invoice_id=invoice.id, action="uncertain_bind", success=1),
        InvoiceSyncLog(invoice_id=invoice.id, action="update", success=1)])
    db.flush()
    assert outbound_task_service._reconcile_missing_outbound_tasks(db)["enqueued"] == 1
    assert outbound_task_service._reconcile_missing_outbound_tasks(db)["enqueued"] == 0
    assert len(_tasks(db)) == 1


def test_reconcile_never_treats_binding_as_complete_sync(db):
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="synced", outbound_auto_requested=1)
    invoice.items.append(_stock_item())
    db.add_all([InvoiceSyncLog(invoice_id=invoice.id, action="create", success=0),
        InvoiceSyncLog(invoice_id=invoice.id, action="uncertain_bind", success=1)])
    db.flush()
    assert outbound_task_service._reconcile_missing_outbound_tasks(db)["enqueued"] == 0
    assert _tasks(db) == []


def _accepted_current_update(db, monkeypatch, *, enrolled=1, enabled=True, order_type="stock"):
    from app.invoice import order_sync_execution as execution
    invoice = _make_invoice(db, order_type=order_type, xiaoman_order_id="424242",
                            outbound_auto_requested=enrolled, status="sync_uncertain",
                            sync_status="sync_uncertain")
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    db.commit()
    rows, _, issues, _ = xiaoman_service._build_product_rows(db, invoice, None, editing=True)
    assert not issues
    attempt = SimpleNamespace(data={"action":"update"}, payload={"product_list":rows},
        key="recovered-update", actor_id=1, inventory_key=None, receipt_token=None)
    observation = {"result_class":"accepted", "provider_reference":"424242"}
    response = {"product_list":rows}
    monkeypatch.setattr(xiaoman_service, "get_settings", lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=enabled))
    monkeypatch.setattr(execution.inventory, "finalize_invoice_sync", lambda *args: None)
    monkeypatch.setattr(execution.invoice_link, "mark_success", lambda *args: {})
    monkeypatch.setattr(execution.invoice_link, "finish_attempt", lambda *args: None)
    return execution, invoice, attempt, observation, response


@pytest.mark.parametrize("enrolled,enabled,order_type,wanted", [
    (1, True, "stock", 1), (1, True, "production", 1),
    (0, True, "stock", 0), (1, False, "stock", 0), (1, True, "presale", 0),
])
def test_current_update_completes_original_outbound_enrollment(db, monkeypatch, enrolled, enabled, order_type, wanted):
    execution, invoice, attempt, observation, response = _accepted_current_update(
        db, monkeypatch, enrolled=enrolled, enabled=enabled, order_type=order_type)
    assert execution.apply(db, invoice, attempt, observation, response)["ok"] is True
    db.flush()
    assert len(_tasks(db)) == wanted
    assert execution.apply(db, invoice, attempt, observation, response)["ok"] is True
    db.flush()
    assert len(_tasks(db)) == wanted
    if wanted:
        assert _tasks(db)[0].order_id == "424242" and _tasks(db)[0].status == "pending"


@pytest.mark.parametrize("status", ["pending", "done", "uncertain", "running", "skipped"])
def test_current_update_preserves_existing_outbound_task(db, monkeypatch, status):
    execution, invoice, attempt, observation, response = _accepted_current_update(db, monkeypatch)
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="424242", status=status,
                            attempts=3, reason="Original task", last_error="Original evidence")
    db.add(task); db.commit()
    assert execution.apply(db, invoice, attempt, observation, response)["ok"] is True
    db.flush()
    assert len(_tasks(db)) == 1
    assert (task.status, task.attempts, task.reason, task.last_error) == (status, 3, "Original task", "Original evidence")


def test_current_update_wakes_original_stock_wait_without_new_task(db, monkeypatch):
    execution, invoice, attempt, observation, response = _accepted_current_update(db, monkeypatch)
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="424242", status="waiting_stock",
                            attempts=3, reason="Insufficient stock", last_error="Old shortage")
    db.add(task); db.commit()
    assert execution.apply(db, invoice, attempt, observation, response)["ok"] is True
    db.flush()
    assert len(_tasks(db)) == 1
    assert (task.status, task.attempts, task.reason, task.last_error) == ("pending", 0, None, None)


@pytest.mark.parametrize("failure", ["missing_rows", "inventory_finalize"])
def test_current_update_never_queues_incomplete_acceptance(db, monkeypatch, failure):
    execution, invoice, attempt, observation, response = _accepted_current_update(db, monkeypatch)
    if failure == "missing_rows":
        response = {"product_list":[]}
    else:
        def fail(*args):
            raise RuntimeError("Inventory finalization failed")
        monkeypatch.setattr(execution.inventory, "finalize_invoice_sync", fail)
    assert execution.apply(db, invoice, attempt, observation, response)["ok"] is False
    assert invoice.sync_status == "sync_uncertain" and _tasks(db) == []


def test_current_update_queue_rolls_back_with_order_finalization(db, monkeypatch):
    execution, invoice, attempt, observation, response = _accepted_current_update(db, monkeypatch)
    assert execution.apply(db, invoice, attempt, observation, response)["ok"] is True
    db.flush()
    assert len(_tasks(db)) == 1
    db.rollback(); db.refresh(invoice)
    assert invoice.sync_status == "sync_uncertain" and _tasks(db) == []



@pytest.mark.parametrize("amount", [None, "0", "0.00"])
def test_stock_zero_receipt_sync_enqueues_outbound_without_receipt(db, monkeypatch, no_reconcile, amount):
    from app.receipt import invoice_link, sync_service
    from app.receipt.models import Receipt
    from app.receipt.schemas import ReceiptDraft
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, order_type="stock")
    invoice.items.append(_stock_item())
    invoice_link.save_draft(db, invoice, ReceiptDraft(amount=amount), 1, new=True)
    db.commit()
    # The current executor owns arming and finishing the intent in its durable
    # attempt; callers no longer pass an independently armed legacy token.
    monkeypatch.setattr(okki_client, "push_order", _fake_push_stock_only)
    result = sync_current(db, invoice, operator_id=1)
    assert result["ok"] is True
    db.commit()
    sync_service.generate_ready(db)
    assert db.query(Receipt).count() == 0
    tasks = _tasks(db)
    assert len(tasks) == 1
    assert tasks[0].order_id == invoice.xiaoman_order_id == "424242"
    assert tasks[0].status == outbound_task_service.STATUS_PENDING
