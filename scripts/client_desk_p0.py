"""P0 prepare/analyze. Default exports a masked evaluation pack; --analyze explicitly calls the approved preset.

Use --input with a previous prepare file to require the same business day, source fingerprint and
masked pack hash. Changed grants, edited files and expired sources cannot be replayed to a model.
The AI facade writes metadata logs in a separate session. Desk domain tables are never written.
"""

import argparse
from copy import deepcopy
from datetime import date, datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.ai.service import chat
from app.ai.text_snapshot import prepare_text_chat
from app.client_desk import pack, sources, validator
from app.client_desk.models import ClientDeskState as State
from app.client_desk.queue import active, read_candidates, state_data
from app.client_desk.rules import R1, R6, R7, evaluate
from app.core.database import engine
from app.core.time import beijing_now


class Mask:
    def __init__(self, key, source):
        self.key = key
        strings = {source["card"].get("name")}
        for c in [*(source.get("contacts") or []), *(source.get("wa_targets") or [])]:
            strings.update(
                c.get(k)
                for k in (
                    "name",
                    "first_name",
                    "last_name",
                    "phone",
                    "email",
                    "tel",
                    "conversation_uid",
                    "account_uid",
                )
            )
        for r in source.get("orders") or []:
            strings.add(r.get("order_no"))
        self.names = sorted(
            (str(v).strip() for v in strings if v and str(v).strip()),
            key=len,
            reverse=True,
        )

    def alias(self, value):
        return hmac.new(self.key, str(value).encode(), hashlib.sha256).hexdigest()[:20]

    def clean(self, value):
        if isinstance(value, dict):
            return {
                k: self.clean(v)
                for k, v in value.items()
                if k
                not in {
                    "id",
                    "order_id",
                    "company_id",
                    "user_id",
                    "account_uid",
                    "conversation_uid",
                    "event_key",
                    "contact_id",
                    "order_no",
                    "raw_json",
                }
            }
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for known in self.names:
                value = re.sub(re.escape(known), "[资料代号]", value, flags=re.I)
            return validator.CONTACT.sub("[联系资料]", value)
        return value


def make_pack(source, state, codes, day, key, correction=False):
    mask = Mask(key, source)
    refs = {}
    keymap = {}
    for k, v in source["refs"].items():
        reference = k.split("-", 1)[0] + "-" + mask.alias(k)
        keymap[k] = reference
        refs[reference] = mask.clean(v) | {
            "source": v["source"],
            "event_key": v["source"] + ":" + mask.alias(v["event_key"]),
        }
    scrubbed = {
        "company_id": mask.alias(source["company_id"]),
        "card": mask.clean(source["card"]),
        "grade": source.get("grade"),
        "grade_options": source.get("grade_options", []),
        "orders_summary": mask.clean(source.get("orders_summary")),
        "research_summary": mask.clean(source.get("research_summary")),
        "refs": refs,
        "source_dependencies": {
            "proof": mask.alias(pack.digest(source["source_dependencies"]))
        },
        "messages": [
            {
                "key": keymap[m["key"]],
                "at": m["at"],
                "text": mask.clean(m.get("text", "")),
            }
            for m in source.get("messages", [])
            if m["key"] in keymap
        ],
    }
    personal = {
        k: mask.clean(state.get(k))
        for k in ("remark", "next_followup_date", "next_followup_remark")
    }
    return pack.build_pack(scrubbed, personal, codes, day, correction)


def snapshot(db, uid, cid, codes, now, key, correction=False):
    cfg = active(db, uid)
    source = sources.analysis_input(db, uid, cid, now)
    state = state_data(db.query(State).filter_by(user_id=uid, company_id=cid).first())
    allowed = evaluate(
        source, state, now, uid, cfg.CLIENT_DESK_RULES, cfg.CLIENT_DESK_CALENDAR
    )
    if (set(codes) & {R1, R6, R7}) - (set(allowed.codes) if allowed else set()):
        raise ValueError("source_changed")
    return make_pack(source, state, codes, now.date(), key, correction)


