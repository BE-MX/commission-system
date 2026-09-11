import pytest

from app.knowledge import service
from app.knowledge.models import KnowledgeLibraryMember
from app.knowledge.reply_sources import (
    SourceBinding, content_hash, parse_bindings, retrieve_reply_sources, sections,
)
from tests.reply_support import binding, publish, seed_reply


@pytest.fixture
def configured(db, monkeypatch):
    return seed_reply(db, monkeypatch)


def actor(identity):
    return {"sub": str(identity.user_id), "roles": [], "permissions": ["knowledge:read"]}


def test_mandatory_policy_survives_irrelevant_search_terms(db, configured):
    identity, _, _, policy, _, settings = configured
    sources, ready = retrieve_reply_sources(db, actor(identity), parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS), ["nonmatching"])
    assert ready
    assert len(sources) == 1
    assert sources[0]["document_id"] == policy["document_id"]


def test_no_platform_or_library_permission_hides_sources_entirely(db, configured):
    identity, _, library, _, _, settings = configured
    bindings = parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS)
    denied = {**actor(identity), "permissions": []}
    assert retrieve_reply_sources(db, denied, bindings, ["Genius"] ) == ([], False)
    db.query(KnowledgeLibraryMember).filter_by(library_id=library.id).delete()
    db.commit()
    # Translation administration is deliberately unrelated to knowledge ACL.
    denied = {**actor(identity), "permissions": ["knowledge:admin", "whatsapp_translation:admin"]}
    assert retrieve_reply_sources(db, denied, bindings, ["Genius"]) == ([], False)


def test_title_weight_and_alias_retrieval_selects_public_fact(db, configured):
    identity, _, _, _, fact, settings = configured
    sources, ready = retrieve_reply_sources(db, actor(identity), parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS), ["发帘"])
    assert ready
    assert sources[1]["document_id"] == fact["document_id"]


def test_hash_mismatch_or_policy_revision_change_fails_closed(db, configured):
    identity, *_, settings = configured
    bindings = parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS)
    bindings[0].content_hash = "0" * 64
    assert retrieve_reply_sources(db, actor(identity), bindings, ["Genius"] ) == ([], False)
    bindings = parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS)
    bindings[0].revision_id += 100
    assert retrieve_reply_sources(db, actor(identity), bindings, ["Genius"] ) == ([], False)


def test_unreviewed_public_revision_does_not_inherit_permission(db, configured):
    identity, _, _, _, fact, settings = configured
    admin = {"sub": str(identity.user_id), "roles": ["super_admin"]}
    new_content = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Genius Weft INTERNAL cost and conditions changed."}]}]}
    service.save_document(db, admin, fact["document_id"], title=fact["title"], content=new_content)
    service.approve_request(db, admin, service.submit_document(db, admin, fact["document_id"]).id)
    sources, ready = retrieve_reply_sources(db, actor(identity), parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS), ["Genius"])
    assert ready
    assert all(source["document_id"] != fact["document_id"] for source in sources)


def test_heading_conditions_are_never_separated_or_truncated():
    def node(kind, text):
        value = {"type": kind, "content": [{"type": "text", "text": text}]}
        if kind == "heading":
            value["attrs"] = {"level": 2}
        return value
    content = {"type": "doc", "content": [node("heading", "Samples"), node("paragraph", "Fee conditions."), node("paragraph", "Except when approval is missing."), node("heading", "After sales"), node("paragraph", "Gather evidence first.")]}
    assert sections(content) == ["Samples\nFee conditions.\nExcept when approval is missing.", "After sales\nGather evidence first."]


def test_oversized_mandatory_section_is_not_silently_cut(db, configured):
    identity, _, library, _, _, _ = configured
    document = publish(db, {"sub": str(identity.user_id), "roles": ["super_admin"]}, library.id, "Large policy", "A" * 1201)
    assert retrieve_reply_sources(db, actor(identity), [binding(document, "constraint", mandatory=True)], ["A"]) == ([], False)


def test_duplicate_or_invalid_mandatory_purposes_are_rejected(configured):
    settings = configured[-1]
    with pytest.raises(ValueError, match="duplicate"):
        parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS * 2)
    with pytest.raises(ValueError):
        SourceBinding.model_validate({**settings.WHATSAPP_REPLY_SOURCE_BINDINGS[0], "purpose": "public_fact"})


def test_total_budget_reserves_constraints_and_never_exceeds_six(db, configured):
    identity, _, library, _, _, settings = configured
    bindings = parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS)
    for number in range(8):
        document = publish(db, {"sub": str(identity.user_id), "roles": ["super_admin"]}, library.id, f"Genius extra {number}", "Genius details. " + "A" * 1100)
        bindings.append(binding(document, "method"))
    sources, ready = retrieve_reply_sources(db, actor(identity), bindings, ["Genius"])
    assert ready
    assert len(sources) <= 6
    assert sum(len(source["text"]) for source in sources) <= 6000
    assert sources[0]["purpose"] == "constraint"


def test_expired_material_is_excluded_and_revalidation_checks_expiry(db, configured, monkeypatch):
    from datetime import date
    from app.knowledge import reply_sources
    identity, *_, settings = configured
    bindings = parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS)
    bindings[1].aliases = ["silicone"]
    bindings[1].shareable_text = True
    bindings[1].valid_until = date(2026, 9, 8)
    monkeypatch.setattr(reply_sources, "beijing_today", lambda: date(2026, 9, 8))
    sources, ready = retrieve_reply_sources(db, actor(identity), bindings, ["silicone"])
    assert ready and sources[1]["shareable_text"]
    monkeypatch.setattr(reply_sources, "beijing_today", lambda: date(2026, 9, 9))
    assert not reply_sources.revalidate_sources(db, actor(identity), sources)
    remaining, ready = retrieve_reply_sources(db, actor(identity), bindings, ["silicone"])
    assert ready and len(remaining) == 1


def test_method_cannot_be_shareable_material(configured):
    settings = configured[-1]
    with pytest.raises(ValueError, match="public facts"):
        SourceBinding.model_validate({**settings.WHATSAPP_REPLY_SOURCE_BINDINGS[1], "purpose": "method", "shareable_text": True})
