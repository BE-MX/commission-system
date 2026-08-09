"""Deterministic classification for multi-output image requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


OutputMode = Literal["single", "composite", "separate", "clarify", "reject"]


@dataclass(frozen=True, slots=True)
class MultiOutputIntent:
    mode: OutputMode
    count: int = 1
    labels: tuple[str, ...] = ()


STANDARD_ANGLES = {
    2: ("正面", "侧面 45°"),
    3: ("正面", "左侧 45°", "右侧 45°"),
    4: ("正面", "左侧 45°", "右侧 45°", "背面"),
}

_CHINESE_COUNTS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_COUNT_TOKEN = r"(?P<count>(?<!\d)\d{1,2}(?!\d)|[一二两三四五六七八九十])"
_COUNT_PATTERNS = (
    re.compile(_COUNT_TOKEN + r"\s*(?:张|幅)\s*(?:效果图|图片|图像|图)?"),
    re.compile(
        _COUNT_TOKEN
        + r"\s*(?:个|种|套|组)?\s*(?:不同(?:的)?|标准)?\s*"
        + r"(?:角度|视角|方向|版本|方案|变体|效果图|图片|图像|张图|张图片)"
    ),
    re.compile(_COUNT_TOKEN + r"\s*款(?:设计|方案|效果图|图片|图)?"),
)
_CONVENTIONAL_VIEW_PATTERN = re.compile(r"(?P<count>[三四])视图")
_REFERENCE_ASSET_SUFFIX = re.compile(
    r"^[^图，。；;]{0,6}(?:参考图|素材图|原图|底图)"
)
_REFERENCE_ASSET_PREFIX = re.compile(
    r"(?:(?:参考|素材|原|底)图(?:共|有|是)?|参考)\s*$"
)
_INPUT_ASSET_VERB_PREFIX = re.compile(r"(?:使用|上传|采用|用)\s*$")
_INPUT_IMAGE_CONTEXT = re.compile(r"(?:张|幅)[^图，。；;]{0,8}(?:图片|图)")
_OUTPUT_VERB_SUFFIX = re.compile(r"(?:生成|输出|制作|出图)\s*$")
_ANGLE_PATTERN = re.compile(
    r"左侧(?:面)?(?:\s*\d{1,3}\s*(?:°|度))?|"
    r"右侧(?:面)?(?:\s*\d{1,3}\s*(?:°|度))?|"
    r"正面|背面|侧面(?:\s*\d{1,3}\s*(?:°|度))?|"
    r"俯视(?:图)?|顶视(?:图)?|仰视(?:图)?"
)
_COMPOSITE_PATTERN = re.compile(
    r"同一张(?:图|画布)|一张图|一张画布|放在一张|"
    r"拼(?:到|在|成)?一张|合成一张|拼版|拼图|三视图|四视图|多视图|"
    r"九宫格|排版展示"
)
_SEPARATE_PATTERN = re.compile(
    r"分别(?:生成|制作|输出|出图)|分开(?:生成|制作|输出|出图)|"
    r"独立(?:生成|制作|输出)|各(?:生成|制作|输出)|"
    r"每(?:个|一)(?:角度|视角).{0,6}(?:一张|一幅)|独立图片|单独出图"
)
_GENERATED_IMAGE_COUNT_PATTERN = re.compile(
    r"(?:生成|输出|制作|出图)\s*" + _COUNT_TOKEN + r"\s*张"
)
_NEGATED_SIGNAL_PREFIX = re.compile(r"(?:不要|别|无需|禁止)[^，。；;]{0,8}$")
_PER_IMAGE_SIGNAL_PREFIX = re.compile(r"(?:每|各|每个角度|每个视角)\s*$")


def _parse_count(token: str) -> int:
    if token.isdigit():
        return int(token)
    return _CHINESE_COUNTS[token]


def _find_requested_count(prompt: str) -> int | None:
    matches: list[tuple[int, int]] = []
    for pattern in _COUNT_PATTERNS:
        for match in pattern.finditer(prompt):
            following = prompt[match.end() : match.end() + 12]
            preceding = prompt[max(0, match.start() - 8) : match.start()]
            is_output_count = _OUTPUT_VERB_SUFFIX.search(preceding)
            is_reference_count = _REFERENCE_ASSET_SUFFIX.match(
                following
            ) or _REFERENCE_ASSET_PREFIX.search(preceding)
            is_input_asset_count = _INPUT_ASSET_VERB_PREFIX.search(
                preceding
            ) and _INPUT_IMAGE_CONTEXT.search(match.group(0) + following)
            is_reference_count = is_reference_count or is_input_asset_count
            if is_reference_count and not is_output_count:
                continue
            count = _parse_count(match.group("count"))
            if count >= 2:
                matches.append((match.start(), count))
    for match in _CONVENTIONAL_VIEW_PATTERN.finditer(prompt):
        matches.append((match.start(), _parse_count(match.group("count"))))
    if not matches:
        return None
    return min(matches)[1]


def _extract_angle_labels(prompt: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _ANGLE_PATTERN.finditer(prompt):
        raw = match.group(0)
        if raw.startswith("左侧"):
            label = "左侧"
        elif raw.startswith("右侧"):
            label = "右侧"
        elif raw.startswith(("俯视", "顶视")):
            label = "俯视"
        elif raw.startswith("仰视"):
            label = "仰视"
        elif raw.startswith("侧面"):
            label = "侧面"
        else:
            label = raw
        degrees = re.search(r"(\d{1,3})\s*(?:°|度)", raw)
        if degrees:
            label = f"{label} {degrees.group(1)}°"
        if label not in labels:
            labels.append(label)
    return tuple(labels)


def _resolved_labels(
    prompt: str,
    count: int,
    named_labels: tuple[str, ...],
) -> tuple[str, ...]:
    if len(named_labels) == count:
        return named_labels
    if (
        "角度" in prompt
        or "视角" in prompt
        or "方向" in prompt
        or "视图" in prompt
        or named_labels
    ):
        return STANDARD_ANGLES.get(count, ())
    return tuple(f"独立变体 {index}/{count}" for index in range(1, count + 1))


def _has_positive_signal(
    pattern: re.Pattern[str],
    prompt: str,
    *,
    exclude_per_image: bool = False,
) -> bool:
    for match in pattern.finditer(prompt):
        clause_prefix = prompt[max(0, match.start() - 12) : match.start()]
        if not _NEGATED_SIGNAL_PREFIX.search(clause_prefix):
            if exclude_per_image and _PER_IMAGE_SIGNAL_PREFIX.search(clause_prefix):
                continue
            return True
    return False


def classify_multi_output_intent(prompt: str) -> MultiOutputIntent:
    requested_count = _find_requested_count(prompt)
    named_labels = _extract_angle_labels(prompt)
    is_composite = _has_positive_signal(
        _COMPOSITE_PATTERN,
        prompt,
        exclude_per_image=True,
    )
    is_separate = _has_positive_signal(_SEPARATE_PATTERN, prompt)
    named_count = (
        len(named_labels)
        if len(named_labels) >= 2 and (is_composite or is_separate)
        else None
    )
    count = requested_count or named_count or 1

    if count > 4:
        return MultiOutputIntent(mode="reject", count=count)
    if count < 2:
        return MultiOutputIntent(mode="single")

    labels = _resolved_labels(prompt, count, named_labels)
    if requested_count is not None and named_labels and requested_count != len(named_labels):
        return MultiOutputIntent(mode="clarify", count=count, labels=labels)
    if is_composite and is_separate:
        mode: OutputMode = "clarify"
    elif is_composite:
        mode: OutputMode = "composite"
    elif is_separate or _GENERATED_IMAGE_COUNT_PATTERN.search(prompt):
        mode = "separate"
    else:
        mode = "clarify"
    return MultiOutputIntent(mode=mode, count=count, labels=labels)


def build_output_prompt(prompt: str, label: str) -> str:
    if label.startswith("独立变体"):
        constraint = "需与同组其他结果有可见差异，但不得虚构用户未指定的场景或属性。"
    else:
        constraint = "人物身份、服装、发型、背景必须与参考图一致。"
    return (
        f"{prompt}\n\n"
        f"输出要求：本次锁定为“{label}”；仅生成这一张独立图片，不得拼图，"
        f"不得在同一画面中包含其他角度或版本。{constraint}"
    )


def build_composite_prompt(prompt: str, labels: tuple[str, ...]) -> str:
    joined_labels = "、".join(labels)
    return (
        f"{prompt}\n\n"
        f"输出要求：在同一张画布中清晰呈现以下全部视图：{joined_labels}；"
        "使用整齐、易比较的分区布局，不得拆分为多张图片。"
    )
