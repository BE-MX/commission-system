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
# 优先级小幅折算加分：final = base + min(priority*unit, cap)。cap 远小于单项权重，
# 只在同评级(相近匹配)内把高优先级款拉前、抬高显示分，不让低匹配款跨大档超过高匹配款。
DEFAULT_PRIORITY_BOOST = {"unit": 0.2, "cap": 6.0}
# must_recommend 保证进入前 N 个推荐（不强占第一）；这里的 N 即"推荐列表"长度
GUARANTEED_LIST_SIZE = 6

FACE_SHAPE_LABELS = {
    "oval": "鹅蛋脸", "round": "圆脸", "square": "方脸",
    "heart": "瓜子脸", "long": "长脸", "diamond": "菱形脸",
}


def load_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        weights = {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}
        pb = {**DEFAULT_PRIORITY_BOOST, **(cfg.get("priority_boost") or {})}
        return {
            "weights": weights,
            "top_n": int(cfg.get("top_n", DEFAULT_TOP_N)),
            "zhizhen_anchor": bool(cfg.get("zhizhen_anchor", True)),
            "priority_boost": {"unit": float(pb["unit"]), "cap": float(pb["cap"])},
        }
    except Exception as exc:  # 配置缺失/损坏走默认，不阻断现场
        logger.warning("expo_matching.yaml load failed, using defaults: %s", exc)
        return {
            "weights": dict(DEFAULT_WEIGHTS), "top_n": DEFAULT_TOP_N,
            "zhizhen_anchor": True, "priority_boost": dict(DEFAULT_PRIORITY_BOOST),
        }


def priority_boost(priority, pb: dict) -> float:
    """优先级折算的小幅加分（封顶），叠加到 base 匹配分上。"""
    return min(max(priority or 0, 0) * pb["unit"], pb["cap"])


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
    weights, top_n, pb = cfg["weights"], cfg["top_n"], cfg["priority_boost"]

    gender = analysis.get("gender")
    candidates = []
    for wig in wigs:
        wig_gender = (wig.fit_tags or {}).get("gender")
        if gender and wig_gender and wig_gender != gender:
            continue  # gender 硬过滤（对必推款同样生效：不给男顾客强推女款）
        candidates.append(wig)

    # 失败路径兜底：性别过滤全灭（如男顾客 × 全女款库）时降级为不过滤照常排名，
    # 展位不能出现"甄选 0 款"死路——宁可给参考款也不给空屏
    if not candidates and wigs:
        msg = f"[expo] matching gender filter eliminated all {len(wigs)} wigs (gender={gender}), fallback to unfiltered ranking"
        logger.warning(msg)
        print(msg, flush=True)
        candidates = list(wigs)

    # final = base 匹配分 + 优先级小幅折算加分（同一分值下 priority 高的显示分更高、排更前）
    score_by_id = {
        w.id: round(score_wig(w, analysis, reg, weights) + priority_boost(w.priority, pb), 1)
        for w in candidates
    }
    ranked = sorted(
        candidates, key=lambda w: (score_by_id[w.id], w.priority or 0), reverse=True,
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

    # 必推保证：must_recommend 款一定进前 GUARANTEED_LIST_SIZE，但不强占第一（保留最高分在首位）
    ranked = _ensure_must_recommend(ranked, GUARANTEED_LIST_SIZE)

    return [
        {"wig_id": w.id, "score": score_by_id[w.id], "reason": build_reason(w, analysis, reg)}
        for w in ranked
    ]


def _ensure_must_recommend(ranked: list, k: int) -> list:
    """把排在第 k 名之外的必推款提升进前 k 名（从末位往前填，保留 index 0 最高分不动）。

    多个必推超过可用坑位时 best-effort（只填得下的），并 log 提示。被挤出的按原分留在后面。
    """
    if len(ranked) <= k:
        return ranked  # 全在列表内，无需处理
    top, rest = ranked[:k], ranked[k:]
    must_in_rest = [w for w in rest if getattr(w, "must_recommend", 0)]
    if not must_in_rest:
        return ranked
    # 前 k 内可替换的非必推位（index 0 = 最高分，永不替换；从末位开始替换扰动最小）
    replaceable = [i for i in range(1, k) if not getattr(top[i], "must_recommend", 0)]
    for must_w in must_in_rest:
        if not replaceable:
            msg = f"[expo] must_recommend overflow: only {k - 1} guaranteed slots, some must-recommend wigs stay below top {k}"
            logger.warning(msg)
            print(msg, flush=True)
            break
        idx = replaceable.pop()  # 末位优先
        displaced = top[idx]
        top[idx] = must_w
        rest.remove(must_w)
        rest.append(displaced)
    return top + rest


def build_reason(wig, analysis: dict, reg: dict) -> str:
    """生成"为什么适合您"一句话（客户屏展示，只说正面）。"""
    tags = wig.fit_tags or {}
    parts = []
    face = analysis.get("face_shape")
    if face in _tag_list(tags, "face_shapes"):
        parts.append(f"版型修饰{FACE_SHAPE_LABELS.get(face, '脸部')}线条")
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
