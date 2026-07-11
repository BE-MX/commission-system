"""基于生效 SOP 生成结构化售后建议。"""

import json
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.aftersales.models import AfterSalesAiRun, AfterSalesCase, AfterSalesEvent, AfterSalesSopVersion
from app.aftersales.schemas import AfterSalesAiResult
from app.ai.service import chat


PRESET_NAME = "aftersales_solution_advice"
COMPENSATION_CODES = {
    "free_rework",
    "replacement",
    "resend",
    "cash_refund",
    "discount",
    "order_credit",
    "freight_subsidy",
}


class AiAnalysisError(ValueError):
    pass


def recover_stale_analyses(db: Session, *, stale_minutes: int = 15) -> int:
    """将因进程退出而遗留的分析中单据恢复为可重试状态。"""
    cutoff = datetime.utcnow() - timedelta(minutes=stale_minutes)
    cases = (
        db.query(AfterSalesCase)
        .filter(
            AfterSalesCase.current_status == "ai_analyzing",
            AfterSalesCase.updated_at < cutoff,
            AfterSalesCase.deleted_at.is_(None),
        )
        .with_for_update()
        .all()
    )
    for case in cases:
        case.current_status = "ai_failed"
        case.current_owner_user_id = case.creator_user_id
        case.version += 1
        db.add(AfterSalesEvent(
            case_id=case.id,
            event_type="ai_stale_recovered",
            actor_name_snapshot="系统",
            workflow_round=case.workflow_round,
            detail_json={"stale_minutes": stale_minutes},
        ))
    db.flush()
    return len(cases)


def _relevant_sop(sop: AfterSalesSopVersion, issue_type: str) -> dict:
    content = sop.structured_content_json or {}
    mapped_title = (sop.issue_mapping_json or {}).get(issue_type)
    mapped_titles = set(mapped_title if isinstance(mapped_title, list) else [mapped_title])
    sections = content.get("sections") or []
    relevant = [section for section in sections if section.get("title") in mapped_titles]
    if not relevant:
        relevant = sections
    return {"sections": relevant, "tables": content.get("tables") or []}


def _prompt_payload(case: AfterSalesCase, sop: AfterSalesSopVersion) -> dict:
    return {
        "case": {
            "customer_grade": case.customer_grade,
            "product": case.product_name_snapshot,
            "batch_no": case.batch_no,
            "color": case.color_value,
            "length": case.length_value,
            "weight": f"{case.weight_value}{case.weight_unit}",
            "quantity": str(case.quantity),
            "issue_type": case.primary_issue_type,
            "problem_description": case.problem_description,
            "occurred_stage": case.occurred_stage,
            "care_storage_note": case.care_storage_note,
            "affects_end_customer": case.affects_end_customer,
            "affected_goods_value": str(case.affected_goods_value),
            "affected_goods_currency": case.affected_goods_currency,
            "evidence": {
                "score": case.evidence_score,
                "is_sufficient": case.evidence_is_sufficient,
                "missing_items": case.evidence_missing_items_json or [],
            },
        },
        "sop": {
            "version": sop.version_no,
            "relevant_content": _relevant_sop(sop, case.primary_issue_type),
        },
        "output_requirement": {
            "format": "JSON only",
            "schema": AfterSalesAiResult.model_json_schema(),
            "customer_reply_draft": {
                "language": "en",
                "content": (
                    "Write a professional, empathetic customer-ready English reply. "
                    "Explain the issue assessment and proposed next steps in plain language. "
                    "Do not expose internal responsibility labels, confidence scores, or SOP citations."
                ),
            },
            "warning": (
                "AI is advisory. Any compensation proposal must include the exact phrase "
                "'subject to final internal approval'."
            ),
        },
    }


