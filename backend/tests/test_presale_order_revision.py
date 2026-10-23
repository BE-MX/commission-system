"""Whole-order edits retain physical/cash history without duplicating products."""
from decimal import Decimal
from copy import deepcopy
import pytest
from tests.test_presale_runtime import order, payment, create, evidence
from app.invoice import service, presale_lines, settlement_service as shipments
from app.invoice.models import InvoiceItem
from app.invoice import presale_order_revision as revisions
from app.invoice.settlement_models import SettlementApplication,ShipmentSettlement
from app.invoice.settlement_schemas import ShipmentQuote
from app.invoice.settlement_schemas import ShipmentCreate
from app.invoice import shipment_delivery
from tests.test_presale_inspection_completion import batch
from tests.test_presale_existing_batch_funding import existing


@pytest.fixture
def revised(db, order):
    payment(db, order)
    batch, _ = create(db, order, quantity=1, freight='0')
    batch.state='shipped'
    for application in db.query(SettlementApplication):application.status='applied'
    original=order.items[0]
    original.presale_archived=1; original.presale_shipped_quantity=1
    original.presale_shipped_amount=Decimal('209')
    current=InvoiceItem(**{c.name:getattr(original,c.name) for c in InvoiceItem.__table__.columns
        if c.name not in {'id','created_at','updated_at'}})
    current.presale_archived=0;current.presale_shipped_quantity=0;current.presale_shipped_amount=0
    order.items.append(current);db.flush()
    order.presale_order_revision={'schema_version':1,'mode':'whole_order','revision':1,
        'request_id':'test-revision','sources':{str(current.id):[original.id]},'approved_credit':'0.00'}
    db.commit()
    return order,original,current,batch


def test_whole_order_amount_does_not_add_shipped_history(db,revised):
    invoice,original,current,_=revised
    service._refresh_invoice_totals(invoice)
    assert invoice.total_amount==Decimal('627')
    assert original.presale_shipped_amount==Decimal('209')
    assert [i.id for i in presale_lines.remote_items(invoice)]==[current.id]


@pytest.fixture
def credit_case(db,revised):
    invoice,original,current,batch=revised
    current.quantity=1;current.total_price=Decimal('51.70');current.discount_amount=Decimal('-157.30')
    extra=InvoiceItem(invoice_id=invoice.id,sort_order=2,product_id=3,sku_id=4,product_name='New hair',
        product_display='Hair',color='A',quantity=2,price_per_piece=250,total_price=500,xiaoman_unique_id='12')
    invoice.items.append(extra);db.flush();revisions.recompute(db,invoice);service._refresh_invoice_totals(invoice);db.commit()
    assert invoice.presale_order_revision['approved_credit']=='157.30'
    return invoice,original,current,batch,extra


def test_credit_is_discount_not_additional_cash_and_net_payable_is_consistent(db,credit_case):
    invoice,original,current,batch,extra=credit_case
    before=[(a.id,a.amount,a.bank_charge,a.status) for a in db.query(SettlementApplication)]
    body=ShipmentQuote(items=[{'invoice_item_id':extra.id,'quantity':2}])
    quoted=shipments.build_quote(db,invoice,body,evidence(db,invoice),current=True)
    assert quoted['items'][0]['line_amount']=='500.00'
    assert Decimal(quoted['gross_goods_amount'])==500
    assert Decimal(quoted['price_credit_applied'])==Decimal('157.30')
    assert Decimal(quoted['goods_amount'])==Decimal('342.70')
    assert Decimal(quoted['funding_total_amount'])==Decimal('342.70')
    assert original.presale_shipped_amount+Decimal(quoted['goods_amount'])==invoice.total_amount==Decimal('551.70')
    assert [(a.id,a.amount,a.bank_charge,a.status) for a in db.query(SettlementApplication)]==before


def test_backend_deducts_explicit_source_history_and_rejects_repeat_shipping(db,credit_case):
    invoice,_,current,_,_=credit_case
    with pytest.raises(ValueError,match='exceeds'):
        shipments.build_quote(db,invoice,ShipmentQuote(items=[{'invoice_item_id':current.id,'quantity':1}]),evidence(db,invoice))


@pytest.mark.parametrize('state',['awaiting_payment','paused','outbound_uncertain','shipped','cancelled'])
def test_credit_occupancy_includes_every_non_cancelled_batch(db,credit_case,state):
    invoice,_,_,_,extra=credit_case
    used=ShipmentSettlement(invoice_id=invoice.id,sequence=2,settlement_no='CREDIT-2',state=state,is_final=0,
        quote={'price_credit_applied':'100.00'},quote_hash='x',request_key='credit-2',request_hash='x',created_by=1)
    db.add(used);db.flush()
    result={'goods_amount':'500.00'};revisions.apply_credit(db,invoice,result,current=True)
    assert Decimal(result['price_credit_applied'])==Decimal('157.30' if state=='cancelled' else '57.30')


