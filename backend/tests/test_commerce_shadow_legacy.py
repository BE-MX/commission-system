"""Actual legacy order completion -> immutable outbox -> isolated local book."""
import json
from pathlib import Path
import subprocess
import sys
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.time import beijing_now
from app.commerce_shadow import service as shadow
from app.commerce_shadow.models import ShadowObservation, ShadowExecution
from app.commerce_shadow.schemas import ReplayRequest
from app.commerce_shadow.transport import export_input_bundle, import_execution_receipts
from app.commerce_shadow.worker import target_fingerprint, run_replay
from app.customer.models import CustomerExternalIdentity, CustomerAccount
from app.catalog.models import CatalogExternalIdentity
from app.auth.models import ArkUser
from app.invoice.models import Invoice, InvoiceCommerceEvent
from tests.test_commerce_shadow_hooks import observing
from tests.test_commerce_shadow import isolated
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer
from tests.test_finance_local import finance


def identity(customer_id, *, fingerprint="a" * 64):
    return CustomerExternalIdentity(customer_id=customer_id, source_system="okki", source_account_key="shadow-tenant",
        identifier_type="company_id", raw_value="123456", normalized_value="123456", identity_strength="strong",
        cardinality="one_to_one", auto_match_ceiling="verified", verification_status="verified", confidence=1,
        confidence_method_version="isolated-fixture-v1", confidence_components_json={}, is_primary=True,
        first_seen_at=beijing_now(), last_seen_at=beijing_now(), verified_at=beijing_now(), status="active",
        identity_fingerprint=fingerprint)


def seed_target_aliases(engine, customer, sku, *, mode="valid"):
    with Session(engine) as target:
        if mode != "missing":
            target.add(identity(customer.id))
        if mode == "ambiguous":
            source = target.get(CustomerAccount, customer.id)
            values = {column.key: getattr(source, column.key) for column in CustomerAccount.__table__.columns}
            values.update(id=customer.id + 100, customer_code="OTHER-VERIFIED", display_name="Conflicting company")
            target.add(CustomerAccount(**values))
            target.add(identity(customer.id + 100, fingerprint="b" * 64))
        target.add(CatalogExternalIdentity(source="okki", tenant="shadow-tenant", external_product_id="1",
            external_sku_id="9001", sku_id=sku.id))
        target.get(ArkUser, 1).okki_department_id = 24925
        target.commit()


@pytest.mark.parametrize("followups,fault", [(False, None), (True, None), (True, "bank_missing"), (True, "warehouse_missing"),
    (True, "update"), (True, "update_header_missing"), (False, "add_line"), (True, "shared")])
