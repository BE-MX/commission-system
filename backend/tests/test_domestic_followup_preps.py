import json
from contextlib import nullcontext
from datetime import date

import pytest

from app.ai import call_service
from app.ai.models import AiPreset, AiProvider
from app.domestic_followup import attachment_service, followup_service, prep_access, prep_service, strategy_service
from app.domestic_followup.collaboration_models import FollowupResponsibility
from app.domestic_followup.models import DomesticFollowup
from app.domestic_followup.prep_models import DomesticFollowupPrep
from app.domestic_followup.prep_schemas import PrepCreateIn
from app.domestic_followup.schemas import DirectSaveIn
from app.domestic_followup.template_models import DomesticFollowupTemplate
from tests.domestic_followup_helpers import make_customer, make_user, seed_dicts

TODAY = date(2026, 11, 16)


def _ctx(user):
    return {"sub": str(user.id), "roles": [], "permissions": ["domestic_followup:read", "domestic_followup:write"]}


def _template(db, code="T03"):
    row = DomesticFollowupTemplate(code=code, version=1, name="场景", status="active", prep_fields=[], record_fields=[],
                                   guidance="先核实", params={"prep_minutes": [3, 5], "talk_minutes": [5, 8]},
                                   avoid=[{"rule": "不能补成预算不足", "keywords": ["预算不足"]}], short_form="")
    db.add(row)
    db.flush()
    return row


def _prep(db, user, customer, template, **values):
    options = {"status": "draft", "strategy_status": "none", "version": 1, **values}
    prep = DomesticFollowupPrep(customer_id=customer.id, author_user_id=user.id, template_code=template.code,
                                template_version=template.version, goal="核实比较口径", request_id=f"prep-{user.id}-{customer.id}",
                                **options)
    db.add(prep)
    db.flush()
    return prep


def test_current_owner_readonly_author_loses_scope_and_third_party_denied(db):
    a = make_user(db, "prep_author")
    b = make_user(db, "prep_new_owner")
    c = make_user(db, "prep_third")
    customer = make_customer(db, a, "交接准备店")
    prep = _prep(db, a, customer, _template(db))
    assert prep_access.can_read(db, _ctx(a), prep)
    customer.owner_user_id = b.id
    db.flush()
    assert prep.status == "expired"
    assert prep_access.can_read(db, _ctx(b), prep)
    assert not prep_access.can_read(db, _ctx(a), prep)
    assert not prep_access.can_read(db, _ctx(c), prep)
    with pytest.raises(PermissionError, match="只有作者"):
        prep_access.ensure_author(db, _ctx(b), prep)


def test_managed_unassigned_has_no_current_owner(db):
    a = make_user(db, "prep_managed_a")
    b = make_user(db, "prep_managed_b")
    customer = make_customer(db, a, "托管公海店")
    db.add(FollowupResponsibility(customer_id=customer.id, owner_user_id=None, status="unassigned", version=1))
    db.flush()
    assert prep_access.current_owner(db, customer) is None
    customer.owner_user_id = b.id
    db.flush()
    assert prep_access.current_owner(db, customer) is None


def test_stop_strategy_drops_sales_talk_and_validates_evidence_numbers_and_time(db, monkeypatch):
    seed_dicts(db)
    a = make_user(db, "prep_strategy_a")
    other = make_user(db, "prep_strategy_b")
    customer = make_customer(db, a, "拒绝策略店")
    db.add(DomesticFollowup(author_user_id=other.id, customer_id=customer.id, followup_date=TODAY,
                            request_id="prep-refusal", status="confirmed", result_code="客户拒绝", version=2,
                            raw_text="不要再打电话"))
    template = _template(db)
    prep = _prep(db, a, customer, template, strategy_status="running")
    db.commit()

    def fake_chat(**kwargs):
        assert kwargs["snapshot_mode"] == "metadata"
        return {"log_id": 9, "content": json.dumps({
            "mode": "normal", "headline": "99% 客户会改变主意，预算不足", "why": "编造依据",
            "opening": "继续推销", "key_questions": [{"q": "还需要吗"}],
            "reply_branches": [{"when": "拒绝", "do": "换微信"}],
            "evidence_refs": [{"type": "followup", "id": 99999, "version": 1}],
            "time_budget": {"prep_minutes": [30, 60]},
        }, ensure_ascii=False)}
    monkeypatch.setattr(strategy_service, "chat", fake_chat)
    strategy_service.run_strategy(prep.id, _ctx(a), session_factory=lambda: nullcontext(db))
    strategy = prep.strategy
    assert prep.strategy_status == "done" and strategy["mode"] == "stop"
    assert strategy["opening"] == "" and strategy["key_questions"] == [] and strategy["reply_branches"] == []
    assert strategy["evidence_refs"] == [] and strategy["why"].startswith("依据不足：")
    assert strategy["time_budget"]["prep_minutes"] == [3, 5]
    reasons = {warning["reason"] for warning in strategy["warnings"]}
    assert "此数字未在资料中出现，请核实" in reasons and "不能补成预算不足" in reasons