def test_credit_cannot_fund_freight_or_create_money(db,credit_case):
    invoice,*_=credit_case
    result={'goods_amount':'50.00','freight_amount':'38.00','handling_amount':'5.00'}
    revisions.apply_credit(db,invoice,result)
    assert Decimal(result['goods_amount'])==0
    assert result['freight_amount']=='38.00' and result['handling_amount']=='5.00'
    assert revisions.used_credit(db,invoice)==0


def test_quote_has_no_orm_side_effects(db,credit_case):
    invoice,*_=credit_case
    before=deepcopy(invoice.presale_order_revision)
    revisions.apply_credit(db,invoice,{'goods_amount':'500.00'})
    assert not db.dirty and invoice.presale_order_revision==before


def test_repeated_recompute_does_not_duplicate_approved_credit(db,credit_case):
    invoice,*_=credit_case
    revisions.recompute(db,invoice);revisions.recompute(db,invoice)
    assert invoice.presale_order_revision['approved_credit']=='157.30'


def test_order_quantity_cannot_drop_below_actual_shipped_quantity(db,revised):
    invoice,_,current,_=revised
    current.quantity=0
    with pytest.raises(ValueError,match='小于历史'):
        revisions.recompute(db,invoice)


def test_append_batch_orders_keep_original_quantity_and_amount_semantics(db,revised):
    invoice,original,current,_=revised
    invoice.presale_order_revision=None
    service._refresh_invoice_totals(invoice)
    assert invoice.total_amount==Decimal('836')
    assert [i.id for i in presale_lines.remote_items(invoice)]==[original.id,current.id]


def test_commercial_credit_can_cover_goods_without_a_fake_receipt(db,credit_case):
    invoice,_,_,_,extra=credit_case
    extra.quantity=1;extra.total_price=100;extra.price_per_piece=100
    service._refresh_invoice_totals(invoice);db.commit()
    draft=ShipmentQuote(items=[{'invoice_item_id':extra.id,'quantity':1}])
    quoted=shipments.build_quote(db,invoice,draft,evidence(db,invoice),current=True)
    assert Decimal(quoted['price_credit_applied'])==100
    assert Decimal(quoted['goods_amount'])==Decimal(quoted['funding_total_amount'])==0
    body=ShipmentCreate(**draft.model_dump(),quote_hash=quoted['quote_hash'],request_key='revision-zero-goods-001')
    row=shipments._create_verified(db,invoice,body,{'sub':'1'},evidence(db,invoice),None)
    db.commit()
    assert not db.query(SettlementApplication).filter_by(settlement_id=row.id).count()
    assert shipment_delivery._funded(db,row)
    assert Decimal(shipments.funding_balance(db,row)['remaining_amount'])==0
    assert revisions.used_credit(db,invoice)==100


def test_credit_reduction_below_reserved_amount_is_rejected(db,credit_case):
    invoice,_,current,_,_=credit_case
    held=ShipmentSettlement(invoice_id=invoice.id,sequence=2,settlement_no='CREDIT-HELD',state='paused',is_final=0,
        quote={'price_credit_applied':'157.30'},quote_hash='x',request_key='credit-held',request_hash='x',created_by=1)
    db.add(held);db.flush();current.total_price=Decimal('52.70')
    with pytest.raises(ValueError,match='已使用抵扣'):
        revisions.recompute(db,invoice,current=True)


def test_source_line_identity_cannot_be_guessed_from_sku(db,revised):
    invoice,_,current,_=revised
    current.xiaoman_unique_id='99'
    with pytest.raises(ValueError,match='来源不属于'):
        revisions.recompute(db,invoice)


