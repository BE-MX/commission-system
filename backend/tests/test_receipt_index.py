"""Shared snapshots never substitute stale data for a live balance check."""
import copy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.invoice.okki_client import OkkiApiError
from app.receipt import receipt_index as index, remote
from app.receipt.models import ReceiptIndexState


def row(identity="1", order="a", amount="5.00", stamp="2026-09-18 10:00:00"):
    return dict(cash_collection_id=identity, cash_collection_no="HK" + identity,
                order_id=order, amount=amount, currency="USD", collect_status=1,
                collection_date="2026-09-18", update_time=stamp)


@pytest.fixture
def state(monkeypatch):
    state = SimpleNamespace(rows=[row()], now=datetime(2026, 9, 18, 10, 1), full=0, calls=[])
    monkeypatch.setattr(index, "beijing_now", lambda: state.now)
    monkeypatch.setattr(index, "get_settings", lambda: SimpleNamespace(OKKI_API_BASE="https://test.invalid", OKKI_CLIENT_ID="test"))
    def full(*args, **kwargs):
        state.full += 1
        if kwargs.get("heartbeat"):
            kwargs["heartbeat"]()
        return [dict(r) for r in state.rows], state.now.strftime("%Y-%m-%d %H:%M:%S")
    monkeypatch.setattr(remote, "_window_order_receipts", full)
    def read(db, path, params):
        state.calls.append(dict(params))
        rows = sorted(state.rows, key=lambda r: r["update_time"], reverse=True)
        if "start_time" in params:
            rows = [r for r in rows if params["start_time"] <= r["update_time"] <= params["end_time"]]
        return {"list": [dict(r) for r in rows[:100]], "totalItem": len(rows)}
    monkeypatch.setattr(remote, "read", read)
    return state


def test_missing_index_blocks_caller_without_full_scan(db, state):
    with pytest.raises(index.IndexNotReady):
        index.verified_rows(db)
    assert state.full == 0 and state.calls == []
    assert index.refresh_background(db)
    assert index.verified_rows(db)[0]["amount"] == "5.00"
    assert state.full == 1 and len(state.calls) == 6


@pytest.mark.parametrize("damage", ["checksum", "source", "watermark", "duplicate"])
def test_damaged_index_only_background_rebuilds(db, state, damage):
    index.refresh_background(db)
    record = db.get(ReceiptIndexState, index._source())
    envelope = copy.deepcopy(record.snapshot)
    payload = envelope["payload"]
    if damage == "checksum":
        payload["rows"][0]["amount"] = "1.00"
    if damage == "source":
        payload["source"] = "wrong"
    if damage == "watermark":
        payload["watermark"] = "2099-01-01 00:00:00"
    if damage == "duplicate":
        payload["rows"] *= 2
    if damage != "checksum":
        import hashlib
        envelope["sha256"] = hashlib.sha256(index._encoded(payload)).hexdigest()
    record.snapshot = envelope
    db.commit()
    with pytest.raises(index.IndexNotReady):
        index.verified_rows(db)
    assert state.full == 1
    index.refresh_background(db)
    assert state.full == 2


def test_changes_move_order_and_update_amount_and_financial_status(db, state):
    index.refresh_background(db)
    state.now = datetime(2026, 9, 18, 10, 3)
    state.rows[0].update(order_id="b", amount="50.00", collect_status=0, update_time="2026-09-18 10:02:00")
    assert remote.order_receipts(db, "a") == []
    result = remote.order_receipts(db, "b")
    assert result[0]["amount"] == "50.00" and result[0]["collect_status"] == 0
    assert state.full == 1


def test_deleted_then_added_with_unchanged_total_blocks_then_rebuilds(db, state):
    index.refresh_background(db)
    state.now = datetime(2026, 9, 18, 10, 3)
    state.rows = [row("2", stamp="2026-09-18 10:02:00")]
    with pytest.raises(index.IndexNotReady):
        index.verified_rows(db)
    assert state.full == 1
    index.refresh_background(db)
    assert index.verified_rows(db)[0]["cash_collection_id"] == "2" and state.full == 2


def test_over_100_delta_splits_in_background_without_full_rebuild(db, state):
    index.refresh_background(db)
    state.now = datetime(2026, 9, 18, 10, 3)
    state.rows += [row(str(i), stamp="2026-09-18 10:02:" + ("00" if i < 70 else "01")) for i in range(2, 132)]
    assert len(index.verified_rows(db)) == 131
    assert state.full == 1
    assert index.refresh_background(db)
    assert len(index.verified_rows(db)) == 131 and state.full == 1
    assert any(c.get("start_time") == c.get("end_time") for c in state.calls)


