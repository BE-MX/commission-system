"""Bounded, actor-scoped published knowledge for the chat assistant.

No chat text is audited or persisted here. The caller supplies a live identity
and owns the transaction, including locks held by final source revalidation.
"""

from collections import Counter

from sqlalchemy.orm import lazyload

from app.auth.models import ArkUser
from app.knowledge import access, service
from app.knowledge.models import (
    KnowledgeDocument, KnowledgeLibrary, KnowledgeLibraryMember, KnowledgeRevision,
)
from app.knowledge.reply_sources import (
    _score, content_hash, extract_query_terms, query_terms, sections,
)


MAX_SOURCES = 6
MAX_TEXT_CHARS = 8000
MAX_SEARCH_TERMS = 32
MAX_DOCUMENTS = 160


def _search_terms(queries: list[str]) -> list[str]:
    """Combine frequent topics with samples spanning all supplied chat terms.

Every message is tokenized and contributes to ranking; no prefix of the chat
is silently substituted for the full input. At most 32 lexical database
searches keep execution bounded even for a long time range.
    """
    sequences = [extract_query_terms(query) for query in queries]
    ordered = list(dict.fromkeys(term for sequence in sequences for term in sequence))
    if len(ordered) <= MAX_SEARCH_TERMS:
        return ordered
    counts = Counter(term for sequence in sequences for term in sequence)
    positions = {term: index for index, term in enumerate(ordered)}
    sampled = [ordered[index * (len(ordered) - 1) // 15] for index in range(16)]
    frequent = sorted(ordered, key=lambda term: (-counts[term], positions[term]))
    return list(dict.fromkeys(sampled + frequent))[:MAX_SEARCH_TERMS]


def _source_id(document_id: int, revision_id: int, section_index: int) -> str:
    return f"knowledge:{document_id}:{revision_id}:{section_index}"


def retrieve_sources(db, actor: dict, queries: list[str]) -> list[dict]:
    """Return at most six complete readable published sections / 8000 chars.

Searches use at most 32 representative terms, 20 results per term, and 160
full document reads. This is a lexical result set, not exhaustive KB coverage.
    """
    if not access.has_platform(actor, "knowledge:read"):
        return []
    terms = query_terms(queries)
    if not terms:
        return []
    found = {}
    # Ordinary search performs the platform/library filtering; a full resource
    # read below is still required, since search alone is not an ACL guarantee.
    for term in _search_terms(queries):
        for item in service.search_published(db, actor, term, limit=20):
            found[item["document_id"]] = item
    # Consider every representative term before capping full document reads;
    # an early generic topic must not suppress a later topic in the chat.
    document_ids = sorted(found, key=lambda document_id: (
        -_score({"title": found[document_id]["title"], "text": found[document_id]["summary"]}, [], terms),
        document_id,
    ))[:MAX_DOCUMENTS]
    candidates = []
    for document_id in document_ids:
        try:
            document = service.get_published_document(db, actor, document_id)
        except (service.ForbiddenError, service.NotFoundError):
            # Expected ACL exclusion: do not expose identifiers or titles.
            continue
        for index, text in enumerate(sections(document["content_json"])):
            if not text.strip() or len(text) > MAX_TEXT_CHARS:
                continue
            source = {
                "source_id": _source_id(document_id, document["revision_id"], index),
                "document_id": document_id,
                "revision_id": document["revision_id"],
                "library_id": document["library_id"],
                "title": document["title"],
                "version_no": document["version_no"],
                "section_index": index,
                "content_hash": content_hash(text),
                "text": text,
            }
            score = _score(source, [], terms)
            if score:
                candidates.append((score, source))
    selected, chars = [], 0
    for _, source in sorted(candidates, key=lambda item: (
        -item[0], item[1]["document_id"], item[1]["section_index"],
    )):
        if len(selected) >= MAX_SOURCES:
            break
        if chars + len(source["text"]) <= MAX_TEXT_CHARS:
            selected.append(source)
            chars += len(source["text"])
    return selected


def _current_read(db, model, *filters):
    # MySQL REPEATABLE READ needs locking reads, not merely expire()/refresh().
    return db.query(model).options(lazyload("*")).populate_existing().filter(*filters).with_for_update().first()


def _refresh_sources(db, actor: dict, sources: list[dict]) -> bool:
    user = _current_read(db, ArkUser, ArkUser.id == access.user_id(actor))
    if user is None or not user.is_active or user.deleted_at is not None:
        return False
    for library_id in sorted({source["library_id"] for source in sources}):
        library = _current_read(db, KnowledgeLibrary, KnowledgeLibrary.id == library_id)
        if library is None or library.deleted_at is not None or library.status != "active":
            return False
        if not access.is_super_admin(actor):
            member = _current_read(
                db, KnowledgeLibraryMember,
                KnowledgeLibraryMember.library_id == library_id,
                KnowledgeLibraryMember.user_id == access.user_id(actor),
            )
            if member is None or member.role not in access.CAPABILITIES["read"]:
                return False
    for source in sorted(sources, key=lambda item: (item["document_id"], item["revision_id"])):
        document = _current_read(db, KnowledgeDocument, KnowledgeDocument.id == source["document_id"])
        if (document is None or document.deleted_at is not None
                or document.node_type != "document"
                or document.library_id != source["library_id"]
                or document.published_revision_id != source["revision_id"]):
            return False
        revision = _current_read(db, KnowledgeRevision, KnowledgeRevision.id == source["revision_id"])
        if revision is None or revision.document_id != document.id:
            return False
    return True


def revalidate_sources(db, actor: dict, sources: list[dict], fresh: bool = False) -> bool:
    """Check metadata-only sources against current ACL, revision and section hash.

``fresh`` locks current authority/resource rows and leaves the caller's
transaction open. Actor roles and permission codes must already be live.
    """
    if not sources:
        return True
    if not access.has_platform(actor, "knowledge:read"):
        return False
    required = ("document_id", "revision_id", "library_id", "section_index", "content_hash")
    if any(not isinstance(source, dict) or any(key not in source for key in required)
           or any(type(source[key]) is not int or source[key] <= 0
                  for key in ("document_id", "revision_id", "library_id"))
           or type(source["section_index"]) is not int or source["section_index"] < 0
           for source in sources):
        return False
    if fresh and not _refresh_sources(db, actor, sources):
        return False
    documents = {}
    for source in sources:
        document_id = source["document_id"]
        if document_id not in documents:
            try:
                documents[document_id] = service.get_published_document(db, actor, document_id)
            except (service.ForbiddenError, service.NotFoundError):
                return False
        document = documents[document_id]
        parts = sections(document["content_json"])
        index = source["section_index"]
        if (document["revision_id"] != source["revision_id"]
                or document["library_id"] != source["library_id"]
                or index >= len(parts)
                or content_hash(parts[index]) != source["content_hash"]):
            return False
        if any(key in source and source[key] != document[key] for key in ("title", "version_no")):
            return False
        if "text" in source and source["text"] != parts[index]:
            return False
        if "source_id" in source and source["source_id"] != _source_id(document_id, document["revision_id"], index):
            return False
    return True