def test_exact_veronika_quantities_and_accounting(db,order):
    from app.invoice.settlement_models import SettlementItem
    from app.invoice.settlement_pricing import quote_current
    order.items.clear();db.flush()
    batch=ShipmentSettlement(invoice_id=order.id,sequence=1,settlement_no='V-ORIGINAL',state='shipped',is_final=0,
        quote={},quote_hash='x',request_key='v-original',request_hash='x',created_by=1)
    db.add(batch);db.flush();mapping={};current=[]
    cases=[(4,'169.72',5,'212.15'),(3,'127.29',3,'127.29'),(5,'119.08',5,'119.08'),
        (5,'188.75',5,'31.45'),(1,'22.16',7,'155.12')]
    for n,(q,amount,target_q,target_amount) in enumerate(cases,1):
        old=InvoiceItem(invoice_id=order.id,sort_order=n,product_id=n,sku_id=n,product_name='Old',product_display='Hair',
            color='A',quantity=q,total_price=Decimal(amount),xiaoman_unique_id=str(n),presale_archived=1,
            presale_shipped_quantity=q,presale_shipped_amount=Decimal(amount))
        row=InvoiceItem(invoice_id=order.id,sort_order=n,product_id=n,sku_id=n,product_name='Target',product_display='Hair',
            color='A',quantity=target_q,total_price=Decimal(target_amount),xiaoman_unique_id=str(n),presale_archived=0)
        order.items.extend([old,row]);db.flush()
        db.add(SettlementItem(settlement_id=batch.id,invoice_item_id=old.id,quantity=q,line_amount=Decimal(amount),snapshot={}))
        mapping[str(row.id)]=[old.id];current.append(row)
    extra=InvoiceItem(invoice_id=order.id,sort_order=6,product_id=6,sku_id=6,product_name='Remaining',product_display='Hair',
        color='A',quantity=1,total_price=Decimal('2625.39'),xiaoman_unique_id='6')
    order.items.append(extra);db.flush()
    order.presale_order_revision={'schema_version':1,'mode':'whole_order','revision':1,'sources':mapping,'approved_credit':'0.00'}
    revisions.recompute(db,order);service._refresh_invoice_totals(order);db.flush()
    facts=revisions.history(db,order);remaining=[row.quantity-sum(facts[k][0] for k in revisions.sources(order,row.id)) for row in current]
    assert remaining==[1,0,0,0,6]
    lines=[{'invoice_item_id':row.id,'quantity':row.quantity,'total_price':str(row.total_price),
        'shipped_quantity':row.quantity-rest,'requested_quantity':rest} for row,rest in zip(current,remaining)]
    lines.append({'invoice_item_id':extra.id,'quantity':1,'total_price':'2625.39','requested_quantity':1})
    quoted=quote_current(lines,'0','0');revisions.apply_credit(db,order,quoted)
    assert Decimal(quoted['gross_goods_amount'])==Decimal('2800.78')
    assert Decimal(quoted['price_credit_applied'])==Decimal('157.30')
    assert Decimal(quoted['goods_amount'])==Decimal('2643.48')
    assert order.total_amount==Decimal('3270.48')==Decimal('627')+Decimal(quoted['goods_amount'])


def test_v2_synced_v3_edit_keeps_original_batch_unlocked_and_rejects_mixed_versions(db,order,existing):
    from app.invoice import linked_sync_service as linked
    settlement,outbound,_,main,_,_=existing
    original=order.items[0]
    original.presale_archived=1;original.presale_shipped_quantity=1;original.presale_shipped_amount=209
    current=InvoiceItem(**{c.name:getattr(original,c.name) for c in InvoiceItem.__table__.columns
        if c.name not in {'id','created_at','updated_at'}})
    current.presale_archived=0;current.presale_shipped_quantity=0;current.presale_shipped_amount=0
    current.price_per_piece=Decimal('51.70');current.total_price=Decimal('155.10')
    order.items.append(current);db.flush()
    order.presale_order_revision={'schema_version':1,'mode':'whole_order','revision':2,
        'sources':{str(current.id):[original.id]},'approved_credit':'157.30'}
    main['product_list'][0].update(count=3,cost_amount='155.10',unit_price='51.70')
    order.sync_status='synced';service._refresh_invoice_totals(order)
    snapshot=linked.snapshot(order);revisions.record_synced(order)
    assert linked.snapshot(order)==snapshot
    db.commit()
    assert shipment_delivery.refresh(db,outbound.id)=='shipped'
    current.price_per_piece=50;current.total_price=150;order.sync_status='not_synced'
    revisions.recompute(db,order);service._refresh_invoice_totals(order);db.commit()
    assert shipment_delivery.refresh(db,outbound.id)=='shipped'  # Provider still at v2.
    main['product_list'][0]['unit_price']='50.00'  # Mixed v2 amount with v3 price is invalid.
    assert shipment_delivery.refresh(db,outbound.id)=='shipped_unfunded'
    main['product_list'][0]['cost_amount']='150.00'
    order.sync_status='synced';revisions.record_synced(order);db.commit()
    assert shipment_delivery.refresh(db,outbound.id)=='shipped'
    main['product_list'][0].update(cost_amount='155.10',unit_price='51.70')
    assert shipment_delivery.refresh(db,outbound.id)=='shipped_unfunded'


