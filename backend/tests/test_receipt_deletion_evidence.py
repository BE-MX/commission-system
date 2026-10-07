"""Deleted-list evidence is required when a soft-deleted receipt remains readable."""
from copy import deepcopy

import pytest

from app.invoice import lifecycle_remote, okki_client
from app.receipt import deletion_evidence, remote


@pytest.fixture
def proof(monkeypatch):
    detail = {"cash_collection_id": "88", "order_id": "123", "currency": "USD",
              "update_time": "2026-10-01 09:08:34", "collect_status": 1, "enable_flag": 0}
    state = {"detail": detail, "active": [], "deleted": [deepcopy(detail)], "calls": []}
    monkeypatch.setattr(lifecycle_remote, "read", lambda *a: deepcopy(state["detail"]))
    monkeypatch.setattr(remote, "order_receipts", lambda *a: deepcopy(state["active"]))
    def read(db, path, params):
        assert path == "/v1/invoices/receipt/list"
        assert params["start_time"] == params["end_time"] == "2026-10-01 09:08:34"
        assert params["count"] == 100 and params["start_index"] == 1
        state["calls"].append(params["removed"])
        rows = state["deleted"] if params["removed"] == 1 else state["active"]
        return {"list": deepcopy(rows), "totalItem": len(rows)}
    monkeypatch.setattr(remote, "read", read)
    return state


def absent():
    return deletion_evidence.absent(None, "123", "88", "USD")


def test_soft_deleted_detail_requires_stable_deleted_and_active_lists(proof):
    assert absent() is True
    assert proof["calls"] == [0, 1, 0, 1]


def test_active_receipt_is_not_deleted_even_if_disabled_financially(proof):
    proof["active"] = [deepcopy(proof["detail"])]
    proof["deleted"] = []
    assert absent() is False


def test_absence_from_active_list_without_deleted_membership_is_not_proof(proof):
    proof["deleted"] = []
    assert absent() is False


def test_clear_not_found_still_requires_active_index_absence(proof):
    proof["detail"] = None
    assert absent() is True
    proof["active"] = [{"cash_collection_id": "88"}]
    assert absent() is False


@pytest.mark.parametrize("field,value", [("order_id", "other"), ("currency", "EUR"),
                                        ("update_time", None)])
def test_invalid_or_changed_detail_never_proves_deletion(proof, field, value):
    proof["detail"][field] = value
    with pytest.raises(ValueError):
        absent()


@pytest.mark.parametrize("problem", ["count", "duplicate", "window", "binding", "both", "changed", "network"])
def test_incomplete_inconsistent_or_failed_reads_never_release_receipt(proof, monkeypatch, problem):
    original = remote.read
    def read(db, path, params):
        data = original(db, path, params)
        if problem == "network":
            raise okki_client.OkkiApiError("unavailable")
        if params["removed"] == 1:
            if problem == "count":
                data["totalItem"] = 101
            elif problem == "duplicate":
                data["list"] *= 2
                data["totalItem"] = 2
            elif problem == "window":
                data["list"][0]["update_time"] = "2026-10-02 09:08:34"
            elif problem == "binding":
                data["list"][0]["order_id"] = "other"
            elif problem == "changed" and len(proof["calls"]) > 2:
                data = {"list": [], "totalItem": 0}
        return data
    monkeypatch.setattr(remote, "read", read)
    if problem == "both":
        proof["active"] = [deepcopy(proof["detail"])]
    with pytest.raises((ValueError, okki_client.OkkiApiError)):
        absent()


def test_detail_move_during_list_reads_is_rejected(proof, monkeypatch):
    reads = iter([deepcopy(proof["detail"]), {**proof["detail"], "update_time": "2026-10-02 09:08:34"}])
    monkeypatch.setattr(lifecycle_remote, "read", lambda *a: next(reads))
    with pytest.raises(ValueError):
        absent()
