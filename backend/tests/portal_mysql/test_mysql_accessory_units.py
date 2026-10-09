"""Exact accessory identities and explicit stock units survive quote through PI."""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import Column, BigInteger, Integer, DateTime, Numeric, MetaData, Table, select, text
from sqlalchemy.orm import Session
from app.core.time import beijing_now
from app.invoice.models import Invoice, InvoiceItem, StdPrice
from app.portal import (auth_service as auth, catalog_service, inventory_source, sku_source,
    quote_service, approval_service, pi_service)
from app.portal.errors import PortalError
from app.portal.models import CatalogItem, CatalogGrant, OrderRequest, RequestLine
from app.portal.schemas import QuoteInput, SubmitInput
from test_mysql_quote_constraints import client_app, snapshot
from test_mysql_services import accepted_request, count


@pytest.mark.parametrize('sale_unit,stock_unit,factor,stock,buffer', [
    ('piece','piece','1','7','1'),
    ('set','piece','3','20','2'),
    ('pack','g','7.5','47','2'),
])
def test_accessory_units_exact_identity_and_complete_pi(trade, monkeypatch,
        sale_unit, stock_unit, factor, stock, buffer):
    ctx = trade
    metadata = MetaData()
    inventory = Table('okki_inventory',metadata,
        Column('id',BigInteger,primary_key=True,autoincrement=True),
        Column('product_id',BigInteger),Column('sku_id',BigInteger),
        Column('enable_count',Numeric(20,6)),Column('disable_flag',Integer),Column('synced_at',DateTime))
    # DATETIME(0) rounds subsecond values; seed a past/current whole second.
    metadata.create_all(ctx.engine,checkfirst=True)
    settings = auth.get_settings()
    settings.PORTAL_INVENTORY_OBSERVED_COLUMN = 'synced_at'
    settings.PORTAL_INVENTORY_SOURCE_TIMEZONE = 'Asia/Shanghai'
    monkeypatch.setattr(inventory_source,'get_settings',lambda:settings)
    # Replace the base trade's synthetic observation adapter with actual mirror SQL.
    monkeypatch.setattr(catalog_service,'load_observations',inventory_source.load)
    with Session(ctx.engine) as db:
        original = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
        product_id = int(original.product_id)*1000+100000; sku_id = product_id+500
        # Identical human attributes, different exact identities and prices.
        for product,sku,price in ((product_id,sku_id,'12.5'),(product_id+1,sku_id+1,'99')):
            db.execute(text("INSERT INTO okki_products VALUES (:id,'Tape / replacement','TAPE','Clear',NULL,NULL,0)"),{'id':product})
            db.execute(text('INSERT INTO okki_product_skus VALUES (:product,:sku,0)'),{'product':product,'sku':sku})
            db.add(StdPrice(product_kind='accessory',product_id=product,sku_id=sku,
                accessory_name='Tape / replacement',accessory_model='TAPE',accessory_color='Clear',
                price=Decimal(price),currency='USD'))
        source = sku_source.load_snapshot(db,namespace='okki:test',product_id=str(product_id),
            sku_id=str(sku_id),product_kind='accessory')
        assert source['standard_json']['length'] == source['standard_json']['weight'] == ''
        item = CatalogItem(site_id=original.site_id,**source,display_name='Replacement tape',
            color_name='Clear',status='published',inventory_unit=stock_unit,sale_unit=sale_unit,
            conversion_factor=Decimal(factor),safety_buffer=Decimal(buffer))
        db.add(item); db.flush()
        db.add(CatalogGrant(access_id=ctx.access_id,catalog_item_id=item.id))
        db.execute(inventory.insert().values(product_id=product_id,sku_id=sku_id,
            enable_count=Decimal(stock),disable_flag=0,synced_at=beijing_now().replace(microsecond=0)))
        db.commit()
        accessory_id = item.public_id
        # A matching name is insufficient: this SKU belongs to the other product.
        with pytest.raises(PortalError) as caught:
            sku_source.load_snapshot(db,namespace='okki:test',product_id=str(product_id),
                sku_id=str(sku_id+1),product_kind='accessory')
        assert caught.value.code == 'SKU_UNAVAILABLE' and caught.value.status == 409
        db.rollback()
        settings.PORTAL_INVENTORY_UNIT_BY_SKU = {f'{product_id}:{sku_id}':stock_unit}
        ctx.quote_body = QuoteInput.model_validate({**ctx.quote_body.model_dump(mode='json'),
            'items':[{'item_id':accessory_id,'quantity':6}]})
    async def quotes():
        async with client_app(ctx,monkeypatch) as client:
            detail = await client.get('/api/portal/v1/catalog/'+accessory_id)
            assert detail.status_code == 200
            data = detail.json()['data']
            assert data['category'] == 'accessory' and data['sale_unit'] == sale_unit
            assert data['weight_display'] == data['length_display'] == ''
            assert data['unit_price'] == '11.2500'
            with Session(ctx.engine) as db:
                observed = inventory_source.load(db,[db.scalar(select(CatalogItem).where(CatalogItem.public_id == accessory_id))])
            assert observed[accessory_id].quantity == Decimal(stock)
            assert observed[accessory_id].unit == stock_unit
            assert observed[accessory_id].observed_at <= beijing_now()
            assert data['availability'] == 'available'
            baseline = snapshot(ctx)
            body = ctx.quote_body.model_dump(mode='json'); body['items'][0]['quantity'] = 7
            excessive = await client.post('/api/portal/v1/quotes',json=body)
            assert excessive.status_code == 409 and excessive.json()['data']['error_code'] == 'STOCK_CHANGED'
            assert snapshot(ctx) == baseline
            with monkeypatch.context() as scoped:
                scoped.setattr(settings,'PORTAL_INVENTORY_UNIT_BY_SKU',{f'{product_id}:{sku_id}':'wrong-unit'})
                wrong = await client.post('/api/portal/v1/quotes',json=ctx.quote_body.model_dump(mode='json'))
                assert wrong.status_code == 503 and wrong.json()['data']['error_code'] == 'INVENTORY_UNAVAILABLE'
                assert snapshot(ctx) == baseline
            response = await client.post('/api/portal/v1/quotes',json=ctx.quote_body.model_dump(mode='json'))
            assert response.status_code == 201
            quote = response.json()['data']
            assert quote['items'][0]['unit_price'] == '11.2500'
            assert quote['product_amount'] == quote['items'][0]['line_amount'] == '67.50'
            assert quote['items'][0]['display_snapshot']['unit'] == sale_unit
            return quote
    quote = asyncio.run(quotes())
    ctx.body = SubmitInput(quote_id=quote['quote_id'],quote_content_hash=quote['content_hash'],
        customer_po=ctx.quote_body.customer_po,remark='')
    request_id,accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,request_id,3,accepted); db.commit()
    # A fresh connection/Session verifies stored PI and immutable confirmation.
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = db.get(Invoice,order.invoice_id)
        row = db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
        record = db.scalar(select(RequestLine).where(RequestLine.revision_id == order.accepted_revision_id))
        assert order.status == 'invoice_created' and count(db,Invoice,Invoice.source_order_id == request_id) == 1
        assert row.product_kind == record.product_kind == 'accessory'
        assert row.product_id == product_id and row.sku_id == sku_id and row.quantity == record.qty == 6
        assert row.product_name == row.product_display == 'Tape / replacement'
        assert row.length is None and row.net_weight_grams is None
        assert row.standard_price == Decimal('12.5000') and row.customer_price == row.price_per_piece == Decimal('11.2500')
        assert row.total_price == invoice.product_amount == Decimal('67.50')
        assert invoice.total_amount == Decimal('114.50')
        assert record.customer_display_json['unit'] == sale_unit
        assert record.unit_weight_grams == (Decimal(factor) if stock_unit == 'g' else None)
        _,_,published = pi_service.capture(db,ctx.token,request_id)
        assert published['product_amount'] == '67.50' and published['total_amount'] == '114.50'
        assert published['items'][0]['display_snapshot']['unit'] == sale_unit


