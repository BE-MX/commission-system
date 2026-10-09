"""Exercise real upstream identity/ownership SQL predicates against isolated rows.

Upstream table columns use model types, but unrelated upstream constraints are
not reproduced here; production schema/concurrency remains a MySQL test gate.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.models import (CustomerAccount, CustomerAssignment,
    CustomerExternalIdentity, CustomerObjectOwnership, CustomerContact, CustomerSourceRecord, CustomerContactRelationship)
from app.portal.access_policy import binding_fingerprint, validate_binding
from app.portal.errors import PortalError


@pytest.fixture
def binding_db():
    metadata = MetaData()
    models = (CustomerAccount, CustomerAssignment, CustomerExternalIdentity,
              CustomerObjectOwnership, CustomerContact, CustomerSourceRecord, CustomerContactRelationship, ArkUser)
    for model in models:
        Table(model.__tablename__, metadata, *(Column(c.name, c.type,
            primary_key=c.primary_key, nullable=not c.primary_key) for c in model.__table__.columns))
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with Session(engine) as db:
        now = beijing_now()
        db.execute(metadata.tables[CustomerAccount.__tablename__].insert(),
                   {"id": 1, "record_status": "active", "identity_status": "verified"})
        db.execute(metadata.tables[ArkUser.__tablename__].insert(), {"id": 1, "is_active": True})
        db.execute(metadata.tables[CustomerExternalIdentity.__tablename__].insert(),
            {"id": 1, "customer_id": 1, "source_system": "okki", "identifier_type": "company_id",
             "status": "active", "verification_status": "verified", "cardinality": "one_to_one",
             "identity_strength": "strong", "source_account_key": "tenant-1", "normalized_value": "501"})
        db.execute(metadata.tables[CustomerAssignment.__tablename__].insert(),
            {"id": 1, "customer_id": 1, "user_id": 1, "assignment_role": "primary",
             "assignment_status": "active", "effective_from": now - timedelta(days=1)})
        db.commit()
        identity = db.get(CustomerExternalIdentity, 1)
        assignment = db.get(CustomerAssignment, 1)
        access = SimpleNamespace(customer_id=1, external_identity_id=1, assignment_id=1,
            sales_user_id=1, okki_namespace="tenant-1", okki_company_id="501",
            binding_fingerprint=binding_fingerprint(1, identity, assignment))
        yield db, access, metadata
    engine.dispose()


def test_exact_verified_identity_and_primary_owner_accept(binding_db):
    db, access, _ = binding_db
    validate_binding(db, access)


@pytest.mark.parametrize("model,field,value", [
    (CustomerAccount, "record_status", "merged"),
    (CustomerAccount, "identity_status", "disputed"),
    (CustomerExternalIdentity, "verification_status", "candidate"),
    (CustomerExternalIdentity, "cardinality", "one_to_many"),
    (CustomerExternalIdentity, "identity_strength", "weak"),
    (CustomerExternalIdentity, "source_account_key", "another-tenant"),
    (CustomerExternalIdentity, "normalized_value", "another-company"),
    (CustomerAssignment, "user_id", 2),
    (CustomerAssignment, "assignment_role", "collaborator"),
    (CustomerAssignment, "assignment_status", "inactive"),
    (ArkUser, "is_active", False),
])
def test_binding_rejects_upstream_authority_changes(binding_db, model, field, value):
    db, access, metadata = binding_db
    table = metadata.tables[model.__tablename__]
    db.execute(table.update().where(table.c.id == 1).values({field: value}))
    db.commit()
    with pytest.raises(PortalError):
        validate_binding(db, access)


def test_logical_identity_transfer_does_not_follow_new_customer(binding_db):
    db, access, metadata = binding_db
    db.execute(metadata.tables[CustomerObjectOwnership.__tablename__].insert(),
        {"object_type": "external_identity", "object_id": 1, "storage_customer_id": 1,
         "current_customer_id": 2})
    db.commit()
    with pytest.raises(PortalError) as error:
        validate_binding(db, access)
    assert error.value.code == "IDENTITY_REVIEW_REQUIRED"


def test_evidence_refresh_does_not_change_binding(binding_db):
    db, access, metadata = binding_db
    table = metadata.tables[CustomerExternalIdentity.__tablename__]
    db.execute(table.update().where(table.c.id == 1).values(last_seen_at=beijing_now(), confidence="0.98"))
    db.commit()
    validate_binding(db, access)
