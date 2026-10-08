import pytest
from fastapi import HTTPException
from sqlalchemy import Column, Integer, MetaData, Table, event

from test_upstream_authority import upstream_db, authorization_db, binding_db
from app.auth import admin_router
from app.auth.models import ArkUserExternalBinding, ArkExternalBindingCandidate
from app.insight import external_binding_service as bindings
from app.portal.models import AuthorityBarrier


@pytest.mark.parametrize("operation", ["create", "delete", "candidate"])
def test_external_binding_routes_reject_revoked_admin(upstream_db, operation):
    db = upstream_db
    actor = {"sub": "1", "roles": ["super_admin"]}
    calls = {
        "create": lambda: admin_router.create_user_binding(1, "okki", "123", None, False, db, actor),
        "delete": lambda: admin_router.delete_user_binding(1, 999, db, actor),
        "candidate": lambda: admin_router.bind_candidate_endpoint(999, 1, db, actor),
    }
    with pytest.raises(HTTPException) as error:
        calls[operation]()
    assert error.value.status_code == 403


def test_binding_create_and_delete_have_atomic_barrier(upstream_db):
    db = upstream_db
    metadata = MetaData()
    for model in (ArkUserExternalBinding, ArkExternalBindingCandidate):
        Table(model.__tablename__, metadata, *(Column(c.name, Integer() if c.primary_key else c.type,
            primary_key=c.primary_key, nullable=c.nullable) for c in model.__table__.columns))
    metadata.create_all(db.get_bind())
    statements = []
    def capture(connection, cursor, sql, params, context, many):
        statements.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        row = bindings.create_binding(db, 1, "okki", "external-123", created_by=1)
        assert AuthorityBarrier.__tablename__ in statements[0]
        db.commit()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    identifier = row.id
    before = db.get(AuthorityBarrier, "authority").version
    db.commit()
    bindings.delete_binding(db, identifier)
    db.rollback()
    assert row.binding_status == "active" and row.deleted_at is None
    assert db.get(AuthorityBarrier, "authority").version == before
    db.commit()
    bindings.delete_binding(db, identifier)
    db.commit()
    assert row.binding_status == "inactive" and row.deleted_at is not None
