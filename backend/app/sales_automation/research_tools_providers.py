"""Read-only provider adapters. An agent cannot supply a provider URL or payload."""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import monotonic
from urllib.parse import urlsplit

import httpx

from app.sales_automation import service

logger = logging.getLogger(__name__)
USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
DOMAIN = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
KEY = re.compile(r"[A-Za-z0-9._:-]{1,96}")
RUN_ID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
MONID_BASE = "https://api.monid.ai/v1"
SCAN_URL = "http://127.0.0.1:7912/scan"
MAX_RESPONSE = 512_000


@dataclass(frozen=True)
class Operation:
    provider: str
    endpoint: str
    source: str
    cap: int
    allowed_gaps: frozenset[str]


OPERATIONS = {
    "instagram_profile": Operation("apify", "/apify/instagram-profile-scraper", "instagram", 10000,
                                   frozenset({"subject_identity", "social_activity"})),
    "tiktok_profile": Operation("tikhub", "/api/v1/tiktok/web/fetch_user_profile", "tiktok", 10000,
                                frozenset({"subject_identity", "social_activity"})),
    "facebook_profile": Operation("apify", "/cleansyntax/facebook-profile-posts-scraper", "facebook", 20000,
                                  frozenset({"subject_identity", "social_activity"})),
    "linkedin_profile": Operation("ploid", "/linkedin/profile", "linkedin", 30000,
                                  frozenset({"subject_identity", "professional_identity"})),
    "hunter_domain_email": Operation("hunterio", "/domain-search", "hunter", 30000, frozenset({"contact"})),
}
RESERVED_PROFILE_PATHS = {"p", "reel", "reels", "explore", "accounts", "login", "watch", "share", "groups", "events"}


def normalize_target(tool: str, operation: str, target: str) -> str:
    if not isinstance(target, str) or not target or len(target) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in target):
        raise service.SalesAutomationError("研究工具目标格式无效")
    if tool == "username_scan" and operation == "username_scan" and USERNAME.fullmatch(target):
        return target.lower()
    op = OPERATIONS.get(operation) if tool == "monid" else None
    if op is None:
        raise service.SalesAutomationError("研究工具操作不在白名单")
    if op.source == "hunter":
        host = target.lower()
        if DOMAIN.fullmatch(host) and host.rsplit(".", 1)[-1] not in {"localhost", "local", "internal", "test", "invalid", "example", "onion", "i2p"}:
            return host
    else:
        host = f"{op.source}.com"
        if "://" not in target and op.source in {"instagram", "tiktok"}:
            handle = target.removeprefix("@")
        else:
            try:
                url = urlsplit(target)
            except ValueError as exc:
                raise service.SalesAutomationError("研究工具仅接受指定平台的公开主页") from exc
            if url.scheme != "https" or url.netloc.lower() not in {host, f"www.{host}"} or url.query or url.fragment:
                raise service.SalesAutomationError("研究工具仅接受指定平台的公开主页")
            path = url.path.strip("/")
            prefix = {"tiktok": "@", "linkedin": "in/"}.get(op.source, "")
            handle = path.removeprefix(prefix) if path.startswith(prefix) else ""
        if USERNAME.fullmatch(handle) and handle.lower() not in RESERVED_PROFILE_PATHS:
            lead = {"tiktok": "@", "linkedin": "in/"}.get(op.source, "")
            return f"https://www.{host}/{lead}{handle.lower()}"
    raise service.SalesAutomationError("研究工具目标格式无效")


def proxy_url(value: str) -> str:
    try:
        url = urlsplit(value)
        if (url.scheme in {"http", "https", "socks5", "socks5h"} and url.hostname and url.port
                and url.username and url.password and url.path in {"", "/"} and not url.query and not url.fragment):
            return value
    except ValueError:
        logger.warning("Private research proxy URL invalid")
    return ""


def is_enabled(settings, tool: str) -> bool:
    if tool == "username_scan":
        token = settings.PRIVATE_RESEARCH_MAIGRET_TOKEN
        return settings.PRIVATE_RESEARCH_MAIGRET_ENABLED and len(token) >= 24 and token.isascii() and token.isprintable()
    return bool(settings.PRIVATE_RESEARCH_MONID_ENABLED and settings.PRIVATE_RESEARCH_MONID_API_KEY
                and proxy_url(settings.PRIVATE_RESEARCH_EGRESS_PROXY))


