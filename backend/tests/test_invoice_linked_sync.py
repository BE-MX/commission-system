"""SQLite-only state-machine regressions; external boundaries are mocked."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.core.time import beijing_now
from app.invoice import linked_sync_service as linked, linked_outbound_service as outbound, sync_coordinator
from app.invoice import outbound_followup_service as followup
from app.invoice.models import Invoice, InvoiceLinkedSync
from app.invoice.router import _linked_result
from app.invoice import router as invoice_router
from app.receipt import remote


@pytest.fixture
def order(db):
    row = Invoice(invoice_no="LINKED-TEST", order_type="production", customer_id="101", customer_name="Test",
        sales_user_id=1, invoice_date=date(2026, 9, 18), total_amount=Decimal("100"), currency="USD",
        xiaoman_order_id="123", sync_status="synced")
    db.add(row); db.commit()
    return row


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*a, **kw): raise AssertionError("Unexpected network access")
    monkeypatch.setattr(remote, "read", forbidden)
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: {"rows": []})


def operation(db, order, status="pending"):
    row = InvoiceLinkedSync(id="linked-test", invoice_id=order.id, request_key="request-test", request_hash="a"*64,
        created_by=1, status=status, before=linked.snapshot(order), after=linked.snapshot(order),
        steps={key: {"status": "pending"} for key in ("order", "outbound", "receipt")})
    order.linked_sync_id = row.id
    db.add(row); db.commit()
    return row


def successful_reads(monkeypatch):
    monkeypatch.setattr(remote, "read", lambda *a: {})
    monkeypatch.setattr(outbound, "summarize", lambda *a: {"status": "manual", "message": "Preserved shipped records"})


def test_plain_invoice_sync_returns_outbound_followup_separately(db, order, monkeypatch):
    monkeypatch.setattr(invoice_router, '_ensure_invoice_visible', lambda *a: None)
    monkeypatch.setattr(sync_coordinator, 'synchronize', lambda *a: {'ok': True, 'message': '已同步到小满'})
    monkeypatch.setattr(followup, 'safely_run', lambda *a: {'status': 'pending', 'message': '缺货核查已排队'})
    response = invoice_router.sync_invoice(order.id, db, {'sub': '1', 'permissions': ['invoice:sync']})
    assert response['data']['ok'] is True
    assert response['data']['outbound_sync']['status'] == 'pending'


def test_linked_invoice_sync_stores_outbound_followup_result(db, order, monkeypatch):
    row = operation(db, order, 'manual')
    order.linked_sync_id = None
    row.steps = {key: {'status': 'done'} for key in ('order', 'receipt')}
    row.steps = {**row.steps, 'outbound': {'status': 'manual', 'message': '旧出库资料'}}
    db.commit()
    monkeypatch.setattr(invoice_router, '_linked_scope', lambda *a: order)
    monkeypatch.setattr(linked, 'run', lambda *a, **kw: row)
    monkeypatch.setattr(followup, 'safely_run', lambda *a: {'status': 'done', 'message': '出库已更新'})
    response = invoice_router.run_linked(order.id, row.id, False, db, {'sub': '1', 'permissions': ['invoice:sync']})
    assert response['data']['status'] == 'done'
    assert row.steps['outbound']['message'] == '出库已更新'


def test_linked_receipt_read_failure_does_not_hold_outbound_followup(db, order, monkeypatch):
    row = operation(db, order)
    monkeypatch.setattr(sync_coordinator, 'synchronize', lambda *a, **kw: {'ok': True})
    monkeypatch.setattr(invoice_router, '_linked_scope', lambda *a: order)
    monkeypatch.setattr(linked.balance, 'calculate', lambda *a: (_ for _ in ()).throw(ValueError('回款暂不可用')))
    monkeypatch.setattr(followup, 'safely_run', lambda *a: {'status': 'done', 'message': '出库已更新'})
    result = invoice_router.run_linked(order.id, row.id, False, db, {'sub': '1', 'permissions': ['invoice:sync']})
    assert result['data']['steps']['order']['status'] == 'done'
    assert result['data']['steps']['outbound']['status'] == 'done'
    assert result['data']['steps']['receipt']['status'] == 'manual'
    assert order.linked_sync_id is None


def test_retry_reads_never_posts_order_again(db, order, monkeypatch):
    row = operation(db, order)
    calls = []
    monkeypatch.setattr(sync_coordinator, "synchronize", lambda *a, **kw: calls.append(1) or {"ok": True})
    assert linked.run(db, row.id, 1).status == "manual"
    assert row.steps["order"]["status"] == "done"
    successful_reads(monkeypatch)
    assert linked.run(db, row.id, 1, recheck=True).status == "manual"
    assert calls == [1] and order.linked_sync_id is None


def test_before_send_retryable_accepted_failure_frozen(db, order, monkeypatch):
    row = operation(db, order)
    def reject(*a, **kw): raise sync_coordinator.BeforeSendError(409, "库存不足")
    monkeypatch.setattr(sync_coordinator, "synchronize", reject)
    assert linked.run(db, row.id, 1).status == "failed"
    monkeypatch.setattr(sync_coordinator, "synchronize", lambda *a, **kw: {"ok": False, "okki_accepted": True})
    assert linked.run(db, row.id, 1).status == "uncertain"
    monkeypatch.setattr(sync_coordinator, "synchronize", lambda *a, **kw: pytest.fail("Must not replay"))
    assert linked.run(db, row.id, 1).status == "uncertain"
    with pytest.raises(ValueError): linked.close_failed(db, row.id)


def test_expired_lease_rejects_stale_completion(db, order):
    row = operation(db, order, "running")
    row.run_token = "old"; row.lease_until = beijing_now() - timedelta(seconds=1); db.commit()
    assert linked.expire(db, row.id).status == "uncertain"
    with pytest.raises(ValueError): linked._save_step(db, row.id, "old", "order", {"status": "done"})
    assert order.linked_sync_id == row.id


def test_manual_resolution_does_not_claim_success(db, order):
    row = operation(db, order, "uncertain")
    result = linked.resolve_manually(db, row.id, 8, "已人工核对原单，保留现有业务结果")
    assert result.status == "manual" and result.steps["order"]["status"] == "pending"
    assert result.steps["resolution"]["operator_id"] == 8 and order.linked_sync_id is None
    with pytest.raises(ValueError): linked.run(db, row.id, 1, recheck=True)


@pytest.mark.parametrize("effective,overpaid", [("120", "20"), ("80", "0")])
def test_pending_amount_is_not_refund(db, order, monkeypatch, effective, overpaid):
    row = operation(db, order)
    monkeypatch.setattr(sync_coordinator, "synchronize", lambda *a, **kw: {"ok": True})
    successful_reads(monkeypatch)
    monkeypatch.setattr(linked.balance, "calculate", lambda *a: {"effective_amount": effective,
        "registered_amount": "120", "remaining_amount": "-20", "total_amount": "100"})
    result = linked.run(db, row.id, 1)
    assert result.steps["receipt"]["overpaid_amount"] == overpaid
    assert result.steps["receipt"]["status"] == "manual"


def test_financial_result_requires_action_and_data_scope(db, order):
    row = operation(db, order)
    row.steps = {**row.steps, "receipt": {"status": "done", "balance": {"amount": "120"}}}
    for user in [{"sub": "1", "permissions": []}, {"sub": "2", "permissions": ["receipt:read"]},
                 {"sub": "2", "permissions": ["receipt:read_all"]}]:
        assert "balance" not in _linked_result(row, order, user)["steps"]["receipt"]
    assert "balance" in _linked_result(row, order, {"sub": "2", "permissions": ["receipt:read_all", "receipt:read"]})["steps"]["receipt"]


def test_same_second_edit_changes_version(db, order):
    old_time, version = order.updated_at, linked.edit_version(order)
    order.remark = "another editor"; order.updated_at = old_time
    assert linked.edit_version(order) != version
    body = SimpleNamespace(request_key="fresh-key", expected_version=version, model_dump_json=lambda: "{}")
    with pytest.raises(ValueError, match="他人修改"): linked.create(db, order, body, 1)


def test_create_idempotency(db, order, monkeypatch):
    monkeypatch.setattr(linked.service, "update_invoice", lambda *a, **kw: None)
    body = SimpleNamespace(request_key="fresh-key", expected_version=linked.edit_version(order), invoice=None, model_dump_json=lambda: "{}")
    first = linked.create(db, order, body, 1); db.commit()
    assert linked.create(db, order, body, 1).id == first.id
    body.model_dump_json = lambda: '{"changed":true}'
    with pytest.raises(ValueError): linked.create(db, order, body, 1)
    with pytest.raises(ValueError): linked.ensure_idle(order)


def test_outbound_incomplete_page_is_not_absence(monkeypatch):
    monkeypatch.setattr(remote, "read", lambda *a: {"list": [], "count": 2})
    with pytest.raises(ValueError): outbound.find_related(None, {"order_id": "123", "create_time": "2026-09-18"})


def test_shipped_outbound_only_reports_difference(db, order, monkeypatch):
    monkeypatch.setattr(outbound, "find_related", lambda *a: [{"outbound_invoice_id": 9, "status": 2,
        "record_list": [{"order_id": "123", "product_id": 1, "sku_id": 2, "outbound_count": "3"}]}])
    result = outbound.summarize(db, order, {"order_id": "123"})
    assert result["status"] == "manual" and result["differences"][0]["difference"] == "-3"

def test_old_runner_cannot_send_after_manual_resolution(db, order):
    row = operation(db, order, "running")
    row.run_token = "old"; row.lease_until = beijing_now() - timedelta(seconds=1); db.commit()
    linked.expire(db, row.id)
    linked.resolve_manually(db, row.id, 8, "已人工核对各关联单据，结束原任务")
    order.remark = "new version"; db.commit()
    with pytest.raises(linked.LostExecution): linked.ensure_running(db, order, row.id, "old")
    assert order.remark == "new version"


def test_fence_checked_after_auth_refresh(monkeypatch):
    from app.invoice import okki_client
    calls = []
    monkeypatch.setattr(okki_client, "ensure_access_token", lambda *a, **kw: "token")
    monkeypatch.setattr(okki_client, "_post_json", lambda *a, **kw: calls.append("post") or None)
    def fence():
        if calls: raise linked.LostExecution("expired")
    with pytest.raises(linked.LostExecution): okki_client.push_order(None, {}, before_send=fence)
    assert calls == ["post"]

def test_migration_preserves_history_on_restart():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / "alembic/versions/158_invoice_linked_sync.py"
    spec = importlib.util.spec_from_file_location("linked_migration", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE ark_invoices (id BIGINT PRIMARY KEY)"))
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        conn.execute(sa.text("INSERT INTO ark_invoice_linked_syncs VALUES ('x', 1, 'key', 'hash', 'manual', '{}', '{}', '{}', NULL, NULL, 1, '2026-09-18 00:00:00', '2026-09-18 00:00:00')"))
        module.upgrade()
        assert conn.execute(sa.text("SELECT COUNT(*) FROM ark_invoice_linked_syncs")).scalar() == 1
        assert {c['name'] for c in sa.inspect(conn).get_columns('ark_invoice_linked_syncs')} == set(InvoiceLinkedSync.__table__.columns.keys())
        with pytest.raises(RuntimeError): module.downgrade()
    engine.dispose()


@pytest.mark.parametrize("clock", ["2026-09-17T23:59:59", "2026-09-18T00:00:01"])
def test_lease_uses_beijing_clock_across_midnight(db, order, monkeypatch, clock):
    from datetime import datetime
    now = datetime.fromisoformat(clock)
    monkeypatch.setattr(linked, "beijing_now", lambda: now)
    row = operation(db, order, "running")
    row.run_token = 'current'; row.lease_until = now + timedelta(minutes=30); db.commit()
    linked.ensure_running(db, order, row.id, 'current')
    monkeypatch.setattr(linked, "beijing_now", lambda: now + timedelta(minutes=31))
    with pytest.raises(linked.LostExecution): linked.ensure_running(db, order, row.id, 'current')

def test_fence_preserves_unflushed_success_with_production_autoflush(db, order):
    db.autoflush = False
    order.sync_status = 'synced'; order.synced_at = beijing_now()
    stamp = order.synced_at
    linked.ensure_running(db, order)
    assert order.synced_at == stamp
    db.commit(); db.refresh(order)
    assert order.sync_status == 'synced' and order.synced_at == stamp

def test_coordinator_persists_success_with_autoflush_disabled(db, order, monkeypatch):
    db.autoflush = False
    row = operation(db, order, 'running')
    row.run_token = 'current'; row.lease_until = beijing_now() + timedelta(minutes=30); db.commit()
    def accepted(db, invoice, **kwargs):
        invoice.sync_status = 'synced'; invoice.status = 'synced'; invoice.synced_at = beijing_now()
        return {'ok': True}
    monkeypatch.setattr(sync_coordinator.xiaoman_service, 'sync_invoice', accepted)
    result = sync_coordinator.synchronize(db, order, 1, linked_id=row.id, linked_token='current')
    db.refresh(order)
    assert result['ok'] and order.sync_status == 'synced' and order.synced_at is not None


def test_old_runner_cannot_prepare_inventory_after_arm_commit(db, order, monkeypatch):
    from app.receipt import invoice_link
    row = operation(db, order, 'running')
    row.run_token = 'current'; row.lease_until = beijing_now() + timedelta(minutes=30); db.commit()
    def interrupted_arm(*a):
        row.lease_until = beijing_now() - timedelta(seconds=1); db.commit()
        linked.expire(db, row.id)
        linked.resolve_manually(db, row.id, 8, '管理员核对后结束，防止旧任务继续')
        return 'old-attempt'
    monkeypatch.setattr(invoice_link, 'arm', interrupted_arm)
    monkeypatch.setattr(sync_coordinator.semifinished_invoice_service, 'prepare_invoice_sync', lambda *a: pytest.fail('Old worker must not reserve'))
    with pytest.raises(linked.LostExecution):
        sync_coordinator.synchronize(db, order, 1, linked_id=row.id, linked_token='current')
