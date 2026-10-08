"""Opt-in real employee login/JWT, built Chinese UI and MySQL approval."""
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import router as auth_router, admin_router as employee_router, service as auth_service, utils
from app.auth.models import ArkUser, ArkUserRole, ArkLoginLog, ArkRefreshToken
from app.core.database import get_db
from app.portal import admin_router
from test_mysql_services import accepted_request, assert_one_pi


@contextmanager
def employee_server(app):
    import uvicorn
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    origin = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False,
        proxy_headers=False, lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(500):
            if server.started: break
            time.sleep(.01)
        assert server.started
        yield origin
    finally:
        server.should_exit = True; thread.join(5); sock.close()
        assert not thread.is_alive()


def test_real_employee_login_chinese_ui_and_pi(request, monkeypatch):
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
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        actor = db.get(ArkUser, ctx.actor); root = db.get(ArkUser, ctx.admin)
        actor.password_hash = root.password_hash = utils.hash_password(password)
        outsider = ArkUser(username='outside-' + secrets.token_hex(6), real_name='Other Sales',
            password_hash=utils.hash_password(password), is_active=True)
        db.add(outsider); db.flush()
        role_id = db.scalar(select(ArkUserRole.role_id).where(ArkUserRole.user_id == ctx.actor))
        db.add(ArkUserRole(user_id=outsider.id, role_id=role_id)); db.commit()
        credentials = {'username': actor.username, 'password': password, 'admin': root.username,
            'outsider': outsider.username, 'actor': ctx.actor}
    request_id, body = accepted_request(ctx)
    credentials.update(request_id=request_id, approval=body.model_dump(mode='json'))
    app = FastAPI()
    app.include_router(auth_router.router, prefix='/api/auth')
    app.include_router(employee_router.router, prefix='/api/auth/admin')
    app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    # No identity, permission, JWT or API response overrides. Unknown API paths
    # stay 404 instead of returning the SPA document.
    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
    def unknown(path): return JSONResponse({'detail':'Not found'}, status_code=404)
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
    @app.get('/{path:path}')
    def frontend(path):
        target = (dist / path).resolve()
        if not target.is_relative_to(dist.resolve()): return JSONResponse({}, status_code=404)
        return FileResponse(target if target.is_file() else dist / 'index.html')
    output = request.getfixturevalue('tmp_path')
    with employee_server(app) as origin:
        result = subprocess.run([paths[0], str(repo / 'frontend/tests/portalLiveEmployee.browser.mjs'),
            origin, paths[1], paths[2], str(output)], input=json.dumps(credentials),
            text=True, encoding='utf-8', capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report['status'] == 'pass' and report['apiInterceptions'] == 0
    assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        assert not db.get(ArkUser, ctx.actor).is_active
        assert db.scalar(select(ArkLoginLog.id).where(ArkLoginLog.user_id == ctx.actor, ArkLoginLog.status == 'success'))
        assert db.scalar(select(ArkRefreshToken.id).where(ArkRefreshToken.user_id == ctx.actor))
    print(json.dumps(report))