def test_legacy_http_formal_order_replays_into_actual_independent_local_book(db, isolated, observing, finance, stock, monkeypatch, tmp_path, followups, fault):
    from app.invoice import okki_client, service as invoices
    from app.invoice.router import router as legacy_router
    from app.commerce_transition.models import PlatformPolicy
    from tests.current_order_sync_helpers import install_transport
    from tests.test_invoice_okki_push import _seed_settings, _seed_binding, _make_invoice, _stock_item
    client, _ = observing
    customer, user, _ = finance
    db.get(PlatformPolicy, 1).phase = "legacy_only"
    db.get(ArkUser, int(user["sub"])).okki_department_id = 24925
    _seed_settings(db)
    _seed_binding(db, ark_user_id=int(user["sub"]))
    original = _make_invoice(db, created_by=int(user["sub"]), invoice_no="LEGACY-VERIFIED", status="ready")
    original.items.append(_stock_item(commercial_kind="bulk"))
    invoices._refresh_invoice_totals(original)
    db.add(identity(customer.id))
    db.add(CatalogExternalIdentity(source="okki", tenant="shadow-tenant", external_product_id="1", external_sku_id="9001", sku_id=stock[0].id))
    db.commit()
    seed_target_aliases(isolated[0], customer, stock[0])
    monkeypatch.setattr(get_settings(), "PORTAL_OKKI_NAMESPACE", "shadow-tenant")
    install_transport(db, monkeypatch)
    monkeypatch.setattr(get_settings(), "OKKI_OUTBOUND_AUTO_ENABLED", False)
    calls = []
    def accepted(_db, payload, *, before_send=None):
        calls.append(payload)
        return {"order_id": payload.get("order_id") or 424241 + len(calls), "product_list": [{**row, "unique_id": 501 + index}
            for index, row in enumerate(payload["product_list"])]}
    monkeypatch.setattr(okki_client, "push_order", accepted)
    client.app.include_router(legacy_router, prefix="/legacy")
    response = client.post(f"/legacy/invoices/{original.id}/sync")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is True, response.text
    assert len(calls) == 1
    source = db.get(Invoice, original.id)
    assert source.transaction_mode == "legacy" and source.xiaoman_order_id == "424242"
    observed = db.scalars(select(ShadowObservation).where(ShadowObservation.action == "legacy.order.push").order_by(ShadowObservation.id)).all()
    assert observed and any(row.outcome == "accepted" for row in observed)
    assert all(row.contract_revision == row.result["original_claim_id"] for row in observed)
    assert db.scalar(select(func.count()).select_from(InvoiceCommerceEvent)) == 0
    if fault == "add_line":
        original.items.append(_stock_item(sort_order=2, product_id=2, sku_id=9002, quantity=2,
            price_per_piece=Decimal("7.50"), commercial_kind="bulk"))
        invoices._refresh_invoice_totals(original)
        db.add(CatalogExternalIdentity(source="okki", tenant="shadow-tenant", external_product_id="2",
            external_sku_id="9002", sku_id=stock[0].id))
        db.commit()
        with Session(isolated[0]) as target:
            target.add(CatalogExternalIdentity(source="okki", tenant="shadow-tenant", external_product_id="2",
                external_sku_id="9002", sku_id=stock[0].id))
            target.commit()
        edited = client.post(f"/legacy/invoices/{original.id}/sync")
        assert edited.status_code == 200 and edited.json()["data"]["ok"], edited.text
        assert len(calls) == 2
        latest = db.scalar(select(ShadowObservation).where(ShadowObservation.action == "legacy.order.push",
            ShadowObservation.outcome == "accepted").order_by(ShadowObservation.id.desc()))
        proof = latest.command["body"]["contract"]
        assert len(proof["previous_source_item_ids"]) == 1
        assert proof["items"][1]["source_line_state"] == "new"
    second = None
    if fault == "shared":
        second = _make_invoice(db, created_by=int(user["sub"]), invoice_no="LEGACY-SHARED-B", status="ready",
            shipping_fee=0, surcharge_amount=0)
        second.items.append(_stock_item(commercial_kind="bulk", quantity=1, price_per_piece=Decimal("40")))
        invoices._refresh_invoice_totals(second)
        db.commit()
        response = client.post(f"/legacy/invoices/{second.id}/sync")
        assert response.status_code == 200 and response.json()["data"]["ok"], response.text
    additions = _original_money_and_outbound(db, original, finance, stock, monkeypatch, fault, second) if followups else {}
    if fault == "warehouse_missing":
        additions.pop("legacy_warehouse_map")
    observed = db.scalars(select(ShadowObservation).order_by(ShadowObservation.id)).all()
    invoice_ids = [original.id] + ([second.id] if second else [])
    payment_ids = additions.pop("payment_ids", [])
    cp = {**isolated[1].checkpoint, "invoice_ids": invoice_ids, "payment_ids": payment_ids, **additions}
    if second:
        # The same original P covers A+B. A partial export cannot execute any
        # candidate command, even though its individual source observations exist.
        shadow.create_dataset(db, dataset_id="legacy-incomplete-A", checkpoint={**cp, "invoice_ids": [original.id]},
            target_fingerprint=target_fingerprint(isolated[0]), actor_id=int(user["sub"]))
        partial = shadow.request_run(db, ReplayRequest(dataset_id="legacy-incomplete-A", request_key="incomplete-A",
            invoice_ids=[original.id], payment_ids=payment_ids, through_observation_id=observed[-1].id), user)
        db.commit()
        from app.commerce_shadow.transport import execute_input_bundle
        piece = export_input_bundle(db, partial.id)
        assert "incomplete_cross_order_closure" in piece["missing_dependencies"]
        receipt = execute_input_bundle(isolated[0], piece)
        assert receipt["results"] == []
        with Session(isolated[0]) as target:
            from app.invoice.settlement_models import ReceiptBatch
            assert target.scalar(select(func.count()).select_from(ReceiptBatch)) == 0
    shadow.create_dataset(db, dataset_id="legacy-http", checkpoint=cp, target_fingerprint=target_fingerprint(isolated[0]), actor_id=int(user["sub"]))
    run = shadow.request_run(db, ReplayRequest(dataset_id="legacy-http", request_key="legacy-real-run", invoice_ids=invoice_ids, payment_ids=payment_ids,
        through_observation_id=observed[-1].id), user)
    db.commit()
    bundle = export_input_bundle(db, run.id)
    request_path, report_path = tmp_path / "legacy-input.json", tmp_path / "legacy-report.json"
    request_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    command = [sys.executable, "-m", "app.commerce_shadow.cli", "--target-url", str(isolated[0].url),
        "--input", str(request_path), "--report", str(report_path)]
    blocked = fault in {"bank_missing", "warehouse_missing", "update_header_missing"}
    for _ in range(2):
        completed = subprocess.run(command, cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert completed.returncode == (2 if blocked else 0), completed.stdout + completed.stderr
    import_execution_receipts(db, bundle, json.loads(report_path.read_text(encoding="utf-8")))
    db.commit()
    assert run.status == ("incomplete" if blocked else "consistent"), run.coverage
    with Session(isolated[0]) as target:
        calculated = target.scalar(select(Invoice))
        assert calculated.id != original.id and calculated.transaction_mode == "local"
        assert calculated.commerce_status == "confirmed" and calculated.total_amount == Decimal("67.50" if fault == "add_line" else "52.50")
        expected_events = {"shared": 6, "add_line": 3, "update": 7, "update_header_missing": 4}.get(
            fault, 4 if followups and not blocked else 2)
        assert target.scalar(select(func.count()).select_from(InvoiceCommerceEvent)) == expected_events
        if fault == "add_line":
            assert len(calculated.items) == 2 and len({item.id for item in calculated.items}) == 2
        if followups:
            from app.invoice.settlement_models import ReceiptBatch, ShipmentSettlement, ShipmentOutbound
            from app.commerce_transition.models import BankIdentity
            from app.receipt.models import Receipt
            batch = target.scalar(select(ReceiptBatch))
            if fault == "bank_missing":
                assert batch is None
                assert target.scalar(select(func.count()).select_from(BankIdentity)) == 0
                assert "legacy_canonical_bank_identity_missing" in str(run.coverage)
                return
            assert batch.gross_amount == batch.allocated_amount == Decimal("92.50" if fault == "shared" else "52.50")
            assert batch.net_amount == Decimal("87.50" if fault == "shared" else "47.50")
            assert target.scalar(select(func.count()).select_from(BankIdentity)) == 1
            assert target.scalar(select(func.count()).select_from(Receipt)) == (3 if fault == "shared" else 2)
            if fault == "warehouse_missing":
                assert target.scalar(select(ShipmentSettlement)) is None
                assert "legacy_warehouse_mapping_missing" in str(run.coverage)
                return
            assert target.scalar(select(ShipmentSettlement).order_by(ShipmentSettlement.id.desc())).state == "ready"
            assert target.scalar(select(ShipmentOutbound).order_by(ShipmentOutbound.id.desc())).status == "local_ready"
            assert calculated.items[0].stock_shipped_quantity == 0
            if fault == "update_header_missing":
                assert "legacy_outbound_currency_missing" in str(run.coverage)
            if fault == "update":
                assert target.scalar(select(ShipmentSettlement).order_by(ShipmentSettlement.id)).state == "cancelled"
                assert target.scalar(select(func.count()).select_from(ShipmentSettlement)) == 2


def _original_money_and_outbound(db, invoice, finance, stock, monkeypatch, fault=None, second=None):
    """Real claimed HTTP helpers and verified original ledgers; no source seeding in target."""
    from app.invoice import legacy_sending, okki_client, outbound_create_plan
    from app.invoice.models import OkkiOutboundTask
    from app.receipt import remote, sync_service
    from app.receipt.models import Receipt
    from app.commerce_shadow.hooks import capture_legacy_receipt, capture_legacy_outbound
    from app.commerce_transition.models import BankAccountDomain
    from app.finance.transition_identity import reconcile_legacy_identity
    actor_id = int(finance[1]["sub"])
    from app.commerce_transition.service import register_bank_domain
    domain = db.scalar(select(BankAccountDomain))
    register_bank_domain(db, subject_key=domain.subject_key, account_key=domain.account_key, channel=domain.channel,
        bank_account_ids=[finance[2].id], legacy_identity_complete=True, enforced=True, exclusive_route="legacy",
        evidence={"original_bank_account_only": True})
    batch = None
    if second:
        from app.invoice.settlement_models import ReceiptBatch
        batch = ReceiptBatch(batch_no="ORIGINAL-SHARED-P", customer_id=invoice.customer_id, currency=invoice.currency,
            gross_amount=invoice.total_amount + second.total_amount, transaction_mode="legacy", bank_account_id=finance[2].id,
            actual_bank_fee=5, rate_to_cny=7, rate_to_usd=1, collection_date=invoice.invoice_date,
            payment_type="bank_transfer", request_key="original-shared-cash-P", request_hash="synthetic-original-P",
            created_by=actor_id)
        db.add(batch); db.flush()
    row = Receipt(receipt_no="LEGACY-ORIGINAL-MONEY", invoice_id=invoice.id, source="manual", request_key="original-bank-allocation",
        request_hash="synthetic-original-body", amount=invoice.total_amount, currency=invoice.currency,
        collection_date=invoice.invoice_date, payment_type="bank_transfer", bank_charge=5,
        attachment_ids=[], customer_id=invoice.customer_id, xiaoman_order_id=invoice.xiaoman_order_id,
        created_by=actor_id, attempt_token="original-cash-attempt", batch_id=batch.id if batch else None)
    db.add(row); db.flush()
    if fault != "bank_missing":
        reconcile_legacy_identity(db, domain_id=domain.id, transaction_id="BANK-ORIGINAL-52-50",
            receipt_id=None if batch else row.id, batch_id=batch.id if batch else None,
            statement_reference="Synthetic original bank statement line 1", actor_id=actor_id)
    db.commit()
    sent = []
    def post(path, _token, payload, *, context):
        assert not db.in_transaction()
        sent.append((path, payload))
        if path.endswith("/receipt/push"):
            identity = 7000 + len(sent)
            return {"cash_collection_id": identity, "cash_collection_no": f"ORIGINAL-CASH-{identity}"}
        assert path.endswith("/outbound/push")
        return {"outbound_invoice_id": 8001, "serial_id": payload.get("serial_id", "ORIGINAL-OUT-8001")}
    monkeypatch.setattr(okki_client, "_post_json", post)
    def read(_db, path, params=None):
        if path.endswith("/types"):
            return ["bank_transfer"]
        if path.endswith("/fields"):
            return []
        raise AssertionError(f"Unexpected synthetic provider path {path}")
    monkeypatch.setattr(remote, "read", read)
    def claim(payload):
        ticket = legacy_sending.start(db, invoice.id, "original-cash-send", "receipt_push", payload,
            {"actor_id": actor_id, "command_input": capture_legacy_receipt(db, invoice, row, payload)})
        db.commit()
        return ticket
    result = remote.push(db, row, {"exchange_rate": 7}, claim)
    # This is independent exact original-provider readback, through the genuine
    # binding validator; an ACK alone intentionally retained an unknown sample.
    data = {**sent[-1][1], **result, "collect_status": 1}
    sync_service.bind_remote(db, row, data, actor_id)
    db.commit()
    assert row.collect_status == 1 and row.sync_status == "synced"
    if second:
        other = Receipt(receipt_no="LEGACY-ORIGINAL-MONEY-B", invoice_id=second.id, source="manual", batch_id=batch.id,
            request_key="original-bank-allocation-B", request_hash="synthetic-original-B", amount=second.total_amount,
            currency=second.currency, collection_date=second.invoice_date, payment_type="bank_transfer", bank_charge=0,
            attachment_ids=[], customer_id=second.customer_id, xiaoman_order_id=second.xiaoman_order_id,
            created_by=actor_id, attempt_token="original-cash-attempt-B")
        db.add(other); db.commit()
        def other_claim(body):
            ticket = legacy_sending.start(db, second.id, "original-cash-send-B", "receipt_push", body,
                {"actor_id": actor_id, "command_input": capture_legacy_receipt(db, second, other, body)})
            db.commit()
            return ticket
        result = remote.push(db, other, {"exchange_rate": 7}, other_claim)
        sync_service.bind_remote(db, other, {**sent[-1][1], **result, "collect_status": 1}, actor_id)
        db.commit()
    item = invoice.items[0]
    payload = {"serial_id": "ORIGINAL-OUT-8001", "remark": invoice.remark or "", "status": 1, "source_type": 2,
        "currency": invoice.currency, "exchange_rate": 7, "exchange_rate_usd": 1, "invoice_warehouse_id": 90001,
        "company_id": int(invoice.customer_id), "handler": ["101"], "record_list": [{
            "order_id": invoice.xiaoman_order_id, "order_record_id": item.xiaoman_unique_id,
            "product_id": item.product_id, "sku_id": item.sku_id, "outbound_count": item.quantity,
            "sale_price": str(item.price_per_piece), "product_name": item.product_name, "product_model": "",
            "product_cn_name": "", "product_unit": "Piece"}]}
    ticket = legacy_sending.start(db, invoice.id, "original-outbound-send", "outbound_create", payload,
        {"actor_id": actor_id, "command_input": capture_legacy_outbound(db, invoice, payload, actor_id,
            request_key="original-outbound-command")})
    db.commit()
    legacy_sending.invoke(db, ticket, "/v1/invoices/outbound/push", "synthetic-token", payload, context="Synthetic original outbound")
    detail = {**payload, "outbound_invoice_id": 8001, "invoice_warehouse_info": {"id": 90001},
        "company_info": {"id": invoice.customer_id}, "handler_info": [{"user_id": "101"}],
        "record_list": [{**line, "outbound_record_id": 801 + index} for index, line in enumerate(payload["record_list"])]}
    verified = outbound_create_plan.verify(detail, payload, invoice.xiaoman_order_id, "8001")
    legacy_sending.finish(db, ticket.request_key, "succeeded", {"original_readback_hash": shadow.digest(verified)}, "8001")
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id == invoice.id))
    if task is None:
        task = OkkiOutboundTask(invoice_id=invoice.id, order_id=invoice.xiaoman_order_id)
        db.add(task)
    task.status = "done"; db.flush()
    legacy_sending.observe_formal(db, ticket.request_key, "legacy.outbound.remote", "accepted", result_row=task,
        actor_id=actor_id, evidence_ref={"original_readback_hash": shadow.digest(verified)})
    db.commit()
    if fault in {"update", "update_header_missing"}:
        from app.shipping_inspection import outbound_sync_plan as plans
        products = [dict(unique_id=int(item.xiaoman_unique_id), product_id=item.product_id, sku_id=item.sku_id,
            count=item.quantity, unit_price=float(item.price_per_piece), cost_amount=float(item.total_price),
            product_name=item.product_name, unit="Piece", product_model="", product_cn_name="")]
        order = dict(order_id=invoice.xiaoman_order_id, company_id=invoice.customer_id, currency=invoice.currency,
            product_list=products)
        plan = plans.build(detail, order, products, "Updated original outbound remark")
        changed = plan["payload"]
        assert "currency" not in changed and "invoice_warehouse_id" not in changed
        grant = legacy_sending.start(db, invoice.id, "original-outbound-update-send", "outbound_update", changed,
            {"actor_id": actor_id, "command_input": capture_legacy_outbound(db, invoice, changed, actor_id,
                request_key="original-outbound-update-command", operation="update",
                before=detail if fault == "update" else None)})
        db.commit()
        legacy_sending.invoke(db, grant, "/v1/invoices/outbound/push", "synthetic-token", changed, context="Synthetic original outbound update")
        after = {**detail, "remark": "Updated original outbound remark", "record_list": [
            {**detail["record_list"][0], "cost_unit_price_rmb": 0}]}
        plans.verify(detail, after, plan)
        verified = after
        legacy_sending.finish(db, grant.request_key, "succeeded", {"original_readback_hash": shadow.digest(verified)}, "8001")
        legacy_sending.observe_formal(db, grant.request_key, "legacy.outbound.remote", "accepted", result_row=task,
            actor_id=actor_id, evidence_ref={"original_readback_hash": shadow.digest(verified)})
        db.commit()
    assert len(sent) == (3 if fault in {"update", "update_header_missing", "shared"} else 2)
    return {"payment_ids": [batch.id] if batch else [],
        "legacy_warehouse_map": {"okki:shadow-tenant:90001": {"warehouse_id": stock[1][0].id,
                "review_reference": "Synthetic warehouse identity independently verified"}},
        "legacy_allocation_plans": {f"legacy-receipt:{row.id}": [
            {"kind": "goods", "amount": "42.50"}, {"kind": "freight", "amount": "10.00"}]}}


