"""邮件触达测试公共造数：客户/联系人/邮箱点/事实/画像最小图 + 草稿/邮箱绑定。"""

from types import SimpleNamespace

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.access_service import CustomerAccess
from app.customer.models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerFact,
    CustomerProfileVersion,
)
from app.mail_outreach import policies
from app.mail_outreach.models import (
    MailMailboxBinding,
    MailOutreachMessage,
    MailOutreachRevision,
)

NOW = beijing_now().replace(microsecond=0)


def seed_graph(
    db,
    *,
    customer_language="en",
    customer_timezone="America/New_York",
    contact_language=None,
    contact_timezone=None,
    verification_status="valid",
    contactability_status="allowed",
    username="mo-sales",
):
    """造一个资格默认全绿的客户图；通过关键字参数制造各类缺项。"""
    user = ArkUser(
        username=username, password_hash="x", real_name="业务员", is_active=True,
    )
    db.add(user)
    db.flush()
    customer = CustomerAccount(
        customer_code=f"C-{username}", display_name="Acme Hair",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="qualified", relationship_stage_changed_at=NOW,
        relationship_stage_reason="test", record_status="active",
        identity_confidence=1, profile_completeness=80, profile_input_seq=0,
        default_language=customer_language, timezone=customer_timezone,
        primary_country_code="US",
    )
    db.add(customer)
    db.flush()
    contact = CustomerContact(
        display_name="Jane Doe", canonical_name="Jane Doe",
        identity_status="verified", confidence=1,
        confidence_method_version="test_v1", confidence_components_json={},
        record_status="active", default_language=contact_language,
        timezone=contact_timezone, country_code="US",
    )
    db.add(contact)
    db.flush()
    point = CustomerContactPoint(
        contact_id=contact.id, point_type="email",
        raw_value="jane@acme.com", normalized_value="jane@acme.com",
        email_domain_type="corporate",
        verification_status=verification_status,
        contactability_status=contactability_status,
        is_primary=True, data_classification="internal_business",
        point_fingerprint=f"{contact.id:064x}", first_seen_at=NOW, last_seen_at=NOW,
        verified_at=NOW,
    )
    relationship = CustomerContactRelationship(
        customer_id=customer.id, contact_id=contact.id,
        relationship_type="buyer", job_title="Purchasing Manager",
        buying_role="decision_maker", verification_status="verified",
        confidence=1, confidence_method_version="test_v1",
        confidence_components_json={}, effective_from=NOW,
        relationship_fingerprint=f"r{contact.id:063x}",
    )
    fact = CustomerFact(
        customer_id=customer.id, subject_type="customer",
        fact_key="business.industry", value_type="string",
        value_json={"value": "hair products"}, fact_layer="confirmed",
        verification_status="verified", confidence=1,
        confidence_method_version="test_v1", confidence_components_json={},
        data_classification="internal_business", visibility_scope="customer_team",
        classification_reason="test", evidence_json={},
        fact_fingerprint=f"f{customer.id:063x}", observed_at=NOW,
    )
    db.add_all([point, relationship, fact])
    db.flush()
    profile = CustomerProfileVersion(
        customer_id=customer.id, version_no=1,
        profile_schema_version="customer_profile_v1", canonicalization_version="jcs_v1",
        input_seq=0, profile_json={}, section_hashes={}, section_data_as_of={},
        evidence_fact_ids=[fact.id], change_summary={}, compiler_version="test_v1",
        profile_fingerprint=f"v{customer.id:063x}", compiled_at=NOW,
    )
    db.add(profile)
    db.flush()
    customer.current_profile_version_id = profile.id
    db.flush()
    access = CustomerAccess(
        customer_id=customer.id, actor_user_id=user.id, can_manage=True,
        max_data_classification="restricted_internal",
        max_visibility_scope="management", run_id=None, scope_kind="customer_team",
    )
    return SimpleNamespace(
        user=user, customer=customer, contact=contact, point=point,
        fact=fact, profile=profile, access=access,
    )


def make_mailbox(db, *, sender_email="sales@leshine.com", owner_user_id=None, **overrides):
    params = {
        "provider": "agent_mail", "sender_email": sender_email,
        "display_name": "Sales", "owner_user_id": owner_user_id,
        "worker_identity": "worker-1", "cli_workspace": "ark-sales",
        "auth_status": "active", "daily_quota": 50, "status": "active",
    }
    params.update(overrides)
    mailbox = MailMailboxBinding(**params)
    db.add(mailbox)
    db.flush()
    return mailbox


def make_draft(
    db,
    graph,
    *,
    subject="Hello Jane",
    body_text="Plain body text",
    language_tag="en",
    claims=None,
    risk_flags=None,
):
    """直接落一条 draft 草稿与首个 revision（content_sha256 按 policies 计算）。"""
    claims = [] if claims is None else claims
    message = MailOutreachMessage(
        customer_id=graph.customer.id, contact_id=graph.contact.id,
        contact_point_id=graph.point.id, relationship_goal="first_intro",
        status="draft", created_by=graph.user.id,
    )
    db.add(message)
    db.flush()
    revision = MailOutreachRevision(
        message_id=message.id, revision_no=1,
        subject=subject, body_text=body_text, language_tag=language_tag,
        language_source="company", language_basis="客户主档默认语言",
        meaning_summary_zh="释义", angle="", cta="",
        claims_json=claims, risk_flags_json=risk_flags or [],
        evidence_snapshot_json={},
        recipient_timezone="America/New_York", location_evidence="",
        schedule_policy_json={},
        content_sha256=policies.compute_content_sha256(
            subject=subject, body_text=body_text,
            language_tag=language_tag, claims=claims,
        ),
        created_by_kind="ai", created_by=graph.user.id,
    )
    db.add(revision)
    db.flush()
    message.current_revision_id = revision.id
    db.flush()
    return message, revision
