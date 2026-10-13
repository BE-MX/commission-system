"""Assistant knowledge tests use only an isolated synthetic SQLite database."""

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Query, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import ArkUser
from app.core.database import Base
from app.core.time import beijing_now
from app.knowledge import service
from app.knowledge.content import extract_text
from app.knowledge.models import (
    KnowledgeAuditLog, KnowledgeDocument, KnowledgeLibrary,
    KnowledgeLibraryMember, KnowledgeRevision,
)
from app.whatsapp import assistant_knowledge as knowledge


ACTOR = {"sub": "1", "roles": [], "permissions": ["knowledge:read"]}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        ArkUser.__table__, KnowledgeLibrary.__table__,
        KnowledgeLibraryMember.__table__, KnowledgeDocument.__table__,
        KnowledgeRevision.__table__, KnowledgeAuditLog.__table__,
    ])
    session = sessionmaker(bind=engine)()
    session.add(ArkUser(id=1, username="synthetic", real_name="Synthetic", password_hash="test-only"))
    session.add(KnowledgeLibrary(id=1, name="Shared", category="company", created_by=1))
    session.add(KnowledgeLibrary(id=2, name="Private", category="personal", created_by=2))
    session.add(KnowledgeLibraryMember(library_id=1, user_id=1, role="viewer", created_by=1))
    session.flush()
    yield session
    session.close()
    engine.dispose()


def node(kind, text):
    value = {"type": kind, "content": [{"type": "text", "text": text}]}
    if kind == "heading":
        value["attrs"] = {"level": 2}
    return value


def document(db, title, text=None, *, library_id=1, published=True, nodes=None):
    content = {"type": "doc", "content": nodes or [node("paragraph", text)]}
    row = KnowledgeDocument(library_id=library_id, title=title, created_by=1,
                            status="published" if published else "draft")
    db.add(row)
    db.flush()
    revision = KnowledgeRevision(document_id=row.id, version_no=1, title=title,
                                 content_json=content, content_text=extract_text(content), created_by=1)
    db.add(revision)
    db.flush()
    row.draft_revision_id = revision.id
    if published:
        row.published_revision_id = revision.id
    db.flush()
    return row, revision


@pytest.mark.parametrize("query", ["客户想知道发帘的接缝厚度", "What are the Genius Weft seam conditions?"])
def test_chinese_and_english_retrieve_only_readable_published_revision(db, query):
    public, _ = document(db, "Genius 发帘", "Genius Weft 接缝厚度条件：先确认安装方式。")
    document(db, "Draft Genius 发帘", "Genius Weft 接缝厚度价格秘密", published=False)
    document(db, "Private Genius 发帘", "Genius Weft 接缝厚度内部成本", library_id=2)
    sources = knowledge.retrieve_sources(db, ACTOR, [query])
    assert [source["document_id"] for source in sources] == [public.id]
    assert set(sources[0]) == {"source_id", "document_id", "revision_id", "library_id", "title", "version_no", "section_index", "content_hash", "text"}
    assert sources == knowledge.retrieve_sources(db, ACTOR, [query])


def test_missing_platform_permission_is_safe_and_does_not_search(db, monkeypatch):
    document(db, "Genius", "Genius details.")
    def forbidden_search(*args, **kwargs):
        pytest.fail("unauthorized retrieval must not search")
    monkeypatch.setattr(service, "search_published", forbidden_search)
    denied = {**ACTOR, "permissions": ["whatsapp:admin"]}
    assert knowledge.retrieve_sources(db, denied, ["Genius"]) == []
    assert knowledge.revalidate_sources(db, denied, [])
    assert not knowledge.revalidate_sources(db, denied, [{"document_id": 1}])


def test_private_acl_and_revoked_membership_fail_closed(db):
    document(db, "Genius", "Genius details.")
    sources = knowledge.retrieve_sources(db, ACTOR, ["Genius"])
    db.query(KnowledgeLibraryMember).filter_by(library_id=1, user_id=1).delete()
    db.flush()
    assert knowledge.retrieve_sources(db, ACTOR, ["Genius"]) == []
    assert not knowledge.revalidate_sources(db, ACTOR, sources, fresh=True)


def test_pending_draft_never_replaces_current_published_content(db):
    row, _ = document(db, "Genius public", "Genius published specification.")
    draft = KnowledgeRevision(document_id=row.id, version_no=2, title="Confidential price",
                              content_json={"type": "doc", "content": [node("paragraph", "Secret draft Genius cost.")]},
                              content_text="Secret draft Genius cost.", created_by=1)
    db.add(draft)
    db.flush()
    row.draft_revision_id = draft.id
    row.status = "pending"
    db.flush()
    sources = knowledge.retrieve_sources(db, ACTOR, ["Genius"])
    assert sources[0]["revision_id"] != draft.id
    assert sources[0]["text"] == "Genius published specification."
    assert knowledge.revalidate_sources(db, ACTOR, sources, fresh=True)


