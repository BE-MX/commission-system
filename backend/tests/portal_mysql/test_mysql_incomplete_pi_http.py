"""Real employee edits of incomplete PI drafts cannot publish customer documents.

HTTP uses actual employee login/JWT and customer cookie/CSRF against owned MySQL.
Upstream anchor tables and data are thin fixtures; PDF bytes are a render probe.
"""
import asyncio
from copy import deepcopy
from decimal import Decimal
import httpx
import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session
from app.invoice import service as invoices, router as invoice_router
from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask
from app.invoice.schemas import InvoiceUpdate, InvoiceItemPayload
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import approval_service, pi_service, pi_pdf
from app.portal.models import OrderRequest, Revision, RequestLine, Publication, Conversion, PiAmendment
from test_mysql_services import accepted_request, count
from test_mysql_decision_recovery import make_app, snapshot, proposal_body


def invoice_body(invoice):
    values = {key:getattr(invoice,key) for key in InvoiceUpdate.model_fields if hasattr(invoice,key) and key != 'items'}
    values['items'] = [{key:getattr(item,key) for key in InvoiceItemPayload.model_fields if hasattr(item,key)} for item in invoice.items]
    for item in values['items']: item['semifinished_plan'] = item.get('semifinished_plan') or []
    return InvoiceUpdate.model_validate(values).model_dump(mode='json')


def current(ctx, request_id):
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = db.get(Invoice,order.invoice_id)
        return order.row_version,invoice.portal_document_version


def rejected(response, code, *, status=409):
    assert response.status_code == status, (response.status_code,response.text[:500])
    assert response.json()['data']['error_code'] == code
    expected_cache = 'private, no-store' if response.request.url.path.startswith('/api/portal/admin/') else 'no-store'
    assert response.headers['cache-control'] == expected_cache


