"""Crash boundaries, finite recovery, and exact remote-identity reconciliation."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core import time as clock
from app.invoice import okki_client
from app.receipt import recovery, remote, service, sync_service
from app.receipt.models import ReceiptAttempt
from app.receipt.receipt_index import IndexNotReady
from tests.authority_helpers import seed_authority
from tests.test_receipt_management import (  # noqa: F401
    USER, no_real_remote, order, reconcile_financial, register,
)


@pytest.fixture(autouse=True)
def live_receipt_authority(db):
    """Creation/change authorization is live: the operator's grants come from
    the database, and the shared engine already carries the authority barrier."""
    seed_authority(db, 1, "receipt:read", "receipt:write")


@pytest.mark.parametrize("phase,expected,kind", [
    ("preparing", "failed", "prepare_retry"), ("sending", "uncertain", "unknown"),
    (None, "uncertain", "unknown")])
def test_expired_phase_determines_whether_replay_is_safe(db, order, phase, expected, kind):
    row, _ = register(db, order)
    row.sync_status, row.send_phase, row.attempt_token = "syncing", phase, "expired"
    row.lease_until = clock.beijing_now() - timedelta(seconds=1)
    db.commit()
    recovery.recover_expired(db)
    db.refresh(row)
    assert (row.sync_status, row.recovery_kind) == (expected, kind)
    assert row.attempt_token is None
    recovery.prepare_due(db)
    db.refresh(row)
    assert row.sync_status == expected  # backoff not due, unknown never retries


def test_preparation_network_retry_is_bounded_and_reuses_original_row(db, order, monkeypatch):
    row, _ = register(db, order)
    now = datetime(2026, 10, 8, 23, 59, 30)
    monkeypatch.setattr(recovery, "beijing_now", lambda: now)
    def offline(*a):
        raise httpx.ReadTimeout("offline")
    monkeypatch.setattr(remote, "order_snapshot", offline)
    for attempt in range(recovery.PREPARE_LIMIT):
        sync_service.deliver(db, row.id)
        db.refresh(row)
        assert row.sync_status == "failed" and row.send_phase == "preparing"
        if attempt + 1 < recovery.PREPARE_LIMIT:
            assert row.next_attempt_at > now
            recovery.prepare_due(db)
            assert row.sync_status == "failed"
            now = row.next_attempt_at
            recovery.prepare_due(db)
            db.refresh(row)
            assert row.sync_status == "pending"
    assert row.recovery_kind == "exhausted" and row.next_attempt_at is None
    assert row.attempts == recovery.PREPARE_LIMIT
    assert all(a.payload_hash is None for a in db.query(ReceiptAttempt).all())


def test_index_not_ready_is_a_retryable_pre_post_failure(db, order, monkeypatch):
    row, _ = register(db, order)
    def missing(*a):
        raise IndexNotReady("building")
    monkeypatch.setattr(remote, "order_snapshot", missing)
    monkeypatch.setattr(remote, "push", lambda *a: pytest.fail("must not POST"))
    sync_service.deliver(db, row.id)
    assert row.sync_status == "failed" and row.recovery_kind == "prepare_retry"
    assert row.send_phase == "preparing"


def test_post_timeout_with_durable_sending_evidence_never_auto_replays(db, order, monkeypatch):
    row, _ = register(db, order)
    def timeout(db, row, snapshot, fence):
        fence({"amount": "500"})
        assert row.send_phase == "sending"
        assert db.get(ReceiptAttempt, row.attempt_token).payload_hash
        raise okki_client.OkkiOutcomeUncertainError("timeout")
    monkeypatch.setattr(remote, "push", timeout)
    sync_service.deliver(db, row.id)
    assert row.sync_status == "uncertain" and row.recovery_kind == "unknown"
    recovery.prepare_due(db)
    monkeypatch.setattr(remote, "push", lambda *a: pytest.fail("must not replay"))
    sync_service.deliver(db, row.id)


def test_known_id_readback_recovers_without_global_index_or_second_post(db, order, monkeypatch):
    row, _ = register(db, order)
    info = remote.receipt_info
    monkeypatch.setattr(remote, "receipt_info", lambda *a: (_ for _ in ()).throw(httpx.ReadTimeout("offline")))
    sync_service.deliver(db, row.id)
    assert row.xiaoman_receipt_id == "701" and row.recovery_kind == "verify"
    assert row.collect_status is None and row.send_phase == "accepted"
    monkeypatch.setattr(remote, "push", lambda *a: pytest.fail("must not POST"))
    monkeypatch.setattr(remote, "order_receipts", lambda *a: pytest.fail("must not use global index"))
    monkeypatch.setattr(remote, "receipt_info", lambda db, identity: dict(info(db, identity), collect_status=1))
    row.next_attempt_at = clock.beijing_now() - timedelta(seconds=1)
    db.commit()
    recovery.verify_due(db)
    assert row.collect_status == 1 and row.send_phase == "verified" and row.last_error is None
    assert row.attempts == 1


def test_financial_pending_is_polled_until_effective(db, order, monkeypatch):
    row, _ = register(db, order)
    sync_service.deliver(db, row.id)
    assert row.sync_status == "synced" and row.collect_status == 0 and row.recovery_kind == "verify"
    info = remote.receipt_info
    monkeypatch.setattr(remote, "receipt_info", lambda db, identity: dict(info(db, identity), collect_status=1))
    row.next_attempt_at = clock.beijing_now() - timedelta(seconds=1)
    db.commit()
    recovery.verify_due(db)
    assert row.collect_status == 1 and row.next_attempt_at is None


def test_readback_failures_are_bounded_without_releasing_balance(db, order, monkeypatch):
    row, _ = register(db, order)
    sync_service.deliver(db, row.id)
    monkeypatch.setattr(remote, "receipt_info", lambda *a: (_ for _ in ()).throw(httpx.ReadTimeout("offline")))
    for _ in range(recovery.VERIFY_LIMIT):
        sync_service.refresh_accepted(db, row.id)
    assert row.recovery_kind == "exhausted" and row.next_attempt_at is None
    monkeypatch.setattr(remote, "receipt_info", lambda *a: pytest.fail("automatic budget exhausted"))
    recovery.verify_due(db)
    assert row.xiaoman_receipt_id == "701" and row.attempts == 1


def test_scheduler_reads_known_ids_even_when_new_sends_disabled(db, order, monkeypatch):
    from types import SimpleNamespace
    from app.receipt import scheduler
    from app.invoice import settlement_policy
    row, _ = register(db, order)
    sync_service.deliver(db, row.id)
    row.next_attempt_at = clock.beijing_now() - timedelta(seconds=1)
    db.commit()
    info = remote.receipt_info
    monkeypatch.setattr(remote, "receipt_info", lambda db, identity: dict(info(db, identity), collect_status=1))
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: db)
    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(RECEIPT_SYNC_ENABLED=False))
    monkeypatch.setattr(settlement_policy, "capabilities", lambda: {
        "freight_delivery_enabled": False, "outbound_delivery_enabled": False})
    monkeypatch.setattr(remote, "push", lambda *a: pytest.fail("sending disabled"))
    identity = row.id
    scheduler.process_receipts()
    from app.receipt.models import Receipt
    row = db.get(Receipt, identity)
    assert row.collect_status == 1 and row.attempts == 1


def test_edit_clears_automatic_retry_schedule(db, order):
    from app.receipt.schemas import ReceiptUpdate
    row, _ = register(db, order)
    row.sync_status, row.send_phase, row.recovery_kind = "failed", "preparing", "prepare_retry"
    row.next_attempt_at = clock.beijing_now() - timedelta(seconds=1)
    db.commit()
    body = ReceiptUpdate(amount="500", collection_date=row.collection_date, payment_type="T/T",
        bank_charge="0", attachment_ids=row.attachment_ids, remark="corrected", version=row.version)
    service.change(db, row, order, body, 1)
    db.commit()
    recovery.prepare_due(db)
    assert row.sync_status == "failed" and row.next_attempt_at is None


def test_wrong_money_is_blocked_and_older_readback_cannot_clear_it(db, order, monkeypatch):
    row, _ = register(db, order)
    sync_service.deliver(db, row.id)
    info = remote.receipt_info
    initial_version = row.version
    def out_of_order(db, identity):
        old = info(db, identity)
        monkeypatch.setattr(remote, "receipt_info", lambda db, identity: dict(old, real_amount="400"))
        sync_service.refresh_accepted(db, row.id)  # newer remote observation commits first
        return old
    monkeypatch.setattr(remote, "receipt_info", out_of_order)
    sync_service.refresh_accepted(db, row.id)
    assert row.sync_status == "uncertain" and row.recovery_kind == "blocked"
    assert row.version > initial_version
    recovery.verify_due(db)
    assert row.sync_status == "uncertain"


def test_late_success_recovers_exact_id_and_does_not_guess_by_amount(db, order, monkeypatch):
    row, _ = register(db, order)
    def late(db, row, snapshot, fence):
        fence({"amount": "500"})
        row.sync_status, row.attempt_token = "uncertain", "changed"
        db.commit()
        return {"cash_collection_id": "99", "cash_collection_no": "HK99"}
    monkeypatch.setattr(remote, "push", late)
    sync_service.deliver(db, row.id)
    assert row.xiaoman_receipt_id is None
    assert db.query(ReceiptAttempt).one().remote_id == "99"
    recovery.recover_late_results(db)
    assert row.xiaoman_receipt_id == "99" and row.recovery_kind == "verify"
    recovery.verify_due(db)
    assert row.sync_status == "synced"
    version = row.version
    recovery.recover_late_results(db)
    assert row.version == version


def test_late_different_id_blocks_existing_binding_and_is_not_reprocessed(db, order):
    row, _ = register(db, order)
    row.xiaoman_receipt_id, row.sync_status, row.collect_status = "new-id", "synced", 1
    db.add(ReceiptAttempt(token="old-attempt", receipt_id=row.id, remote_id="old-id", remote_no="HK-old"))
    db.commit()
    recovery.recover_late_results(db)
    assert row.xiaoman_receipt_id == "new-id" and row.sync_status == "uncertain"
    assert row.recovery_kind == "blocked"
    version = row.version
    recovery.recover_late_results(db)
    assert row.version == version


def test_current_id_reconciliation_cannot_clear_other_exact_response_ids(db, order, monkeypatch):
    from app.invoice import lifecycle_remote
    from app.receipt import remote_change_service
    from app.receipt.schemas import RemoteChange
    row, _ = register(db, order)
    row.xiaoman_receipt_id, row.sync_status = "701", "synced"
    db.add(ReceiptAttempt(token="different-result", receipt_id=row.id, remote_id="99", remote_no="HK99"))
    db.commit()
    recovery.recover_late_results(db)
    # The public one-shot helpers were replaced by evidence-passing service
    # functions and the current-authorized accept path; both still hit the same
    # identity guard, so the conflict survives a current-ID readback.
    with pytest.raises(service.ReturnedIdentityConflict):
        reconcile_financial(db, row, 1)
    identity, version = row.id, row.version  # Capture before closing the transaction.
    db.rollback()  # The rejected reconciliation leaves an open lock transaction.
    seed_authority(db, 1, "receipt:admin")
    monkeypatch.setattr(lifecycle_remote, "read", lambda db, kind, identity: {
        "cash_collection_id": "701", "cash_collection_no": "TEST-HK", "order_id": "2001",
        "currency": "USD", "amount": "500", "bank_charge": "0", "real_amount": "500",
        "collect_status": 1, "collection_date": "2026-09-17"})
    body = RemoteChange(version=version, evidence_hash="a" * 64,
                        reason="已核实实际收款与小满原单一致", confirmed=True)
    with pytest.raises(service.ReturnedIdentityConflict):
        remote_change_service.accept(db, identity, body, USER)
    sync_service.refresh_accepted(db, row.id)
    assert row.sync_status == "uncertain" and row.recovery_kind == "blocked"
    assert row.xiaoman_receipt_id == "701"


def test_late_id_already_mapped_elsewhere_preserves_identity_evidence(db, order, monkeypatch):
    row, _ = register(db, order)
    other, _ = register(db, order, key="other-test-request-001")
    other.xiaoman_receipt_id, other.sync_status = "701", "synced"
    db.commit()
    monkeypatch.setattr(remote, "order_snapshot", lambda db, invoice: {
        "rows": [remote.receipt_info(db, "701")], "exchange_rate": 725})
    sync_service.deliver(db, row.id)
    assert db.query(ReceiptAttempt).filter_by(receipt_id=row.id).one().remote_id == "701"
    assert row.xiaoman_receipt_id is None and row.sync_status == "uncertain"
    recovery.recover_late_results(db)
    assert row.recovery_kind == "blocked"


@pytest.mark.parametrize("host_offset", [-7, 0])
def test_recovery_dates_follow_beijing_midnight_not_server_timezone(db, order, monkeypatch, host_offset):
    # Simulate a host clock returning its local date unless explicitly given a timezone.
    instant = datetime(2026, 10, 8, 15, 59, 30, tzinfo=timezone.utc)
    class HostDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz or timezone(timedelta(hours=host_offset)))
    monkeypatch.setattr(clock, "datetime", HostDateTime)
    values = recovery.retry_values(0, "prepare_retry")
    assert values["next_attempt_at"] == datetime(2026, 10, 9, 0, 0, 30)
    assert values["next_attempt_at"].tzinfo is None
