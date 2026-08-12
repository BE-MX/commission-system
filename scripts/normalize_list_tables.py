#!/usr/bin/env python3
"""One-shot idempotent normalization for Element Plus list tables in Vue views."""

import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
VIEW_ROOTS = (REPO / "frontend/src", REPO / "frontend-pm/src")


def _tags(text: str, name: str) -> list[tuple[int, int, str]]:
    """Return opening tags while respecting > inside quoted Vue expressions."""
    result = []
    start = 0
    needle = f"<{name}"
    while True:
        index = text.find(needle, start)
        if index < 0:
            break
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
                result.append((index, cursor + 1, text[index:cursor + 1]))
                start = cursor + 1
                break
            cursor += 1
        else:
            break
    return result


def _normalize_table(match: re.Match[str]) -> str:
    tag = match.group(0)
    tag = re.sub(r"\s+stripe(?=\s|=|>)", "", tag)
    if not re.search(r"(?<!:)\bborder(?=\s|=|>)", tag):
        tag = tag[:-1].rstrip() + " border>"
    class_match = re.search(r'\bclass\s*=\s*(["\'])(.*?)\1', tag, re.S)
    if class_match:
        classes = class_match.group(2).split()
        if "list-table" not in classes:
            replacement = f'class={class_match.group(1)}{class_match.group(2)} list-table{class_match.group(1)}'
            tag = tag[:class_match.start()] + replacement + tag[class_match.end():]
    else:
        tag = tag[:-1].rstrip() + ' class="list-table">'
    return tag


def normalize(text: str) -> str:
    for start, end, tag in reversed(_tags(text, "el-table")):
        text = text[:start] + _normalize_table(re.match(r".*", tag, re.S)) + text[end:]

    def normalize_column(match: re.Match[str]) -> str:
        tag = match.group(0)
        tag = re.sub(r'(?<![-:])\bwidth\s*=\s*(["\'])(\d+)\1', r'min-width=\1\2\1', tag)
        tag = re.sub(r'\s+align\s*=\s*(["\'])center\1', "", tag)
        return tag

    for start, end, tag in reversed(_tags(text, "el-table-column")):
        text = text[:start] + normalize_column(re.match(r".*", tag, re.S)) + text[end:]

    def normalize_button(match: re.Match[str]) -> str:
        return re.sub(r'\s+size\s*=\s*(["\'])small\1', "", match.group(0))

    for start, end, tag in reversed(_tags(text, "el-button")):
        text = text[:start] + normalize_button(re.match(r".*", tag, re.S)) + text[end:]
    return text


def main() -> int:
    changed = []
    for root in VIEW_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.vue"):
            original = path.read_text(encoding="utf-8")
            updated = normalize(original)
            if updated != original:
                path.write_text(updated, encoding="utf-8")
                changed.append(path.relative_to(REPO).as_posix())
    print(f"normalize_list_tables: updated {len(changed)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
