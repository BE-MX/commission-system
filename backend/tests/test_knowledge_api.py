from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
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
    KnowledgeLibrary.__table__, KnowledgeLibraryMember.__table__, KnowledgeDocument.__table__,
    KnowledgeRevision.__table__, KnowledgeApprovalRequest.__table__, KnowledgeAuditLog.__table__,
]


def _setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(router.router, prefix="/api/knowledge")
    app.dependency_overrides[get_db] = lambda: db
    identity = {"sub": "1", "username": "admin", "roles": [], "permissions": ["knowledge:admin"]}
    app.dependency_overrides[get_current_user] = lambda: identity
    return TestClient(app), db, identity, engine


def test_http_workflow_uses_envelope_and_published_search():
    client, db, identity, engine = _setup()
    try:
        library = client.post("/api/knowledge/libraries", json={"name": "产品知识"})
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
        library_id = client.post("/api/knowledge/libraries", json={"name": "机密"}).json()["data"]["id"]
        identity.update({"sub": "2", "permissions": ["knowledge:read"]})
        response = client.get(f"/api/knowledge/libraries/{library_id}")
        assert response.status_code == 404
    finally:
        client.close()
        db.close()
        engine.dispose()
