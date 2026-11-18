import httpx
import pytest

from app.factory_inbound import okki_transport as module
from app.invoice.okki_client import OkkiApiError


@pytest.fixture(autouse=True)
def mock_boundary(monkeypatch):
    def forbid(*args, **kwargs):
        pytest.fail("Unexpected external connection")

    monkeypatch.setattr(module.httpx, "get", forbid)
    monkeypatch.setattr(module.httpx, "post", forbid)
    monkeypatch.setattr(module.okki_client, "_base_url", lambda: "https://okki.invalid")
    keys = []

    def token(*, scope):
        assert scope == "invoices purchaseOrder"
        keys.append(scope)
        return "fake-token", None

    monkeypatch.setattr(module.okki_client, "fetch_token", token)
    return keys


@pytest.mark.parametrize(("method", "path", "number_field", "id_field"), [
    ("find_purchase", "/v1/purchaseOrder/info", "purchase_order_no", "purchase_order_id"),
    ("find_inbound", "/v1/invoices/purchaseInbound/info", "serial_id", "inbound_invoice_id"),
])
def test_exact_read_returns_authoritative_id_detail(monkeypatch, mock_boundary, method, path, number_field, id_field):
    calls = []

    def get(url, *, params, **kwargs):
        assert url == f"https://okki.invalid{path}"
        calls.append(params)
        if len(calls) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"code": 0, "data": {
            number_field: "FI-001", id_field: "987001", "status": len(calls),
        }})

    monkeypatch.setattr(module.httpx, "get", get)
    detail = getattr(module.OkkiTransport(), method)("FI-001")
    assert detail["status"] == 3
    assert calls == [{number_field: "FI-001"}, {number_field: "FI-001"}, {id_field: 987001}]
    assert len(mock_boundary) == 2


@pytest.mark.parametrize(("status", "body", "absent"), [
    (200, {"code": 404, "message": "Not Found Resource", "data": None}, True),
    (200, {"code": 404, "message": "Not Found Resource.", "data": {}}, True),
    (404, {"code": 404, "message": "Not Found Resource"}, False),
    (200, {"code": 404, "message": "No Privilege"}, False),
    (200, {"code": 404, "message": "Not Found Resource", "data": False}, False),
    (200, {"code": 404, "message": "Not Found Resource", "error": "denied"}, False),
    (200, {"code": 404, "message": "Not Found Resource", "data": {"inbound_invoice_id": 7}}, False),
])
def test_only_exact_not_found_is_absence(monkeypatch, status, body, absent):
    monkeypatch.setattr(module.httpx, "get", lambda *a, **kw: httpx.Response(status, json=body))
    if absent:
        assert module.OkkiTransport().find_inbound("FI-001") is None
    else:
        with pytest.raises(OkkiApiError):
            module.OkkiTransport().find_inbound("FI-001")


def test_number_found_id_not_found_is_not_absence(monkeypatch):
    responses = iter([
        {"code": 0, "data": {"serial_id": "FI-001", "inbound_invoice_id": 123}},
        {"code": 404, "message": "Not Found Resource"},
    ])
    monkeypatch.setattr(module.httpx, "get", lambda *a, **kw: httpx.Response(200, json=next(responses)))
    with pytest.raises(OkkiApiError, match="身份不一致"):
        module.OkkiTransport().find_inbound("FI-001")


def test_purchase_create_requires_gate_and_accepts_documented_code_zero(monkeypatch, mock_boundary):
    body = {"purchase_order_no": "FI-001"}
    with pytest.raises(module.OkkiMutationRejected):
        module.OkkiTransport().create_purchase(body)
    assert mock_boundary == []

    calls = []

    def post(url, *, json, **kwargs):
        calls.append((url, json))
        return httpx.Response(200, json={"code": 0, "data": {"purchase_order_id": 987}})

    monkeypatch.setattr(module.httpx, "post", post)
    client = module.OkkiTransport(before_send=lambda path, payload: calls.append((path, payload)))
    assert client.create_purchase(body) == 987
    path = "/v1/purchaseOrder/push"
    assert calls == [(path, body), (f"https://okki.invalid{path}", body)]


@pytest.mark.parametrize("response", [
    httpx.Response(401), httpx.Response(502), httpx.Response(200, json={"code": 404, "message": "No Privilege"}),
    httpx.Response(200, json={"code": 0, "data": {"inbound_invoice_id": 654}}),
    httpx.Response(200, json={"code": 0, "data": {}}),
    httpx.ReadTimeout("simulated"),
])
def test_unknown_completion_is_never_replayed(monkeypatch, response):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(module.httpx, "post", post)
    client = module.OkkiTransport(before_send=lambda *a: None)
    with pytest.raises(module.OkkiOutcomeUncertainError):
        client.push_inbound({"serial_id": "FI-001", "status": 2, "inbound_id": 987})
    assert calls == ["https://okki.invalid/v1/invoices/purchaseInbound/push"]
