#!/usr/bin/env python3
"""Audit list-table invariants and freeze measurable legacy UI debt."""

import argparse
import json
import re
import sys
from pathlib import Path
import subprocess


REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "scripts/ui_debt_baseline.json"
VIEW_ROOTS = (REPO / "frontend/src", REPO / "frontend-pm/src")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
TRANSITION_ALL = re.compile(r"transition(?:-property)?\s*:\s*all\b")


def _tags(text: str, name: str) -> list[str]:
    """Parse opening tags without treating comparison operators in quotes as tag ends."""
    result = []
    start = 0
    needle = f"<{name}"
    while True:
        index = text.find(needle, start)
        if index < 0:
            return result
        boundary = index + len(needle)
        if boundary < len(text) and not (text[boundary].isspace() or text[boundary] == ">"):
            start = boundary
            continue
        quote = None
        escaped = False
        cursor = boundary
        while cursor < len(text):
            char = text[cursor]
            if quote:
                if char == quote and not escaped:
                    quote = None
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False
            elif char in {'"', "'"}:
                quote = char
            elif char == ">":
                result.append(text[index:cursor + 1])
                start = cursor + 1
                break
            cursor += 1
        else:
            return result


def scan() -> tuple[list[str], dict[str, dict[str, int]]]:
    failures: list[str] = []
    debt: dict[str, dict[str, int]] = {}
    for root in VIEW_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.vue"):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(REPO).as_posix()
            tables = _tags(text, "el-table")
            columns = _tags(text, "el-table-column")
            buttons = _tags(text, "el-button")
            for index, tag in enumerate(tables, 1):
                if re.search(r"\s+stripe(?=\s|=|>)", tag):
                    failures.append(f"{relative}: table {index} uses stripe")
                if not re.search(r"(?<!:)\bborder(?=\s|=|>)", tag):
                    failures.append(f"{relative}: table {index} misses border")
                static_class = re.search(r'\bclass\s*=\s*(["\'])(.*?)\1', tag, re.S)
                if not static_class or "list-table" not in static_class.group(2).split():
                    failures.append(f"{relative}: table {index} misses list-table class")
            for index, tag in enumerate(columns, 1):
                if re.search(r'(?<![-:])\bwidth\s*=\s*["\']\d+', tag):
                    failures.append(f"{relative}: column {index} uses fixed width")
                if re.search(r'\balign\s*=\s*["\']center', tag):
                    failures.append(f"{relative}: column {index} forces centered content")
            for index, tag in enumerate(buttons, 1):
                if re.search(r'\bsize\s*=\s*["\']small', tag):
                    failures.append(f"{relative}: button {index} uses legacy small size")

            metrics = {
                "hex_colors": len(HEX.findall(text)),
                "transition_all": len(TRANSITION_ALL.findall(text)),
                "lines_over_500": max(0, len(text.splitlines()) - 500),
            }
            if any(metrics.values()):
                debt[relative] = metrics
    return failures, debt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument(
        "--baseline-ref",
        help="Git ref whose committed baseline must not be increased (missing file bootstraps the gate)",
    )
    args = parser.parse_args()
    failures, debt = scan()
    if args.write_baseline:
        if failures:
            print("audit_frontend_ui: baseline unchanged because list-table invariants fail", file=sys.stderr)
            for finding in failures:
                print(f"[UI] {finding}", file=sys.stderr)
            return 1
        BASELINE.write_text(json.dumps(debt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"audit_frontend_ui: wrote {len(debt)} debt entries")
        return 0


    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    metric_names = ("hex_colors", "transition_all", "lines_over_500")
    for path in sorted(set(debt) | set(baseline)):
        actual = debt.get(path, {})
        allowed = baseline.get(path, {})
        for metric in metric_names:
            value = int(actual.get(metric, 0))
            expected = int(allowed.get(metric, 0))
            if value != expected:
                failures.append(
                    f"{path}: {metric} baseline is stale (baseline={expected}, actual={value}); "
                    "regenerate it only after intentional cleanup"
                )

    if args.baseline_ref:
        previous = subprocess.run(
            ["git", "show", f"{args.baseline_ref}:scripts/ui_debt_baseline.json"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # The first commit that introduces the gate has no historical baseline.
        if previous.returncode == 0:
            previous_baseline = json.loads(previous.stdout)
            for path, metrics in baseline.items():
                previous_metrics = previous_baseline.get(path, {})
                for metric in metric_names:
                    value = int(metrics.get(metric, 0))
                    old_value = int(previous_metrics.get(metric, 0))
                    if value > old_value:
                        failures.append(
                            f"{path}: {metric} committed baseline increased {old_value} -> {value}"
                        )
    if failures:
        for finding in failures:
            print(f"[UI] {finding}")
        print(f"audit_frontend_ui: {len(failures)} failure(s)")
        return 1
    totals = {name: sum(item[name] for item in debt.values()) for name in metric_names}
    print(f"audit_frontend_ui: table invariants pass; legacy debt frozen {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
