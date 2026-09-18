"""HTTP boundary tests: no real OKKI credentials or network requests."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.core.time import beijing_now
from app.invoice import okki_client
from app.receipt import remote, sync_service
from app.receipt.models import Receipt


@pytest.fixture
def payload_row():
    return SimpleNamespace(xiaoman_order_id="2001", amount=Decimal("123.45"), currency="USD",
        collection_date=date(2026, 9, 17), payment_type="T/T", bank_charge=Decimal("2.34"),
        receipt_no="HK-TEST-ONLY", remark="test")


@pytest.fixture(autouse=True)
def fake_auth(monkeypatch):
    monkeypatch.setattr(okki_client, "ensure_access_token", lambda *a, **k: "test-only-not-a-real-token")
    monkeypatch.setattr(okki_client, "_base_url", lambda: "https://test.invalid")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("unexpected GET"))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("unexpected POST"))


def prepare(monkeypatch, fields=None):
    def get(url, **kwargs):
        data = ["T/T"] if url.endswith("/types") else (fields or [])
        return httpx.Response(200, json={"code": 200, "data": data})
    monkeypatch.setattr(httpx, "get", get)


@pytest.mark.parametrize("persistent", [False, True])
def test_receipt_get_retries_network_timeout_only_once(monkeypatch, persistent):
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1 or persistent:
            raise httpx.ReadTimeout("test timeout")
        return httpx.Response(200, json={"code": 200, "data": ["T/T"]})
    monkeypatch.setattr(httpx, "get", get)
    if persistent:
        with pytest.raises(okki_client.OkkiApiError): remote.receipt_types(None)
    else:
        assert remote.receipt_types(None) == ["T/T"]
    assert len(calls) == 2


def test_real_helper_unwraps_types_fields_and_preserves_rate(monkeypatch, payload_row):
    prepare(monkeypatch, [{"id": "exchange_rate_usd", "require": 1}])
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(200, json={"code": 200, "data": {"cash_collection_id": 700, "cash_collection_no": "HK700"}})
    monkeypatch.setattr(httpx, "post", post)
    fence = []
    result = remote.push(None, payload_row, {"exchange_rate": 725}, lambda: fence.append(True))
    assert result["cash_collection_id"] == 700 and fence == [True]
    assert calls[0]["amount"] == "123.45" and calls[0]["bank_charge"] == "2.34"
    assert calls[0]["exchange_rate"] == "725" and calls[0]["collect_status"] == 1
    assert "file_list" not in calls[0] and "exchange_rate_usd" not in calls[0]


@pytest.mark.parametrize("response", [httpx.Response(500, json={"message": "test"}),
    httpx.Response(200, text="not-json"), httpx.Response(200, json={"code": 200, "data": {}})])
def test_ambiguous_http_result_never_becomes_retryable(monkeypatch, payload_row, response):
    prepare(monkeypatch)
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or response)
    with pytest.raises(okki_client.OkkiOutcomeUncertainError):
        remote.push(None, payload_row, {"exchange_rate": 725})
    assert calls == [1]


def test_fence_after_all_read_preparation_prevents_post(monkeypatch, payload_row):
    prepare(monkeypatch)
    def lost():
        raise ValueError("lease lost")
    with pytest.raises(ValueError, match="lease lost"):
        remote.push(None, payload_row, {"exchange_rate": 725}, lost)


def test_custom_required_field_blocks_before_post(monkeypatch, payload_row):
    prepare(monkeypatch, [{"id": "1234", "name": "收款账号", "require": 1}])
    with pytest.raises(ValueError, match="收款账号"):
        remote.push(None, payload_row, {"exchange_rate": 725})


def test_list_exhausts_pages_filters_order_and_rejects_changed_total(monkeypatch):
    pages = {1: {"list": [{"cash_collection_id": "1", "order_id": "other"}], "totalItem": 2},
             2: {"list": [{"cash_collection_id": "2", "order_id": "2001"}], "totalItem": 2}}
    monkeypatch.setattr(remote, "read", lambda db, path, params: pages[params["start_index"]])
    assert remote.order_receipts(None, "2001") == pages[2]["list"]
    pages[2]["totalItem"] = 3
    with pytest.raises(ValueError, match="变动"):
        remote.order_receipts(None, "2001")
    pages[2]["totalItem"] = 2
    pages[2]["list"][0]["cash_collection_id"] = "1"
    with pytest.raises(ValueError, match="重复"):
        remote.order_receipts(None, "2001")


def test_unassociated_remote_receipt_does_not_block_other_orders(monkeypatch):
    monkeypatch.setattr(remote, "read", lambda *args: {"totalItem": 2, "list": [
        {"cash_collection_id": "1", "order_id": 0, "opportunity_id": 0},
        {"cash_collection_id": "2", "order_id": 2001, "amount": 500}]})
    assert remote.order_receipts(None, "2001")[0]["cash_collection_id"] == "2"


def window_rows():
    return ([{"cash_collection_id": str(i), "order_id": "2001", "update_time": "2026-06-06 00:00:00"} for i in range(99)]
            + [{"cash_collection_id": "tie" + str(i), "order_id": "2001", "update_time": "2026-06-05 21:42:14"} for i in range(2)]
            + [{"cash_collection_id": "old", "order_id": "other", "update_time": "2026-06-04 00:00:00"}])


def window_reader(rows, mutation=None):
    def read(db, path, params):
        filtered = [r for r in rows if "start_time" not in params or params["start_time"] <= r["update_time"] <= params["end_time"]]
        result = {"list": filtered[:100], "totalItem": len(filtered)}
        return mutation(params, result) if mutation else result
    return read


def test_time_window_recovers_entire_tied_boundary_without_using_bad_pages(monkeypatch):
    rows = window_rows()
    monkeypatch.setattr(remote, "read", window_reader(rows))
    def overlap(*args):
        raise remote._PageOverlap("duplicate")
    monkeypatch.setattr(remote, "_paged_order_receipts", overlap)
    result = remote.order_receipts(None, "2001")
    assert {r["cash_collection_id"] for r in result} == {r["cash_collection_id"] for r in rows if r["order_id"] == "2001"}
    assert len(result) == 101


@pytest.mark.parametrize("problem", ["missing_boundary", "duplicate_boundary", "moved_row", "changed_total"])
def test_time_window_rejects_incomplete_or_changed_boundaries(monkeypatch, problem):
    def mutate(params, result):
        if params.get("start_time") == "2026-06-05 21:42:14":
            if problem == "missing_boundary": result["list"] = result["list"][:1]
            if problem == "duplicate_boundary": result["list"] = [result["list"][0]] * 2
            if problem == "moved_row": result["list"] = [{**r, "update_time": "2026-06-06 00:00:00"} for r in result["list"]]
        if problem == "changed_total" and params.get("end_time") == "2026-06-05 21:42:13": result["totalItem"] += 1
        return result
    monkeypatch.setattr(remote, "read", window_reader(window_rows(), mutate))
    with pytest.raises(ValueError): remote._window_order_receipts(None, "2001")


def test_time_window_rejects_more_than_one_page_in_one_second(monkeypatch):
    rows = [{"cash_collection_id": str(i), "order_id": "2001", "update_time": "2026-06-05 21:42:14"} for i in range(101)]
    monkeypatch.setattr(remote, "read", window_reader(rows))
    with pytest.raises(ValueError, match="同秒"):
        remote._window_order_receipts(None, "2001")


@pytest.mark.parametrize("root", ["unfiltered", "frozen"])
def test_time_window_rejects_final_root_total_change(monkeypatch, root):
    calls = {}
    def mutate(params, result):
        key = (params.get("start_time"), params.get("end_time"))
        calls[key] = calls.get(key, 0) + 1
        selected = key == (None, None) if root == "unfiltered" else key[0] == "1970-01-01 00:00:00"
        if selected and calls[key] == 2:
            result["totalItem"] += 1
        return result
    monkeypatch.setattr(remote, "read", window_reader(window_rows(), mutate))
    with pytest.raises(ValueError, match="扫描期间"):
        remote._window_order_receipts(None, "2001")


def test_worker_does_not_post_after_lease_expires_during_read(db, monkeypatch):
    from app.invoice.models import Invoice
    from app.receipt import attachments
    invoice = Invoice(invoice_no="LEASE-TEST", order_type="production", customer_id="101", customer_name="Test",
        invoice_date=date(2026, 9, 17), currency="USD", total_amount=500, xiaoman_order_id="2001", sync_status="synced")
    db.add(invoice); db.flush()
    row = Receipt(receipt_no="HK-LEASE", invoice_id=invoice.id, source="manual", request_key="lease-test-key",
        request_hash="test", amount=100, currency="USD", collection_date=date(2026, 9, 17), payment_type="T/T",
        attachment_ids=["test-proof"], customer_id="101", xiaoman_order_id="2001", created_by=1)
    db.add(row); db.commit()
    def slow_read(db, invoice):
        row.lease_until = beijing_now() - timedelta(seconds=1)
        db.commit()
        sync_service.recover_expired(db)
        return {"rows": [], "exchange_rate": 725}
    monkeypatch.setattr(remote, "order_snapshot", slow_read)
    monkeypatch.setattr(attachments, "bind", lambda *a: [])
    prepare(monkeypatch)
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "uncertain" and row.xiaoman_receipt_id is None
