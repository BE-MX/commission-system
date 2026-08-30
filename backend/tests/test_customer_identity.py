"""Identity resolution contracts for the unified customer domain."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.core.time import beijing_now
from app.customer.identity_service import (
    CustomerDomainError,
    IdentityCandidate,
    attach_identity_candidate,
    confirm_identity,
    resolve_business_context,
)
from app.customer.models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerExternalIdentity,
    CustomerName,
    CustomerResearchTask,
    CustomerResolutionKey,
    CustomerSourceRecord,
)


def _okki_candidate(value: str = "OKKI-COMPANY-42") -> IdentityCandidate:
    return IdentityCandidate(
        identifier_type="company_id",
        raw_value=value,
        verification_status="verified",
        confidence=1,
    )


def test_okki_company_id_deterministically_converges_without_name_matching(db):
    first = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-a",
        source_entity_type="company",
        external_context_id="sync-row-1",
        company_name="Example Trading",
        identity_candidates=[_okki_candidate()],
    )
    second = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-a",
        source_entity_type="company",
        external_context_id="sync-row-2",
        company_name="A renamed value that is not an identity",
        identity_candidates=[_okki_candidate()],
    )

    assert first.customer.id == second.customer.id
    assert first.created is True
    assert second.created is False
    assert first.customer.identity_status == "verified"
    assert db.query(CustomerAccount).count() == 1
    assert db.query(CustomerResolutionKey).count() == 1


def test_unverified_strong_candidate_is_scoped_to_business_context(db):
    candidate = IdentityCandidate("company_id", "UNVERIFIED-OKKI")
    first = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-unverified",
        source_entity_type="company",
        external_context_id="row-unverified-1",
        identity_candidates=[candidate],
    )
    second = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-unverified",
        source_entity_type="company",
        external_context_id="row-unverified-2",
        identity_candidates=[candidate],
    )

    assert first.customer.id != second.customer.id
    assert first.customer.identity_status == "provisional"
    assert second.customer.identity_status == "provisional"
    assert first.resolution.resolution_type == "business_context"
    assert second.resolution.resolution_type == "business_context"


def test_resolve_reuses_existing_verified_strong_identity_without_resolution_key(db):
    existing = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-before-okki",
    )
    identity = attach_identity_candidate(
        db,
        customer_id=existing.customer.id,
        source_system="okki",
        source_account_key="tenant-existing",
        identifier_type="company_id",
        raw_value="OKKI-EXISTING-1",
    )
    confirm_identity(db, identity.id)
    before_count = db.query(CustomerAccount).count()

    resolved = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-existing",
        source_entity_type="company",
        external_context_id="sync-after-alibaba",
        identity_candidates=[_okki_candidate("OKKI-EXISTING-1")],
    )

    assert resolved.customer.id == existing.customer.id
    assert resolved.created is False
    assert db.query(CustomerAccount).count() == before_count


def test_same_company_name_and_shared_domain_never_auto_merge(db):
    first = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-1",
        company_name="Global Hair",
    )
    second = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-2",
        company_name="Global Hair",
    )

    attach_identity_candidate(
        db,
        customer_id=first.customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="https://shared.example/path",
    )
    attach_identity_candidate(
        db,
        customer_id=second.customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="shared.example",
    )

    assert first.customer.id != second.customer.id
    identities = db.query(CustomerExternalIdentity).order_by(CustomerExternalIdentity.id).all()
    assert [row.identity_strength for row in identities] == ["medium", "medium"]
    assert [row.cardinality for row in identities] == ["unknown", "unknown"]
    assert [row.auto_match_ceiling for row in identities] == ["candidate", "candidate"]
    assert all(row.verification_status == "candidate" for row in identities)


def test_same_free_email_never_auto_merges_business_contexts(db):
    first = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="free-email-1",
        contact_name="Mina",
        contact_email="same.person@gmail.com",
    )
    second = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="free-email-2",
        contact_name="Mina",
        contact_email="same.person@gmail.com",
    )

    assert first.customer.id != second.customer.id
    assert first.contact.id != second.contact.id


def test_alibaba_buyer_identity_belongs_to_contact_not_customer(db):
    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-buyer-1",
        contact_name="Mina",
        identity_candidates=[IdentityCandidate("buyer_id", "BUYER-9")],
    )

    identity = db.query(CustomerExternalIdentity).one()
    assert result.contact is not None
    assert identity.customer_id is None
    assert identity.contact_id == result.contact.id
    assert identity.identity_strength == "strong"
    assert identity.auto_match_ceiling == "identified"


def test_resolution_does_not_depend_on_session_autoflush(db):
    db.autoflush = False

    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-no-autoflush",
        source_entity_type="inquiry",
        external_context_id="inq-no-autoflush",
        contact_name="Mina",
        identity_candidates=[IdentityCandidate("buyer_id", "BUYER-NO-AUTOFLUSH")],
    )

    identity = db.query(CustomerExternalIdentity).filter_by(
        normalized_value="BUYER-NO-AUTOFLUSH"
    ).one()
    assert identity.contact_id == result.contact.id


def test_provider_explicit_organization_declaration_can_bind_alibaba_member_to_account(db):
    source = CustomerSourceRecord(
        customer_id=None,
        source_system="alibaba",
        source_account_key="shop-a",
        authority_level="verified_platform",
        source_entity_type="inquiry",
        external_record_id="org-row-1",
        external_record_key_hash="c" * 64,
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test registered schema",
        payload_schema_version="alibaba_inquiry_v1",
        payload_json={
            "provider_identity_declarations": [{
                "identifier_type": "member_id",
                "raw_value": "ORG-MEMBER-1",
                "subject_type": "organization",
            }],
        },
        content_hash="d" * 64,
        captured_at=beijing_now(),
        processing_status="pending",
    )
    db.add(source)
    db.flush()
    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="company",
        external_context_id="org-row-1",
        source_record_id=source.id,
        identity_candidates=[
            IdentityCandidate(
                "member_id",
                "ORG-MEMBER-1",
                provider_declared_subject_type="customer",
            )
        ],
    )

    identity = db.query(CustomerExternalIdentity).one()
    assert identity.customer_id == result.customer.id
    assert identity.contact_id is None
    assert identity.auto_match_ceiling == "identified"


def test_forged_alibaba_organization_flag_without_registered_payload_is_rejected(db):
    with pytest.raises(CustomerDomainError) as forged:
        resolve_business_context(
            db,
            source_system="alibaba",
            source_account_key="shop-a",
            source_entity_type="company",
            external_context_id="forged-org-row",
            identity_candidates=[
                IdentityCandidate(
                    "member_id",
                    "FORGED-ORG",
                    provider_declared_subject_type="customer",
                )
            ],
        )

    assert forged.value.error_code == "IDENTITY_SUBJECT_EVIDENCE_REQUIRED"


def test_personal_email_and_person_name_create_provisional_graph_and_research_seed(db):
    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-personal-1",
        company_name="Mina Lee",
        contact_name="Mina Lee",
        contact_email="mina.lee@gmail.com",
        identity_candidates=[IdentityCandidate("member_id", "MEMBER-PERSON-1")],
    )

    account = result.customer
    contact = db.query(CustomerContact).one()
    point = db.query(CustomerContactPoint).one()
    relation = db.query(CustomerContactRelationship).one()
    alias = db.query(CustomerName).one()
    research = db.query(CustomerResearchTask).one()

    assert account.canonical_company_name is None
    assert account.entity_type == "unknown"
    assert account.identity_status == "provisional"
    assert contact.id == result.contact.id
    assert point.contact_id == contact.id
    assert point.email_domain_type == "free"
    assert relation.customer_id == account.id and relation.contact_id == contact.id
    assert relation.verification_status == "identified"
    assert alias.name == "Mina Lee" and alias.name_type == "person_alias"
    assert research.customer_id == account.id
    assert research.task_type == "identity_enrichment"
    assert research.input_snapshot["contact_point_id"] == point.id
    assert research.input_snapshot["email_domain"] == "gmail.com"
    assert "canonical_company_name" not in research.input_snapshot
    assert account.profile_input_seq == 1


def test_company_name_is_captured_as_name_signal_but_never_canonical_identity(db):
    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-name-1",
        company_name="Filled In Company",
    )

    name = db.query(CustomerName).one()
    assert name.name == "Filled In Company"
    assert name.name_type == "platform_alias"
    assert result.customer.canonical_company_name is None
    assert db.query(CustomerExternalIdentity).count() == 0


def test_replayed_business_context_does_not_increment_profile_sequence(db):
    first = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-replay-1",
        contact_name="Lee",
    )
    initial_seq = first.customer.profile_input_seq

    replay = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-replay-1",
        contact_name="Changed replay payload is handled by source versions",
    )

    assert replay.created is False
    assert replay.customer.profile_input_seq == initial_seq


def test_existing_winner_applies_new_context_material_once(db):
    first = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-winner",
        source_entity_type="company",
        external_context_id="winner-row-1",
        identity_candidates=[_okki_candidate("WINNER-COMPANY")],
    )
    source = CustomerSourceRecord(
        customer_id=None,
        source_system="okki",
        source_account_key="tenant-winner",
        authority_level="transactional",
        source_entity_type="customer",
        external_record_id="winner-source-2",
        external_record_key_hash="a" * 64,
        source_version="v2",
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test",
        payload_schema_version="okki_customer_v1",
        payload_json={"company_name": "Winner Trading"},
        content_hash="b" * 64,
        captured_at=beijing_now(),
        processing_status="pending",
    )
    db.add(source)
    db.flush()
    before_seq = first.customer.profile_input_seq

    enriched = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-winner",
        source_entity_type="company",
        external_context_id="winner-row-2",
        source_record_id=source.id,
        company_name="Winner Trading",
        contact_name="Mina",
        contact_email="mina@winner.example",
        identity_candidates=[_okki_candidate("WINNER-COMPANY")],
    )
    after_seq = first.customer.profile_input_seq
    replay = resolve_business_context(
        db,
        source_system="okki",
        source_account_key="tenant-winner",
        source_entity_type="company",
        external_context_id="winner-row-2",
        source_record_id=source.id,
        company_name="Winner Trading",
        contact_name="Mina",
        contact_email="mina@winner.example",
        identity_candidates=[_okki_candidate("WINNER-COMPANY")],
    )

    assert enriched.customer.id == first.customer.id
    assert source.customer_id == first.customer.id
    assert db.query(CustomerName).filter_by(
        customer_id=first.customer.id,
        name="Winner Trading",
        source_record_id=source.id,
    ).count() == 1
    assert enriched.contact is not None
    assert db.query(CustomerContactPoint).filter_by(
        contact_id=enriched.contact.id,
        normalized_value="mina@winner.example",
    ).count() == 1
    assert after_seq == before_seq + 1
    assert replay.customer.profile_input_seq == after_seq


def test_identity_subject_xor_and_registry_subject_are_enforced(db):
    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-xor-1",
        contact_name="Mina",
    )

    with pytest.raises(CustomerDomainError) as both:
        attach_identity_candidate(
            db,
            customer_id=result.customer.id,
            contact_id=result.contact.id,
            source_system="alibaba",
            source_account_key="shop-a",
            identifier_type="buyer_id",
            raw_value="BUYER-X",
        )
    assert both.value.error_code == "IDENTITY_SUBJECT_INVALID"

    with pytest.raises(CustomerDomainError) as wrong_subject:
        attach_identity_candidate(
            db,
            customer_id=result.customer.id,
            source_system="alibaba",
            source_account_key="shop-a",
            identifier_type="buyer_id",
            raw_value="BUYER-X",
        )
    assert wrong_subject.value.error_code == "IDENTITY_SUBJECT_INVALID"


def test_attach_identity_is_idempotent_and_bumps_sequence_only_once(db):
    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-identity-replay",
    )
    original_seq = result.customer.profile_input_seq

    first = attach_identity_candidate(
        db,
        customer_id=result.customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="https://Example.COM/about",
    )
    seq_after_first = result.customer.profile_input_seq
    replay = attach_identity_candidate(
        db,
        customer_id=result.customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="example.com",
    )

    assert first.id == replay.id
    assert seq_after_first == original_seq + 1
    assert result.customer.profile_input_seq == seq_after_first


def test_confirmed_strong_identity_conflict_marks_review_instead_of_merging(db):
    left = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-conflict-left",
    )
    right = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-conflict-right",
    )
    left_identity = attach_identity_candidate(
        db,
        customer_id=left.customer.id,
        source_system="okki",
        source_account_key="tenant-a",
        identifier_type="company_id",
        raw_value="CONFLICT-42",
    )
    right_identity = attach_identity_candidate(
        db,
        customer_id=right.customer.id,
        source_system="okki",
        source_account_key="tenant-a",
        identifier_type="company_id",
        raw_value="CONFLICT-42",
    )
    confirm_identity(db, left_identity.id)

    outcome = confirm_identity(db, right_identity.id)

    assert outcome.conflict is True
    assert left.customer.record_status == "active"
    assert right.customer.record_status == "active"
    assert left.customer.merged_into_customer_id is None
    assert right.customer.merged_into_customer_id is None
    assert left.customer.identity_status == "disputed"
    assert right.customer.identity_status == "disputed"
    assert left_identity.status == "disputed"
    assert right_identity.status == "disputed"

    left_seq = left.customer.profile_input_seq
    right_seq = right.customer.profile_input_seq
    replay = confirm_identity(db, right_identity.id)
    assert replay.conflict is True
    assert right_identity.verification_status == "disputed"
    assert left.customer.profile_input_seq == left_seq
    assert right.customer.profile_input_seq == right_seq


def test_contact_identity_confirmation_and_conflict_do_not_dispute_accounts(db):
    left = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-contact-conflict",
        source_entity_type="inquiry",
        external_context_id="buyer-left",
        contact_name="Left Buyer",
    )
    right = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-contact-conflict",
        source_entity_type="inquiry",
        external_context_id="buyer-right",
        contact_name="Right Buyer",
    )
    left_identity = attach_identity_candidate(
        db,
        contact_id=left.contact.id,
        source_system="alibaba",
        source_account_key="shop-contact-conflict",
        identifier_type="buyer_id",
        raw_value="BUYER-CONFLICT",
    )
    right_identity = attach_identity_candidate(
        db,
        contact_id=right.contact.id,
        source_system="alibaba",
        source_account_key="shop-contact-conflict",
        identifier_type="buyer_id",
        raw_value="BUYER-CONFLICT",
    )

    confirm_identity(db, left_identity.id)
    outcome = confirm_identity(db, right_identity.id)

    assert outcome.conflict is True
    assert left.contact.identity_status == "disputed"
    assert right.contact.identity_status == "disputed"
    assert left.customer.identity_status == "provisional"
    assert right.customer.identity_status == "provisional"


def test_confirm_medium_domain_never_promotes_account_past_candidate(db):
    result = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="inq-domain-confirm",
    )
    identity = attach_identity_candidate(
        db,
        customer_id=result.customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="one.example",
    )

    confirm_identity(db, identity.id)

    assert identity.verification_status == "verified"
    assert result.customer.identity_status == "provisional"


def test_ambiguous_contact_identity_opens_resolution_conflict_instead_of_picking_first(db):
    left = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="contact-ambiguous-left",
        contact_name="Left",
    )
    right = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_context_id="contact-ambiguous-right",
        contact_name="Right",
    )
    attach_identity_candidate(
        db,
        contact_id=left.contact.id,
        source_system="alibaba",
        source_account_key="shop-a",
        identifier_type="buyer_id",
        raw_value="AMBIGUOUS-BUYER",
    )
    attach_identity_candidate(
        db,
        contact_id=right.contact.id,
        source_system="alibaba",
        source_account_key="shop-a",
        identifier_type="buyer_id",
        raw_value="AMBIGUOUS-BUYER",
    )
    account_count = db.query(CustomerAccount).count()

    with pytest.raises(CustomerDomainError) as conflict:
        resolve_business_context(
            db,
            source_system="alibaba",
            source_account_key="shop-a",
            source_entity_type="inquiry",
            external_context_id="contact-ambiguous-third",
            identity_candidates=[IdentityCandidate("buyer_id", "AMBIGUOUS-BUYER")],
        )

    assert conflict.value.error_code == "IDENTITY_RESOLUTION_CONFLICT"
    assert db.query(CustomerAccount).count() == account_count


def test_failed_graph_flush_leaves_no_orphan_customer(db):
    before = db.query(CustomerAccount).count()

    with pytest.raises(CustomerDomainError) as failure:
        resolve_business_context(
            db,
            source_system="alibaba",
            source_account_key="shop-a",
            source_entity_type="inquiry",
            external_context_id="inq-invalid-graph",
            contact_email="not-an-email",
        )

    assert failure.value.error_code == "CONTACT_POINT_INVALID"
    assert db.query(CustomerAccount).count() == before
    assert db.query(CustomerResolutionKey).filter_by(
        source_system="alibaba",
        source_entity_type="inquiry",
    ).count() == 0


def test_failure_after_graph_creation_rolls_back_resolution_customer_and_contact(db):
    counts_before = (
        db.query(CustomerResolutionKey).count(),
        db.query(CustomerAccount).count(),
        db.query(CustomerContact).count(),
        db.query(CustomerContactRelationship).count(),
    )

    with pytest.raises(CustomerDomainError) as failure:
        resolve_business_context(
            db,
            source_system="alibaba",
            source_account_key="shop-a",
            source_entity_type="inquiry",
            external_context_id="inq-fail-after-graph",
            contact_name="Mina",
            identity_candidates=[
                IdentityCandidate(
                    "buyer_id",
                    "BUYER-INVALID-STATUS",
                    verification_status="not-a-status",  # type: ignore[arg-type]
                )
            ],
        )

    assert failure.value.error_code == "IDENTITY_STATUS_INVALID"
    assert (
        db.query(CustomerResolutionKey).count(),
        db.query(CustomerAccount).count(),
        db.query(CustomerContact).count(),
        db.query(CustomerContactRelationship).count(),
    ) == counts_before


def test_first_resolution_key_statement_is_insert_not_gap_lock_select(db):
    statements = []
    engine = db.get_bind()

    def _capture(_conn, _cursor, statement, _params, _context, _many):
        if "ark_customer_resolution_keys" in statement:
            statements.append(statement.lstrip().upper())

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        resolve_business_context(
            db,
            source_system="alibaba",
            source_account_key="insert-first",
            source_entity_type="inquiry",
            external_context_id="insert-first-1",
        )
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert statements
    assert statements[0].startswith("INSERT INTO ARK_CUSTOMER_RESOLUTION_KEYS")


@pytest.mark.skipif(
    not os.getenv("CUSTOMER_TEST_MYSQL_URL"),
    reason="set CUSTOMER_TEST_MYSQL_URL only for an explicitly disposable MySQL schema",
)
def test_real_mysql_two_session_resolution_has_one_winner_and_no_orphans():
    """Optional destructive integration coverage for database arbitration."""
    url = os.environ["CUSTOMER_TEST_MYSQL_URL"]
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    suffix = str(beijing_now().timestamp()).replace(".", "")
    context_id = f"mysql-race-{suffix}"
    start = threading.Barrier(2)

    def _resolve_in_own_session():
        with factory() as session:
            start.wait(timeout=10)
            result = resolve_business_context(
                session,
                source_system="alibaba",
                source_account_key="test-only",
                source_entity_type="inquiry",
                external_context_id=context_id,
            )
            session.commit()
            return result.customer.id, result.resolution.resolution_key

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: _resolve_in_own_session(), range(2)))
    customer_ids = {outcome[0] for outcome in outcomes}
    resolution_key = outcomes[0][1]
    assert len(customer_ids) == 1
    winner_id = next(iter(customer_ids))

    with Session(engine) as check:
        key = check.query(CustomerResolutionKey).filter_by(
            resolution_key=resolution_key,
        ).one()
        assert key.customer_id == winner_id
        assert check.query(CustomerAccount).filter(
            CustomerAccount.id == winner_id
        ).count() == 1
