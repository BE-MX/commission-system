"""Conservative transcription normalization and deterministic SKU ranking."""

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata


def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "")).upper()


def normalize_ref(value):
    value = re.sub(r"^[#＃]|单$", "", compact(value)).lstrip("0")
    return value if re.fullmatch(r"[0-9]{3,5}", value or "") else None


def parse_ref(value):
    ref = normalize_ref(value)
    if not ref or re.fullmatch(r"20[0-9]{2}", ref):
        return set()
    return {
        (int(ref[:width]), int(ref[width:]))
        for width in (1, 2)
        if 1 <= int(ref[:width]) <= 12
        and 2 <= len(ref[width:]) <= 3
        and int(ref[width:]) >= (100 if len(ref[width:]) == 3 else 1)
    }


def extract_invoice_ref(value):
    value = re.sub(r"~DEL~[0-9]+$", "", unicodedata.normalize("NFKC", value or "").strip())
    if re.search(r"-KC-[0-9]{3,5}$|^INV[0-9]{8}-[0-9]+$", value, re.I):
        return None
    exact = re.fullmatch(r"SC-([0-9]{3,5})", value, re.I)
    refs = {exact[1]} if exact else set(re.findall(
        r"(?:#|生产单|生产)\s*([0-9]{3,5})(?![0-9])|(?<![0-9])([0-9]{3,5})(?=\s*生产)", value
    ))
    if not exact:
        refs = {part for pair in refs for part in pair if part}
    valid = {normalize_ref(ref) for ref in refs if parse_ref(ref)}
    return next(iter(valid)) if len(valid) == 1 else None


def measure(value, kind):
    suffix = r"""(?:"|″|''|英寸|IN(?:CH(?:ES)?)?)?""" if kind == "length" else "(?:G|克)?"
    match = re.fullmatch(r"([0-9]{1,4}(?:\.[0-9]{1,3})?)" + suffix, compact(value))
    if match and Decimal(match[1]) > 0:
        return Decimal(match[1])
    return None


def color_key(value):
    return compact(value).strip("#")


def color_keys(value, aliases):
    exact = color_key(value)
    if exact in aliases:
        return color_key(aliases[exact]), set()
    variants = set()
    if m := re.fullmatch(r"([A-Z0-9]+)-([A-Z0-9]+)-([A-Z0-9]+)", exact):
        variants.add(f"{m[1]}TP{m[2]}/{m[3]}")
    if m := re.fullmatch(r"([A-Z0-9]+?)(?:TP|T|7)([A-Z0-9]+)-([A-Z0-9]+)", exact):
        variants.add(f"{m[1]}TP{m[2]}/{m[3]}")
    if m := re.fullmatch(r"([A-Z0-9]+)-([A-Z0-9]+)", exact):
        variants.add(f"{m[1]}T{m[2]}")
    if "T" not in exact and (m := re.fullmatch(r"([0-9]+[A-Z]?)7([0-9]+[A-Z]?)", exact)):
        variants.add(f"{m[1]}T{m[2]}")
    return exact, variants


@dataclass(frozen=True)
class Candidate:
    product_id: int
    sku_id: int | None
    name: str
    size: str
    color: str
    weight: str
    ordered: int | None = None
    remaining: int | None = None
    issue: str | None = None


def match_candidates(catalog, *, length, weight, color, process, grade, quantity, aliases=None):
    exact, converted = color_keys(color, aliases or {})
    if not all((length, weight, exact, process)):
        return "blocked", []
    eligible = [
        row for row in catalog
        if measure(row.size, "length") == length and measure(row.weight, "weight") == weight
        and process.casefold() in row.name.casefold()
        and (not grade or row.name.casefold().startswith(grade.casefold() + " ")
             or row.name.casefold() == grade.casefold())
    ]
    matches = [row for row in eligible if color_key(row.color) == exact]
    used_rule = not matches
    if used_rule:
        matches = [row for row in eligible if color_key(row.color) in converted]
    matches.sort(key=lambda row: (row.remaining != quantity, row.name, row.sku_id or 0))
    if len(matches) != 1:
        return ("choose" if matches else "blocked"), matches
    return ("confirm" if used_rule else "matched"), matches
