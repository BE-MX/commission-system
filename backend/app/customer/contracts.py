"""Executable policies for the unified customer domain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Mapping


class IdentityStatus(StrEnum):
    PROVISIONAL = "provisional"
    IDENTIFIED = "identified"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class RelationshipStage(StrEnum):
    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    DEVELOPING = "developing"
    ACTIVE_CUSTOMER = "active_customer"
    INACTIVE = "inactive"


class QualificationDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class QualificationReason(StrEnum):
    QUALIFIED = "qualified"
    NOT_NOW = "not_now"
    POOR_FIT = "poor_fit"
    WRONG_IDENTITY = "wrong_identity"
    DUPLICATE = "duplicate"
    DO_NOT_CONTACT = "do_not_contact"
    BAD_DATA = "bad_data"


class FactSemanticLayer(StrEnum):
    EXPRESSED = "expressed"
    OBSERVED = "observed"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"


class DataClassification(StrEnum):
    PUBLIC_BUSINESS = "public_business"
    INTERNAL_BUSINESS = "internal_business"
    PERSONAL_CONTACT = "personal_contact"
    RESTRICTED_INTERNAL = "restricted_internal"


_DATA_CLASSIFICATION_ORDER = (
    DataClassification.PUBLIC_BUSINESS,
    DataClassification.INTERNAL_BUSINESS,
    DataClassification.PERSONAL_CONTACT,
    DataClassification.RESTRICTED_INTERNAL,
)


IDENTITY_STATUSES = frozenset(item.value for item in IdentityStatus)
RELATIONSHIP_STAGES = frozenset(item.value for item in RelationshipStage)
QUALIFICATION_DECISIONS = frozenset(item.value for item in QualificationDecision)
QUALIFICATION_REASONS = frozenset(item.value for item in QualificationReason)
FACT_SEMANTIC_LAYERS = frozenset(item.value for item in FactSemanticLayer)
DATA_CLASSIFICATIONS = frozenset(item.value for item in DataClassification)


IdentitySubject = Literal["customer", "contact"]
SourceKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class IdentityPolicy:
    subject_type: IdentitySubject
    strength: Literal["strong", "medium", "weak"]
    cardinality: Literal["one_to_one", "one_to_many", "unknown"]
    auto_match_ceiling: Literal["candidate", "identified", "verified"]
    normalization_rule: str
    unique_slot: bool


_STRONG_CUSTOMER_ID = IdentityPolicy(
    subject_type="customer",
    strength="strong",
    cardinality="one_to_one",
    auto_match_ceiling="verified",
    normalization_rule="trim_exact",
    unique_slot=True,
)
_STRONG_CONTACT_ID = IdentityPolicy(
    subject_type="contact",
    strength="strong",
    cardinality="one_to_one",
    auto_match_ceiling="identified",
    normalization_rule="trim_exact",
    unique_slot=True,
)
_SHARED_DOMAIN = IdentityPolicy(
    subject_type="customer",
    strength="medium",
    cardinality="unknown",
    auto_match_ceiling="candidate",
    normalization_rule="registrable_domain",
    unique_slot=False,
)


IDENTITY_REGISTRY: Mapping[tuple[str, str], IdentityPolicy] = MappingProxyType({
    ("okki", "company_id"): _STRONG_CUSTOMER_ID,
    ("okki", "contact_id"): _STRONG_CONTACT_ID,
    ("alibaba", "company_id"): _STRONG_CUSTOMER_ID,
    ("official_registry", "business_id"): _STRONG_CUSTOMER_ID,
    ("alibaba", "buyer_id"): _STRONG_CONTACT_ID,
    ("alibaba", "member_id"): _STRONG_CONTACT_ID,
    ("public_web", "domain"): _SHARED_DOMAIN,
    ("public_web", "website_domain"): _SHARED_DOMAIN,
    ("public_web", "corporate_email_domain"): _SHARED_DOMAIN,
    ("web", "domain"): _SHARED_DOMAIN,
    ("web", "website_domain"): _SHARED_DOMAIN,
    ("web", "corporate_email_domain"): _SHARED_DOMAIN,
})


@dataclass(frozen=True, slots=True)
class ObjectOwnershipPolicy:
    """Declare how a movable business root exposes its storage customer."""

    storage_mode: Literal["direct", "subject"]
    handling_mode: Literal["overlay", "end_and_rebuild_if_open"]
    eligibility: Literal[
        "always",
        "non_policy_annotation",
        "terminal_research_task",
    ]


OBJECT_OWNERSHIP_REGISTRY_VERSION = "customer_object_ownership_v1"
OBJECT_OWNERSHIP_REGISTRY: Mapping[str, ObjectOwnershipPolicy] = MappingProxyType({
    "name": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "external_identity": ObjectOwnershipPolicy("subject", "overlay", "always"),
    "contact_point": ObjectOwnershipPolicy("subject", "overlay", "always"),
    "source_record": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "fact": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "conversation": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "order": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "research_task": ObjectOwnershipPolicy(
        "direct",
        "end_and_rebuild_if_open",
        "terminal_research_task",
    ),
    "search_result": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "opportunity": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "action": ObjectOwnershipPolicy("direct", "overlay", "always"),
    "annotation": ObjectOwnershipPolicy(
        "direct",
        "overlay",
        "non_policy_annotation",
    ),
    "acquisition_attribution": ObjectOwnershipPolicy(
        "direct",
        "overlay",
        "always",
    ),
})


def identity_policy(source_system: str, identifier_type: str) -> IdentityPolicy:
    """Return the registered identity policy, rejecting undeclared identities."""
    try:
        return IDENTITY_REGISTRY[(source_system, identifier_type)]
    except KeyError:
        raise KeyError(
            f"Unregistered identity policy: {source_system}/{identifier_type}",
        ) from None


@dataclass(frozen=True, slots=True)
class FactRegistration:
    value_types: frozenset[Literal[
        "string", "number", "boolean", "date", "datetime", "list", "object",
    ]]
    data_classification: DataClassification
    allowed_sources: frozenset[SourceKey]
    ttl_days: int | None
    conflict_key: str
    allowed_purposes: frozenset[str]
    supports_high_impact: bool


_PUBLIC_FACT_SOURCES = frozenset({
    ("okki", "customer"),
    ("official_registry", "customer"),
    ("public_web", "company_page"),
})
_MESSAGE_SOURCES = frozenset({
    ("alibaba", "message"),
    ("email", "message"),
    ("whatsapp", "message"),
})
_EXPRESSED_SOURCES = _MESSAGE_SOURCES | {("alibaba", "inquiry")}
_AGENT_SOURCE = frozenset({("agent", "research_report")})
_MANUAL_SOURCE = frozenset({("manual", "customer")})
_PROFILE_PURPOSES = frozenset({"profile", "research", "sales"})

_EXPRESSED_FACT_KEYS = frozenset({
    "preference.expressed.product_family",
    "preference.expressed.model",
    "preference.expressed.color",
    "preference.expressed.length",
    "preference.expressed.quantity",
    "preference.expressed.price_range",
    "preference.expressed.delivery_window",
})
_OBSERVED_PREFERENCE_FACT_KEYS = frozenset({
    "preference.observed.product_family",
    "preference.observed.model",
    "preference.observed.color",
    "preference.observed.length",
    "preference.observed.order_size",
    "preference.observed.sample_or_bulk",
})
_INFERRED_PREFERENCE_FACT_KEYS = frozenset({
    "preference.inferred.product_direction",
    "preference.inferred.price_sensitivity",
    "preference.inferred.seasonality",
})
_OBSERVED_BEHAVIOR_FACT_KEYS = frozenset({
    "behavior.observed.response_latency",
    "behavior.observed.preferred_channel",
    "behavior.observed.active_hours",
    "behavior.observed.inquiry_frequency",
    "behavior.observed.decision_speed",
    "behavior.observed.silence_period",
})
_INFERRED_BEHAVIOR_FACT_KEYS = frozenset({
    "behavior.inferred.buying_stage",
    "behavior.inferred.supplier_switch_signal",
    "behavior.inferred.growth_signal",
    "behavior.inferred.churn_risk",
})

_NUMBER_VALUE_FACT_KEYS = frozenset({
    "preference.expressed.quantity",
    "preference.observed.order_size",
    "behavior.observed.response_latency",
    "behavior.observed.inquiry_frequency",
    "behavior.observed.decision_speed",
    "behavior.observed.silence_period",
})
_OBJECT_VALUE_FACT_KEYS = frozenset({
    "preference.expressed.price_range",
    "preference.inferred.seasonality",
})
_LIST_VALUE_FACT_KEYS = frozenset({"behavior.observed.active_hours"})
_STRING_VALUE_FACT_KEYS = (
    {
        "business.industry",
        "behavior.confirmed.priority",
        "behavior.confirmed.relationship_note",
    }
    | (_EXPRESSED_FACT_KEYS - _NUMBER_VALUE_FACT_KEYS - _OBJECT_VALUE_FACT_KEYS)
    | (_OBSERVED_PREFERENCE_FACT_KEYS - _NUMBER_VALUE_FACT_KEYS)
    | (
        _INFERRED_PREFERENCE_FACT_KEYS
        | _INFERRED_BEHAVIOR_FACT_KEYS
    ) - _OBJECT_VALUE_FACT_KEYS
    | (_OBSERVED_BEHAVIOR_FACT_KEYS - _NUMBER_VALUE_FACT_KEYS - _LIST_VALUE_FACT_KEYS)
)


def _registered_value_types(fact_key: str) -> frozenset[str]:
    if fact_key == "commercial.has_valid_order":
        return frozenset({"boolean"})
    if fact_key in _NUMBER_VALUE_FACT_KEYS:
        return frozenset({"number"})
    if fact_key in _OBJECT_VALUE_FACT_KEYS:
        return frozenset({"object"})
    if fact_key in _LIST_VALUE_FACT_KEYS:
        return frozenset({"list"})
    if fact_key in _STRING_VALUE_FACT_KEYS:
        return frozenset({"string"})
    raise KeyError(f"Fact value type is not registered: {fact_key}")


def _registrations(
    fact_keys: frozenset[str],
    *,
    classification: DataClassification,
    sources: frozenset[SourceKey],
    ttl_days: int | None,
    purposes: frozenset[str] = _PROFILE_PURPOSES,
) -> dict[str, FactRegistration]:
    return {
        fact_key: FactRegistration(
            value_types=_registered_value_types(fact_key),
            data_classification=classification,
            allowed_sources=sources,
            ttl_days=ttl_days,
            conflict_key=fact_key,
            allowed_purposes=purposes,
            supports_high_impact=False,
        )
        for fact_key in sorted(fact_keys)
    }


_fact_registry: dict[str, FactRegistration] = {
    "business.industry": FactRegistration(
        value_types=_registered_value_types("business.industry"),
        data_classification=DataClassification.PUBLIC_BUSINESS,
        allowed_sources=_PUBLIC_FACT_SOURCES,
        ttl_days=365,
        conflict_key="business.industry",
        allowed_purposes=_PROFILE_PURPOSES,
        supports_high_impact=False,
    ),
    "commercial.has_valid_order": FactRegistration(
        value_types=_registered_value_types("commercial.has_valid_order"),
        data_classification=DataClassification.INTERNAL_BUSINESS,
        allowed_sources=frozenset({("okki", "order")}),
        ttl_days=None,
        conflict_key="commercial.has_valid_order",
        allowed_purposes=frozenset({"profile", "relationship_stage", "sales"}),
        supports_high_impact=True,
    ),
    "behavior.confirmed.priority": FactRegistration(
        value_types=_registered_value_types("behavior.confirmed.priority"),
        data_classification=DataClassification.INTERNAL_BUSINESS,
        allowed_sources=_MANUAL_SOURCE,
        ttl_days=180,
        conflict_key="behavior.confirmed.priority",
        allowed_purposes=_PROFILE_PURPOSES,
        supports_high_impact=False,
    ),
    "behavior.confirmed.relationship_note": FactRegistration(
        value_types=_registered_value_types("behavior.confirmed.relationship_note"),
        data_classification=DataClassification.RESTRICTED_INTERNAL,
        allowed_sources=_MANUAL_SOURCE,
        ttl_days=None,
        conflict_key="behavior.confirmed.relationship_note",
        allowed_purposes=frozenset({"profile"}),
        supports_high_impact=False,
    ),
}
_fact_registry.update(_registrations(
    _EXPRESSED_FACT_KEYS,
    classification=DataClassification.INTERNAL_BUSINESS,
    sources=_EXPRESSED_SOURCES,
    ttl_days=180,
))
_fact_registry.update(_registrations(
    _OBSERVED_PREFERENCE_FACT_KEYS,
    classification=DataClassification.INTERNAL_BUSINESS,
    sources=frozenset({("okki", "order")}),
    ttl_days=365,
))
_fact_registry.update(_registrations(
    _INFERRED_PREFERENCE_FACT_KEYS | _INFERRED_BEHAVIOR_FACT_KEYS,
    classification=DataClassification.INTERNAL_BUSINESS,
    sources=_AGENT_SOURCE,
    ttl_days=90,
))
_fact_registry.update(_registrations(
    _OBSERVED_BEHAVIOR_FACT_KEYS,
    classification=DataClassification.INTERNAL_BUSINESS,
    sources=_MESSAGE_SOURCES,
    ttl_days=180,
))
FACT_REGISTRY: Mapping[str, FactRegistration] = MappingProxyType(_fact_registry)
del _fact_registry


def validate_registered_fact(
    fact_key: str,
    source_system: str,
    source_entity_type: str,
) -> DataClassification:
    """Return the fact classification, failing closed for unknown combinations."""
    if not source_entity_type:
        raise ValueError("source_entity_type is required")

    registration = FACT_REGISTRY.get(fact_key)
    if registration is None:
        return DataClassification.RESTRICTED_INTERNAL

    source_key = (source_system, source_entity_type)
    source_registration = SOURCE_REGISTRY.get(source_key)
    if (
        source_key not in registration.allowed_sources
        or source_registration is None
        or fact_key not in source_registration.allowed_fact_keys
    ):
        return DataClassification.RESTRICTED_INTERNAL
    return max(
        registration.data_classification,
        source_registration.default_classification,
        key=_DATA_CLASSIFICATION_ORDER.index,
    )


@dataclass(frozen=True, slots=True)
class SourceRegistration:
    registry_version: str
    authority: str
    publisher_key_rule: str
    source_family_key_rule: str
    allowed_fact_keys: frozenset[str]
    default_classification: DataClassification
    ttl_days: int | None
    promotion_ceiling: Literal["candidate", "identified", "verified"]
    collection_legal_basis: str


SOURCE_REGISTRY_VERSION = "source_registry_v1"


SOURCE_REGISTRY: Mapping[tuple[str, str], SourceRegistration] = MappingProxyType({
    ("okki", "customer"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="transactional",
        publisher_key_rule="internal_source_account",
        source_family_key_rule="external_record_key",
        allowed_fact_keys=frozenset({"business.industry"}),
        default_classification=DataClassification.INTERNAL_BUSINESS,
        ttl_days=365,
        promotion_ceiling="verified",
        collection_legal_basis="authorized internal customer-system synchronization",
    ),
    ("okki", "contact"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="transactional",
        publisher_key_rule="internal_source_account",
        source_family_key_rule="external_contact_id",
        allowed_fact_keys=frozenset(),
        default_classification=DataClassification.PERSONAL_CONTACT,
        ttl_days=365,
        promotion_ceiling="identified",
        collection_legal_basis="authorized internal customer-system synchronization",
    ),
    ("okki", "order"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="transactional",
        publisher_key_rule="internal_source_account",
        source_family_key_rule="external_order_id",
        allowed_fact_keys=(
            _OBSERVED_PREFERENCE_FACT_KEYS | {"commercial.has_valid_order"}
        ),
        default_classification=DataClassification.INTERNAL_BUSINESS,
        ttl_days=None,
        promotion_ceiling="verified",
        collection_legal_basis="authorized internal order-system synchronization",
    ),
    ("okki", "order_item"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="transactional",
        publisher_key_rule="internal_source_account",
        source_family_key_rule="external_order_item_id",
        allowed_fact_keys=frozenset(),
        default_classification=DataClassification.INTERNAL_BUSINESS,
        ttl_days=None,
        promotion_ceiling="verified",
        collection_legal_basis="authorized internal order-system synchronization",
    ),
    ("alibaba", "inquiry"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="verified_platform",
        publisher_key_rule="platform_account",
        source_family_key_rule="external_inquiry_id",
        allowed_fact_keys=_EXPRESSED_FACT_KEYS,
        default_classification=DataClassification.INTERNAL_BUSINESS,
        ttl_days=180,
        promotion_ceiling="identified",
        collection_legal_basis="authorized business-account inquiry synchronization",
    ),
    ("alibaba", "message"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="verified_platform",
        publisher_key_rule="platform_account",
        source_family_key_rule="external_message_id",
        allowed_fact_keys=_EXPRESSED_FACT_KEYS | _OBSERVED_BEHAVIOR_FACT_KEYS,
        default_classification=DataClassification.RESTRICTED_INTERNAL,
        ttl_days=180,
        promotion_ceiling="identified",
        collection_legal_basis="authorized business-account message synchronization",
    ),
    ("email", "message"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="first_party",
        publisher_key_rule="business_mailbox_account",
        source_family_key_rule="external_message_id",
        allowed_fact_keys=_EXPRESSED_FACT_KEYS | _OBSERVED_BEHAVIOR_FACT_KEYS,
        default_classification=DataClassification.RESTRICTED_INTERNAL,
        ttl_days=180,
        promotion_ceiling="identified",
        collection_legal_basis="authorized business-mailbox synchronization",
    ),
    ("whatsapp", "message"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="first_party",
        publisher_key_rule="business_messaging_account",
        source_family_key_rule="external_message_id",
        allowed_fact_keys=_EXPRESSED_FACT_KEYS | _OBSERVED_BEHAVIOR_FACT_KEYS,
        default_classification=DataClassification.RESTRICTED_INTERNAL,
        ttl_days=180,
        promotion_ceiling="identified",
        collection_legal_basis="authorized business-messaging synchronization",
    ),
    ("agent", "research_report"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="first_party",
        publisher_key_rule="governed_agent_run",
        source_family_key_rule="evidence_set_hash",
        allowed_fact_keys=_INFERRED_PREFERENCE_FACT_KEYS | _INFERRED_BEHAVIOR_FACT_KEYS,
        default_classification=DataClassification.INTERNAL_BUSINESS,
        ttl_days=90,
        promotion_ceiling="candidate",
        collection_legal_basis="governed research run using registered evidence",
    ),
    ("manual", "customer"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="first_party",
        publisher_key_rule="authorized_ark_user",
        source_family_key_rule="audited_manual_entry",
        allowed_fact_keys=frozenset({
            "behavior.confirmed.priority",
            "behavior.confirmed.relationship_note",
        }),
        default_classification=DataClassification.RESTRICTED_INTERNAL,
        ttl_days=None,
        promotion_ceiling="verified",
        collection_legal_basis="authorized employee input with audit trail",
    ),
    ("public_web", "company_page"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="official_company",
        publisher_key_rule="registrable_domain",
        source_family_key_rule="canonical_content_hash",
        allowed_fact_keys=frozenset({"business.industry"}),
        default_classification=DataClassification.PUBLIC_BUSINESS,
        ttl_days=365,
        promotion_ceiling="candidate",
        collection_legal_basis="publicly accessible official business page",
    ),
    ("official_registry", "customer"): SourceRegistration(
        registry_version=SOURCE_REGISTRY_VERSION,
        authority="official_registry",
        publisher_key_rule="registry_authority",
        source_family_key_rule="registry_record_id",
        allowed_fact_keys=frozenset({"business.industry"}),
        default_classification=DataClassification.PUBLIC_BUSINESS,
        ttl_days=365,
        promotion_ceiling="verified",
        collection_legal_basis="public official business registry record",
    ),
})


def source_policy(source_system: str, source_entity_type: str) -> SourceRegistration:
    """Return the registered source policy, rejecting undeclared source types."""
    try:
        return SOURCE_REGISTRY[(source_system, source_entity_type)]
    except KeyError:
        raise KeyError(
            f"Unregistered source policy: {source_system}/{source_entity_type}",
        ) from None


def sources_are_independent(
    left_publisher_key: str | None,
    left_source_family_key: str | None,
    right_publisher_key: str | None,
    right_source_family_key: str | None,
) -> bool:
    """Require both distinct publishers and distinct source families."""
    return bool(
        left_publisher_key
        and left_source_family_key
        and right_publisher_key
        and right_source_family_key
        and left_publisher_key != right_publisher_key
        and left_source_family_key != right_source_family_key
    )


def allowed_relationship_transition(
    current_stage: str,
    target_stage: str,
    trigger: str,
    condition_met: bool,
    *,
    has_primary_assignment: bool = False,
    has_open_opportunity: bool = False,
) -> bool:
    """Evaluate the frozen relationship-stage transition matrix."""
    boolean_context = {
        "condition_met": condition_met,
        "has_primary_assignment": has_primary_assignment,
        "has_open_opportunity": has_open_opportunity,
    }
    for field, value in boolean_context.items():
        if type(value) is not bool:
            raise TypeError(f"{field} must be bool")

    try:
        current = RelationshipStage(current_stage)
        target = RelationshipStage(target_stage)
    except ValueError:
        return False

    if current is RelationshipStage.ACTIVE_CUSTOMER and target is current:
        return bool(
            trigger in {
                "valid_order",
                "historical_order_replay",
                "qualification_approved",
                "new_product_opportunity",
            }
            and condition_met
        )

    if target is RelationshipStage.INACTIVE and current is not target:
        return trigger == "manual_inactivation" and condition_met

    if current is RelationshipStage.DISCOVERED and target is RelationshipStage.QUALIFIED:
        return trigger == "qualification_approved" and condition_met

    if current is RelationshipStage.QUALIFIED and target is RelationshipStage.DEVELOPING:
        return bool(
            trigger == "sales_development_ready"
            and condition_met
            and has_primary_assignment
            and has_open_opportunity
        )

    if current is RelationshipStage.DEVELOPING and target is RelationshipStage.QUALIFIED:
        return trigger == "opportunities_closed_keep_qualified" and condition_met

    if target is RelationshipStage.ACTIVE_CUSTOMER:
        if current is RelationshipStage.INACTIVE:
            return trigger == "valid_order" and condition_met
        if current in {
            RelationshipStage.DISCOVERED,
            RelationshipStage.QUALIFIED,
            RelationshipStage.DEVELOPING,
        }:
            return trigger in {"valid_order", "historical_order_replay"} and condition_met

    if current is RelationshipStage.INACTIVE and target is RelationshipStage.DEVELOPING:
        return bool(
            trigger == "manual_reactivation"
            and condition_met
            and has_primary_assignment
            and has_open_opportunity
        )

    return False
