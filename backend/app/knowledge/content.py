"""Validation and text extraction for canonical Tiptap JSON."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class ContentValidationError(ValueError):
    """Raised when editor JSON is outside the supported schema."""


_CONTAINER_TYPES = {
    "doc",
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "listItem",
    "blockquote",
    "codeBlock",
    "table",
    "tableRow",
    "tableHeader",
    "tableCell",
    "taskList",
    "taskItem",
    "knowledgeCallout",
    "details",
    "detailsSummary",
    "detailsContent",
}
_LEAF_TYPES = {"text", "hardBreak", "horizontalRule"}
_ATOM_TYPES = {"knowledgeImage"}
_ALLOWED_MARKS = {
    "bold", "italic", "strike", "code", "link", "confirmation", "textColor",
    "underline", "knowledgeTextSize", "knowledgeHighlight",
}
_TEXT_COLOR_TONES = {"gold", "danger", "success", "info"}
_TEXT_SIZES = {12, 13, 14, 15, 16, 19, 22, 24, 29, 32, 40, 48}
_BLOCK_TYPES = {
    "paragraph", "heading", "bulletList", "orderedList", "blockquote",
    "codeBlock", "table", "taskList", "horizontalRule", "knowledgeImage",
    "knowledgeCallout", "details",
}
_BLOCK_BREAKS = {
    "paragraph",
    "heading",
    "listItem",
    "blockquote",
    "codeBlock",
    "tableRow",
    "taskItem",
    "knowledgeCallout",
    "detailsSummary",
    "detailsContent",
    "details",
}


def _validate_marks(marks: Any) -> None:
    if marks is None:
        return
    if not isinstance(marks, list):
        raise ContentValidationError("marks must be a list")
    for mark in marks:
        if not isinstance(mark, dict) or mark.get("type") not in _ALLOWED_MARKS:
            raise ContentValidationError("unsupported mark")
        attrs = mark.get("attrs", {})
        if not isinstance(attrs, dict):
            raise ContentValidationError("mark attrs must be an object")
        if mark["type"] == "link":
            href = attrs.get("href")
            if not isinstance(href, str) or not href.startswith(("https://", "http://", "mailto:")):
                raise ContentValidationError("invalid link")
            if set(attrs) - {"href", "target", "rel", "class"}:
                raise ContentValidationError("unsupported link attribute")
        elif mark["type"] in {"textColor", "knowledgeHighlight"}:
            tone = attrs.get("tone")
            if set(attrs) != {"tone"} or not isinstance(tone, str) or tone not in _TEXT_COLOR_TONES:
                raise ContentValidationError("invalid text tone")
        elif mark["type"] == "knowledgeTextSize":
            size = attrs.get("size")
            if set(attrs) != {"size"} or type(size) is not int or size not in _TEXT_SIZES:
                raise ContentValidationError("invalid text size")
        elif attrs:
            raise ContentValidationError("unsupported mark attributes")


def _validate_node(node: Any, *, root: bool = False, parent_type: str | None = None) -> None:
    if not isinstance(node, dict):
        raise ContentValidationError("node must be an object")
    node_type = node.get("type")
    if root and node_type != "doc":
        raise ContentValidationError("root node must be doc")
    if node_type not in _CONTAINER_TYPES | _LEAF_TYPES | _ATOM_TYPES:
        raise ContentValidationError("unsupported node")
    if node_type in {"detailsSummary", "detailsContent"} and parent_type != "details":
        raise ContentValidationError("details children require a details parent")

    attrs = node.get("attrs", {})
    if not isinstance(attrs, dict):
        raise ContentValidationError("attrs must be an object")
    allowed_attrs: set[str] = set()
    if node_type == "heading":
        allowed_attrs = {"level", "textAlign"}
        if attrs.get("level") not in range(1, 7):
            raise ContentValidationError("invalid heading level")
    elif node_type == "paragraph":
        allowed_attrs = {"textAlign"}
    elif node_type == "knowledgeCallout":
        allowed_attrs = {"tone"}
        tone = attrs.get("tone")
        if not isinstance(tone, str) or tone not in _TEXT_COLOR_TONES:
            raise ContentValidationError("invalid callout tone")
    elif node_type in {"tableCell", "tableHeader"}:
        allowed_attrs = {"colspan", "rowspan", "colwidth", "align"}
        if attrs.get("align") not in {None, "left", "center", "right"}:
            raise ContentValidationError("invalid table cell alignment")
    elif node_type == "taskItem":
        allowed_attrs = {"checked"}
        if "checked" in attrs and not isinstance(attrs["checked"], bool):
            raise ContentValidationError("invalid task state")
    elif node_type == "orderedList":
        allowed_attrs = {"start", "type"}
    elif node_type == "codeBlock":
        allowed_attrs = {"language"}
    elif node_type == "knowledgeImage":
        allowed_attrs = {"assetId", "alt", "caption"}
        asset_id = attrs.get("assetId")
        if not isinstance(asset_id, int) or isinstance(asset_id, bool) or asset_id <= 0:
            raise ContentValidationError("invalid knowledge image asset")
        alt = attrs.get("alt", "")
        caption = attrs.get("caption", "")
        if not isinstance(alt, str) or len(alt) > 500:
            raise ContentValidationError("invalid knowledge image alt")
        if not isinstance(caption, str) or len(caption) > 500:
            raise ContentValidationError("invalid knowledge image caption")
    if set(attrs) - allowed_attrs:
        raise ContentValidationError("unsupported node attribute")
    if node_type in {"paragraph", "heading"} and attrs.get("textAlign") not in (
        None, "left", "center", "right", "justify",
    ):
        raise ContentValidationError("invalid text alignment")

    _validate_marks(node.get("marks"))
    if node_type == "text":
        if not isinstance(node.get("text"), str):
            raise ContentValidationError("text node requires string text")
        if "content" in node:
            raise ContentValidationError("text node cannot contain children")
        return
    if node_type in _ATOM_TYPES:
        if "content" in node:
            raise ContentValidationError("atom node cannot contain children")
        return
    if "text" in node:
        raise ContentValidationError("only text nodes may contain text")
    children = node.get("content", [])
    if not isinstance(children, list):
        raise ContentValidationError("content must be a list")
    for child in children:
        _validate_node(child, parent_type=node_type)
    if node_type == "details" and [child["type"] for child in children] != [
        "detailsSummary", "detailsContent",
    ]:
        raise ContentValidationError("details requires summary followed by content")
    if node_type == "detailsSummary" and any(
        child["type"] != "text" for child in children
    ):
        raise ContentValidationError("details summary requires text content")
    if node_type in {"knowledgeCallout", "detailsContent"} and (
        not children or any(child["type"] not in _BLOCK_TYPES for child in children)
    ):
        raise ContentValidationError("container requires block content")


def validate_content(content: Any) -> dict:
    """Return valid content unchanged; reject unsupported executable structures."""
    _validate_node(content, root=True)
    return content


def extract_text(content: dict) -> str:
    """Convert supported editor JSON to stable searchable plain text."""
    lines: list[str] = []
    current: list[str] = []

    def flush() -> None:
        text = "".join(current).strip()
        if text:
            lines.append(text)
        current.clear()

    def walk(node: dict) -> None:
        node_type = node["type"]
        if node_type == "text":
            current.append(node["text"])
        elif node_type == "hardBreak":
            flush()
        elif node_type == "knowledgeImage":
            alt = node.get("attrs", {}).get("alt", "").strip()
            caption = node.get("attrs", {}).get("caption", "").strip()
            current.append(caption or alt)
            flush()
        for child in node.get("content", []):
            walk(child)
        if node_type in _BLOCK_BREAKS:
            flush()

    walk(validate_content(content))
    flush()
    return "\n".join(lines)


def extract_asset_ids(content: dict) -> list[int]:
    """Return unique knowledge image asset IDs in document order."""
    result: list[int] = []
    seen: set[int] = set()

    def walk(node: dict) -> None:
        if node["type"] == "knowledgeImage":
            asset_id = node["attrs"]["assetId"]
            if asset_id not in seen:
                result.append(asset_id)
                seen.add(asset_id)
        for child in node.get("content", []):
            walk(child)

    walk(validate_content(content))
    return result


def extract_text_stream(content: dict) -> str:
    """Concatenate authored characters independent of block formatting."""
    parts: list[str] = []

    def walk(node: dict) -> None:
        if node["type"] == "text":
            parts.append(node["text"])
            return
        if node["type"] == "hardBreak":
            parts.append("\n")
            return
        for child in node.get("content", []):
            walk(child)

    walk(validate_content(content))
    return "".join(parts)


def protected_structure_signature(content: dict) -> list[dict]:
    """Freeze structures that smart formatting must never alter."""
    signature: list[dict] = []

    def text_of(node: dict) -> str:
        if node["type"] == "text":
            return node["text"]
        return "".join(text_of(child) for child in node.get("content", []))

    def walk(node: dict) -> None:
        node_type = node["type"]
        if node_type in {"codeBlock", "table", "knowledgeImage", "knowledgeCallout", "details"}:
            signature.append({
                "type": node_type,
                "node": deepcopy(node),
            })
            return
        if node_type == "text":
            for mark in node.get("marks", []):
                if mark.get("type") == "link":
                    signature.append({
                        "type": "link",
                        "href": mark.get("attrs", {}).get("href"),
                        "text": node.get("text", ""),
                    })
        for child in node.get("content", []):
            walk(child)

    walk(validate_content(content))
    return signature