@pytest.mark.parametrize("mode", ["missing", "ambiguous"])
def test_legacy_exact_identity_mapping_missing_or_ambiguous_is_incomplete(db, isolated, finance, stock, mode):
    from app.commerce_shadow.legacy_adapter import expected_order
    customer, user, _ = finance
    seed_target_aliases(isolated[0], customer, stock[0], mode=mode)
    raw = {"request_key": "legacy-original", "actor": user, "original_payload": {"product_list": [{}]}, "contract": {
        "source_invoice_id": 901, "source_namespace": "okki", "tenant": "shadow-tenant", "customer_external_id": "123456",
        "invoice_no": "LEGACY", "invoice_date": "2026-10-03", "currency": "USD", "order_type": "production", "sales_user_id": 1,
        "shipping_fee": "0", "surcharge_amount": "0", "product_amount": "100", "total_amount": "100",
        "items": [{"source_item_id": 1, "external_product_id": "1", "external_sku_id": "9001", "quantity": 1,
            "price_per_piece": "100", "total_price": "100", "discount_amount": "0"}]}}
    observation = shadow.record_observation(db, source_event_id="legacy-formal", invoice_id=901, action="legacy.order.push",
        request_key="legacy-original", command={"body": raw, "actor": user}, outcome="accepted", result=expected_order(raw),
        contract_revision=1, causal_version=1, dependencies=[], actor_id=1)
    run = shadow.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="mapping-case", invoice_ids=[901], through_observation_id=observation.id), user)
    db.commit()
    run_replay(db, run.id, isolated[0])
    db.commit()
    assert run.status == "incomplete" and any("mapping_missing_or_ambiguous" in item for item in run.coverage["missing_dependencies"])
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(Invoice)) == 0


