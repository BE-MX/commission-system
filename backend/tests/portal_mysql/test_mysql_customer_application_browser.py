"""Current customer bundle -> actual app.main/lifespan -> exclusively owned MySQL.

The ASGI shell is a test loopback proxy/OTP broker and one controlled ACK fault.
It never replaces portal/auth/admin business endpoints or fabricates their results.
Non-portal seeds/jobs/upstream mirror remain the assembled commerce fixture.
"""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import http.client
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from uuid import UUID, uuid4

import pytest
from pypdf import PdfReader
from sqlalchemy import select, event
from sqlalchemy.orm import Session
from starlette.responses import FileResponse, JSONResponse
import uvicorn

from app.core.time import beijing_now
from app.portal import auth_service as auth
from app.portal.models import (Account, AuthChallenge, CommandReceipt, Conversion, CustomerAccess,
    Invitation, MappingRevision, Membership, OrderRequest, OutboxEvent, PortalSession, Publication, Revision, Site)
from app.portal.security import open_secret
from owned_invitation_mailbox import activated_login_allowed, invitation_evidence
from owned_process import consume_owned_process, safe_runner_summary
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from test_mysql_application_trade import commerce, business_snapshot  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401


BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
RECEIPT_PHASE = ContextVar('owned_action_receipt', default=None)
ACCEPT = re.compile(r'^/api/portal/v1/orders/([0-9a-f-]{36})/proposals/([0-9a-f-]{36})/accept$')