def test_metadata_only_sources_invalidate_when_revision_or_hash_changes(db):
    row, revision = document(db, "Genius", "Genius seam conditions.")
    sources = knowledge.retrieve_sources(db, ACTOR, ["Genius"])
    metadata = [{key: value for key, value in sources[0].items() if key != "text"}]
    assert knowledge.revalidate_sources(db, ACTOR, metadata, fresh=True)
    assert not knowledge.revalidate_sources(db, ACTOR, [{**metadata[0], "title": "Invented authority"}])
    metadata[0]["content_hash"] = "0" * 64
    assert not knowledge.revalidate_sources(db, ACTOR, metadata)
    revised = KnowledgeRevision(document_id=row.id, version_no=2, title="Genius",
                                content_json=revision.content_json, content_text=revision.content_text, created_by=1)
    db.add(revised)
    db.flush()
    row.published_revision_id = revised.id
    db.flush()
    assert not knowledge.revalidate_sources(db, ACTOR, sources, fresh=True)


@pytest.mark.parametrize("change", ["archived", "deleted_document", "deleted_library", "disabled_user", "deleted_user", "removed_revision"])
def test_fresh_validation_rejects_removed_or_inactive_resources(db, change):
    row, revision = document(db, "Genius", "Genius conditions.")
    sources = knowledge.retrieve_sources(db, ACTOR, ["Genius"])
    if change == "archived":
        db.query(KnowledgeLibrary).filter_by(id=1).update({"status": "archived"})
    elif change == "deleted_document":
        row.deleted_at = beijing_now()
    elif change == "deleted_library":
        db.query(KnowledgeLibrary).filter_by(id=1).update({"deleted_at": beijing_now()})
    elif change == "disabled_user":
        db.query(ArkUser).filter_by(id=1).update({"is_active": False})
    elif change == "deleted_user":
        db.query(ArkUser).filter_by(id=1).update({"deleted_at": beijing_now()})
    else:
        db.delete(revision)
    db.flush()
    assert not knowledge.revalidate_sources(db, ACTOR, sources, fresh=True)


def test_fresh_current_reads_refresh_stale_identity_map_and_lock_all_authority_rows(db, monkeypatch):
    row, _ = document(db, "Genius", "Genius conditions.")
    sources = knowledge.retrieve_sources(db, ACTOR, ["Genius"])
    locked_models = []
    original = Query.with_for_update
    def tracked_lock(query, *args, **kwargs):
        locked_models.append(query.column_descriptions[0]["entity"])
        return original(query, *args, **kwargs)
    monkeypatch.setattr(Query, "with_for_update", tracked_lock)
    assert knowledge.revalidate_sources(db, ACTOR, sources, fresh=True)
    assert set(locked_models) == {ArkUser, KnowledgeLibrary, KnowledgeLibraryMember, KnowledgeDocument, KnowledgeRevision}
    db.execute(update(KnowledgeDocument).where(KnowledgeDocument.id == row.id).values(published_revision_id=None),
               execution_options={"synchronize_session": False})
    assert row.published_revision_id == sources[0]["revision_id"]  # deliberately stale ORM value
    assert not knowledge.revalidate_sources(db, ACTOR, sources, fresh=True)
    assert row.published_revision_id is None


def test_whole_sections_and_budgets_never_cut_conditions(db):
    whole = "Genius\n" + "A" * 3990 + "\nApproval required."
    row, _ = document(db, "Genius", nodes=[
        node("heading", "Genius"), node("paragraph", "A" * 3990),
        node("paragraph", "Approval required."), node("heading", "Genius excess"),
        node("paragraph", "B" * 8001),
    ])
    for index in range(8):
        document(db, f"Genius {index}", "Genius smaller complete paragraph.")
    sources = knowledge.retrieve_sources(db, ACTOR, ["Genius"])
    assert len(sources) <= 6
    assert sum(len(source["text"]) for source in sources) <= 8000
    assert next(source["text"] for source in sources if source["document_id"] == row.id) == whole
    assert not any(source["section_index"] == 1 and source["document_id"] == row.id for source in sources)


def test_search_terms_cover_chat_end_and_queries_are_not_audited_or_committed(db, monkeypatch):
    row, _ = document(db, "Zirconium", "Zirconium care conditions.")
    before = db.query(KnowledgeAuditLog).count()
    searches = []
    search = service.search_published
    def tracked_search(*args, **kwargs):
        assert not kwargs.get("audit_action")
        searches.append(args[2])
        return search(*args, **kwargs)
    monkeypatch.setattr(service, "search_published", tracked_search)
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("source retrieval must not commit"))
    query = " ".join(f"synthetictopic{index}" for index in range(300)) + " zirconium"
    sources = knowledge.retrieve_sources(db, ACTOR, [query])
    assert len(searches) <= knowledge.MAX_SEARCH_TERMS
    assert "zirconium" in searches
    assert [source["document_id"] for source in sources] == [row.id]
    assert knowledge.revalidate_sources(db, ACTOR, sources, fresh=True)
    assert db.query(KnowledgeAuditLog).count() == before


def test_ascii_matches_whole_words_and_invalid_metadata_fails_closed(db):
    document(db, "Silicone", "Silicone specification.")
    assert knowledge.retrieve_sources(db, ACTOR, ["cone"]) == []
    sources = knowledge.retrieve_sources(db, ACTOR, ["silicone"])
    assert not knowledge.revalidate_sources(db, ACTOR, [{**sources[0], "text": "Invented specification."}])
    assert not knowledge.revalidate_sources(db, ACTOR, [{**sources[0], "section_index": -1}])
    assert not knowledge.revalidate_sources(db, ACTOR, [{**sources[0], "source_id": "invented"}])
    assert not knowledge.revalidate_sources(db, ACTOR, [{"document_id": 1}])
