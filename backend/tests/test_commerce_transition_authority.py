"""Economic gates use real isolated SQLAlchemy sessions, never mocked cores."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.commerce_transition import service as s, transfer_service as transfers
from app.commerce_transition.models import (BankIdentity, ClaimEvidence, InvoiceAuthority,
    BankAccountDomain, PlatformPolicy, SendingClaim, WriterReceipt)
from app.core.database import Base
from app.core.time import beijing_now, beijing_today
from app.invoice.models import Invoice
# These production relationships are part of the closure being tested. Import
# their actual metadata before the isolated fixture creates its schema.
from app.production.local_models import ProductionSupply  # noqa: F401
from app.inventory import models as _inventory_models  # noqa: F401
from app.catalog import models as _catalog_models  # noqa: F401
from app.invoice.settlement_models import ReceiptBatch
from app.receipt.models import Receipt


def install(db, phase="transition"):
    current = db.get(PlatformPolicy, 1)
    if current is None:
        db.add(PlatformPolicy(id=1, phase="legacy_only", version=1, min_writer_version=1,
                               writer_inventory_verified=False, local_ever_effective=False))
    else:
        assert current.phase == "legacy_only", "Isolated fixture must start from the migration seed"
    db.flush()
    s.set_writer_receipt(db, "test-writer", 1, "compatible", {"enforced": True})
    if phase != "legacy_only":
        s.set_policy(db, phase=phase, expected_version=s.policy(db).version,
                      inventory_evidence={"all_writers": ["test-writer"]})


def invoice(db, suffix="A", route="legacy", confirmed=True):
    row = Invoice(invoice_no=f"transition-{suffix}", customer_id="test-customer",
        customer_name="Isolated customer", invoice_date=beijing_today(),
        transaction_mode=route, status="draft", commerce_status="draft", created_by=1)
    db.add(row)
    db.flush()
    s.ensure_authority(db, row, source_evidence={"new_draft": suffix}, route=route, confirmed=confirmed)
    return row


def verified_domain(db, complete=True):
    return s.register_bank_domain(db, subject_key="legal-company", account_key="bank-account",
        channel="bank-statement", legacy_identity_complete=complete, enforced=True,
        evidence={"statement_checkpoint": "isolated-01"})


def test_wrong_route_and_epoch_rejected_without_sending(db):
    install(db)
    row = invoice(db)
    with pytest.raises(s.TransitionError, match="办理权"):
        s.begin_send(db, row, "wrong", "outbound", {"quantity": 6}, 1, route="local")
    with pytest.raises(s.TransitionError, match="版本"):
        s.require_route(db, row, "legacy", 2)
    assert db.query(SendingClaim).count() == 0


def test_draft_route_changes_epoch_but_confirmed_route_cannot_change(db):
    install(db)
    row = invoice(db, confirmed=False)
    authority = s.set_draft_route(db, row, "local", 1, {"pilot": "explicit"})
    assert (authority.epoch, row.transaction_mode) == (2, "local")
    s.confirm_authority(db, row, "local", 2, {"contract": "confirmed"})
    with pytest.raises(s.TransitionError, match="已生效"):
        s.set_draft_route(db, row, "legacy", 2, {"attempt": "forbidden"})
    with pytest.raises(s.TransitionError, match="禁止退回"):
        s.set_policy(db, phase="legacy_only", expected_version=s.policy(db).version)


def test_claim_retry_same_identity_never_grants_another_send(db):
    install(db)
    row = invoice(db)
    first = s.begin_send(db, row, "request-one", "receipt", {"amount": "600.00"}, 1)
    again = s.begin_send(db, row, "request-one", "receipt", {"amount": "600.00"}, 1)
    assert first.created is True and again.created is False and first.claim.id == again.claim.id
    with pytest.raises(s.TransitionError, match="不同内容"):
        s.begin_send(db, row, "request-one", "receipt", {"amount": "601.00"}, 1)
    with pytest.raises(s.TransitionError, match="原请求"):
        s.begin_send(db, row, "request-two", "receipt", {"amount": "600.00"}, 1)


def test_expired_lease_unknown_and_late_result_keep_original_responsibility(db):
    install(db)
    row = invoice(db)
    result = s.begin_send(db, row, "original-request", "receipt", {"amount": "1000"}, 1,
                          lease_until=beijing_now().replace(year=2020))
    s.finish_send(db, result.claim.id, "unknown", {"timeout": True})
    frozen = transfers.prepare_transfer(db, invoice_ids=[row.id], target_route="local",
        request_key="transfer-unknown", checkpoint="consistent-checkpoint", evidence={"freeze": "requested"})
    assert frozen.state == "waiting"
    assert db.get(InvoiceAuthority, row.id).state == "frozen"
    with pytest.raises(s.TransitionError, match="未证明"):
        s.finish_send(db, result.claim.id, "not_sent", {"lease_expired": True})
    with pytest.raises(s.TransitionError, match="unknown"):
        transfers.complete_transfer(db, frozen.id, verification={part: "verified" for part in transfers.VERIFICATION_PARTS})
    s.finish_send(db, result.claim.id, "succeeded", {"original_request_readback": True}, external_id="remote-100")
    assert result.claim.external_id == "remote-100"
    assert db.query(ClaimEvidence).filter_by(claim_id=result.claim.id).count() == 2
    with pytest.raises(s.TransitionError, match="适配器"):
        transfers.complete_transfer(db, frozen.id, verification={part: "verified" for part in transfers.VERIFICATION_PARTS})
    assert s.begin_send(db, row, "original-request", "receipt", {"amount": "1000"}, 1).created is False


def test_original_receipt_unknown_blocks_transfer_without_new_claim_row(db):
    install(db)
    row = invoice(db)
    db.add(Receipt(receipt_no="legacy-unknown", invoice_id=row.id, source="manual",
        request_key="legacy-unknown", request_hash="a" * 64, amount=Decimal("1000"),
        currency="USD", collection_date=beijing_today(), payment_type="bank",
        customer_id="test-customer", sync_status="uncertain", created_by=1))
    db.flush()
    preparation = transfers.prepare_transfer(db, invoice_ids=[row.id], target_route="local",
        request_key="old-unknown-freeze", checkpoint="fixed", evidence={"original": "uncertain"})
    assert preparation.state == "waiting"
    assert db.get(InvoiceAuthority, row.id).state == "frozen"


def test_completed_transfer_keeps_late_original_claim_evidence(db):
    from app.invoice.models import InvoiceCommerceEvent
    install(db)
    row = invoice(db)
    claim = s.begin_send(db, row, "completed-send", "receipt", {"amount": "0"}, 1).claim
    s.finish_send(db, claim.id, "not_sent", {"definitive_original_request_result": True})
    preparation = transfers.prepare_transfer(db, invoice_ids=[row.id], target_route="local",
        request_key="complete", checkpoint="fixed", evidence={"empty_liability_inventory": "verified"})

    def empty_opening_receipt(db, prepared, verification):
        # A real local receipt for this synthetic contract with no ledger facts;
        # production uses the existing verified migration opening adapter.
        event = InvoiceCommerceEvent(invoice_id=row.id, request_key="opening-empty",
            request_hash=s.digest(verification), action="verified_empty_opening",
            payload={"preparation_id": prepared.id, "no_consumed_or_available_funds": True})
        db.add(event)
        db.flush()
        return {"invoice_commerce_event_id": event.id}

    transfers.complete_transfer(db, preparation.id,
        verification={part: "verified-empty" for part in transfers.VERIFICATION_PARTS},
        apply_opening=empty_opening_receipt)
    assert db.get(InvoiceAuthority, row.id).epoch == 2
    assert row.transaction_mode == "local"
    # A late repeat from epoch 1 is retained without granting another send.
    s.finish_send(db, claim.id, "not_sent", {"definitive_original_request_result": True, "late": True})
    assert db.query(ClaimEvidence).filter_by(claim_id=claim.id).count() == 2
    assert s.begin_send(db, row, "completed-send", "receipt", {"amount": "0"}, 1).created is False
    with pytest.raises(s.TransitionError, match="办理权"):
        s.require_route(db, row, "legacy", 1)
    s.finish_send(db, claim.id, "succeeded", {"late_conflicting_provider_success": True}, external_id="late-success")
    assert s.authority_view(db, row.id)["pending_claims"] == 1
    with pytest.raises(s.TransitionError, match="在途"):
        s.set_policy(db, phase="local_only", expected_version=s.policy(db).version)


@pytest.mark.parametrize("linked_state", ["running", "uncertain"])
def test_original_linked_worker_blocks_transfer_without_new_claim(db, linked_state):
    from app.invoice.models import InvoiceLinkedSync
    install(db)
    row = invoice(db)
    db.add(InvoiceLinkedSync(id="old-linked", invoice_id=row.id, request_key="old-linked",
        request_hash="a" * 64, status=linked_state, before={}, after={}, steps={}, created_by=1))
    db.flush()
    prepared = transfers.prepare_transfer(db, invoice_ids=[row.id], target_route="local",
        request_key="freeze-linked", checkpoint="fixed", evidence={"legacy_worker": linked_state})
    assert prepared.state == "waiting"
    with pytest.raises(s.TransitionError, match="unknown"):
        transfers.complete_transfer(db, prepared.id,
            verification={part: "verified" for part in transfers.VERIFICATION_PARTS})


def test_late_contradictory_terminal_evidence_is_retained_and_freezes(db):
    install(db)
    row = invoice(db)
    claim = s.begin_send(db, row, "late", "outbound", {}, 1).claim
    s.finish_send(db, claim.id, "not_sent", {"definitive_original_request_result": True})
    s.finish_send(db, claim.id, "succeeded", {"provider_callback": "late"}, external_id="late-remote")
    assert db.query(ClaimEvidence).filter_by(claim_id=claim.id).count() == 2
    assert db.get(InvoiceAuthority, row.id).state == "frozen"
    assert claim.state == "unknown"


def test_account_domain_legacy_unknown_blocks_all_new_local_money(db):
    install(db)
    domain = verified_domain(db, complete=False)
    with pytest.raises(s.TransitionError, match="旧款身份未核清"):
        s.claim_bank_identity(db, domain_id=domain.id, transaction_id="BANK-001", route="local",
            currency="USD", amount=Decimal("1000"), payer_evidence={"bank_identity_verified": True})
    assert db.query(BankIdentity).count() == 0


def test_same_bank_payment_cannot_create_cross_route_or_second_principal(db):
    install(db)
    domain = verified_domain(db)
    arguments = dict(domain_id=domain.id, transaction_id="BANK-001", route="legacy",
        currency="USD", amount=Decimal("1000.00"), payer_evidence={"bank_identity_verified": True})
    first = s.claim_bank_identity(db, **arguments)
    repeat = s.claim_bank_identity(db, **arguments)
    assert first.created and not repeat.created and first.identity.id == repeat.identity.id
    with pytest.raises(s.TransitionError, match="同一银行款"):
        s.claim_bank_identity(db, **{**arguments, "route": "local"})
    s.bind_bank_payment(db, first.identity.id, "legacy:payment-1")
    with pytest.raises(s.TransitionError, match="第二份"):
        s.bind_bank_payment(db, first.identity.id, "legacy:payment-2")
    assert db.query(BankIdentity).count() == 1


def test_original_payment_cannot_bind_a_second_canonical_bank_identity(db):
    install(db)
    domain = verified_domain(db)
    identities = [s.claim_bank_identity(db, domain_id=domain.id, transaction_id=key,
        route='legacy', currency='USD', amount=Decimal('1000'),
        payer_evidence={'bank_identity_verified': True}).identity for key in ('BANK-A', 'BANK-B')]
    s.bind_bank_payment(db, identities[0].id, 'legacy-receipt:42')
    with pytest.raises(s.TransitionError, match='原付款'):
        s.bind_bank_payment(db, identities[1].id, 'legacy-receipt:42')
    assert identities[1].payment_ref is None


def test_payment_a600_b400_requires_entire_closure(db):
    install(db)
    a, b = invoice(db, "A"), invoice(db, "B")
    transfers.register_responsibility(db, kind="payment", responsibility_key="P1000",
        members={a.id: Decimal("600"), b.id: Decimal("400")}, complete=True,
        evidence={"original_payment": "P1000", "checkpoint": "fixed"})
    with pytest.raises(s.TransitionError, match="整体冻结"):
        transfers.prepare_transfer(db, invoice_ids=[a.id], target_route="local", request_key="partial",
                                   checkpoint="fixed", evidence={"inventory": "complete"})
    assert db.get(InvoiceAuthority, a.id).state == "active"
    assert db.get(InvoiceAuthority, b.id).state == "active"
    prepared = transfers.prepare_transfer(db, invoice_ids=[a.id, b.id], target_route="local",
        request_key="entire", checkpoint="fixed", evidence={"inventory": "complete"})
    assert prepared.state == "ready"
    assert db.get(InvoiceAuthority, a.id).state == db.get(InvoiceAuthority, b.id).state == "frozen"
    with pytest.raises(s.TransitionError, match="冻结"):
        s.begin_send(db, a, "old-worker", "receipt", {}, 1)


def test_actual_receipt_ledger_detects_shared_payment_without_registered_group(db):
    install(db)
    a, b = invoice(db, "A"), invoice(db, "B")
    batch = ReceiptBatch(batch_no="P", customer_id="test-customer", currency="USD",
        gross_amount=Decimal("1000"), collection_date=beijing_today(), payment_type="bank",
        request_key="batch-P", request_hash="x" * 64, created_by=1)
    db.add(batch)
    db.flush()
    for row, amount in ((a, "600"), (b, "400")):
        db.add(Receipt(receipt_no=f"P-{row.id}", invoice_id=row.id, batch_id=batch.id,
            source="manual", request_key=f"receipt-{row.id}", request_hash="a" * 64,
            amount=Decimal(amount), currency="USD", collection_date=beijing_today(),
            payment_type="bank", customer_id="test-customer", created_by=1))
    db.flush()
    with pytest.raises(s.TransitionError, match="整体冻结"):
        transfers.prepare_transfer(db, invoice_ids=[a.id], target_route="local", request_key="hidden-B",
                                   checkpoint="fixed", evidence={"client_claim": "only-A"})
    assert db.get(InvoiceAuthority, a.id).state == "active"


def test_resource_scope_blocks_other_route_and_missing_mirror_dimension(db):
    install(db)
    evidence = {"checkpoint": "counted", "old_responsibilities_cleared": True, "writers_enforced": True}
    s.register_resource_scope(db, route="local", resource_kind="sku", resource_key="SKU1",
                              warehouse_key="warehouse-A", evidence=evidence)
    assert s.require_resource_scope(db, "local", "sku", "SKU1", "warehouse-A").route == "local"
    with pytest.raises(s.TransitionError, match="不归"):
        s.require_resource_scope(db, "legacy", "sku", "SKU1", "warehouse-A")
    with pytest.raises(s.TransitionError, match="维度"):
        s.require_resource_scope(db, "legacy", "sku", "SKU1")
    with pytest.raises(s.TransitionError, match="交叉"):
        s.register_resource_scope(db, route="legacy", resource_kind="sku", resource_key="SKU1",
                                  warehouse_key="*", evidence=evidence)


def test_new_unknown_writer_invalidates_readiness_and_local_gate(db):
    install(db)
    row = invoice(db, route="local")
    s.set_writer_receipt(db, "uncontrolled-script", 1, "unknown", {"discovered": "new"})
    with pytest.raises(s.TransitionError, match="writer"):
        s.require_route(db, row, "local", 1)


def test_missing_policy_fails_closed(db):
    db.query(PlatformPolicy).delete()  # Dedicated isolated fixture, simulating an uninstalled policy row.
    db.flush()
    with pytest.raises(s.TransitionError, match="未安装"):
        s.policy(db)


def test_full_local_cutover_defaults_new_unassigned_resources_to_local(db):
    install(db, phase="local_only")
    assert s.require_phase(db, "local").phase == "local_only"
    assert s.require_resource_scope(db, "local", "sku", "new-sku", "new-warehouse") is None
    evidence = {"checkpoint": "cutover", "old_responsibilities_cleared": True, "writers_enforced": True}
    scope = s.register_resource_scope(db, route="local", resource_kind="material", resource_key="M1",
                                      warehouse_key="*", evidence=evidence)
    scope.state = "frozen"
    db.flush()
    with pytest.raises(s.TransitionError, match="冻结"):
        s.require_resource_scope(db, "local", "material", "M1", "new-warehouse")
    with pytest.raises(s.TransitionError, match="平台阶段"):
        s.require_phase(db, "legacy")


def test_transition_unassigned_resource_still_requires_explicit_exclusion(db):
    install(db)
    with pytest.raises(s.TransitionError, match="排他核验"):
        s.require_resource_scope(db, "local", "sku", "new-sku", "warehouse")


@pytest.fixture
def concurrent_db(tmp_path):
    # Independent connections to a dedicated file DB exercise actual concurrent
    # transactions. This proves coordination behavior on SQLite, not InnoDB.
    engine = create_engine(f"sqlite:///{tmp_path / 'authority.sqlite'}", connect_args={"timeout": 10})
    tables = [table for table in Base.metadata.tables.values()
              if table.name.startswith("ark_commerce_") and table.name not in {
                  "ark_commerce_migration_batches", "ark_commerce_migration_records"}]
    Invoice.__table__.create(engine)
    Base.metadata.create_all(engine, tables=tables)
    for table in (ReceiptBatch.__table__, Receipt.__table__, ProductionSupply.__table__,
                  _inventory_models.StockDocument.__table__, _catalog_models.CatalogSku.__table__):
        table.create(engine, checkfirst=True)
    from app.invoice.models import InvoiceItem
    from app.invoice.models import InvoiceLinkedSync, OkkiOutboundTask
    from app.stock.models import ProductionOrderItem
    InvoiceItem.__table__.create(engine, checkfirst=True)
    OkkiOutboundTask.__table__.create(engine, checkfirst=True)
    InvoiceLinkedSync.__table__.create(engine, checkfirst=True)
    ProductionOrderItem.__table__.create(engine, checkfirst=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as seed:
        install(seed)
        row = invoice(seed)
        row_id = row.id
        seed.commit()
    try:
        yield sessions, row_id
    finally:
        engine.dispose()


def test_send_and_freeze_share_real_sqlite_transaction_lock(concurrent_db):
    sessions, row_id = concurrent_db
    claimed, freeze_started = threading.Event(), threading.Event()

    def worker():
        with sessions() as db:
            claim = s.begin_send(db, row_id, "concurrent-send", "receipt", {"amount": "600"}, 1)
            claimed.set()
            assert freeze_started.wait(5)
            db.commit()
            return claim.claim.id

    def freeze():
        assert claimed.wait(5)
        freeze_started.set()
        with sessions() as db:
            preparation = transfers.prepare_transfer(db, invoice_ids=[row_id], target_route="local",
                request_key="concurrent-freeze", checkpoint="fixed", evidence={"readback": "pending"})
            db.commit()
            return preparation.state

    with ThreadPoolExecutor(max_workers=2) as executor:
        sending, freezing = executor.submit(worker), executor.submit(freeze)
        assert sending.result(timeout=15) > 0
        assert freezing.result(timeout=15) == "waiting"
    with sessions() as verify:
        assert verify.get(InvoiceAuthority, row_id).state == "frozen"
        assert verify.query(SendingClaim).count() == 1


def test_freeze_wins_before_paused_worker_can_claim(concurrent_db):
    sessions, row_id = concurrent_db
    frozen, worker_started = threading.Event(), threading.Event()

    def freeze():
        with sessions() as db:
            preparation = transfers.prepare_transfer(db, invoice_ids=[row_id], target_route="local",
                request_key="freeze-first", checkpoint="fixed", evidence={"no_previous_send": True})
            frozen.set()
            assert worker_started.wait(5)
            db.commit()
            return preparation.state

    def worker():
        assert frozen.wait(5)
        worker_started.set()
        with sessions() as db:
            with pytest.raises(s.TransitionError, match="冻结"):
                s.begin_send(db, row_id, "too-late-worker", "outbound", {}, 1)
            db.rollback()

    with ThreadPoolExecutor(max_workers=2) as executor:
        freezing, sending = executor.submit(freeze), executor.submit(worker)
        assert freezing.result(timeout=15) == "ready"
        sending.result(timeout=15)
    with sessions() as verify:
        assert verify.query(SendingClaim).count() == 0
        assert verify.get(InvoiceAuthority, row_id).state == "frozen"


def test_concurrent_duplicate_claim_has_only_one_send_permission(concurrent_db):
    sessions, row_id = concurrent_db
    start = threading.Barrier(2)

    def claim():
        start.wait(timeout=5)
        with sessions() as db:
            result = s.begin_send(db, row_id, "same-request", "receipt", {"amount": "600"}, 1)
            db.commit()
            return result.created, result.claim.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: claim(), range(2)))
    assert sorted(result[0] for result in results) == [False, True]
    assert results[0][1] == results[1][1]


def test_stale_session_claim_cannot_overwrite_committed_terminal_result(concurrent_db):
    sessions, row_id = concurrent_db
    with sessions() as seed:
        claim_id = s.begin_send(seed, row_id, "stale-finish", "receipt", {}, 1).claim.id
        seed.commit()
    with sessions() as stale, sessions() as other:
        cached = stale.get(SendingClaim, claim_id)
        assert cached.state == "sending"
        s.finish_send(other, claim_id, "failed", {"definitive_original_request_result": True})
        other.commit()
        assert cached.state == "sending"  # Prove this session still holds the old object.
        s.finish_send(stale, claim_id, "succeeded", {"callback": "contradiction"}, external_id="conflicting-success")
        stale.commit()
    with sessions() as verify:
        assert verify.get(SendingClaim, claim_id).state == "unknown"
        assert verify.get(InvoiceAuthority, row_id).state == "frozen"
        assert verify.query(ClaimEvidence).filter_by(claim_id=claim_id).count() == 2


def test_stale_session_writer_receipt_does_not_allow_revoked_readiness(concurrent_db):
    sessions, row_id = concurrent_db
    with sessions() as stale, sessions() as other:
        cached = stale.get(WriterReceipt, "test-writer")
        assert cached.state == "compatible"
        s.set_writer_receipt(other, "test-writer", 1, "unknown", {"lost_enforcement": True})
        other.commit()
        with pytest.raises(s.TransitionError, match="writer"):
            s.require_route(stale, row_id, "local", 1)


def test_stale_bank_domain_and_bound_payment_cannot_create_principal(concurrent_db):
    sessions, _row_id = concurrent_db
    with sessions() as seed:
        domain_id = verified_domain(seed).id
        identity_id = s.claim_bank_identity(seed, domain_id=domain_id, transaction_id="stale-bank",
            route="legacy", currency="USD", amount=Decimal("1000"),
            payer_evidence={"bank_identity_verified": True}).identity.id
        seed.commit()
    with sessions() as stale, sessions() as other:
        cached_domain = stale.get(BankAccountDomain, domain_id)
        cached_payment = stale.get(BankIdentity, identity_id)
        assert cached_domain.legacy_identity_complete and cached_payment.payment_ref is None
        verified_domain(other, complete=False)
        s.bind_bank_payment(other, identity_id, "legacy:first-payment")
        other.commit()
        with pytest.raises(s.TransitionError, match="旧款身份未核清"):
            s.claim_bank_identity(stale, domain_id=domain_id, transaction_id="new-local",
                route="local", currency="USD", amount=Decimal("1000"),
                payer_evidence={"bank_identity_verified": True})
        with pytest.raises(s.TransitionError, match="第二份"):
            s.bind_bank_payment(stale, identity_id, "legacy:second-payment")