class OwnedApplicationShell:
    """No production proxy claim: overwrite identity headers only on owned TCP."""
    def __init__(self, fixture, frontend):
        self.fixture = fixture
        self.frontend = frontend.resolve(strict=True)
        self.employee_frontend = (ROOT / 'frontend/dist').resolve(strict=True)
        assert (self.employee_frontend / 'index.html').is_file()
        self.broker_key = secrets.token_urlsafe(32)
        self.arm_accept = False
        self.fault_count = 0
        self.accept_original = None
        self.calls = Counter()
        self.receipt_observations = []
        self.pdf_documents = []
        self.publication_snapshots = []
        self.published_graphs = []
        self.original_mapping_snapshots = []
        self.invited_account_id = None
        self.invited_invitation_id = None
        self.invitation_landing_snapshots = []
        self.otp_codes = set()
        self.otp_reads = Counter()
        self.receipt_dml = []
        self.receipt_business_writes = []

    def observe_receipt_dml(self, connection, cursor, statement, parameters, context, executemany):
        # Context propagates through actual AnyIO sync router/dependency threads.
        if RECEIPT_PHASE.get() is not self: return
        matched = re.match(r'\s*(INSERT|REPLACE|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\b', statement, re.I)
        if not matched: return
        operation = matched.group(1).upper()
        table = re.match(r'\s*(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+[`"]?(\w+)', statement, re.I)
        target = table.group(1) if table else '<DDL>'
        self.receipt_dml.append((operation, target))
        if operation != 'UPDATE' or target != PortalSession.__tablename__:
            self.receipt_business_writes.append((operation, target))
            raise AssertionError('Receipt GET attempted a commercial database write')

    async def respond(self, scope, receive, send, code, data):
        await JSONResponse(data, status_code=code, headers={
            'Cache-Control': 'no-store', 'Pragma': 'no-cache',
            'X-Content-Type-Options': 'nosniff'})(scope, receive, send)

    async def broker(self, scope, receive, send):
        headers = dict(scope.get('headers', []))
        supplied = headers.get(b'x-owned-broker', b'')
        if not hmac.compare_digest(supplied, self.broker_key.encode()):
            return await self.respond(scope, receive, send, 403, {'error': 'Owned broker authorization required'})
        path, method = scope['path'], scope['method']
        if method == 'GET' and path.startswith('/__owned/invitation/'):
            evidence = invitation_evidence(self, path.removeprefix('/__owned/invitation/'))
            if evidence is None:
                return await self.respond(scope, receive, send, 404, {'error': 'Owned invitation not available'})
            return await self.respond(scope, receive, send, 200, evidence)
        if method == 'GET' and path.startswith('/__owned/otp/'):
            try:
                challenge_id = str(UUID(path.removeprefix('/__owned/otp/')))
            except ValueError:
                return await self.respond(scope, receive, send, 404, {'error': 'Owned challenge not available'})
            c = self.fixture
            with Session(c.app.ctx.engine) as db:
                allowed = (AuthChallenge.account_id.in_([c.buyer_id, c.other_buyer_id, c.forwarded_id])) & (AuthChallenge.purpose == 'login')
                if self.invited_account_id is not None:
                    allowed |= ((AuthChallenge.account_id == self.invited_account_id) & (AuthChallenge.purpose == 'activate') &
                        (AuthChallenge.invitation_id == self.invited_invitation_id))
                if hasattr(c, 'onboard_customer_id') and self.invited_account_id is not None:
                    allowed |= ((AuthChallenge.account_id == self.invited_account_id) &
                        (AuthChallenge.purpose == 'login') & AuthChallenge.invitation_id.is_(None))
                challenge = db.scalar(select(AuthChallenge).where(AuthChallenge.public_id == challenge_id, allowed))
                if (challenge is not None and challenge.account_id == self.invited_account_id
                    and challenge.purpose == 'login' and not activated_login_allowed(db, self, challenge)):
                    return await self.respond(scope, receive, send, 404, {'error': 'Owned challenge not available'})
                account = db.get(Account, challenge.account_id) if challenge else None
                event = db.scalar(select(OutboxEvent).where(
                    OutboxEvent.aggregate_public_id == challenge_id,
                    OutboxEvent.event_type == 'auth_code')) if challenge else None
                if (challenge is None or account is None or event is None or
                    challenge.consumed_at is not None or challenge.revoked_at is not None or
                    challenge.expires_at <= beijing_now() or event.secret_envelope is None):
                    return await self.respond(scope, receive, send, 404, {'error': 'Owned challenge not available'})
                code = open_secret(c.app.settings.PORTAL_MAIL_KEYS[event.secret_key_version],
                    event.secret_envelope, event_key=event.event_key,
                    purpose=challenge.purpose, object_id=challenge_id)
                self.otp_reads[challenge.account_id] += 1
                self.otp_codes.add(code)
            return await self.respond(scope, receive, send, 200, {'code': code})
        if method == 'POST' and path == '/__owned/control':
            data = bytearray()
            while True:
                message = await receive()
                if message['type'] != 'http.request':
                    return await self.respond(scope, receive, send, 400, {'error': 'Invalid owned control'})
                data.extend(message.get('body', b''))
                if len(data) > 128:
                    return await self.respond(scope, receive, send, 400, {'error': 'Invalid owned control'})
                if not message.get('more_body', False): break
            try:
                payload = json.loads(data)
            except (ValueError, UnicodeError):
                payload = None
            if payload != {'fault': 'accept_ack'} or self.arm_accept or self.fault_count:
                return await self.respond(scope, receive, send, 400, {'error': 'Invalid owned control'})
            self.arm_accept = True
            return await self.respond(scope, receive, send, 200, {'armed': True})
        return await self.respond(scope, receive, send, 404, {'error': 'Owned broker entry not available'})

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.fixture.app.app(scope, receive, send)
        scope = dict(scope)
        # Uvicorn also has proxy_headers=False: the trusted peer is actual TCP.
        assert scope.get('client', ('',))[0] == '127.0.0.1'
        scope['headers'] = [(name, value) for name, value in scope.get('headers', [])
            if name.lower() not in {b'x-real-ip', b'x-forwarded-for', b'x-forwarded-proto',
                b'x-forwarded-host', b'forwarded'}] + [(b'x-real-ip', b'127.0.0.1')]
        path, method = scope['path'], scope['method']
        if path.startswith('/__owned/'):
            return await self.broker(scope, receive, send)
        if path == '/api' or path.startswith('/api/') or path == '/health' or path.startswith('/mcp'):
            self.calls[(method, path)] += 1
            capture = bool(ACCEPT.fullmatch(path) and method == 'POST') or (
                method == 'GET' and (path.endswith('/action-receipt') or path.endswith('/pi')))
            if not capture:
                return await self.fixture.app.app(scope, receive, send)
            before = business_snapshot(self.fixture) if path.endswith('/action-receipt') else None
            messages = []
            async def buffered(message):
                messages.append(dict(message))
            receipt_token = RECEIPT_PHASE.set(self) if path.endswith('/action-receipt') else None
            try:
                await self.fixture.app.app(scope, receive, buffered)
            finally:
                if receipt_token is not None: RECEIPT_PHASE.reset(receipt_token)
            status = next(message['status'] for message in messages if message['type'] == 'http.response.start')
            body = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
            if path.endswith('/action-receipt'):
                assert business_snapshot(self.fixture) == before, 'Receipt GET changed commercial rows'
                if status == 200:
                    self.receipt_observations.append(json.loads(body)['data'])
            if path.endswith('/pi') and status == 200:
                assert body.startswith(b'%PDF-')
                self.pdf_documents.append(body)
                with Session(self.fixture.app.ctx.engine) as db:
                    order_id = db.scalar(select(OrderRequest.id).where(OrderRequest.public_id == path.split('/')[-2]))
                    rows = db.execute(select(*Publication.__table__.columns).where(Publication.request_id == order_id).order_by(Publication.id)).all()
                    self.publication_snapshots.append(tuple(tuple(row) for row in rows))
                self.published_graphs.append(published_graph(self.fixture, path.split('/')[-2]))
                self.original_mapping_snapshots.append(original_mapping(self.fixture))
            if ACCEPT.fullmatch(path) and method == 'POST' and self.arm_accept and status == 200:
                self.arm_accept = False
                self.fault_count += 1
                self.accept_original = json.loads(body)['data']['original_receipt']
                # Main has returned its original 200 after actual service commit.
                # This is a controlled response replacement, not packet loss/crash.
                return await self.respond(scope, receive, send, 503, {'code': 503,
                    'message': 'The original action result needs checking.',
                    'data': {'error_code': 'OWNED_ACK_LOST', 'retryable': True, 'issues': []}})
            for message in messages:
                await send(message)
            return
        if method not in {'GET', 'HEAD'}:
            return await self.respond(scope, receive, send, 404, {'error': 'Entry not available'})
        # Test-only two-bundle static host. Every /api path still enters actual main.
        employee_route = path == '/login' or path == '/portal' or path.startswith('/portal/')
        roots = (self.employee_frontend, self.frontend) if employee_route else (self.frontend, self.employee_frontend)
        target = None
        for static_root in roots:
            candidate = (static_root / path.lstrip('/')).resolve()
            if not candidate.is_relative_to(static_root):
                return await self.respond(scope, receive, send, 404, {'error': 'Entry not available'})
            if candidate.is_file():
                target = candidate
                break
        if target is None and (path == '/' or not Path(path).suffix):
            target = roots[0] / 'index.html'
        if target is None or not target.is_file():
            return await self.respond(scope, receive, send, 404, {'error': 'Entry not available'})
        await FileResponse(target, headers={'Cache-Control': 'no-store'})(scope, receive, send)


