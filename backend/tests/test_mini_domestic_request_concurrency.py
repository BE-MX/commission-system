"""Blocking domestic services must leave unrelated ASGI requests responsive."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.core.database import get_db
from app.mini import router as mini


@pytest.mark.parametrize('method,path,body,name,result', [
    ('GET', '/domestic/history', None, 'list_today_reports', [
        {'revoked': 0, 'report_qty': 3}, {'revoked': 1, 'report_qty': 2},
    ]),
    ('GET', '/domestic/history/all?page=2&page_size=5', None, 'list_reports', ([], 11)),
    ('GET', '/domestic/scan/7?sign=valid', None, 'scan_item', {'item_id': 7}),
    ('GET', '/domestic/unit-scan/7?sign=valid', None, 'scan_unit', {'unit_id': 7}),
    ('POST', '/domestic/scan/submit', {
        'item_id': 7, 'progress_id': 8, 'qty': 1, 'request_id': 'same-request',
    }, 'submit_report', {'log_id': 9, 'replayed': True}),
    ('POST', '/domestic/scan/revoke', {'log_id': 9}, 'revoke_report', {'revoked_qty': 1}),
])
@pytest.mark.asyncio
async def test_domestic_work_does_not_block_event_loop(monkeypatch, method, path, body, name, result):
    app = FastAPI()
    app.include_router(mini.router, prefix='/api/mini')
    session = object()
    user = SimpleNamespace(id=42)
    app.dependency_overrides[get_db] = lambda: session
    for route in app.routes:
        if getattr(route, 'path', '').startswith('/api/mini/domestic/'):
            for dependency in route.dependant.dependencies:
                if dependency.name == 'current_user':
                    app.dependency_overrides[dependency.call] = lambda: user

    @app.get('/unrelated')
    async def unrelated():
        return {'responsive': True}

    monkeypatch.setattr(mini, '_domestic_report_mode', lambda _: 'unit' if name == 'scan_unit' else 'quantity')
    monkeypatch.setattr(mini.domestic_report_service, 'verify_qr_data', lambda _: (True, 7))
    monkeypatch.setattr(mini.domestic_report_service, 'verify_unit_qr_data', lambda _: (True, 7))
    started, release = threading.Event(), threading.Event()
    calls = []
    loop_thread = threading.get_ident()

    def blocking(db, *args, **kwargs):
        calls.append((db, threading.get_ident(), args, kwargs))
        started.set()
        if not release.wait(2):
            raise AssertionError('Unrelated request failed to release worker')
        return result

    monkeypatch.setattr(mini.domestic_report_service, name, blocking)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        pending = asyncio.create_task(client.request(method, '/api/mini' + path, json=body))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            assert not pending.done()
            response = await client.get('/unrelated')
            assert response.json() == {'responsive': True}
            assert not pending.done()
        finally:
            release.set()
            response = await pending
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert calls[0][0] is session
    assert calls[0][1] != loop_thread
    if name == 'list_today_reports':
        assert response.json() == {'today_count': 1, 'today_qty': 3, 'records': result}
    elif name == 'list_reports':
        assert calls[0][3] == {'page': 2, 'page_size': 5, 'user_id': 42}
        assert response.json() == {'items': [], 'total': 11, 'page': 2, 'page_size': 5}
    elif name == 'submit_report':
        assert calls[0][3]['request_id'] == 'same-request'
        assert calls[0][3]['user_id'] == 42
        assert response.json() == result
    elif name == 'revoke_report':
        assert calls[0][2] == (9, 42)
        assert response.json() == result
