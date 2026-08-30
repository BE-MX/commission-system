"""Immutable first-party Agent Profile seeds."""

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from app.agent_runtime.models import AgentProfile


logger = logging.getLogger("commission")


_COPILOT_PROMPT = """你是莱莎方舟客户与订单经营副驾驶。你只能依据方舟授权工具返回的事实回答。
先确定问题需要哪些证据，再调用最少的工具。summary 只能做不含数字的定性概括；所有事实、风险和建议
都必须按 text + evidence_call_ids 输出，并关联 evidence 中本次成功工具调用的 call_id。
事实、推断、建议必须分开；证据不足时明确说明，不得补造客户、订单或库存信息。
每条 evidence 必须原样回传成功工具调用的 tool_call_id，并以 source 填写对应工具名。
你只能生成建议和草案，不能代表公司对客户作出承诺，也不能直接修改业务数据。"""

_REPURCHASE_PROMPT = """你是莱莎方舟复购与流失干预分析 Agent。候选客户已由确定性规则召回；
你不能改变客户归属或凭空创造风险。基于方舟客户档案与订单事实解释为什么现在值得跟进，
给出一个具体、克制、可由业务员确认的下一步，并列出全部证据。不得自动发送消息或承诺价格、库存、交期。"""

_SHADOW_PROMPT = """你是莱莎方舟新客户开发影子 Agent。你只能针对冻结的目标画像寻找公开可验证企业，
逐一核验企业主体、官网域名、国家、行业相关性与来源。禁止猜测联系人或邮箱，禁止跨主体拼接，
禁止发送邮件或写入正式线索。输出只用于与现有 OpenClaw 流程做盲评。"""

_CUSTOMER_EVIDENCE_PROMPT = (
    "\n成功工具事件只接受 payload.output 为已解析 JSON object 的规范形态，证据位于其中的 "
    "evidence_refs；不得提交 JSON 字符串或顶层 evidence_refs。每条 evidence 必须设置唯一 "
    "claim_id，原样复制工具 evidence_refs 中的 evidence_ref、"
    "evidence_content_hash、customer_id、profile_version、freshness，并回传成功调用的 "
    "tool_call_id，以 source 填写对应工具名；不得自行改写这些字段。"
)
_COPILOT_PROMPT += _CUSTOMER_EVIDENCE_PROMPT
_REPURCHASE_PROMPT += _CUSTOMER_EVIDENCE_PROMPT
_SHADOW_PROMPT += "\n每个 candidate 必须包含 source_url、source 工具名和取得该证据的成功 tool_call_id。"


def _schema(required: list[str], properties: dict) -> dict:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _evidence_array(*, customer_envelope: bool = False) -> dict:
    required = ["source", "tool_call_id"]
    properties = {
        "source": {"type": "string"},
        "tool_call_id": {"type": "string"},
        "source_url": {"type": "string"},
    }
    if customer_envelope:
        required = [
            "claim_id", "tool_call_id", "source", "evidence_ref",
            "evidence_content_hash", "customer_id", "profile_version", "freshness",
        ]
        properties.update({
            "claim_id": {"type": "string", "minLength": 1},
            "evidence_ref": {"type": "string", "minLength": 1},
            "evidence_content_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "customer_id": {"type": "integer", "minimum": 1},
            "profile_version": {"type": "integer", "minimum": 1},
            "freshness": {"const": "current"},
        })
    return {
        "type": "array",
        "items": {
            "type": "object",
            "required": required,
            "properties": properties,
            "additionalProperties": False,
        },
    }


def _cited_statement_array() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["text", "evidence_call_ids"],
            "properties": {
                "text": {"type": "string", "minLength": 1},
                "evidence_call_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "uniqueItems": True,
                },
            },
            "additionalProperties": False,
        },
    }


PROFILE_SEEDS = [
    {
        "profile_key": "customer_order_copilot",
        "version": 5,
        "name": "客户与订单经营副驾驶",
        "description": "基于授权客户与订单事实生成可追溯经营建议",
        "runtime": "dsh",
        "mode": "interactive",
        "model_preset": "agent_runtime_copilot",
        "system_prompt": _COPILOT_PROMPT,
        "skill_manifest": [{"name": "ark-customer-order-copilot", "version": "5"}],
        "tool_allowlist": [
            "get_customer_profile", "get_customer_facts", "get_customer_orders",
            "search_customer_messages", "get_customer_actions", "get_customer_evidence",
            "get_customer_source_chunks",
        ],
        "limits_json": {"max_steps": 12, "timeout_seconds": 300, "max_output_tokens": 4000, "max_total_tokens": 12000},
        "policy_json": {
            "read_only": True, "human_confirm_business_write": True, "evidence_required": True,
            "claim_evidence_required": True,
            "max_data_classification": "restricted_internal",
            "artifact_type": "copilot_answer", "max_artifacts": 1,
        },
        "output_schema": _schema(
            ["summary", "key_findings", "risks", "recommended_actions", "evidence", "open_questions"],
            {
                "summary": {"type": "string"}, "key_findings": _cited_statement_array(),
                "risks": _cited_statement_array(), "recommended_actions": _cited_statement_array(),
                "evidence": _evidence_array(customer_envelope=True), "open_questions": {"type": "array"},
            },
        ),
    },
    {
        "profile_key": "repurchase_risk_analyst",
        "version": 5,
        "name": "复购与流失干预分析",
        "description": "为规则召回客户生成有证据的行动卡草案",
        "runtime": "dsh",
        "mode": "scheduled",
        "model_preset": "agent_runtime_repurchase",
        "system_prompt": _REPURCHASE_PROMPT,
        "skill_manifest": [{"name": "ark-repurchase-risk-analyst", "version": "5"}],
        "tool_allowlist": [
            "get_customer_profile", "get_customer_facts", "get_customer_orders",
            "get_customer_actions", "get_customer_evidence",
        ],
        "limits_json": {"max_steps": 8, "timeout_seconds": 240, "max_output_tokens": 2500, "max_total_tokens": 8000},
        "policy_json": {
            "read_only": True, "projection": "customer_action", "evidence_required": True,
            "artifact_type": "repurchase_action_card", "max_artifacts": 1,
            "claim_evidence_required": True,
        },
        "output_schema": _schema(
            ["action_reason", "suggested_next_action", "suggested_message", "evidence"],
            {
                "action_reason": {"type": "string"}, "suggested_next_action": {"type": "string"},
                "suggested_message": {"type": "string"},
                "evidence": _evidence_array(customer_envelope=True),
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
        "tool_allowlist": ["search_web", "fetch_public_page"],
        "limits_json": {"max_steps": 20, "timeout_seconds": 600, "max_output_tokens": 6000, "max_total_tokens": 30000},
        "policy_json": {
            "read_only": True, "shadow_only": True, "evidence_required": True,
            "artifact_type": "sales_discovery_shadow_result", "max_artifacts": 1,
        },
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
        else:
            db.add(AgentProfile(**data, prompt_hash=prompt_hash, status="active"))
            created += 1
        db.query(AgentProfile).filter(
            AgentProfile.profile_key == data["profile_key"],
            AgentProfile.version < data["version"],
            AgentProfile.status == "active",
        ).update({AgentProfile.status: "inactive"}, synchronize_session=False)
    db.commit()
    return created