@contextmanager
def live_application(c):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    # The actual main and actual auth fixture share the same selected origin.
    c.app.settings.PORTAL_ORIGIN = origin
    c.app.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    c.app.settings.CORS_ALLOW_ORIGINS = [origin]
    auth_settings = auth.get_settings()
    auth_settings.PORTAL_ORIGIN = origin
    auth_settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    for middleware in c.app.app.user_middleware:
        if middleware.cls.__name__ == 'CORSMiddleware':
            middleware.kwargs['allow_origins'] = [origin]
    assert c.app.app.middleware_stack is None
    with Session(c.app.ctx.engine) as db:
        access = db.get(CustomerAccess, c.app.ctx.access_id)
        db.get(Site, access.site_id).allowed_origin = origin
        db.commit()
    shell = OwnedApplicationShell(c, ROOT / 'frontend-portal/dist')
    errors = []
    server = uvicorn.Server(uvicorn.Config(shell, host='127.0.0.1', port=listener.getsockname()[1],
        lifespan='on', proxy_headers=False, access_log=False, log_config=None, log_level='critical'))
    def serve():
        try: server.run(sockets=[listener])
        except BaseException as error: errors.append(error)
    thread = threading.Thread(target=serve, name='owned-customer-asgi', daemon=True)
    event.listen(c.app.ctx.engine, 'before_cursor_execute', shell.observe_receipt_dml)
    try:
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started and thread.is_alive() and not errors, 'Owned ASGI failed to start'
        yield origin, shell
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        listener.close()
        event.remove(c.app.ctx.engine, 'before_cursor_execute', shell.observe_receipt_dml)
        assert not thread.is_alive(), 'Owned ASGI thread did not stop'
        assert not errors, 'Owned ASGI lifecycle failed'
        assert c.app.main._scheduler is None and c.app.registry._active_scheduler is None
        assert c.app.events.count('dispose') == 1


