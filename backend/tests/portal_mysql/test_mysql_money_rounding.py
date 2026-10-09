"""Four-decimal price and negative discount survive real PI math and MySQL."""
from decimal import Decimal
import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session
from app.invoice import service as invoices
from app.invoice.models import Invoice, InvoiceItem, CustomerPriceRule, OkkiOutboundTask
from app.invoice.schemas import InvoiceUpdate, InvoiceItemPayload
from app.receipt.models import Receipt
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import (quote_service, approval_service, pi_service, pi_amendment_service as amendments,
    pi_revision_source, auth_service, order_queries)
from app.portal.domain import line_amount, total_amount
from app.portal.errors import PortalError
from app.portal.models import CustomerAccess, OrderRequest, Revision, RequestLine, Publication, Conversion
from app.portal.schemas import SubmitInput, PiProposalInput, AcceptInput, PublishPiInput
from test_mysql_services import accepted_request, count


def test_fractional_price_discount_reconfirmation_and_mysql_round_trip(trade, monkeypatch):
    ctx = trade
    monkeypatch.setattr(pi_revision_source, 'get_settings', auth_service.get_settings)
    metadata = MetaData()
    for model in (Receipt, InvoiceAllocation, ShippingOperationEvent, OkkiOutboundTask):
        Table(model.__tablename__, metadata, *(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=c.nullable,default=c.default,server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        rule = db.scalar(select(CustomerPriceRule).where(CustomerPriceRule.customer_id == access.okki_company_id))
        rule.adjust_type = 'fixed'; rule.adjust_value = Decimal('5.2750'); db.commit()
        quote = quote_service.create(db, ctx.token, ctx.csrf, ctx.quote_body); db.commit()
        assert quote['items'][0]['unit_price'] == '35.2750'
        assert quote['items'][0]['line_amount'] == quote['product_amount'] == '105.83'
        ctx.body = SubmitInput(quote_id=quote['quote_id'], quote_content_hash=quote['content_hash'],
            customer_po=ctx.quote_body.customer_po, remark='')
    request_id, accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,request_id,3,accepted); db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = invoices.get_invoice(db,order.invoice_id)
        invoice_id = invoice.id
        assert invoice.items[0].price_per_piece == Decimal('35.2750')
        assert invoice.items[0].total_price == invoice.product_amount == Decimal('105.83')
        assert invoice.total_amount == Decimal('152.83')
        old_revision = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == order.accepted_revision_id)).one())
        old_lines = tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == order.accepted_revision_id)).all())
        values = {key:getattr(invoice,key) for key in InvoiceUpdate.model_fields if hasattr(invoice,key) and key != 'items'}
        values['items'] = [{key:getattr(item,key) for key in InvoiceItemPayload.model_fields if hasattr(item,key)} for item in invoice.items]
        for item in values['items']:
            item['semifinished_plan'] = item.get('semifinished_plan') or []
            item['discount_amount'] = '-5.00'
        values.update(shipping_fee='45.00', internal_accessory='0.00', surcharge_amount='0.00')
        invoices.update_invoice(db,invoice,InvoiceUpdate.model_validate(values),user_id=ctx.actor); db.commit()
    # Independent Session verifies storage precision, not only in-memory calculations.
    with Session(ctx.engine) as db:
        invoice = invoices.get_invoice(db,invoice_id)
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        item = invoice.items[0]
        assert item.price_per_piece == Decimal('35.2750') and item.discount_amount == Decimal('-5.00')
        assert item.total_price == invoice.product_amount == line_amount(3,'35.2750','-5.00') == Decimal('100.83')
        assert invoice.total_amount == total_amount(['100.83'],'45.00','0.00','0.00')[1] == Decimal('145.83')
        with pytest.raises(PortalError) as caught: pi_service.capture(db,ctx.token,request_id)
        assert caught.value.code == 'PI_REVISION_PENDING'
        db.rollback()
        proposed = amendments.create(db,ctx.actor,request_id,order.row_version,
            PiProposalInput(invoice_document_version=invoice.portal_document_version,reason='Confirm agreed line discount'))
        db.commit()
        revision = proposed['original_receipt']
        amendments.decide(db,ctx.token,ctx.csrf,request_id,revision['revision_id'],proposed['row_version'],
            AcceptInput(proposal_hash=revision['content_hash']),accept=True); db.commit()
        db.refresh(order)
        amendments.publish(db,ctx.actor,request_id,order.row_version,PublishPiInput(
            accepted_revision_id=revision['revision_id'],invoice_document_version=invoice.portal_document_version)); db.commit()
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.invoice_id == invoice_id and order.status == 'invoice_created'
        assert count(db,Invoice,Invoice.source_order_id == request_id) == 1
        assert count(db,Conversion,Conversion.request_id == order.id) == 1
        assert count(db,Publication,Publication.request_id == order.id) == 2
        _, _, published = pi_service.capture(db,ctx.token,request_id)
        assert published['total_amount'] == '145.83' and published['product_amount'] == '100.83'
        detail = order_queries.customer_detail(db,ctx.token,request_id)
        assert detail['items'][0]['unit_price'] == '35.2750' and detail['items'][0]['discount_amount'] == '-5.00'
        assert detail['items'][0]['line_amount'] == '100.83' and detail['total_amount'] == '145.83'
        assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == order.accepted_revision_id)).one()) == old_revision
        assert tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == order.accepted_revision_id)).all()) == old_lines