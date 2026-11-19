import json
from contextlib import nullcontext
from datetime import date, datetime

import pytest

from app.domestic_followup import ai_parse_service, followup_service, task_service
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupAttachment, DomesticFollowupItem
from app.domestic_followup.schemas import ConfirmIn
from tests.domestic_followup_helpers import make_customer, make_shipment, make_user, seed_dicts

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


def _attachment(db, followup, user, monkeypatch):
    monkeypatch.setattr(ai_parse_service.attachment_service, "data_url", lambda att: "data:image/png;base64,AA")
    att = DomesticFollowupAttachment(followup_id=followup.id, uploader_user_id=user.id, seq=1,
                                     file_path="fu/x.png", mime_type="image/png")
    db.add(att)
    db.commit()
    return att.id


def _record_ocr(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_parse_service.attachment_service, "run_ocr",
                        lambda ids, **_kwargs: calls.append(list(ids)))
    return calls


def _user_text(sent):
    message = next(message for message in sent["messages"] if message["role"] == "user")
    return message["content"][0]["text"]


def _context(sent):
    line = next(row for row in _user_text(sent).split("\n") if row.startswith("背景："))
    return json.loads(line[len("背景："):])


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
    user_text = _user_text(sent)
    assert "竞争品牌增加" in user_text and "售后退换" in user_text and "2026-10-30 周五" in user_text
    assert any(message["role"] == "system" and "handled_source" in message["content"] for message in sent["messages"])
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


@pytest.mark.parametrize(("kind", "source", "record_only"), [
    ("suggestion", {"kind": "attachment", "attachment_index": 0}, True),
    ("issue", {"kind": "raw_text"}, True),
    ("suggestion", {"kind": "attachment", "attachment_index": 1}, False),
    ("suggestion", None, False),
], ids=["answered_in_screenshot", "answered_in_notes", "wrong_screenshot", "still_pending"])
def test_ai_objection_creates_a_todo_only_if_still_open(db, monkeypatch, kind, source, record_only):
    seed_dicts(db)
    user = make_user(db, "fu_ai_price")
    customer = make_customer(db, user, "试单店")
    followup = _draft(db, user, "ai-price-objection", customer_id=customer.id)
    objection = "客户认为15厘米发片1598元偏贵"
    reply = "分界最短规格是20厘米，所以按20厘米规格报价"
    ocr_text = f"客户：15厘米发片1598元有点贵\n我：{reply}"
    if source is None:
        ocr_text += "\n客户：还是贵，麻烦再申请一下折扣\n我：我去问问，明天回复你"
    if source and source["kind"] == "raw_text":
        followup.raw_text = f"{objection}。我已解释：{reply}。"
    _attachment(db, followup, user, monkeypatch)

    def fake_chat(**_kwargs):
        return {"content": json.dumps({
            f"{kind}s": [{"text": objection, "handled_source": {**source, "excerpt": reply} if source else None}],
            "ocr": [{"attachment_index": 0, "text": ocr_text}],
        }, ensure_ascii=False)}

    monkeypatch.setattr(ai_parse_service, "chat", fake_chat)
    monkeypatch.setattr(followup_service, "beijing_today", lambda: FRI)
    _run(db, followup, user)

    draft_items = followup.ai_result["items"]
    followup_service.confirm_draft(db, _ctx(user), followup.id, ConfirmIn(
        version=followup.version, customer_id=customer.id, result_code="有效沟通", items=draft_items,
    ))
    item = db.query(DomesticFollowupItem).filter_by(followup_id=followup.id).one()
    assert task_service.list_tasks(db, _ctx(user), task_type="issue")["total"] == (0 if record_only else 1)
    assert item.status == ("closed_no_action" if record_only else "open")
    assert objection in item.text
    assert (reply in item.text) is record_only


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
                        lambda ids, **_kwargs: ocr_calls.append(ids))
    _run(db, followup, user)
    assert followup.ai_status == "failed" and "JSONDecodeError" in followup.ai_error
    assert ocr_calls == []  # 没有截图就不开降级 OCR


