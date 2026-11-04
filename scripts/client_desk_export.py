"""Read-only, de-identified current pilot snapshot. Keep the HMAC key outside the export directory."""

import argparse
from datetime import date, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import text
from app.core.database import engine
from app.core.time import beijing_now
from app.client_desk.queue import linkage_fingerprint, read_candidates, today_rows
from sqlalchemy.orm import Session


def export(db, uid, now, key, biz_date=None):
    def alias(value):
        return hmac.new(key, str(value).encode(), hashlib.sha256).hexdigest()[:20]

    biz_date = biz_date or now.date()
    if biz_date > now.date():
        raise ValueError("future_business_day")
    candidates, material = read_candidates(db, uid, now)
    cache = {c.company_id: c for c in candidates}
    by_company = {}
    for r in today_rows(db, uid, biz_date).order_by("run_seq"):
        by_company.setdefault(r.company_id, []).append(r)
    for cid in sorted(material.keys() | by_company.keys()):
        src = material.get(cid, {})
        routine = cache.get(cid)
        ts = src.get("last_touch_at")
        if biz_date != now.date() and cid not in by_company:
            continue
        snap = {
            "user": alias(f"user:{uid}"),
            "day": str(biz_date),
            "customer": alias(f"company:{cid}"),
            "active_customer": bool(
                src.get("order_count") or (ts and ts >= now - timedelta(days=30))
            ),
            "grade": src.get("grade"),
            "wa_linked": bool(src.get("conversations")),
            "calendar_version": "CN-2025-2026",
            "cutoff": now.isoformat(),
            "protocol_version": "desk_v1",
        }
        for row in by_company.get(cid, []) or [None]:
            output = dict(snap)
            if row:
                output.update(
                    {
                        k: getattr(row, k)
                        for k in (
                            "run_seq",
                            "rule_codes",
                            "rank_score",
                            "cohort",
                            "disposition",
                            "quality_feedback",
                            "shown_at",
                            "feedback_at",
                            "snoozed_until",
                            "done_at",
                            "opened_at",
                            "send_status",
                            "status",
                            "call_started_at",
                            "error_code",
                            "token_usage",
                            "protocol_hash",
                            "rule_version",
                        )
                    }
                )
                output["report_key"] = alias(row.report_key) if row.report_key else None
                output["wa_linked"] = (row.snapshot or {}).get(
                    "wa_linked", snap["wa_linked"]
                )
                output["active_customer"] = (row.snapshot or {}).get(
                    "active_customer", snap["active_customer"]
                )
                output["grade"] = (row.snapshot or {}).get("grade", snap["grade"])
            else:
                output.update(
                    run_seq=0,
                    rule_codes=routine.codes if routine else [],
                    rank_score=routine.score if routine else 0,
                    cohort=routine.cohort if routine else "ineligible",
                    disposition=routine.disposition if routine else None,
                    status="not_analyzed",
                )
            output["communication_times"] = (
                sorted(str(t) for t in src.get("communication_times", []))
                if "communication_times" in src
                else None
            )
            frozen = row.snapshot or {} if row else {}
            exclusion = None
            if cid not in material:
                exclusion = "customer_out_of_scope"
            elif output["wa_linked"] and not src.get("conversations"):
                exclusion = "wa_link_or_access_lost"
            elif row and output["wa_linked"] and not frozen.get("linkage_fingerprint"):
                exclusion = "enrollment_linkage_unknown"
            elif frozen.get("linkage_fingerprint") and frozen[
                "linkage_fingerprint"
            ] != linkage_fingerprint(src):
                exclusion = "wa_link_or_access_changed"
            if exclusion:
                output["communication_times"] = None
                output["exclusion_reason"] = exclusion
            yield output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user", required=True, type=int)
    p.add_argument("--key-file", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument(
        "--day",
        type=date.fromisoformat,
        help="Refresh a previous candidate day's feedback and completed ITT windows",
    )
    args = p.parse_args()
    key = args.key_file.read_bytes()
    if len(key) < 32:
        p.error("use a secret key of at least 32 bytes")
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        with Session(bind=conn, autoflush=False) as db:
            rows = list(export(db, args.user, beijing_now(), key, args.day))
            db.rollback()
    with args.out.open("x", encoding="utf8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
