"""Single-use authorization, live access, durable results, and inbox suppression."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.models import ArkRole
from app.core.config import get_settings
from app.customer.models import CustomerEvent
from app.mail_outreach import approval_service, event_service, worker_service
from app.mail_outreach.errors import MailOutreachError
from app.mail_outreach.models import MailEvent, MailOutreachSendAttempt, MailOutreachSendJob
from app.mail_outreach.schemas import ApproveRequest
from app.mail_outreach.worker_auth import require_mail_worker
from app.mail_outreach.worker_schemas import ClassifyRequest, EventsRequest, HeartbeatRequest, ResultRequest
from tests.mail_outreach_helpers import make_draft, make_mailbox, seed_graph


def prepared(db, monkeypatch, *, internal_test=False):
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_SEND_ENABLED", True)
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_ALLOWED_RECIPIENTS", "jane@acme.com")
    graph = seed_graph(db)
    graph.user.roles.append(ArkRole(name="super_admin", label="Admin"))
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    revision.evidence_snapshot_json = {"profile_version_id": graph.profile.id,
        "contact_point_id": graph.point.id, "email": graph.point.normalized_value,
        "fact_fingerprints": [{"fact_id": graph.fact.id, "fact_fingerprint": graph.fact.fact_fingerprint}]}
    if internal_test:
        from app.mail_outreach.policies import compute_content_sha256
        revision.subject = "[ARK INTERNAL TEST] Mail check"
        revision.claims_json = []
        revision.evidence_snapshot_json = {**revision.evidence_snapshot_json, "internal_test": True}
        revision.content_sha256 = compute_content_sha256(subject=revision.subject,
            body_text=revision.body_text, language_tag=revision.language_tag, claims=[])
        db.commit()
    user = {"sub": str(graph.user.id), "roles": ["super_admin"], "permissions": []}
    approved = approval_service.approve(db, graph.access, user, message.id, ApproveRequest(
        revision_id=revision.id, mailbox_binding_id=mailbox.id,
        expected_content_sha256=revision.content_sha256,
        scheduled_at_utc=datetime.now(timezone.utc) - timedelta(seconds=1)))
    worker_service.heartbeat(db, "worker-1", mailbox.id,
        HeartbeatRequest(sender_email=mailbox.sender_email, auth_status="active"))
    job = db.get(MailOutreachSendJob, approved["job"]["id"])
    return graph, mailbox, message, revision, job, user


def test_internal_test_delivery_does_not_record_customer_touch(db, monkeypatch):
    graph, mailbox, _, revision, job, user = prepared(db, monkeypatch, internal_test=True)
    claimed = worker_service.claim(db, "worker-1", mailbox.id)
    worker_service.authorize(db, "worker-1", job.id, claimed["fencing_token"])
    worker_service.record_result(db, "worker-1", job.id,
        ResultRequest(fencing_token=claimed["fencing_token"], outcome="accepted"))
    assert job.status == "provider_accepted"
    assert db.query(CustomerEvent).filter_by(event_type="outreach.accepted").count() == 0
    payload = EventsRequest(events=[dict(provider_message_id="internal-reply",
        from_address="jane@acme.com", to_address=mailbox.sender_email,
        subject="Re: " + revision.subject, received_at_utc=datetime.now(timezone.utc))])
    assert event_service.ingest(db, "worker-1", mailbox.id, payload)["inserted"] == 1
    event = db.query(MailEvent).one()
    event_service.classify(db, event.id, user, ClassifyRequest(classification="human_reply", reason="Internal acceptance reply"))
    assert event.processed_status == "processed"
    assert db.query(CustomerEvent).filter_by(event_type="outreach.classified").count() == 0


def test_internal_test_cannot_use_wildcard_at_send_time(db, monkeypatch):
    _, mailbox, _, _, job, _ = prepared(db, monkeypatch, internal_test=True)
    claimed = worker_service.claim(db, "worker-1", mailbox.id)
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_ALLOWED_RECIPIENTS", "*")
    with pytest.raises(MailOutreachError):
        worker_service.authorize(db, "worker-1", job.id, claimed["fencing_token"])
    assert job.status == "needs_review"
    assert "internal_test_recipient_forbidden" in job.last_precheck_json["reasons"]


def test_single_use_authorization_result_replay_and_timeline(db, monkeypatch):
    graph, mailbox, message, revision, job, user = prepared(db, monkeypatch)
    claimed = worker_service.claim(db, "worker-1", mailbox.id)
    assert claimed["id"] == job.id
    data = worker_service.authorize(db, "worker-1", job.id, claimed["fencing_token"])
    assert data == {"to": "jane@acme.com", "subject": revision.subject, "body_text": revision.body_text}
    with pytest.raises(MailOutreachError, match="授权已使用"):
        worker_service.authorize(db, "worker-1", job.id, claimed["fencing_token"])
    payload = ResultRequest(fencing_token=claimed["fencing_token"], outcome="accepted")
    worker_service.record_result(db, "worker-1", job.id, payload)
    worker_service.record_result(db, "worker-1", job.id, payload)
    assert db.query(MailOutreachSendAttempt).count() == 1
    assert db.query(CustomerEvent).filter_by(event_type="outreach.accepted").count() == 1
    assert job.status == "provider_accepted"
    assert worker_service.claim(db, "worker-1", mailbox.id) is None


@pytest.mark.parametrize("mutation,reason", [
    ("optout", "contactability"), ("disabled", "send_disabled"),
    ("permission", "approver_permission_revoked"), ("allowlist", "recipient_not_enabled"),
    ("content", "approved_content_changed"), ("profile", "evidence_changed"),
])
def test_live_precheck_blocks_stale_approvals(db, monkeypatch, mutation, reason):
    graph, mailbox, message, revision, job, user = prepared(db, monkeypatch)
    claimed = worker_service.claim(db, "worker-1", mailbox.id)
    if mutation == "optout": graph.point.contactability_status = "opted_out"
    if mutation == "disabled": monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_SEND_ENABLED", False)
    if mutation == "permission": graph.user.is_active = False
    if mutation == "allowlist": monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_ALLOWED_RECIPIENTS", "")
    if mutation == "content": revision.body_text += " changed"
    if mutation == "profile": graph.customer.current_profile_version_id = None
    db.commit()
    with pytest.raises(MailOutreachError):
        worker_service.authorize(db, "worker-1", job.id, claimed["fencing_token"])
    assert reason in job.last_precheck_json["reasons"]
    assert job.status == "needs_review"
    assert job.send_started_at_utc is None


def test_crashed_sender_never_reclaimed_and_late_result_recovers(db, monkeypatch):
    _, mailbox, _, _, job, _ = prepared(db, monkeypatch)
    claim = worker_service.claim(db, "worker-1", mailbox.id)
    worker_service.authorize(db, "worker-1", job.id, claim["fencing_token"])
    job.lease_until_utc = worker_service.utc_now() - timedelta(seconds=1)
    db.commit()
    assert worker_service.claim(db, "worker-1", mailbox.id) is None
    db.refresh(job)
    assert job.status == "ambiguous"
    worker_service.record_result(db, "worker-1", job.id, ResultRequest(fencing_token=claim["fencing_token"], outcome="accepted"))
    assert job.status == "provider_accepted"


def test_expired_claim_can_recover_but_old_fence_cannot_send(db, monkeypatch):
    _, mailbox, _, _, job, _ = prepared(db, monkeypatch)
    first = worker_service.claim(db, "worker-1", mailbox.id)
    job.lease_until_utc = worker_service.utc_now() - timedelta(seconds=1)
    db.commit()
    second = worker_service.claim(db, "worker-1", mailbox.id)
    assert second["fencing_token"] == first["fencing_token"] + 1
    with pytest.raises(MailOutreachError):
        worker_service.authorize(db, "worker-1", job.id, first["fencing_token"])


def test_mailbox_identity_and_token_isolation(db, monkeypatch):
    _, mailbox, _, _, job, _ = prepared(db, monkeypatch)
    with pytest.raises(MailOutreachError): worker_service.claim(db, "wrong-worker", mailbox.id)
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_WORKER_TOKENS_JSON",
        json.dumps({"worker-1": hashlib.sha256(b"dedicated-token").hexdigest()}))
    assert require_mail_worker(HTTPAuthorizationCredentials(scheme="Bearer", credentials="dedicated-token")) == "worker-1"
    with pytest.raises(HTTPException):
        require_mail_worker(HTTPAuthorizationCredentials(scheme="Bearer", credentials="human-jwt"))


def test_inbox_dedup_human_optout_stops_future_contacts(db, monkeypatch):
    graph, mailbox, _, revision, job, user = prepared(db, monkeypatch)
    claim = worker_service.claim(db, "worker-1", mailbox.id)
    worker_service.authorize(db, "worker-1", job.id, claim["fencing_token"])
    worker_service.record_result(db, "worker-1", job.id, ResultRequest(fencing_token=claim["fencing_token"], outcome="accepted"))
    payload = EventsRequest(events=[dict(provider_message_id="inbox-1", from_address="jane@acme.com",
        to_address=mailbox.sender_email, subject="Re: " + revision.subject,
        received_at_utc=datetime.now(timezone.utc))])
    assert event_service.ingest(db, "worker-1", mailbox.id, payload)["inserted"] == 1
    assert event_service.ingest(db, "worker-1", mailbox.id, payload)["inserted"] == 0
    event = db.query(MailEvent).one()
    assert event.classification == "uncertain"
    event_service.classify(db, event.id, user, ClassifyRequest(classification="opt_out", reason="用户明确退订"))
    assert graph.point.contactability_status == "opted_out"
    assert db.query(CustomerEvent).filter_by(event_type="outreach.classified").count() == 1


@pytest.mark.parametrize("outcome,expected", [("failed_safe", "failed_safe"), ("unknown", "ambiguous")])
def test_pre_authorization_failure_can_acknowledge_durable_journal(db, monkeypatch, outcome, expected):
    _, mailbox, _, _, job, _ = prepared(db, monkeypatch)
    claim = worker_service.claim(db, "worker-1", mailbox.id)
    payload = ResultRequest(fencing_token=claim["fencing_token"], outcome=outcome)
    worker_service.record_result(db, "worker-1", job.id, payload)
    worker_service.record_result(db, "worker-1", job.id, payload)
    assert job.status == expected
    assert db.query(MailOutreachSendAttempt).count() == 1


def test_precheck_rejection_ack_preserves_reason(db, monkeypatch):
    graph, mailbox, _, _, job, _ = prepared(db, monkeypatch)
    claim = worker_service.claim(db, "worker-1", mailbox.id)
    graph.point.contactability_status = "opted_out"
    db.commit()
    with pytest.raises(MailOutreachError):
        worker_service.authorize(db, "worker-1", job.id, claim["fencing_token"])
    worker_service.record_result(db, "worker-1", job.id,
        ResultRequest(fencing_token=claim["fencing_token"], outcome="failed_safe"))
    assert job.status == "needs_review"
    assert "contactability" in job.blocked_reason


def test_inbox_classification_does_not_cancel_authorized_send(db, monkeypatch):
    graph, mailbox, message, revision, job, user = prepared(db, monkeypatch)
    claim = worker_service.claim(db, "worker-1", mailbox.id)
    worker_service.authorize(db, "worker-1", job.id, claim["fencing_token"])
    event = MailEvent(mailbox_binding_id=mailbox.id, provider_message_id="prior-reply",
        from_address="jane@acme.com", to_address=mailbox.sender_email, subject="Prior subject",
        matched_job_id=job.id, matched_customer_id=graph.customer.id,
        classification="uncertain", match_basis="sender_subject_candidate", processed_status="needs_human")
    db.add(event)
    db.commit()
    event_service.classify(db, event.id, user, ClassifyRequest(classification="opt_out", reason="Manual verification"))
    db.refresh(job)
    assert job.status == "sending"
    worker_service.record_result(db, "worker-1", job.id,
        ResultRequest(fencing_token=claim["fencing_token"], outcome="accepted"))
    assert job.status == "provider_accepted"


def test_worker_and_human_http_credentials_are_isolated(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.utils import create_access_token
    from app.core.database import get_db
    from app.mail_outreach.errors import register_mail_outreach_error_handler
    from app.mail_outreach.router import router
    graph, mailbox, message, revision, job, user = prepared(db, monkeypatch)
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_WORKER_TOKENS_JSON",
        json.dumps({"worker-1": hashlib.sha256(b"test-worker-token").hexdigest()}))
    app = FastAPI()
    app.include_router(router, prefix="/api/mail-outreach")
    register_mail_outreach_error_handler(app)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    machine = {"Authorization": "Bearer test-worker-token"}
    human = {"Authorization": "Bearer " + create_access_token(user)}
    assert client.get("/api/mail-outreach/worker/bindings", headers=human).status_code == 401
    assert client.get("/api/mail-outreach/drafts", headers=machine).status_code == 401
    assert client.get("/api/mail-outreach/worker/bindings", headers=machine).json()["data"][0]["id"] == mailbox.id
    assert client.get("/api/mail-outreach/status", headers=human).json()["data"]["worker_ready"] is True
    outsider = {"sub": str(graph.user.id + 999), "roles": [], "permissions": ["mail_outreach:read", "mail_outreach:write", "customer:read", "customer:write"]}
    headers = {"Authorization": "Bearer " + create_access_token(outsider)}
    assert client.get("/api/mail-outreach/jobs", headers=headers).json()["data"]["total"] == 0
    assert client.post(f"/api/mail-outreach/jobs/{job.id}/cancel", headers=headers, json={}).status_code == 404


def test_delivery_notice_is_only_a_human_candidate(db, monkeypatch):
    graph, mailbox, _, _, job, user = prepared(db, monkeypatch)
    claim = worker_service.claim(db, "worker-1", mailbox.id)
    worker_service.authorize(db, "worker-1", job.id, claim["fencing_token"])
    worker_service.record_result(db, "worker-1", job.id, ResultRequest(fencing_token=claim["fencing_token"], outcome="accepted"))
    payload = EventsRequest(events=[dict(provider_message_id="dsn-1", from_address="mailer-daemon@example.com",
        to_address=mailbox.sender_email, subject="Delivery failure", received_at_utc=datetime.now(timezone.utc),
        original_recipient_candidates=["jane@acme.com"])])
    assert event_service.ingest(db, "worker-1", mailbox.id, payload)["inserted"] == 1
    event = db.query(MailEvent).one()
    assert event.classification == "uncertain"
    assert graph.point.contactability_status == "allowed"
    event_service.classify(db, event.id, user, ClassifyRequest(classification="bounce", reason="Confirmed delivery notice in mailbox"))
    assert graph.point.contactability_status == "bounced"
