"""Pure rules for the B track: watermarks, prompt packs, strict result checks, weak matching.

Nothing here touches the database or the model; every rule is unit-tested.
"""

import hashlib
import json
import re
from pathlib import Path

PROTOCOL_VERSION = "unlinked_v1"
PROTOCOL_DIR = Path(__file__).resolve().parent.parent / "protocol"

INTENT_STAGES = ("inquiring", "quoting", "sampling", "negotiating", "cold", "other")
URGENCIES = ("high", "medium", "low")
MAX_MESSAGES = 25
MAX_PACK_CHARS = 10_000
MAX_WEEKLY_THREADS = 40
MAX_WEEKLY_CHARS = 16_000
MAX_MESSAGE_CHARS = 1_000

_FENCE_OPEN = re.compile(r"<\s*/?\s*external_data", re.IGNORECASE)
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_NUMBER = re.compile(r"\d[\d\s-]{6,}\d")  # 8+ digits
_BANK = re.compile(r"\b(iban|swift|bank account|account number)\b|收款账号|银行账号", re.IGNORECASE)
_MONEY_OR_TERMS = re.compile(
    r"\$|usd|eur|€|£|%|\bmoq\b|lead ?time|discount|price|quote|ship|折扣|报价|价格|交期|运费|库存",
    re.IGNORECASE,
)


class InvalidResult(ValueError):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def protocol_text(name):
    return (PROTOCOL_DIR / name).read_text(encoding="utf-8")


def digest(data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def thread_key(record_type, inquiry_id, conversation_id, schema_version):
    """Stable identity for one logical conversation.

    Stable v1.1 conversations are keyed by conversation_id. Legacy v1 records
    have no conversation identity, so they are keyed by the record itself.
    """
    if schema_version == "ark_alibaba_feed_v1.1" and conversation_id:
        return f"conv:{conversation_id}"
    return f"rec:{record_type}:{inquiry_id}"


def as_pair(value):
    if value is None:
        return None
    return (int(value[0]), int(value[1]))


def has_newer_inbound(seen, done):
    """True when the observed inbound watermark is ahead of the processed one.

    Watermarks are (order, revision) integer pairs compared numerically. String
    message identities are never compared, because they are not ordered.
    """
    seen_pair = as_pair(seen)
    if seen_pair is None:
        return False
    done_pair = as_pair(done)
    return done_pair is None or seen_pair > done_pair


def escape_external(text):
    """Neutralise fence markers so customer text cannot close the data block."""
    return _FENCE_OPEN.sub(lambda m: m.group(0).replace("<", "&lt;"), str(text or ""))


def weak_match(display_name, companies):
    """Exact, case-insensitive company-name match against the rep's own private companies.

    Returns a suggestion only. Binding is always an explicit user action.
    """
    name = (display_name or "").strip().casefold()
    if not name:
        return None
    for company in companies:
        if company.get("name") and company["name"].strip().casefold() == name:
            return {"company_id": company["company_id"], "name": company["name"],
                    "hint": "公司名一致", "level": "weak"}
    return None


def build_daily_pack(*, buyer, messages, biz_date, intent_stages=INTENT_STAGES, urgencies=URGENCIES):
    """Return (wire_text, refs) for one unlinked thread.

    `messages` is chronological: dicts with key, dir, at, text. The newest
    MAX_MESSAGES are kept, and the oldest are dropped further if the pack still
    exceeds MAX_PACK_CHARS. A single oversize message is truncated, never failed.
    External strings are escaped and placed inside the fence; trusted enums are
    injected here, never in the system prompt (CLAUDE.md red line 7).
    """
    recent = list(messages)[-MAX_MESSAGES:]

    def render(rows):
        out = []
        for m in rows:
            speaker = "买家" if m["dir"] == "buyer" else "我方" if m["dir"] == "seller" else "机器人"
            text = escape_external(m.get("text"))[:MAX_MESSAGE_CHARS]
            out.append(f"[{m['key']}] {escape_external(m.get('at'))} {speaker}: {text}")
        return out

    buyer_line = " · ".join(escape_external(buyer.get(k)) for k in ("name", "country", "level") if buyer.get(k))
    head = [
        f"今天 {biz_date.isoformat()}（北京时间）。以下为一位未绑定客户的会话。",
        f"可选意向阶段（可信，只能从中选）：{', '.join(intent_stages)}",
        f"可选紧急度（可信，只能从中选）：{', '.join(urgencies)}",
        "<external_data>",
        f"买家：{buyer_line or '未知'}",
    ]

    def assemble(rows):
        return "\n".join(head + render(rows) + ["</external_data>"])

    wire = assemble(recent)
    while len(wire) > MAX_PACK_CHARS and len(recent) > 1:
        recent = recent[1:]
        wire = assemble(recent)
    refs = {m["key"]: {**m, "text": str(m.get("text") or "")[:MAX_MESSAGE_CHARS]} for m in recent}
    return wire, refs


def _digits(text):
    return re.sub(r"\D", "", text)


def validate_daily(raw, refs):
    """Strictly check the model's JSON. Raises InvalidResult; never repairs data."""
    if not isinstance(raw, str):
        raise InvalidResult("non_json")
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InvalidResult("non_json") from exc
    if not isinstance(data, dict):
        raise InvalidResult("invalid_structure")

    is_lead = data.get("is_business_lead")
    if not isinstance(is_lead, bool):
        raise InvalidResult("invalid_structure", "is_business_lead")
    if data.get("intent_stage") not in INTENT_STAGES:
        raise InvalidResult("invalid_enum", "intent_stage")
    if data.get("urgency") not in URGENCIES:
        raise InvalidResult("invalid_enum", "urgency")

    limits = {"one_line_summary": 200, "missing_or_next_action": 400, "breakthrough_angle": 200, "draft_message": 800}
    out = {}
    for field, limit in limits.items():
        value = data.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value) > limit:
            raise InvalidResult("invalid_structure", field)
        out[field] = value.strip()

    cites = data.get("cites")
    if not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
        raise InvalidResult("invalid_structure", "cites")
    if any(c not in refs for c in cites):
        raise InvalidResult("unknown_cite")
    if is_lead and not cites:
        raise InvalidResult("missing_cite")

    pack_text = " ".join(str(m.get("text") or "") for m in refs.values())
    pack_emails = set(_EMAIL.findall(pack_text))

    clues_in = data.get("extracted_clues") or {}
    if not isinstance(clues_in, dict):
        raise InvalidResult("invalid_structure", "extracted_clues")
    clues = {}
    for key in ("company", "contact", "country", "email"):
        value = clues_in.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()[:120]
        if key == "email" and value not in pack_emails:
            continue  # invented contact details are dropped, not repaired
        if _URL.search(value) or _BANK.search(value):
            continue
        clues[key] = value
    products = clues_in.get("products")
    if isinstance(products, list):
        clues["products"] = [str(p)[:80] for p in products if isinstance(p, str) and p.strip()][:10]

    if not is_lead:
        # Non-leads never reach the rep with a draft attached.
        out["draft_message"] = ""

    for field in ("draft_message", "missing_or_next_action", "breakthrough_angle"):
        value = out[field]
        if _URL.search(value):
            raise InvalidResult("forbidden_content", f"{field}:url")
        for email in _EMAIL.findall(value):
            if email not in pack_emails:
                raise InvalidResult("forbidden_content", f"{field}:email")
        for number in _LONG_NUMBER.findall(value):
            digits = _digits(number)
            # The number must appear inside one message, not be stitched from the whole pack.
            if not any(digits in _digits(str(m.get("text") or "")) for m in refs.values()):
                raise InvalidResult("forbidden_content", f"{field}:number")
        if _BANK.search(value):
            raise InvalidResult("forbidden_content", f"{field}:bank")

    return {
        "is_business_lead": is_lead,
        "intent_stage": data["intent_stage"],
        "urgency": data["urgency"],
        **out,
        "extracted_clues": clues,
        "cites": cites,
        "needs_review": bool(out["draft_message"] and _MONEY_OR_TERMS.search(out["draft_message"])),
    }