@pytest.mark.parametrize("state", ["existing", "new"])
def test_known_before_line_without_candidate_reference_never_becomes_a_new_line(db, isolated, finance, stock, state):
    from datetime import date
    from app.commerce_shadow.legacy_adapter import execute_order
    from app.commerce_shadow.dispatcher import UnsupportedCommand
    customer, user, _ = finance
    seed_target_aliases(isolated[0], customer, stock[0])
    raw = {"request_key": "existing-line-lost-reference", "original_payload": {"order_id": 424242, "product_list": [{}]},
        "contract": {"source_invoice_id": 901, "source_namespace": "okki", "tenant": "shadow-tenant", "customer_external_id": "123456",
        "invoice_no": "OLD-BASE", "invoice_date": "2026-10-03", "currency": "USD", "order_type": "production", "sales_user_id": 1,
        "shipping_fee": "0", "surcharge_amount": "0", "previous_source_item_ids": [1],
        "items": [{"source_item_id": 1, "external_product_id": "1", "external_sku_id": "9001", "quantity": 1,
            "price_per_piece": "100", "total_price": "100", "commercial_kind": "bulk", "source_line_state": state}]}}
    with Session(isolated[0]) as target:
        target.add(Invoice(id=991, invoice_no="OLD-BASE", transaction_mode="local", customer_id=f"ark:{customer.id}",
            customer_name="Verified independent baseline", invoice_date=date(2026, 10, 3), created_by=1))
        target.commit()
        with pytest.raises(UnsupportedCommand, match="legacy_amendment_line_checkpoint_missing"):
            execute_order(target, dataset_id="line-proof", command={"body": raw, "actor": user}, actor_id=1,
                checkpoint={"identity_map": {"invoice:901": 991}})
        assert target.scalar(select(func.count()).select_from(InvoiceCommerceEvent)) == 0


