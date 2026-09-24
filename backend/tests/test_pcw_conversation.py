"""PCW-03 源会话绑定与增量 AI 沟通分析服务契约测试。"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

# conftest 未导入 whatsapp / ai 模型，显式导入保证 create_all 覆盖到这些表
from app.whatsapp import models as _whatsapp_models  # noqa: F401
from app.ai import models as _ai_models  # noqa: F401

from app.core.time import beijing_now
from app.customer import pcw_conversation_service as svc
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAssignment,
    CustomerContactPoint,
    CustomerConversation,
    CustomerConversationAnalysis,
    CustomerFact,
    CustomerMessage,
    CustomerSourceRecord,
)
from app.customer.pcw_models import (
    ConversationAnalysisJob,
    ConversationBinding,
    ConversationBindingEvent,
    CustomerFactReview,
)
from app.whatsapp.models import (
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppConversation,
    WhatsAppMessage,
)
from tests.test_customer_workflow import _account, _grant_permission, _user

NOW = beijing_now().replace(microsecond=0)

READ_PERMS = ["customer:read"]
WRITE_PERMS = ["customer:write"]


def _customer_with_owner(db, *, code: str, user_id: int, grant_read: bool = True):
    account, _version = _account(db, code=code)
    owner = _user(db, user_id)
    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=owner.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=owner.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    if grant_read:
        _grant_permission(db, owner.id, "customer:read")
    db.flush()
    return account, owner


def _wa_account(db, user, uid: str, status: str = "active") -> WhatsAppAccount:
    row = WhatsAppAccount(
        account_uid=uid,
        ark_user_id=user.id,
        phone_number="+8613900000000",
        display_name=f"WA {uid}",
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _wa_conversation(
    db,
    account_uid: str,
    conversation_uid: str,
    *,
    phone: str | None = None,
    name: str | None = None,
    is_group: bool = False,
) -> WhatsAppConversation:
    row = WhatsAppConversation(
        conversation_uid=conversation_uid,
        account_uid=account_uid,
        chat_id=f"chat-{conversation_uid}",
        contact_phone=phone,
        contact_name=name,
        is_group=is_group,
        last_message_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _wa_message(
    db,
    account_uid: str,
    conversation_uid: str,
    n: int,
    *,
    direction: str = "in",
    text: str | None = None,
    sent_at=None,
    content_type: str = "text",
) -> WhatsAppMessage:
    row = WhatsAppMessage(
        message_uid=f"msg-{conversation_uid}-{n}",
        account_uid=account_uid,
        conversation_uid=conversation_uid,
        external_message_id=f"ext-{conversation_uid}-{n}",
        direction=direction,
        sender_phone="+8613800138000" if direction in ("in", "inbound") else None,
        content_type=content_type,
        content_text=text if text is not None else f"消息{n}",
        sent_at=sent_at if sent_at is not None else NOW - timedelta(minutes=100 - n),
    )
    db.add(row)
    db.flush()
    return row


def _phone_point(db, customer_id: int, normalized: str, *, status: str = "valid"):
    point = CustomerContactPoint(
        customer_id=customer_id,
        point_type="phone",
        raw_value=normalized,
        normalized_value=normalized,
        verification_status=status,
        contactability_status="allowed",
        is_primary=True,
        data_classification="internal_business",
        point_fingerprint=f"{customer_id:064x}",
        first_seen_at=NOW,
        last_seen_at=NOW,
        verified_at=NOW,
    )
    db.add(point)
    db.flush()
    return point


def _bind(db, owner, account_uid: str, conversation_uid: str, customer_id: int, **kw):
    params = dict(
        actor_user_id=owner.id,
        actor_permissions=WRITE_PERMS,
        source_system="whatsapp",
        source_account_key=account_uid,
        source_conversation_id=conversation_uid,
        customer_id=customer_id,
        evidence_refs=[{"type": "verified_contact_point", "id": 1}],
    )
    params.update(kw)
    return svc.create_binding(db, **params)


def _bound_conversation(db, *, tag: str, customer_id: int, owner, message_count: int = 3):
    account = _wa_account(db, owner, f"acc-{tag}")
    _wa_conversation(db, account.account_uid, f"conv-{tag}")
    for n in range(message_count):
        _wa_message(
            db,
            account.account_uid,
            f"conv-{tag}",
            n,
            direction="in" if n % 2 == 0 else "out",
        )
    result = _bind(db, owner, account.account_uid, f"conv-{tag}", customer_id)
    return account, result


def _enable_ai(monkeypatch, *, enabled: bool = True):
    monkeypatch.setattr(
        svc,
        "get_settings",
        lambda: SimpleNamespace(
            PCW_AI_ANALYSIS_ENABLED=enabled, PCW_AI_TIMEOUT_SECONDS=30
        ),
    )


def _ok_payload(message_ids, *, with_fact: bool = False):
    first = message_ids[0]
    candidate = {"text": "客户偏好自然黑色", "evidence_message_ids": [first]}
    if with_fact:
        candidate["fact_key"] = "preference.expressed.color"
        candidate["value"] = "natural black"
    return {
        "summary": "客户询价发束产品",
        "demands": [
            {"text": "需要 20inch 发束", "evidence_message_ids": [first]},
            {"text": "越界引用应被剔除", "evidence_message_ids": [999999]},
        ],
        "objections": [],
        "commitments": [],
        "open_questions": [],
        "next_steps": [],
        "profile_candidates": [candidate],
    }


# ── A. 待绑定队列 ────────────────────────────────────────────


def test_pending_bindings_scope_and_candidates(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-PEND", user_id=9201)
    _phone_point(db, customer.id, "+8613800138000")
    # 同名但无已核验联系方式的客户绝不进入候选
    same_name, _v = _account(db, code="Alice")

    own = _wa_account(db, owner, "acc-own")
    _wa_conversation(
        db, own.account_uid, "conv-own", phone="+86 138 0013 8000", name="Alice"
    )
    other_user = _user(db, 9202)
    other = _wa_account(db, other_user, "acc-other")
    _wa_conversation(db, other.account_uid, "conv-other", phone="+8613899999999")

    mine = svc.list_pending_bindings(
        db, actor_user_id=owner.id, actor_permissions=READ_PERMS
    )
    assert mine["total"] == 1
    item = mine["items"][0]
    assert item["source_conversation_id"] == "conv-own"
    candidate_ids = [c["customer_id"] for c in item["candidate_customers"]]
    assert candidate_ids == [customer.id]
    assert same_name.id not in candidate_ids

    admin = _user(db, 9203)
    _grant_permission(db, admin.id, "customer:read_all")
    admin_view = svc.list_pending_bindings(
        db, actor_user_id=admin.id, actor_permissions=["customer:read_all"]
    )
    assert admin_view["total"] == 2


def test_pending_queue_excludes_bound_conversation(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-BOUNDQ", user_id=9211)
    _bound_conversation(db, tag="boundq", customer_id=customer.id, owner=owner)
    queue = svc.list_pending_bindings(
        db, actor_user_id=owner.id, actor_permissions=READ_PERMS
    )
    assert queue["total"] == 0


# ── B. 绑定与投影 ────────────────────────────────────────────


def test_bind_projects_messages_and_idempotent_replay(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-BIND", user_id=9221)
    account = _wa_account(db, owner, "acc-bind")
    _wa_conversation(db, account.account_uid, "conv-bind")
    _wa_message(db, account.account_uid, "conv-bind", 0, direction="in")
    _wa_message(db, account.account_uid, "conv-bind", 1, direction="out")
    _wa_message(db, account.account_uid, "conv-bind", 2, direction="outbound")

    result = _bind(
        db, owner, account.account_uid, "conv-bind", customer.id,
        idempotency_key="bind-key-0000000001",
    )
    assert result["version"] == 1
    assert result["state"] == "active"
    assert result["reused"] is False
    assert result["replayed"] is False
    assert result["projected_message_count"] == 3

    messages = db.query(CustomerMessage).filter_by(
        conversation_id=result["projected_conversation_id"]
    ).all()
    assert len(messages) == 3
    assert {m.direction for m in messages} == {"in", "out"}  # outbound 归一为 out
    assert all(m.source_record_id is not None for m in messages)
    sources = db.query(CustomerSourceRecord).filter_by(
        source_system="whatsapp", source_entity_type="message"
    ).all()
    assert len(sources) == 3
    assert all(s.customer_id == customer.id for s in sources)
    assert all(s.processing_status == "processed" for s in sources)

    replay = _bind(
        db, owner, account.account_uid, "conv-bind", customer.id,
        idempotency_key="bind-key-0000000001",
    )
    assert replay["replayed"] is True
    assert replay["binding_id"] == result["binding_id"]

    repeat = _bind(
        db, owner, account.account_uid, "conv-bind", customer.id,
        idempotency_key="bind-key-0000000002",
    )
    assert repeat["reused"] is True
    assert (
        db.query(CustomerMessage)
        .filter_by(conversation_id=result["projected_conversation_id"])
        .count()
        == 3
    )


def test_bind_conflict_when_bound_to_other_customer(db):
    customer_a, owner = _customer_with_owner(db, code="C-PCW-CFA", user_id=9231)
    customer_b, _vb = _account(db, code="C-PCW-CFB")
    db.add(CustomerAssignment(
        customer_id=customer_b.id,
        user_id=owner.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=owner.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    account = _wa_account(db, owner, "acc-cf")
    _wa_conversation(db, account.account_uid, "conv-cf")
    _wa_message(db, account.account_uid, "conv-cf", 0)
    _bind(db, owner, account.account_uid, "conv-cf", customer_a.id)

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _bind(db, owner, account.account_uid, "conv-cf", customer_b.id)
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "BINDING_CONFLICT"
    assert excinfo.value.details["rebind_required"] is True


def test_bind_requires_evidence(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-NOEV", user_id=9241)
    account = _wa_account(db, owner, "acc-noev")
    _wa_conversation(db, account.account_uid, "conv-noev")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _bind(
            db, owner, account.account_uid, "conv-noev", customer.id,
            evidence_refs=[],
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "BINDING_EVIDENCE_REQUIRED"


def test_bind_expected_version_conflict(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-VER", user_id=9251)
    account = _wa_account(db, owner, "acc-ver")
    _wa_conversation(db, account.account_uid, "conv-ver")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _bind(
            db, owner, account.account_uid, "conv-ver", customer.id,
            expected_binding_version=3,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "BINDING_VERSION_CONFLICT"


def test_bind_rejects_unknown_message_direction(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-DIR", user_id=9261)
    account = _wa_account(db, owner, "acc-dir")
    _wa_conversation(db, account.account_uid, "conv-dir")
    _wa_message(db, account.account_uid, "conv-dir", 0, direction="sideways")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _bind(db, owner, account.account_uid, "conv-dir", customer.id)
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "MESSAGE_DIRECTION_INVALID"


def test_source_account_not_owned_is_404(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-NOWN", user_id=9271)
    stranger = _user(db, 9272)
    account = _wa_account(db, stranger, "acc-stranger")
    _wa_conversation(db, account.account_uid, "conv-stranger")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _bind(db, owner, account.account_uid, "conv-stranger", customer.id)
    assert excinfo.value.status_code == 404
    assert excinfo.value.error_code == "SOURCE_NOT_FOUND_OR_FORBIDDEN"


# ── C. 重绑 / 解绑治理 ────────────────────────────────────────


def _succeeded_job_with_fact(db, monkeypatch, customer, owner, tag="rebind"):
    _enable_ai(monkeypatch)
    account, binding = _bound_conversation(
        db, tag=tag, customer_id=customer.id, owner=owner
    )

    def chat_fn(*, messages, timeout_sec):
        ids = [
            row.id
            for row in db.query(CustomerMessage).filter_by(
                conversation_id=binding["projected_conversation_id"]
            )
        ]
        return {"content": json.dumps(_ok_payload(ids, with_fact=True))}

    job_result = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
        run_inline=True,
        chat_fn=chat_fn,
    )
    assert job_result["status"] == "succeeded"
    return account, binding, job_result


def test_rebind_stales_derivations_and_transfers_ownership(db, monkeypatch):
    customer_a, owner = _customer_with_owner(db, code="C-PCW-RBA", user_id=9281)
    customer_b, _vb = _account(db, code="C-PCW-RBB")
    _account_owner_b = _user(db, 9282)
    db.add(CustomerAssignment(
        customer_id=customer_b.id,
        user_id=9282,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=9282,
        created_at=NOW,
        updated_at=NOW,
    ))
    _grant_permission(db, 9282, "customer:read")
    db.flush()

    _wa_acct, binding, job_result = _succeeded_job_with_fact(
        db, monkeypatch, customer_a, owner
    )
    # 分析成功已落地：分析版本行 + 候选事实 + 待审建议
    analysis_id = job_result["result_analysis_id"]
    assert analysis_id is not None
    fact = db.query(CustomerFact).filter_by(
        customer_id=customer_a.id, fact_key="preference.expressed.color"
    ).one()
    assert fact.fact_layer == "expressed"
    assert fact.verification_status == "candidate"
    review = db.query(CustomerFactReview).filter_by(
        candidate_fact_id=fact.id
    ).one()
    assert review.status == "pending"

    outcome = svc.rebind(
        db,
        binding_id=binding["binding_id"],
        actor_user_id=owner.id,
        can_manage=True,
        new_customer_id=customer_b.id,
        reason="绑定到错误客户，更正归属",
    )
    assert outcome["version"] == 2
    assert outcome["customer_id"] == customer_b.id
    assert outcome["staled_analysis_jobs"] == 1
    assert outcome["staled_suggestions"] == 1

    event = (
        db.query(ConversationBindingEvent)
        .filter_by(binding_id=binding["binding_id"], event_type="rebound")
        .one()
    )
    assert event.before_customer_id == customer_a.id
    assert event.after_customer_id == customer_b.id
    assert event.binding_version == 2

    job = db.get(ConversationAnalysisJob, job_result["id"])
    assert job.status == "stale"
    assert review.status == "stale"

    conversation = db.get(
        CustomerConversation, binding["projected_conversation_id"]
    )
    assert conversation.customer_id == customer_b.id
    moved_sources = db.query(CustomerSourceRecord).filter_by(
        source_system="whatsapp", source_entity_type="message"
    ).all()
    assert moved_sources
    assert all(s.customer_id == customer_b.id for s in moved_sources)

    # 旧客户读侧不再可见；新客户可见
    old_view = svc.list_conversations(
        db, customer_id=customer_a.id, actor_user_id=owner.id
    )
    assert old_view["total"] == 0
    new_view = svc.list_conversations(
        db, customer_id=customer_b.id, actor_user_id=9282
    )
    assert new_view["total"] == 1
    assert new_view["items"][0]["binding_version"] == 2


def test_rebind_requires_governance_permission(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-NOGOV", user_id=9291)
    other, _v = _account(db, code="C-PCW-NOGOV2")
    _acct, binding = _bound_conversation(
        db, tag="nogov", customer_id=customer.id, owner=owner
    )
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        svc.rebind(
            db,
            binding_id=binding["binding_id"],
            actor_user_id=owner.id,
            can_manage=False,
            new_customer_id=other.id,
            reason="无权限也应被拒绝",
        )
    assert excinfo.value.status_code == 403
    assert excinfo.value.error_code == "BINDING_GOVERNANCE_REQUIRED"

    with pytest.raises(pcw_errors.PcwError) as excinfo2:
        svc.unbind(
            db,
            binding_id=binding["binding_id"],
            actor_user_id=owner.id,
            can_manage=True,
            reason="",
        )
    assert excinfo2.value.status_code == 400
    assert excinfo2.value.error_code == "BINDING_REASON_REQUIRED"


def test_unbind_then_reads_404_and_create_binding_blocked(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-UNB", user_id=9301)
    account, binding = _bound_conversation(
        db, tag="unb", customer_id=customer.id, owner=owner
    )
    job = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    outcome = svc.unbind(
        db,
        binding_id=binding["binding_id"],
        actor_user_id=owner.id,
        can_manage=True,
        reason="会话不再归属该客户",
        idempotency_key="unbind-key-000000001",
    )
    assert outcome["state"] == "unbound"
    assert outcome["customer_id"] is None

    replay = svc.unbind(
        db,
        binding_id=binding["binding_id"],
        actor_user_id=owner.id,
        can_manage=True,
        reason="会话不再归属该客户",
        idempotency_key="unbind-key-000000001",
    )
    # 已是 unbound 的重复解绑走无操作早退（不重复写回执），reused 标记幂等
    assert replay["reused"] is True
    assert replay["state"] == "unbound"

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        svc.list_messages(
            db,
            conversation_id=binding["projected_conversation_id"],
            actor_user_id=owner.id,
            actor_permissions=READ_PERMS,
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.error_code == "CONVERSATION_NOT_FOUND_OR_FORBIDDEN"

    with pytest.raises(pcw_errors.PcwError) as excinfo2:
        svc.get_analysis_job(
            db,
            job_id=job["job_id"],
            actor_user_id=owner.id,
            actor_permissions=READ_PERMS,
        )
    assert excinfo2.value.status_code == 404
    assert excinfo2.value.error_code == "ANALYSIS_JOB_NOT_FOUND"

    # 已解绑会话重新绑定必须走重绑治理
    with pytest.raises(pcw_errors.PcwError) as excinfo3:
        _bind(db, owner, account.account_uid, "conv-unb", customer.id)
    assert excinfo3.value.status_code == 409
    assert excinfo3.value.error_code == "BINDING_CONFLICT"
    assert excinfo3.value.details["rebind_required"] is True


def test_revoked_source_account_forbids_reads(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-REVK", user_id=9311)
    account, binding = _bound_conversation(
        db, tag="revk", customer_id=customer.id, owner=owner
    )
    account.status = "revoked"
    db.flush()
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        svc.list_messages(
            db,
            conversation_id=binding["projected_conversation_id"],
            actor_user_id=owner.id,
            actor_permissions=READ_PERMS,
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.error_code == "SOURCE_NOT_FOUND_OR_FORBIDDEN"


# ── D. 会话与消息读模型 ───────────────────────────────────────


def test_list_conversations_for_customer(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-LIST", user_id=9321)
    _bound_conversation(db, tag="list1", customer_id=customer.id, owner=owner)
    _bound_conversation(db, tag="list2", customer_id=customer.id, owner=owner)
    result = svc.list_conversations(
        db, customer_id=customer.id, actor_user_id=owner.id
    )
    assert result["total"] == 2
    item = result["items"][0]
    assert item["channel"] == "whatsapp"
    assert item["message_count"] == 3
    assert item["binding_version"] == 1


def test_message_cursor_pagination_with_ties(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-PAGE", user_id=9331)
    account = _wa_account(db, owner, "acc-page")
    _wa_conversation(db, account.account_uid, "conv-page")
    base = NOW - timedelta(hours=1)
    # 25 条：前 5 条同一 sent_at（验证 id 破平局），其余逐分钟递增；乱序写入
    for n in range(24, 4, -1):
        _wa_message(db, account.account_uid, "conv-page", n, sent_at=base + timedelta(minutes=n))
    for n in range(5):
        _wa_message(db, account.account_uid, "conv-page", n, sent_at=base)
    _bind(db, owner, account.account_uid, "conv-page", customer.id)
    binding = db.query(ConversationBinding).filter_by(
        source_conversation_id="conv-page"
    ).one()

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        page = svc.list_messages(
            db,
            conversation_id=binding.projected_conversation_id,
            actor_user_id=owner.id,
            actor_permissions=READ_PERMS,
            cursor=cursor,
            limit=10,
        )
        pages += 1
        seen.extend(item["message_id"] for item in page["items"])
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"]
        cursor = page["next_cursor"]
    assert pages == 3
    assert len(seen) == 25
    assert len(set(seen)) == 25  # 无重叠无遗漏

    rows = (
        db.query(CustomerMessage)
        .filter_by(conversation_id=binding.projected_conversation_id)
        .order_by(CustomerMessage.sent_at.asc(), CustomerMessage.id.asc())
        .all()
    )
    assert seen == [row.id for row in rows]  # 严格 (sent_at, id) 升序
    assert len({row.sent_at for row in rows[:5]}) == 1  # 平局组

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        svc.list_messages(
            db,
            conversation_id=binding.projected_conversation_id,
            actor_user_id=owner.id,
            actor_permissions=READ_PERMS,
            cursor="not-a-cursor",
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "MESSAGE_CURSOR_INVALID"


def test_message_attachments_marked_unread(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-ATT", user_id=9341)
    account = _wa_account(db, owner, "acc-att")
    _wa_conversation(db, account.account_uid, "conv-att")
    text_msg = _wa_message(db, account.account_uid, "conv-att", 0)
    image_msg = _wa_message(
        db, account.account_uid, "conv-att", 1, content_type="image", text=""
    )
    db.add(WhatsAppAttachment(
        message_uid=image_msg.message_uid,
        file_name="photo.jpg",
        mime_type="image/jpeg",
        file_size=12345,
        storage_url="s3://bucket/photo.jpg",
    ))
    db.flush()
    assert text_msg is not None
    binding = _bind(db, owner, account.account_uid, "conv-att", customer.id)

    page = svc.list_messages(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    flags = {item["content_type"]: item["attachments_unread"] for item in page["items"]}
    assert flags == {"text": False, "image": True}

    job = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    coverage = job["coverage"]
    assert coverage["schema_version"] == "pcw_analysis_coverage_v1"
    assert coverage["attachments_unread"] == 1
    assert coverage["message_count"] == 2
    assert coverage["sync_from"] is not None and coverage["sync_to"] is not None


# ── E/F. 分析任务创建与执行 ────────────────────────────────────


def test_analysis_job_reuses_unique_key(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-REUSE", user_id=9351)
    _acct, binding = _bound_conversation(
        db, tag="reuse", customer_id=customer.id, owner=owner
    )
    first = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    assert first["status"] == "queued"
    assert first["reused"] is False
    second = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    assert second["reused"] is True
    assert second["id"] == first["id"]
    assert (
        db.query(ConversationAnalysisJob)
        .filter_by(conversation_id=binding["projected_conversation_id"])
        .count()
        == 1
    )


def test_analysis_job_requires_binding(db):
    customer, owner = _customer_with_owner(db, code="C-PCW-NOBIND", user_id=9361)
    conversation = CustomerConversation(
        customer_id=customer.id,
        source_system="whatsapp",
        source_account_key="acc-nobind",
        external_conversation_id="conv-nobind",
        channel="whatsapp",
        owner_user_id=owner.id,
        conversation_status="active",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(conversation)
    db.flush()
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        svc.create_analysis_job(
            db,
            conversation_id=conversation.id,
            actor_user_id=owner.id,
            actor_permissions=READ_PERMS,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "BINDING_REQUIRED"


def test_run_analysis_success_writes_versioned_analysis(db, monkeypatch):
    customer, owner = _customer_with_owner(db, code="C-PCW-RUNOK", user_id=9371)
    _enable_ai(monkeypatch)
    _acct, binding = _bound_conversation(
        db, tag="runok", customer_id=customer.id, owner=owner
    )
    captured: dict = {}

    def chat_fn(*, messages, timeout_sec):
        captured["messages"] = messages
        captured["timeout_sec"] = timeout_sec
        ids = [
            row.id
            for row in db.query(CustomerMessage).filter_by(
                conversation_id=binding["projected_conversation_id"]
            )
        ]
        return {"content": json.dumps(_ok_payload(ids), ensure_ascii=False)}

    result = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
        run_inline=True,
        chat_fn=chat_fn,
    )
    assert result["status"] == "succeeded"
    assert result["analysis_version"] == 1
    assert captured["timeout_sec"] == 30
    # 输入是已授权消息清单，提示词中带事实键目录
    assert len(captured["messages"]) == 1
    assert "preference.expressed.color" in captured["messages"][0]["content"]

    job = db.get(ConversationAnalysisJob, result["id"])
    analysis = db.get(CustomerConversationAnalysis, job.result_analysis_id)
    assert analysis is not None
    assert analysis.version_no == 1
    assert analysis.analysis_schema_version == "pcw_conversation_summary_v1"
    assert analysis.canonicalization_version == "jcs_v1"
    assert analysis.analysis_rule_version == "pcw_conversation_analysis_v1"
    assert str(analysis.confidence) == "0.0000"
    assert analysis.data_classification == "restricted_internal"
    assert analysis.summary == "客户询价发束产品"

    message_ids = [
        row.id
        for row in db.query(CustomerMessage).filter_by(
            conversation_id=binding["projected_conversation_id"]
        )
    ]
    assert analysis.window_start_message_id == min(message_ids)
    assert analysis.window_end_message_id == max(message_ids)
    # 越界证据引用被剔除并计数；有效引用保留
    assert analysis.analysis_json["meta"]["dropped_evidence_refs"] == 1
    assert analysis.analysis_json["demands"][0]["evidence_message_ids"] == [
        message_ids[0]
    ]
    assert analysis.analysis_json["demands"][1]["evidence_message_ids"] == []
    assert set(analysis.evidence_message_ids) <= set(message_ids)
    assert len(analysis.analysis_fingerprint) == 64

    # 幂等：succeeded 任务重复执行直接返回
    again = svc.run_analysis_job(db, job_id=job.id, chat_fn=chat_fn)
    assert again.status == "succeeded"


def test_run_analysis_chat_failures(db, monkeypatch):
    customer, owner = _customer_with_owner(db, code="C-PCW-RUNERR", user_id=9381)
    _enable_ai(monkeypatch)

    def make_job(tag):
        _acct, binding = _bound_conversation(
            db, tag=tag, customer_id=customer.id, owner=owner, message_count=1
        )
        created = svc.create_analysis_job(
            db,
            conversation_id=binding["projected_conversation_id"],
            actor_user_id=owner.id,
            actor_permissions=READ_PERMS,
        )
        return created["id"]

    def timeout_fn(*, messages, timeout_sec):
        raise TimeoutError("read timed out")

    job_timeout = svc.run_analysis_job(db, job_id=make_job("err-timeout"), chat_fn=timeout_fn)
    assert job_timeout.status == "failed"
    assert job_timeout.failure_reason == "AI_TIMEOUT"

    def bad_json_fn(*, messages, timeout_sec):
        return {"content": "抱歉，我无法输出 JSON"}

    job_bad = svc.run_analysis_job(db, job_id=make_job("err-badjson"), chat_fn=bad_json_fn)
    assert job_bad.status == "failed"
    assert job_bad.failure_reason == "AI_INVALID_OUTPUT"

    def missing_preset_fn(*, messages, timeout_sec):
        raise ValueError("Preset 'pcw_conversation_summary' not configured")

    job_preset = svc.run_analysis_job(db, job_id=make_job("err-preset"), chat_fn=missing_preset_fn)
    assert job_preset.status == "failed"
    assert job_preset.failure_reason == "AI_PRESET_MISSING"

    # 失败任务不静默吞错：可再次创建同输入任务时复用既有失败记录
    reused = svc.create_analysis_job(
        db,
        conversation_id=db.get(ConversationAnalysisJob, job_timeout.id).conversation_id,
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    assert reused["reused"] is True
    assert reused["status"] == "failed"


def test_run_analysis_disabled_by_settings(db, monkeypatch):
    customer, owner = _customer_with_owner(db, code="C-PCW-AIDIS", user_id=9391)
    _enable_ai(monkeypatch, enabled=False)
    _acct, binding = _bound_conversation(
        db, tag="aidis", customer_id=customer.id, owner=owner, message_count=1
    )
    created = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    job = svc.run_analysis_job(db, job_id=created["id"], chat_fn=None)
    assert job.status == "failed"
    assert job.failure_reason == "AI_ANALYSIS_DISABLED"


def test_run_analysis_binding_version_drift_marks_stale(db, monkeypatch):
    customer, owner = _customer_with_owner(db, code="C-PCW-DRIFT", user_id=9401)
    _enable_ai(monkeypatch)
    _acct, binding = _bound_conversation(
        db, tag="drift", customer_id=customer.id, owner=owner, message_count=1
    )
    created = svc.create_analysis_job(
        db,
        conversation_id=binding["projected_conversation_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    other, _v = _account(db, code="C-PCW-DRIFT2")
    svc.rebind(
        db,
        binding_id=binding["binding_id"],
        actor_user_id=owner.id,
        can_manage=True,
        new_customer_id=other.id,
        reason="归属更正使旧任务失效",
    )
    job = svc.run_analysis_job(db, job_id=created["id"], chat_fn=None)
    assert job.status == "stale"


def test_get_analysis_job_returns_coverage_and_result(db, monkeypatch):
    customer, owner = _customer_with_owner(db, code="C-PCW-GETJOB", user_id=9411)
    _acct, binding, job_result = _succeeded_job_with_fact(
        db, monkeypatch, customer, owner, tag="getjob"
    )
    view = svc.get_analysis_job(
        db,
        job_id=job_result["job_id"],
        actor_user_id=owner.id,
        actor_permissions=READ_PERMS,
    )
    assert view["status"] == "succeeded"
    assert view["result_analysis_id"] is not None
    assert view["coverage"]["message_count"] == 3
    assert view["finished_at"] is not None
    assert view["rule_version"] == "pcw_conversation_analysis_v1"

    stranger = _user(db, 9412)
    _grant_permission(db, stranger.id, "customer:read")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        svc.get_analysis_job(
            db,
            job_id=job_result["job_id"],
            actor_user_id=stranger.id,
            actor_permissions=READ_PERMS,
        )
    assert excinfo.value.status_code == 404
