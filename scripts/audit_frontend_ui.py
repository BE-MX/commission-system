#!/usr/bin/env python3
"""Audit list-table invariants and freeze measurable legacy UI debt.

Debt metrics cover DESIGN.md 的 [可门禁] 条目（2026-09-30 落地）：
筛选控件 size/inline 宽度、分页 layout、empty-text、dialog/drawer 宽度白名单、
底部按钮区别名、el-tag 静态 type、date-picker value-format、:deep(.el-) 覆盖、
裸 ElMessage/ElNotification/ElMessageBox、金额格式化散写（toLocaleString /
Intl.NumberFormat / toFixed(2)）。.vue 全量度量；.js 只统计消息与金额两类代码模式。
"""

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

# --- Component-spec debt metrics (DESIGN.md [可门禁] 条目，2026-09-30 落地) ---
CONTROL_TAGS = ("el-input", "el-select", "el-date-picker")
CANONICAL_PAGINATION_LAYOUT = "total,sizes,prev,pager,next"
DIALOG_WIDTH_WHITELIST = {"480", "640", "760"}
DRAWER_SIZE_WHITELIST = {"640", "760"}
VALUE_FORMAT_WHITELIST = {"YYYY-MM-DD", "YYYY-MM-DD HH:mm:ss"}
FOOTER_ALIAS = re.compile(r'\bclass\s*=\s*(["\'])[^"\']*\b(?:form-actions|drawer-actions)\b')
MESSAGE_CALLS = re.compile(r"\bElMessage(?:Box)?\b|\bElNotification\b")
MONEY_FORMAT = re.compile(r"\btoLocaleString\s*\(|\bIntl\.NumberFormat\b|\btoFixed\s*\(\s*2\s*\)")
PUBLIC_VALIDATOR = re.compile(r"\^1\[3-9\]|\[\^\\s@\]\+@")
NONSTANDARD_PAGE_DEFAULT = re.compile(r"\bpageSize\s*:\s*(?!20\b)\d+|\bpageSize\s*=\s*ref\(\s*(?!20\b)\d+")
EXCEPTIONS = REPO / 'scripts/ui_component_exceptions.json'
METRIC_NAMES = (
    'hex_colors', 'transition_all', 'small_controls', 'inline_width',
    'bad_pagination_layout', 'empty_text_attr', 'bad_dialog_width', 'bad_drawer_size',
    'footer_alias', 'static_tag_type', 'bad_value_format', 'deep_el_override',
    'message_calls', 'money_format', 'bad_pagination_sizes', 'bad_page_default',
    'form_label_position', 'bad_glass_button_size', 'non_md_glass_button', 'inline_public_validator',
)
DEEP_EL_OVERRIDE = re.compile(r":deep\(\s*\.el-")
EMPTY_TEXT_ATTR = re.compile(r"\bempty-text\s*=")
SIZE_SMALL = re.compile(r'\bsize\s*=\s*["\']small')
INLINE_WIDTH = re.compile(r'\bstyle\s*=\s*(["\'])[^"\']*\bwidth\s*:')


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


def _attr(tag: str, name: str) -> str | None:
    """Return the static attribute value, or None when absent or dynamically bound (:name)."""
    match = re.search(rf'(?<![-:\w]){name}\s*=\s*(["\'])(.*?)\1', tag, re.S)
    return match.group(2) if match else None


def _dimension_ok(tag: str, name: str, whitelist: set[str]) -> bool:
    """Absent/dynamic attributes are unjudged; static ones must be whitelisted pixel sizes."""
    value = _attr(tag, name)
    if value is None:
        return True
    match = re.fullmatch(r"(\d+)(?:px)?", value.strip())
    return bool(match) and match.group(1) in whitelist


def _value_format_ok(tag: str) -> bool:
    value = _attr(tag, "value-format")
    return value is None or value.strip() in VALUE_FORMAT_WHITELIST


def _vue_metrics(text: str) -> dict[str, int]:
    controls = [tag for name in CONTROL_TAGS for tag in _tags(text, name)]
    return {
        "hex_colors": len(HEX.findall(text)),
        "transition_all": len(TRANSITION_ALL.findall(text)),
        "small_controls": sum(1 for tag in controls if SIZE_SMALL.search(tag)),
        "inline_width": sum(1 for tag in controls if INLINE_WIDTH.search(tag)),
        "bad_pagination_layout": sum(
            1
            for tag in _tags(text, "el-pagination")
            if re.sub(r"\s+", "", _attr(tag, "layout") or "") != CANONICAL_PAGINATION_LAYOUT
        ),
        "empty_text_attr": len(EMPTY_TEXT_ATTR.findall(text)),
        "bad_dialog_width": sum(1 for tag in _tags(text, "el-dialog") if not _dimension_ok(tag, "width", DIALOG_WIDTH_WHITELIST)),
        "bad_drawer_size": sum(1 for tag in _tags(text, "el-drawer") if not _dimension_ok(tag, "size", DRAWER_SIZE_WHITELIST)),
        "footer_alias": len(FOOTER_ALIAS.findall(text)),
        "static_tag_type": sum(1 for tag in _tags(text, "el-tag") if _attr(tag, "type") is not None),
        "bad_value_format": sum(1 for tag in _tags(text, "el-date-picker") if not _value_format_ok(tag)),
        "deep_el_override": len(DEEP_EL_OVERRIDE.findall(text)),
        "message_calls": len(MESSAGE_CALLS.findall(text)),
        "money_format": len(MONEY_FORMAT.findall(text)),
        "bad_pagination_sizes": sum(
            1 for tag in _tags(text, 'el-pagination')
            if not _pagination_sizes_ok(tag)
        ),
        "bad_page_default": len(NONSTANDARD_PAGE_DEFAULT.findall(text)),
        "form_label_position": sum(_attr(tag, 'label-position') != 'top' for tag in _tags(text, 'el-form')),
        "bad_glass_button_size": sum(
            _attr(tag, 'size') not in (None, 'xs', 'sm', 'md', 'lg', 'xl')
            for tag in _tags(text, 'GlassButton')
        ),
        "non_md_glass_button": sum(_attr(tag, 'size') not in (None, 'md') for tag in _tags(text, 'GlassButton')),
        "inline_public_validator": len(PUBLIC_VALIDATOR.findall(text)),
    }