def attempt_analysis(db, uid, cid, codes, now, key, initial, metadata_session):
    counts = {"input": 0, "output": 0}
    for attempt in range(2):
        db.rollback()
        if beijing_now().date() != now.date():
            return {"status": "failed", "error_code": "day_changed"}
        cfg = active(db, uid)
        material = snapshot(db, uid, cid, codes, now, key, correction=bool(attempt))
        if material.dependencies != initial.dependencies or (
            not attempt and material.hash != initial.hash
        ):
            return {"status": "failed", "error_code": "source_changed"}
        # Lock the dedicated eligible provider/preset only in the AI log session.
        preset = prepare_text_chat(metadata_session, cfg.CLIENT_DESK_PRESET_NAME, 1800)
        if (
            preset.provider.id not in cfg.CLIENT_DESK_ALLOWED_PROVIDER_IDS
            or preset.preset.system_prompt
        ):
            metadata_session.rollback()
            return {"status": "failed", "error_code": "unapproved_preset"}
        metadata_session.commit()
        db.rollback()
        started = beijing_now()
        try:
            response = chat(
                metadata_session,
                cfg.CLIENT_DESK_PRESET_NAME,
                material.messages,
                "client_desk_p0",
                caller_user_id=uid,
                snapshot_mode="metadata",
                timeout_sec=85,
                enforce_total_timeout=True,
                trusted_text_snapshot=preset,
            )
        except Exception as exc:
            metadata_session.rollback()
            print(
                f"P0 uncertain response: {type(exc).__name__}",
                file=sys.stderr,
                flush=True,
            )
            return {
                "status": "ambiguous",
                "error_code": "call_uncertain",
                "call_started_at": started,
                "token_usage": counts,
            }
        counts["input"] += response.get("tokens_prompt") or 0
        counts["output"] += response.get("tokens_completion") or 0
        try:
            result = validator.validate(response.get("content"), material, now.date())
        except ValueError:
            if attempt == 0:
                continue
            return {
                "status": "rule_only",
                "error_code": "validation_failed",
                "call_started_at": started,
                "token_usage": counts,
            }
        db.rollback()
        latest = snapshot(db, uid, cid, codes, now, key)
        if latest.dependencies != initial.dependencies:
            return {
                "status": "failed",
                "error_code": "source_changed",
                "call_started_at": started,
                "token_usage": counts,
            }
        return {
            "status": "succeeded",
            "result": result,
            "call_started_at": started,
            "token_usage": counts,
            "provider_id": preset.provider.id,
            "model": preset.preset.model,
            "preset": cfg.CLIENT_DESK_PRESET_NAME,
        }


def run(db, uid, key, now, previous=None, metadata_session=None):
    ranked, material = read_candidates(db, uid, now)
    rows = []
    user_alias = Mask(key, {"card": {}}).alias(f"user:{uid}")
    for candidate in ranked:
        cid = candidate.company_id
        mask = Mask(key, material[cid])
        identifier = mask.alias(f"company:{cid}")
        row = {
            "user": user_alias,
            "day": str(now.date()),
            "customer": identifier,
            "run_seq": 0,
            "cohort": candidate.cohort,
            "rule_codes": candidate.codes,
            "rank_score": candidate.score,
            "disposition": candidate.disposition,
            "protocol_version": "desk_v1",
            "protocol_hash": pack.PROTOCOL_HASH,
            "status": "rule_only",
        }
        if candidate.disposition == "eligible":
            try:
                db.rollback()
                p = snapshot(db, uid, cid, candidate.codes, now, key)
                row.update(
                    pack_hash=p.hash,
                    source_proof=p.dependencies,
                    masked_pack=p.messages,
                    status="prepared",
                )
                if previous is not None:
                    expected = previous.get((user_alias, str(now.date()), identifier))
                    if (
                        not expected
                        or expected.get("pack_hash") != p.hash
                        or expected.get("source_proof") != p.dependencies
                    ):
                        raise ValueError("frozen_pack_mismatch")
                if metadata_session is not None:
                    row.update(
                        attempt_analysis(
                            db, uid, cid, candidate.codes, now, key, p, metadata_session
                        )
                    )
            except Exception as exc:
                print(
                    f"P0 case {identifier}: {type(exc).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
                db.rollback()
                if metadata_session:
                    metadata_session.rollback()
                row.update(status="failed", error_code="capture_failed")
        rows.append(row)
    priority = {"high": 0, "medium": 1, "low": 2}
    eligible = [
        r
        for r in rows
        if r["cohort"] != "holdout"
        and set(r["rule_codes"]) - {"R4_NEW_ACTIVITY"}
        and r.get("result", {}).get("suggestion", {}).get("priority") != "skip"
    ]
    ordered = sorted(
        eligible,
        key=lambda r: (
            priority.get(r.get("result", {}).get("suggestion", {}).get("priority"), 3),
            -r["rank_score"],
        ),
    )
    for i, r in enumerate(ordered[:10], 1):
        r["evaluation_rank"] = i
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user", required=True, type=int)
    p.add_argument("--key-file", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument(
        "--input", type=Path, help="Require the exact masked pack prepared previously"
    )
    p.add_argument(
        "--analyze",
        action="store_true",
        help="Submit each eligible pack only through the approved AI facade",
    )
    args = p.parse_args()
    if args.out.exists() or not args.out.parent.exists():
        p.error("use a fresh output file in an existing restricted directory")
    key = args.key_file.read_bytes()
    if len(key) < 32:
        p.error("pseudonym key must have at least 32 bytes")
    prev = None
    if args.input:
        data = [
            json.loads(x)
            for x in args.input.read_text(encoding="utf8").splitlines()
            if x
        ]
        prev = {(r["user"], r["day"], r["customer"]): r for r in data}
    # The driver session is read-only; only the AI facade's separate session may write its own logs.
    read_engine = engine.execution_options(isolation_level="READ COMMITTED")
    with read_engine.connect() as conn:
        conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
        conn.commit()
        try:
            with Session(bind=conn, autoflush=False) as db, Session(
                bind=engine
            ) as log_db:
                rows = run(
                    db,
                    args.user,
                    key,
                    beijing_now(),
                    prev,
                    log_db if args.analyze else None,
                )
        finally:
            conn.rollback()
            conn.exec_driver_sql("SET SESSION TRANSACTION READ WRITE")
            conn.commit()
    with args.out.open("x", encoding="utf8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