@pytest.mark.parametrize("recover", [True, False], ids=["retry-succeeds", "retry-exhausted"])
def test_strategy_retries_truncated_model_output(db, monkeypatch, recover):
    seed_dicts(db)
    user = make_user(db, "prep_strategy_retry")
    customer = make_customer(db, user, "策略重试店")
    prep = _prep(db, user, customer, _template(db), strategy_status="failed", strategy_count=2)
    provider = AiProvider(name="DeepSeek test", api_base="https://api.deepseek.com", timeout_sec=120)
    db.add(provider)
    db.flush()
    db.add(AiPreset(
        preset_name=strategy_service.STRATEGY_PRESET, provider_id=provider.id, model="deepseek-flash",
        parameters={"temperature": 0.3, "max_tokens": 4096}, system_prompt="只输出 JSON。",
    ))
    db.commit()

    requests = []
    clock = iter((100.0, 128.0, 150.0))
    monkeypatch.setattr(attachment_service, "monotonic", lambda: next(clock))

    def model_response(_url, *, body, timeout_sec, enforce_total_timeout=False, **_kwargs):
        requests.append((body, timeout_sec, enforce_total_timeout))
        if len(requests) == 1 or not recover:
            return {
                "choices": [{"message": {"content": '{"headline": "未结束'}, "finish_reason": "length"}],
                "usage": {"completion_tokens": 4096},
            }
        output = {"headline": "核实报价比较口径", "mode": "normal", "opening": "方便聊聊对比的款式吗？"}
        return {"choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}]}

    monkeypatch.setattr(call_service, "post_json", model_response)
    prep, started = strategy_service.start(db, _ctx(user), prep.id)
    assert started
    db.commit()
    strategy_service.run_strategy(prep.id, _ctx(user), expected_version=prep.version,
                                  session_factory=lambda: nullcontext(db))

    if recover:
        assert prep.strategy_status == "done", prep.strategy_error
        assert prep.strategy["headline"] == "核实报价比较口径"
        assert prep.strategy_error is None and prep.strategy_log_id is not None
    else:
        assert prep.strategy_status == "failed"
        assert prep.strategy is None
    assert prep.goal == "核实比较口径" and prep.strategy_count == 3
    assert [(timeout, total) for _, timeout, total in requests] == [(120, True), (92, True)]
    for body, _, _ in requests:
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}


def test_generation_limit_and_single_use_binding(db):
    seed_dicts(db)
    user = make_user(db, "prep_bind")
    customer = make_customer(db, user, "准备绑定店")
    prep = _prep(db, user, customer, _template(db))
    db.commit()
    first, _ = followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        result_code="有效沟通", request_id="prep-bind-first", customer_id=customer.id, raw_text="第一次", prep_id=prep.id))
    assert first.prep_id == prep.id and prep.status == "used" and prep.followup_id == first.id
    second, _ = followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        result_code="有效沟通", request_id="prep-bind-second", customer_id=customer.id, raw_text="第二次", prep_id=prep.id))
    assert second.prep_id is None and second._confirmation_warnings
    prep.status = "ready"
    prep.strategy_count = 5
    db.flush()
    with pytest.raises(prep_service.PrepConflictError, match="5 次"):
        strategy_service.start(db, _ctx(user), prep.id)


def test_strategy_becomes_stale_on_new_or_edited_evidence(db):
    user = make_user(db, "prep_stale")
    customer = make_customer(db, user, "策略过期店")
    record = DomesticFollowup(author_user_id=user.id, customer_id=customer.id, followup_date=TODAY,
                              request_id="prep-stale-record", status="confirmed", version=2)
    db.add(record)
    db.flush()
    prep = _prep(db, user, customer, _template(db), strategy_status="done", strategy={
        "evidence_versions": {str(record.id): 2}, "latest_followup_id": record.id,
    })
    assert not strategy_service.is_stale(db, prep)
    record.version = 3
    db.flush()
    assert strategy_service.is_stale(db, prep)


def test_draft_creation_rechecks_prep_author_before_ai_can_read_it(db):
    from app.domestic_followup.schemas import DraftCreateIn

    author = make_user(db, "prep_private_author")
    other = make_user(db, "prep_private_other")
    customer = make_customer(db, author, "私有背调店")
    prep = _prep(db, author, customer, _template(db), known_facts=[{"text": "不能泄露的事实"}])
    db.commit()
    with pytest.raises(PermissionError):
        followup_service.create_draft(db, _ctx(other), DraftCreateIn(
            request_id="prep-private-draft", raw_text="试图读取", prep_id=prep.id,
        ))
    assert db.query(DomesticFollowup).filter_by(request_id="prep-private-draft").first() is None


def test_context_only_carries_facts_from_readable_preps_and_hides_issue_text(db):
    from app.domestic_followup.models import DomesticFollowupItem

    author = make_user(db, "prep_context_author")
    caller = make_user(db, "prep_context_caller")
    customer = make_customer(db, None, "公海准备上下文店", creator=author)
    prep = _prep(db, author, customer, _template(db), status="used", followup_id=99,
                 known_facts=[{"text": "不能向受限用户泄露"}])
    db.add(DomesticFollowupItem(followup_id=99, customer_id=customer.id, seq=1, kind="issue",
                                text="受限异常正文", severity="紧急", status="open"))
    db.commit()
    data = prep_service.context(db, _ctx(caller), customer.id)
    assert data["carried_facts"] == [] and data["history_count"] == 0
    assert "受限异常正文" not in data["recommendation"]["reason"]


