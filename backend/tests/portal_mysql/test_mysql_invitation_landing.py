"""Opening the actual built activation page cannot consume the real invitation."""
import json
from pathlib import Path
import subprocess

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.portal import auth_service as auth, router
from app.portal.models import Account, AuditEvent, AuthChallenge, Invitation, Membership, OutboxEvent, PortalSession
from test_mysql_browser import employee_server
from test_mysql_invitation_race import invite


def test_opening_invitation_in_browser_does_not_activate(request, monkeypatch):
    paths = [request.config.getoption('portal_browser_' + name) for name in ('node', 'module', 'chromium')]
    if not all(paths): pytest.skip('Explicit browser runtime options required')
    ctx = request.getfixturevalue('trade')
    repo = Path(__file__).resolve().parents[3]
    dist = repo / 'frontend-portal/dist'
    assert (dist / 'index.html').is_file()
    with Session(ctx.engine) as db:
        invited = invite(ctx, db)
    models = (AuthChallenge, PortalSession, OutboxEvent, AuditEvent)
    def counts():
        with Session(ctx.engine) as db:
            return tuple(db.scalar(select(func.count()).select_from(model)) for model in models)
    before = counts()
    app = FastAPI()
    monkeypatch.setattr(router, 'get_settings', auth.get_settings)
    app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
    @app.get('/activate')
    def landing(): return FileResponse(dist / 'index.html')
    with employee_server(app) as origin:
        result = subprocess.run([paths[0], str(repo / 'frontend-portal/tests/invitationLanding.browser.mjs'),
            origin, paths[1], paths[2]], input=json.dumps({'token': invited.token}),
            text=True, encoding='utf-8', capture_output=True, timeout=60)
        # Avoid exposing a URL containing the invitation secret on a failed assertion.
        assert result.returncode == 0, 'Activation landing browser failed (output withheld to protect invitation token)'
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report['status'] == 'pass' and report['automaticApiRequests'] == 0
    assert counts() == before
    with Session(ctx.engine) as db:
        assert db.get(Invitation, invited.identifier).consumed_at is None
        assert db.get(Account, invited.account_id).status == 'invited'
        assert db.get(Account, invited.account_id).verified_at is None
        assert db.get(Membership, invited.member_id).status == 'invited'
    print(json.dumps(report))
