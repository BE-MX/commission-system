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
    r"(?:https?://|www\.)[^\s<>()\]\"，。]+|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b|\b(?:bank|account|iban|swift|paypal|cuenta|conta|compte|账号|银行)\s*[:#：-]?\s*[a-z0-9-]{4,}",
    re.I,
)
RISK = re.compile(
    r"[$€£¥]|\d+\s*(?:%|usd|eur|dollars?|euros?|days?|jours?|d[ií]as?|dias|天)|price|discount|in stock|ship|deliver|lead time|precio|descuento|existencias|entrega|env[ií]o|prix|remise|stock|livraison|délai|pre[çc]o|desconto|estoque|prazo|frete|价格|交期|库存|折扣|到货",
    re.I,
)
UNSAFE = re.compile(
    r"(?i)<[/!a-z]|javascript\s*:|data\s*:|!\[|底价|成本价|bottom price|cost price|便宜|划算|性价比|打折|薅羊毛"
)


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate_key")
        obj[key] = value
    return obj


def validate(raw, pack, day):
    if not isinstance(raw, str) or len(raw) > 16000:
        raise ValueError("invalid_result")
    try:
        result = Result.model_validate(json.loads(raw, object_pairs_hook=unique_keys))
    except (ValidationError, ValueError, RecursionError):
        raise ValueError("invalid_result") from None
    suggestion = result.suggestion
    if result.recheck and not day < date.fromisoformat(
        result.recheck.date
    ) <= day + timedelta(days=30):
        raise ValueError("invalid_recheck")
    if suggestion.priority == "skip" and not result.recheck:
        raise ValueError("missing_recheck")
    if result.grade_hint and result.grade_hint.value not in pack.grades:
        raise ValueError("invalid_grade")
    blocks = {
        key: block
        for key, block in (result.profile or Profile()).__dict__.items()
        if block is not None
    }
    codes = [tag.code for tag in result.tags]
    if len(set(codes)) != len(codes) or not set(codes) <= set(pack.tags):
        raise ValueError("invalid_tags")
    keys = suggestion.cites + (result.grade_hint.cites if result.grade_hint else [])
    keys += [k for tag in result.tags for k in tag.cites]
    keys += [k for block in blocks.values() for k in block.cites]
    if not set(keys) <= pack.refs.keys():
        raise ValueError("invalid_cites")
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
        m.group().casefold()
        for message in pack.messages
        if message["role"] == "user"
        for m in CONTACT.finditer(message["content"])
    }
    for field in fields + profile_fields:
        if UNSAFE.search(field) or any(
            m.group().casefold() not in trusted_contacts
            for m in CONTACT.finditer(field)
        ):
            raise ValueError("unsafe_output")
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
