"""Shared outbound print ordering for the HTML payload and Word export."""
import re


def _natural_spec(value):
    text = str(value or "").strip().upper()
    # Unicode order keeps 天才 before 平行; locale/pinyin ordering does not.
    return (not bool(text), tuple(
        (0, int(part)) if part.isascii() and part.isdigit() else (1, part)
        for part in re.split(r"([0-9]+)", text) if part
    ))


def _size(item):
    value = str(item.get("size") or "").strip()
    if not value:
        # Legacy products encode size as the first segment after the category.
        parts = re.split(r"[/／]", str(item.get("product_name") or ""))
        value = parts[1].strip() if len(parts) > 1 else ""
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(?:寸|英寸|["″]|in(?:ch(?:es)?)?)?', value, re.I)
    return float(match[1]) if match else float("inf")


def sort_outbound_print_items(items: list[dict]) -> list[dict]:
    """Stable sort, without mutating source items or inspection/photo ordering."""
    return sorted(items, key=lambda item: (_natural_spec(item.get("spec")), _size(item)))