def test_ambiguous_mirror_join_is_rejected_without_quote(trade):
    ctx = trade
    # The base mirror PK prevents duplicates. Use a test-owned replacement with
    # repeated source rows to exercise fail-closed SQL cardinality, then restore.
    with ctx.engine.begin() as connection:
        connection.execute(text('RENAME TABLE okki_product_skus TO portal_saved_skus'))
        connection.execute(text('CREATE TABLE okki_product_skus (product_id BIGINT,sku_id BIGINT,disable_flag INT)'))
        connection.execute(text('INSERT INTO okki_product_skus SELECT * FROM portal_saved_skus'))
    try:
        with Session(ctx.engine) as db:
            item = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
            db.execute(text('INSERT INTO okki_product_skus VALUES (:product,:sku,0)'),
                {'product':int(item.product_id),'sku':int(item.sku_id)})
            db.commit()
        baseline = snapshot(ctx)
        with Session(ctx.engine) as db:
            with pytest.raises(PortalError) as caught:
                quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body)
            assert caught.value.code == 'SKU_UNAVAILABLE' and caught.value.status == 409
            db.rollback()
        assert snapshot(ctx) == baseline
    finally:
        with ctx.engine.begin() as connection:
            connection.execute(text('DROP TABLE okki_product_skus'))
            connection.execute(text('RENAME TABLE portal_saved_skus TO okki_product_skus'))
    with Session(ctx.engine) as db:
        restored = quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body)
        db.commit()
        assert restored['product_amount'] == '81.00'