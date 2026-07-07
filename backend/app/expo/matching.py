"""发型匹配规则引擎（纯函数，不调 AI）。

刻意用规则打分：可解释（"为什么推这款"能讲给客户听）、可调（改
config/expo_matching.yaml 立即生效）、零延迟零成本。
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger("commission.expo")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "expo_matching.yaml"

DEFAULT_WEIGHTS = {"face_shape": 30, "skin_tone": 20, "need": 25, "style": 15, "age": 10}
DEFAULT_TOP_N = 3

_FACE_SHAPE_LABELS = {
    "oval": "鹅蛋脸", "round": "圆脸", "square": "方脸",
    "heart": "瓜子脸", "long": "长脸", "diamond": "菱形脸",
}


def load_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        weights = {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}
        return {
            "weights": weights,
            "top_n": int(cfg.get("top_n", DEFAULT_TOP_N)),
            "zhizhen_anchor": bool(cfg.get("zhizhen_anchor", True)),
        }
    except Exception as exc:  # 配置缺失/损坏走默认，不阻断现场
        logger.warning("expo_matching.yaml load failed, using defaults: %s", exc)
        return {"weights": dict(DEFAULT_WEIGHTS), "top_n": DEFAULT_TOP_N, "zhizhen_anchor": True}


def _tag_list(fit_tags: dict | None, key: str) -> list:
    if not fit_tags:
        return []
    value = fit_tags.get(key) or []
    return value if isinstance(value, list) else [value]


def _age_overlap(age_range: str | None, wig_ranges: list) -> bool:
    """age_range 形如 '40-50'；wig_ranges 形如 ['35-45','45-60']。区间有交集即命中。"""
    if not age_range or not wig_ranges:
        return False

    def parse(rng):
        try:
            lo, hi = str(rng).replace("岁", "").split("-")
            return int(lo), int(hi)
        except (ValueError, AttributeError):
            return None

    target = parse(age_range)
    if not target:
        return False
    for rng in wig_ranges:
        parsed = parse(rng)
        if parsed and parsed[0] <= target[1] and target[0] <= parsed[1]:
            return True
    return False


def score_wig(wig, analysis: dict, reg: dict, weights: dict) -> float:
    """单款打分。wig 为 ExpoWig ORM 或具备同名属性的对象。

    gender 硬过滤由调用方（match_wigs）负责，这里只算加权分。
    """
    tags = wig.fit_tags or {}
    score = 0.0

    if analysis.get("face_shape") in _tag_list(tags, "face_shapes"):
        score += weights["face_shape"]

    skin = analysis.get("skin_tone") or {}
    if skin.get("depth") in _tag_list(tags, "skin_depths"):
        score += weights["skin_tone"] / 2
    if skin.get("undertone") in _tag_list(tags, "undertones"):
        score += weights["skin_tone"] / 2

    if reg.get("primary_need") in _tag_list(tags, "needs"):
        score += weights["need"]

    style_tags = _tag_list(tags, "styles")
    style_hits = sum(
        1 for s in (analysis.get("temperament"), reg.get("style_pref")) if s and s in style_tags
    )
    if style_hits:
        score += weights["style"] * (1 if style_hits >= 2 else 0.6)

    if _age_overlap(analysis.get("age_range"), _tag_list(tags, "age_ranges")):
        score += weights["age"]

    return score


def match_wigs(wigs: list, analysis: dict, reg: dict, batch: int = 0) -> list[dict]:
    """全量排序 + 至臻锚点，返回 [{wig_id, score, reason}] 的完整排名。

    batch 参数由调用方用 matched_wig_ids[batch*top_n:] 切片实现"换一批"，
    本函数总是返回完整排名（存库后切片，保证换批稳定）。
    """
    cfg = load_config()
    weights, top_n = cfg["weights"], cfg["top_n"]

    gender = analysis.get("gender")
    candidates = []
    for wig in wigs:
        wig_gender = (wig.fit_tags or {}).get("gender")
        if gender and wig_gender and wig_gender != gender:
            continue  # gender 硬过滤
        candidates.append(wig)

    # 失败路径兜底：性别过滤全灭（如男顾客 × 全女款库）时降级为不过滤照常排名，
    # 展位不能出现"甄选 0 款"死路——宁可给参考款也不给空屏
    if not candidates and wigs:
        msg = f"[expo] matching gender filter eliminated all {len(wigs)} wigs (gender={gender}), fallback to unfiltered ranking"
        logger.warning(msg)
        print(msg, flush=True)
        candidates = list(wigs)

    ranked = sorted(
        candidates,
        key=lambda w: (score_wig(w, analysis, reg, weights), w.priority or 0),
        reverse=True,
    )

    # 至臻锚点：前 6 名中有至臻款但第一批（top_n）没有 → 用至臻款替换第一批末位
    if cfg["zhizhen_anchor"] and len(ranked) > top_n:
        first_batch = ranked[:top_n]
        if not any(w.series == "zhizhen" for w in first_batch):
            pool = ranked[top_n : top_n * 2]
            anchor = next((w for w in pool if w.series == "zhizhen"), None)
            if anchor:
                swapped = first_batch[-1]
                ranked[top_n - 1] = anchor
                anchor_idx = ranked.index(anchor, top_n)
                ranked[anchor_idx] = swapped

    return [
        {
            "wig_id": w.id,
            "score": round(score_wig(w, analysis, reg, weights), 1),
            "reason": build_reason(w, analysis, reg),
        }
        for w in ranked
    ]


def build_reason(wig, analysis: dict, reg: dict) -> str:
    """生成"为什么适合您"一句话（客户屏展示，只说正面）。"""
    tags = wig.fit_tags or {}
    parts = []
    face = analysis.get("face_shape")
    if face in _tag_list(tags, "face_shapes"):
        parts.append(f"版型修饰{_FACE_SHAPE_LABELS.get(face, '脸部')}线条")
    skin = analysis.get("skin_tone") or {}
    if skin.get("undertone") in _tag_list(tags, "undertones"):
        parts.append("发色与您的肤色同调")
    temperament = analysis.get("temperament")
    if temperament and temperament in _tag_list(tags, "styles"):
        parts.append(f"衬托{temperament}气质")
    if wig.series == "zhizhen":
        parts.append("至臻系列全手工钩织")
    if not parts and wig.selling_points:
        parts.append(wig.selling_points.split("\n")[0][:30])
    return "，".join(parts[:2]) or "依据您的整体特征甄选"
