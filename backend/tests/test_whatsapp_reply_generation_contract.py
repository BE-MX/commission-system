"""Direct-generation contracts replace citation rejection and fixed planner calls."""
import json
import pytest
from app.whatsapp_translation import reply_service, reply_state
from app.whatsapp_translation.errors import WhatsAppTranslationError
from tests.reply_support import mock_model, output, request, seed_reply

@pytest.fixture
def configured(db, monkeypatch):
    reply_state.reply_cache.clear()
    return seed_reply(db, monkeypatch)


def test_auto_preserves_all_topic_answers_in_order_without_extra_model_calls(db, monkeypatch, configured):
    parts = ['Synthetic process P is applied only in step two.', 'Synthetic finish F is limited to grade Z.', 'Which of the listed specifications do you need?']
    calls = mock_model(monkeypatch, generator=output(auto_action='reply', reply_segments=parts))
    result = reply_service.suggest_reply(db, configured[0], request(mode='auto'))
    assert result.reply_segments == parts
    assert result.reply_text == '\n\n'.join(parts)
    assert len(calls) == 1
    assert '所有段落合起来应回应本轮每个问题' in calls[0]['messages'][0]['content']


def test_release_facts_and_queried_catalog_reach_one_generation_call(db, monkeypatch, configured, tmp_path):
    from tests.reply_support import publish, binding
    from app.whatsapp_translation import reply_service
    identity, _, library, _, _, settings = configured
    actor = {'sub': str(identity.user_id), 'roles': ['super_admin']}
    process = publish(db, actor, library.id, 'Synthetic process FAQ', 'Process P uses method Z.')
    finish = publish(db, actor, library.id, 'Synthetic finish FAQ', 'Finish F follows step Z.')
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps([binding(process, 'public_fact').model_dump(), binding(finish, 'public_fact').model_dump()]), encoding='utf8')
    monkeypatch.setattr(settings, 'WHATSAPP_REPLY_SOURCE_PROFILE', str(profile))
    # An older inline list contains only constraints; release facts must still enter.
    monkeypatch.setattr(settings, 'WHATSAPP_REPLY_SOURCE_BINDINGS', settings.WHATSAPP_REPLY_SOURCE_BINDINGS[:1])
    catalog = {'status': 'matched', 'matched_by': 'family', 'matches': [{'model': 'Synthetic Weft', 'size': '12', 'unit': '17g'}], 'available_lengths': ['12']}
    monkeypatch.setattr(reply_service, 'retrieve_catalog', lambda *args: catalog)
    live_actor = reply_service.live_actor
    monkeypatch.setattr(reply_service, 'live_actor', lambda *args: {**live_actor(*args), 'permissions': ['whatsapp_reply:write', 'knowledge:read', 'invoice:read']})
    calls = mock_model(monkeypatch, generator=output(auto_action='reply', reply_segments=['Process P uses method Z.', 'Finish F follows step Z.', 'Synthetic Weft is 12 inches and 17g.']))
    result = reply_service.suggest_reply(db, identity, request(mode='auto', messages=[{'role':'customer','text':'What process and finish apply to this weft?'}]))
    payload = json.loads(calls[0]['messages'][1]['content'])
    assert {process['document_id'], finish['document_id']}.issubset({item['document_id'] for item in payload['sources']})
    assert payload['conversation']['product_catalog'] == catalog
    assert result.risk_flags == ['limited_context', 'catalog_matched']
    assert len(calls) == 1


@pytest.mark.parametrize('revoke_at', ['generation', 'cache'])
def test_catalog_permission_is_rechecked_after_generation_and_on_cache(db, monkeypatch, configured, revoke_at):
    allowed = [True]
    live_actor = reply_service.live_actor
    def actor(*args):
        value = live_actor(*args)
        if allowed[0]:
            value['permissions'].append('invoice:read')
        return value
    monkeypatch.setattr(reply_service, 'live_actor', actor)
    monkeypatch.setattr(reply_service, 'retrieve_catalog', lambda *args: {'status': 'matched', 'matches': [{'model': 'Synthetic', 'size': '12', 'unit': '17g'}]})
    def on_call(*args):
        if revoke_at == 'generation':
            allowed[0] = False
    mock_model(monkeypatch, on_call=on_call)
    payload = request()
    if revoke_at == 'cache':
        assert reply_service.suggest_reply(db, configured[0], payload).status == 'ready'
        allowed[0] = False
    with pytest.raises(WhatsAppTranslationError) as exc:
        reply_service.suggest_reply(db, configured[0], payload)
    assert exc.value.error_code == 'reply_permission_denied'


