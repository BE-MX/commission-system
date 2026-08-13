import io
from types import SimpleNamespace
from datetime import timedelta

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import ArkUser
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.core.database import Base
from app.knowledge import asset_service, image_service, service
from app.knowledge.models import (
    KnowledgeApprovalRequest,
    KnowledgeAsset,
    KnowledgeAuditLog,
    KnowledgeDocument,
    KnowledgeLibrary,
    KnowledgeLibraryMember,
    KnowledgeRevision,
    KnowledgeRevisionAsset,
    bj_now,
    KnowledgeAiJob,
    KnowledgeAiJobSource,
    KnowledgeAiProfile,
    KnowledgeAiProfileLog,
    KnowledgeAiProfileSource,
    KnowledgeAiProfileTarget,
)


TABLES = [
    ArkUser.__table__, KnowledgeLibrary.__table__, KnowledgeLibraryMember.__table__,
    KnowledgeDocument.__table__, KnowledgeRevision.__table__,
    KnowledgeApprovalRequest.__table__, KnowledgeAuditLog.__table__,
    KnowledgeAsset.__table__, KnowledgeRevisionAsset.__table__,
    AiProvider.__table__, AiPreset.__table__, AiCallLog.__table__,
    KnowledgeAiProfile.__table__, KnowledgeAiProfileLog.__table__,
    KnowledgeAiProfileSource.__table__, KnowledgeAiProfileTarget.__table__,
    KnowledgeAiJob.__table__, KnowledgeAiJobSource.__table__,
]


def identity(user_id, permissions):
    return {
        "sub": str(user_id), "username": f"user-{user_id}",
        "roles": [], "permissions": permissions,
    }


def image_doc(asset_id):
    return {"type": "doc", "content": [{
        "type": "knowledgeImage",
        "attrs": {"assetId": asset_id, "alt": "安全帽", "caption": "正确示例"},
    }]}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLES)
    session = sessionmaker(bind=engine)()
    session.add_all([
        ArkUser(
            id=user_id, username=f"user-{user_id}", real_name=f"用户{user_id}",
            password_hash="test", is_active=True,
        )
        for user_id in range(1, 5)
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_image_normalization_removes_metadata_and_enforces_private_root(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        KNOWLEDGE_IMAGE_MAX_UPLOAD_MB=2,
        KNOWLEDGE_STORAGE_ROOT=str(tmp_path / "private"),
    )
    monkeypatch.setattr(image_service, "get_settings", lambda: settings)
    source = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "secret customer metadata")
    Image.new("RGB", (32, 24), "red").save(source, "PNG", pnginfo=metadata)

    stored = image_service.store_upload(12, source.getvalue(), "image/png")
    path = image_service.resolve_private_path(stored.storage_path)

    assert path.is_file()
    assert path.is_relative_to((tmp_path / "private").resolve())
    with Image.open(path) as normalized:
        assert normalized.size == (32, 24)
        assert "Comment" not in normalized.info
    with pytest.raises(image_service.ImageStorageError):
        image_service.resolve_private_path("../../outside.png")
    with pytest.raises(image_service.ImageValidationError, match="真实格式"):
        image_service._normalized_bytes(source.getvalue(), "image/jpeg")


def test_revision_image_visibility_follows_draft_review_and_publish_acl(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write", "knowledge:review"])
    viewer = identity(2, ["knowledge:read"])
    reviewer = identity(3, ["knowledge:review"])
    library = service.create_library(db, admin, name="安全规范", category="company")
    service.replace_members(db, admin, library.id, [
        {"user_id": 2, "role": "viewer"},
        {"user_id": 3, "role": "reviewer"},
    ])
    asset = KnowledgeAsset(
        library_id=library.id, storage_path="1/a.png", original_name="a.png",
        mime_type="image/png", file_size=10, width=10, height=10, sha256="a" * 64,
        status="temporary", created_by=1,
    )
    db.add(asset)
    db.commit()
    document = service.create_document(
        db, admin, library.id, title="图片规范", content=image_doc(asset.id)
    )
    db.refresh(asset)
    assert asset.status == "attached"
    assert db.query(KnowledgeRevisionAsset).filter_by(
        revision_id=document.draft_revision_id, asset_id=asset.id
    ).one()
    with pytest.raises(service.NotFoundError):
        asset_service.get_image_asset(db, viewer, asset.id)

    approval = service.submit_document(db, admin, document.id)
    assert asset_service.get_image_asset(db, reviewer, asset.id).id == asset.id
    service.approve_request(db, admin, approval.id)
    assert asset_service.get_image_asset(db, viewer, asset.id).id == asset.id


def test_revision_rejects_foreign_library_and_foreign_temporary_asset(db):
    admin = identity(1, ["knowledge:admin", "knowledge:write"])
    editor = identity(2, ["knowledge:write"])
    first = service.create_library(db, admin, name="一", category="company")
    second = service.create_library(db, admin, name="二", category="company")
    service.replace_members(db, admin, first.id, [{"user_id": 2, "role": "editor"}])
    foreign = KnowledgeAsset(
        library_id=second.id, storage_path="2/a.png", original_name="a.png",
        mime_type="image/png", file_size=1, width=1, height=1, sha256="b" * 64,
        status="temporary", created_by=1,
    )
    own_library_other_user = KnowledgeAsset(
        library_id=first.id, storage_path="1/b.png", original_name="b.png",
        mime_type="image/png", file_size=1, width=1, height=1, sha256="c" * 64,
        status="temporary", created_by=1,
    )
    db.add_all([foreign, own_library_other_user])
    db.commit()

    with pytest.raises(service.ValidationError, match="another library"):
        service.create_document(db, editor, first.id, title="非法", content=image_doc(foreign.id))
    db.rollback()
    with pytest.raises(service.ValidationError, match="another user"):
        service.create_document(
            db, editor, first.id, title="非法", content=image_doc(own_library_other_user.id)
        )


def test_cleanup_retries_failed_file_removal_and_clears_path_on_success(db, monkeypatch):
    admin = identity(1, ["knowledge:admin", "knowledge:write"])
    library = service.create_library(db, admin, name="临时图", category="company")
    asset = KnowledgeAsset(
        library_id=library.id, storage_path="1/stale.png", original_name="stale.png",
        mime_type="image/png", file_size=9, width=1, height=1, sha256="d" * 64,
        status="temporary", created_by=1, expires_at=bj_now() - timedelta(hours=1),
    )
    db.add(asset)
    db.commit()
    monkeypatch.setattr(image_service, "remove_quietly", lambda _path: False)

    assert asset_service.cleanup_expired_images(db) == 1
    db.refresh(asset)
    assert asset.deleted_at is not None
    assert asset.storage_path == "1/stale.png"

    monkeypatch.setattr(image_service, "remove_quietly", lambda _path: True)
    assert asset_service.cleanup_expired_images(db) == 1
    db.refresh(asset)
    assert asset.storage_path == ""
    assert asset.file_size == 0
