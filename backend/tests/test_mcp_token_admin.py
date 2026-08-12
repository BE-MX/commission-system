from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.core.database import Base, get_db
from app.knowledge.models import KnowledgeLibrary, KnowledgeLibraryMember
from app.mcp.models import MCPToken
from app.mcp.token_admin import router


TABLES = [
    ArkUser.__table__,
    ArkRole.__table__,
    ArkPermission.__table__,
    ArkUserRole.__table__,
    ArkRolePermission.__table__,
    KnowledgeLibrary.__table__,
    KnowledgeLibraryMember.__table__,
    MCPToken.__table__,
]


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()

    read_permission = ArkPermission(
        id=1, code="knowledge:read", module="knowledge", action="read", label="Knowledge read"
    )
    reader_role = ArkRole(id=1, name="reader", label="Reader", permissions=[read_permission])
    ready = ArkUser(
        id=2, username="ready", real_name="Ready User", password_hash="test", roles=[reader_role]
    )
    no_access = ArkUser(id=3, username="plain", real_name="Plain User", password_hash="test")
    inactive = ArkUser(
        id=4, username="inactive", real_name="Inactive User", password_hash="test", is_active=False
    )
    library = KnowledgeLibrary(id=1, name="Sales", category="company", created_by=1)
    db.add_all([ready, no_access, inactive, library])
    db.flush()
    db.add(KnowledgeLibraryMember(library_id=1, user_id=2, role="viewer", created_by=1))
    db.add_all([
        MCPToken(id=1, token_hash="old-hash", user_id=2, label="Sales bot", is_active=True),
        MCPToken(id=2, token_hash="revoked-hash", user_id=2, label="Old bot", is_active=False),
    ])
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/mcp")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1", "roles": [], "permissions": ["mcp:admin"]
    }
    return TestClient(app), db, engine


def test_candidates_return_active_users_with_access_summary():
    client, db, engine = _setup()
    try:
        response = client.get("/api/mcp/token-candidates", params={"q": "user"})
        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert [item["username"] for item in items] == ["plain", "ready"]
        ready = next(item for item in items if item["username"] == "ready")
        assert ready["has_knowledge_read"] is True
        assert ready["knowledge_library_count"] == 1
        assert ready["active_token_count"] == 1
        plain = next(item for item in items if item["username"] == "plain")
        assert plain["has_knowledge_read"] is False
        assert plain["knowledge_library_count"] == 0
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_issue_requires_active_user_and_non_blank_label():
    client, db, engine = _setup()
    try:
        assert client.post("/api/mcp/tokens", json={"user_id": 4, "label": "Inactive bot"}).status_code == 400
        assert client.post("/api/mcp/tokens", json={"user_id": 2, "label": "  "}).status_code == 422

        issued = client.post("/api/mcp/tokens", json={"user_id": 2, "label": "Knowledge agent"})
        assert issued.status_code == 200, issued.text
        assert issued.json()["data"]["token"]

        listed = client.get("/api/mcp/tokens").json()["data"]["items"]
        created = next(row for row in listed if row["label"] == "Knowledge agent")
        assert "token" not in created
        assert created["real_name"] == "Ready User"
        assert created["knowledge_library_count"] == 1
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_rotate_replaces_active_token_and_revokes_old_token():
    client, db, engine = _setup()
    try:
        response = client.post("/api/mcp/tokens/1/rotate")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["id"] != 1
        assert data["replaced_token_id"] == 1
        assert data["token"]

        db.expire_all()
        assert db.query(MCPToken).filter(MCPToken.id == 1).one().is_active is False
        replacement = db.query(MCPToken).filter(MCPToken.id == data["id"]).one()
        assert replacement.is_active is True
        assert replacement.label == "Sales bot"

        second = client.post("/api/mcp/tokens/1/rotate")
        assert second.status_code == 409
    finally:
        client.close()
        db.close()
        engine.dispose()
