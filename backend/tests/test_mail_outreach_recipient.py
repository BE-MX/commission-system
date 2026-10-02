from dataclasses import replace

import pytest

from app.customer.models import CustomerContact, CustomerContactPoint
from app.mail_outreach.errors import MailOutreachError
from app.mail_outreach.recipient_service import prepare_recipient
from tests.mail_outreach_helpers import seed_graph


def payload(**changes):
    result = dict(display_name="Purchasing team", email="hello@acme.com", language_tag="en", timezone="America/New_York", country_code="US", source_url="https://acme.com/contact", verification_basis="Manually reviewed company contact page", verified=False, contact_allowed=False)
    result.update(changes)
    return result


def test_public_email_is_not_automatically_verified_and_replay_is_unique(db):
    graph = seed_graph(db)
    user = {"sub": str(graph.user.id)}
    first = prepare_recipient(db, graph.access, user, payload())
    second = prepare_recipient(db, graph.access, user, payload(verified=True, contact_allowed=True))
    assert first["verification_status"] == "unknown"
    assert first["contactability_status"] == "unknown"
    assert first["contact_point_id"] == second["contact_point_id"]
    point = db.get(CustomerContactPoint, first["contact_point_id"])
    assert point.data_classification == "personal_contact"
    assert point.verification_status == "valid"
    assert point.contactability_status == "allowed"
    assert db.query(CustomerContact).count() == 2
    assert graph.customer.profile_input_seq >= 1


def test_existing_blocked_address_cannot_be_reenabled(db):
    graph = seed_graph(db, contactability_status="opted_out")
    with pytest.raises(MailOutreachError) as error:
        prepare_recipient(db, graph.access, {"sub": str(graph.user.id)}, payload(email=graph.point.normalized_value, verified=True, contact_allowed=True))
    assert error.value.error_code == "recipient_suppressed"
    assert graph.point.contactability_status == "opted_out"


def test_recipient_requires_personal_data_access_and_preserves_direct_verification_basis(db):
    graph = seed_graph(db)
    access = replace(graph.access, max_data_classification="public_business")
    with pytest.raises(MailOutreachError):
        prepare_recipient(db, access, {"sub": str(graph.user.id)}, payload())
    result = prepare_recipient(db, graph.access, {"sub": str(graph.user.id)},
        payload(source_url=None, verification_basis="Recipient provided this address directly"))
    from app.customer.models import CustomerSourceRecord
    point = db.get(CustomerContactPoint, result["contact_point_id"])
    source = db.get(CustomerSourceRecord, point.source_record_id)
    assert source.payload_json["verification_basis"] == "Recipient provided this address directly"
    assert source.source_url is None
    assert result["verification_status"] == "unknown"


def test_source_fact_identity_cannot_be_downgraded(db):
    from app.customer.models import CustomerSourceRecord
    graph = seed_graph(db)
    graph.fact.fact_key = "research.source.business_contact"
    graph.fact.value_json = {"email": "hello@acme.com"}
    graph.fact.data_classification = "restricted_internal"
    graph.fact.visibility_scope = "management"
    db.flush()
    result = prepare_recipient(db, graph.access, {"sub": str(graph.user.id)}, payload(source_fact_id=graph.fact.id, source_url=None))
    point = db.get(CustomerContactPoint, result["contact_point_id"])
    source = db.get(CustomerSourceRecord, point.source_record_id)
    assert point.data_classification == "restricted_internal"
    assert source.data_classification == "restricted_internal"
    assert source.visibility_scope == "management"