def _js_metrics(text: str) -> dict[str, int]:
    return {
        "message_calls": len(MESSAGE_CALLS.findall(text)),
        "money_format": len(MONEY_FORMAT.findall(text)),
        "bad_page_default": len(NONSTANDARD_PAGE_DEFAULT.findall(text)),
        "inline_public_validator": len(PUBLIC_VALIDATOR.findall(text)),
    }


def _pagination_sizes_ok(tag: str) -> bool:
    match = re.search(r'(?<![-\w]):page-sizes\s*=\s*(["\'])(.*?)\1', tag, re.S)
    if not match:
        return False
    value = re.sub(r'\s+', '', match.group(2))
    # A variable binding needs semantic review; literal arrays are checked exactly.
    return value == '[20,50,100]' or bool(re.fullmatch(r'[a-zA-Z_$][\w.$]*', value))


def apply_exceptions(relative: str, metrics: dict[str, int], exceptions: dict) -> dict[str, int]:
    metrics = dict(metrics)
    # Each app owns one feedback/format/validator implementation. Domain callers are gated.
    if relative in ('frontend/src/utils/feedback.js', 'frontend-pm/src/utils/feedback.js'):
        metrics['message_calls'] = 0
    if relative in ('frontend/src/utils/money.js', 'frontend-pm/src/utils/money.js'):
        metrics['money_format'] = 0
    if relative == 'frontend/src/utils/validators.js':
        metrics['inline_public_validator'] = 0
    for metric, entry in exceptions.get(relative, {}).items():
        metrics[metric] = max(0, metrics.get(metric, 0) - entry['count'])
    return metrics


def baseline_increases(current: dict, previous: dict) -> list[str]:
    return [
        f'{path}: {metric} baseline increased {previous.get(path, {}).get(metric, 0)} -> {value}'
        for path, metrics in current.items() for metric, value in metrics.items()
        if metric in METRIC_NAMES and value > previous.get(path, {}).get(metric, 0)
    ]


def scan() -> tuple[list[str], dict[str, dict[str, int]]]:
    failures: list[str] = []
    debt: dict[str, dict[str, int]] = {}
    exceptions = json.loads(EXCEPTIONS.read_text(encoding='utf-8')) if EXCEPTIONS.exists() else {}
    for root in VIEW_ROOTS:
        if not root.exists():
            continue
        for path in list(root.rglob("*.vue")) + list(root.rglob("*.js")):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(REPO).as_posix()
            if path.suffix == ".js":
                metrics = _js_metrics(text)
            else:
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
                metrics = _vue_metrics(text)
            if not relative.startswith('frontend/src/'):
                # PM has its own component sizes/form conventions; do not import main-site rules.
                for metric in ('bad_pagination_sizes', 'bad_page_default', 'form_label_position', 'bad_glass_button_size', 'non_md_glass_button', 'inline_public_validator'):
                    metrics[metric] = 0
            for metric, entry in exceptions.get(relative, {}).items():
                if metric not in METRIC_NAMES or not entry.get('reason') or metrics.get(metric, 0) != entry['count']:
                    failures.append(f'{relative}: stale component exception {metric}; review its count and business reason')
            metrics = apply_exceptions(relative, metrics, exceptions)
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
        previous = json.loads(BASELINE.read_text(encoding='utf-8')) if BASELINE.exists() else {}
        failures.extend(baseline_increases(debt, previous))
        if failures:
            print("audit_frontend_ui: baseline unchanged because invariants or debt-growth checks fail", file=sys.stderr)
            for finding in failures:
                print(f"[UI] {finding}", file=sys.stderr)
            return 1
        BASELINE.write_text(json.dumps(debt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"audit_frontend_ui: wrote {len(debt)} debt entries")
        return 0


    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    metric_names = METRIC_NAMES
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
    totals = {name: sum(item.get(name, 0) for item in debt.values()) for name in metric_names}
    print(f"audit_frontend_ui: table invariants pass; legacy debt frozen {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