def test_future_saves_keep_sources_and_immutable_revision_audits(db,credit_case):
    from types import SimpleNamespace
    from app.shipping_inspection.models import ShippingOperationEvent
    invoice,original,current,_,extra=credit_case
    body=SimpleNamespace(items=[SimpleNamespace(id=current.id),SimpleNamespace(id=extra.id)],
        internal_accessory=0,surcharge_amount=0)
    before=deepcopy(invoice.presale_order_revision)
    for _ in range(2):
        context=revisions.edit_context(db,invoice,body)
        revisions.finish_edit(db,invoice,context,[(current,current.id),(extra,extra.id)],actor=1)
        db.commit()
    rows=db.query(ShippingOperationEvent).filter_by(scope='presale-order-revision').order_by(ShippingOperationEvent.id).all()
    assert len(rows)==2 and rows[0].request_id!=rows[1].request_id
    assert rows[0].payload['before']==before
    assert rows[0].payload['after']==rows[1].payload['before']
    assert revisions.sources(invoice,current.id)==[original.id]
    assert invoice.presale_order_revision['approved_credit']=='157.30'


@pytest.mark.parametrize('field',['packaging_amount','handling_amount'])
def test_whole_order_revision_rejects_unsupported_historical_fees(db,credit_case,field):
    invoice,_,_,batch,_=credit_case
    batch.quote={**batch.quote,field:'1.00'};db.flush()
    with pytest.raises(ValueError,match='历史批次存在'):
        revisions.recompute(db,invoice)


def test_saving_after_another_partial_batch_preserves_full_source_chain(db,revised,monkeypatch):
    from app.invoice.schemas import InvoiceUpdate,InvoiceItemPayload
    from app.invoice.settlement_models import SettlementItem
    from app.invoice import product_service,price_service
    invoice,original,current,_=revised
    later=ShipmentSettlement(invoice_id=invoice.id,sequence=2,settlement_no='SECOND-SHIPPED',state='shipped',is_final=0,
        quote={},quote_hash='x',request_key='second-shipped',request_hash='x',created_by=1)
    db.add(later);db.flush()
    db.add(SettlementItem(settlement_id=later.id,invoice_item_id=current.id,quantity=1,line_amount=209,snapshot={'order_record_id':'11'}));db.commit()
    monkeypatch.setattr(product_service,'valid_okki_product_skus',lambda _db,pairs:pairs)
    monkeypatch.setattr(price_service,'resolve_price',lambda *a,**k:{'standard_price':None,'customer_price':None,'currency':'USD'})
    old_id=current.id;original_fields=(original.quantity,original.total_price,original.xiaoman_unique_id)
    def save(item):
        body=InvoiceUpdate(customer_id=invoice.customer_id,customer_name=invoice.customer_name,
            invoice_date=invoice.invoice_date,order_type='presale',items=[InvoiceItemPayload(id=item.id,
                product_id=item.product_id,sku_id=item.sku_id,product_name=item.product_name,product_display=item.product_display,
                color=item.color,quantity=4,price_per_piece=209)])
        service._replace_items(db,invoice,body,user_id=1);service._refresh_invoice_totals(invoice);db.commit()
        return presale_lines.current_items(invoice)[0]
    replacement=save(current)
    assert replacement.id!=old_id and replacement.xiaoman_unique_id=='11'
    assert revisions.sources(invoice,replacement.id)==[original.id,old_id]
    assert invoice.total_amount==Decimal('836')
    assert (original.quantity,original.total_price,original.xiaoman_unique_id)==original_fields
    again=save(replacement)
    assert again.id==replacement.id
    assert revisions.sources(invoice,again.id)==[original.id,old_id]
    assert invoice.presale_order_revision['approved_credit']=='0.00'


def test_activation_is_audited_with_production_column_lengths_and_refuses_replay(db,revised):
    import json
    from app.shipping_inspection.models import ShippingOperationEvent
    invoice,original,current,_=revised
    invoice.presale_order_revision=None;invoice.sync_status='synced';current.xiaoman_unique_id='99';db.flush()
    revisions.activate(db,invoice,{str(current.id):[original.id]},
        {'11':{'quantity':3,'amount':'627.00','unit_price':'209.00'}},actor=0,request_id='activate-contract',confirmation='User confirmed whole-order repair')
    db.flush()
    event=db.query(ShippingOperationEvent).filter_by(scope='presale-order-revision',request_id='activate-contract').one()
    assert len(event.action)<=ShippingOperationEvent.__table__.c.action.type.length
    assert event.action=='revision_activated'
    assert current.xiaoman_unique_id==original.xiaoman_unique_id=='11'
    assert json.loads(invoice.xiaoman_removed_lines)[0]['unique_id']=='99'
    with pytest.raises(ValueError,match='读取原维护结果'):
        revisions.activate(db,invoice,{str(current.id):[original.id]}, {},actor=0,
            request_id='activate-contract',confirmation='User confirmed whole-order repair')
