"""Standalone OpenSSH forced command for fetching public radar website pages."""

import base64
from contextlib import closing
from http.client import HTTPSConnection
import ipaddress
import json
import signal
import socket
import ssl
import sys
from urllib.parse import quote, urljoin, urlsplit

MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 4 * ((MAX_BODY_BYTES + 2) // 3) + 32 * 1024
MAX_REDIRECTS = 5
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/rss+xml", "application/atom+xml")
_URI_SAFE = "/%:@!$&'()*+,;=-._~"
_NAT64_NETWORKS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def _public_address(value):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            address = address.ipv4_mapped
        elif (
            address.is_site_local or address.sixtofour or address.teredo
            or any(address in network for network in _NAT64_NETWORKS)
        ):
            return False
    return address.is_global and not address.is_multicast


def _validated_target(url):
    if not isinstance(url, str) or not url or len(url) > 4096 or any(ord(char) < 32 for char in url):
        raise ValueError("Invalid website URL")
    target = urlsplit(url)
    if target.scheme != "https" or not target.hostname or target.port not in {None, 443}:
        raise ValueError("Public HTTPS on port 443 is required")
    if target.username is not None or target.password is not None:
        raise ValueError("URL credentials are forbidden")
    host = target.hostname.rstrip(".").encode("idna").decode("ascii")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Non-public host")
    addresses = list(dict.fromkeys(
        row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ))
    if not addresses or not all(_public_address(address) for address in addresses):
        raise ValueError("Non-public DNS answer")
    return target, host, addresses


def _connect(host, addresses):
    tls = ssl.create_default_context()
    tls.set_alpn_protocols(["http/1.1"])
    tls.post_handshake_auth = True
    last_error = None
    for address in addresses:
        try:
            with socket.create_connection((address, 443), timeout=5) as raw:
                connection = tls.wrap_socket(raw, server_hostname=host)
                connection.settimeout(15)
                return connection
        except OSError as exc:
            last_error = exc
    raise OSError("Public HTTPS connection failed") from last_error


def fetch(url, *, etag=None):
    headers = {"User-Agent": "Leshine-Ark-Project-Radar/1.0", "Connection": "close"}
    if etag is not None:
        if (
            not isinstance(etag, str) or not etag or len(etag) > 255
            or any(not 32 <= ord(char) <= 126 for char in etag)
        ):
            raise ValueError("Invalid ETag")
        headers["If-None-Match"] = etag
    for hop in range(MAX_REDIRECTS + 1):
        target, host, addresses = _validated_target(url)
        path = quote(target.path or "/", safe=_URI_SAFE)
        if target.query:
            path += "?" + quote(target.query, safe=_URI_SAFE + "?")
        with closing(HTTPSConnection(host, timeout=15)) as connection:
            connection.sock = _connect(host, addresses)
            authority = f"[{host}]" if ":" in host else host
            connection.request("GET", path, headers={"Host": authority, **headers})
            with connection.getresponse() as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if hop == MAX_REDIRECTS or not location:
                        raise ValueError("Invalid redirect")
                    url = urljoin(url, location)
                    continue
                content_type = response.getheader("Content-Type", "").lower()
                if response.status == 304 and etag:
                    body = b""
                else:
                    if not 200 <= response.status < 300:
                        raise ValueError(f"Upstream HTTP {response.status}")
                    if content_type and not content_type.startswith(TEXT_TYPES):
                        raise ValueError("Unsupported content type")
                    if response.getheader("Content-Encoding", "identity").lower() != "identity":
                        raise ValueError("Unsupported content encoding")
                    if int(response.getheader("Content-Length", "0")) > MAX_BODY_BYTES:
                        raise ValueError("Website response too large")
                    body = response.read(MAX_BODY_BYTES + 1)
                    if len(body) > MAX_BODY_BYTES:
                        raise ValueError("Website response too large")
                return {
                    "url": url, "status_code": response.status,
                    "content": base64.b64encode(body).decode("ascii"),
                    "content_type": content_type, "encoding": response.headers.get_content_charset() or "utf-8",
                    "etag": response.getheader("ETag"),
                }
    raise ValueError("Invalid redirect")


def main():
    signal.alarm(23)
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("Request too large")
        request = json.loads(raw)
        if not isinstance(request, dict) or set(request) != {"url", "etag"}:
            raise ValueError("Invalid request")
        result = json.dumps(fetch(request["url"], etag=request["etag"]), ensure_ascii=True).encode("ascii")
        if len(result) > MAX_RESPONSE_BYTES:
            raise ValueError("Encoded response too large")
        sys.stdout.buffer.write(result)
    except Exception as exc:
        print(f"Project radar Singapore worker failed ({type(exc).__name__})", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
