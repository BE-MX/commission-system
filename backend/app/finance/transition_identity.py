"""Canonical bank money identity, shared by both formal routes.

Account codes are configured by finance, never supplied as an alternate domain
by a payment caller. A domain must have a complete legacy-money reconciliation
before the independent route can reserve any principal.
"""
from sqlalchemy import select
from app.core.config import get_settings
from app.commerce_transition import service as transition
from app.commerce_transition.models import BankAccountDomain, BankIdentity
from app.finance.models import BankAccount


def unmapped_legacy_money(db):
    """Weak old references freeze their possible account overlap as a domain.

Old Receipt rows often have no stable account at all. A complete-domain
checkbox cannot hide such rows; reconcile their canonical bank identities
first. A legacy batch maps the shared cash once, rather than once per order.
"""
    from app.receipt.models import Receipt
    from app.invoice.settlement_models import ReceiptBatch
    rows = db.scalars(select(Receipt).where((Receipt.source.is_(None) | (Receipt.source != 'local')), Receipt.amount > 0,
        (Receipt.collect_status == 1) | Receipt.sync_status.in_(['pending', 'syncing', 'synced', 'uncertain']))
        .with_for_update().execution_options(populate_existing=True)).all()
    batches = db.scalars(select(ReceiptBatch).where(ReceiptBatch.transaction_mode == 'legacy',
        ReceiptBatch.gross_amount > 0).with_for_update().execution_options(populate_existing=True)).all()
    references = set(db.scalars(select(BankIdentity.payment_ref).where(BankIdentity.route == 'legacy')
        .with_for_update()))
    missing = [f'legacy-batch:{row.id}' for row in batches if f'legacy-batch:{row.id}' not in references]
    missing += [f'legacy-receipt:{row.id}' for row in rows if
        (f'legacy-batch:{row.batch_id}' if row.batch_id else f'legacy-receipt:{row.id}') not in references]
    return sorted(set(missing))


def domain_for(db, account):
    settings = get_settings()
    domains = db.scalars(select(BankAccountDomain).where(
        BankAccountDomain.subject_key == settings.COMMERCE_RECEIVING_ENTITY_KEY,
        BankAccountDomain.channel == settings.COMMERCE_BANK_CHANNEL
    ).with_for_update().execution_options(populate_existing=True)).all()
    matches = [row for row in domains if account.id in (row.evidence or {}).get('bank_account_ids', [])]
    if len(matches) != 1:
        raise ValueError('收款账户域尚未核清旧款身份，不能登记独立收款')
    row = matches[0]
    if not row.legacy_identity_complete or not row.enforced or row.exclusive_route == 'legacy':
        raise ValueError('收款账户域旧款身份未核清或旧入口未受约束')
    if unmapped_legacy_money(db):
        raise ValueError('存在账户身份不明的旧款，可能重叠的收款账户域须先逐笔核清')
    return row


def reserve(db, account, reference, currency, amount, actor_id, *, payment_type):
    transition.require_phase(db, 'local')
    domain = domain_for(db, account)
    prior = db.scalar(select(BankIdentity).where(BankIdentity.domain_id == domain.id,
        BankIdentity.transaction_id == reference).with_for_update().execution_options(populate_existing=True))
    # Only a never-confirmed registration can release its reservation. Reuse
    # stays on the same route and retains every original assertion in evidence.
    if (prior is not None and prior.route == 'local' and prior.payment_ref is None
            and (prior.payer_evidence or {}).get('registration_reservation_released')):
        prior.currency, prior.amount = currency, amount
        prior.payer_evidence = {**prior.payer_evidence, 'registration_reservation_released': False,
            'bank_identity_verified': True, 'corrected_by': actor_id}
    return transition.claim_bank_identity(db, domain_id=domain.id,
        transaction_id=reference, route='local', currency=currency, amount=amount,
        payer_evidence={'bank_identity_verified': True, 'recorded_by': actor_id,
            'evidence_kind': 'finance_operator_bank_transaction_reference',
            'payment_type': payment_type, 'bank_account_code': account.code}).identity


