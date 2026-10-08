"""T19: real SQL lookup boundaries and stored input through both built UIs."""
import asyncio
from copy import deepcopy
from io import BytesIO
import json
from importlib.util import module_from_spec, spec_from_file_location
from types import SimpleNamespace
from pathlib import Path
import re
import subprocess
import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from app.auth import router as employee_router
from app.auth.models import ArkUser
from app.auth import utils
from app.core.database import get_db
from app.customer.models import CustomerAccount
from app.invoice.models import Invoice, InvoiceItem
from app.portal import auth_service as auth, router, admin_router, mapping_service, pi_pdf
from app.portal.models import CatalogItem, CustomerAccess, MappingRevision, OrderRequest, Revision, RequestLine, Site, Quote
from app.portal.schemas import MappingInput
from test_mysql_browser import employee_server
from test_mysql_services import submit, assert_one_pi
from test_mysql_decision_recovery import make_app, snapshot


def root_login(ctx, credentials):
    with Session(ctx.engine) as db:
        root = db.get(ArkUser, ctx.admin)
        root.password_hash = utils.hash_password(credentials['password'])
        username = root.username; db.commit()
    return {'username': username, 'password': credentials['password']}


def test_sql_payloads_remain_parameters_and_do_not_expand_scope(trade, monkeypatch):
    ctx = trade
    with Session(ctx.engine) as db:
        request_id = submit(ctx, db)['request_id']; db.commit()
        source = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
        values = {c.name: deepcopy(getattr(source, c.name)) for c in CatalogItem.__table__.columns
            if c.name not in {'id','public_id','created_at','updated_at'}}
        values.update(product_id='hidden-sql-source', sku_id='hidden-sql-source',
            display_name='Hidden SQL Sentinel', color_name='Secret')
        hidden = CatalogItem(**values); db.add(hidden); db.commit(); hidden_id = hidden.public_id
    app, settings, headers, owner = make_app(ctx, monkeypatch)
    credentials = root_login(ctx, owner)
    payloads = ["' OR 1=1 --", "%\' OR '1'='1", "'; DROP TABLE ark_order_portal_orders; --", '%', '_', chr(92)]
    captured = []
    def observe(connection, cursor, statement, parameters, context, many):
        if any(value in statement for value in payloads[:3]):
            raise AssertionError('Untrusted SQL text entered a statement')
        if parameters: captured.append((statement, parameters))
    def state():
        with Session(ctx.engine) as db:
            return snapshot(ctx), tuple(tuple(db.execute(select(*m.__table__.columns).order_by(m.id)).all())
                for m in (CatalogItem, CustomerAccess, MappingRevision, CustomerAccount, Quote))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1',51000)),
            base_url=settings.PORTAL_ORIGIN) as client:
            login = await client.post('/api/auth/login', json=credentials); assert login.status_code == 200
            employee = {'Authorization':'Bearer '+login.json()['access_token']}
            own_login = await client.post('/api/auth/login', json=owner); assert own_login.status_code == 200
            own_headers = {'Authorization':'Bearer '+own_login.json()['access_token']}
            lookups = [('/api/portal/v1/catalog', headers, 'Standard'),
                ('/api/portal/admin/v1/catalog', employee, 'Standard'),
                ('/api/portal/admin/v1/customers', employee, 'Buyer'),
                ('/api/portal/admin/v1/orders/'+request_id+'/proposal-catalog', own_headers, 'Standard')]
            for path, actor, keyword in lookups:
                positive = await client.get(path, params={'keyword':keyword}, headers=actor)
                assert positive.status_code == 200, positive.text[:300]
                assert positive.json()['data']['total'] >= 1
            before = state()
            event.listen(ctx.engine, 'before_cursor_execute', observe)
            try:
                for path, actor, _ in lookups:
                    for payload in payloads:
                        found = await client.get(path, params={'keyword':payload}, headers=actor)
                        assert found.status_code == 200, found.text[:300]
                        data = found.json()['data']; assert data['items'] == [] and data['total'] == 0
                for payload in payloads[:3]:
                    invalid = await client.get('/api/portal/v1/catalog/'+payload, headers=headers)
                    assert invalid.status_code == 422 and invalid.json()['data']['error_code'] == 'INVALID_INPUT'
                    assert payload not in invalid.text
                    assert invalid.headers['X-Content-Type-Options'] == 'nosniff'
                hidden_result = await client.get('/api/portal/v1/catalog/'+hidden_id, headers=headers)
                assert hidden_result.status_code == 404
                assert state() == before
                # Mapping labels reject markup before any business writes, including
                # direct publication that bypasses the browser preview.
                with Session(ctx.engine) as db:
                    access = db.get(CustomerAccess,ctx.access_id)
                    map_path = '/api/portal/admin/v1/customers/'+access.public_id+'/mapping'
                    row_version,base_version = access.row_version,access.mapping_version
                for field,payload in (('display_value','<img src=/xss-probe onerror="window.__portalXss++">'),
                    ('display_value','<svg onload="window.__portalXss++"></svg>'),
                    ('customer_sku','<script>window.__portalXss++</script>'),
                    ('display_value','＜img src=/xss-probe onerror=window.__portalXss++＞'),
                    ('customer_sku','＜script＞window.__portalXss++＜/script＞')):
                    entry = {'kind':'sku','source_key':ctx.item_id,'item_id':ctx.item_id,'display_value':'Plain alias'}
                    entry[field] = payload
                    body = {'base_version':base_version,'entries':[entry]}
                    for action in ('preview','publish'):
                        rejected = await client.post(map_path+'/'+action,json=body,
                            headers={**employee,'If-Match':chr(34)+str(row_version)+chr(34)})
                        assert rejected.status_code == 422 and rejected.json()['data']['error_code'] == 'INVALID_INPUT'
                        assert payload not in rejected.text
                        assert state() == before
            finally: event.remove(ctx.engine, 'before_cursor_execute', observe)
            # P1 CSV export is outside P0; current route inventory has no export endpoint.
            assert not any('csv' in route.path or 'export' in route.path for route in [*router.router.routes,*admin_router.router.routes])
            assert captured and any(any(value == payloads[0] or payloads[0] in str(value) for value in
                (params.values() if isinstance(params, dict) else params)) for _, params in captured)
    asyncio.run(run())


