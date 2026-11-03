"""Real MySQL fence contention must queue the saved intent without another click."""
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from sqlalchemy.orm import Session, sessionmaker

from app.invoice import outbound_mode
from app.invoice.models import Invoice, InvoiceLinkedSync
from test_mysql_linked_execution import prepared, request
from mysql_current_fixture import current_queue_schema  # noqa: F401


def test_busy_saved_quantity_sync_is_pending_then_background_finishes_once(editor, monkeypatch, tmp_path):
    c = prepared(editor, monkeypatch, tmp_path)
    with Session(editor.ctx.engine) as other:
        with outbound_mode.executor_fence(other) as acquired:
            assert acquired
            response = request(c)
            assert response.status_code == 200, response.text
            result = response.json()['data']
            assert result['status'] == 'pending', result
            assert result['steps']['order']['status'] == 'pending'
            assert result['steps']['order']['category'] == 'inventory_busy'
            assert c.posts == []
            with Session(editor.ctx.engine) as db:
                task = db.get(InvoiceLinkedSync, c.identity)
                assert task.run_token is None and task.lease_until is None
    from app.invoice.linked_sync_worker import run_once
    factory = sessionmaker(bind=editor.ctx.engine)
    run_once(factory)
    assert len(c.posts) == 1
    with Session(editor.ctx.engine) as db:
        task = db.get(InvoiceLinkedSync, c.identity)
        assert task.steps['order']['status'] == 'done'
        assert task.status == 'manual' and task.run_token is None
    run_once(factory)
    assert len(c.posts) == 1


def _queued(c):
    with Session(c.e.ctx.engine) as other:
        with outbound_mode.executor_fence(other) as acquired:
            assert acquired
            response = request(c)
            assert response.status_code == 200, response.text
            assert response.json()['data']['status'] == 'pending'


def test_pending_intent_rechecks_original_actors_current_authority(editor, monkeypatch, tmp_path):
    from app.auth.models import ArkUser
    from app.invoice.linked_sync_worker import run_once
    c = prepared(editor, monkeypatch, tmp_path)
    _queued(c)
    with Session(editor.ctx.engine) as db:
        db.get(ArkUser, editor.ctx.actor).is_active = False
        db.commit()
    run_once(sessionmaker(bind=editor.ctx.engine))
    assert c.posts == []
    with Session(editor.ctx.engine) as db:
        task = db.get(InvoiceLinkedSync, c.identity)
        assert task.status == 'failed' and task.run_token is None
        assert task.steps['order']['category'] == 'queue_validation'


def test_two_background_runners_and_ui_do_not_repeat_a_queued_order(editor, monkeypatch, tmp_path):
    from app.invoice import okki_client
    from app.invoice.linked_sync_worker import run_once
    c = prepared(editor, monkeypatch, tmp_path)
    _queued(c)
    entered, release = Event(), Event()
    original_post = c.post
    def paused_post(url, **kwargs):
        entered.set()
        assert release.wait(15)
        return original_post(url, **kwargs)
    monkeypatch.setattr(okki_client.httpx, 'post', paused_post)
    factory = sessionmaker(bind=editor.ctx.engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_once, factory)
        assert entered.wait(15)
        try:
            second = pool.submit(run_once, factory).result(timeout=10)
            assert second['processed'] == 0
            foreground = request(c)
            assert foreground.status_code == 200
            assert foreground.json()['data']['status'] == 'running'
        finally:
            release.set()
        first.result(timeout=15)
    assert len(c.posts) == 1


def test_preparation_exception_finalizes_only_its_unsent_run(editor, monkeypatch, tmp_path):
    from app.invoice import order_sync_execution as orders
    c = prepared(editor, monkeypatch, tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('Synthetic preparation failure before original claim')
    monkeypatch.setattr(orders, 'prepare', fail)
    response = request(c)
    assert response.status_code == 500 and c.posts == []
    with Session(editor.ctx.engine) as db:
        task = db.get(InvoiceLinkedSync, c.identity)
        assert task.status == 'failed' and task.run_token is None and task.lease_until is None
        assert task.steps['order']['category'] == 'unsent_preparation'


def test_exception_after_durable_claim_preserves_uncertainty_and_never_replays(editor, monkeypatch, tmp_path):
    from app.invoice import order_sync_execution as orders
    from app.invoice.linked_sync_worker import run_once
    from app.commerce_transition.models import SendingClaim
    from sqlalchemy import select
    c = prepared(editor, monkeypatch, tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('Synthetic failure after durable original claim')
    monkeypatch.setattr(orders, 'send', fail)
    response = request(c)
    assert response.status_code == 500 and c.posts == []
    with Session(editor.ctx.engine) as db:
        task = db.get(InvoiceLinkedSync, c.identity)
        assert task.status == 'uncertain' and task.run_token is None and task.lease_until is None
        assert task.steps['order']['category'] == 'original_result'
        assert orders.facts.unresolved(db, db.get(Invoice, c.e.invoice_id))
        claim = db.scalar(select(SendingClaim).where(SendingClaim.active_invoice_key == c.e.invoice_id))
        assert claim is not None
        claim_id = claim.id
    run_once(sessionmaker(bind=editor.ctx.engine))
    assert c.posts == []
    with Session(editor.ctx.engine) as db:
        assert db.get(InvoiceLinkedSync, c.identity).status == 'uncertain'
        assert db.get(SendingClaim, claim_id).active_invoice_key == c.e.invoice_id
