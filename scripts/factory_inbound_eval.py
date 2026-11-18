"""Score saved factory OCR results against warehouse-reviewed answers offline.

Inputs are private JSON objects keyed by image filename. Each value has
delivery_no, month, day and lines with row and recognition fields (see design.md).
In a truth fixture, optional expected_sku_id and order_hit annotate ranking.
In predictions, optional candidate_sku_ids lists SKU IDs in shown order.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import unicodedata


FIELDS = ("order_ref", "quantity", "line_type", "length", "weight", "color", "grade")
HEADERS = ("delivery_no", "month", "day")


def normalized(value):
    return unicodedata.normalize("NFKC", value).strip() if isinstance(value, str) else value


def by_row(note):
    rows = note["lines"]
    result = {row["row"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate row numbers")
    return result


def score(truth, predictions):
    counts = Counter()
    correct = Counter()
    extra_rows = unsafe_rows = 0
    for filename, expected in truth.items():
        if not expected or not expected.get("lines"):
            raise ValueError(f"Missing warehouse-reviewed answer for {filename}")
        actual = predictions.get(filename, {"lines": []})
        target_rows, actual_rows = by_row(expected), by_row(actual)
        for field in HEADERS:
            counts[field] += 1
            correct[field] += bool(actual.get("lines")) and normalized(expected[field]) == normalized(actual.get(field))
        extra = actual_rows.keys() - target_rows.keys()
        extra_rows += len(extra)
        unsafe_rows += sum(actual_rows[key].get("line_type") == "inbound" for key in extra)
        for key, target in target_rows.items():
            observed = actual_rows.get(key, {})
            for field in FIELDS:
                if field == "grade" and not target.get("grade"):
                    continue
                counts[field] += 1
                correct[field] += field in observed and normalized(target[field]) == normalized(observed[field])
            unsafe_rows += target["line_type"] != "inbound" and observed.get("line_type") == "inbound"
            if target.get("expected_sku_id") is not None:
                matched = observed.get("candidate_sku_ids", [])
                ranking = "order_hit_top1" if target.get("order_hit") else "no_order_unique"
                counts[ranking] += 1
                correct[ranking] += (matched[:1] if target.get("order_hit") else matched) == [target["expected_sku_id"]]
    return {
        "files": len(truth),
        "unexpected_files": sorted(predictions.keys() - truth.keys()),
        "fields": {field: {"correct": correct[field], "total": total, "rate": round(correct[field] / total, 4)}
                   for field, total in counts.items()},
        "extra_rows": extra_rows,
        "non_inbound_as_inbound": unsafe_rows,
    }


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    template = sub.add_parser("template")
    template.add_argument("directory", type=Path)
    compare = sub.add_parser("score")
    compare.add_argument("truth", type=Path)
    compare.add_argument("predictions", type=Path)
    args = parser.parse_args()
    if args.command == "template":
        data = {file.name: None for file in sorted(args.directory.iterdir())
                if file.is_file() and file.suffix.lower() in {".jpg", ".jpeg", ".png"}}
    else:
        data = score(load(args.truth), load(args.predictions))
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
