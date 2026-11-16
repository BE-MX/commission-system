"""Annotate precise private research statements using facts from the active Run."""

import re
import unicodedata
from urllib.parse import urlsplit

from app.customer.models import CustomerSourceRecord

MARKER = "〔待核实〕"
_EMAIL = r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
_URL = r"https?://[^\s<>()\[\]{}\"'\x60，。；！？、〔〕]+"
_PHONE = r"(?<!\w)(?:\+?\d[ .()\-]*){7,15}(?!\d)"
_NUMBER = r"(?<![A-Za-z0-9])(?:[$€£¥]\s*)?[+-]?\d+(?:[.,]\d+)*(?:\s?(?:[%％]|万|亿|k\b|m\b|b\b))?(?![A-Za-z0-9])"
_LATIN_NAME = r"(?<![\w@.])(?:[A-Z][a-zÀ-ÖØ-öø-ÿ'’-]+\s+){1,4}[A-Z][a-zÀ-ÖØ-öø-ÿ'’-]+\b"
_NAMED_PERSON = r"(?:姓名|联系人|创始人|负责人|店主|法定代表人)[：:]\s*([\u3400-\u9fff·]{2,10})(?=[\s，。；、（(]|$)"
_ORDERED_LIST = re.compile(r"(?m)^[ \t]*(\d{1,9})[.)][ \t]+")
_TOKENS = re.compile(
    rf"(?P<link>!?\[[^\]\n]+\]\(<?(?P<link_url>{_URL})>?(?:[ \t]+\"[^\"]*\")?\))"
    rf"|(?P<url>{_URL})|(?P<email>{_EMAIL})|(?P<phone>{_PHONE})|(?P<number>{_NUMBER})",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _url(value: str) -> str:
    parsed = urlsplit(value)
    return parsed._replace(netloc=parsed.netloc.lower(), path=parsed.path.rstrip("/"), fragment="").geturl()


def _key(kind: str, value: str) -> str:
    if kind in {"url", "link"}:
        try:
            return _url(value)
        except ValueError:
            return value
    if kind == "phone":
        return re.sub(r"\D", "", value)
    if kind == "number":
        return _normalize(value).replace(",", "").replace(" ", "").lstrip("+")
    return _normalize(value)


def _text_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)
    elif isinstance(value, str) or type(value) in {int, float}:
        yield str(value)


def _tokens(text: str, names: set[str]):
    spans = []
    list_prefixes = {match.start(1) for match in _ORDERED_LIST.finditer(text)}
    for match in _TOKENS.finditer(text):
        kind = match.lastgroup
        end = match.end()
        if kind == "link":
            spans.append((match.start("link_url"), end, "url", match["link_url"]))
            continue
        if kind == "number" and match.start() in list_prefixes:
            continue
        raw = match.group().rstrip(".,:;!? ")
        if raw:
            spans.append((match.start(), match.start() + len(raw), kind, raw))
    for match in re.finditer(_LATIN_NAME, text):
        spans.append((*match.span(), "name", match.group()))
    for match in re.finditer(_NAMED_PERSON, text):
        spans.append((*match.span(1), "name", match[1]))
    for name in names:
        for match in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            spans.append((*match.span(), "name", match.group()))
    end = 0
    for span in sorted(spans, key=lambda item: (item[0], -item[1])):
        if span[0] >= end:
            yield span
            end = span[1]


def _has_name(name: str, evidence: list[str]) -> bool:
    escaped = re.escape(_normalize(name))
    return any(re.search(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", value) for value in evidence)


def validate_report(db, task, result: dict, facts) -> None:
    facts = [fact for fact in facts if fact.fact_layer == "source" and fact.fact_key != "social_profile_candidate"]
    by_fact = {fact.id: list(_text_values((fact.value_json or {}).get("value"))) for fact in facts}
    source_ids = {fact.source_record_id for fact in facts if fact.source_record_id is not None}
    sources = db.query(CustomerSourceRecord.source_url).filter(
        CustomerSourceRecord.id.in_(source_ids), CustomerSourceRecord.source_url.is_not(None)
    ).all() if source_ids else []
    evidence = [value for values in by_fact.values() for value in values] + [row[0] for row in sources]
    normalized = [_normalize(value) for value in evidence]
    token_keys = {(kind, _key(kind, token)) for value in evidence for _, _, kind, token in _tokens(value, set())}
    names = set(result.pop("names", []))
    info = (task.input_snapshot or {}).get("existing_information") or {}
    names.update(row["name"] for row in info.get("contact_names", []) if row.get("name"))

    report = result["report_markdown"]
    position = 0
    marked = []
    precise_count = unverified_count = 0
    for begin, end, kind, token in _tokens(report, names):
        precise_count += 1
        confirmed = _has_name(token, normalized) if kind == "name" else (kind, _key(kind, token)) in token_keys
        marked.append(report[position:end])
        if not confirmed:
            if not report.startswith(MARKER, end):
                marked.append(MARKER)
            unverified_count += 1
        position = end
    marked.append(report[position:])
    result["report_markdown"] = "".join(marked)
    result["precise_count"] = precise_count
    result["unverified_count"] = unverified_count

    citation_facts = {citation["citation_id"]: int(citation["evidence_ref"].split(":")[1])
                      for citation in result["citations"]}
    # Full claims only enter analysis if the observed fact actually states the same thing.
    result["verified_claims"] = [
        claim["statement"] for claim in result["claims"]
        if MARKER not in claim["statement"] and any(
            _normalize(claim["statement"]).rstrip(".。") == _normalize(value).rstrip(".。")
            for citation_id in claim["citation_ids"]
            for value in by_fact.get(citation_facts[citation_id], [])
        )
    ]