def published_graph(c, public_id):
    """Every persisted column of the original publication and commercial lineage."""
    with Session(c.app.ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == public_id))
        assert order is not None and order.invoice_id is not None
        predicates = ((Publication, Publication.request_id == order.id),
            (Invoice, Invoice.id == order.invoice_id),
            (InvoiceItem, InvoiceItem.invoice_id == order.invoice_id),
            (Conversion, Conversion.request_id == order.id),
            (ReceiptIntent, ReceiptIntent.invoice_id == order.invoice_id))
        return tuple(tuple(tuple(row) for row in db.execute(
            select(*model.__table__.columns).where(predicate).order_by(model.id)).all())
            for model, predicate in predicates)


def original_mapping(c):
    """All persisted columns of the original mapping; new versions may be added."""
    with Session(c.app.ctx.engine) as db:
        rows = db.execute(select(*MappingRevision.__table__.columns).where(
            MappingRevision.access_id == c.app.ctx.access_id,
            MappingRevision.version == 1).order_by(MappingRevision.id)).all()
        assert len(rows) == 1
        return tuple(tuple(row) for row in rows)


def broker_call(origin, path, key=None, payload=None):
    parsed = origin.removeprefix('http://').split(':')
    connection = http.client.HTTPConnection(parsed[0], int(parsed[1]), timeout=5)
    try:
        connection.request('GET' if payload is None else 'POST', path,
            body=None if payload is None else json.dumps(payload),
            headers={} if key is None else {'X-Owned-Broker': key, 'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data
    finally: connection.close()






def run_browser(c, shell, node, script, origin, playwright, chrome, output):
    seed = None
    private_input = ''
    try:
        with Session(c.app.ctx.engine) as db:
            seed = {'buyerEmail': c.buyer_email, 'otherBuyerEmail': c.other_buyer_email,
                'invitedBuyerEmail': c.invited_email, 'forwardedBuyerEmail': c.forwarded_email,
                'buyerAccountPublicId': db.get(Account, c.buyer_id).public_id,
                'otherBuyerAccountPublicId': db.get(Account, c.other_buyer_id).public_id,
                'ownerUsername': c.owner_name, 'otherUsername': c.other_name,
                'rootUsername': c.root_name, 'password': c.password,
                'ownerId': c.app.ctx.actor, 'accessId': c.access_id,
                'accessVersion': c.access_version, 'itemId': c.item_id,
                'otherAccessId': c.other_access_id, 'standardModel': c.catalog_model,
                'standardColor': c.catalog_color,
                'standardColorKey': c.standard['color_key'], 'brokerKey': shell.broker_key}
        if hasattr(c, 'onboard_customer_id'):
            seed.update({'onboardCustomerId': str(c.onboard_customer_id), 'onboardCustomerCode': c.onboard_customer_code,
                'onboardAssignmentId': str(c.onboard_assignment_id), 'onboardIdentityId': str(c.onboard_identity_id),
                'blockedCustomerId': str(c.blocked_customer_id), 'blockedCustomerCode': c.blocked_customer_code,
                'onboardEmail': c.onboard_invited_email})
        if hasattr(c, 'readonly_price'):
            seed.update({'readonlyPrice': c.readonly_price, 'historyRequestId': c.history_request_id, 'historyRequestNo': c.history_request_no})
        if hasattr(c, 'interaction_mode'):
            assert c.interaction_mode == 'keyboard'
            seed['interactionMode'] = c.interaction_mode
        private_input = json.dumps(seed)
        seed.clear()
        seed = None
        return consume_owned_process([node, str(script), origin, playwright, chrome, str(output)], private_input)
    finally:
        if seed is not None: seed.clear()
        seed = None
        private_input = ''


@pytest.mark.parametrize('timeout', [False, True])
def test_owned_failed_process_clears_credentials_before_assertion_caller(monkeypatch, timeout):
    private = 'synthetic-private-jwt synthetic-private-cookie synthetic-private-csrf'
    children = []
    actual_popen = subprocess.Popen
    def tracked(*args, **kwargs):
        child = actual_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', tracked)
    program = 'import sys,time; value=sys.stdin.read(); print(value,flush=True); print(value,file=sys.stderr,flush=True); ' + (
        'time.sleep(10)' if timeout else 'sys.exit(7)')
    summary = consume_owned_process([sys.executable, '-c', program], private, timeout=.5 if timeout else 5)
    assert children and all(getattr(child, '_input', None) is None for child in children)
    assert all(child.poll() is not None for child in children)
    assert all(secret not in json.dumps(summary) for secret in private.split())
    assert summary['raw_output_retained'] is False and summary['stdout_bytes'] > 0 and summary['stderr_bytes'] > 0
    assert summary['timed_out'] is timeout and summary['exit_code'] != 0


def test_runner_diagnostics_never_persist_input_or_headers():
    jwt, cookie, csrf = 'synthetic-jwt-private-abc', 'synthetic-cookie-private-def', 'synthetic-csrf-private-ghi'
    vectors = [f'Authorization: Bearer {jwt}\nCookie: portal={cookie}\nX-Portal-CSRF: {csrf}',
        json.dumps({'Authorization': jwt, 'Cookie': cookie, 'X-Portal-CSRF': csrf}),
        f'authorization\n{jwt}\ncookie\n{cookie}\nx-portal-csrf\n{csrf}',
        f'{jwt} {cookie} {csrf}', 'originalreason-private-marker']
    for raw in vectors:
        summary = safe_runner_summary(1, raw, raw)
        encoded = json.dumps(summary)
        assert all(secret not in encoded for secret in [jwt, cookie, csrf, raw])
        assert summary['raw_output_retained'] is False and summary['failure_category'] == 'process_failure'
    normal = safe_runner_summary(1, '', 'AssertionError at applicationTrade.browser.mjs:82:57')
    assert normal['failure_category'] == 'assertion' and normal['source_frames'] == [{'line': 82, 'column': 57}]
    onboarding = safe_runner_summary(1, jwt, f'AssertionError {csrf} at applicationOnboarding.browser.mjs:31:9 {cookie}')
    assert onboarding['source_frames'] == [{'line': 31, 'column': 9}]
    assert all(secret not in json.dumps(onboarding) for secret in (jwt, cookie, csrf))
    assert safe_runner_summary(0, 'arbitrary successful stdout', '')['failure_category'] == 'none'
    assert safe_runner_summary(-1, '', '', timed_out=True)['failure_category'] == 'timeout'


def test_current_customer_bundle_actual_application_trade_and_receipt_recovery(commerce, request):
    c = commerce
    runtime = [request.config.getoption('portal_browser_' + name) for name in ('node', 'module', 'chromium')]
    if not all(runtime): pytest.skip('Explicit owned Node, Playwright module and Chrome paths required')
    node, playwright, chrome = (str(Path(value).resolve(strict=True)) for value in runtime)
    script = ROOT / 'frontend-portal/tests/applicationTrade.browser.mjs'
    assert script.is_file(), 'The actual browser runner must be ready before execution'
    workspace = Path(request.config.getoption('portal_mysql_workspace')).resolve()
    output = workspace / ('browser-evidence-keyboard' if getattr(c, 'interaction_mode', None) == 'keyboard' else 'browser-evidence')
    output.mkdir()
    with live_application(c) as (origin, shell):
        # Actual broker guards cannot read arbitrary OTPs or mutate commerce.
        before = business_snapshot(c)
        denied, headers, _ = broker_call(origin, '/__owned/otp/' + str(uuid4()))
        assert denied == 403 and headers['cache-control'] == 'no-store'
        missing, headers, _ = broker_call(origin, '/__owned/otp/' + str(uuid4()), shell.broker_key)
        assert missing == 404 and headers['cache-control'] == 'no-store'
        invalid, headers, _ = broker_call(origin, '/__owned/control', shell.broker_key, {'fault': 'accept_ack', 'extra': True})
        assert invalid == 400 and headers['cache-control'] == 'no-store' and not shell.arm_accept
        for broker_path in ('/__owned/invitation/' + str(uuid4()), '/__owned/invitation/not-a-uuid'):
            denied, headers, _ = broker_call(origin, broker_path)
            assert denied == 403 and headers['cache-control'] == 'no-store'
            missing, headers, _ = broker_call(origin, broker_path, shell.broker_key)
            assert missing == 404 and headers['cache-control'] == 'no-store'
        assert business_snapshot(c) == before
        summary = run_browser(c, shell, node, script, origin, playwright, chrome, output)
        # No arbitrary Playwright output is saved: timeout call logs may contain
        # JWT/cookies/CSRF without a stable label or line format.
        (output / 'runner-summary.json').write_text(json.dumps(summary), encoding='utf-8')
        assert not summary['timed_out'], 'Owned browser timed out; its process tree was stopped'
        assert summary['exit_code'] == 0, 'Owned browser failed; inspect safe browser evidence'
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        assert report['status'] == 'pass' and report['apiInterceptions'] == 0
        if getattr(c, 'interaction_mode', None) == 'keyboard':
            interaction = report['interaction']
            assert interaction['mode'] == 'keyboard'
            assert interaction['reached'] >= 50 and interaction['inputs'] >= 20
            assert interaction['activated'] >= 25 and interaction['options'] >= 4 and interaction['checked'] == 2
            assert interaction['driverProgrammaticFocus'] is False and interaction['driverPointerFallback'] is False
            assert 320 in interaction['widths']
        assert report['portalPostAccept'] == 1 and report['receiptGets'] >= 1
        request_id = str(UUID(report['requestId']))
        accept_calls = sum(count for (method, path), count in shell.calls.items() if method == 'POST' and ACCEPT.fullmatch(path))
        assert accept_calls == 1 and shell.fault_count == 1 and not shell.arm_accept
        matching_receipts = [row for row in shell.receipt_observations if row.get('found') and row['command']['request_id'] == request_id]
        assert matching_receipts and all(row['receipt']['original_receipt'] == shell.accept_original for row in matching_receipts)
        assert shell.receipt_dml and shell.receipt_business_writes == []
        assert all(operation == 'UPDATE' and table == PortalSession.__tablename__ for operation, table in shell.receipt_dml)
        assert shell.otp_reads[c.buyer_id] >= 1 and shell.otp_reads[c.other_buyer_id] >= 1
        assert shell.invited_account_id is not None and shell.otp_reads[shell.invited_account_id] == 1
        assert len(shell.invitation_landing_snapshots) == 3
        assert all(row == shell.invitation_landing_snapshots[0] for row in shell.invitation_landing_snapshots)
        with Session(c.app.ctx.engine) as db:
            rejected_id = str(UUID(report['rejectedActivationChallengeId']))
            rejected = db.scalar(select(AuthChallenge).where(AuthChallenge.public_id == rejected_id))
            assert rejected is not None and rejected.purpose == 'activate' and rejected.account_id is None and rejected.invitation_id is None
            assert db.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_public_id == rejected_id, OutboxEvent.event_type == 'auth_code')) is None
            assert db.scalar(select(PortalSession.id).where(PortalSession.account_id == c.forwarded_id)) is None
            foreign_graph = tuple(tuple(db.execute(select(*model.__table__.columns).where(model.id == identifier)).one())
                for model, identifier in ((Account, c.forwarded_id), (Membership, c.forwarded_member_id)))
            assert foreign_graph == c.forwarded_graph
            invited = db.get(Account, shell.invited_account_id)
            invitation = db.get(Invitation, shell.invited_invitation_id)
            membership = db.get(Membership, invitation.membership_id)
            assert invited.email_normalized == c.invited_email and invited.verified_at is not None and invited.status == 'disabled'
            assert invitation.consumed_at is not None and invitation.revoked_at is None
            assert membership.account_id == invited.id and membership.access_id == c.app.ctx.access_id and membership.status == 'active'
            activation = db.scalars(select(AuthChallenge).where(AuthChallenge.account_id == invited.id, AuthChallenge.purpose == 'activate')).all()
            assert len(activation) == 1 and activation[0].invitation_id == invitation.id and activation[0].consumed_at is not None
            sessions = db.scalars(select(PortalSession).where(PortalSession.account_id == invited.id)).all()
            assert len(sessions) == 1 and sessions[0].revoked_at is not None
        assert len(shell.pdf_documents) >= 2
        texts = ['\n'.join(page.extract_text() for page in PdfReader(BytesIO(value)).pages) for value in shell.pdf_documents]
        assert all(value == texts[0] for value in texts), 'Published PI commercial text changed'
        assert all(value == shell.publication_snapshots[0] for value in shell.publication_snapshots), 'Published PI snapshot/hash/document version changed'
        download_texts = ['\n'.join(page.extract_text() for page in PdfReader(str(output / name)).pages)
            for name in ('confirmed.pdf', 'after-mapping.pdf')]
        assert download_texts == [texts[0], texts[0]], 'Actual downloaded historical PI changed'
        pages = [len(PdfReader(BytesIO(value)).pages) for value in shell.pdf_documents]
        assert all(value == pages[0] for value in pages)
        assert [len(PdfReader(str(output / name)).pages) for name in ('confirmed.pdf', 'after-mapping.pdf')] == [pages[0], pages[0]]
        assert all(value == shell.published_graphs[0] for value in shell.published_graphs), 'Published financial graph changed during reads/mapping'
        assert published_graph(c, request_id) == shell.published_graphs[0], 'Published financial graph changed after mapping/revocation'
        assert shell.original_mapping_snapshots
        assert all(row == shell.original_mapping_snapshots[0] for row in shell.original_mapping_snapshots)
        assert original_mapping(c) == shell.original_mapping_snapshots[0], 'Original mapping revision was rewritten'
        assert 'Buyer New Straight' not in texts[0] and 'BUYER-NEW-20' not in texts[0]
        assert all(value in texts[0] for value in ('Buyer Signature Straight', 'Buyer Natural Black', 'BUYER-ST-20', '128.00', 'Payment before shipment', '10 Example Street', 'London'))
        with Session(c.app.ctx.engine) as db:
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            assert order is not None and order.status == 'invoice_created' and order.account_id == c.buyer_id
            maps = db.scalars(select(MappingRevision).where(MappingRevision.access_id == c.app.ctx.access_id).order_by(MappingRevision.version)).all()
            assert [row.version for row in maps] == [1, 2]
            original_entries = maps[0].snapshot_json['entries']
            assert any(row['display_value'] == 'Buyer Signature Straight' and row.get('customer_sku') == 'BUYER-ST-20' for row in original_entries)
            assert any(row['display_value'] == 'Buyer Natural Black' for row in original_entries)
            invoices = db.scalars(select(Invoice).where(Invoice.source_order_id == request_id)).all()
            assert len(invoices) == 1 and invoices[0].id == order.invoice_id
            invoice = invoices[0]
            assert invoice.total_amount == 128 and invoice.sales_user_id == c.app.ctx.actor
            assert invoice.outbound_auto_requested == 0 and invoice.sync_status == 'not_synced' and invoice.xiaoman_order_id is None
            intents = db.scalars(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id)).all()
            # Portal PIs skip the creation-time receipt intent draft.
            assert intents == []
            conversions = db.scalars(select(Conversion).where(Conversion.request_id == order.id)).all()
            assert len(conversions) == 1 and conversions[0].invoice_id == invoice.id and conversions[0].status == 'created'
            publications = db.scalars(select(Publication).where(Publication.request_id == order.id)).all()
            assert len(publications) == 1 and publications[0].invoice_id == invoice.id and publications[0].status == 'published'
            receipts = db.scalars(select(CommandReceipt).where(CommandReceipt.object_public_id == request_id)).all()
            assert sum(row.action == 'accept' for row in receipts) == 1
            assert sum(row.action == 'approve' for row in receipts) == 1
            accepted = db.get(Revision, order.accepted_revision_id)
            assert accepted.customer_accepted_by == c.buyer_id
            line = db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
            assert str(line.product_id) == c.product_id and line.model == c.standard['model'] and line.color == c.standard['color']
        # Hash only the original response reference; never print raw customer inputs.
        (output / 'server-evidence.json').write_text(json.dumps({'scope': 'owned loopback ASGI shell',
            'fault': 'committed accept 200 replaced once by controlled 503', 'acceptPostCount': accept_calls,
            'faultCount': shell.fault_count, 'receiptGetCount': len(shell.receipt_observations),
            'originalReceiptDigest': hashlib.sha256(json.dumps(shell.accept_original, sort_keys=True).encode()).hexdigest(),
            'pdfCount': len(shell.pdf_documents), 'receiptIdleUpdates': len(shell.receipt_dml),
            'commercialReceiptReadWrites': len(shell.receipt_business_writes)}), encoding='utf-8')
    assert c.calls == [] and c.forbidden_writes == []

def test_actual_application_keyboard_trade_and_receipt_recovery(commerce, request):
    commerce.interaction_mode = 'keyboard'
    test_current_customer_bundle_actual_application_trade_and_receipt_recovery(commerce, request)
