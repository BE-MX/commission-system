"""Revision-bound disclosure purposes, always behind the ordinary knowledge ACL.

Configuration contains metadata, never copied knowledge or chat queries. Paragraph
boundaries are stable indexes for a revision; an oversized paragraph is excluded,
never truncated into a potentially misleading policy.
"""

import hashlib
import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

from app.knowledge import service
from app.knowledge.content import extract_text
from app.core.time import beijing_today


class SourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    section_index: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_version: str = Field(min_length=1, max_length=64)
    purpose: Literal["method", "public_fact", "constraint", "blocked"]
    mandatory: bool = False
    aliases: list[str] = Field(default_factory=list, max_length=20)
    applicability: str = Field(default="", max_length=240)
    valid_until: date | None = None
    shareable_text: bool = False

    @model_validator(mode="after")
    def mandatory_requires_constraint(self):
        if self.mandatory and self.purpose != "constraint":
            raise ValueError("mandatory source must be a constraint")
        if self.shareable_text and self.purpose != "public_fact":
            raise ValueError("only reviewed public facts can be reusable material")
        if any(not value.strip() or len(value) > 80 for value in self.aliases):
            raise ValueError("invalid source alias")
        return self


def parse_bindings(values: list[dict]) -> list[SourceBinding]:
    if len(values) > 512:
        raise ValueError("too many source bindings")
    result = [SourceBinding.model_validate(value) for value in values]
    keys = [(binding.document_id, binding.section_index) for binding in result]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate section purpose")
    return result


def sections(content: dict) -> list[str]:
    """Keep each heading and its conditions together; never cut a list/table."""
    result, nodes = [], []
    for node in content.get("content", []):
        if node.get("type") == "heading" and nodes:
            result.append(extract_text({"type": "doc", "content": nodes}))
            nodes = []
        nodes.append(node)
    if nodes:
        result.append(extract_text({"type": "doc", "content": nodes}))
    return result


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_binding(db, identity: dict, binding: SourceBinding, *, documents=None) -> dict | None:
    if binding.valid_until is not None and binding.valid_until < beijing_today():
        return None
    try:
        if documents is not None and binding.document_id in documents:
            document = documents[binding.document_id]
        else:
            document = service.get_published_document(db, identity, binding.document_id)
            if documents is not None:
                documents[binding.document_id] = document
    except (service.ForbiddenError, service.NotFoundError):
        # Expected ACL exclusion. Do not reveal existence/title or audit chat queries.
        return None
    parts = sections(document["content_json"])
    if document["revision_id"] != binding.revision_id or binding.section_index >= len(parts):
        return None
    text = parts[binding.section_index]
    if len(text) > 1200 or content_hash(text) != binding.content_hash:
        return None
    return {
        "document_id": document["document_id"], "revision_id": document["revision_id"],
        "version_no": document["version_no"], "title": document["title"],
        "section": str(binding.section_index), "text": text,
        "purpose": binding.purpose, "binding": binding.model_dump(mode="json"),
        "applicability": binding.applicability, "shareable_text": binding.shareable_text,
    }


def retrieve_reply_sources(db, identity: dict, bindings: list[SourceBinding], queries: list[str]) -> tuple[list[dict], bool]:
    documents = {}  # This invocation only; never shared across users or requests.
    mandatory = [binding for binding in bindings if binding.mandatory and binding.purpose == "constraint"]
    if not mandatory:
        return [], False
    required = [resolve_binding(db, identity, binding, documents=documents) for binding in mandatory]
    if any(source is None for source in required):
        return [], False
    selected = list(required)
    chars = sum(len(source["text"]) for source in selected)
    if len(selected) > 6 or chars > 6000:
        return [], False
    terms = {term.casefold() for query in queries for term in re.split(r"[\s,，;/]+", query) if len(term) >= 2}
    # Small corpus: title-weighted lexical scoring after Chinese/alias planning.
    candidates = []
    required_keys = {(item.document_id, item.section_index) for item in mandatory}
    for binding in bindings:
        if binding.purpose == "blocked" or (binding.document_id, binding.section_index) in required_keys:
            continue
        source = resolve_binding(db, identity, binding, documents=documents)
        if source is None:
            continue
        score = sum(3 * (term in source["title"].casefold()) + source["text"].casefold().count(term) for term in terms)
        score += sum(5 * any(term in alias.casefold() or alias.casefold() in term for alias in binding.aliases) for term in terms)
        if score:
            candidates.append((score, source))
    # Relevant answer evidence gets a slot before stylistic examples; otherwise
    # long method paragraphs can crowd out the product answer the customer needs.
    for _, source in sorted(candidates, key=lambda item: (item[1]["purpose"] != "method", item[0]), reverse=True):
        if len(selected) >= 6:
            break
        if chars + len(source["text"]) <= 6000:
            selected.append(source)
            chars += len(source["text"])
    return selected, True


def revalidate_sources(db, identity: dict, sources: list[dict]) -> bool:
    documents = {}
    return all(resolve_binding(db, identity, SourceBinding.model_validate(source["binding"]), documents=documents) is not None for source in sources)
