"""Aggregate de-identified pilot JSONL exports. No DB or network access."""

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.client_desk.calendar import offset_workdays


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def ratio(n, d):
    return {"numerator": n, "denominator": d, "rate": n / d if d else None}


def summarize(rows, labels, as_of):
    grouped = defaultdict(list)
    latest = {}
    for row in rows:
        cutoff = (
            datetime.fromisoformat(row["cutoff"]) if row.get("cutoff") else datetime.min
        )
        if cutoff > as_of:
            continue
        key = (row["user"], row["day"], row["customer"], row["run_seq"])
        if key not in latest or cutoff >= latest[key][0]:
            latest[key] = (cutoff, row)
    for key, (_, row) in latest.items():
        grouped[key[:3]].append(row)
    reports = {}
    missed = {}
    reviews = {}
    evaluated = set()
    for x in labels:
        key = (x["user"], x["day"], x["customer"])
        if x.get("missed"):
            missed[key] = True
        if x.get("quality") in {"useful", "useless"}:
            reviews[key] = x["quality"]
        if x.get("shown") is True or key in reviews:
            evaluated.add(key)
    shown = useful = feedback = eligible = graded = started = failed = matched = 0
    groups = defaultdict(lambda: [0, 0])
    excluded_windows = crossovers = 0
    breakdown = defaultdict(int)
    exclusions = defaultdict(int)
    for key, runs in grouped.items():
        routine = next((r for r in runs if not r["run_seq"]), None)
        exposed = any(r.get("shown_at") for r in runs) or key in evaluated
        rated = sorted(
            (r for r in runs if r.get("quality_feedback")),
            key=lambda r: (r.get("feedback_at") or "", r["run_seq"]),
        )
        quality = reviews.get(key) or (rated[-1]["quality_feedback"] if rated else None)
        shown += int(exposed)
        useful += int(exposed and quality == "useful")
        feedback += int(
            exposed
            and bool(
                quality or any(r.get("done_at") or r.get("snoozed_until") for r in runs)
            )
        )
        for r in runs:
            if r.get("report_key"):
                reports[r["report_key"]] = r
            if r.get("call_started_at"):
                started += 1
                failed += int(
                    r["status"] in {"failed", "ambiguous"}
                    or r.get("error_code") == "validation_failed"
                )
        if routine and routine.get("active_customer"):
            eligible += 1
            graded += int(bool(routine.get("grade")))
        if key in missed and routine and routine.get("rule_codes"):
            matched += 1
            cause = (
                "holdout"
                if routine.get("cohort") == "holdout"
                else (
                    "outside_quota"
                    if routine.get("disposition") == "quota"
                    else "outside_top_ten"
                )
            )
            breakdown[cause] += 1
        if (
            not routine
            or routine.get("cohort") not in {"treatment", "holdout"}
            or not routine.get("wa_linked")
        ):
            continue
        day = date.fromisoformat(key[1])
        start = datetime.combine(day, time(8, 40))
        end = datetime.combine(offset_workdays(day, 2) + timedelta(days=1), time())
        cutoff = (
            datetime.fromisoformat(routine["cutoff"])
            if routine.get("cutoff")
            else datetime.min
        )
        exclusion = routine.get("exclusion_reason")
        if not exclusion and min(as_of, cutoff) < end:
            exclusion = "incomplete_window"
        if not exclusion and routine.get("communication_times") is None:
            exclusion = "communication_unavailable"
        if exclusion:
            excluded_windows += 1
            exclusions[exclusion] += 1
            continue
        contacted = any(
            start <= datetime.fromisoformat(t) < end
            for t in routine["communication_times"]
        )
        for category in [
            routine["cohort"],
            ("actually_shown" if exposed else "unshown") + "_" + routine["cohort"],
        ]:
            groups[category][0] += int(contacted)
            groups[category][1] += 1
        crossovers += int(routine["cohort"] == "holdout" and exposed)
    accepted = [r for r in reports.values() if r.get("send_status") == "accepted"]
    breakdown["no_rule"] = len(missed) - matched
    return {
        "usefulness": ratio(useful, shown),
        "feedback": ratio(feedback, shown),
        "supplemental_recall": ratio(matched, len(missed)),
        "missed_breakdown": dict(breakdown),
        "analysis_failures": ratio(failed, started),
        "report_opens": ratio(
            sum(bool(r.get("opened_at")) for r in accepted), len(accepted)
        ),
        "send_uncertain": sum(
            r.get("send_status") in {"sending", "unknown"} for r in reports.values()
        ),
        "grade_coverage": ratio(graded, eligible),
        "communication": {
            k: ratio(*groups[k])
            for k in (
                "holdout",
                "treatment",
                "actually_shown_treatment",
                "actually_shown_holdout",
                "unshown_treatment",
                "unshown_holdout",
            )
        },
        "itt_difference": (
            groups["treatment"][0] / groups["treatment"][1]
            - groups["holdout"][0] / groups["holdout"][1]
            if groups["holdout"][1] and groups["treatment"][1]
            else None
        ),
        "incomplete_or_unavailable_windows": excluded_windows,
        "window_exclusion_reasons": dict(exclusions),
        "holdout_crossovers": crossovers,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshots", nargs="+", type=Path)
    p.add_argument("--labels", type=Path)
    p.add_argument(
        "--as-of",
        required=True,
        type=datetime.fromisoformat,
        help="Beijing local datetime",
    )
    args = p.parse_args()
    rows = [r for path in args.snapshots for r in read_rows(path)]
    labels = read_rows(args.labels) if args.labels else []
    result = {"aggregate": summarize(rows, labels, args.as_of)}
    for user in sorted({r["user"] for r in rows}):
        subset = [r for r in rows if r["user"] == user]
        ratings = [r for r in labels if r["user"] == user]
        result[user] = {"total": summarize(subset, ratings, args.as_of), "days": {}}
        for day in sorted({r["day"] for r in subset}):
            result[user]["days"][day] = summarize(
                [r for r in subset if r["day"] == day],
                [r for r in ratings if r["day"] == day],
                args.as_of,
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
