"""Bounded model input. The final evidence map contains only material in the wire prompt."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

PROTOCOL = (
    Path(__file__)
    .with_name("protocol")
    .joinpath("desk_v1.md")
    .read_text(encoding="utf8")
)
PROTOCOL_HASH = hashlib.sha256(PROTOCOL.encode()).hexdigest()
LIMIT = 24000


def canonical(data):
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def digest(data):
    return hashlib.sha256(canonical(data).encode()).hexdigest()


@dataclass
class Pack:
    messages: list
    refs: dict
    dependencies: dict
    hash: str
    grades: list


def build_pack(source, state, codes, day, correction=False):
    deps = source["source_dependencies"]
    if not deps:
        raise ValueError("source_dependencies_missing")
    grades = [g for g in source.get("grade_options", []) if g in tuple("SABCDE")]
    data = {
        "card": source["card"],
        "orders_summary": source.get("orders_summary"),
        "grade": source.get("grade"),
        "personal": {
            "remark": state.get("remark"),
            "next_followup_date": state.get("next_followup_date"),
            "next_followup_remark": state.get("next_followup_remark"),
        },
        "rules": codes,
        "research_summary": source.get("research_summary"),
        "previous_brief": None,
    }
    from .source_policy import previous_brief

    data["previous_brief"] = previous_brief(state, deps)
    data["coverage_gaps"] = source.get("coverage_gaps", [])
    data["analysis_policy"] = source.get("analysis_policy")
    refs = {
        k: dict(v) for k, v in (source.get("refs") or {}).items() if v.get("event_key")
    }
    for message in source.get("messages", []):
        key = message["key"]
        if key in refs:
            refs[key]["text"] = message.get("text")
            refs[key]["at"] = str(message.get("at") or "")
    if codes:
        # A real deterministic rule snapshot is inspectable in the customer's suggestion.
        for code in codes:
            refs["R-" + code] = {
                "source": "rule",
                "event_key": "rule:" + code,
                "text": code,
            }
    if not refs:
        refs["R-CARD"] = {
            "source": "rule",
            "event_key": "rule:CARD",
            "text": "档案建档",
            "company_id": source["company_id"],
        }
    messages = sorted(
        (k for k in refs if k.startswith(("M-", "AF-"))),
        key=lambda k: (str(refs[k].get("at", "")), k),
    )
    optional = sorted(
        (k for k in refs if not k.startswith(("M-", "AF-"))), reverse=True
    )
    instruction = canonical(
        {
            "biz_date": str(day),
            "priorities": ["high", "medium", "low", "skip"],
            "grades": grades,
        }
    )
    if correction:
        instruction += " 上次结果未通过结构、证据或安全检查，请重新严格按协议输出。"
    while True:
        wire = (
            canonical(data | {"refs": refs})
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("`", "\\u0060")
        )
        user_text = instruction + "\n<external_data>" + wire + "</external_data>"
        if len(user_text) + len(PROTOCOL) <= LIMIT:
            break
        if messages and len(refs) > 1:
            del refs[messages.pop(0)]
        elif data["previous_brief"]:
            data["previous_brief"] = None
        elif data["research_summary"]:
            data["research_summary"] = None
        elif optional and len(refs) > 1:
            del refs[optional.pop()]
        else:
            raise ValueError("pack_too_large")
    prompts = [
        {"role": "system", "content": PROTOCOL},
        {"role": "user", "content": user_text},
    ]
    return Pack(prompts, refs, deps, digest(prompts), grades)