@pytest.mark.parametrize('missing', ['contact_name','length','items'])
def test_saved_incomplete_pi_requires_repair_and_new_customer_confirmation(trade,monkeypatch,missing):
    ctx = trade
    metadata = MetaData()
    for model in (Receipt,InvoiceAllocation,ShippingOperationEvent,OkkiOutboundTask):
        Table(model.__tablename__,metadata,*(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=c.nullable,default=c.default,server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine,checkfirst=True)
    request_id,approved = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,request_id,3,approved); db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = invoices.get_invoice(db,order.invoice_id)
        invoice_id = invoice.id
        original = invoice_body(invoice)
        original_revision = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == order.accepted_revision_id)).one())
        original_lines = tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == order.accepted_revision_id)).all())
        _,_,published = pi_service.capture(db,ctx.token,request_id)
        assert published['total_amount'] == '128.00'; db.rollback()
    app,settings,customer_headers,credentials = make_app(ctx,monkeypatch)
    app.include_router(invoice_router.router,prefix='/api/invoice')
    render_calls = []
    def render_probe(value):
        render_calls.append(deepcopy(value)); return b'%PDF-test-render-probe'
    monkeypatch.setattr(pi_pdf,'render',render_probe)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',51000)),
                base_url=settings.PORTAL_ORIGIN) as client:
            logged_in = await client.post('/api/auth/login',json=credentials)
            assert logged_in.status_code == 200
            employee_headers = {'Authorization':'Bearer '+logged_in.json()['access_token']}
            employee_path = '/api/portal/admin/v1/orders/'+request_id
            customer_path = '/api/portal/v1/orders/'+request_id
            update_path = '/api/invoice/invoices/'+str(invoice_id)
            if missing == 'contact_name':
                null_fee = deepcopy(original); null_fee['shipping_fee'] = None
                baseline = snapshot(ctx)
                refused = await client.put(update_path,headers=employee_headers,json=null_fee)
                assert refused.status_code == 422
                assert any(issue['loc'] == ['body','shipping_fee'] for issue in refused.json()['detail'])
                assert snapshot(ctx) == baseline
            # Create and actually accept A before another edit, so publishing A
            # with the current version cannot pass merely through old If-Match.
            revised = deepcopy(original); revised['remark'] = 'Complete reviewed PI A'
            saved = await client.put(update_path,headers=employee_headers,json=revised)
            assert saved.status_code == 200, saved.text[:500]
            row,document = current(ctx,request_id)
            proposed_a = await client.post(employee_path+'/pi-proposals',
                headers={**employee_headers,'If-Match':chr(34)+str(row)+chr(34)},
                json={'invoice_document_version':document,'reason':'Confirm complete PI A','valid_for_hours':24})
            assert proposed_a.status_code == 200, proposed_a.text[:500]
            a = proposed_a.json()['data']; a_receipt = a['original_receipt']
            accepted_a = await client.post(customer_path+'/proposals/'+a_receipt['revision_id']+'/accept',
                headers={**customer_headers,'If-Match':chr(34)+str(a['row_version'])+chr(34)},
                json={'proposal_hash':a_receipt['content_hash']})
            assert accepted_a.status_code == 200, accepted_a.text[:500]
            incomplete = deepcopy(revised)
            if missing == 'items': incomplete['items'] = []
            elif missing == 'length': incomplete['items'][0]['length'] = None
            else: incomplete[missing] = ''
            saved = await client.put(update_path,headers=employee_headers,json=incomplete)
            assert saved.status_code == 200, saved.text[:500]
            row,document = current(ctx,request_id)
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                invoice = invoices.get_invoice(db,invoice_id)
                amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id))
                assert invoice.portal_document_version == document and document > a_receipt['invoice_document_version']
                assert amendment.status == 'withdrawn' and amendment.accepted_revision_id is None
                assert count(db,Publication,(Publication.invoice_id == invoice_id)&(Publication.status == 'published')) == 0
                if missing == 'items': assert invoice.items == [] and any(issue['field'] == 'items' for issue in invoices.validate_invoice(invoice))
                elif missing == 'length':
                    assert invoice.items[0].length is None
                    assert any(issue['field'].endswith('.length') for issue in invoices.validate_invoice(invoice))
                else: assert invoice.contact_name == ''
            baseline = snapshot(ctx)
            blocked = await client.post(employee_path+'/pi-proposals',
                headers={**employee_headers,'If-Match':chr(34)+str(row)+chr(34)},
                json={'invoice_document_version':document,'reason':'Attempt incomplete PI proposal','valid_for_hours':24})
            rejected(blocked,'INVOICE_VALIDATION_FAILED')
            assert snapshot(ctx) == baseline
            # A was accepted, but its confirmation never authorizes the edited document.
            blocked = await client.post(employee_path+'/publish-pi',
                headers={**employee_headers,'If-Match':chr(34)+str(row)+chr(34)},
                json={'invoice_document_version':document,'accepted_revision_id':a_receipt['revision_id']})
            rejected(blocked,'CUSTOMER_ACCEPTANCE_REQUIRED')
            download = await client.get(customer_path+'/pi',headers=customer_headers)
            rejected(download,'PI_REVISION_PENDING')
            assert render_calls == [] and snapshot(ctx) == baseline
            with Session(ctx.engine) as db:
                invoice = db.get(Invoice,invoice_id)
                assert count(db,Invoice,Invoice.source_order_id == request_id) == 1
            # Explicit repair permits a new proposal; publication still needs B's
            # own customer acceptance. No second invoice or ReceiptIntent is created.
            repaired = deepcopy(revised); repaired['remark'] = 'Repaired complete PI B'
            saved = await client.put(update_path,headers=employee_headers,json=repaired)
            assert saved.status_code == 200, saved.text[:500]
            row,document = current(ctx,request_id)
            proposed_b = await client.post(employee_path+'/pi-proposals',
                headers={**employee_headers,'If-Match':chr(34)+str(row)+chr(34)},
                json={'invoice_document_version':document,'reason':'Confirm repaired PI B','valid_for_hours':24})
            assert proposed_b.status_code == 200, proposed_b.text[:500]
            b = proposed_b.json()['data']; b_receipt = b['original_receipt']
            baseline = snapshot(ctx)
            blocked = await client.post(employee_path+'/publish-pi',
                headers={**employee_headers,'If-Match':chr(34)+str(b['row_version'])+chr(34)},
                json={'invoice_document_version':document,'accepted_revision_id':b_receipt['revision_id']})
            rejected(blocked,'CUSTOMER_ACCEPTANCE_REQUIRED')
            assert snapshot(ctx) == baseline
            accepted_b = await client.post(customer_path+'/proposals/'+b_receipt['revision_id']+'/accept',
                headers={**customer_headers,'If-Match':chr(34)+str(b['row_version'])+chr(34)},
                json={'proposal_hash':b_receipt['content_hash']})
            assert accepted_b.status_code == 200, accepted_b.text[:500]
            published_b = await client.post(employee_path+'/publish-pi',
                headers={**employee_headers,'If-Match':chr(34)+str(accepted_b.json()['data']['row_version'])+chr(34)},
                json={'invoice_document_version':document,'accepted_revision_id':b_receipt['revision_id']})
            assert published_b.status_code == 200, published_b.text[:500]
            download = await client.get(customer_path+'/pi',headers=customer_headers)
            assert download.status_code == 200 and download.content == b'%PDF-test-render-probe'
            assert len(render_calls) == 1 and render_calls[0]['remark'] == 'Repaired complete PI B'
            assert render_calls[0]['total_amount'] == '128.00'
            assert render_calls[0]['fees']['shipping_amount'] == '45.00'
    asyncio.run(run())
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.invoice_id == invoice_id and order.status == 'invoice_created'
        assert count(db,Invoice,Invoice.source_order_id == request_id) == 1
        assert count(db,Conversion,Conversion.request_id == order.id) == 1
        assert count(db,ReceiptIntent,ReceiptIntent.invoice_id == invoice_id) == 1
        assert count(db,Publication,Publication.invoice_id == invoice_id) == 2
        assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == order.accepted_revision_id)).one()) == original_revision
        assert tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == order.accepted_revision_id)).all()) == original_lines