def _extract_json(content: str) -> dict:
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AiAnalysisError("AI 返回内容不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise AiAnalysisError("AI 返回 JSON 必须是对象")
    return value


def _validate_result(raw: dict, sop: AfterSalesSopVersion) -> AfterSalesAiResult:
    try:
        result = AfterSalesAiResult.model_validate(raw)
    except ValidationError as exc:
        first_error = exc.errors()[0]
        location = ".".join(str(part) for part in first_error.get("loc", [])) or "root"
        raise AiAnalysisError(
            f"AI 结果字段校验失败: {location}: {first_error['msg']}"
        ) from exc

    section_titles = {
        section.get("title")
        for section in (sop.structured_content_json or {}).get("sections", [])
    }
    invalid_sections = [
        citation.section for citation in result.sop_citations if citation.section not in section_titles
    ]
    if invalid_sections:
        raise AiAnalysisError(f"AI 引用了不存在的 SOP 条款: {invalid_sections[0]}")

    for action in result.recommended_actions:
        expected_compensation = action.code in COMPENSATION_CODES
        if action.code not in {"return_inspection", "custom"} and (
            action.has_compensation != expected_compensation
        ):
            raise AiAnalysisError(f"措施 {action.code} 的赔偿标记不正确")

    action_codes = [action.code for action in result.recommended_actions]
    if len(action_codes) != len(set(action_codes)):
        raise AiAnalysisError("AI 推荐措施 code 不得重复")

    has_compensation = any(action.has_compensation for action in result.recommended_actions)
    reply = result.customer_reply_draft.content.lower()
    if has_compensation and "subject to final internal approval" not in reply:
        raise AiAnalysisError("赔偿英文话术缺少待最终审批提示")
    return result


def run_analysis(
    db: Session,
    case_id: int,
    user_id: int,
    *,
    chat_fn=chat,
) -> AfterSalesAiRun:
    case = db.query(AfterSalesCase).filter(AfterSalesCase.id == case_id).first()
    if case is None:
        raise AiAnalysisError("售后单不存在")
    sop = (
        db.query(AfterSalesSopVersion)
        .filter(AfterSalesSopVersion.is_active.is_(True))
        .first()
    )
    if sop is None:
        raise AiAnalysisError("当前没有生效的售后 SOP")

    run_no = (
        db.query(func.coalesce(func.max(AfterSalesAiRun.run_no), 0))
        .filter(AfterSalesAiRun.case_id == case.id)
        .scalar()
        + 1
    )
    prompt_payload = _prompt_payload(case, sop)
    run = AfterSalesAiRun(
        case_id=case.id,
        sop_version_id=sop.id,
        run_no=run_no,
        status="running",
        preset_code=PRESET_NAME,
        input_summary_json=prompt_payload,
        created_by_user_id=user_id,
    )
    case.current_status = "ai_analyzing"
    case.sop_version_id = sop.id
    db.add(run)
    db.flush()

    validation_error = None
    duration_ms = 0
    for attempt in range(2):
        messages = [
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False),
            }
        ]
        if attempt and validation_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "上一份 JSON 校验失败。请仅返回修正后的完整 JSON。错误："
                        f"{validation_error}"
                    ),
                }
            )
        try:
            response = chat_fn(
                db=db,
                preset_name=PRESET_NAME,
                messages=messages,
                caller_module="aftersales",
                caller_user_id=user_id,
            )
            duration_ms += int(response.get("duration_ms") or 0)
            result = _validate_result(_extract_json(response.get("content", "")), sop)
        except (AiAnalysisError, ValidationError, ValueError) as exc:
            validation_error = str(exc)
            continue

        output = result.model_dump(by_alias=True, mode="json")
        run.status = "success"
        run.output_json = output
        run.duration_ms = duration_ms
        run.completed_at = datetime.utcnow()
        case.current_status = "awaiting_sales_decision"
        case.responsibility_class = output["responsibility"]["class"]
        case.responsibility_reason = "；".join(output["responsibility"]["reasoning"])
        case.customer_reply_draft = output["customer_reply_draft"]["content"]
        case.version += 1
        db.flush()
        return run

    run.status = "failed"
    run.duration_ms = duration_ms
    run.error_summary = (validation_error or "AI 结果未知错误")[:500]
    run.completed_at = datetime.utcnow()
    case.current_status = "ai_failed"
    case.version += 1
    db.flush()
    raise AiAnalysisError(f"AI 结果校验失败，已转为人工处理：{run.error_summary}")
