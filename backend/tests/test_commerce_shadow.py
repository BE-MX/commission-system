"""Real isolated domain replay and immutable non-economic evidence."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.core.database import Base
from app.commerce_shadow import service, worker
from app.commerce_shadow.models import (ShadowObservation, ShadowOutbox, ShadowDataset, ShadowRun,
    ShadowResult, ShadowDifference, ShadowReview, ShadowExecution, ShadowBinding)
from app.commerce_shadow.schemas import ReplayRequest, ReviewRequest
from app.invoice.models import Invoice, InvoiceCommerceEvent
from app.finance.models import FinanceEvent, BankAccount, Currency
from app.invoice.settlement_models import ReceiptBatch, Receivable
from app.receipt.models import Receipt
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer, draft
from tests.test_finance_local import finance, payment


@pytest.fixture
def isolated(db, finance, stock, tmp_path):
    customer, user, bank = finance
    from app.core.config import get_settings
    from app.commerce_transition.models import BankAccountDomain
    settings = get_settings()
    domain = db.scalar(select(BankAccountDomain).where(BankAccountDomain.account_key == bank.code,
        BankAccountDomain.subject_key == settings.COMMERCE_RECEIVING_ENTITY_KEY,
        BankAccountDomain.channel == settings.COMMERCE_BANK_CHANNEL))
    if domain is None:
        domain = BankAccountDomain(subject_key=settings.COMMERCE_RECEIVING_ENTITY_KEY, account_key=bank.code,
            channel=settings.COMMERCE_BANK_CHANNEL, legacy_identity_complete=True, enforced=True, exclusive_route="local",
            evidence={"isolated_fixture": "empty account domain; no legacy principal or writers", "bank_account_ids": [bank.id]})
        db.add(domain)
        db.flush()
    engine = create_engine("sqlite:///" + (tmp_path / "candidate.sqlite").as_posix(), hide_parameters=True)
    Base.metadata.create_all(engine)
    # Reference inputs only. No source invoices/events/receipts/ledger/results.
    from app.auth.models import ArkUser
    from app.customer.models import CustomerAccount
    from app.catalog.models import CatalogSku, CatalogProduct
    from app.inventory.models import Warehouse
    with Session(engine) as target:
        for model in (ArkUser, CustomerAccount, CatalogProduct, CatalogSku, Warehouse, Currency, BankAccount, BankAccountDomain):
            for row in db.scalars(select(model)).unique():
                target.add(model(**{column.key: getattr(row, column.key) for column in model.__table__.columns}))
        target.commit()
    invoice = Invoice(id=901, invoice_no="SOURCE-ONLY", created_by=int(user["sub"]), sales_user_id=int(user["sub"]),
                      transaction_mode="legacy", commerce_status="draft", currency="USD", customer_id="source-customer",
                      customer_name="Source buyer", invoice_date=date(2026, 10, 3))
    db.add(invoice)
    db.flush()
    checkpoint = dict(complete=True, invoice_ids=[invoice.id], dependencies=[], watermarks={},
                      through_observation_id=0, initial_state_verified=True, evidence="zero economic opening; reference inputs verified",
                      bank_domains=[dict(subject_key=domain.subject_key, account_key=domain.account_key, channel=domain.channel,
                          legacy_identity_complete=True, enforced=True, exclusive_route="local", evidence_hash=service.digest(domain.evidence))])
    dataset = service.create_dataset(db, dataset_id="dataset-1", checkpoint=checkpoint,
        target_fingerprint=worker.target_fingerprint(engine), actor_id=int(user["sub"]))
    db.commit()
    yield engine, dataset, invoice, user
    engine.dispose()


def observe(db, isolated, action="payment.register", *, event="source-1", sequence=1,
            body=None, target_id=None, outcome="accepted", expected=None, dependencies=(), reason=None, **changes):
    _, _, invoice, user = isolated
    command_body = dict(body or {})
    command_body.setdefault("request_key", event)
    command = dict(body=command_body, actor=user)
    if target_id is not None:
        command["target_id"] = target_id
    return service.record_observation(db, source_event_id=event, invoice_id=invoice.id, action=action,
        request_key=event, command=command, outcome=outcome, result=expected or {}, contract_revision=1,
        causal_version=sequence, dependencies=list(dependencies), actor_id=int(user["sub"]), reason_code=reason, **changes)


def run(db, isolated, *, key="run-1", through=None):
    engine, dataset, invoice, user = isolated
    through = through or db.scalar(select(func.max(ShadowObservation.id)))
    row = service.request_run(db, ReplayRequest(dataset_id=dataset.id, request_key=key,
        invoice_ids=[invoice.id], through_observation_id=through), user)
    db.commit()
    worker.run_replay(db, row.id, engine)
    db.commit()
    return row


def test_atomic_observation_outbox_rollback_and_immutable_evidence(db, isolated):
    first = observe(db, isolated, expected={"gross_amount": "1000"})
    identity = first.id
    db.rollback()
    assert db.get(ShadowObservation, identity) is None
    assert not db.scalars(select(ShadowOutbox)).all()
    row = observe(db, isolated, outcome="rejected", reason="invalid_business_date")
    db.commit()
    assert db.scalar(select(func.count()).select_from(FinanceEvent)) == 0
    assert db.scalar(select(func.count()).select_from(ShadowOutbox)) == 1
    assert observe(db, isolated, outcome="rejected", reason="invalid_business_date").id == row.id
    with pytest.raises(ValueError, match="不同命令"):
        observe(db, isolated, outcome="accepted")
    row.result = {"fake": "replacement"}
    with pytest.raises(ValueError, match="不可修改"):
        db.flush()
    db.rollback()


def test_real_payment_execution_has_independent_identity_and_reopen_retry(db, isolated, finance):
    engine, _, _, _ = isolated
    customer, _, bank = finance
    body = payment(customer, bank).model_dump(mode="json")
    observe(db, isolated, body=body, expected={"gross_amount": "1000.00", "net_amount": "980.00", "finance_status": "registered"})
    row = run(db, isolated)
    assert row.status == "consistent", row.coverage
    with Session(engine) as target:
        payment_row = target.scalar(select(ReceiptBatch))
        event = target.scalar(select(FinanceEvent))
        receipt = target.scalar(select(ShadowExecution))
        assert payment_row.gross_amount == Decimal(1000)
        assert event.request_key.startswith("shadow:") and event.request_key != "shadow:" + receipt.id
        assert event.request_key != "source-1"
        assert receipt.first_run_id == row.id
        assert receipt.actual["invariants"]["passed"] is True
    engine.dispose()
    reopened = create_engine(engine.url, hide_parameters=True)
    newer = service.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="after-restart",
        invoice_ids=[901], through_observation_id=1), isolated[3])
    db.commit()
    worker.run_replay(db, newer.id, reopened)
    db.commit()
    with Session(reopened) as target:
        assert target.scalar(select(func.count()).select_from(ReceiptBatch)) == 1
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 1
        assert target.scalar(select(func.count()).select_from(ShadowExecution)) == 1
    assert newer.status == "consistent"
    reopened.dispose()


def test_false_formal_rejection_executes_candidate_and_records_difference(db, isolated, finance):
    customer, _, bank = finance
    observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), outcome="rejected",
            reason="source_wrongly_rejected")
    row = run(db, isolated)
    assert row.status == "differences"
    diff = db.scalar(select(ShadowDifference))
    assert (diff.field, diff.expected, diff.actual) == ("outcome", {"value": "rejected"}, {"value": "accepted"})
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(ReceiptBatch)) == 1
    assert db.scalar(select(func.count()).select_from(ReceiptBatch)) == 0


def test_actual_business_rejection_rolls_back_candidate_economic_claim(db, isolated, finance):
    customer, _, bank = finance
    body = payment(customer, bank, collection_date=date(2099, 1, 1)).model_dump(mode="json")
    observe(db, isolated, body=body, outcome="rejected", reason="不能使用未来记账日期")
    row = run(db, isolated)
    assert row.status == "consistent", row.coverage
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 0
        assert target.scalar(select(func.count()).select_from(ReceiptBatch)) == 0
        assert target.scalar(select(ShadowExecution)).outcome == "rejected"


@pytest.mark.parametrize("kind", ["missing_dependency", "version_gap", "unknown", "unsupported"])
def test_incomplete_or_unsupported_can_never_be_consistent(db, isolated, finance, kind):
    customer, _, bank = finance
    arguments = dict(body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1000"})
    if kind == "missing_dependency":
        arguments["dependencies"] = ["absent-cross-order-payment"]
    elif kind == "version_gap":
        arguments["sequence"] = 2
    elif kind == "unknown":
        arguments["outcome"] = "unknown"
    else:
        arguments["action"] = "unobserved.remote_manual_change"
    observe(db, isolated, **arguments)
    row = run(db, isolated)
    assert row.status == "incomplete"
    assert row.coverage["missing_dependencies"]
    assert db.scalar(select(ShadowOutbox)).state == "pending"
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 0


def test_formal_result_not_seeded_and_numerical_difference_survives_review(db, isolated, finance):
    customer, _, bank = finance
    observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1001"})
    row = run(db, isolated)
    assert row.status == "differences"
    diff = db.scalar(select(ShadowDifference))
    service.review_difference(db, diff.id, ReviewRequest(classification="explained", evidence="source receipt verified 1000; source comparison snapshot corrected separately"), isolated[3])
    db.commit()
    assert diff.expected == {"value": "1001"}
    assert Decimal(diff.actual["value"]) == Decimal("1000.00")
    assert row.status == "differences"
    assert db.scalar(select(ShadowReview)).actor_id == int(isolated[3]["sub"])


def test_target_down_retains_outbox_and_recovery_reads_actual_receipt(db, isolated, finance):
    customer, _, bank = finance
    observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1000"})
    # Target data change commits, but source report ACK transaction is lost.
    engine, dataset, _, user = isolated
    row = service.request_run(db, ReplayRequest(dataset_id=dataset.id, request_key="lost-ack", invoice_ids=[901], through_observation_id=1), user)
    db.commit()
    worker.run_replay(db, row.id, engine)
    db.rollback()
    assert db.scalar(select(ShadowOutbox)).state == "pending"
    assert not db.scalars(select(ShadowResult)).all()
    worker.run_replay(db, row.id, engine)
    db.commit()
    assert row.status == "consistent"
    with Session(engine) as target:
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 1


def test_isolation_blocks_same_database_capabilities_and_dataset_reuse(db, isolated):
    engine, dataset, _, _ = isolated
    with pytest.raises(worker.IsolationError, match="不能与"):
        worker.assert_isolated(engine, create_engine(engine.url))
    with pytest.raises(worker.IsolationError, match="不得持有"):
        worker.assert_isolated(db.get_bind(), engine, runtime_capabilities=["real_scan"])
    with Session(engine) as target:
        worker.bind_target(target, dataset)
        target.commit()
        fake = ShadowDataset(id="other", checkpoint_hash=dataset.checkpoint_hash)
        with pytest.raises(worker.IsolationError, match="其他数据集"):
            worker.bind_target(target, fake)


def test_float_credentials_and_real_media_not_exportable(db, isolated):
    for value in ({"gross_amount": 1.25}, {"token": "production"}, {"attachment_ids": ["real-proof"]}):
        with pytest.raises(ValueError):
            observe(db, isolated, body=value)
    assert not db.scalars(select(ShadowObservation)).all()


def test_contract_cash_allocation_reversal_shipment_execute_actual_domains(db, isolated, finance, stock):
    customer, user, bank = finance
    sku, warehouses = stock
    ref = lambda event, field="id": {"$ref": event, "field": field}
    body = draft(customer, user, sku, order_type="production", shipping_fee=0, surcharge_amount=0,
                 items=[dict(local_sku_id=sku.id, quantity=10, price_per_piece="100")]).model_dump(mode="json")
    observe(db, isolated, action="contract.create", event="create", body=body,
            expected={"total_amount": "1000", "commerce_status": "draft"})
    observe(db, isolated, action="contract.confirm", event="confirm-order", sequence=2, target_id=ref("create"),
            body={"expected_version": 1, "reason": "verified", "warehouse_id": None}, dependencies=["create"],
            expected={"commerce_status": "confirmed", "commerce_version": 2})
    observe(db, isolated, event="pay", sequence=3, body=payment(customer, bank).model_dump(mode="json"),
            dependencies=["confirm-order"], expected={"gross_amount": "1000", "finance_status": "registered"})
    observe(db, isolated, action="payment.confirm", event="pay-confirm", sequence=4, target_id=ref("pay"),
            body={"expected_version": 1, "business_date": "2026-10-03", "reason": "verified"}, dependencies=["pay"],
            expected={"finance_status": "confirmed", "available_amount": "1000"})
    observe(db, isolated, action="allocation.create", event="allocate", sequence=5, target_id=ref("pay"),
            body={"expected_version": 2, "invoice_id": ref("create"), "receivable_id": ref("confirm-order", "receivable_id"),
                  "amount": "600", "business_date": "2026-10-03"}, dependencies=["pay-confirm", "confirm-order"],
            expected={"amount": "600", "status": "active"})
    observe(db, isolated, action="allocation.reverse", event="reverse", sequence=6, target_id=ref("allocate"),
            body={"expected_version": 1, "amount": "100", "business_date": "2026-10-03", "reason": "verified"},
            dependencies=["allocate"], expected={"reversed_amount": "100"})
    observe(db, isolated, action="payment.refund", event="refund", sequence=7, target_id=ref("pay"),
            body={"expected_version": 4, "amount": "500", "business_date": "2026-10-03", "reason": "verified", "bank_reference": "REFUND-1"},
            dependencies=["reverse"], expected={"allocated_amount": "500", "refunded_amount": "500", "available_amount": "0"})
    observe(db, isolated, action="shipment.create", event="shipment", sequence=8, target_id=ref("create"),
            body={"expected_version": 2, "business_date": "2026-10-03", "warehouse_id": warehouses[0].id,
                "freight_amount": "0", "items": [{"invoice_item_id": ref("create", "item_0"), "quantity": 5}]},
            dependencies=["refund", "confirm-order"], expected={"state": "awaiting_payment", "goods_amount": "500"})
    observe(db, isolated, action="shipment.ready", event="ready", sequence=9, target_id=ref("shipment"),
            body={"expected_version": 1, "business_date": "2026-10-03", "reason": "verified"}, dependencies=["shipment"],
            expected={"state": "ready"})
    observe(db, isolated, action="shipment.dispatch", event="dispatch", sequence=10, target_id=ref("shipment"),
            body={"expected_version": 2, "business_date": "2026-10-03", "reason": "verified", "inspection_version": 1},
            dependencies=["ready"], outcome="rejected", reason="请完成当前出库明细的发货检验并刷新版本")
    observe(db, isolated, action="shipment.cancel", event="cancel-shipment", sequence=11, target_id=ref("shipment"),
            body={"expected_version": 2, "business_date": "2026-10-03", "reason": "verified"}, dependencies=["dispatch"],
            expected={"state": "cancelled"})
    row = run(db, isolated)
    assert row.status == "consistent", (row.coverage, [(diff.field, diff.expected, diff.actual) for diff in db.scalars(select(ShadowDifference))])
    with Session(isolated[0]) as target:
        invoice = target.scalar(select(Invoice))
        assert invoice.id != 901 and invoice.total_amount == Decimal(1000)
        assert invoice.internal_received == Decimal(500)
        batch = target.scalar(select(ReceiptBatch))
        assert batch.allocated_amount == batch.refunded_amount == 500
        assert target.scalar(select(Receipt)).reversed_amount == 100
        assert target.scalar(select(func.count()).select_from(ShadowExecution)) == 11
    assert db.scalar(select(func.count()).select_from(FinanceEvent)) == 0


def test_process_boundary_exports_no_expected_result_and_candidate_needs_no_source_session(db, isolated, finance):
    from app.commerce_shadow.transport import export_input_bundle, execute_input_bundle, import_execution_receipts
    customer, _, bank = finance
    observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1001"})
    row = service.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="process-boundary", invoice_ids=[901], through_observation_id=1), isolated[3])
    db.commit()
    bundle = export_input_bundle(db, row.id)
    assert "result" not in bundle["commands"][0]
    assert "outcome" not in bundle["commands"][0]
    assert "1001" not in str(bundle)
    report = execute_input_bundle(isolated[0], bundle)
    assert Decimal(report["results"][0]["actual"]["metrics"]["gross_amount"]) == Decimal("1000.00")
    import_execution_receipts(db, bundle, report)
    db.commit()
    assert row.status == "differences"
    import_execution_receipts(db, bundle, report)
    db.commit()
    assert db.scalar(select(func.count()).select_from(ShadowResult)) == 1
    assert db.scalar(select(func.count()).select_from(ShadowDifference)) == 1
    changed_outcome = {**report, "results": [{**report["results"][0], "candidate_outcome": "rejected"}]}
    with pytest.raises(worker.IsolationError, match="回执变化"):
        import_execution_receipts(db, bundle, changed_outcome)
    db.rollback()
    duplicated = {**report, "results": report["results"] * 2}
    with pytest.raises(worker.IsolationError, match="重复"):
        import_execution_receipts(db, bundle, duplicated)
    db.rollback()


def test_unknown_terminal_resolution_keeps_evidence_and_executes_only_once(db, isolated, finance):
    customer, _, bank = finance
    original = observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), outcome="unknown")
    db.commit()
    first = run(db, isolated)
    assert first.status == "incomplete"
    resolution = service.resolve_observation(db, unknown_source_event_id=original.source_event_id, outcome="accepted",
        result={"gross_amount": "1000"}, evidence_ref={"terminal_readback_ref": "original-claim/1/readback/1"},
        actor_id=int(isolated[3]["sub"]))
    assert resolution.command == original.command
    assert original.outcome == "unknown"
    assert service.resolve_observation(db, unknown_source_event_id=original.source_event_id, outcome="accepted",
        result={"gross_amount": "1000"}, evidence_ref={"terminal_readback_ref": "original-claim/1/readback/1"},
        actor_id=int(isolated[3]["sub"])).id == resolution.id
    with pytest.raises(ValueError, match="不同终局"):
        service.resolve_observation(db, unknown_source_event_id=original.source_event_id, outcome="accepted",
            result={"gross_amount": "2000"}, evidence_ref={"terminal_readback_ref": "original-claim/1/readback/1"},
            actor_id=int(isolated[3]["sub"]))
    row = run(db, isolated, key="resolved-run", through=resolution.id)
    assert row.status == "consistent", row.coverage
    assert row.coverage["resolved_unknown"] == [original.source_event_id]
    assert db.scalar(select(ShadowResult).where(ShadowResult.observation_id == original.id)).status == "resolved"
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 1
        assert target.scalar(select(func.count()).select_from(ReceiptBatch)) == 1
        receipts = target.scalars(select(ShadowExecution).order_by(ShadowExecution.causal_version)).all()
        assert receipts[0].outcome == "resolved_unknown"
        assert receipts[0].actual["economic_execution"] is False
        assert receipts[1].outcome == "accepted"


def test_unallocated_prepayment_replays_without_any_invoice_identity(db, isolated, finance):
    from app.finance import service as finance_service
    from app.commerce_shadow.transport import export_input_bundle
    customer, user, bank = finance
    source_payment = finance_service.register(db, payment(customer, bank), user)
    observation = service.record_observation(db, source_event_id="prepayment", invoice_id=None,
        local_customer_id=customer.id, payment_id=source_payment.id, action="payment.register", request_key="prepayment",
        command={"body": payment(customer, bank).model_dump(mode="json"), "actor": user}, outcome="accepted",
        result={"gross_amount": "1000", "finance_status": "registered"}, contract_revision=1, causal_version=1,
        dependencies=[], actor_id=int(user["sub"]))
    checkpoint = dict(complete=True, invoice_ids=[], payment_ids=[source_payment.id], dependencies=[], watermarks={},
        through_observation_id=0, initial_state_verified=True, evidence="unallocated payment; no invoice exists",
        bank_domains=isolated[1].checkpoint["bank_domains"])
    service.create_dataset(db, dataset_id="prepayment-only", checkpoint=checkpoint,
        target_fingerprint=worker.target_fingerprint(isolated[0]), actor_id=int(user["sub"]))
    row = service.request_run(db, ReplayRequest(dataset_id="prepayment-only", request_key="prepayment-run",
        invoice_ids=[], payment_ids=[source_payment.id], through_observation_id=observation.id), user)
    db.commit()
    bundle = export_input_bundle(db, row.id)
    assert len(bundle["commands"]) == 1 and not bundle["missing_dependencies"]
    worker.run_replay(db, row.id, isolated[0])
    db.commit()
    assert row.status == "consistent", row.coverage
    assert observation.invoice_id is None
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(Invoice)) == 0
        assert target.scalar(select(ReceiptBatch)).gross_amount == Decimal(1000)


def test_payment_ancestor_is_collected_and_real_shared_payment_missing_order_is_incomplete(db, isolated, finance):
    from app.finance import service as finance_service
    from app.commerce_shadow.transport import export_input_bundle
    customer, user, bank = finance
    source_payment = finance_service.register(db, payment(customer, bank), user)
    parent = service.record_observation(db, source_event_id="pure-prepayment", invoice_id=None,
        local_customer_id=customer.id, payment_id=source_payment.id, action="payment.register", request_key="prepayment",
        command={"body": payment(customer, bank).model_dump(mode="json"), "actor": user}, outcome="accepted",
        result={"gross_amount": "1000"}, contract_revision=1, causal_version=1, dependencies=[], actor_id=int(user["sub"]))
    db.add(Invoice(id=902, invoice_no="SHARED-ORDER-B", customer_id="source-customer", customer_name="Source buyer",
        invoice_date=date(2026, 10, 3), created_by=int(user["sub"]), sales_user_id=int(user["sub"]), currency="USD"))
    for identity, amount in ((901, 600), (902, 400)):
        db.add(Receipt(receipt_no=f"SHARED-{identity}", invoice_id=identity, batch_id=source_payment.id, source="local", amount=amount,
            bank_charge=0, currency="USD", collection_date=date(2026, 10, 3), payment_type="bank_transfer",
            customer_id=f"ark:{customer.id}", request_key=f"shared-{identity}", request_hash="a" * 64,
            created_by=int(user["sub"])))
    child = observe(db, isolated, action="allocation.create", event="allocation-a", sequence=1,
        target_id={"$ref": parent.source_event_id, "field": "id"}, expected={"amount": "600"},
        aggregate_key="invoice:901")
    db.commit()
    row = service.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="incomplete-shared",
        invoice_ids=[901], through_observation_id=child.id), user)
    db.commit()
    bundle = export_input_bundle(db, row.id)
    assert {command["source_event_id"] for command in bundle["commands"]} == {parent.source_event_id, child.source_event_id}
    assert "incomplete_cross_order_closure" in bundle["missing_dependencies"]
    worker.run_replay(db, row.id, isolated[0])
    db.commit()
    assert row.status == "incomplete"
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(FinanceEvent)) == 0


def test_unmapped_raw_business_identity_never_falls_through_to_same_numeric_candidate_id(db, isolated):
    observe(db, isolated, action="contract.confirm", target_id=1, body={"expected_version": 1, "reason": "test"},
            expected={"commerce_status": "confirmed"})
    row = run(db, isolated)
    assert row.status == "incomplete"
    assert any("unmapped_source_business_identity" in value for value in row.coverage["missing_dependencies"])


def test_actual_target_connection_failure_keeps_pending_outbox(db, isolated, finance):
    customer, _, bank = finance
    observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1000"})
    ShadowExecution.__table__.drop(isolated[0])
    row = run(db, isolated)
    assert row.status == "incomplete"
    assert any("target_unavailable" in value for value in row.coverage["missing_dependencies"])
    assert db.scalar(select(ShadowOutbox)).state == "pending"


@pytest.mark.parametrize("host_offset", [0, -7])
def test_new_audit_times_use_beijing_midnight_on_non_beijing_hosts(db, isolated, finance, monkeypatch, host_offset):
    from app.core import time as business_time
    instant = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            # A call without a business timezone would get the previous day.
            return instant.astimezone(tz or timezone(timedelta(hours=host_offset)))

    monkeypatch.setattr(business_time, "datetime", Clock)
    customer, _, bank = finance
    observation = observe(db, isolated, body=payment(customer, bank).model_dump(mode="json"), expected={"gross_amount": "1001"})
    row = run(db, isolated)
    diff = db.scalar(select(ShadowDifference))
    service.review_difference(db, diff.id, ReviewRequest(classification="explained", evidence="verified source snapshot differs from original input"), isolated[3])
    db.commit()
    midnight = datetime(2026, 10, 28, 0, 0, 0)
    assert observation.observed_at == row.created_at == row.checked_at == midnight
    assert db.scalar(select(ShadowResult)).checked_at == diff.created_at == midnight
    assert db.scalar(select(ShadowReview)).reviewed_at == midnight
    with Session(isolated[0]) as target:
        assert target.scalar(select(ShadowExecution)).completed_at == midnight


def test_initial_stock_checkpoint_requires_exact_physical_baseline(db, isolated, stock):
    from app.inventory.models import StockBalance
    from app.commerce_shadow.dispatcher import verify_conservation
    engine, dataset, _, user = isolated
    sku, warehouses = stock
    with Session(engine) as target:
        target.add(StockBalance(warehouse_id=warehouses[0].id, sku_id=sku.id, quality="sellable", on_hand=10, reserved=0))
        target.commit()
        with pytest.raises(worker.IsolationError, match="初始责任不守恒"):
            worker.bind_target(target, dataset)
        target.rollback()
    checkpoint = {**dataset.checkpoint, "initial_stock": [{"warehouse_id": warehouses[0].id, "sku_id": sku.id,
        "quality": "sellable", "on_hand": 10, "reserved": 0}]}
    verified = service.create_dataset(db, dataset_id="counted-stock", checkpoint=checkpoint,
        target_fingerprint=worker.target_fingerprint(engine), actor_id=int(user["sub"]))
    db.commit()
    with Session(engine) as target:
        worker.bind_target(target, verified)
        target.commit()
        assert verify_conservation(target, checkpoint=checkpoint)["passed"] is True
        target.scalar(select(StockBalance)).on_hand = 9
        target.flush()
        assert verify_conservation(target, checkpoint=checkpoint)["passed"] is False
    with pytest.raises(ValueError, match="非零检查点"):
        service.create_dataset(db, dataset_id="missing-revisions", checkpoint={**checkpoint, "watermarks": {"invoice:901": 1}},
            target_fingerprint=worker.target_fingerprint(engine), actor_id=int(user["sub"]))
