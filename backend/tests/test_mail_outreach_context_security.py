from dataclasses import replace

from app.mail_outreach.context_service import build_outreach_snapshot
from app.knowledge.models import KnowledgeLibrary, KnowledgeDocument, KnowledgeRevision, KnowledgeLibraryMember
from tests.mail_outreach_helpers import seed_graph


def test_business_contact_fact_available_without_profile_recompile_and_acl_holds(db):
    graph = seed_graph(db)
    graph.fact.fact_key = "research.source.business_contact"
    graph.fact.value_json = {"email": "hello@acme.com", "name": "Purchasing"}
    graph.profile.evidence_fact_ids = []
    db.flush()
    snapshot = build_outreach_snapshot(db, graph.access)
    assert snapshot["contact_candidates"][0]["email"] == "hello@acme.com"
    restricted = replace(graph.access, max_data_classification="public_business")
    assert build_outreach_snapshot(db, restricted)["contact_candidates"] == []
    graph.fact.verification_status = "rejected"
    db.flush()
    assert build_outreach_snapshot(db, graph.access)["contact_candidates"] == []


def test_only_accessible_published_company_knowledge_is_exposed(db):
    graph = seed_graph(db)
    library = KnowledgeLibrary(name="Company", category="company", status="active", created_by=graph.user.id)
    db.add(library)
    db.flush()
    doc = KnowledgeDocument(library_id=library.id, title="Intro", node_type="document", status="published", created_by=graph.user.id)
    db.add(doc)
    db.flush()
    published = KnowledgeRevision(document_id=doc.id, version_no=1, title="Intro", content_json={}, content_text="Verified capabilities", created_by=graph.user.id)
    draft = KnowledgeRevision(document_id=doc.id, version_no=2, title="Draft", content_json={}, content_text="Secret draft", created_by=graph.user.id)
    db.add_all([published, draft])
    db.flush()
    doc.published_revision_id = published.id
    doc.draft_revision_id = draft.id
    identity = {"sub": str(graph.user.id), "permissions": ["knowledge:read"]}
    assert build_outreach_snapshot(db, graph.access, identity)["knowledge_items"] == []
    db.add(KnowledgeLibraryMember(library_id=library.id, user_id=graph.user.id, role="viewer", created_by=graph.user.id))
    db.flush()
    items = build_outreach_snapshot(db, graph.access, identity)["knowledge_items"]
    assert len(items) == 1
    assert items[0]["knowledge_version_id"] == published.id
    assert items[0]["content_text"] == "Verified capabilities"
    assert build_outreach_snapshot(db, graph.access)["knowledge_items"] == []
