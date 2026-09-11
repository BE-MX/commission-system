"""eligibility_service 统一触达资格规则用例。"""

from app.core.time import beijing_now
from app.customer.models import CustomerSuppressionRegistry
from app.mail_outreach.eligibility_service import evaluate_email_eligibility
from app.mail_outreach.models import (
    MailOutreachApproval,
    MailOutreachSendJob,
)
from tests.mail_outreach_helpers import NOW, make_draft, make_mailbox, seed_graph


def _evaluate(db, graph):
    return evaluate_email_eligibility(
        db, graph.access, graph.customer.id, graph.contact.id, graph.point.id,
    )


def test_eligible_when_all_rules_pass(db):
    graph = seed_graph(db)
    result = _evaluate(db, graph)
    assert result == {"eligible": True, "missing": [], "reasons": []}


def test_unknown_email_verification_blocks(db):
    graph = seed_graph(db, verification_status="unknown")
    result = _evaluate(db, graph)
    assert result["eligible"] is False
    assert "email_verification" in result["missing"]


def test_customer_level_suppression_blocks(db):
    graph = seed_graph(db)
    db.add(CustomerSuppressionRegistry(
        identifier_type="email", source_system="global", source_account_key="global",
        normalized_value_hmac="h" * 64, hmac_key_version="v1",
        scope_type="channel", scope_ref_id="email",
        reason_code="do_not_contact", source_ref_type="manual",
        status="active", mapping_status="mapped",
        mapped_customer_id=graph.customer.id,
        suppression_fingerprint="c" * 64, effective_at=NOW,
    ))
    db.flush()
    result = _evaluate(db, graph)
    assert result["eligible"] is False
    assert "customer_suppression" in result["missing"]


def test_point_level_suppression_blocks(db):
    graph = seed_graph(db)
    db.add(CustomerSuppressionRegistry(
        identifier_type="email", source_system="global", source_account_key="global",
        normalized_value_hmac="p" * 64, hmac_key_version="v1",
        scope_type="global", scope_ref_id=None,
        reason_code="opted_out", source_ref_type="provider_event",
        status="active", mapping_status="mapped",
        mapped_contact_point_id=graph.point.id,
        suppression_fingerprint="d" * 64, effective_at=NOW,
    ))
    db.flush()
    result = _evaluate(db, graph)
    assert result["eligible"] is False
    assert "point_suppression" in result["missing"]


def test_missing_timezone_blocks(db):
    graph = seed_graph(db, customer_timezone=None, contact_timezone=None)
    result = _evaluate(db, graph)
    assert result["eligible"] is False
    assert "timezone" in result["missing"]


def test_missing_language_blocks(db):
    graph = seed_graph(db, customer_language=None, contact_language=None)
    result = _evaluate(db, graph)
    assert result["eligible"] is False
    assert "language" in result["missing"]


def test_contact_language_fallback_passes(db):
    """客户缺语言/时区但联系人有，视为有依据。"""
    graph = seed_graph(
        db, customer_language=None, customer_timezone=None,
        contact_language="en", contact_timezone="America/New_York",
    )
    result = _evaluate(db, graph)
    assert result["eligible"] is True


def test_recipient_cooldown_blocks_with_recent_job(db):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    approval = MailOutreachApproval(
        message_id=message.id, revision_id=revision.id,
        approver_user_id=graph.user.id, decision="approved",
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=graph.point.id,
        to_email_snapshot=graph.point.normalized_value,
        decided_at=NOW,
    )
    db.add(approval)
    db.flush()
    job = MailOutreachSendJob(
        idempotency_key="e" * 64, approval_id=approval.id,
        message_id=message.id, revision_id=revision.id,
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=graph.point.id,
        to_email_snapshot=graph.point.normalized_value,
        status="provider_accepted", due_at=NOW, due_at_utc=NOW,
    )
    db.add(job)
    db.flush()
    result = _evaluate(db, graph)
    assert result["eligible"] is False
    assert "recipient_cooldown" in result["missing"]
    assert f"job#{job.id}" in "；".join(result["reasons"])


def test_cooldown_ignores_terminal_jobs(db):
    """终态 job（cancelled）不占用冷却期。"""
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    message, revision = make_draft(db, graph)
    approval = MailOutreachApproval(
        message_id=message.id, revision_id=revision.id,
        approver_user_id=graph.user.id, decision="approved",
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=graph.point.id,
        to_email_snapshot=graph.point.normalized_value,
        decided_at=NOW,
    )
    db.add(approval)
    db.flush()
    db.add(MailOutreachSendJob(
        idempotency_key="9" * 64, approval_id=approval.id,
        message_id=message.id, revision_id=revision.id,
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=graph.point.id,
        to_email_snapshot=graph.point.normalized_value,
        status="cancelled", due_at=NOW, due_at_utc=NOW,
    ))
    db.flush()
    assert beijing_now() >= NOW
    assert _evaluate(db, graph)["eligible"] is True