def test_idempotent_replay_rechecks_author_scope(db):
    from app.domestic_followup.prep_schemas import PrepCreateIn

    author = make_user(db, "prep_replay_author")
    new_owner = make_user(db, "prep_replay_owner")
    customer = make_customer(db, author, "撤权幂等店")
    template = _template(db)
    payload = PrepCreateIn(request_id="prep-replay-request", customer_id=customer.id,
                           template_code=template.code, goal="原目标")
    prep = prep_service.create(db, _ctx(author), payload)
    db.commit()
    customer.owner_user_id = new_owner.id
    db.flush()
    with pytest.raises(PermissionError):
        prep_service.create(db, _ctx(author), payload)
    assert prep.status == "expired"


def test_clone_is_idempotent(db):
    from app.domestic_followup.prep_schemas import PrepCloneIn

    author = make_user(db, "prep_clone_author")
    customer = make_customer(db, author, "克隆幂等店")
    source = _prep(db, author, customer, _template(db))
    payload = PrepCloneIn(request_id="prep-clone-request")
    first = prep_service.clone(db, _ctx(author), source.id, payload)
    second = prep_service.clone(db, _ctx(author), source.id, payload)
    assert first.id == second.id
    assert first.strategy["cloned_from_prep_id"] == source.id


def test_strategy_result_from_old_version_is_discarded(db, monkeypatch):
    user = make_user(db, "prep_version_author")
    customer = make_customer(db, user, "策略乱序店")
    prep = _prep(db, user, customer, _template(db), strategy_status="running", version=2)
    db.commit()
    monkeypatch.setattr(strategy_service, "chat", lambda **kwargs: {"content": json.dumps({
        "mode": "normal", "headline": "旧策略不能回来", "evidence_refs": [],
    })})
    prep.version = 3
    prep.strategy_status = "none"
    db.flush()
    strategy_service.run_strategy(prep.id, _ctx(user), expected_version=2, session_factory=lambda: nullcontext(db))
    assert prep.strategy is None and prep.strategy_status == "none"


def test_empty_evidence_strategy_still_becomes_stale_on_new_record(db):
    user = make_user(db, "prep_empty_evidence")
    customer = make_customer(db, user, "空引用策略店")
    prep = _prep(db, user, customer, _template(db), strategy_status="done", strategy={
        "evidence_versions": {}, "latest_followup_id": 0,
    })
    db.add(DomesticFollowup(author_user_id=user.id, customer_id=customer.id, followup_date=TODAY,
                            request_id="prep-empty-new", status="confirmed", version=1))
    db.flush()
    assert strategy_service.is_stale(db, prep)


def test_revoked_prep_is_not_read_during_ai_parse(db, monkeypatch):
    from app.domestic_followup import ai_parse_service
    from app.domestic_followup.schemas import DraftCreateIn

    author = make_user(db, "prep_parse_author")
    new_owner = make_user(db, "prep_parse_owner")
    customer = make_customer(db, author, "撤权整理店")
    prep = _prep(db, author, customer, _template(db), known_facts=[{"text": "不能进入提示词"}])
    draft, _ = followup_service.create_draft(db, _ctx(author), DraftCreateIn(
        request_id="prep-revoked-parse", raw_text="原文", prep_id=prep.id,
    ))
    db.commit()
    customer.owner_user_id = new_owner.id
    db.flush()
    called = []
    monkeypatch.setattr(ai_parse_service, "chat", lambda **kwargs: called.append(kwargs))
    ai_parse_service.run_parse(draft.id, _ctx(author), session_factory=lambda: nullcontext(db))
    assert called == [] and draft.ai_result is None and draft.ai_status == "failed"


def test_valid_prep_completes_ai_parse_successfully(db, monkeypatch):
    from app.domestic_followup import ai_parse_service
    from app.domestic_followup.schemas import DraftCreateIn

    author = make_user(db, "prep_parse_success")
    customer = make_customer(db, author, "正常准备整理店")
    prep = _prep(db, author, customer, _template(db))
    draft, _ = followup_service.create_draft(db, _ctx(author), DraftCreateIn(
        request_id="prep-valid-parse", raw_text="老板说明天再谈", prep_id=prep.id,
    ))
    db.commit()
    monkeypatch.setattr(ai_parse_service, "chat", lambda **kwargs: {"content": json.dumps({
        "summary": "整理成功", "facts": [], "next_steps": [],
    }, ensure_ascii=False)})
    ai_parse_service.run_parse(draft.id, _ctx(author), session_factory=lambda: nullcontext(db))
    assert draft.ai_status == "done" and draft.ai_result["summary"] == "整理成功"
    assert draft.ai_result["template_code"] == prep.template_code
