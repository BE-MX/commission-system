"""AI 报告文案：数字全部由后端注入，模型只产出文字；任何失败降级为模板文案。"""
import json
import logging
import re

from sqlalchemy.orm import Session

from app.ai.call_service import chat
from app.perf_goal.models import METRICS

logger = logging.getLogger(__name__)

METRIC_LABELS = {"gmv": "GMV(USD)", "new_sign": "新签客户(个)",
                 "repeat_customers": "复购客户(个)", "repeat_amount": "复购金额(USD)"}
OUTPUT_KEYS = ("summary", "highlights", "risks", "suggestions")


def _pct(value) -> str:
    return "—" if value is None else f"{round(value * 100, 1)}%"


def _numbers(payload: dict) -> dict:
    """Distill the frozen snapshot into the only numbers the model is allowed to quote."""
    metrics = {}
    for metric in METRICS:
        row = payload["metrics"][metric]
        metrics[metric] = {"label": METRIC_LABELS[metric], "target": row["target"],
                           "achieved": row["achieved"], "rate": row["rate"],
                           "delta_pp": row["delta_pp"], "unit": row["unit"]}
    people = payload.get("people") or []
    ranked = [p for p in people if p["metrics"]["gmv"]["rate"] is not None]
    return {"scope_name": payload["scope_name"], "period_label": payload["period_label"],
            "as_of": payload["as_of"], "time_progress": payload["time_progress"],
            "metrics": metrics,
            "top_people": [{"name": p["name"], "gmv_rate": p["metrics"]["gmv"]["rate"]}
                           for p in ranked[:3]],
            "bottom_people": [{"name": p["name"], "gmv_rate": p["metrics"]["gmv"]["rate"]}
                              for p in ranked[-3:]],
            "warnings": payload.get("warnings") or []}


def _prompt(numbers: dict) -> list[dict]:
    instruction = (
        "你是外贸销售团队的绩效分析师。下面是后端计算并冻结的绩效数据（JSON）。"
        "只允许引用其中出现的数字，禁止编造或换算任何数字。"
        "请输出严格 JSON（不要输出其他文字、不要用代码块包裹），格式："
        '{"summary": "80字内总体评价", "highlights": ["亮点1", "亮点2"], '
        '"risks": ["风险1"], "suggestions": ["建议1", "建议2"]}。'
        "highlights/risks/suggestions 各 1-4 条，每条 40 字内，用中文。"
    )
    return [{"role": "user", "content": instruction + "\n\n绩效数据：\n"
             + json.dumps(numbers, ensure_ascii=False)}]


def _parse_content(content: str) -> dict | None:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not data["summary"].strip():
        return None
    result = {"summary": data["summary"].strip()}
    for key in ("highlights", "risks", "suggestions"):
        value = data.get(key)
        if not isinstance(value, list):
            return None
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            return None
        result[key] = items[:6]
    return result


def render_markdown(title: str, content: dict) -> str:
    lines = [f"### {title}", "", content["summary"], "", "**亮点**"]
    lines += [f"- {item}" for item in content["highlights"]]
    lines += ["", "**风险**"] + [f"- {item}" for item in content["risks"]]
    lines += ["", "**建议**"] + [f"- {item}" for item in content["suggestions"]]
    return "\n".join(lines)


def _fallback(payload: dict, reason: str) -> dict:
    numbers = _numbers(payload)
    metrics = numbers["metrics"]
    parts = [f"{payload['scope_name']} {payload['period_label']}（截至 {payload['as_of']}）"
             f"时间进度 {_pct(payload['time_progress'])}"]
    summary_bits = []
    highlights, risks = [], []
    for metric in METRICS:
        row = metrics[metric]
        if row["target"] is None:
            continue
        summary_bits.append(f"{row['label']} 完成 {row['achieved']}/{row['target']}"
                            f"（{_pct(row['rate'])}，差 {row['delta_pp']}pp）")
        if row["rate"] is not None and row["rate"] >= 1:
            highlights.append(f"{row['label']} 已提前完成年度目标")
        elif row["delta_pp"] is not None and row["delta_pp"] >= 0:
            highlights.append(f"{row['label']} 完成率跑赢时间进度 {row['delta_pp']}pp")
        elif row["delta_pp"] is not None and row["delta_pp"] <= -20:
            risks.append(f"{row['label']} 落后时间进度 {-row['delta_pp']}pp，需重点冲刺")
    for person in numbers["top_people"][:2]:
        highlights.append(f"{person['name']} GMV 完成率 {_pct(person['gmv_rate'])} 领跑")
    for warning in (payload.get("warnings") or [])[:3]:
        risks.append(warning["text"])
    if not highlights:
        highlights = ["各项目标推进中，暂无明显亮点"]
    if not risks:
        risks = ["暂无显著风险，保持当前节奏"]
    suggestions = [f"关注落后指标：{bit}" for bit in summary_bits if "差 -" in bit][:2] or ["保持当前节奏，按日推进"]
    return {"summary": "；".join(parts + summary_bits[:4]),
            "highlights": highlights[:4], "risks": risks[:4],
            "suggestions": suggestions, "degraded": True, "degrade_reason": reason}


def generate_content(db: Session, payload: dict, ai_preset: str) -> tuple[str, dict]:
    """返回 (content_md, content_json)；任何 AI 失败都降级为模板文案。"""
    numbers = _numbers(payload)
    title = f"{payload['scope_name']}·{payload['period_label']}绩效报告"
    try:
        result = chat(db, ai_preset, _prompt(numbers), caller_module="perf_goal",
                      snapshot_mode="metadata")
        parsed = _parse_content(result.get("content", ""))
        if parsed is None:
            raise ValueError("AI 输出不是合法的报告 JSON")
        return render_markdown(title, parsed), parsed
    except Exception as exc:
        logger.warning("perf report AI degraded: %s", type(exc).__name__)
        print(f"[PERF-REPORT] AI degraded: {type(exc).__name__}", flush=True)
        content = _fallback(payload, type(exc).__name__)
        return render_markdown(title, content), content