def request_json(client, method, url, **kwargs):
    deadline = monotonic() + (95 if url == SCAN_URL else 25)
    with client.stream(method, url, **kwargs) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE or monotonic() >= deadline:
                raise ValueError("provider_response_limit")
        # Reject non-finite literals before persisting JSON to MySQL.
        parsed = json.loads(raw, parse_constant=_bad_constant)
        if not isinstance(parsed, dict):
            raise ValueError("invalid_provider_response")
        return parsed


def _bad_constant(_):
    raise ValueError("nonfinite_provider_response")


def _safe_public_url(value):
    if not isinstance(value, str) or len(value) > 512 or not value.isascii() or any(ord(c) < 33 for c in value):
        return ""
    try:
        url = urlsplit(value)
        if url.scheme in {"https", "http"} and DOMAIN.fullmatch(url.netloc.lower()) and not url.query and not url.fragment:
            return value
    except ValueError:
        logger.warning("Private research provider returned invalid candidate URL")
    return ""


def _candidate(source, value, url):
    return {"fact_type": {"maigret": "social_profile_candidate", "linkedin": "linkedin_person_profile",
                         "hunter": "personal_contact"}.get(source, "social_profile"),
            "value": value, "source_url": url}


def scan_result(raw):
    count = raw.get("checked")
    error_count = raw.get("connection_failures")
    unknown_count = raw.get("unknown")
    hits = raw.get("hits")
    if (not all(type(item) is int for item in (count, error_count, unknown_count))
            or not 0 <= error_count <= unknown_count <= count <= 500 or not isinstance(hits, list)):
        raise ValueError("invalid_scan_response")
    candidates = []
    for hit in hits[:60]:
        if not isinstance(hit, dict):
            continue
        url = _safe_public_url(hit.get("url"))
        site = hit.get("site")
        if url and isinstance(site, str) and 0 < len(site) <= 100:
            candidates.append(_candidate("maigret", {"platform": site, "profile_url": url}, url))
    if candidates:
        outcome = "candidate_found"
    elif hits or not count or unknown_count * 2 >= count:
        outcome = "unavailable"
    else:
        outcome = "no_matches"
    return {"outcome": outcome, "checked": count, "connection_failure_rate": error_count / count if count else None,
            "candidates": [{**item, "id": i} for i, item in enumerate(candidates, 1)]}


def scan(settings, target):
    with httpx.Client(timeout=95, trust_env=False, follow_redirects=False) as client:
        return request_json(client, "POST", SCAN_URL, json={"username": target},
                            headers={"Authorization": f"Bearer {settings.PRIVATE_RESEARCH_MAIGRET_TOKEN}"})


def monid_client(settings):
    return httpx.Client(proxy=proxy_url(settings.PRIVATE_RESEARCH_EGRESS_PROXY), timeout=20, trust_env=False,
                        follow_redirects=False, headers={"Authorization": f"Bearer {settings.PRIVATE_RESEARCH_MONID_API_KEY}"})


def _expected_max_price(price):
    if not isinstance(price, dict) or price.get("currency") != "USD" or price.get("type") not in {"PER_CALL", "PER_RESULT"}:
        return None
    try:
        amount = Decimal(str(price["amount"]))
        fee = Decimal(str(price.get("flatFee") or 0))
        if amount.is_finite() and fee.is_finite() and amount >= 0 and fee >= 0:
            # Each allowlisted adapter requests at most one result.
            return (amount + fee) * 1_000_000
    except (KeyError, InvalidOperation):
        logger.warning("Private research provider returned unsupported price data")
    return None


