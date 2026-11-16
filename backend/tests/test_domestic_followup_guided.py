import json
from contextlib import nullcontext
from datetime import date

from app.domestic_followup import ai_parse_service, followup_service
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem
from app.domestic_followup.schemas import DirectSaveIn
from app.domestic_followup.template_models import DomesticFollowupTemplate
from tests.domestic_followup_helpers import make_customer, make_user, seed_dicts

TODAY = date(2026, 11, 16)


def _ctx(user):
    return {"sub": str(user.id), "roles": [], "permissions": ["domestic_followup:read", "domestic_followup:write"]}


def _template(db):
    row = DomesticFollowupTemplate(
        code="T03", version=2, name="价格异议", status="active", prep_fields=[], guidance="",
        record_fields=[
            {"key": "amount_meaning", "label": "金额及含义", "kind": "amount", "options": {"inline": ["未确认"]}},
            {"key": "concern", "label": "已确认顾虑", "kind": "select", "options": {"inline": ["价格", "效果"]}},
        ], params={}, avoid=[], short_form="",
    )
    db.add(row)
    db.flush()
    return row


def _draft(db, user, template, **values):
    row = DomesticFollowup(author_user_id=user.id, followup_date=TODAY, request_id=f"guided-{user.id}",
                           status="draft", ai_status="running", raw_text="店里发片多，多推发片；2000—3000，重点跟进",
                           template_code=template.code, template_version=template.version, version=1, **values)
    db.add(row)
    db.commit()
    return row


def test_guided_facts_fields_and_manual_evidence_priority(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "guided_ai")
    template = _template(db)
    followup = _draft(db, user, template, evidence_kind="customer",
                      template_answers={"fields": {"concern": "价格"}, "questions": [{"q": "比较对象", "answer": "同规格", "state": "asked"}]})
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "summary": "发片与金额含义待确认",
        "facts": [
            {"text": "多推发片", "nature": "customer_said", "speaker": "unknown", "source": {"kind": "raw_text", "excerpt": "多推发片"}},
            {"text": "2000—3000 的含义未知", "nature": "to_confirm", "source": {"kind": "raw_text", "excerpt": "2000—3000"}},
            {"text": "重点跟进", "nature": "assessment", "source": {"kind": "raw_text", "excerpt": "重点跟进"}},
        ],
        "field_values": {
            "amount_meaning": {"value": {"raw": "2000—3000", "meaning": "未确认"}, "source": {"kind": "raw_text", "excerpt": "2000—3000"}},
            "concern": {"value": "效果"}, "unknown": {"value": "不能写入"},
        },
        "question_answers": [
            {"q": "比较对象", "answer": "AI 不能覆盖手填", "state": "asked"},
            {"q": "比较价格", "answer": "2000—3000", "state": "asked"},
        ],
        "questions_to_salesperson": [{"q": f"问题{i}"} for i in range(5)],
    }, ensure_ascii=False)})
    ai_parse_service.run_parse(followup.id, _ctx(user), session_factory=lambda: nullcontext(db))
    result = followup.ai_result
    assert result["evidence_kind"] == "customer"
    assert [item["nature"] for item in result["items"]] == ["to_confirm", "to_confirm", "assessment"]
    assert result["items"][0]["speaker"] == "unknown"
    assert result["field_values"]["amount_meaning"]["value"]["raw"] == "2000—3000"
    assert "concern" not in result["field_values"] and "unknown" not in result["field_values"]
    assert result["question_answers"] == [{"q": "比较价格", "answer": "2000—3000", "state": "asked"}]
    assert len(result["questions_to_salesperson"]) == 3


def test_verified_customer_fact_and_unverified_fact_are_separated(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "guided_source")
    template = _template(db)
    followup = _draft(db, user, template)
    followup.raw_text = "老板说先别补货，店员说还是贴头皮"
    db.commit()
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "facts": [
            {"text": "先别补货", "nature": "customer_said", "speaker": "老板", "source": {"kind": "raw_text", "excerpt": "老板说先别补货"}},
            {"text": "客户已经接受价格", "nature": "customer_said", "speaker": "老板", "source": {"kind": "raw_text", "excerpt": "原文没有这句"}},
        ],
    }, ensure_ascii=False)})
    ai_parse_service.run_parse(followup.id, _ctx(user), session_factory=lambda: nullcontext(db))
    items = followup.ai_result["items"]
    assert items[0]["nature"] == "customer_said" and items[0]["source"]["label"] == "业务员转述"
    assert items[1]["nature"] == "to_confirm"
    assert followup.ai_result["evidence_kind"] == "customer"


def test_confirmed_record_persists_template_answers_and_item_nature(db):
    seed_dicts(db)
    user = make_user(db, "guided_save")
    customer = make_customer(db, user, "引导保存店")
    template = _template(db)
    record, _ = followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        result_code="有效沟通", request_id="guided-save-req", customer_id=customer.id, raw_text="2000—3000，含义待确认",
        template_code=template.code, template_version=template.version,
        template_answers={"fields": {"amount_meaning": {"raw": "2000—3000", "meaning": "未确认"}, "concern": "价格"},
                          "questions": [{"q": "比较对象", "answer": "同规格", "state": "asked"}]},
        items=[{"kind": "content", "text": "金额含义待确认", "nature": "to_confirm"}],
        evidence_kind="assessment",
    ))
    item = db.query(DomesticFollowupItem).filter_by(followup_id=record.id).one()
    assert item.nature == "to_confirm"
    assert record.template_version == 2 and record.template_answers["fields"]["concern"] == "价格"
    assert record.evidence_kind == "assessment"
    data = followup_service.serialize(db, record)
    assert data["items"][0]["nature"] == "to_confirm" and data["template_answers"]["questions"][0]["state"] == "asked"
