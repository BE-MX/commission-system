"""Opt-in HTTPS browser test: real customer routes, local SQLite, no SMTP or MySQL.

The loopback-only QA mailbox/control routes exist in this test app, never in app.main.
The Python reverse proxy overwrites X-Real-IP and connects from a distinct loopback IP.
"""
import json
from pathlib import Path
import subprocess
import threading

import pytest
from live_browser_server import running_portal
from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from test_admin_service import managed, portal_metadata, auth_context
from app.core.time import beijing_now
from app.core.database import get_db
from app.portal import access_policy, admin_service, authority, router as customer_router
from app.portal.access_policy import validate_binding as real_validate_binding
from app.portal.models import Account, OutboxEvent
from app.portal.schemas import AccountUpdate
from app.portal.security import open_secret


def test_real_https_cookie_origin_proxy_logout_and_revocation(managed, monkeypatch, request):
    paths = [request.config.getoption(name) for name in ('portal_browser_node', 'portal_browser_module', 'portal_browser_chromium')]
    if not all(paths): pytest.skip('Opt in with --portal-browser-node/module/chromium')
    tmp_path = request.getfixturevalue("tmp_path")
    ctx = managed
    repo = Path(__file__).resolve().parents[3]
    dist = repo / 'frontend-portal/dist'
    assert (dist / 'index.html').exists(), 'Build frontend-portal before this browser test'
    # Restore the actual company/owner binding checks replaced by the base auth fixture.
    monkeypatch.setattr(access_policy, 'validate_binding', real_validate_binding)
    monkeypatch.setattr(customer_router, 'get_settings', lambda: ctx.settings)
    monkeypatch.setattr(authority, 'get_settings', lambda: ctx.settings)
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.2']
    ctx.account.verified_at = beijing_now()
    account_id = ctx.account.public_id
    lock = threading.Lock()  # StaticPool shares one SQLite connection; this is not a concurrency test.
    factory = sessionmaker(bind=ctx.db.get_bind())
    def database():
        with lock, factory() as db:
            yield db
    app = FastAPI(); app.include_router(customer_router.router, prefix='/api/portal/v1')
    app.dependency_overrides[get_db] = database

    @app.get('/__qa/mailbox')
    def mailbox(db=Depends(get_db)):
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == 'auth_code').order_by(OutboxEvent.id.desc()))
        assert row is not None
        return {'code': open_secret(ctx.settings.PORTAL_MAIL_KEYS['v1'], row.secret_envelope,
            event_key=row.event_key, purpose='login', object_id=row.aggregate_public_id)}

    @app.post('/__qa/disable')
    def disable(db=Depends(get_db)):
        account = db.scalar(select(Account).where(Account.public_id == account_id))
        admin_service.update_account(db, 1, account_id, account.row_version,
                                     AccountUpdate(status='disabled', reason='Isolated revocation test'))
        db.commit()
        return {'disabled': True}

    with running_portal(app, ctx, dist, tmp_path) as (origin, backend):
        result = subprocess.run([paths[0], str(repo / 'frontend-portal/tests/liveAuth.browser.mjs'),
            origin, backend, paths[1], paths[2]], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report['status'] == 'pass' and report['network'] == 'real-local-https'
        print(json.dumps(report))