@pytest.mark.parametrize('fee_input',['null','omitted'])
def test_unknown_fees_are_not_automatically_confirmed_as_zero(trade,monkeypatch,fee_input):
    ctx = trade
    app,settings,customer_headers,credentials = make_app(ctx,monkeypatch)
    render_calls = []
    def render_probe(value):
        render_calls.append(deepcopy(value)); return b'%PDF-explicit-zero-probe'
    monkeypatch.setattr(pi_pdf,'render',render_probe)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',51000)),
                base_url=settings.PORTAL_ORIGIN) as client:
            login = await client.post('/api/auth/login',json=credentials)
            assert login.status_code == 200
            employee_headers = {'Authorization':'Bearer '+login.json()['access_token']}
            submitted = await client.post('/api/portal/v1/orders',
                headers={**customer_headers,'Idempotency-Key':str(ctx.key)},json=ctx.body.model_dump(mode='json'))
            assert submitted.status_code == 201, submitted.text[:500]
            request_id = submitted.json()['data']['request_id']
            employee_path = '/api/portal/admin/v1/orders/'+request_id
            customer_path = '/api/portal/v1/orders/'+request_id
            detail = await client.get(customer_path,headers=customer_headers)
            assert detail.status_code == 200
            assert detail.json()['data']['total_amount'] is None and detail.json()['data']['fees']['status'] == 'pending'
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                initial_id = order.active_revision_id
                initial = db.get(Revision,initial_id)
                assert initial.shipping_amount is None and initial.total_amount is None
                assert count(db,Invoice,Invoice.source_order_id == request_id) == 0
                assert count(db,Publication,Publication.request_id == order.id) == 0
            incomplete = proposal_body(ctx).model_dump(mode='json')
            if fee_input == 'null': incomplete['fees']['shipping_amount'] = None
            else: del incomplete['fees']['shipping_amount']
            baseline = snapshot(ctx)
            refused = await client.post(employee_path+'/proposals',
                headers={**employee_headers,'If-Match':'"1"'},json=incomplete)
            rejected(refused,'INVALID_INPUT',status=422)
            refused_download = await client.get(customer_path+'/pi',headers=customer_headers)
            rejected(refused_download,'PI_REVISION_PENDING')
            assert snapshot(ctx) == baseline and render_calls == []
            explicit = proposal_body(ctx).model_dump(mode='json')
            explicit['fees'] = {'shipping_amount':'0.00','packaging_amount':'0.00','surcharge_amount':'0.00'}
            proposed = await client.post(employee_path+'/proposals',
                headers={**employee_headers,'If-Match':'"1"'},json=explicit)
            assert proposed.status_code == 200, proposed.text[:500]
            proposal = proposed.json()['data']; receipt = proposal['original_receipt']
            # A valid explicit-zero proposal does not become a PI before acceptance.
            baseline = snapshot(ctx)
            refused = await client.get(customer_path+'/pi',headers=customer_headers)
            rejected(refused,'PI_REVISION_PENDING'); assert snapshot(ctx) == baseline
            accepted = await client.post(customer_path+'/proposals/'+receipt['revision_id']+'/accept',
                headers={**customer_headers,'If-Match':chr(34)+str(proposal['row_version'])+chr(34)},
                json={'proposal_hash':receipt['content_hash']})
            assert accepted.status_code == 200, accepted.text[:500]
            approved = await client.post(employee_path+'/approve',
                headers={**employee_headers,'If-Match':chr(34)+str(accepted.json()['data']['row_version'])+chr(34)},
                json={'accepted_revision_id':receipt['revision_id']})
            assert approved.status_code == 200, approved.text[:500]
            downloaded = await client.get(customer_path+'/pi',headers=customer_headers)
            assert downloaded.status_code == 200 and downloaded.content == b'%PDF-explicit-zero-probe'
            assert len(render_calls) == 1 and render_calls[0]['total_amount'] == '81.00'
            assert render_calls[0]['fees']['shipping_amount'] == '0.00'
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                invoice = db.get(Invoice,order.invoice_id)
                initial = db.get(Revision,initial_id)
                assert invoice.shipping_fee == Decimal('0.00') and invoice.total_amount == Decimal('81.00')
                assert initial.fees_status == 'pending' and initial.shipping_amount is None and initial.total_amount is None
                assert count(db,Invoice,Invoice.source_order_id == request_id) == 1
                assert count(db,Publication,Publication.request_id == order.id) == 1
    asyncio.run(run())