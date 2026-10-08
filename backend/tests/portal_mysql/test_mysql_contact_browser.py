"""Real admin login, contact configuration UI and owned MySQL persistence."""
import json
from pathlib import Path
import secrets
import subprocess
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import router as auth_router, service as auth_service, utils
from app.auth.models import ArkUser
from app.core.database import get_db
from app.portal import admin_router, admin_service, site_service
from app.portal.models import CustomerAccess, Site, Quote, AuditEvent
from test_mysql_browser import employee_server


def test_real_mysql_admin_contact_browser(request, monkeypatch):
    paths = [request.config.getoption('portal_browser_' + name) for name in ('node', 'module', 'chromium')]
    if not all(paths): pytest.skip('Explicit browser runtime options required')
    ctx = request.getfixturevalue('trade')
    repo = Path(__file__).resolve().parents[3]
    dist = repo / 'frontend/dist'
    assert (dist / 'index.html').is_file()
    settings = SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48), JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15, REFRESH_TOKEN_EXPIRE_DAYS=1, COOKIE_SECURE=False,
        LOGIN_LOCK_MINUTES=30, LOGIN_MAX_FAIL=5)
    for module in (auth_router, auth_service, utils): monkeypatch.setattr(module, 'settings', settings)
    monkeypatch.setattr(site_service, 'get_settings', admin_service.get_settings)
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        root = db.get(ArkUser, ctx.admin); root.password_hash = utils.hash_password(password)
        actor = db.get(ArkUser, ctx.actor)
        access = db.get(CustomerAccess, ctx.access_id); site = db.get(Site, access.site_id)
        seed = {'username': root.username, 'password': password, 'actor': actor.id,
            'employeeName': actor.real_name, 'policyVersion': site.policy_version}
        site_id, site_public_id = site.id, site.public_id
        db.commit()
    app = FastAPI()
    app.include_router(auth_router.router, prefix='/api/auth')
    app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
    def unknown(path): return JSONResponse({'detail': 'Not found'}, status_code=404)
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
    @app.get('/{path:path}')
    def frontend(path):
        target = (dist / path).resolve()
        if not target.is_relative_to(dist.resolve()): return JSONResponse({}, status_code=404)
        return FileResponse(target if target.is_file() else dist / 'index.html')
    output = request.getfixturevalue('tmp_path')
    with employee_server(app) as origin:
        result = subprocess.run([paths[0], str(repo / 'frontend/tests/portalLiveContacts.browser.mjs'),
            origin, paths[1], paths[2], str(output)], input=json.dumps(seed),
            text=True, encoding='utf-8', capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report['status'] == 'pass' and report['apiInterceptions'] == 0
    with Session(ctx.engine) as db:
        site = db.get(Site, site_id)
        assert site.policy_version == seed['policyVersion']
        assert site.policy_json['sales_contacts'][0]['approved'] is False
        assert db.scalar(select(Quote).where(Quote.access_id == ctx.access_id)).status == 'valid'
        events = db.scalars(select(AuditEvent).where(AuditEvent.object_public_id == site_public_id,
            AuditEvent.action == 'site_updated')).all()
        assert len(events) == 2
    print(json.dumps(report))