def test_latest_customer_focus_and_direct_answer_instructions_reach_auto_agent(db, monkeypatch, configured):
    from tests.reply_support import publish, binding
    identity, _, library, _, _, settings = configured
    admin = {'sub': str(identity.user_id), 'roles': ['super_admin']}
    fact = publish(db, admin, library.id, 'Synthetic finish FAQ', 'Synthetic finish Z is used only after colouring.')
    item = binding(fact, 'public_fact'); item.aliases = ['finish']
    settings.WHATSAPP_REPLY_SOURCE_BINDINGS.append(item.model_dump())
    focused = []
    retrieve = reply_service.retrieve_reply_sources
    def observed_retrieval(*args, **kwargs):
        focused.append(kwargs['focus_query'])
        return retrieve(*args, **kwargs)
    monkeypatch.setattr(reply_service, 'retrieve_reply_sources', observed_retrieval)
    calls = mock_model(monkeypatch, generator=output(auto_action='reply', reply_segments=['Synthetic finish Z is used after colouring.']))
    result = reply_service.suggest_reply(db, identity, request(mode='auto', messages=[
        {'role': 'salesperson', 'text': 'Historical generic extensions and donor details. ' * 150},
        {'role': 'customer', 'text': 'What finish is used, and which specifications are offered?'},
    ]))
    payload = json.loads(calls[0]['messages'][1]['content'])
    assert any(s['document_id'] == fact['document_id'] and s['purpose'] == 'public_fact' for s in payload['sources'])
    assert '已知与未知分开处理' in calls[0]['messages'][0]['content']
    assert result.status == 'ready'
    assert focused == ['What finish is used, and which specifications are offered?']

@pytest.mark.parametrize("text", [
    "Thanks for your message today.", "You mentioned USD 100 as your budget.",
    "I cannot guarantee delivery.", "Catalog: https://example.com/catalog",
    "20 models, 10 pieces each means 200 pieces.", "Which size do you need?",
])
def test_content_is_editable_not_rejected_by_semantic_rules(db, monkeypatch, configured, text):
    calls = mock_model(monkeypatch, generator=output(reply_text=text, claims=[{"source_index": 999, "quote": "bad"}]))
    result = reply_service.suggest_reply(db, configured[0], request())
    assert result.status == "ready" and result.reply_text == text
    assert len(calls) == 1
    assert result.claims == []  # Model citations are no longer presented as verified.

@pytest.mark.parametrize("purpose", ["method", "constraint", "public_fact"])
def test_source_purpose_reaches_agent_without_forced_citation_schema(db, monkeypatch, configured, purpose):
    configured[-1].WHATSAPP_REPLY_SOURCE_BINDINGS[1]["purpose"] = purpose
    calls = mock_model(monkeypatch)
    reply_service.suggest_reply(db, configured[0], request())
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["sources"][1]["purpose"] == purpose
    assert "allowed_fact_source_indices" not in payload
    assert "claims" not in payload.get("schema", {}).get("required", [])

def test_more_than_forty_rounds_reach_single_agent_call_in_order(db, monkeypatch, configured):
    messages = [{"role": "customer" if i % 2 == 0 else "salesperson", "text": f"message {i}", "timestamp": f"day {i // 20}"} for i in range(160)]
    calls = mock_model(monkeypatch)
    payload = request(messages=messages, context_scope={"requested_limit": 2000})
    result = reply_service.suggest_reply(db, configured[0], payload)
    data = json.loads(calls[0]["messages"][1]["content"])
    assert len(calls) == 1 and result.context_processing == "full"
    assert data["conversation"]["messages"] == payload.model_dump()["messages"]

def test_optional_blank_or_invalid_bookkeeping_never_suppresses_draft(db, monkeypatch, configured):
    calls = mock_model(monkeypatch, generator=output(meaning_zh="   ", rationale_zh="\n", missing_information=None),
                       planner={"memory_changes": [{"invalid": "optional"}]})
    result = reply_service.suggest_reply(db, configured[0], request())
    assert result.reply_text == output()["reply_text"] and result.status == "ready"
    assert result.meaning_zh.strip() and len(calls) == 1