def test_draft_confirmed_while_ai_running_is_not_overwritten(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_e")
    followup = _draft(db, user, "ai-e")
    att_id = _attachment(db, followup, user, monkeypatch)
    ocr_calls = _record_ocr(monkeypatch)

    def confirm_meanwhile(**kwargs):  # 模型还在跑，业务员已经手填确认
        followup.status = "confirmed"
        kwargs["db"].commit()
        return {"content": json.dumps({"summary": "late"})}
    monkeypatch.setattr(ai_parse_service, "chat", confirm_meanwhile)
    _run(db, followup, user)
    db.refresh(followup)
    assert followup.ai_result is None and followup.ai_status == "done"
    assert ocr_calls == [[att_id]]


def test_fallback_ocr_runs_even_if_marking_failed_cannot_commit(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_g")
    followup = _draft(db, user, "ai-g")
    att_id = _attachment(db, followup, user, monkeypatch)
    ocr_calls = _record_ocr(monkeypatch)
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": "not json"})

    def broken_commit():
        raise RuntimeError("connection lost")
    monkeypatch.setattr(db, "commit", broken_commit)
    _run(db, followup, user)
    assert ocr_calls == [[att_id]]


def test_success_path_ocrs_screenshots_the_model_skipped(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_h")
    followup = _draft(db, user, "ai-h")
    att_id = _attachment(db, followup, user, monkeypatch)
    ocr_calls = _record_ocr(monkeypatch)
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({"summary": "x"})})
    _run(db, followup, user)
    assert followup.ai_status == "done" and ocr_calls == [[att_id]]


def test_context_hides_followups_outside_scope_and_injects_rules(db, monkeypatch):
    seed_dicts(db)
    a = make_user(db, "fu_ai_i1")
    b = make_user(db, "fu_ai_i2")
    customer = make_customer(db, None, "公海店I", creator=a)  # 公海：B 可写不可读
    db.add(DomesticFollowup(author_user_id=a.id, customer_id=customer.id, followup_date=FRI, request_id="ai-i-a",
                            status="confirmed", summary="A的私下报价"))
    make_shipment(db, customer, a, datetime(2026, 10, 28, 9, 0))
    followup = _draft(db, b, "ai-i-b", customer_id=customer.id)
    sent = {}

    def fake_chat(**kwargs):
        sent.update(kwargs)
        return {"content": json.dumps({"summary": "x"})}
    monkeypatch.setattr(ai_parse_service, "chat", fake_chat)
    _run(db, followup, b)
    context = _context(sent)
    assert "A的私下报价" not in json.dumps(context, ensure_ascii=False)
    assert context["customer"]["recent_followups"] == [] and context["customer"]["recent_shipments"] == []
    assert context["rules"]["maintenance_days"] == 30 and context["rules"]["inquiry_days"] == 1
    assert context["allowed_values"]["severities"] == ["一般", "紧急"]


def test_unknown_customer_has_no_maintenance_days(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_j")
    followup = _draft(db, user, "ai-j")
    sent = {}
    monkeypatch.setattr(ai_parse_service, "chat",
                        lambda **k: sent.update(k) or {"content": json.dumps({"summary": "x"})})
    _run(db, followup, user)
    assert "maintenance_days" not in _context(sent)["rules"]


@pytest.mark.parametrize("payload", [
    {"customer_hint": {"chat_title": "店A", "confidence": "高"}},
    {"receipt_feedback": {"is_receipt_feedback": True, "has_problem": "否"}},
    {"unreadable": [{"text": "语音 3″"}, {"kind": "video"}]},
    {"state_changes": "订单减少"},
    {"customer_hint": {"matched_customer_id": "店A", "confidence": 0.9}},
    {"issues": ["退货率高"]},
], ids=["confidence_text", "has_problem_text", "unreadable_objects", "state_changes_string",
        "customer_id_text", "issue_strings"])
def test_malformed_model_fields_do_not_void_the_draft(db, monkeypatch, payload):
    seed_dicts(db)
    user = make_user(db, "fu_ai_k")
    followup = _draft(db, user, "ai-k")
    monkeypatch.setattr(ai_parse_service, "chat",
                        lambda **k: {"content": json.dumps({"summary": "x", **payload}, ensure_ascii=False)})
    _run(db, followup, user)
    assert followup.ai_status == "done"
    if "state_changes" in payload:
        assert followup.ai_result["state_changes"] == ["订单减少"]
    if "issues" in payload:
        assert [i["text"] for i in followup.ai_result["items"] if i["kind"] == "issue"] == ["退货率高"]
    if "unreadable" in payload:
        assert followup.ai_result["unreadable"] == ["语音 3″"]


@pytest.mark.parametrize("confidence", [86, -0.5, 1.5])
def test_out_of_range_confidence_is_treated_as_zero(db, monkeypatch, confidence):
    seed_dicts(db)
    user = make_user(db, "fu_ai_l")
    customer = make_customer(db, user, "越界置信店")
    followup = _draft(db, user, "ai-l")
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "customer_hint": {"matched_customer_id": customer.id, "confidence": confidence}, "summary": "x"})})
    _run(db, followup, user)
    assert followup.ai_result["customer_id"] is None and followup.ai_result["customer_confidence"] is None


