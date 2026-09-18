"""Durable snapshots never substitute stale data for a live balance check."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.invoice.okki_client import OkkiApiError
from app.receipt import receipt_index as index, remote


def row(identity="1", order="a", amount="5.00", stamp="2026-09-18 10:00:00"):
    return dict(cash_collection_id=identity, cash_collection_no="HK" + identity,
                order_id=order, amount=amount, currency="USD", collect_status=1,
                collection_date="2026-09-18", update_time=stamp)


@pytest.fixture
def state(monkeypatch, tmp_path):
    state = SimpleNamespace(rows=[row()], now=datetime(2026, 9, 18, 10, 1), full=0, calls=[])
    monkeypatch.setattr(index, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(index, "beijing_now", lambda: state.now)
    monkeypatch.setattr(index, "get_settings", lambda: SimpleNamespace(OKKI_API_BASE="https://test.invalid", OKKI_CLIENT_ID="test"))
    def full(*args, **kwargs):
        state.full += 1
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


def test_private_persistent_cache_reused_with_three_live_requests(state):
    assert index.verified_rows(None)[0]["amount"] == "5.00"
    assert state.full == 1
    # No in-memory snapshot exists; each call reopens the durable file.
    assert index.verified_rows(None)[0]["amount"] == "5.00"
    assert state.full == 1 and len(state.calls) == 3
    assert state.calls[0]["start_time"] == "2026-09-18 10:00:00"


@pytest.mark.parametrize("damage", ["json", "checksum", "source", "watermark", "duplicate"])
def test_damaged_cache_rebuilds(state, damage):
    index.verified_rows(None)
    path = next(index.CACHE_ROOT.glob("*.json"))
    envelope = json.loads(path.read_text())
    if damage == "json":
        path.write_text("broken")
    else:
        payload = envelope["payload"]
        if damage == "checksum": payload["rows"][0]["amount"] = "1.00"
        if damage == "source": payload["source"] = "wrong"
        if damage == "watermark": payload["watermark"] = "2099-01-01 00:00:00"
        if damage == "duplicate": payload["rows"] *= 2
        if damage == "checksum": path.write_text(json.dumps(envelope))
        else: index._save(path, payload)
    index.verified_rows(None)
    assert state.full == 2


def test_changes_move_order_and_update_amount_and_financial_status(state):
    index.verified_rows(None)
    state.now = datetime(2026, 9, 18, 10, 3)
    state.rows[0].update(order_id="b", amount="50.00", collect_status=0, update_time="2026-09-18 10:02:00")
    assert remote.order_receipts(None, "a") == []
    result = remote.order_receipts(None, "b")
    assert result[0]["amount"] == "50.00" and result[0]["collect_status"] == 0
    assert state.full == 1


def test_deleted_then_added_with_unchanged_total_rebuilds(state):
    index.verified_rows(None)
    state.now = datetime(2026, 9, 18, 10, 3)
    state.rows = [row("2", stamp="2026-09-18 10:02:00")]
    assert index.verified_rows(None)[0]["cash_collection_id"] == "2"
    assert state.full == 2


def test_incremental_overflow_rebuilds_instead_of_truncating(state):
    index.verified_rows(None)
    state.rows = [row(str(i)) for i in range(101)]
    assert len(index.verified_rows(None)) == 101 and state.full == 2


def test_network_failure_never_returns_stale_balance(state, monkeypatch):
    index.verified_rows(None)
    monkeypatch.setattr(remote, "read", lambda *a: (_ for _ in ()).throw(OkkiApiError("offline")))
    with pytest.raises(OkkiApiError): index.verified_rows(None)
    assert state.full == 1


def test_older_complete_atomic_snapshot_can_win_without_losing_updates(state):
    index.verified_rows(None)
    path = next(index.CACHE_ROOT.glob("*.json"))
    old = json.loads(path.read_text())["payload"]
    state.now = datetime(2026, 9, 18, 10, 3)
    state.rows.append(row("2", stamp="2026-09-18 10:02:00"))
    assert len(index.verified_rows(None)) == 2
    index._save(path, old)  # Another process finishes its older full snapshot later.
    assert len(index.verified_rows(None)) == 2 and state.full == 1


def test_atomic_write_failure_preserves_previous_snapshot(state, monkeypatch):
    index.verified_rows(None)
    path = next(index.CACHE_ROOT.glob("*.json"))
    old = path.read_bytes()
    monkeypatch.setattr(index.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk error")))
    with pytest.raises(OSError): index.verified_rows(None)
    assert path.read_bytes() == old and not list(index.CACHE_ROOT.glob("*.tmp"))


def test_same_count_edit_after_delta_end_cannot_return_stale_amount(state, monkeypatch):
    index.verified_rows(None)
    original = remote.read
    def changing(db, path, params):
        if "start_time" not in params:
            state.rows[0].update(amount="50.00", update_time="2026-09-18 10:01:01")
        return original(db, path, params)
    monkeypatch.setattr(remote, "read", changing)
    # Real full rebuild must also validate its upper bound, not return this stale cache.
    monkeypatch.setattr(remote, "_window_order_receipts", lambda *a, **k: (_ for _ in ()).throw(ValueError("unstable")))
    with pytest.raises(ValueError): index.verified_rows(None)


def test_minimal_private_fields_exclude_remote_links_and_customer_data(state):
    state.rows[0].update(file_list=["private-url"], company_info={"name": "private-name"})
    index.verified_rows(None)
    content = next(index.CACHE_ROOT.glob("*.json")).read_text()
    assert "private-url" not in content and "private-name" not in content



def test_exactly_100_incremental_rows_remain_incremental(state):
    state.now = datetime(2026,9,18,10,10)
    index.verified_rows(None)
    state.now = datetime(2026,9,18,10,12)
    state.rows += [row(str(i),stamp="2026-09-18 10:11:00") for i in range(2,102)]
    assert len(index.verified_rows(None)) == 101
    assert state.full == 1


def test_different_client_uses_separate_cache(state,monkeypatch):
    index.verified_rows(None)
    monkeypatch.setattr(index,"get_settings",lambda:SimpleNamespace(OKKI_API_BASE="https://test.invalid",OKKI_CLIENT_ID="other"))
    index.verified_rows(None)
    assert state.full == 2 and len(list(index.CACHE_ROOT.glob("*.json"))) == 2


def test_failed_rebuild_does_not_advance_watermark(state,monkeypatch):
    index.verified_rows(None)
    path=next(index.CACHE_ROOT.glob("*.json"));old=path.read_bytes()
    state.rows=[]
    monkeypatch.setattr(remote,"_window_order_receipts",lambda *a,**k:(_ for _ in ()).throw(ValueError("incomplete")))
    with pytest.raises(ValueError):index.verified_rows(None)
    assert path.read_bytes() == old
