from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import ArkUser
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.core.database import Base
from app.knowledge.models import (
    KnowledgeApprovalRequest,
    KnowledgeAsset,
    KnowledgeAuditLog,
    KnowledgeDocument,
    KnowledgeLibrary,
    KnowledgeLibraryMember,
    KnowledgeRevision,
    KnowledgeRevisionAsset,
    KnowledgeAiJob,
    KnowledgeAiJobSource,
    KnowledgeAiProfile,
    KnowledgeAiProfileLog,
    KnowledgeAiProfileSource,
    KnowledgeAiProfileTarget,
)
from app.knowledge import service


TABLES = [
    ArkUser.__table__,
    KnowledgeLibrary.__table__,
    KnowledgeLibraryMember.__table__,
    KnowledgeDocument.__table__,
    KnowledgeRevision.__table__,
    KnowledgeAsset.__table__,
    KnowledgeRevisionAsset.__table__,
    AiProvider.__table__,
    AiPreset.__table__,
    AiCallLog.__table__,
    KnowledgeAiProfile.__table__,
    KnowledgeAiProfileLog.__table__,
    KnowledgeAiProfileSource.__table__,
    KnowledgeAiProfileTarget.__table__,
    KnowledgeAiJob.__table__,
    KnowledgeAiJobSource.__table__,
    KnowledgeApprovalRequest.__table__,
    KnowledgeAuditLog.__table__,
]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=TABLES)
    session = sessionmaker(bind=engine)()
    session.add_all([
        ArkUser(
            id=user_id,
            username=f"user-{user_id}",
            real_name=f"用户{user_id}",
            password_hash="test-only",
            is_active=user_id != 9,
        )
        for user_id in range(1, 11)
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def identity(user_id, permissions=(), roles=()):
    return {"sub": str(user_id), "username": f"user-{user_id}", "permissions": list(permissions), "roles": list(roles)}


def doc_json(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def test_model_contract_has_required_tables_and_unique_keys():
    assert {
        "ark_users",
        "ark_knowledge_libraries",
        "ark_knowledge_library_members",
        "ark_knowledge_documents",
        "ark_knowledge_revisions",
        "ark_knowledge_approval_requests",
        "ark_knowledge_audit_logs",
    }.issubset({table.name for table in TABLES})
    member_uniques = {tuple(c.name for c in item.columns) for item in KnowledgeLibraryMember.__table__.constraints if hasattr(item, "columns")}
    revision_uniques = {tuple(c.name for c in item.columns) for item in KnowledgeRevision.__table__.constraints if hasattr(item, "columns")}
    assert ("library_id", "user_id") in member_uniques
    assert ("document_id", "version_no") in revision_uniques
    assert "pending_approval_id" in KnowledgeDocument.__table__.columns
    approval_uniques = {tuple(c.name for c in item.columns) for item in KnowledgeApprovalRequest.__table__.constraints if hasattr(item, "columns")}
    assert ("document_id", "pending_slot") in approval_uniques


def test_library_category_round_trips_and_rejects_invalid_value(db):
    admin = identity(1, ["knowledge:admin", "knowledge:read"])
    created = {
        category: service.create_library(
            db, admin, name=f"{category} library", category=category
        )
        for category in ("company", "department", "personal")
    }

    listed = {item["id"]: item["category"] for item in service.list_libraries(db, admin)}
    assert listed == {library.id: category for category, library in created.items()}
    for category, library in created.items():
        assert library.category == category
        assert service.get_library(db, admin, library.id)["category"] == category

    with pytest.raises(service.ValidationError, match="invalid knowledge library category"):
        service.create_library(db, admin, name="Team library", category="team")


def test_library_acl_is_real_time_and_creator_is_admin(db):
    admin = identity(1, ["knowledge:admin"])
    viewer = identity(2, ["knowledge:read"])
    library = service.create_library(db, admin, name="销售知识", category="company", description="内部资料")

    assert service.list_libraries(db, admin)[0]["role"] == "admin"
    assert service.list_libraries(db, viewer) == []

    service.replace_members(db, admin, library.id, [{"user_id": 2, "role": "viewer"}])
    assert service.list_libraries(db, viewer)[0]["role"] == "viewer"
    assert {item["user_id"] for item in service.list_members(db, admin, library.id)} == {1, 2}

    service.replace_members(db, admin, library.id, [])
    assert service.list_libraries(db, viewer) == []
    with pytest.raises(service.NotFoundError):
        service.get_library(db, viewer, library.id)


def test_library_members_use_active_ark_user_profiles(db):
    admin = identity(1, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Company", category="company")
    service.replace_members(db, admin, library.id, [{"user_id": 3, "role": "viewer"}])

    assert service.list_members(db, admin, library.id) == [
        {"user_id": 1, "username": "user-1", "real_name": "用户1", "role": "admin"},
        {"user_id": 3, "username": "user-3", "real_name": "用户3", "role": "viewer"},
    ]
    assert service.search_member_candidates(db, admin, library.id, "user-3", limit=20) == [
        {"user_id": 3, "username": "user-3", "real_name": "用户3"}
    ]


def test_non_member_platform_admin_cannot_search_member_candidates(db):
    admin = identity(1, ["knowledge:admin"])
    outsider = identity(2, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Company", category="company")

    with pytest.raises(service.NotFoundError):
        service.search_member_candidates(db, outsider, library.id, "", limit=20)


def test_replace_members_rejects_duplicate_user_ids(db):
    admin = identity(1, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Company", category="company")

    with pytest.raises(service.ValidationError, match="duplicate"):
        service.replace_members(db, admin, library.id, [
            {"user_id": 3, "role": "viewer"},
            {"user_id": 3, "role": "editor"},
        ])


@pytest.mark.parametrize("user_id", [9, 999])
def test_replace_members_rejects_inactive_or_missing_users(db, user_id):
    admin = identity(1, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Company", category="company")

    with pytest.raises(service.InvalidMembersError, match="inactive or missing") as caught:
        service.replace_members(db, admin, library.id, [{"user_id": user_id, "role": "viewer"}])
    assert caught.value.invalid_user_ids == [user_id]


def test_replace_members_rejects_deleted_users(db):
    admin = identity(1, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Company", category="company")
    db.query(ArkUser).filter(ArkUser.id == 8).update({
        ArkUser.deleted_at: datetime(2026, 1, 2, 3, 4, 5)
    }, synchronize_session=False)
    db.commit()

    with pytest.raises(service.ValidationError, match="inactive or missing"):
        service.replace_members(db, admin, library.id, [{"user_id": 8, "role": "viewer"}])


def test_member_candidate_search_excludes_deleted_users(db):
    admin = identity(1, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Company", category="company")
    db.query(ArkUser).filter(ArkUser.id == 8).update({
        ArkUser.deleted_at: datetime(2026, 1, 2, 3, 4, 5)
    }, synchronize_session=False)
    db.commit()

    assert service.search_member_candidates(db, admin, library.id, "user-8", limit=20) == []


def test_member_candidate_service_caps_limit_at_twenty(db):
    admin = identity(1, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Company", category="company")
    db.add_all([
        ArkUser(
            id=user_id,
            username=f"extra-{user_id}",
            password_hash="test-only",
            real_name=f"额外用户{user_id}",
            is_active=True,
        )
        for user_id in range(11, 32)
    ])
    db.commit()

    results = service.search_member_candidates(db, admin, library.id, "", limit=999)

    assert len(results) == 20


def test_approval_publishes_frozen_revision_not_later_draft(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:review", "knowledge:read"])
    editor = identity(2, ["knowledge:write", "knowledge:read"])
    reviewer = identity(3, ["knowledge:review", "knowledge:read"])
    viewer = identity(4, ["knowledge:read"])
    library = service.create_library(db, admin, name="产品知识", category="company")
    service.replace_members(db, admin, library.id, [
        {"user_id": 2, "role": "editor"},
        {"user_id": 3, "role": "reviewer"},
        {"user_id": 4, "role": "viewer"},
    ])
    document = service.create_document(db, editor, library.id, title="发制品", content=doc_json("冻结版本"))
    approval = service.submit_document(db, editor, document.id)
    service.save_document(db, editor, document.id, title="发制品", content=doc_json("后续草稿"))

    review_detail = service.get_approval_detail(db, reviewer, approval.id)
    assert review_detail["content_text"] == "冻结版本"

    service.approve_request(db, reviewer, approval.id, remark="通过")
    published = service.get_published_document(db, viewer, document.id)
    assert published["content_text"] == "冻结版本"
    assert service.search_published(db, viewer, "后续草稿") == []
    assert service.search_published(db, viewer, "冻结版本")[0]["document_id"] == document.id


def test_reject_requires_reason_and_clears_pending(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:review", "knowledge:read"])
    library = service.create_library(db, admin, name="制度", category="company")
    document = service.create_document(db, admin, library.id, title="流程", content=doc_json("待审"))
    approval = service.submit_document(db, admin, document.id)
    with pytest.raises(service.ValidationError):
        service.reject_request(db, admin, approval.id, remark="")
    service.reject_request(db, admin, approval.id, remark="需要补充")
    db.refresh(document)
    assert document.pending_approval_id is None


def test_viewer_tree_hides_unpublished_structure(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:review", "knowledge:read"])
    viewer = identity(2, ["knowledge:read"])
    library = service.create_library(db, admin, name="Private structure", category="company")
    service.replace_members(db, admin, library.id, [{"user_id": 2, "role": "viewer"}])
    hidden_folder = service.create_folder(db, admin, library.id, title="Secret roadmap")
    visible_folder = service.create_folder(db, admin, library.id, title="Published guidance")
    document = service.create_document(
        db, admin, library.id, title="Public handbook", content=doc_json("approved content"), parent_id=visible_folder.id
    )
    approval = service.submit_document(db, admin, document.id)
    service.approve_request(db, admin, approval.id)

    viewer_tree = service.get_tree(db, viewer, library.id)
    assert {item["id"] for item in viewer_tree} == {visible_folder.id, document.id}
    assert hidden_folder.id not in {item["id"] for item in viewer_tree}


def test_search_applies_acl_before_limit(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:review", "knowledge:read"])
    viewer = identity(2, ["knowledge:read"])
    hidden = service.create_library(db, admin, name="Hidden", category="company")
    visible = service.create_library(db, admin, name="Visible", category="company")
    service.replace_members(db, admin, visible.id, [{"user_id": 2, "role": "viewer"}])

    for index in range(6):
        document = service.create_document(db, admin, hidden.id, title=f"match {index}", content=doc_json("needle"))
        service.approve_request(db, admin, service.submit_document(db, admin, document.id).id)
    allowed = service.create_document(db, admin, visible.id, title="allowed", content=doc_json("needle"))
    service.approve_request(db, admin, service.submit_document(db, admin, allowed.id).id)

    assert service.search_published(db, viewer, "needle", limit=1)[0]["document_id"] == allowed.id


def test_concurrent_pending_approval_becomes_conflict(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:read"])
    library = service.create_library(db, admin, name="Approvals", category="company")
    document = service.create_document(db, admin, library.id, title="Policy", content=doc_json("draft"))
    db.add(KnowledgeApprovalRequest(
        document_id=document.id,
        revision_id=document.draft_revision_id,
        submitted_by=1,
        pending_slot=1,
    ))
    db.commit()

    with pytest.raises(service.ConflictError):
        service.submit_document(db, admin, document.id)


def test_folder_parent_must_be_same_library_folder(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:read"])
    first = service.create_library(db, admin, name="First", category="company")
    second = service.create_library(db, admin, name="Second", category="company")
    foreign_folder = service.create_folder(db, admin, second.id, title="Foreign")

    with pytest.raises(service.ValidationError):
        service.create_folder(db, admin, first.id, title="Invalid", parent_id=foreign_folder.id)


def test_delete_folder_soft_deletes_subtree_and_cancels_pending_approval(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:read"])
    editor = identity(2, ["knowledge:write", "knowledge:read"])
    library = service.create_library(db, admin, name="Operations", category="company")
    service.replace_members(db, admin, library.id, [{"user_id": 2, "role": "editor"}])
    root = service.create_folder(db, editor, library.id, title="Root")
    child = service.create_folder(db, editor, library.id, title="Child", parent_id=root.id)
    document = service.create_document(
        db, editor, library.id, title="Checklist", content=doc_json("pending"), parent_id=child.id
    )
    approval = service.submit_document(db, editor, document.id)

    result = service.delete_node(db, editor, root.id)

    assert result == {
        "id": root.id,
        "folder_count": 2,
        "document_count": 1,
        "cancelled_approval_count": 1,
    }
    for node in (root, child, document):
        db.refresh(node)
        assert node.deleted_at is not None
    db.refresh(approval)
    assert approval.status == "cancelled"
    assert approval.pending_slot is None
    assert approval.reviewed_by == 2
    assert approval.remark == "content deleted"
    assert document.pending_approval_id is None
    audit = db.query(KnowledgeAuditLog).filter(KnowledgeAuditLog.action == "delete_folder").one()
    assert audit.object_id == root.id
    assert audit.detail == {
        "folder_count": 2,
        "document_count": 1,
        "cancelled_approval_count": 1,
    }


def test_delete_node_requires_platform_write_and_library_write_role(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:read"])
    platform_editor = identity(2, ["knowledge:write", "knowledge:read"])
    no_platform_write = identity(3, ["knowledge:read"])
    library = service.create_library(db, admin, name="Policies", category="company")
    service.replace_members(db, admin, library.id, [
        {"user_id": 2, "role": "viewer"},
        {"user_id": 3, "role": "editor"},
    ])
    document = service.create_document(db, admin, library.id, title="Policy", content=doc_json("body"))

    with pytest.raises(service.NotFoundError):
        service.delete_node(db, platform_editor, document.id)
    with pytest.raises(service.ForbiddenError):
        service.delete_node(db, no_platform_write, document.id)


def test_delete_library_requires_library_admin_and_hides_all_content(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:read"])
    non_member_admin = identity(2, ["knowledge:admin"])
    library = service.create_library(db, admin, name="Retired", category="company")
    folder = service.create_folder(db, admin, library.id, title="Archive")
    document = service.create_document(
        db, admin, library.id, title="Legacy", content=doc_json("old"), parent_id=folder.id
    )

    with pytest.raises(service.NotFoundError):
        service.delete_library(db, non_member_admin, library.id)

    result = service.delete_library(db, admin, library.id)

    assert result == {
        "id": library.id,
        "folder_count": 1,
        "document_count": 1,
        "cancelled_approval_count": 0,
    }
    db.refresh(library)
    db.refresh(document)
    assert library.deleted_at is not None
    assert document.deleted_at is not None
    assert service.list_libraries(db, admin) == []
    with pytest.raises(service.NotFoundError):
        service.get_document(db, admin, document.id)


def test_mutations_request_library_row_lock():
    source = Path(service.__file__).read_text(encoding="utf-8")

    assert "def _library(db, identity: dict, library_id: int, capability: str = \"read\", *, for_update: bool = False)" in source
    assert "if for_update:\n        query = query.with_for_update()" in source
    assert source.count("for_update=True") >= 3
    assert source.count("lock_library=True") >= 3
    assert "def _document(db, identity: dict, document_id: int, capability: str = \"read\", *, lock_library: bool = False)" in source
    assert "def _approval(db, identity: dict, approval_id: int, *, lock: bool = False)" in source
    assert source.count("_approval(db, identity, approval_id, lock=True)") == 2
    assert ").with_for_update().first()" in source