def release_unconfirmed_registration(db, payment, event, actor_id):
    if payment.finance_status != 'registered' or payment.confirmed_at is not None:
        raise ValueError('已确认的真实银行款身份不可释放')
    identity = require_payment(db, payment)
    original = {'payment_ref': identity.payment_ref, 'currency': identity.currency,
        'amount': str(identity.amount), 'void_event_id': event.id, 'recorded_by': actor_id}
    identity.payer_evidence = {**identity.payer_evidence,
        'registration_reservation_released': True,
        'voided_registration_history': [*(identity.payer_evidence or {}).get('voided_registration_history', []), original]}
    identity.payment_ref = None
    db.flush()


def reconcile_legacy_identity(db, *, domain_id, transaction_id, receipt_id=None, batch_id=None,
                              statement_reference, actor_id):
    """An explicit finance reconciliation; no money row is created or changed."""
    from app.receipt.models import Receipt
    from app.invoice.settlement_models import ReceiptBatch
    transition.require_phase(db, 'legacy')
    if bool(receipt_id) == bool(batch_id) or not statement_reference.strip():
        raise ValueError('选择一份原银行款或原批次，并提供银行对账依据')
    model, identity = (ReceiptBatch, batch_id) if batch_id else (Receipt, receipt_id)
    original = db.scalar(select(model).where(model.id == identity).with_for_update().execution_options(populate_existing=True))
    if original is None or (batch_id and original.transaction_mode != 'legacy') or (
            receipt_id and (original.source == 'local' or original.batch_id is not None)):
        raise ValueError('必须选择原旧款；共享批次只能按完整原批次登记银行身份')
    settings = get_settings()
    domain = db.scalar(select(BankAccountDomain).where(BankAccountDomain.id == domain_id)
        .with_for_update().execution_options(populate_existing=True))
    account_ids = (domain.evidence or {}).get('bank_account_ids', []) if domain else []
    if (domain is None or domain.subject_key != settings.COMMERCE_RECEIVING_ENTITY_KEY
            or domain.channel != settings.COMMERCE_BANK_CHANNEL or not account_ids):
        raise ValueError('只能使用已关联真实银行账户的当前主体和渠道域')
    known_account = getattr(original, 'bank_account_id', None)
    if known_account is not None and known_account not in account_ids:
        raise ValueError('原批次已知银行账户与所选真实结算账户域不一致')
    accounts = db.scalars(select(BankAccount).where(BankAccount.id.in_(account_ids))
        .with_for_update().execution_options(populate_existing=True)).all()
    if len(accounts) != len(set(account_ids)) or original.currency not in {row.currency for row in accounts}:
        raise ValueError('账户域银行账户或原币不匹配')
    amount = original.gross_amount if batch_id else original.amount
    result = transition.claim_bank_identity(db, domain_id=domain_id, transaction_id=transaction_id,
        route='legacy', currency=original.currency, amount=amount, historical=True,
        payer_evidence={'bank_identity_verified': True, 'statement_reference': statement_reference,
                        'reconciled_by': actor_id, 'original_row_id': identity})
    reference = f'legacy-batch:{batch_id}' if batch_id else f'legacy-receipt:{receipt_id}'
    return transition.bind_bank_payment(db, result.identity.id, reference)


def require_payment(db, payment):
    transition.require_phase(db, 'local')
    if payment.finance_status == 'voided':
        return None  # Immutable replay; no operation may spend a voided row.
    account = db.scalar(select(BankAccount).where(BankAccount.id == payment.bank_account_id)
        .with_for_update().execution_options(populate_existing=True))
    if account is None:
        raise ValueError('原收款账户不存在，禁止扩大可用本金')
    domain = domain_for(db, account)
    row = db.scalar(select(BankIdentity).where(BankIdentity.domain_id == domain.id,
        BankIdentity.transaction_id == payment.bank_reference)
        .with_for_update().execution_options(populate_existing=True))
    if (row is None or row.route != 'local' or row.currency != payment.currency
            or row.amount != payment.gross_amount or row.payment_ref != f'local:{payment.id}'):
        raise ValueError('原收款的跨路线银行身份未核验或归属冲突')
    return row
