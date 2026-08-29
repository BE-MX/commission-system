from types import MappingProxyType

import pytest

from app.customer.contracts import (
    DATA_CLASSIFICATIONS,
    FACT_REGISTRY,
    FACT_SEMANTIC_LAYERS,
    IDENTITY_STATUSES,
    QUALIFICATION_DECISIONS,
    QUALIFICATION_REASONS,
    RELATIONSHIP_STAGES,
    DataClassification,
    FactSemanticLayer,
    IdentityStatus,
    QualificationDecision,
    QualificationReason,
    RelationshipStage,
    SOURCE_REGISTRY,
    allowed_relationship_transition,
    identity_policy,
    source_policy,
    sources_are_independent,
    validate_registered_fact,
)


def _values(enum_type):
    return frozenset(item.value for item in enum_type)


def test_frozen_customer_enums_match_the_approved_design():
    assert IDENTITY_STATUSES == _values(IdentityStatus) == frozenset({
        "provisional",
        "identified",
        "verified",
        "disputed",
    })
    assert RELATIONSHIP_STAGES == _values(RelationshipStage) == frozenset({
        "discovered",
        "qualified",
        "developing",
        "active_customer",
        "inactive",
    })
    assert QUALIFICATION_DECISIONS == _values(QualificationDecision) == frozenset({
        "approved",
        "rejected",
        "deferred",
    })
    assert QUALIFICATION_REASONS == _values(QualificationReason) == frozenset({
        "qualified",
        "not_now",
        "poor_fit",
        "wrong_identity",
        "duplicate",
        "do_not_contact",
        "bad_data",
    })
    assert FACT_SEMANTIC_LAYERS == _values(FactSemanticLayer) == frozenset({
        "expressed",
        "observed",
        "inferred",
        "confirmed",
    })
    assert DATA_CLASSIFICATIONS == _values(DataClassification) == frozenset({
        "public_business",
        "internal_business",
        "personal_contact",
        "restricted_internal",
    })


@pytest.mark.parametrize(
    ("source_system", "identifier_type"),
    [
        ("public_web", "domain"),
        ("public_web", "website_domain"),
        ("web", "website_domain"),
        ("web", "corporate_email_domain"),
    ],
)
def test_shared_domain_never_auto_matches_a_company(source_system, identifier_type):
    policy = identity_policy(source_system, identifier_type)

    assert policy.subject_type == "customer"
    assert policy.strength == "medium"
    assert policy.cardinality in {"one_to_many", "unknown"}
    assert policy.auto_match_ceiling == "candidate"
    assert policy.unique_slot is False


def test_company_name_is_not_a_registered_unique_identity():
    with pytest.raises(KeyError):
        identity_policy("public_web", "company_name")


@pytest.mark.parametrize(
    ("source_system", "identifier_type"),
    [
        ("okki", "company_id"),
        ("alibaba", "company_id"),
        ("official_registry", "business_id"),
    ],
)
def test_verified_organization_keys_can_occupy_a_unique_slot(
    source_system,
    identifier_type,
):
    policy = identity_policy(source_system, identifier_type)

    assert policy.subject_type == "customer"
    assert policy.strength == "strong"
    assert policy.cardinality == "one_to_one"
    assert policy.auto_match_ceiling in {"identified", "verified"}
    assert policy.unique_slot is True


@pytest.mark.parametrize("identifier_type", ["buyer_id", "member_id"])
def test_alibaba_buyer_keys_are_contact_identities(identifier_type):
    policy = identity_policy("alibaba", identifier_type)

    assert policy.subject_type == "contact"
    assert policy.strength == "strong"
    assert policy.cardinality == "one_to_one"


def test_discovered_requires_an_approved_qualification_to_become_qualified():
    assert allowed_relationship_transition(
        "discovered", "qualified", "qualification_approved", True,
    )
    assert not allowed_relationship_transition(
        "discovered", "qualified", "qualification_rejected", True,
    )
    assert not allowed_relationship_transition(
        "discovered", "qualified", "qualification_approved", False,
    )