def monid_prepare(client, operation, target, reservation):
    op = OPERATIONS[operation]
    slug = target.rsplit("/", 1)[-1].removeprefix("@")
    payload = {"provider": op.provider, "endpoint": op.endpoint}
    inspect = request_json(client, "POST", f"{MONID_BASE}/inspect", json=payload)
    price = _expected_max_price(inspect.get("price"))
    if inspect.get("provider") != op.provider or inspect.get("endpoint") != op.endpoint or price is None or price > reservation:
        return None
    # Optional structured section supported by Monid's proxy. Do not expose it to callers.
    params = {
        "instagram": ("body", {"usernames": [slug]}),
        "tiktok": ("queryParams", {"uniqueId": slug}),
        # The connector requires max_posts even in profile-details mode.
        "facebook": ("body", {"endpoint": "details_by_url", "urls_text": target, "max_posts": 1}),
        "linkedin": ("queryParams", {"url": target}),
        "hunter": ("body", {"domain": target, "limit": 1}),
    }
    field, values = params[op.source]
    return {**payload, "input": {field: values}}


def monid_result(operation, target, body):
    """Materialize minimal provider-owned candidate values without copying raw payload to facts."""
    op = OPERATIONS[operation]
    if body.get("status") != "COMPLETED" or (body.get("providerResponse") or {}).get("httpStatus") != 200:
        return {"outcome": "no_data", "candidates": []}
    output = body.get("output", (body.get("providerResponse") or {}).get("data"))
    if isinstance(output, list):
        output = output[0] if len(output) == 1 else None
    if not isinstance(output, dict):
        return {"outcome": "no_data", "candidates": []}
    candidates = []
    if op.source == "hunter":
        for obj in (output.get("data") or {}).get("emails", [])[:1]:
            email = obj.get("value") if isinstance(obj, dict) else None
            if isinstance(email, str) and len(email) <= 254 and re.fullmatch(r"[^\s@]+@" + re.escape(target), email, re.I):
                source_urls = [_safe_public_url(item.get("uri")) for item in (obj.get("sources") or [])
                               if isinstance(item, dict)]
                candidates.append(_candidate("hunter", {"email": email, "domain": target},
                                             next((url for url in source_urls if url), None)))
    else:
        if op.source == "facebook":
            output = output.get("profile")
        elif op.source == "tiktok":
            info = (output.get("data") or output).get("userInfo") or {}
            output = {**(info.get("user") or {}), **(info.get("stats") or {})}
        if isinstance(output, dict):
            keys = {"username", "fullName", "name", "headline", "summary", "nickname", "uniqueId",
                    "signature", "biography", "followerCount", "followersCount", "postsCount",
                    "verified", "location", "intro", "publicIdentifier", "profile_id"}
            values = {k: v[:500] if isinstance(v, str) else v for k, v in output.items()
                      if k in keys and (isinstance(v, str) and v or type(v) in {int, bool})}
            slug = target.rsplit("/", 1)[-1].removeprefix("@")
            identifiers = [values[k] for k in ("username", "uniqueId", "publicIdentifier") if k in values]
            if values and all(isinstance(value, str) and value.lower() == slug for value in identifiers):
                raw_urls = [output[k] for k in ("url", "linkedinUrl") if output.get(k) not in (None, "")]
                urls_match = all(_matching_profile_url(operation, url, target) for url in raw_urls)
                if (identifiers or raw_urls) and urls_match:
                    candidates.append(_candidate(op.source, {"profile_url": target, **values}, target))
    return {"outcome": "candidate_found" if candidates else "no_data",
            "candidates": [{**item, "id": i} for i, item in enumerate(candidates, 1)]}


def _matching_profile_url(operation, value, target):
    if not isinstance(value, str) or not value.startswith("https://"):
        return False
    try:
        return normalize_target("monid", operation, value) == target
    except service.SalesAutomationError:
        return False


def reported_charge(body):
    billing = body.get("billing")
    charge = (billing.get("reportedCost") or {}) if isinstance(billing, dict) else {}
    value = charge.get("value")
    if charge.get("currency") == "USD" and charge.get("unit") == "MICRO_DOLLAR" and type(value) is int and 0 <= value <= 2**31 - 1:
        return value
    cost = body.get("cost")
    if isinstance(cost, dict) and cost.get("currency") == "USD":
        try:
            micro = Decimal(str(cost["value"])) * 1_000_000
            if micro.is_finite() and 0 <= micro <= 2**31 - 1 and micro == micro.to_integral_value():
                return int(micro)
        except (KeyError, InvalidOperation):
            logger.warning("Private research provider returned invalid settlement data")
    return None
