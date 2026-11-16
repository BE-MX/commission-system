"""Parse and validate untrusted model output before it can reach persistence."""

from datetime import date, timedelta
import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Annotated, Literal

Short = Annotated[str, Field(min_length=1, max_length=60)]
Item = Annotated[str, Field(min_length=1, max_length=160)]
References = Annotated[list[Short], Field(min_length=1, max_length=24)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Suggestion(Strict):
    priority: Literal["high", "medium", "low", "skip"]
    reason: Short
    strategy: Annotated[str, Field(min_length=1, max_length=150)]
    check_before_reply: Annotated[list[Item], Field(max_length=8)]
    talking_points: Annotated[list[Item], Field(max_length=3)]
    draft_message: Annotated[str, Field(max_length=1600)]
    cites: References


class Grade(Strict):
    value: Short
    reason: Short
    cites: References


class Recheck(Strict):
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    condition: Annotated[str, Field(min_length=2, max_length=160)]


Cites = Annotated[list[Short], Field(max_length=12)]


class Block(Strict):
    text: Annotated[str, Field(min_length=1, max_length=200)]
    cites: Cites


class Profile(Strict):
    identity: Block | None = None
    needs: Block | None = None
    decision: Block | None = None
    relationship: Block | None = None
    opportunity: Block | None = None


class Tag(Strict):
    code: Short
    reason: Annotated[str, Field(min_length=1, max_length=40)]
    cites: References


class Result(Strict):
    brief_md: Annotated[str, Field(min_length=1, max_length=600)]
    profile: Profile | None = None
    tags: Annotated[list[Tag], Field(max_length=6)] = []
    suggestion: Suggestion
    grade_hint: Grade | None
    recheck: Recheck | None


CONTACT = re.compile(
    r"(?:https?://|www\.)[^\s<>()\]\"，。]+|[\w.+-]+@[\w.-]+\.[a-z]{2,}"
    r"|(?<!\w)(?P<number>\+?\d[\d ()-]{6,}\d)(?!\w)",
    re.I,
)
BANK_DETAILS = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b|"
    r"(?:(?<!\w)(?:bank(?:\s+account)?|account|iban|swift|paypal|cuenta|conta|compte)\b"
    r"|账号|账户|银行)\s*(?:number\b|no\.?|号码)?\s*[:#：-]?\s*"
    r"(?=[a-z0-9-]*\d)[a-z0-9-]{4,}\b",
    re.I,
)
SWIFT_BIC = re.compile(
    r"\b(?:swift(?:\s*(?:/|or)\s*bic)?|bic)\b(?:\s+code)?"
    r"\s*[:#：-]?\s*[a-z]{6}[a-z0-9]{2}(?:[a-z0-9]{3})?\b",
    re.I,
)
PAYMENT_INSTRUCTION = re.compile(
    r"\b(?:pay\s+(?:to|via|using|us\s+(?:via|using))|"
    r"(?:send|wire|transfer)\s+(?:(?:the|your|a)\s+)?(?:payment|funds|money)\s+(?:to|via))\b"
    r"|(?:请)?(?:付款|打款|汇款|转账)(?:给|至|到)",
    re.I,
)
DATE_OR_YEARS = re.compile(r"(?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}|\d{4}-\d{2}-\d{2}")
RISK = re.compile(
    r"[$€£¥]|\d+\s*(?:%|usd|eur|dollars?|euros?|days?|jours?|d[ií]as?|dias|天)|price|discount|in stock|ship|deliver|lead time|precio|descuento|existencias|entrega|env[ií]o|prix|remise|stock|livraison|délai|pre[çc]o|desconto|estoque|prazo|frete|价格|交期|库存|折扣|到货",
    re.I,
)
UNSAFE = re.compile(
    r"(?i)<[/!a-z]|javascript\s*:|\bdata\s*:\s*(?:[\w.+-]+/[\w.+-]+)?[;,]"
    r"|!\[|底价|成本价|bottom price|cost price|便宜|划算|性价比|打折|薅羊毛"
)
JSON_FENCE = re.compile(r"\x60{3}(?:json)?[ \t]*\r?\n(.*?)\r?\n[ \t]*\x60{3}", re.I | re.S)
MAX_RESULT_CHARS = 16000
SCHEMA_FIELDS = {
    key
    for model in (Result, Suggestion, Grade, Recheck, Profile, Block, Tag)
    for key in model.model_fields
}


class InvalidResult(ValueError):
    def __init__(self, code, issues=()):
        super().__init__(code)
        self.issues = list(issues)


