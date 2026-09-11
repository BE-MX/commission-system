"""Synthetic-only fixtures shared by reply tests and offline evaluation."""

import json
from uuid import uuid4

from app.ai.models import AiPreset, AiProvider
from app.auth.models import ArkPermission, ArkRolePermission
from app.core.config import get_settings
from app.knowledge import service as knowledge
from app.knowledge.reply_sources import SourceBinding, content_hash, sections
from app.whatsapp_translation.auth import DeviceIdentity
from app.whatsapp_translation.reply_schemas import ReplyRequest
from tests.test_whatsapp_translation_auth import make_device


def request(**overrides):
    data = {
        "request_id": str(uuid4()), "conversation_epoch": str(uuid4()),
        "context_version": 1, "draft_version": 0,
        "messages": [{"role": "customer", "text": "I need a lightweight weft. Could you explain this method?"}],
        "context_scope": {"requested_limit": 20, "latest_visible": False},
    }
    return ReplyRequest.model_validate({**data, **overrides})


def plan(**overrides):
    return {**{
        "reply_language": "en", "language_confident": True, "queries": ["发帘", "Genius Weft"],
        "stage": "产品兴趣", "activity": "当前有提问，时间间隔未知", "trend": "unknown",
        "blocker": "尚未确认安装方式", "goal": "确认所需安装方式", "strategy": "先回答再确认用途",
        "completion_signal": "客户确认安装方式",
        "evidence": [{"message_index": 0, "role": "customer", "kind": "confirmed_need", "summary": "客户询问轻薄发帘"}],
        "action": {"kind": "clarify", "focus": "确认安装方式", "question": "Which installation method do you prefer?", "owner": "customer", "completion_signal": "客户确认安装方式"},
        "memory_changes": [], "unanswered_requests": [0], "answered_questions": [],
    }, **overrides}


def output(**overrides):
    return {**{
        "status": "ready", "reply_language": "en",
        "reply_text": "Genius Weft has a thin seam. Which installation method do you prefer?",
        "meaning_zh": "Genius Weft 接缝薄。您倾向哪种安装方式？",
        "rationale_zh": "先回答轻薄需求，再确认安装方式；客户确认方式后才有明确的匹配依据。",
        "claims": [{"text": "Genius Weft has a thin seam.", "source_index": 1, "quote": "Genius Weft has a thin seam."}],
        "risk_flags": [], "missing_information": [],
    }, **overrides}


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def seed_reply(db, monkeypatch):
    user, device, token = make_device(db, username="reply-worker", role_name="reply-worker-role")
    for code in ("whatsapp_reply:write", "knowledge:read"):
        perm = ArkPermission(code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
        db.add(perm)
        db.flush()
        db.add(ArkRolePermission(role_id=user.roles[0].id, permission_id=perm.id))
    provider = AiProvider(name="synthetic-reply", provider_type="direct", api_base="https://synthetic.invalid", is_enabled=True)
    db.add(provider)
    db.flush()
    for name in ("whatsapp_reply_planner", "whatsapp_reply_generator"):
        db.add(AiPreset(preset_name=name, provider_id=provider.id, model="synthetic-model", is_enabled=True, parameters={"max_tokens": 1200}))
    db.commit()
    identity = DeviceIdentity(user_id=user.id, device_id=device.id, real_name="synthetic", extension_version="1.2.6", expires_at=device.expires_at, is_admin=False)
    admin = {"sub": str(user.id), "roles": ["super_admin"], "permissions": []}
    library = knowledge.create_library(db, admin, name="Synthetic sales knowledge", category="company")
    policy = publish(db, admin, library.id, "Synthetic policy", "Do not promise sample refunds or delivery dates. Confirm conditions internally.")
    fact = publish(db, admin, library.id, "Genius Weft 发帘", "Genius Weft has a thin seam.")
    bindings = [binding(policy, "constraint", mandatory=True), binding(fact, "public_fact")]
    settings = get_settings()
    monkeypatch.setattr(settings, "WHATSAPP_REPLY_ENABLED", True)
    monkeypatch.setattr(settings, "WHATSAPP_REPLY_SOURCE_PROFILE", "")
    monkeypatch.setattr(settings, "WHATSAPP_REPLY_SOURCE_BINDINGS", [item.model_dump() for item in bindings])
    return identity, token, library, policy, fact, settings


def publish(db, actor, library_id, title, text):
    document = knowledge.create_document(db, actor, library_id, title=title, content={
        "type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    })
    approval = knowledge.submit_document(db, actor, document.id)
    knowledge.approve_request(db, actor, approval.id)
    return knowledge.get_published_document(db, actor, document.id)


def binding(document, purpose, mandatory=False):
    return SourceBinding(
        document_id=document["document_id"], revision_id=document["revision_id"], section_index=0,
        content_hash=content_hash(sections(document["content_json"])[0]), policy_version="synthetic-v1",
        purpose=purpose, mandatory=mandatory,
    )


def mock_model(monkeypatch, planner=None, generator=None, on_call=None):
    from app.whatsapp_translation import reply_service
    calls = []

    def fake_chat(db, **kwargs):
        calls.append(kwargs)
        if on_call:
            on_call(db, len(calls))
        payload = generator if generator is not None else output()
        payload = {**payload, "memory_changes": (planner or plan()).get("memory_changes", [])}
        return {"content": encode(payload), "log_id": len(calls)}

    monkeypatch.setattr(reply_service, "chat", fake_chat)
    return calls