def test_late_original_order_generation_cannot_replace_current_contract_or_before_image(db, isolated, finance, stock):
    from app.commerce_shadow.legacy_adapter import expected_order
    from app.commerce_shadow.capture import contract_history
    customer, user, _ = finance
    seed_target_aliases(isolated[0], customer, stock[0])
    raw = {"request_key": "current-original-claim", "actor": user, "original_payload": {"product_list": [{}]}, "contract": {
        "source_invoice_id": 901, "source_namespace": "okki", "tenant": "shadow-tenant", "customer_external_id": "123456",
        "invoice_no": "CURRENT-CONTRACT", "invoice_date": "2026-10-03", "currency": "USD", "order_type": "production", "sales_user_id": 1,
        "shipping_fee": "0", "surcharge_amount": "0", "product_amount": "100", "total_amount": "100",
        "items": [{"source_item_id": 1, "external_product_id": "1", "external_sku_id": "9001", "quantity": 1,
            "price_per_piece": "100", "total_price": "100", "discount_amount": "0", "commercial_kind": "bulk"}]}}
    current = shadow.record_observation(db, source_event_id="original-claim-10", invoice_id=901, action="legacy.order.push",
        request_key="current-claim", command={"body": raw, "actor": user}, outcome="accepted", result=expected_order(raw),
        contract_revision=10, causal_version=1, dependencies=[], actor_id=1)
    shadow.record_observation(db, source_event_id="late-original-claim-2", invoice_id=901, action="legacy.order.push",
        request_key="late-claim", command={"body": raw, "actor": user}, outcome="accepted", result=expected_order(raw),
        contract_revision=2, causal_version=2, dependencies=[], actor_id=1)
    db.commit()
    monkeypatch_settings = get_settings().COMMERCE_SHADOW_ENABLED
    try:
        get_settings().COMMERCE_SHADOW_ENABLED = True
        assert contract_history(db, isolated[2])["previous_contract_ref"]["$ref"] == current.source_event_id
    finally:
        get_settings().COMMERCE_SHADOW_ENABLED = monkeypatch_settings
    run = shadow.request_run(db, ReplayRequest(dataset_id="dataset-1", request_key="late-original-claim-run", invoice_ids=[901],
        through_observation_id=2), user)
    db.commit()
    run_replay(db, run.id, isolated[0]); db.commit()
    assert run.status == "incomplete" and "late_contract_revision_or_authority_epoch" in str(run.coverage)
    with Session(isolated[0]) as target:
        assert target.scalar(select(func.count()).select_from(InvoiceCommerceEvent)) == 2
        assert target.scalar(select(Invoice)).total_amount == 100


