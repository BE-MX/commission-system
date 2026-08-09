"""智能获客的外部身份与证据 URL 归一化。"""

import ipaddress
import re
from urllib.parse import urlparse


class InvalidExternalUrl(ValueError):
    pass


_NUMERIC_HOST_LABEL = re.compile(r"(?:0x[0-9a-f]+|0[0-7]+|[0-9]+)", re.IGNORECASE)


def _public_host(url: str, field: str) -> tuple[str, object]:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").strip(".").lower()
    if parsed.scheme not in ("http", "https") or not host or "." not in host:
        raise InvalidExternalUrl(f"{field} 必须是公开 http/https URL")
    if parsed.username or parsed.password or host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        raise InvalidExternalUrl(f"{field} 不允许凭据或本机地址")
    # urllib/ipaddress do not consistently recognize legacy numeric IPv4 forms
    # such as 0177.0.0.1 or 0x7f.0.0.1. Reject them before treating the host as DNS.
    if all(_NUMERIC_HOST_LABEL.fullmatch(label) for label in host.split(".")):
        raise InvalidExternalUrl(f"{field} 不允许数字形式的主机地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise InvalidExternalUrl(f"{field} 不允许内网地址")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidExternalUrl(f"{field} 域名无效") from exc
    if len(host) > 253:
        raise InvalidExternalUrl(f"{field} 域名无效")
    return host, parsed


def normalize_domain(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        raise InvalidExternalUrl("website 必填")
    if "://" not in raw:
        raw = f"https://{raw}"
    host, _parsed = _public_host(raw, "website")
    return host[4:] if host.startswith("www.") else host


def normalize_source_url(source_url: str) -> str:
    raw = (source_url or "").strip()
    _public_host(raw, "source_url")
    return raw