def _forbidden_text(value):
    return bool(_URL.search(value) or _BANK.search(value) or _EMAIL.search(value))


def validate_weekly(raw, thread_ids, company_by_thread):
    """Keep only entries that point at live threads in this run, and companies from the candidate set.

    Invalid entries are dropped and counted, not repaired. `thread_ids` should be
    the set of threads still open at write-back time.
    """
    if not isinstance(raw, str):
        raise InvalidResult("non_json")
    try:
        data = json.loads(raw.strip())
    except ValueError as exc:
        raise InvalidResult("non_json") from exc
    if not isinstance(data, dict):
        raise InvalidResult("invalid_structure")

    dropped = 0
    overview = data.get("overview_md") or ""
    if not isinstance(overview, str) or len(overview) > 400:
        raise InvalidResult("invalid_structure", "overview_md")
    if _forbidden_text(overview):
        overview = "（本周总览含不允许的外部内容，已隐藏）"

    def keep(items, required):
        nonlocal dropped
        result = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                dropped += 1
                continue
            tid = str(item.get("thread_id", ""))
            if tid not in thread_ids:
                dropped += 1
                continue
            if any(not isinstance(item.get(k), str) or not item.get(k).strip() for k in required):
                dropped += 1
                continue
            if any(_forbidden_text(item[k]) for k in required if k != "matched_company_id"):
                dropped += 1
                continue
            if "matched_company_id" in required and str(item.get("matched_company_id")) not in company_by_thread.get(tid, set()):
                dropped += 1
                continue
            result.append({"thread_id": tid, **{k: item[k] for k in required}})
        return result

    return {
        "overview_md": overview,
        "missed_tasks": keep(data.get("missed_tasks"), ("title", "evidence", "suggested_action")),
        "breakthrough_leads": keep(data.get("breakthrough_leads"), ("concern", "angle", "draft_hint")),
        "likely_existing_customers": keep(data.get("likely_existing_customers"), ("why", "matched_company_id")),
        "cleanup_candidates": keep(data.get("cleanup_candidates"), ("reason",)),
        "dropped": dropped,
    }
