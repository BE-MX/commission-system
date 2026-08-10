import pytest

from app.knowledge.content import ContentValidationError, extract_text, validate_content


def test_validate_content_accepts_supported_document_and_extracts_text():
    content = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "标题"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "第一段"}, {"type": "hardBreak"}, {"type": "text", "text": "第二行"}]},
        ],
    }

    assert validate_content(content) == content
    assert extract_text(content) == "标题\n第一段\n第二行"


def test_validate_content_accepts_confirmation_mark_without_changing_search_text():
    content = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "content": [{
                "type": "text",
                "text": "需要业务负责人确认",
                "marks": [{"type": "confirmation"}],
            }],
        }],
    }

    assert validate_content(content) == content
    assert extract_text(content) == "需要业务负责人确认"


@pytest.mark.parametrize(
    "content",
    [
        {},
        {"type": "paragraph"},
        {"type": "doc", "content": [{"type": "script", "text": "alert(1)"}]},
        {"type": "doc", "content": [{"type": "iframe", "attrs": {"src": "https://evil.test"}}]},
        {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 9}}]},
        {"type": "doc", "content": [{"type": "text", "text": 3}]},
    ],
)
def test_validate_content_rejects_malformed_or_unknown_nodes(content):
    with pytest.raises(ContentValidationError):
        validate_content(content)
