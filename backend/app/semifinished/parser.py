"""产品名称到半成品组成的纯函数解析器。"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


PARSER_VERSION = "sf-v2"
_SIZE_RE = re.compile(r"^\d+(?:\.\d+)?$")
_WEIGHT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*g$", re.I)


@dataclass(frozen=True)
class ParsedProduct:
    size: str
    color_expression: str
    unit_grams: Decimal
    components: tuple[str, ...]
    color_type: str
    parse_status: str
    message: str | None = None


def normalize_color(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    return value.upper()


def _parse_weight(value: str | None) -> Decimal | None:
    match = _WEIGHT_RE.fullmatch((value or "").strip())
    if not match:
        return None
    try:
        weight = Decimal(match.group(1))
    except InvalidOperation:
        return None
    return weight if Decimal("0") < weight <= Decimal("500") else None


def _split_branch(branch: str) -> tuple[list[str], str, list[str]]:
    branch = normalize_color(branch)
    if not branch:
        return [], "solid", ["颜色为空"]
    if not branch.startswith("#"):
        return [branch], "named_t", []
    if branch.startswith("#P"):
        parts = [part.strip().lstrip("#") for part in branch[2:].split("/") if part.strip()]
        if len(parts) < 2:
            return ["#" + parts[0]] if parts else [], "piano", ["P 色缺少第二个颜色"]
        return ["#" + part for part in parts], "piano", []
    match = re.match(r"^(#.+?T)P([^/]+)(?:/(.+))?$", branch, re.I)
    if match:
        tails = [match.group(2)]
        if match.group(3):
            tails.extend(part for part in match.group(3).split("/") if part)
        errors = [] if len(tails) >= 2 else ["TP 色缺少第二个底色"]
        return [f"{match.group(1)}/{tail}" for tail in tails], "t", errors
    match = re.match(r"^(#.+?T)/?([^/]+)$", branch, re.I)
    if match:
        return [f"{match.group(1)}/{match.group(2)}"], "t", []
    if "/" in branch:
        return [branch], "compound", ["无法识别的斜杠颜色表达式"]
    return [branch], "solid", []


def split_color_expression(expression: str) -> tuple[tuple[str, ...], str, list[str]]:
    components: list[str] = []
    errors: list[str] = []
    types: list[str] = []
    normalized = normalize_color(expression)
    # 英文命名色（如 "Salt & Pepper"）整体就是一个 T 色名称；只有带 # 的
    # 编码表达式才把 & 解释为多个半成品分支。
    branches = (
        [part for part in normalized.split("&") if part.strip()]
        if normalized.startswith("#") else [normalized]
    )
    for branch in branches:
        values, color_type, branch_errors = _split_branch(branch)
        components.extend(values)
        types.append(color_type)
        errors.extend(branch_errors)
    unique: list[str] = []
    seen: set[str] = set()
    for value in components:
        key = normalize_color(value)
        if key not in seen:
            unique.append(key)
            seen.add(key)
    color_type = "compound" if len(branches) > 1 else (types[0] if types else "solid")
    return tuple(unique), color_type, errors


def parse_product(
    product_name: str,
    *,
    structured_size: str | None = None,
    structured_color: str | None = None,
    structured_unit: str | None = None,
) -> ParsedProduct | None:
    parts = [part.strip() for part in (product_name or "").split("/")]
    used_fallback = False
    size = color = ""
    weight: Decimal | None = None
    if len(parts) >= 4 and _SIZE_RE.fullmatch(parts[1]):
        candidate_weight = _parse_weight(parts[-1])
        if candidate_weight is not None:
            size = parts[1]
            color = "/".join(parts[2:-1])
            weight = candidate_weight
    if weight is None:
        fallback_size = (structured_size or "").strip()
        fallback_weight = _parse_weight(structured_unit)
        if _SIZE_RE.fullmatch(fallback_size) and (structured_color or "").strip() and fallback_weight:
            size = fallback_size
            color = (structured_color or "").strip()
            weight = fallback_weight
            used_fallback = True
        else:
            return None
    components, color_type, errors = split_color_expression(color)
    if not components:
        return None
    if used_fallback:
        errors.append("产品名称异常，已使用结构化字段回退")
    status = "confirmed" if len(components) == 1 and not errors else "needs_review"
    return ParsedProduct(
        size=size,
        color_expression=normalize_color(color),
        unit_grams=weight,
        components=components,
        color_type=color_type,
        parse_status=status,
        message="；".join(errors) or None,
    )