def test_claim_sent_before_observation_keeps_original_generation_and_unobserved_children_incomplete(db, isolated, observing, finance, monkeypatch):
    from app.invoice import legacy_sending, okki_client
    from app.invoice.models import InvoiceItem
    from app.receipt.models import Receipt
    from app.receipt.sync_service import bind_remote
    from app.commerce_shadow.capture import receipt as capture_receipt, contract_history
    from app.commerce_transition.models import PlatformPolicy
    source, user = isolated[2], finance[1]
    db.get(PlatformPolicy, 1).phase = "legacy_only"
    source.customer_id, source.order_type, source.total_amount, source.product_amount = "123456", "production", Decimal("100"), Decimal("100")
    source.sync_status, source.xiaoman_order_id = "synced", "424242"
    source.items.append(InvoiceItem(sort_order=1, item_type="stock", product_id=1, sku_id=9001,
        product_name="Synthetic original hair", product_display="Synthetic original hair", color="#1",
        quantity=1, price_per_piece=100, total_price=100, commercial_kind="bulk"))
    db.commit()
    payload = {"order_id": 424242, "company_id": 123456, "currency": "USD", "product_list": [{"product_id": 1, "sku_id": 9001}]}
    raw = {"actor": user, "original_payload": payload, "contract": {"source_invoice_id": source.id,
        "source_namespace": "okki", "tenant": "shadow-tenant", "customer_external_id": source.customer_id,
        "invoice_no": source.invoice_no, "invoice_date": source.invoice_date.isoformat(), "currency": "USD", "order_type": "production",
        "sales_user_id": 1, "shipping_fee": "0", "surcharge_amount": "0", "product_amount": "100", "total_amount": "100",
        "items": [{"source_item_id": source.items[0].id, "external_product_id": "1", "external_sku_id": "9001", "quantity": 1,
            "price_per_piece": "100", "total_price": "100", "discount_amount": "0", "commercial_kind": "bulk"}]}}
    def provider(path, _token, body, *, context):
        assert not db.in_transaction()
        return {"cash_collection_id": 7001, "cash_collection_no": "ORIGINAL-7001"} if path.endswith("receipt/push") else {"order_id": 424242}
    monkeypatch.setattr(okki_client, "_post_json", provider)
    monkeypatch.setattr(get_settings(), "COMMERCE_SHADOW_ENABLED", False)
    old = legacy_sending.start(db, source.id, "observer-off-original", "order_push", payload,
        {"actor_id": 1, "command_input": raw})
    db.commit()
    legacy_sending.invoke(db, old, "/v1/invoices/order/push", "synthetic-token", payload, context="Observer-off original")
    assert db.scalar(select(func.count()).select_from(ShadowObservation)) == 0
    monkeypatch.setattr(get_settings(), "COMMERCE_SHADOW_ENABLED", True)
    row = Receipt(receipt_no="UNOBSERVED-ORDER-CHILD", invoice_id=source.id, source="manual", request_key="unobserved-child",
        request_hash="synthetic-body", amount=100, currency="USD", collection_date=source.invoice_date, payment_type="bank_transfer",
        bank_charge=0, attachment_ids=[], customer_id=source.customer_id, xiaoman_order_id=source.xiaoman_order_id,
        created_by=1, attempt_token="unobserved-order-child-attempt")
    db.add(row); db.commit()
    cash_payload = {"order_id": 424242, "currency": "USD", "collection_date": source.invoice_date.isoformat(),
        "amount": "100", "real_amount": "100", "bank_charge": "0", "exchange_rate": "7"}
    captured = capture_receipt(db, source, row, cash_payload)
    assert captured["source_contract_revision"] is None
    cash = legacy_sending.start(db, source.id, "unobserved-child-send", "receipt_push", cash_payload,
        {"actor_id": 1, "command_input": captured})
    db.commit()
    result = legacy_sending.invoke(db, cash, "/v1/invoices/receipt/push", "synthetic-token", cash_payload, context="Unobserved order child")
    bind_remote(db, row, {**cash_payload, **result, "collect_status": 1}, 1); db.commit()
    assert row.sync_status == "synced" and row.collect_status == 1
    children = list(db.scalars(select(ShadowObservation).where(ShadowObservation.action == "legacy.receipt.remote")))
    assert children and all("legacy_source_order_generation_missing" in item.command["unavailable_evidence"] for item in children)
    current = legacy_sending.start(db, source.id, "observer-on-current", "order_push", payload,
        {"actor_id": 1, "command_input": raw})
    db.commit()
    legacy_sending.invoke(db, current, "/v1/invoices/order/push", "synthetic-token", payload, context="Observer-on current")
    latest = legacy_sending.observe_formal(db, current.request_key, "legacy.order.push", "accepted", result_row=source, actor_id=1)
    db.commit()
    late = legacy_sending.observe_formal(db, old.request_key, "legacy.order.push", "accepted", result_row=source, actor_id=1)
    db.commit()
    assert late.contract_revision == old.claim_id < latest.contract_revision == current.claim_id
    assert contract_history(db, source)["previous_contract_ref"]["$ref"] == latest.source_event_id
    with pytest.raises(ValueError, match="动作不匹配"):
        legacy_sending.observe_formal(db, old.request_key, "legacy.receipt.remote", "accepted", result_row=row, actor_id=1)
    unrelated = Invoice(invoice_no="UNRELATED-CLAIM-PARENT", customer_id=source.customer_id,
        customer_name="Other synthetic order", invoice_date=source.invoice_date, created_by=1,
        sync_status="synced", xiaoman_order_id="999999")
    db.add(unrelated); db.commit()
    with pytest.raises(ValueError, match="原订单正式凭证"):
        legacy_sending.observe_formal(db, old.request_key, "legacy.order.push", "accepted", result_row=unrelated, actor_id=1)
