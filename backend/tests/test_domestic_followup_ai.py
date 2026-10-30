import json
from contextlib import nullcontext
from datetime import date

import pytest

from app.domestic_followup import ai_parse_service
from app.domestic_followup.models import DomesticFollowup
from tests.domestic_followup_helpers import make_customer, make_user, seed_dicts

FRI = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(ai_parse_service, "beijing_today", lambda: FRI)


def _ctx(user):
    return {"sub": str(user.id), "roles": [], "permissions": ["domestic_followup:read", "domestic_followup:write"]}


def _draft(db, user, request_id, **kw):
    row = DomesticFollowup(author_user_id=user.id, followup_date=FRI, request_id=request_id, status="draft",
                           ai_status="running", raw_text="原文", version=1, **kw)
    db.add(row)
    db.commit()  # run_parse 失败分支会 rollback；夹具先提交
    return row


def _run(db, followup, user):
    ai_parse_service.run_parse(followup.id, _ctx(user), session_factory=lambda: nullcontext(db))


def test_injects_enums_and_normalizes_output(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_a")
    customer = make_customer(db, user, "均哥三家店")
    followup = _draft(db, user, "ai-a")
    sent = {}

    def fake_chat(**kwargs):
        kwargs["db"].commit()  # 真实 facade 写调用日志会提交事务
        sent.update(kwargs)
        return {"log_id": 7, "content": json.dumps({
            "customer_hint": {"chat_title": "均哥 三家店", "matched_customer_id": customer.id, "confidence": 0.9},
            "summary": "想开新账号",
            "contents": [{"text": "月销 13 万", "origin": "user"}],
            "issues": [{"text": "退货率 50%", "category": "瞎分类", "severity": "很急", "origin": "user"}],
            "state_changes": ["店里增加短视频", "外星人入侵"],
            "next": {"date_expression": "下周一", "date": "2026-11-03", "method": "电话", "plan": "问开通进度"},
            "unreadable": ["第2张截图含语音条2″"],
        }, ensure_ascii=False)}
    monkeypatch.setattr(ai_parse_service, "chat", fake_chat)

    _run(db, followup, user)

    assert sent["preset_name"] == "domestic_followup_parse" and sent["snapshot_mode"] == "metadata"
    user_text = sent["messages"][0]["content"][0]["text"]
    assert "竞争品牌增加" in user_text and "售后退换" in user_text and "2026-10-30 周五" in user_text
    assert "均哥三家店" in user_text  # 未选客户 → 注入候选
    assert '"detail"' not in json.dumps(sent["messages"], ensure_ascii=False)

    draft = followup.ai_result
    assert followup.ai_status == "done" and followup.ai_log_id == 7
    assert draft["customer_id"] == customer.id
    issue = [i for i in draft["items"] if i["kind"] == "issue"][0]
    assert issue["category"] == "其他" and issue["severity"] == "一般"
    assert draft["state_changes"] == ["店里增加短视频"]
    assert draft["next"] == {"date": "2026-11-02", "weekday": "周一", "expression": "下周一", "basis": "mismatch",
                             "method": "电话", "plan": "问开通进度"}
    assert draft["unreadable"] == ["第2张截图含语音条2″"]


def test_blank_and_null_fields_from_model_are_tolerated(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_f")
    followup = _draft(db, user, "ai-f")
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "customer_hint": {"chat_title": "", "matched_customer_id": None, "confidence": None},
        "summary": "x", "issues": None, "state_changes": None,
        "next": {"date_expression": "", "date": "YYYY-MM-DD", "method": None, "plan": ""},
    })})
    _run(db, followup, user)
    assert followup.ai_status == "done"
    assert followup.ai_result["next"]["date"] is None and followup.ai_result["items"] == []


def test_low_confidence_hint_is_ignored(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_b")
    customer = make_customer(db, user, "低置信店")
    followup = _draft(db, user, "ai-b")
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "customer_hint": {"matched_customer_id": customer.id, "confidence": 0.5}, "summary": "x"})})
    _run(db, followup, user)
    assert followup.ai_result["customer_id"] is None


def test_hint_outside_candidates_is_ignored(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_c1")
    stranger = make_user(db, "fu_ai_c2")
    foreign = make_customer(db, stranger, "别人的店")
    followup = _draft(db, user, "ai-c")
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "customer_hint": {"matched_customer_id": foreign.id, "confidence": 0.95}, "summary": "x"})})
    _run(db, followup, user)
    assert followup.ai_result["customer_id"] is None


def test_failure_marks_failed_and_falls_back_to_ocr(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_d")
    followup = _draft(db, user, "ai-d")
    ocr_calls = []
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": "not json at all"})
    monkeypatch.setattr(ai_parse_service.attachment_service, "run_ocr",
                        lambda ids, session_factory=None: ocr_calls.append(ids))
    _run(db, followup, user)
    assert followup.ai_status == "failed" and "JSONDecodeError" in followup.ai_error
    assert ocr_calls == [[]]


def test_does_not_overwrite_confirmed_draft(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_e")
    followup = _draft(db, user, "ai-e")
    followup.status = "confirmed"
    db.flush()
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({"summary": "late"})})
    _run(db, followup, user)
    assert followup.ai_result is None
