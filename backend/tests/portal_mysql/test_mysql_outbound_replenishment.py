"""Immediate replenishment through actual authorization, MySQL and mocked supplier HTTP."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import Column, inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.invoice import outbound_mode, outbound_worker as worker
from app.invoice.models import OkkiOutboundTask
from app.shipping_inspection import outbound_inventory_router
from test_mysql_outbound_worker import prepare, records
from test_mysql_invoice_cancellation_refresh import demote_admin


@pytest.fixture(scope='session', autouse=True)
def current_catalog_fixture(service_schema):
    # The historical 182 fixture predates these catalog fields. Align synthetic
    # catalog inputs with today's ORM; this is not a production migration test.
    from app.core.database import Base
    with service_schema.engine.begin() as connection:
        operations=Operations(MigrationContext.configure(connection))
        for table in Base.metadata.tables.values():
            if not table.name.startswith('ark_order_portal_') or not inspect(connection).has_table(table.name):
                continue
            existing={row['name'] for row in inspect(connection).get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing:
                    operations.add_column(table.name,Column(column.name,column.type,nullable=True))


def setup_replenishment(editor, monkeypatch, tmp_path):
    c = prepare(editor, monkeypatch, tmp_path)
    monkeypatch.setattr(worker.get_settings(),'PORTAL_OUTBOUND_WORKER_ENABLED',False)
    with Session(editor.ctx.engine) as db:
        task=db.get(OkkiOutboundTask,c.task_id)
        task.status='waiting_stock'
        db.execute(text("DELETE FROM ark_order_portal_auth_barriers WHERE code='outbound-worker-v1'"))
        db.commit()
    editor.app.include_router(outbound_inventory_router.router,prefix='/api/shipping-inspection')
    c.route=f'/api/shipping-inspection/outbound-records/task:{c.task_id}/replenishment-sync'
    return c


def request(c):
    return asyncio.run(c.e.write(c.route,{},'POST',c.e.admin_token))


def test_manual_legacy_restock_executes_immediately_without_installing_worker_mode(editor,monkeypatch,tmp_path):
    c=setup_replenishment(editor,monkeypatch,tmp_path)
    result=request(c)
    assert result.status_code==200,result.text
    assert result.json()['data']['status']=='done'
    assert len(c.posts)==1
    assert records(c,worker.facts.START)[0][1]['manual_actor']==editor.ctx.admin
    with Session(editor.ctx.engine) as db:
        assert outbound_mode.read_mode(db)=='legacy'
    again=request(c)
    assert again.status_code==200 and len(c.posts)==1


def test_manual_stock_shortage_rechecks_now_without_creating_or_sending(editor,monkeypatch,tmp_path):
    c=setup_replenishment(editor,monkeypatch,tmp_path);c.stock=0
    result=request(c)
    assert result.status_code==200,result.text
    data=result.json()['data']
    assert data['status']=='waiting_stock' and data['shortages']
    assert c.posts==[] and records(c,worker.facts.SEND)==[]
    with Session(editor.ctx.engine) as db:
        error=json.loads(db.get(OkkiOutboundTask,c.task_id).last_error)
        assert error['shortages']==data['shortages']


def test_manual_replenishment_current_permission_is_required(editor,monkeypatch,tmp_path):
    c=setup_replenishment(editor,monkeypatch,tmp_path)
    demote_admin(editor,['invoice:sync'])
    result=request(c)
    assert result.status_code==403 and c.posts==[]


def test_two_clicks_share_native_executor_fence_and_only_one_submits(editor,monkeypatch,tmp_path):
    c=setup_replenishment(editor,monkeypatch,tmp_path)
    entered,release=Event(),Event()
    def gate(path):
        if path=='post':
            entered.set();assert release.wait(15)
    c.gate=gate
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(request,c)
        assert entered.wait(15)
        try:
            second=pool.submit(request,c).result(timeout=10)
            assert second.status_code==200,second.text
            assert second.json()['data']['status']=='busy'
        finally:release.set()
        result=first.result(timeout=15)
    assert result.status_code==200,result.text
    assert len(c.posts)==1


def test_order_resync_cannot_change_reservation_generation_during_outbound_send(editor,monkeypatch,tmp_path):
    c=setup_replenishment(editor,monkeypatch,tmp_path)
    entered,release=Event(),Event()
    def gate(path):
        if path=='post':
            entered.set();assert release.wait(15)
    c.gate=gate
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(request,c)
        assert entered.wait(15)
        try:
            route=f'/api/invoice/invoices/{editor.invoice_id}/sync'
            second=asyncio.run(editor.write(route,{},'POST',editor.admin_token))
            assert second.status_code==409,second.text
            assert '库存出库正在处理中' in second.json()['detail']
        finally:release.set()
        result=first.result(timeout=15)
    assert result.status_code==200,result.text
    assert len(c.posts)==1
