import httpx
import pytest

from app.core import public_fetch
from app.mcp.public_web_tools import _validate_public_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "https://localhost/internal",
    "https://169.254.169.254/latest/meta-data",
    "https://example.com:8443/private",
])
def test_non_public_or_non_standard_targets_are_rejected(url):
    with pytest.raises(ValueError):
        _validate_public_url(url)


def test_redirect_to_private_network_is_never_requested(monkeypatch):
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://127.0.0.1/internal"})

    monkeypatch.setattr(public_fetch.socket, "getaddrinfo", lambda host, port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", port))])
    monkeypatch.setattr(public_fetch, "_validate_peer", lambda response: None)
    with pytest.raises(ValueError, match="公开"):
        public_fetch.fetch_public("https://example.com/start", transport=httpx.MockTransport(handler))
    assert requested == ["https://example.com/start"]


def test_response_size_limit_and_html_cleanup(monkeypatch):
    monkeypatch.setattr(public_fetch.socket, "getaddrinfo", lambda host, port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", port))])
    monkeypatch.setattr(public_fetch, "_validate_peer", lambda response: None)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 100)

    with pytest.raises(ValueError, match="大小限制"):
        public_fetch.fetch_public("https://example.com", max_bytes=10, transport=httpx.MockTransport(handler))

    cleaned = public_fetch.clean_html("<html><head><title>Radar</title><script>ignore()</script></head><body><h1>Hello</h1><a href='/changelog'>Changes</a></body></html>")
    assert cleaned["title"] == "Radar"
    assert "Hello" in cleaned["text"] and "ignore" not in cleaned["text"]
    assert cleaned["links"] == [{"href": "/changelog", "text": "Changes"}]


@pytest.mark.parametrize("include_content", [False, True])
def test_github_304_preserves_release_facts_and_allows_readme(monkeypatch, include_content):
    from datetime import datetime
    from types import SimpleNamespace
    from app.project_radar.fetcher import RadarFetcher

    target = SimpleNamespace(
        canonical_url="https://github.com/a/b", repo_etag="repo-old", release_etag="release-old",
        title="b", stars=12, license="MIT", language="Python", archived=True,
        version="v2.0.0", last_updated_at=datetime(2026, 11, 1, 8, 0),
    )
    monkeypatch.setattr(public_fetch.socket, "getaddrinfo", lambda host, port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", port))])
    monkeypatch.setattr(public_fetch, "_validate_peer", lambda response: None)
    requests = []

    def handler(request):
        path = request.url.path
        etag = request.headers.get("If-None-Match")
        requests.append((path, etag))
        if path == "/repos/a/b/readme":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="# Project README")
        return httpx.Response(304, headers={"etag": etag, "content-length": "6000000"})

    fetcher = RadarFetcher(transport=httpx.MockTransport(handler))
    result = fetcher.read_repo(target, include_content=include_content)
    assert result["unchanged"] is True
    assert result["facts"]["version"] == "v2.0.0"
    assert result["facts"]["last_updated_at"] == target.last_updated_at
    assert result["facts"]["archived"] is True
    assert result["repo_etag"] == "repo-old"
    assert result["release_etag"] == "release-old"
    expected_requests = [("/repos/a/b", "repo-old"), ("/repos/a/b/releases", "release-old")]
    if include_content:
        expected_requests.append(("/repos/a/b/readme", None))
    assert requests == expected_requests
    assert result["text"] == ("# Project README" if include_content else "")


def test_unconditional_304_is_rejected(monkeypatch):
    monkeypatch.setattr(public_fetch.socket, "getaddrinfo", lambda host, port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", port))])
    monkeypatch.setattr(public_fetch, "_validate_peer", lambda response: None)
    transport = httpx.MockTransport(lambda request: httpx.Response(304))

    with pytest.raises(RuntimeError) as exc:
        public_fetch.fetch_public("https://example.com", transport=transport)

    assert isinstance(exc.value.__cause__, httpx.HTTPStatusError)
    assert exc.value.__cause__.response.status_code == 304
