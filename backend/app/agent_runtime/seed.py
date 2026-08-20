"""Immutable first-party Agent Profile seeds."""

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from app.agent_runtime.models import AgentProfile


logger = logging.getLogger("commission")


_COPILOT_PROMPT = """你是莱莎方舟客户与订单经营副驾驶。你只能依据方舟授权工具返回的事实回答。
先确定问题需要哪些证据，再调用最少的工具。所有定量结论都必须关联 evidence 中的工具调用和字段。
事实、推断、建议必须分开；证据不足时明确说明，不得补造客户、订单、价格、物流或库存信息。
每条 evidence 必须原样回传成功工具调用的 tool_call_id，并以 source 填写对应工具名。
你只能生成建议和草案，不能代表公司对客户作出承诺，也不能直接修改业务数据。"""

_REPURCHASE_PROMPT = """你是莱莎方舟复购与流失干预分析 Agent。候选客户已由确定性规则召回；
你不能改变客户归属或凭空创造风险。基于订单节奏、客户事件、售后与知识证据解释为什么现在值得跟进，
给出一个具体、克制、可由业务员确认的下一步，并列出全部证据。不得自动发送消息或承诺价格、库存、交期。"""

_SHADOW_PROMPT = """你是莱莎方舟新客户开发影子 Agent。你只能针对冻结的目标画像寻找公开可验证企业，
逐一核验企业主体、官网域名、国家、行业相关性与来源。禁止猜测联系人或邮箱，禁止跨主体拼接，
禁止发送邮件或写入正式线索。输出只用于与现有 OpenClaw 流程做盲评。"""

_REPURCHASE_PROMPT += "\n每条 evidence 必须原样回传成功工具调用的 tool_call_id，并以 source 填写对应工具名。"
_SHADOW_PROMPT += "\n每个 candidate 必须包含 source_url、source 工具名和取得该证据的成功 tool_call_id。"


def _schema(required: list[str], properties: dict) -> dict:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _evidence_array() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["source", "tool_call_id"],
            "properties": {
                "source": {"type": "string"},
                "tool_call_id": {"type": "string"},
                "source_url": {"type": "string"},
            },
        },
    }


PROFILE_SEEDS = [
    {
        "profile_key": "customer_order_copilot",
        "version": 1,
        "name": "客户与订单经营副驾驶",
        "description": "基于授权客户、订单、知识、物流和价格事实生成可追溯经营建议",
        "runtime": "dsh",
        "mode": "interactive",
        "model_preset": "agent_runtime_copilot",
        "system_prompt": _COPILOT_PROMPT,
        "skill_manifest": [{"name": "ark-customer-order-copilot", "version": "1"}],
        "tool_allowlist": [
            "get_customer_profile", "get_customer_order_timeline", "get_customer_repurchase_analysis",
            "get_order_intelligence_snapshot", "get_customer_actions", "search_knowledge",
            "track_shipment", "get_standard_price",
        ],
        "limits_json": {"max_steps": 12, "timeout_seconds": 300, "max_output_tokens": 4000, "max_total_tokens": 12000},
        "policy_json": {"read_only": True, "human_confirm_business_write": True, "evidence_required": True},
        "output_schema": _schema(
            ["summary", "key_findings", "risks", "recommended_actions", "evidence", "open_questions"],
            {
                "summary": {"type": "string"}, "key_findings": {"type": "array"},
                "risks": {"type": "array"}, "recommended_actions": {"type": "array"},
                "evidence": _evidence_array(), "open_questions": {"type": "array"},
            },
        ),
    },
    {
        "profile_key": "repurchase_risk_analyst",
        "version": 1,
        "name": "复购与流失干预分析",
        "description": "为规则召回客户生成有证据的行动卡草案",
        "runtime": "dsh",
        "mode": "scheduled",
        "model_preset": "agent_runtime_repurchase",
        "system_prompt": _REPURCHASE_PROMPT,
        "skill_manifest": [{"name": "ark-repurchase-risk-analyst", "version": "1"}],
        "tool_allowlist": [
            "get_customer_profile", "get_customer_order_timeline", "get_customer_repurchase_analysis",
            "get_customer_actions", "search_knowledge",
        ],
        "limits_json": {"max_steps": 8, "timeout_seconds": 240, "max_output_tokens": 2500, "max_total_tokens": 8000},
        "policy_json": {"read_only": True, "projection": "customer_action", "evidence_required": True},
        "output_schema": _schema(
            ["action_reason", "suggested_next_action", "suggested_message", "evidence"],
            {
                "action_reason": {"type": "string"}, "suggested_next_action": {"type": "string"},
                "suggested_message": {"type": "string"}, "evidence": _evidence_array(),
            },
        ),
    },
    {
        "profile_key": "sales_discovery_shadow",
        "version": 1,
        "name": "新客户开发 DSH 影子任务",
        "description": "同输入评测 DSH 与 OpenClaw，不写入正式线索",
        "runtime": "dsh",
        "mode": "shadow",
        "model_preset": "agent_runtime_sales_shadow",
        "system_prompt": _SHADOW_PROMPT,
        "skill_manifest": [{"name": "ark-lead-discovery-shadow", "version": "1"}],
        "tool_allowlist": ["get_search_job_context", "search_web", "fetch_public_page"],
        "limits_json": {"max_steps": 20, "timeout_seconds": 600, "max_output_tokens": 6000, "max_total_tokens": 30000},
        "policy_json": {"read_only": True, "shadow_only": True, "evidence_required": True},
        "output_schema": _schema(["candidates"], {"candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "website", "source_url", "captured_at", "source", "tool_call_id"],
                "properties": {
                    "name": {"type": "string"}, "website": {"type": "string"},
                    "source_url": {"type": "string"}, "captured_at": {"type": "string"},
                    "source": {"type": "string"}, "tool_call_id": {"type": "string"},
                },
            },
        }}),
    },
]


def seed_default_profiles(db: Session) -> int:
    created = 0
    for data in PROFILE_SEEDS:
        existing = db.query(AgentProfile).filter(
            AgentProfile.profile_key == data["profile_key"],
            AgentProfile.version == data["version"],
        ).one_or_none()
        prompt_hash = hashlib.sha256(data["system_prompt"].encode("utf-8")).hexdigest()
        if existing is not None:
            expected = {**data, "prompt_hash": prompt_hash}
            actual = {key: getattr(existing, key) for key in expected}
            if json.dumps(actual, ensure_ascii=False, sort_keys=True) != json.dumps(expected, ensure_ascii=False, sort_keys=True):
                logger.warning("Agent profile seed drift: %s v%s", data["profile_key"], data["version"])
            continue
        db.add(AgentProfile(**data, prompt_hash=prompt_hash, status="active"))
        created += 1
    db.commit()
    return created
