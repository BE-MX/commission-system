import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.aftersales.ai_service import AiAnalysisError, recover_stale_analyses, run_analysis
from app.aftersales.models import AfterSalesAiRun, AfterSalesCase, AfterSalesEvent, AfterSalesSopVersion
from app.auth.models import ArkUser


def test_stale_ai_analysis_is_recovered_for_manual_retry(db):
    user = _user(db)
    case = _case(db, user)
    case.current_status = "ai_analyzing"
    case.current_owner_user_id = user.id
    case.updated_at = datetime.utcnow() - timedelta(minutes=20)
    db.flush()

    recovered = recover_stale_analyses(db, stale_minutes=15)

    assert recovered == 1
    assert case.current_status == "ai_failed"
    assert case.current_owner_user_id == user.id
    assert db.query(AfterSalesEvent).filter_by(case_id=case.id, event_type="ai_stale_recovered").count() == 1


def _user(db):
    user = ArkUser(
        username="ai-sales",
        password_hash="test-hash",
        real_name="AI Sales",
        dingtalk_id="ding-ai-sales",
    )
    db.add(user)
    db.flush()
    return user


def _case(db, user):
    case = AfterSalesCase(
        case_no="AS-20260710-AI1",
        creator_user_id=user.id,
        creator_name_snapshot=user.real_name,
        customer_id="CUST001",
        customer_name_snapshot="Sensitive Customer Name",
        customer_grade="A",
        order_id="ORD001",
        order_no_snapshot="NO001",
        purchase_date=date(2026, 7, 1),
        feedback_date=date(2026, 7, 10),
        product_id=1,
        product_name_snapshot="Invisible Weft",
        is_custom_product=False,
        batch_no="BATCH-1",
        color_value="#2B",
        length_value="20 inch",
        weight_value=Decimal("100"),
        weight_unit="g",
        quantity=Decimal("2"),
        primary_issue_type="褪色",
        problem_description="客户使用三周后出现明显褪色，已经影响终端客户继续销售。",
        occurred_stage="使用几天",
        care_storage_note="客户使用无硫酸盐洗发水，低温护理，未游泳或暴晒。",
        affects_end_customer="yes",
        affected_goods_value=Decimal("1150"),
        affected_goods_currency="USD",
        evidence_score=80,
        evidence_is_sufficient=True,
        evidence_missing_items_json=["洗护产品成分或照片"],
    )
    db.add(case)
    db.flush()
    return case


def _sop(db, user, active=True):
    sop = AfterSalesSopVersion(
        version_no="2026.07.10",
        original_filename="sop.docx",
        storage_path="sop/test.docx",
        file_hash="a" * 64,
        change_summary="首版",
        effective_date=date(2026, 7, 10),
        parse_status="parsed",
        structured_content_json={
            "sections": [
                {
                    "title": "褪色 / 变色问题",
                    "level": 1,
                    "paragraphs": [
                        "高风险颜色：#2B、#5A、#9A、#18B。",
                        "处理原则：区分 fading 与 color changing。",
                    ],
                }
            ],
            "tables": [],
        },
        issue_mapping_json={"褪色": "褪色 / 变色问题"},
        clause_count=2,
        is_active=active,
        uploaded_by_user_id=user.id,
    )
    db.add(sop)
    db.flush()
    return sop


def _result(*, compensation=False, section="褪色 / 变色问题"):
    reply = "Thank you for letting us know. We will inspect the affected hair."
    action = {
        "code": "return_inspection",
        "title": "返厂检测",
        "has_compensation": False,
        "rationale": "需进一步核实原因",
    }
    if compensation:
        action = {
            "code": "replacement",
            "title": "免费换货",
            "has_compensation": True,
            "rationale": "支持重要客户",
        }
        reply += " This proposal is subject to final internal approval."
    return {
        "evidence": {
            "score": 80,
            "is_sufficient": True,
            "missing_items": ["洗护产品成分或照片"],
            "conflicts": [],
        },
        "responsibility": {
            "class": "D",
            "label": "责任暂不明确",
            "confidence": 0.72,
            "reasoning": ["高风险色号 #2B", "尚未排除洗护或高温影响"],
        },
        "sop_citations": [
            {"section": section, "clause": "处理原则", "quote_digest": "区分 fading 与 color changing"}
        ],
        "recommended_actions": [action],
        "customer_reply_draft": {"language": "en", "content": reply},
        "internal_follow_up": ["检查同批次是否有其他反馈"],
    }