def test_long_history_is_explicitly_summarized_without_dropping_chunks(db, monkeypatch, configured):
    calls = []
    def model(db, **kwargs):
        data = json.loads(kwargs["messages"][1]["content"]); calls.append(data)
        if data.get("task") == "summarize_history":
            return {"content": json.dumps({"summary": "Synthetic complete chunk summary"})}
        return {"content": json.dumps(output())}
    monkeypatch.setattr(reply_service, "chat", model)
    messages = [{"role": "customer", "text": str(i) + "x" * 1500} for i in range(30)]
    result = reply_service.suggest_reply(db, configured[0], request(messages=messages, context_scope={"requested_limit": 2000}))
    assert result.context_processing == "summarized"
    seen = {part["message_index"] for call in calls[:-1] for part in call["messages"]}
    assert seen == set(range(30))
    assert calls[-1]["conversation"]["history_summaries"]
    assert sum(len(m["text"]) for m in calls[-1]["conversation"]["messages"]) <= 8000

@pytest.mark.parametrize("action,segments", [("reply", ["Hi!", "Which size works for you? 🙂"]), ("wait", []), ("handoff", [])])
def test_auto_reply_contract(db, monkeypatch, configured, action, segments):
    calls = mock_model(monkeypatch, generator=output(auto_action=action, reply_segments=segments))
    result = reply_service.suggest_reply(db, configured[0], request(mode="auto"))
    assert result.auto_action == action and result.reply_segments == segments
    assert "后台系统提示词" in calls[0]["messages"][0]["content"]
    assert json.loads(calls[0]["messages"][1]["content"])["conversation"]["mode"] == "auto"
    if action == "reply":
        assert result.reply_text == "\n\n".join(segments)

@pytest.mark.parametrize("fields", [{},
    {"auto_action": {'unexpected': 'object'}, "reply_segments": ['Known answer.']},
    {"auto_action": "reply", "reply_segments": ["x" * 401]},
    {"auto_action": "reply", "reply_segments": ['word ' * 300]},
    {"auto_action": "reply", "reply_segments": ['Known answer.', {'invalid': 'part'}]}])
def test_ambiguous_or_unfit_auto_output_preserves_draft_without_sending(db, monkeypatch, configured, fields):
    mock_model(monkeypatch, generator=output(**fields))
    result = reply_service.suggest_reply(db, configured[0], request(mode="auto"))
    assert result.auto_action == 'handoff' and result.reply_segments == []
    assert 'auto_reply_review_required' in result.risk_flags
    if fields.get('reply_segments') and all(isinstance(part, str) for part in fields['reply_segments']):
        assert result.reply_text == '\n\n'.join(fields['reply_segments']).strip()
    else:
        assert result.reply_text == output()['reply_text']


@pytest.mark.parametrize('fields', [
    {'reply_text': None, 'reply_segments': ['First answer.', 'Second answer.']},
    {'reply_segments': ['Known answer. ' * 35]},
    {'reply_segments': ['First.', 'Second.', 'Third.', 'Fourth.']},
    {'reply_segments': ['Answer 🙂. ' * 39]},
    {'reply_segments': []},
])
def test_auto_recovers_usable_segments_without_another_model_call(db, monkeypatch, configured, fields):
    from app.whatsapp_translation.reply_segments import browser_length
    calls = mock_model(monkeypatch, generator=output(auto_action='reply', **fields))
    result = reply_service.suggest_reply(db, configured[0], request(mode='auto'))
    original = '\n\n'.join(fields['reply_segments']) or output()['reply_text']
    assert result.auto_action == 'reply' and 1 <= len(result.reply_segments) <= 3
    assert ''.join(result.reply_text.split()) == ''.join(original.split())
    assert all(browser_length(part) <= 400 for part in result.reply_segments)
    assert len(calls) == 1


@pytest.mark.parametrize('action', ['wait', 'handoff'])
def test_explicit_no_send_action_wins_over_stray_segments(db, monkeypatch, configured, action):
    mock_model(monkeypatch, generator=output(auto_action=action, reply_text=None, rationale_zh={'invalid': 'optional'}, reply_segments=['Do not send this.']))
    result = reply_service.suggest_reply(db, configured[0], request(mode='auto'))
    assert result.auto_action == action and result.reply_segments == []


@pytest.mark.parametrize('content,code', [
    ('{"reply_text":', 'reply_model_format_invalid'),
    ('[]', 'reply_model_format_invalid'),
    ('{"auto_action":"reply","reply_segments":[]}', 'reply_model_empty'),
    (json.dumps(output(reply_text='x' * 3001)), 'reply_model_too_long'),
])
def test_unrecoverable_output_reports_specific_metadata_only_error(db, monkeypatch, configured, content, code):
    monkeypatch.setattr(reply_service, 'chat', lambda *args, **kwargs: {'content': content})
    with pytest.raises(WhatsAppTranslationError) as exc:
        reply_service.suggest_reply(db, configured[0], request(mode='auto'))
    assert exc.value.error_code == code
