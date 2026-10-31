"""Cash opening on the actual migration chain, with an explicit order-proof fixture.

The fixture is not an order importer. This verifies cash and paid commission
continuity only; complete historical fulfillment is verified separately.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.models import ArkUser
from app.catalog.models import CatalogSku
from app.customer.models import CustomerAccount
from app.commerce_migration import finance_service as opening
from app.commerce_migration.finance_schemas import FinanceOpeningManifest
from app.commission.models import CommissionEventProjection
from app.finance import service as finance
from app.finance.models import BankAccount
from app.finance.query_service import reconcile
from app.inventory.models import Warehouse
from app.invoice.models import Invoice
from app.invoice.commerce_service import create_draft, confirm
from app.invoice.settlement_models import ReceiptBatch, Receivable
from app.models.commission import CommissionDetail, SyncedPayment
from app.receipt.models import Receipt
from tests.test_commerce_finance_opening import inputs, counts
from tests.test_commission_local import batch
from tests.test_finance_local import cmd
from tests.test_invoice_commerce import draft, action
from app.services.commission_calculator import calculate_commission


def verify_finance_opening(engine):
    with Session(engine) as db:
        actor = db.scalar(select(ArkUser).where(ArkUser.username == 'chain-native-seller'))
        customer = db.scalar(select(CustomerAccount).where(CustomerAccount.customer_code == 'CHAIN-C'))
        bank = db.scalar(select(BankAccount).where(BankAccount.code == 'CHAIN-USD'))
        sku = db.scalar(select(CatalogSku).where(CatalogSku.code == 'CHAIN-S'))
        warehouses = list(db.scalars(select(Warehouse).where(Warehouse.code.in_(['CHAIN-MAIN', 'CHAIN-OTHER']))))
        user = dict(sub=str(actor.id), roles=['super_admin'], permissions=['invoice:write'])
        invoice = create_draft(db, draft(customer, user, sku, request_key='chain-opening-order-create',
            order_type='production', shipping_fee=0, surcharge_amount=0,
            items=[dict(local_sku_id=sku.id, quantity=10, price_per_piece=100)]), user)
        confirm(db, invoice.id, action('chain-opening-order-confirm', 1), user)
        target = db.scalar(select(Receivable).where(Receivable.invoice_id == invoice.id))
        raw, invoice, target = inputs(db, (customer, user, bank), (sku, warehouses), (customer, user), invoice_target=(invoice, target))
        invoice_id, target_id = invoice.id, target.id
        body = FinanceOpeningManifest.model_validate(raw)
        assert opening.preview(db, body)['can_apply']
        before = counts(db)
        db.commit()
    barrier = Barrier(3)
    def import_worker(index):
        with Session(engine) as db:
            counts(db)  # Establish the prior RR view before another writer commits.
            barrier.wait(timeout=15)
            candidate = body if index < 2 else body.model_copy(update={'batch_key': 'chain-old-rr-other-batch'})
            result = opening.apply_manifest(db, candidate, user)
            db.commit()
            return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(import_worker, range(3)))
    assert results[0] == results[1]
    assert results[0]['payments'] == results[2]['payments']
    result = results[0]
    with Session(engine) as db:
        after = counts(db)
        assert [a - b for a, b in zip(after, before)] == [2, 1, 1, 1, 3, 1, 0, 0]
        invoice, target = db.get(Invoice, invoice_id), db.get(Receivable, target_id)
        cash = db.get(ReceiptBatch, result['payments'][0]['batch_id'])
        receipt = db.get(Receipt, result['payments'][0]['allocations'][0]['receipt_id'])
        assert target.paid_amount == cash.allocated_amount == invoice.internal_received == 400
        assert cash.refunded_amount == 200 and finance.available(cash) == 0
        assert invoice.internal_balance == 600 and reconcile(db, user)['differences'] == []
        assert db.scalar(select(SyncedPayment.exchange_rate).where(SyncedPayment.payment_id == 'OLD-PAYMENT')) == Decimal('650')
        assert db.scalar(select(CommissionDetail.salesperson_commission).where(CommissionDetail.payment_id == 'OLD-PAYMENT')) == Decimal('7.01')
        paid_batch = batch(db, 'Chain historical no fresh income')
        assert calculate_commission(db, paid_batch.id).total_payments == 0
        for index, amount in enumerate([Decimal('133.33'), Decimal('133.33'), Decimal('133.34')]):
            finance.reverse_allocation(db, receipt.id, cmd(f'chain-opening-reverse-{index}', receipt.version, amount=amount), user)
        refund_batch = batch(db, 'Chain historical new full reversal')
        assert calculate_commission(db, refund_batch.id).total_salesperson_commission == Decimal('-4.67')
        projections = list(db.scalars(select(CommissionEventProjection).where(
            CommissionEventProjection.basis_id == db.scalar(select(CommissionEventProjection.basis_id).where(
                CommissionEventProjection.payment_id.like('ark-finance:%')).order_by(CommissionEventProjection.event_id.desc()).limit(1)))))
        assert sum((row.salesperson_commission_rmb for row in projections), Decimal(0)) == Decimal('-30.35')
        assert {db.scalar(select(SyncedPayment.exchange_rate).where(SyncedPayment.payment_id == row.payment_id))
                for row in projections} == {Decimal('6.5')}
        finance.refund(db, cash.id, cmd('chain-opening-full-refund', cash.version, amount=400, bank_reference='CHAIN-OPENING-REFUND'), user)
        assert target.paid_amount == cash.allocated_amount == invoice.internal_received == 0
        assert invoice.internal_balance == 1000 and cash.refunded_amount == 600
        assert reconcile(db, user)['differences'] == []
        db.commit()
        final_counts = counts(db)
        assert opening.apply_manifest(db, body, user) == result
        repeat = body.model_copy(update={'batch_key': 'chain-financial-replay-after-full-refund'})
        assert opening.apply_manifest(db, repeat, user)['payments'] == result['payments']
        db.commit()
        assert counts(db)[2:] == final_counts[2:]
        assert cash.refunded_amount == 600 and target.paid_amount == 0
    return dict(order_proof='explicit fixture, not imported order', concurrent_identical_results=True,
        opening_allocated='400.00', original_paid_usd='7.01', new_reversed_usd='4.67',
        new_reversed_rmb='30.35', original_scaled_fx_preserved='650', new_effective_fx='6.5',
        final_refunded='600.00', post_refund_replay_does_not_reset=True)