def test_analysis_requires_active_sop(db):
    user = _user(db)
    case = _case(db, user)

    with pytest.raises(AiAnalysisError, match="生效"):
        run_analysis(db, case.id, user.id, chat_fn=lambda **_: {})


def test_analysis_sends_minimal_case_data_and_persists_result(db):
    user = _user(db)
    case = _case(db, user)
    sop = _sop(db, user)
    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {"content": json.dumps(_result(), ensure_ascii=False), "duration_ms": 123}

    result = run_analysis(db, case.id, user.id, chat_fn=fake_chat)

    prompt = captured["messages"][0]["content"]
    assert "Sensitive Customer Name" not in prompt
    assert "CUST001" not in prompt
    assert "#2B" in prompt
    assert "customer_reply_draft" in prompt
    assert '"language": "en"' in prompt
    assert "subject to final internal approval" in prompt
    assert captured["preset_name"] == "aftersales_solution_advice"
    assert result.sop_version_id == sop.id
    assert result.output_json["responsibility"]["class"] == "D"
    assert case.current_status == "awaiting_sales_decision"
    assert case.customer_reply_draft.startswith("Thank you")


def test_invalid_citation_is_repaired_once(db):
    user = _user(db)
    case = _case(db, user)
    _sop(db, user)
    responses = [_result(section="不存在条款"), _result()]

    def fake_chat(**_):
        return {"content": json.dumps(responses.pop(0), ensure_ascii=False), "duration_ms": 10}

    run = run_analysis(db, case.id, user.id, chat_fn=fake_chat)

    assert run.status == "success"
    assert responses == []


def test_missing_output_field_repair_message_contains_exact_path(db):
    user = _user(db)
    case = _case(db, user)
    _sop(db, user)
    invalid = _result()
    del invalid["customer_reply_draft"]
    captured_messages = []
    responses = [invalid, _result()]

    def fake_chat(**kwargs):
        captured_messages.append(kwargs["messages"])
        return {"content": json.dumps(responses.pop(0), ensure_ascii=False), "duration_ms": 10}

    run_analysis(db, case.id, user.id, chat_fn=fake_chat)

    assert "customer_reply_draft" in captured_messages[1][-1]["content"]


def test_duplicate_action_codes_are_repaired(db):
    user = _user(db)
    case = _case(db, user)
    _sop(db, user)
    invalid = _result()
    invalid["recommended_actions"].append(dict(invalid["recommended_actions"][0]))
    responses = [invalid, _result()]

    def fake_chat(**_):
        return {"content": json.dumps(responses.pop(0), ensure_ascii=False), "duration_ms": 10}

    run = run_analysis(db, case.id, user.id, chat_fn=fake_chat)

    assert run.status == "success"
    assert responses == []


def test_two_invalid_results_set_ai_failed_and_keep_run(db):
    user = _user(db)
    case = _case(db, user)
    _sop(db, user)

    def fake_chat(**_):
        return {"content": json.dumps(_result(section="不存在条款"), ensure_ascii=False), "duration_ms": 10}

    with pytest.raises(AiAnalysisError, match="校验失败"):
        run_analysis(db, case.id, user.id, chat_fn=fake_chat)

    db.refresh(case)
    run = db.query(AfterSalesAiRun).filter(AfterSalesAiRun.case_id == case.id).one()
    assert case.current_status == "ai_failed"
    assert run.status == "failed"
    assert run.error_summary


def test_compensation_reply_requires_approval_caveat(db):
    user = _user(db)
    case = _case(db, user)
    _sop(db, user)
    invalid = _result(compensation=True)
    invalid["customer_reply_draft"]["content"] = "We will replace the affected packs immediately."

    def fake_chat(**_):
        return {"content": json.dumps(invalid, ensure_ascii=False), "duration_ms": 10}

    with pytest.raises(AiAnalysisError, match="校验失败"):
        run_analysis(db, case.id, user.id, chat_fn=fake_chat)
