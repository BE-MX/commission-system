"""素材管理 — AI 打标签服务

根据目录路径 + 文件名，调用 AI 分析建议标签值。

v2（2026-07-22 标签体系重构）：维度与值域运行时从标签库注入 user message，
不再硬编码（system prompt 在 asset_analyze preset，见 bootstrap/seed_ai.py）。
只注入可见且非托管的维度——托管维度（色系）由派生脚本写入，AI 不建议。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.call_service import chat
from app.asset.tag_service import list_dimensions_cached


def _clean_ai_response(content: str) -> str:
    """去除可能的 Markdown 代码块标记。"""
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _norm(s: str) -> str:
    return s.lower().replace(" ", "").strip()


def _suggestable_dimensions(db: Session) -> list[dict]:
    """AI 可建议的维度：可见 + 非托管。"""
    return [d for d in list_dimensions_cached(db)
            if d.get("is_visible", 1) and not d.get("is_managed", 0)]


def _build_taxonomy_block(dims: list[dict]) -> str:
    """给 AI 的值域描述（紧凑 JSON）：维度name/中文名/单多选/值列表（含英文别名）。"""
    payload = []
    for d in dims:
        values = []
        for v in d["values"]:
            if not v.get("is_active", 1):
                continue
            entry = v["value"]
            extras = [x for x in ([v.get("name_en")] + list(v.get("aliases") or [])) if x]
            if extras:
                entry = f"{v['value']}（{'/'.join(extras)}）"
            values.append(entry)
        if values:
            payload.append({
                "name": d["name"],
                "label": d["label"],
                "select": "单选" if d["is_single_select"] else "多选",
                "values": values,
            })
    return json.dumps(payload, ensure_ascii=False)


def _match_value_ids(dim: dict, raw_values: list[str]) -> list[dict]:
    """AI 返回值 → 标签值记录。精确匹配优先，再按 value/name_en/aliases 规范化匹配。"""
    index: dict[str, dict] = {}
    for v in dim["values"]:
        if not v.get("is_active", 1):
            continue
        for cand in [v["value"], v.get("name_en")] + list(v.get("aliases") or []):
            if cand:
                index.setdefault(_norm(cand), v)

    matched, seen = [], set()
    for raw in raw_values:
        if not isinstance(raw, str):
            continue
        v = index.get(_norm(raw))
        if v and v["id"] not in seen:
            seen.add(v["id"])
            matched.append(v)
    return matched


def analyze_asset_tags(
    db: Session,
    file_name: str,
    directory_path: Optional[str] = None,
) -> dict:
    """调用 AI 分析素材标签。返回建议标签列表。

    Returns:
        {
            "confidence": float,
            "suggestions": [
                {"dimension_id": int, "dimension_name": str, "dimension_label": str,
                 "values": [{"tag_value_id": int, "value": str}], "is_ai_suggested": true}
            ]
        }
    """
    dims = _suggestable_dimensions(db)
    taxonomy_block = _build_taxonomy_block(dims)

    prompt = f"""请分析以下素材的标签：

directory_path: {directory_path or "未知"}
file_name: {file_name}
taxonomy: {taxonomy_block}

按系统提示的 JSON 格式返回。"""

    result = chat(
        db,
        preset_name="asset_analyze",
        messages=[{"role": "user", "content": prompt}],
        caller_module="asset_analyze",
    )

    content = _clean_ai_response(result["content"])

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = {}

    confidence = parsed.get("confidence", 0.0)
    raw_tags = parsed.get("tags") or {}
    if not isinstance(raw_tags, dict):
        raw_tags = {}

    dim_by_name = {d["name"]: d for d in dims}
    suggestions = []
    for dim_name, raw_values in raw_tags.items():
        dim = dim_by_name.get(dim_name)
        if dim is None:
            continue
        if isinstance(raw_values, str):
            raw_values = [raw_values]
        if not isinstance(raw_values, list) or not raw_values:
            continue
        if dim["is_single_select"]:
            raw_values = raw_values[:1]

        matched = _match_value_ids(dim, raw_values)
        if not matched:
            continue
        suggestions.append({
            "dimension_id": dim["id"],
            "dimension_name": dim["name"],
            "dimension_label": dim["label"],
            "values": [{"tag_value_id": v["id"], "value": v["value"]} for v in matched],
            "is_ai_suggested": True,
        })

    return {
        "confidence": confidence,
        "suggestions": suggestions,
        "raw_response": content,
    }
