"""Complete historical contracts retain identities before activation."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from app.commerce_migration import order_service as service, service as catalog_service
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.commerce_migration.models import MigrationRecord, MigrationBatch
from app.customer.models import CustomerExternalIdentity, CustomerOrder, CustomerOrderItem
from app.core.time import beijing_now
from app.finance.models import FinanceEvent
from app.finance.query_service import order_options
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import Receivable
from app.inventory.models import StockLedger
from app.trade.snapshot_service import build_snapshot
from app.trade.projection_service import project_invoice
from app.trade.refresh_service import pending_invoices
from tests.test_commerce_migration import manifest
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock

DAY = date(2026, 10, 3)


def inputs(db, buyer, *, tag='OLD', tenant='tenant-A', catalog_code=None):
    customer, user = buyer
    catalog_body = manifest() if tenant == 'tenant-A' else manifest(tenant=tenant, batch_key=f'catalog-{tag}')
    if catalog_code is not None:
        catalog_body.catalog[0].product.code = f'M-P1-{catalog_code}'
        catalog_body.catalog[0].sku.code = f'M-S1-{catalog_code}'
    catalog = catalog_service.apply_manifest(db, catalog_body, user)['catalog'][0]
    identity = CustomerExternalIdentity(customer_id=customer.id, source_system='okki', source_account_key=tenant,
        identifier_type='company_id', raw_value=f'{tag}-CUSTOMER', normalized_value=f'{tag}-CUSTOMER',
        identity_strength='strong', cardinality='one_to_one', auto_match_ceiling='verified', verification_status='verified',
        confidence=1, confidence_method_version='confidence_v1', confidence_components_json={}, is_primary=True,
        first_seen_at=beijing_now(), last_seen_at=beijing_now(), status='active', identity_fingerprint=catalog_service.digest([customer.id, tenant, tag]))
    db.add(identity); db.flush()
    row = dict(source_order_id='OLD-ORDER', source_customer_id='OLD-CUSTOMER', source_order_no='OLD-NO', legacy_invoice_order_no=None,
        source_order_name='Old contract', source_order_status='effective', local_customer_id=customer.id,
        customer_external_identity_id=identity.id, invoice_no='ORIGINAL-INVOICE', order_type='stock',
        commerce_status='partially_shipped', invoice_date='2026-10-01', account_date='2026-10-02', currency='USD', rate_to_usd='1',
        customer_name='Original buyer', customer_grade=None, contact_name=None, contact_phone=None, contact_email=None,
        delivery_address='Original address', sales_user_id=int(user['sub']), sales_user_name='Original seller',
        owner_external_user_id='OLD-SELLER', merchandiser_id=None, merchandiser_name=None, express_channel=None,
        shipping_fee='0', surcharge_name=None, surcharge_amount='0', packaging_quantity=0, internal_accessory=None,
        internal_discount=None, internal_payment_method=None, internal_shipping_type=None, product_amount='1000',
        total_amount='1000', source_received_amount='600', source_balance_amount='400', local_deposit_amount='0',
        local_deposit_charge='0', commercial_source='other', is_new_deal=False, is_first_return=True, is_private_order=False,
        is_valid_business_order=True, business_amount_original='1000', business_amount_usd='1000', country='US',
        departments=[], payment_term=None, remark='Original remark', items=[dict(source_item_id='OLD-ITEM', legacy_unique_id='OLD-ITEM',
            catalog_record_id=catalog['record_id'], local_sku_id=catalog['sku_id'], product_kind='hair', item_type='stock',
            product_name='Old product name', product_display='Old hair', product_family='Old hair', net_weight_grams='20g', model='Old model',
            color='Black', length='18', curl=None, quantity=10, price_per_piece='100', standard_price=None, customer_price=None,
            discount_amount='0', total_price='1000', price_source='manual', commercial_kind='bulk', shipped_quantity=6,
            production_pending_quantity=0, reservations=[])], receivables=[dict(external_id='OLD-AR', kind='goods',
        amount='1000', handling_amount='0', source_settlement_id=None, due_date='2026-10-31', paid_amount='600', adjustments=[])],
        historical_shipment_ids=['OLD-SHIP'], production_ids=[], material_allocation_ids=[])
    if tag != 'OLD':
        row.update(source_order_id=f'{tag}-ORDER', source_customer_id=f'{tag}-CUSTOMER', source_order_no=f'{tag}-NO', invoice_no=f'{tag}-INVOICE')
        row['items'][0]['source_item_id'] = f'{tag}-ITEM'
        row['items'][0]['legacy_unique_id'] = f'{tag}-ITEM'
        row['receivables'][0]['external_id'] = f'{tag}-AR'
        row['historical_shipment_ids'] = [f'{tag}-SHIP']
    raw = dict(batch_key='whole-order-opening' if tag == 'OLD' else f'whole-order-{tag}', source='okki', tenant=tenant, cutover_date=DAY,
        evidence_sha256='b'*64, review_reference='Synthetic complete contract reviewed', orders=[row])
    return raw


def counts(db):
    return [db.scalar(select(func.count()).select_from(model)) for model in
        (Invoice, InvoiceItem, CustomerOrder, CustomerOrderItem, Receivable, FinanceEvent, StockLedger)]


def seed_original_order(db, raw, user):
    """Create the legacy full contract and actual stable projection identities."""
    body = OrderOpeningManifest.model_validate(raw)
    row = body.orders[0]
    source = service._source(db, body, row, 'order', row.source_order_id, {'old': 'raw'}, row.local_customer_id)
    invoice = Invoice(**{key: getattr(row, key) for key in service.HEADER_FIELDS}, customer_id=row.source_customer_id,
        xiaoman_order_id=row.source_order_id, xiaoman_order_no=row.legacy_invoice_order_no, internal_received=row.source_received_amount,
        internal_balance=row.source_balance_amount, status='synced', sync_status='synced')
    db.add(invoice); db.flush()
    order = CustomerOrder(customer_id=row.local_customer_id, source_system=body.source, source_account_key=body.tenant,
        external_order_id=row.source_order_id, **{key: getattr(row, value) for key, value in service.ORDER_FIELDS.items()},
        source_record_id=source.id, source_hash=source.content_hash, synced_at=beijing_now())
    db.add(order); db.flush()
    raw['orders'][0].update(existing_invoice_id=invoice.id, existing_customer_order_id=order.id)
    for index, old in enumerate(row.items):
        line = InvoiceItem(invoice_id=invoice.id, xiaoman_unique_id=old.legacy_unique_id,
            **{key: getattr(old, key) for key in service.ITEM_FIELDS})
        projected = CustomerOrderItem(order_id=order.id, external_item_id=old.source_item_id, quantity=old.quantity,
            quantity_unit='pcs', unit_price=old.price_per_piece, line_amount=old.total_price,
            item_type=old.commercial_kind, product_name=old.product_name, source_record_id=source.id,
            item_fingerprint=service.digest([body.source, body.tenant, old.source_item_id]))
        db.add_all([line, projected]); db.flush()
        raw['orders'][0]['items'][index].update(existing_invoice_item_id=line.id, existing_customer_order_item_id=projected.id)
    return invoice, order


def test_complete_contract_preparation_is_read_only_then_gated_and_replay_preserves_live_state(db, stock, buyer):
    raw = inputs(db, buyer)
    body = OrderOpeningManifest.model_validate(raw)
    before = counts(db)
    assert service.preview(db, body)['can_apply'] and counts(db) == before
    result = service.apply_manifest(db, body, buyer[1]); db.commit()
    mapping = result['orders'][0]
    invoice = db.get(Invoice, mapping['invoice_id'])
    assert invoice.commerce_status == 'opening' and invoice.transaction_mode == 'local'
    assert invoice.total_amount == 1000 and invoice.items[0].quantity == 10
    assert invoice.customer_id == 'OLD-CUSTOMER' and invoice.internal_received == 0 and invoice.internal_balance == 1000
    assert invoice.items[0].stock_shipped_quantity == 0
    assert counts(db) == [1, 1, 1, 1, 1, 0, 0]
    assert build_snapshot(db, invoice.id) is None
    assert db.scalars(pending_invoices()).all() == []
    assert order_options(db, buyer[1])['items'] == []
    assert service.apply_manifest(db, body, buyer[1]) == result
    invoice.internal_received, invoice.internal_balance = 600, 400
    later = body.model_copy(update={'batch_key': 'whole-order-replay'})
    assert service.apply_manifest(db, later, buyer[1])['orders'] == result['orders']
    assert invoice.internal_received == 600 and invoice.internal_balance == 400
    assert counts(db) == [1, 1, 1, 1, 1, 0, 0]


def test_full_projection_number_is_separate_from_original_invoice_alias(db, stock, buyer):
    raw = inputs(db, buyer)
    raw['orders'][0].update(source_order_no='N'*100, legacy_invoice_order_no='Original invoice alias')
    body = OrderOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    mapping = service.apply_manifest(db, body, buyer[1])['orders'][0]
    assert db.get(CustomerOrder, mapping['customer_order_id']).order_no == 'N'*100
    assert db.get(Invoice, mapping['invoice_id']).xiaoman_order_no == 'Original invoice alias'
    wrong = deepcopy(raw)
    wrong['orders'][0]['legacy_invoice_order_no'] = 'X'*65
    with pytest.raises(ValidationError):
        OrderOpeningManifest.model_validate(wrong)


def test_existing_full_invoice_and_projection_keep_ids_sources_and_namespace(db, stock, buyer):
    raw = inputs(db, buyer)
    row = OrderOpeningManifest.model_validate(raw).orders[0]
    source = service._source(db, OrderOpeningManifest.model_validate(raw), row, 'order', 'OLD-ORDER', {'old': 'raw'}, buyer[0].id)
    invoice = Invoice(**{key: getattr(row, key) for key in service.HEADER_FIELDS}, customer_id='OLD-CUSTOMER',
        xiaoman_order_id='OLD-ORDER', internal_received=600, internal_balance=400, status='synced', sync_status='synced')
    db.add(invoice); db.flush()
    line = InvoiceItem(invoice_id=invoice.id, xiaoman_unique_id='OLD-ITEM', **{key: getattr(row.items[0], key) for key in service.ITEM_FIELDS})
    order = CustomerOrder(customer_id=buyer[0].id, source_system='okki', source_account_key='tenant-A', external_order_id='OLD-ORDER',
        **{key: getattr(row, source) for key, source in service.ORDER_FIELDS.items()}, source_record_id=source.id, source_hash=source.content_hash,
        synced_at=beijing_now())
    db.add_all([line, order]); db.flush()
    projected = CustomerOrderItem(order_id=order.id, external_item_id='OLD-ITEM', quantity=10, quantity_unit='pcs',
        unit_price=100, line_amount=1000, item_type='bulk', product_name='Old product name', source_record_id=source.id,
        item_fingerprint='c'*64)
    db.add(projected); db.flush()
    original_created = invoice.created_at
    raw['orders'][0].update(existing_invoice_id=invoice.id, existing_customer_order_id=order.id)
    raw['orders'][0]['items'][0].update(existing_invoice_item_id=line.id, existing_customer_order_item_id=projected.id)
    body = OrderOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    mapping = service.apply_manifest(db, body, buyer[1])['orders'][0]; db.commit()
    assert (mapping['invoice_id'], mapping['customer_order_id']) == (invoice.id, order.id)
    assert mapping['items'][0]['invoice_item_id'] == line.id and mapping['items'][0]['customer_order_item_id'] == projected.id
    assert projected.source_record_id == order.source_record_id == source.id
    assert projected.item_fingerprint == 'c'*64 and projected.quantity_unit == 'pcs'
    assert invoice.created_at == original_created and invoice.xiaoman_order_id == 'OLD-ORDER'
    # This directly releases the gate only to isolate native read-model behavior;
    # it is not evidence that the activation responsibility checks are complete.
    invoice.commerce_status = 'partially_shipped'
    invoice.items[0].stock_shipped_quantity = 6
    invoice.internal_received, invoice.internal_balance = 600, 400
    result = project_invoice(db, invoice.id); db.commit()
    assert result.id == order.id and result.source_system == 'okki' and result.external_order_id == 'OLD-ORDER'
    assert result.order_no == 'OLD-NO' and result.order_name == 'Old contract' and result.owner_external_user_id == 'OLD-SELLER'
    assert result.account_date == date(2026, 10, 2) and result.amount_usd == 1000
    assert db.scalars(select(CustomerOrderItem)).one().id == projected.id
    assert projected.external_item_id == 'OLD-ITEM' and projected.item_fingerprint == 'c'*64 and projected.local_invoice_item_id == line.id


@pytest.mark.parametrize('change', ['credit_positive', 'goods_fee_missing', 'shipped_in_confirmed', 'partial_without_shipment'])
def test_schema_rejects_unconserved_or_incomplete_old_contracts(db, stock, buyer, change):
    raw = inputs(db, buyer)
    row = raw['orders'][0]
    if change == 'credit_positive':
        row['receivables'][0]['adjustments'] = [dict(external_id='OLD-CREDIT', kind='credit', amount='10', released_bank_charge='0',
            business_date='2026-10-03', reason='Source credit')]
    elif change == 'goods_fee_missing':
        row.update(surcharge_amount='10', total_amount='1010')
        row['receivables'][0].update(amount='1010')
        row['source_balance_amount'] = '410'
    elif change == 'shipped_in_confirmed':
        row['commerce_status'] = 'confirmed'
    else:
        row['historical_shipment_ids'] = []
    with pytest.raises(ValidationError):
        OrderOpeningManifest.model_validate(raw)


@pytest.mark.parametrize('change', ['wrong_catalog', 'wrong_customer', 'omitted_original_invoice'])
def test_current_proofs_and_existing_identity_conflicts_fail_before_mutation(db, stock, buyer, change):
    raw = inputs(db, buyer)
    if change == 'wrong_catalog':
        raw['orders'][0]['items'][0]['local_sku_id'] = stock[0].id
    elif change == 'wrong_customer':
        raw['orders'][0]['source_customer_id'] = 'OTHER-CUSTOMER'
    else:
        row = OrderOpeningManifest.model_validate(raw).orders[0]
        db.add(Invoice(**{key: getattr(row, key) for key in service.HEADER_FIELDS}, customer_id=row.source_customer_id,
            xiaoman_order_id=row.source_order_id))
        db.flush()
    body = OrderOpeningManifest.model_validate(raw)
    before = counts(db)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert counts(db) == before


def test_late_preparation_failure_rolls_back_all_master_and_economic_rows(db, stock, buyer, monkeypatch):
    raw = inputs(db, buyer)
    body = OrderOpeningManifest.model_validate(raw)
    before = counts(db)
    post = service._post_order
    def fail(*args):
        post(*args)
        raise ValueError('Synthetic late order opening failure')
    monkeypatch.setattr(service, '_post_order', fail)
    with pytest.raises(ValueError, match='late'):
        service.apply_manifest(db, body, buyer[1])
    db.commit()
    assert counts(db) == before
    assert db.get(MigrationBatch, body.batch_key) is None


def test_opening_credit_fee_and_source_validity_keep_original_business_basis(db, stock, buyer):
    raw = inputs(db, buyer)
    row = raw['orders'][0]
    row.update(surcharge_amount='10', total_amount='1010', source_balance_amount='300',
        business_amount_original='900', business_amount_usd='900', is_valid_business_order=False)
    row['receivables'][0].update(amount='1010', handling_amount='10', adjustments=[dict(external_id='OLD-CREDIT',
        kind='credit', amount='-110', released_bank_charge='10', business_date='2026-10-03', reason='Original approved credit')])
    body = OrderOpeningManifest.model_validate(raw)
    mapping = service.apply_manifest(db, body, buyer[1])['orders'][0]
    invoice = db.get(Invoice, mapping['invoice_id'])
    target = db.get(Receivable, mapping['receivables'][0]['receivable_id'])
    assert target.amount == 1010 and target.adjustment_amount == -110 and target.handling_amount == 0
    invoice.commerce_status = 'partially_shipped'
    snapshot = build_snapshot(db, invoice.id)
    assert snapshot['amount_usd'] == '900.00' and snapshot['is_valid_business_order'] is False


def test_finance_allocation_uses_current_order_owner_but_unallocated_cash_keeps_payer(db, stock, buyer):
    from app.customer.models import CustomerAccount, CustomerChangeProposal
    from datetime import timedelta
    from tests.test_customer_governance_policy import _profile, _digest
    from app.customer.transaction_identity import invoice_customer, current_customer
    from app.core.time import beijing_now
    from app.customer.models import CustomerObjectOwnership
    raw = inputs(db, buyer)
    mapping = service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), buyer[1])['orders'][0]
    invoice = db.get(Invoice, mapping['invoice_id'])
    old = buyer[0]
    new = CustomerAccount(customer_code='C2', display_name='Logical buyer', entity_type='registered_company',
        identity_status='verified', relationship_stage='active_customer', relationship_stage_changed_at=beijing_now(),
        relationship_stage_reason='test', record_status='active', identity_confidence=1,
        profile_completeness=100, profile_input_seq=1)
    db.add(new); db.flush()
    # A split transfers this specific order through the existing ownership
    # object. It does not change ownership of an unrelated payer's cash.
    profile = _profile(db, old)
    proposal = CustomerChangeProposal(customer_id=old.id, target_customer_id=new.id, action_type='split',
        payload_schema_version='customer_split_v1', payload_json={}, profile_version_id=profile.id, evidence_fact_ids=[],
        risk_level='critical', data_classification='restricted_internal', visibility_scope='management',
        action_hash=_digest('order-opening-split'), status='executed', expires_at=beijing_now()+timedelta(days=1))
    db.add(proposal); db.flush()
    ownership = CustomerObjectOwnership(object_type='order', object_id=mapping['customer_order_id'],
        storage_customer_id=old.id, current_customer_id=new.id, ownership_version=1,
        last_change_proposal_id=proposal.id, last_action_type='split')
    db.add(ownership); db.flush()
    assert invoice_customer(db, invoice) == new.id
    assert current_customer(db, old.id) == old.id
    old.record_status, old.merged_into_customer_id = 'merged', new.id
    db.flush()
    assert current_customer(db, old.id) == new.id and invoice_customer(db, invoice) == new.id
