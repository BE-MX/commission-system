"""approval_service 审批/哈希/幂等/人类校验/撤销用例。"""

from datetime import datetime, timezone

import pytest

from app.core.time import to_beijing_naive
from app.mail_outreach import policies
from app.mail_outreach.approval_service import approve, revoke
from app.mail_outreach.errors import MailOutreachError
from app.mail_outreach.generation_service import create_human_revision
from app.mail_outreach.models import MailOutreachApproval, MailOutreachSendJob
from app.mail_outreach.schemas import ApproveRequest
from tests.mail_outreach_helpers import make_draft, make_mailbox, seed_graph

SCHEDULED_AT = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)
SCHEDULE_POLICY = {"office_start": "09:00"}


def _payload(graph, mailbox, revision, **overrides):
    params = {
        "revision_id": revision.id,
        "mailbox_binding_id": mailbox.id,
        "expected_content_sha256": revision.content_sha256,
        "schedule_policy": dict(SCHEDULE_POLICY),
        "scheduled_at_utc": SCHEDULED_AT,
        "reason": "内容已核对",
    }
    params.update(overrides)
    return ApproveRequest(**params)


def _user(graph):
    return {"sub": str(graph.user.id), "roles": [], "permissions": []}


def test_approve_creates_job_with_correct_hashes(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)

    result = approve(db, graph.access, _user(graph), message.id,
                     _payload(graph, mailbox, revision))

    assert result["idempotent_replay"] is False
    approval = db.query(MailOutreachApproval).filter_by(message_id=message.id).one()
    job = db.query(MailOutreachSendJob).filter_by(approval_id=approval.id).one()
    assert approval.decision == "approved"
    assert approval.approver_user_id == graph.user.id
    assert approval.approval_sha256 == policies.compute_approval_sha256(
        content_sha256=revision.content_sha256,
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=graph.point.id,
        to_email_snapshot="jane@acme.com",
        language_tag="en",
        schedule_policy=SCHEDULE_POLICY,
        scheduled_at_utc=SCHEDULED_AT.isoformat(),
    )
    assert job.idempotency_key == policies.job_idempotency_key(message.id, revision.id)
    assert job.status == "scheduled"
    assert job.due_at == to_beijing_naive(SCHEDULED_AT, naive_is_beijing=False)
    assert job.due_at_utc == SCHEDULED_AT.replace(tzinfo=None)
    assert result["job"]["id"] == job.id
    assert message.status == "approved"


def test_approve_rejects_content_hash_mismatch(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)

    with pytest.raises(MailOutreachError) as exc_info:
        approve(db, graph.access, _user(graph), message.id, _payload(
            graph, mailbox, revision, expected_content_sha256="0" * 64,
        ))
    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "content_hash_mismatch"
    assert db.query(MailOutreachSendJob).count() == 0


def test_double_approve_is_idempotent_with_single_job(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    payload = _payload(graph, mailbox, revision)

    first = approve(db, graph.access, _user(graph), message.id, payload)
    second = approve(db, graph.access, _user(graph), message.id, payload)

    assert second["idempotent_replay"] is True
    assert second["approval"]["id"] == first["approval"]["id"]
    assert db.query(MailOutreachApproval).filter_by(
        message_id=message.id, decision="approved",
    ).count() == 1
    assert db.query(MailOutreachSendJob).count() == 1


def test_approve_requires_active_human_user(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)

    with pytest.raises(MailOutreachError) as exc_info:
        approve(db, graph.access, {"sub": "999999"}, message.id,
                _payload(graph, mailbox, revision))
    assert exc_info.value.error_code == "approver_invalid"
    assert exc_info.value.status_code == 403

    graph.user.is_active = False
    db.flush()
    with pytest.raises(MailOutreachError):
        approve(db, graph.access, _user(graph), message.id,
                _payload(graph, mailbox, revision))


def test_approve_rechecks_eligibility(db):
    """批准时点资格复查：邮箱验证状态变差即拒绝批准。"""
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    graph.point.verification_status = "unknown"
    db.flush()

    with pytest.raises(MailOutreachError) as exc_info:
        approve(db, graph.access, _user(graph), message.id,
                _payload(graph, mailbox, revision))
    assert exc_info.value.error_code == "eligibility_failed"
    assert db.query(MailOutreachSendJob).count() == 0


def test_revoke_cancels_scheduled_job(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    approve(db, graph.access, _user(graph), message.id, _payload(graph, mailbox, revision))

    result = revoke(db, graph.access, _user(graph), message.id, "客户要求暂停")

    approval = db.query(MailOutreachApproval).filter_by(message_id=message.id).one()
    job = db.query(MailOutreachSendJob).filter_by(approval_id=approval.id).one()
    assert approval.revoked_at is not None
    assert approval.revoke_reason == "客户要求暂停"
    assert job.status == "cancelled"
    assert result["message_status"] == "cancelled"
    assert message.status == "cancelled"


def test_revoke_too_late_after_send_started(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    approve(db, graph.access, _user(graph), message.id, _payload(graph, mailbox, revision))
    job = db.query(MailOutreachSendJob).one()
    job.status = "sending"
    job.send_started_at_utc = datetime(2026, 9, 20, 0, 59)
    db.flush()

    with pytest.raises(MailOutreachError) as exc_info:
        revoke(db, graph.access, _user(graph), message.id, "太晚了")
    assert exc_info.value.error_code == "revoke_too_late"


def test_new_revision_supersedes_prior_approval(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    approve(db, graph.access, _user(graph), message.id, _payload(graph, mailbox, revision))

    result = create_human_revision(
        db, graph.access, _user(graph), message.id,
        {"subject": "Updated subject", "regenerate": False},
    )

    approval = db.query(MailOutreachApproval).filter_by(message_id=message.id).one()
    job = db.query(MailOutreachSendJob).filter_by(approval_id=approval.id).one()
    assert approval.revoked_at is not None
    assert approval.revoke_reason == "revision_superseded"
    assert job.status == "cancelled"
    assert job.cancel_note == "revision_superseded"
    assert message.status == "draft"
    assert result["current_revision"]["revision_no"] == 2
    assert result["current_revision"]["created_by_kind"] == "edit"
    assert result["current_revision"]["subject"] == "Updated subject"
    # 新 revision 必须重算内容哈希
    assert result["current_revision"]["content_sha256"] == policies.compute_content_sha256(
        subject="Updated subject", body_text=revision.body_text,
        language_tag="en", claims=[],
    )
    assert result["current_revision"]["content_sha256"] != revision.content_sha256
