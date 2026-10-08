"""Actual legacy quote to current create must preserve original business item order."""
from uuid import uuid4
from sqlalchemy.orm import Session
from app.invoice.models import Invoice, InvoiceItem
from app.invoice import settlement_service
from test_mysql_shipment_create import shipment_app, snapshot, authorize, login  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


def test_reverse_business_item_order_quote_then_create(shipment_app):
    c=shipment_app
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);invoice.product_amount=150;invoice.total_amount=165;invoice.surcharge_amount=15
        first=db.get(InvoiceItem,c.item_id);first.sort_order=20
        values={col.name:getattr(first,col.name) for col in InvoiceItem.__table__.columns if col.name not in {'id'}}
        values.update(sort_order=10,product_id=3,sku_id=4,xiaoman_unique_id='102',quantity=5,total_price=50,price_per_piece=10)
        second=InvoiceItem(**values);db.add(second);db.flush();second_id=second.id;assert second_id>first.id;db.commit()
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        draft={'items':[{'invoice_item_id':c.item_id,'quantity':4},{'invoice_item_id':second_id,'quantity':2}],'freight_amount':'20.00'}
        quote=client.post(f'/api/invoices/{c.invoice_id}/shipment-quotes',headers=owner,json=draft)
        assert quote.status_code==200,quote.text
        expected=quote.json()['data'];assert [row['invoice_item_id'] for row in expected['items']]==[second_id,c.item_id]
        with Session(c.ctx.engine) as db:
            original=settlement_service.get_order(db,c.invoice_id,{'sub':str(c.ctx.actor),'roles':[],'permissions':[]})
            from app.invoice.settlement_schemas import ShipmentQuote
            legacy=settlement_service.build_quote(db,original,ShipmentQuote.model_validate(draft),settlement_service.fetch_evidence(db,original))
        assert expected==legacy, 'Current quote must retain original financial values, business order and hash'
        assert expected['goods_amount']=='60.00' and expected['handling_amount']=='6.00' and expected['new_payment_due']=='86.00'
        body={**draft,'quote_hash':expected['quote_hash'],'request_key':uuid4().hex}
        response=client.post(f'/api/invoices/{c.invoice_id}/shipment-settlements',headers=owner,json=body)
        assert response.status_code==200,response.text
        actual=response.json()['data']['quote']
        assert actual==expected and actual['quote_hash']==body['quote_hash'] and c.calls==[]
