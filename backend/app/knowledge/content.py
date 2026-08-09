"""Validation and text extraction for canonical Tiptap JSON."""

from __future__ import annotations

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
}
_LEAF_TYPES = {"text", "hardBreak", "horizontalRule"}
_ALLOWED_MARKS = {"bold", "italic", "strike", "code", "link"}
_BLOCK_BREAKS = {
    "paragraph",
    "heading",
    "listItem",
    "blockquote",
    "codeBlock",
    "tableRow",
    "taskItem",
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
        elif attrs:
            raise ContentValidationError("unsupported mark attributes")


def _validate_node(node: Any, *, root: bool = False) -> None:
    if not isinstance(node, dict):
        raise ContentValidationError("node must be an object")
    node_type = node.get("type")
    if root and node_type != "doc":
        raise ContentValidationError("root node must be doc")
    if node_type not in _CONTAINER_TYPES | _LEAF_TYPES:
        raise ContentValidationError("unsupported node")

    attrs = node.get("attrs", {})
    if not isinstance(attrs, dict):
        raise ContentValidationError("attrs must be an object")
    allowed_attrs: set[str] = set()
    if node_type == "heading":
        allowed_attrs = {"level"}
        if attrs.get("level") not in range(1, 7):
            raise ContentValidationError("invalid heading level")
    elif node_type in {"tableCell", "tableHeader"}:
        allowed_attrs = {"colspan", "rowspan", "colwidth"}
    elif node_type == "taskItem":
        allowed_attrs = {"checked"}
        if "checked" in attrs and not isinstance(attrs["checked"], bool):
            raise ContentValidationError("invalid task state")
    elif node_type == "orderedList":
        allowed_attrs = {"start", "type"}
    elif node_type == "codeBlock":
        allowed_attrs = {"language"}
    if set(attrs) - allowed_attrs:
        raise ContentValidationError("unsupported node attribute")

    _validate_marks(node.get("marks"))
    if node_type == "text":
        if not isinstance(node.get("text"), str):
            raise ContentValidationError("text node requires string text")
        if "content" in node:
            raise ContentValidationError("text node cannot contain children")
        return
    if "text" in node:
        raise ContentValidationError("only text nodes may contain text")
    children = node.get("content", [])
    if not isinstance(children, list):
        raise ContentValidationError("content must be a list")
    for child in children:
        _validate_node(child)


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
        for child in node.get("content", []):
            walk(child)
        if node_type in _BLOCK_BREAKS:
            flush()

    walk(validate_content(content))
    flush()
    return "\n".join(lines)