def contact_values(text):
    for match in CONTACT.finditer(text):
        value = match.group()
        if match.group("number") and DATE_OR_YEARS.fullmatch(value):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                try:
                    date.fromisoformat(value)
                except ValueError:
                    yield value.casefold()
            continue
        yield value.casefold()


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise InvalidResult("invalid_structure", [{"field": "$", "type": "duplicate_key"}])
        obj[key] = value
    return obj


def unwrapped_json(raw):
    if isinstance(raw, str):
        raw = raw.strip()
        match = JSON_FENCE.fullmatch(raw)
        return match.group(1) if match else raw
    return raw


def validate(raw, pack, day, *, finish_reason=None):
    if finish_reason in ("length", "max_tokens"):
        raise InvalidResult("truncated")
    if not isinstance(raw, str):
        raise InvalidResult("non_json")
    if len(raw) > MAX_RESULT_CHARS:
        raise InvalidResult("invalid_structure", [{"field": "$", "type": "output_too_long"}])
    try:
        payload = json.loads(unwrapped_json(raw), object_pairs_hook=unique_keys)
    except InvalidResult:
        raise
    except (ValueError, RecursionError):
        raise InvalidResult("non_json") from None
    try:
        result = Result.model_validate(payload)
    except ValidationError as exc:
        issues = [
            {
                "field": ".".join(
                    str(part) if type(part) is int or part in SCHEMA_FIELDS else "*"
                    for part in err["loc"]
                ) or "$",
                "type": err["type"],
            }
            for err in exc.errors(include_input=False, include_context=False, include_url=False)[:8]
        ]
        raise InvalidResult("invalid_structure", issues) from None
    suggestion = result.suggestion
    if result.recheck:
        try:
            recheck_day = date.fromisoformat(result.recheck.date)
        except ValueError:
            raise InvalidResult("invalid_recheck") from None
        if not day < recheck_day <= day + timedelta(days=30):
            raise InvalidResult("invalid_recheck")
    if suggestion.priority == "skip" and not result.recheck:
        raise InvalidResult("missing_recheck")
    if result.grade_hint and result.grade_hint.value not in pack.grades:
        raise InvalidResult("invalid_grade")
    blocks = {
        key: block
        for key, block in (result.profile or Profile()).__dict__.items()
        if block is not None
    }
    codes = [tag.code for tag in result.tags]
    if len(set(codes)) != len(codes) or not set(codes) <= set(pack.tags):
        raise InvalidResult("invalid_tags")
    keys = suggestion.cites + (result.grade_hint.cites if result.grade_hint else [])
    keys += [k for tag in result.tags for k in tag.cites]
    keys += [k for block in blocks.values() for k in block.cites]
    if not set(keys) <= pack.refs.keys():
        raise InvalidResult("invalid_cites")
    fields = [
        result.brief_md,
        suggestion.reason,
        suggestion.strategy,
        suggestion.draft_message,
        *suggestion.check_before_reply,
        *suggestion.talking_points,
    ]
    if result.recheck:
        fields.append(result.recheck.condition)
    if result.grade_hint:
        fields.append(result.grade_hint.reason)
    profile_fields = [b.text for b in blocks.values()] + [t.reason for t in result.tags]
    # Tool results are later user turns; contacts quoted there are equally trusted.
    trusted_contacts = {
        contact
        for message in pack.messages
        if message["role"] == "user"
        for contact in contact_values(message["content"])
    }
    for field in fields + profile_fields:
        if (
            UNSAFE.search(field)
            or BANK_DETAILS.search(field)
            or SWIFT_BIC.search(field)
            or PAYMENT_INSTRUCTION.search(field)
            or set(contact_values(field)) - trusted_contacts
        ):
            raise InvalidResult("unsafe_output")
    out = result.model_dump()

    def cite_objects(cites):
        return [
            {
                "key": k,
                "event_key": pack.refs[k]["event_key"],
                "source": pack.refs[k]["source"],
            }
            for k in cites
        ]

    for target in [out["suggestion"], out["grade_hint"]]:
        if target:
            target["cites"] = cite_objects(target["cites"])
    out["profile"] = {
        key: {"text": block.text, "cites": cite_objects(block.cites)}
        for key, block in blocks.items()
    }
    out["tags"] = [
        {"code": tag.code, "reason": tag.reason, "cites": cite_objects(tag.cites)}
        for tag in result.tags
    ]
    out["suggestion"]["needs_review"] = any(RISK.search(s) for s in fields[1:])
    if out["suggestion"]["needs_review"] and not suggestion.check_before_reply:
        out["suggestion"]["check_before_reply"] = ["回复前核对报价、库存及交期"]
    return out