def test_stored_input_in_real_customer_and_employee_browsers(request, monkeypatch):
    paths = [request.config.getoption('portal_browser_'+name) for name in ('node','module','chromium')]
    if not all(paths): pytest.skip('Explicit browser runtime options required')
    ctx = request.getfixturevalue('trade')
    repo = Path(__file__).resolve().parents[3]
    assert all((repo / folder / 'dist/index.html').is_file() for folder in ('frontend','frontend-portal'))
    _, settings, _, owner = make_app(ctx, monkeypatch)
    credentials = root_login(ctx, owner)
    settings.PDF_CJK_FONT_PATH = 'C:/Windows/Fonts/arial.ttf'
    monkeypatch.setattr(pi_pdf, 'get_settings', lambda: settings)
    attack_model = '<img src=/xss-probe onerror="window.__portalXss++">'
    model = 'Quote " & alias'
    attack_color = '<svg onload="window.__portalXss++"></svg>'
    color = 'Shade & "quote"'
    attack_sku = '<script>window.__portalXss++</script>'
    sku = 'javascript:window.__portalXss++'
    delivery = {'contact_name':attack_color, 'phone':'+44 10000000', 'country_code':'GB',
        'address_line1':'"><img src=/xss-probe onerror=window.__portalXss++>',
        'address_line2':'<a href="javascript:window.__portalXss++">tap</a>',
        'city':"' OR 1=1 --"}
    formula = '=HYPERLINK("https://example.test","SKU")'
    remark = attack_sku+" '; DROP TABLE ark_order_portal_orders; --"
    reason = '<img src=/xss-probe onerror="window.__portalXss++">'
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        company = db.get(CustomerAccount, access.customer_id)
        company.display_name = company.canonical_company_name = attack_color
        access_public_id, site_id = access.public_id, access.site_id
        item = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
        entries = [{'kind':'sku','source_key':ctx.item_id,'item_id':ctx.item_id,
            'display_value':'Baseline mapping','customer_sku':'Baseline SKU'},
            {'kind':'color','source_key':item.standard_json['color_key'],'display_value':'Baseline color'}]
        mapping_service.publish(db, ctx.admin, access_public_id, access.row_version,
            MappingInput(base_version=0, entries=entries)); db.commit()
    seed = {**credentials, 'session':ctx.token, 'item_id':ctx.item_id, 'access_id':access_public_id,
        'model':model,'color':color,'sku':sku,'delivery':delivery,'formula':formula,'remark':remark,'reason':reason,
        'attack_model':attack_model,'attack_color':attack_color,'attack_sku':attack_sku,'owner':owner['username']}
    def frontend_app(folder):
        app = FastAPI()
        app.include_router(employee_router.router, prefix='/api/auth')
        app.include_router(router.router, prefix='/api/portal/v1')
        app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
        def database():
            with Session(ctx.engine) as db: yield db
        app.dependency_overrides[get_db] = database
        @app.api_route('/api/{path:path}', methods=['GET','POST','PATCH','PUT','DELETE'])
        def unknown(path): return JSONResponse({'detail':'Not found'},status_code=404)
        dist = repo / folder / 'dist'
        app.mount('/assets', StaticFiles(directory=dist/'assets'),name='assets')
        @app.get('/{path:path}')
        def frontend(path):
            target = (dist/path).resolve()
            if not target.is_relative_to(dist.resolve()): return JSONResponse({},status_code=404)
            return FileResponse(target if target.is_file() else dist/'index.html')
        return app
    output = request.getfixturevalue('tmp_path')
    # Reuse the loopback HTTPS ingress harness: it strips spoofed headers,
    # supplies X-Real-IP, and preserves the backend TCP peer (127.0.0.2).
    spec = spec_from_file_location('portal_input_https_harness',repo/'backend/tests/portal/live_browser_server.py')
    harness = module_from_spec(spec); spec.loader.exec_module(harness)
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.2']
    with employee_server(frontend_app('frontend')) as employee_origin:
        with Session(ctx.engine) as db:
            proxy_ctx = SimpleNamespace(settings=settings,site=db.get(Site,site_id),db=db)
            with harness.running_portal(frontend_app('frontend-portal'),proxy_ctx,repo/'frontend-portal/dist',output) as origins:
                customer_origin,_ = origins
                result = subprocess.run([paths[0],str(repo/'frontend/tests/portalLiveInputSafety.browser.mjs'),
                    employee_origin,customer_origin,paths[1],paths[2],str(output)], input=json.dumps(seed),
                    text=True,encoding='utf-8',capture_output=True,timeout=150)
                assert result.returncode == 0, result.stdout+result.stderr
                report = json.loads(result.stdout.strip().splitlines()[-1])
                assert report['status'] == 'pass' and report['apiInterceptions'] == 0
                assert report['checkpoints'] == 12 and report['positiveControlExecutions'] == 2 and report['injectedRequests'] == 0
    request_id = report['request_id']; assert_one_pi(ctx,request_id)
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        revision = db.get(Revision,order.accepted_revision_id)
        line = db.scalar(select(RequestLine).where(RequestLine.revision_id == revision.id))
        assert order.customer_po == formula and revision.delivery_json == {**delivery,'region':'','postal_code':''}
        assert revision.remark == remark
        assert (line.customer_display_json['model_name'],line.customer_display_json['color_name'],line.customer_display_json['customer_sku']) == (model,color,sku)
        invoice = db.get(Invoice,order.invoice_id)
        assert invoice.customer_name == attack_color and invoice.source_order_name == order.public_no
        item = db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
        assert item.product_kind == 'hair' and item.quantity == 3 and item.price_per_piece == 27
    # Render is real ReportLab; payloads remain visible text, never PDF link/action markup.
    pdf = PdfReader(BytesIO((output/'input-safety.pdf').read_bytes()))
    text = re.sub(r'\s+','', ''.join(page.extract_text() for page in pdf.pages))
    for payload in (model,color,sku,attack_color,formula,remark,delivery['address_line1'],delivery['address_line2']):
        assert re.sub(r'\s+','',payload) in text
    root = pdf.trailer['/Root']
    assert '/OpenAction' not in root and '/AA' not in root
    assert '/JavaScript' not in root.get('/Names',{})
    assert all(not page.get('/Annots') and '/AA' not in page for page in pdf.pages)
    print(json.dumps({key:value for key,value in report.items() if key != 'request_id'}))