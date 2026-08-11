from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import Base, get_db
from app.knowledge import router
from app.knowledge.models import (
    KnowledgeApprovalRequest,
    KnowledgeAuditLog,
    KnowledgeDocument,
    KnowledgeLibrary,
    KnowledgeLibraryMember,
    KnowledgeRevision,
)


def test_permission_seed_contains_all_knowledge_capabilities():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "app/auth/service.py").read_text(encoding="utf-8")
    for code in ("knowledge:read", "knowledge:write", "knowledge:review", "knowledge:admin"):
        assert f'("{code}"' in source


TABLES = [
    ArkUser.__table__, KnowledgeLibrary.__table__, KnowledgeLibraryMember.__table__, KnowledgeDocument.__table__,
    KnowledgeRevision.__table__, KnowledgeApprovalRequest.__table__, KnowledgeAuditLog.__table__,
]


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    db.add_all([
        ArkUser(
            id=user_id,
            username=f"user-{user_id}",
            real_name=f"用户{user_id}",
            password_hash="test-only",
            is_active=user_id != 9,
        )
        for user_id in range(1, 11)
    ])
    db.commit()
    app = FastAPI()
    app.include_router(router.router, prefix="/api/knowledge")
    app.dependency_overrides[get_db] = lambda: db
    identity = {"sub": "1", "username": "admin", "roles": [], "permissions": ["knowledge:admin"]}
    app.dependency_overrides[get_current_user] = lambda: identity
    return TestClient(app), db, identity, engine


def test_http_workflow_uses_envelope_and_published_search():
    client, db, identity, engine = _setup()
    try:
        library = client.post(
            "/api/knowledge/libraries", json={"name": "产品知识", "category": "company"}
        )
        assert library.status_code == 200, library.text
        assert library.json()["code"] == 200
        library_id = library.json()["data"]["id"]

        document = client.post(f"/api/knowledge/libraries/{library_id}/documents", json={
            "title": "洗护流程",
            "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "温水清洗"}]}]},
        })
        assert document.status_code == 200, document.text
        document_id = document.json()["data"]["id"]

        submitted = client.post(f"/api/knowledge/documents/{document_id}/submit")
        assert submitted.status_code == 200, submitted.text
        approval_id = submitted.json()["data"]["id"]
        approved = client.post(f"/api/knowledge/approvals/{approval_id}/approve", json={"remark": "ok"})
        assert approved.status_code == 200, approved.text

        result = client.get("/api/knowledge/search", params={"q": "温水"})
        assert result.status_code == 200
        assert result.json()["data"][0]["document_id"] == document_id
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_unauthorized_library_is_404_not_metadata_leak():
    client, db, identity, engine = _setup()
    try:
        library_id = client.post(
            "/api/knowledge/libraries", json={"name": "机密", "category": "company"}
        ).json()["data"]["id"]
        identity.update({"sub": "2", "permissions": ["knowledge:read"]})
        response = client.get(f"/api/knowledge/libraries/{library_id}")
        assert response.status_code == 404
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_delete_folder_endpoint_returns_counts_and_hides_descendants():
    client, db, identity, engine = _setup()
    try:
        library_id = client.post(
            "/api/knowledge/libraries", json={"name": "Operations", "category": "company"}
        ).json()["data"]["id"]
        folder_id = client.post(f"/api/knowledge/libraries/{library_id}/documents", json={
            "title": "Archive", "node_type": "folder",
        }).json()["data"]["id"]
        document_id = client.post(f"/api/knowledge/libraries/{library_id}/documents", json={
            "title": "Checklist",
            "parent_id": folder_id,
            "content": {"type": "doc", "content": [{"type": "paragraph"}]},
        }).json()["data"]["id"]

        deleted = client.delete(f"/api/knowledge/documents/{folder_id}")

        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["data"] == {
            "id": folder_id,
            "folder_count": 1,
            "document_count": 1,
            "cancelled_approval_count": 0,
        }
        assert client.get(f"/api/knowledge/documents/{document_id}").status_code == 404
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_delete_library_endpoint_hides_library():
    client, db, identity, engine = _setup()
    try:
        library_id = client.post(
            "/api/knowledge/libraries", json={"name": "Retired", "category": "company"}
        ).json()["data"]["id"]

        deleted = client.delete(f"/api/knowledge/libraries/{library_id}")

        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["data"]["id"] == library_id
        assert client.get(f"/api/knowledge/libraries/{library_id}").status_code == 404
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_library_category_is_required_and_department_round_trips():
    client, db, identity, engine = _setup()
    try:
        missing = client.post("/api/knowledge/libraries", json={"name": "Missing category"})
        assert missing.status_code == 422

        created = client.post(
            "/api/knowledge/libraries",
            json={"name": "Department library", "category": "department"},
        )
        assert created.status_code == 200, created.text
        assert created.json()["data"]["category"] == "department"

        identity["permissions"] = ["knowledge:read"]
        listed = client.get("/api/knowledge/libraries")
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"] == [{
            "id": created.json()["data"]["id"],
            "name": "Department library",
            "description": None,
            "category": "department",
            "role": "admin",
        }]
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_member_endpoints_use_ark_user_profiles_without_sensitive_fields():
    client, db, identity, engine = _setup()
    try:
        library_id = client.post(
            "/api/knowledge/libraries", json={"name": "Company", "category": "company"}
        ).json()["data"]["id"]
        replaced = client.put(f"/api/knowledge/libraries/{library_id}/members", json={
            "members": [{"user_id": 3, "role": "viewer"}],
        })
        assert replaced.status_code == 200, replaced.text

        members = client.get(f"/api/knowledge/libraries/{library_id}/members")
        assert members.status_code == 200, members.text
        assert members.json()["data"] == [
            {"user_id": 1, "username": "user-1", "real_name": "用户1", "role": "admin"},
            {"user_id": 3, "username": "user-3", "real_name": "用户3", "role": "viewer"},
        ]

        candidates = client.get(
            f"/api/knowledge/libraries/{library_id}/member-candidates",
            params={"q": "user-3", "limit": 20},
        )
        assert candidates.status_code == 200, candidates.text
        assert candidates.json()["data"] == [
            {"user_id": 3, "username": "user-3", "real_name": "用户3"}
        ]
        assert set(candidates.json()["data"][0]) == {"user_id", "username", "real_name"}

        identity.update({"sub": "2", "permissions": ["knowledge:admin"]})
        forbidden = client.get(f"/api/knowledge/libraries/{library_id}/member-candidates")
        assert forbidden.status_code == 404
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_replace_members_returns_invalid_user_ids_for_row_level_correction():
    client, db, identity, engine = _setup()
    try:
        library_id = client.post(
            "/api/knowledge/libraries", json={"name": "Company", "category": "company"}
        ).json()["data"]["id"]

        response = client.put(f"/api/knowledge/libraries/{library_id}/members", json={
            "members": [{"user_id": 9, "role": "viewer"}],
        })

        assert response.status_code == 422
        assert response.json()["detail"] == {
            "message": "knowledge member user is inactive or missing",
            "invalid_user_ids": [9],
        }
    finally:
        client.close()
        db.close()
        engine.dispose()