def test_network_failure_never_returns_stale_balance(db, state, monkeypatch):
    index.refresh_background(db)
    monkeypatch.setattr(remote, "read", lambda *a: (_ for _ in ()).throw(OkkiApiError("offline")))
    with pytest.raises(OkkiApiError):
        index.verified_rows(db)
    assert state.full == 1


def test_same_count_edit_after_delta_end_cannot_return_stale_amount(db, state, monkeypatch):
    index.refresh_background(db)
    original = remote.read
    def changing(db, path, params):
        if "start_time" not in params:
            state.rows[0].update(amount="50.00", update_time="2026-09-18 10:01:01")
        return original(db, path, params)
    monkeypatch.setattr(remote, "read", changing)
    with pytest.raises(index.IndexNotReady):
        index.verified_rows(db)
    assert state.full == 1


def test_minimal_snapshot_excludes_links_and_customer_data(db, state):
    state.rows[0].update(file_list=["private-url"], company_info={"name": "private-name"})
    index.refresh_background(db)
    content = index._encoded(db.get(ReceiptIndexState, index._source()).snapshot)
    assert b"private-url" not in content and b"private-name" not in content


def test_exactly_100_incremental_rows_remain_incremental(db, state):
    state.now = datetime(2026, 9, 18, 10, 10)
    index.refresh_background(db)
    state.now = datetime(2026, 9, 18, 10, 12)
    state.rows += [row(str(i), stamp="2026-09-18 10:11:00") for i in range(2, 102)]
    assert len(index.verified_rows(db)) == 101 and state.full == 1


def test_different_client_has_separate_index(db, state, monkeypatch):
    index.refresh_background(db)
    monkeypatch.setattr(index, "get_settings", lambda: SimpleNamespace(OKKI_API_BASE="https://test.invalid", OKKI_CLIENT_ID="other"))
    with pytest.raises(index.IndexNotReady):
        index.verified_rows(db)
    index.refresh_background(db)
    assert state.full == 2 and db.query(ReceiptIndexState).count() == 2


def test_failed_rebuild_preserves_snapshot_and_watermark(db, state, monkeypatch):
    index.refresh_background(db)
    old = copy.deepcopy(db.get(ReceiptIndexState, index._source()).snapshot)
    state.rows = []
    monkeypatch.setattr(remote, "_window_order_receipts", lambda *a, **k: (_ for _ in ()).throw(ValueError("incomplete")))
    with pytest.raises(ValueError):
        index.refresh_background(db)
    record = db.get(ReceiptIndexState, index._source())
    assert record.snapshot == old and record.lease_token is None


def test_active_refresh_lease_blocks_second_worker(db, state):
    index.refresh_background(db)
    record = db.get(ReceiptIndexState, index._source())
    record.lease_token, record.lease_until = "other-worker", state.now + timedelta(minutes=5)
    db.commit()
    assert index.refresh_background(db) is False and state.full == 1
    assert record.lease_token == "other-worker"


def test_lost_lease_cannot_publish_or_release_new_worker(db, state, monkeypatch):
    index.refresh_background(db)
    record = db.get(ReceiptIndexState, index._source())
    old = copy.deepcopy(record.snapshot)
    def stolen(*a, **k):
        record.lease_token = "new-worker"
        db.commit()
        return [row("2")], state.now.strftime("%Y-%m-%d %H:%M:%S")
    state.rows = []
    monkeypatch.setattr(remote, "_window_order_receipts", stolen)
    with pytest.raises(RuntimeError, match="lease lost"):
        index.refresh_background(db)
    db.refresh(record)
    assert record.snapshot == old and record.lease_token == "new-worker"


def test_split_scan_rechecks_earlier_window_for_same_count_edits(db, state, monkeypatch):
    index.refresh_background(db)
    state.now = datetime(2026, 9, 18, 10, 3)
    state.rows += [row(str(i), stamp="2026-09-18 10:02:" + ("00" if i < 70 else "01")) for i in range(2, 132)]
    original = remote.read
    def changed(db, path, params):
        if "start_time" not in params:
            state.rows[1]["amount"] = "999.00"
        return original(db, path, params)
    monkeypatch.setattr(remote, "read", changed)
    payload = index._load(db, index._source())
    with pytest.raises(ValueError, match="扫描期间变化"):
        index._refresh(db, payload, windows=True)
