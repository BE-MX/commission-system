"""方舟洞见 — AI 调用辅助 (chat / OCR / chat-analysis skill)"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session


logger = logging.getLogger("insight")

# ── 上传目录 ──────────────────────────────────────────
INSIGHT_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "insight"
INSIGHT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Jinja2 模板环境 ─────────────────────────────────────
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)



def _try_invoke_ai(db: Session, preset_name: str, user_text: str, user_id: Optional[int] = None) -> Optional[str]:
    """统一 AI 调用入口 — preset 缺失时返回 None,由调用方降级。"""
    try:
        from app.ai import service as ai_service
        from app.ai.models import AiPreset

        preset = (
            db.query(AiPreset)
            .filter(AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None))
            .first()
        )
        if not preset or not preset.is_enabled:
            logger.warning(f"AI preset '{preset_name}' missing or disabled, falling back to mock")
            return None

        result = ai_service.chat(
            db=db,
            preset_name=preset_name,
            messages=[{"role": "user", "content": user_text}],
            caller_module="insight",
            caller_user_id=user_id,
        )
        return result.get("content") or ""
    except Exception as e:
        logger.exception(f"AI invoke failed (preset={preset_name})")
        return None


def _safe_json_parse(text: str) -> Optional[Any]:
    """从 AI 返回文本中提取 JSON(支持 ```json fenced 块)。"""
    if not text:
        return None
    candidates = [text]
    # 提取 fenced code block
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        candidates.insert(0, m.group(1))
    # 提取首个 { 到末尾 } 的子串
    if "{" in text and "}" in text:
        start = text.index("{")
        end = text.rindex("}")
        if end > start:
            candidates.insert(0, text[start : end + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def _invoke_ocr(db: Session, image_path: str, user_id: Optional[int]) -> str:
    """图片 OCR — 通过 ark_ai_presets 中的 ocr_extract preset。"""
    # 注意:当前 ai.service.chat 仅支持纯文本 messages。多模态 OCR 需要扩展为 image_url 消息体。
    # 当 preset 不存在或调用失败时,返回友好提示文本,案例字段由用户手动补充。
    text = _try_invoke_ai(
        db,
        "ocr_extract",
        f"请从以下图片(image path: {image_path})中提取所有文字,保持原有格式输出。",
        user_id,
    )
    if text:
        return text.strip()
    return "[OCR 暂未配置:请在 AI 接入管理中创建多模态 preset 'ocr_extract',或改用文本粘贴方式上传案例]"


def _load_chat_skill() -> str:
    """读取 chat-analysis SKILL 文件内容。"""
    skill_path = Path(__file__).parent / "skills" / "chat-analysis.md"
    if skill_path.exists():
        return skill_path.read_text(encoding="utf-8")
    return ""


def _invoke_case_format(db: Session, raw_text: str, user_id: Optional[int]) -> dict:
    """案例库整理 — 使用精简版 SKILL 核心指令进行 AI 整理，避免完整文件导致超时。"""
    system_text = (
        _CASE_SKILL_CORE
        + "\n\n## 输出 JSON 格式\n"
        + '{\n'
        '  "title": "案例标题(25字以内)",\n'
        '  "customer_name": "客户名称",\n'
        '  "customer_country": "客户国家",\n'
        '  "customer_type": "客户类型(沙龙/品牌/电商/批发/影视)",\n'
        '  "communication_channel": "沟通渠道(WhatsApp/阿里TM/Email/Instagram)",\n'
        '  "communication_period": "沟通时段",\n'
        '  "total_rounds": 总回合数(整数),\n'
        '  "final_result": "最终结果(成交/未成交/谈判中/流失)",\n'
        '  "background_check_status": "背调状态(有wiki记录/无历史背调)",\n'
        '  "scenario": "场景背景(2-3句话概述)",\n'
        '  "rounds_analysis": [\n'
        '    {"round_no": "R1", "time": "时间/间隔", "customer_action": "客户动作", "salesperson_action": "业务员动作标签", "summary": "回合摘要", "score": 1-5, "comment": "一句话评价"}\n'
        '  ],\n'
        '  "dimension_scores": {\n'
        '    "response_speed": {"score": 1-5, "comment": "简评"},\n'
        '    "talk_track_quality": {"score": 1-5, "comment": "简评"},\n'
        '    "needs_alignment": {"score": 1-5, "comment": "简评"},\n'
        '    "deal_momentum": {"score": 1-5, "comment": "简评"},\n'
        '    "emotional_engagement": {"score": 1-5, "comment": "简评"},\n'
        '    "compliance_risk": {"score": 1-5, "comment": "简评"},\n'
        '    "overall": 加权均分\n'
        '  },\n'
        '  "golden_phrases": [\n'
        '    {"scene": "适用场景", "phrase": "原话", "why": "为什么好(一句话)"}\n'
        '  ],\n'
        '  "red_flags": [\n'
        '    {"issue_type": "问题类型", "phrase": "原话", "problem": "问题在哪(一句话)", "suggestion": "修正建议"}\n'
        '  ],\n'
        '  "core_strengths": ["核心亮点1", "核心亮点2", "核心亮点3"],\n'
        '  "result_analysis": [\n'
        '    {"factor": "驱动因素/流失根因", "evidence": "一句话证据"}\n'
        '  ],\n'
        '  "improvements": [\n'
        '    {"priority": "🔴/🟡/🟢", "problem": "问题描述", "impact": "影响评估", "fix": "修正方案", "benefit": "预期收益"}\n'
        '  ],\n'
        '  "next_actions": [\n'
        '    {"priority": "🔴/🟡/🟢", "action": "具体动作", "owner": "负责人", "deadline": "截止日期或null"}\n'
        '  ],\n'
        '  "tags": ["标签1", "标签2"],\n'
        '  "raw_summary": "100字摘要"\n'
        '}\n'
    )

    user_text = f"请对以下聊天记录进行复盘分析:\n\n{raw_text}"

    try:
        from app.ai import service as ai_service
        from app.ai.models import AiPreset

        preset = (
            db.query(AiPreset)
            .filter(AiPreset.preset_name == "case_library_format", AiPreset.deleted_at.is_(None))
            .first()
        )
        if not preset or not preset.is_enabled:
            logger.warning("AI preset 'case_library_format' missing or disabled, falling back")
            raise ValueError("preset missing")

        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
        result = ai_service.chat(
            db=db,
            preset_name="case_library_format",
            messages=messages,
            caller_module="insight",
            caller_user_id=user_id,
        )
        text = result.get("content") or ""
    except Exception:
        # 降级:用 _try_invoke_ai 走传统方式(无 SKILL)
        text = _try_invoke_ai(db, "case_library_format", user_text, user_id)

    parsed = _safe_json_parse(text or "")
    if not parsed:
        # 最终降级
        first_line = (raw_text or "").strip().split("\n", 1)[0][:25]
        return {
            "title": first_line or "(待补充)",
            "scenario": (raw_text or "")[:200],
            "what_was_done": "",
            "result": "",
            "customer_name": "",
            "tags": [],
            "core_strengths": [],
            "raw_summary": (raw_text or "")[:100],
        }
    return parsed if isinstance(parsed, dict) else {}


def _invoke_meeting_summary(db: Session, original_text: str, user_id: Optional[int]) -> str:
    """精要 Markdown — meeting_summary preset。"""
    prompt = (
        "请将以下钉钉 AI 转录文本整理为精要版会议记录,要求:\n"
        "1. 保留关键决策、关键数据、分歧点;\n"
        "2. 压缩到原文长度的约 20%;\n"
        "3. 格式: ## 核心决策 / ## 主要讨论点 / ## 待跟进事项;\n"
        "4. 不要使用'综上所述'。\n"
        "输出 Markdown 纯文本。\n\n"
        f"原文:\n{original_text}"
    )
    text = _try_invoke_ai(db, "meeting_summary", prompt, user_id)
    if text:
        return text.strip()
    # 降级:截取原文前 500 字 + 提示
    head = (original_text or "")[:500]
    return f"## 主要讨论点\n\n{head}\n\n_AI preset 'meeting_summary' 未配置,以上为原文截断。请在 AI 管理中配置后重新上传。_"


def _invoke_meeting_tasks(db: Session, original_text: str, user_id: Optional[int]) -> list:
    """任务清单 JSON 数组 — meeting_tasks preset。"""
    prompt = (
        "从以下会议转录中提取所有明确的任务指派,输出 JSON 数组,每条任务包含:\n"
        "{\n"
        '  "assignee": "责任人姓名",\n'
        '  "description": "任务描述(50 字以内, 动词开头)",\n'
        '  "deadline": "YYYY-MM-DD 或 null",\n'
        '  "priority": "high/medium/low",\n'
        '  "source_quote": "原文中的相关原句(100 字以内)"\n'
        "}\n"
        "只输出 JSON 数组,不要其他文字。\n\n"
        f"原文:\n{original_text}"
    )
    text = _try_invoke_ai(db, "meeting_tasks", prompt, user_id)
    parsed = _safe_json_parse(text or "")
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "tasks" in parsed and isinstance(parsed["tasks"], list):
        return parsed["tasks"]
    # 降级:从原文用正则匹配中文人名+动词
    return _fallback_extract_tasks(original_text)


def _fallback_extract_tasks(text: str) -> list:
    """从原文简单提取「XXX:动作」式任务,作为 AI preset 缺失时的兜底。"""
    if not text:
        return []
    tasks = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^([一-龥]{2,4})[::](.+)$", line)
        if m and len(m.group(2).strip()) > 4:
            tasks.append({
                "assignee": m.group(1),
                "description": m.group(2).strip()[:200],
                "priority": "medium",
                "source_quote": line[:300],
            })
        if len(tasks) >= 10:
            break
    return tasks
