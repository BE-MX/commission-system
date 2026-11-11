from email.message import Message
import json
from types import SimpleNamespace

import pytest

from app.project_radar import singapore_fetch, singapore_worker


def _mock_origin(monkeypatch, *, status, headers):
    connected = []
    requests = []
    response_headers = Message()
    for name, value in headers.items():
        response_headers[name] = value

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def getheader(self, name, default=None):
            return response_headers.get(name, default)

        def read(self, size):
            raise AssertionError("Redirect and 304 responses have no body to read")

    response = Response()
    response.status = status
    response.headers = response_headers

    def resolve(host, port, **kwargs):
        address = "127.0.0.1" if host == "redirect.example" else "93.184.216.34"
        return [(2, 1, 6, "", (address, port))]

    def connect(host, addresses):
        connected.append((host, addresses))
        return object()

    monkeypatch.setattr(singapore_worker.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(singapore_worker, "_connect", connect)
    monkeypatch.setattr(singapore_worker, "HTTPSConnection", lambda *args, **kwargs: SimpleNamespace(
        request=lambda method, path, **options: requests.append((method, path, options["headers"])),
        getresponse=lambda: response, close=lambda: None,
    ))
    return connected, requests


def test_singapore_rejects_private_redirect_before_connecting(monkeypatch):
    connected, _ = _mock_origin(monkeypatch, status=302, headers={"Location": "https://redirect.example/secret"})
    with pytest.raises(ValueError, match="Non-public DNS answer"):
        singapore_worker.fetch("https://example.com/docs")
    assert connected == [("example.com", ["93.184.216.34"])]


def test_singapore_conditional_get_uses_public_ip_and_preserves_304(monkeypatch):
    connected, requests = _mock_origin(
        monkeypatch, status=304, headers={"Content-Length": "6000000", "ETag": '"current"'},
    )
    result = singapore_worker.fetch("https://example.com/docs?channel=stable", etag='"previous"')
    assert connected == [("example.com", ["93.184.216.34"])]
    method, path, headers = requests[0]
    assert (method, path, headers["Host"], headers["If-None-Match"]) == (
        "GET", "/docs?channel=stable", "example.com", '"previous"',
    )
    assert (result["status_code"], result["content"], result["etag"]) == (304, "", '"current"')
    with pytest.raises(ValueError, match="Upstream HTTP 304"):
        singapore_worker.fetch("https://example.com/docs")


def test_singapore_rejects_oversized_page_before_reading_body(monkeypatch):
    _mock_origin(monkeypatch, status=200, headers={"Content-Length": "6000000"})
    with pytest.raises(ValueError, match="Website response too large"):
        singapore_worker.fetch("https://example.com/docs")


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "::ffff:127.0.0.1", "224.0.0.1", "fe80::1", "fec0::1",
    "64:ff9b::a00:1", "64:ff9b:1::a00:1", "2002:a00:1::",
])
def test_singapore_worker_rejects_nonpublic_addresses(address):
    assert not singapore_worker._public_address(address)


def test_singapore_client_sends_site_url_only_via_stdin(monkeypatch):
    url = "https://example.com/docs?content=$(echo)"
    payload = {
        "url": url, "status_code": 200, "content": "aGVsbG8=",
        "content_type": "text/plain", "encoding": "utf-8", "etag": None,
    }
    calls = []

    def run(command, **options):
        calls.append(command)
        assert "StrictHostKeyChecking=yes" in command
        assert "ClearAllForwardings=yes" in command
        assert command[command.index("-S") + 1] == "none"
        assert command[-2:] == ["radar-singapore", "/usr/bin/false"]
        assert url not in command
        assert json.loads(options["input"]) == {"url": url, "etag": None}
        assert options["timeout"] == 30 and options["check"] is True
        return SimpleNamespace(stdout=json.dumps(payload).encode("ascii"))

    monkeypatch.setattr(singapore_fetch.subprocess, "run", run)
    assert singapore_fetch.fetch_via_singapore("radar-singapore", url).text == "hello"
    with pytest.raises(ValueError, match="host alias"):
        singapore_fetch.fetch_via_singapore("-oProxyCommand=unsafe", url)
    assert len(calls) == 1