def test_confirmed_meanwhile_still_keeps_ai_log_id(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_m")
    followup = _draft(db, user, "ai-m")

    def confirm_meanwhile(**kwargs):
        followup.status = "confirmed"
        kwargs["db"].commit()
        return {"log_id": 42, "content": json.dumps({"summary": "late"})}
    monkeypatch.setattr(ai_parse_service, "chat", confirm_meanwhile)
    _run(db, followup, user)
    db.refresh(followup)
    assert followup.ai_status == "done" and followup.ai_log_id == 42


def test_success_path_retries_previously_failed_ocr(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_n")
    followup = _draft(db, user, "ai-n")
    att_id = _attachment(db, followup, user, monkeypatch)
    att = db.get(DomesticFollowupAttachment, att_id)
    att.ocr_status = "failed"
    db.commit()
    ocr_calls = _record_ocr(monkeypatch)
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({"summary": "x"})})
    _run(db, followup, user)
    assert followup.ai_status == "done" and ocr_calls == [[att_id]]


def test_relative_dates_are_based_on_followup_date_for_backfilled_chats(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_rel")
    followup = DomesticFollowup(author_user_id=user.id, followup_date=date(2026, 10, 20), request_id="ai-rel",
                                status="draft", ai_status="running", raw_text="补录 10-20 的聊天", version=1)
    db.add(followup)
    db.commit()
    sent = {}

    def fake_chat(**kwargs):
        sent.update(kwargs)
        return {"content": json.dumps({"summary": "x", "next": {"date_expression": "明天", "date": "2026-10-31"}})}
    monkeypatch.setattr(ai_parse_service, "chat", fake_chat)

    _run(db, followup, user)

    context = _context(sent)
    assert context["today"] == "2026-10-30 周五" and context["followup_date"] == "2026-10-20"
    assert followup.ai_result["next"]["date"] == "2026-10-21"
    assert followup.ai_result["next"]["basis"] == "mismatch"


def test_next_steps_verify_sources_dates_and_default_selection(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_steps")
    followup = _draft(db, user, "ai-steps")
    followup.raw_text = "客户说下周四前给方案。我答应周四前发技术方案。"
    db.commit()
    att_id = _attachment(db, followup, user, monkeypatch)
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "summary": "已约定方案",
        "next_steps": [
            {"text": "回访方案", "basis": "customer_agreed", "trigger": "date", "date": "2026-11-05",
             "source": {"kind": "raw_text", "excerpt": "客户说下周四前给方案"}},
            {"text": "协调技术", "basis": "our_commitment", "trigger": "date", "date": "2026-11-04",
             "source": {"kind": "raw_text", "excerpt": "我答应周四前发技术方案"}},
            {"text": "截图里的约定", "basis": "customer_agreed", "trigger": "event", "event": "方案发出后",
             "source": {"kind": "attachment", "attachment_index": 0, "excerpt": "周四前给方案"}},
            {"text": "无出处建议", "basis": "customer_agreed", "trigger": "date", "date": "2026-11-06",
             "source": {"kind": "raw_text", "excerpt": "原文根本没有这句话"}},
        ],
        "ocr": [{"attachment_index": 0, "text": "周四前给方案"}],
    }, ensure_ascii=False)})
    _run(db, followup, user)
    steps = followup.ai_result["next_steps"]
    assert steps[0]["default_selected"] is True and steps[0]["source"]["verified"] is True
    assert steps[1]["default_selected"] is False and steps[1]["commitment_advice"] is True
    assert steps[2]["default_selected"] is False and steps[2]["source"]["label"] == "截图转写·待核"
    assert steps[3]["basis"] == "ai_suggestion" and steps[3]["default_selected"] is False
    assert steps[0]["step_key"] and len({step["step_key"] for step in steps}) == 4


def test_legacy_next_does_not_duplicate_next_steps_or_drop_fourth(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_next_dedup")
    followup = _draft(db, user, "ai-next-dedup")
    steps = [{"text": f"步骤{i}", "basis": "ai_suggestion", "trigger": "date", "date": "2026-11-05"} for i in range(4)]
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "next": {"plan": "步骤0", "date": "2026-11-05"}, "next_steps": steps,
    })})
    _run(db, followup, user)
    assert [step["text"] for step in followup.ai_result["next_steps"]] == ["步骤0", "步骤1", "步骤2", "步骤3"]


def test_ai_facts_default_to_ai_inferred_origin(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_ai_fact_origin")
    followup = _draft(db, user, "ai-fact-origin")
    monkeypatch.setattr(ai_parse_service, "chat", lambda **k: {"content": json.dumps({
        "facts": [{"text": "模型推断的判断", "nature": "assessment"}],
    }, ensure_ascii=False)})
    _run(db, followup, user)
    assert followup.ai_result["items"][0]["origin"] == "ai_inferred"