@pytest.mark.parametrize(
    ("has_primary_assignment", "has_open_opportunity", "expected"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_qualified_requires_primary_assignment_and_open_opportunity_to_develop(
    has_primary_assignment,
    has_open_opportunity,
    expected,
):
    assert allowed_relationship_transition(
        "qualified",
        "developing",
        "sales_development_ready",
        True,
        has_primary_assignment=has_primary_assignment,
        has_open_opportunity=has_open_opportunity,
    ) is expected


@pytest.mark.parametrize("current_stage", ["discovered", "qualified", "developing"])
def test_eligible_non_inactive_stage_becomes_active_only_on_valid_order(current_stage):
    assert allowed_relationship_transition(
        current_stage, "active_customer", "valid_order", True,
    )
    assert not allowed_relationship_transition(
        current_stage, "active_customer", "opportunity_won", True,
    )
    assert not allowed_relationship_transition(
        current_stage, "active_customer", "valid_order", False,
    )


def test_active_customer_never_regresses_on_historical_order_replay():
    assert allowed_relationship_transition(
        "active_customer", "active_customer", "historical_order_replay", True,
    )
    assert not allowed_relationship_transition(
        "active_customer", "developing", "historical_order_replay", True,
    )


def test_historical_order_replay_does_not_override_newer_inactive_stage():
    assert not allowed_relationship_transition(
        "inactive", "active_customer", "historical_order_replay", False,
    )
    assert not allowed_relationship_transition(
        "inactive", "active_customer", "historical_order_replay", True,
    )


def test_inactive_reactivation_requires_manual_action_or_newer_valid_order():
    assert allowed_relationship_transition(
        "inactive",
        "developing",
        "manual_reactivation",
        True,
        has_primary_assignment=True,
        has_open_opportunity=True,
    )
    assert not allowed_relationship_transition(
        "inactive",
        "developing",
        "manual_reactivation",
        True,
        has_primary_assignment=True,
        has_open_opportunity=False,
    )
    assert allowed_relationship_transition(
        "inactive", "active_customer", "valid_order", True,
    )
    assert not allowed_relationship_transition(
        "inactive", "active_customer", "valid_order", False,
    )


def test_registered_fact_exposes_governance_metadata_and_classification():
    registration = FACT_REGISTRY["business.industry"]

    assert isinstance(FACT_REGISTRY, MappingProxyType)
    assert registration.allowed_sources == frozenset({
        ("okki", "customer"),
        ("official_registry", "customer"),
        ("public_web", "company_page"),
    })
    assert registration.ttl_days == 365
    assert registration.conflict_key == "business.industry"
    assert registration.supports_high_impact is False
    assert validate_registered_fact(
        "business.industry", "public_web", "company_page",
    ) == DataClassification.PUBLIC_BUSINESS


def test_high_impact_fact_is_explicitly_registered():
    registration = FACT_REGISTRY["commercial.has_valid_order"]

    assert registration.allowed_sources == frozenset({("okki", "order")})
    assert registration.ttl_days is None
    assert registration.conflict_key == "commercial.has_valid_order"
    assert registration.supports_high_impact is True
    assert validate_registered_fact(
        "commercial.has_valid_order", "okki", "order",
    ) == DataClassification.INTERNAL_BUSINESS


def test_unregistered_or_disallowed_fact_is_rejected_by_default():
    assert validate_registered_fact(
        "unknown.key", "public_web",
    ) == DataClassification.RESTRICTED_INTERNAL
    assert validate_registered_fact(
        "commercial.has_valid_order", "public_web", "company_page",
    ) == DataClassification.RESTRICTED_INTERNAL


def test_fact_validation_rejects_wrong_source_entity_type():
    assert validate_registered_fact(
        "commercial.has_valid_order", "okki", "customer",
    ) == DataClassification.RESTRICTED_INTERNAL
    assert validate_registered_fact(
        "commercial.has_valid_order", "okki", "order",
    ) == DataClassification.INTERNAL_BUSINESS


def test_every_allowed_fact_source_has_a_matching_source_registration():
    for fact_key, fact_registration in FACT_REGISTRY.items():
        for source_key in fact_registration.allowed_sources:
            assert source_key in SOURCE_REGISTRY
            source_registration = SOURCE_REGISTRY[source_key]
            assert fact_key in source_registration.allowed_fact_keys
            assert source_registration.registry_version == "source_registry_v1"
            assert source_registration.collection_legal_basis


def test_source_registry_freezes_authority_and_promotion_contract():
    registration = source_policy("public_web", "company_page")

    assert isinstance(SOURCE_REGISTRY, MappingProxyType)
    assert registration.authority == "official_company"
    assert registration.publisher_key_rule == "registrable_domain"
    assert registration.source_family_key_rule == "canonical_content_hash"
    assert "business.industry" in registration.allowed_fact_keys
    assert registration.default_classification == DataClassification.PUBLIC_BUSINESS
    assert registration.ttl_days == 365
    assert registration.promotion_ceiling == "candidate"
    assert registration.registry_version == "source_registry_v1"
    assert registration.collection_legal_basis


def test_unknown_source_is_not_silently_registered():
    with pytest.raises(KeyError):
        source_policy("unknown_source", "customer")


@pytest.mark.parametrize(
    ("left_publisher", "left_family", "right_publisher", "right_family", "expected"),
    [
        ("registry:gb", "record:1", "company:acme", "page:2", True),
        ("company:acme", "page:1", "company:acme", "page:2", False),
        ("company:acme", "release:1", "news:mirror", "release:1", False),
        (None, "page:1", "company:acme", "page:2", False),
    ],
)
def test_source_independence_requires_different_publishers_and_families(
    left_publisher,
    left_family,
    right_publisher,
    right_family,
    expected,
):
    assert sources_are_independent(
        left_publisher,
        left_family,
        right_publisher,
        right_family,
    ) is expected
