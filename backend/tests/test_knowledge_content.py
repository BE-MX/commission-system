from copy import deepcopy
import json

import pytest

from app.knowledge.content import (
    ContentValidationError,
    extract_asset_ids,
    extract_text,
    extract_text_stream,
    protected_structure_signature,
    validate_content,
)


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


def test_knowledge_images_are_canonical_searchable_and_protected():
    content = {
        "type": "doc",
        "content": [
            {"type": "knowledgeImage", "attrs": {
                "assetId": 8, "alt": "仓库照片", "caption": "正确佩戴示例",
            }},
            {"type": "paragraph", "content": [{"type": "text", "text": "正文"}]},
            {"type": "knowledgeImage", "attrs": {
                "assetId": 8, "alt": "重复引用", "caption": "",
            }},
        ],
    }

    assert validate_content(content) == content
    assert extract_asset_ids(content) == [8]
    assert extract_text(content) == "正确佩戴示例\n正文\n重复引用"
    assert extract_text_stream(content) == "正文"
    assert protected_structure_signature(content)[0]["node"]["attrs"]["assetId"] == 8


@pytest.mark.parametrize("attrs", [
    {"assetId": 0, "alt": "", "caption": ""},
    {"assetId": True, "alt": "", "caption": ""},
    {"assetId": 1, "src": "https://evil.test/a.png", "alt": "", "caption": ""},
    {"assetId": 1, "alt": "x" * 501, "caption": ""},
])
def test_knowledge_image_rejects_invalid_or_remote_attributes(attrs):
    with pytest.raises(ContentValidationError):
        validate_content({"type": "doc", "content": [{"type": "knowledgeImage", "attrs": attrs}]})


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


def test_validate_content_accepts_tiptap_table_cell_alignment_attributes():
    content = {
        "type": "doc",
        "content": [{
            "type": "table",
            "content": [{
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableHeader",
                        "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None, "align": None},
                        "content": [{"type": "paragraph"}],
                    },
                    {
                        "type": "tableCell",
                        "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None, "align": "center"},
                        "content": [{"type": "paragraph"}],
                    },
                ],
            }],
        }],
    }

    assert validate_content(content) == content


@pytest.mark.parametrize("tone", ["gold", "danger", "success", "info"])
def test_validate_content_accepts_semantic_text_colors_without_changing_search_text(tone):
    content = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "content": [{
                "type": "text",
                "text": "受控颜色",
                "marks": [{"type": "textColor", "attrs": {"tone": tone}}],
            }],
        }],
    }

    assert validate_content(content) == content
    assert extract_text(content) == "受控颜色"


@pytest.mark.parametrize(
    "content",
    [
        {},
        {"type": "paragraph"},
        {"type": "doc", "content": [{"type": "script", "text": "alert(1)"}]},
        {"type": "doc", "content": [{"type": "iframe", "attrs": {"src": "https://evil.test"}}]},
        {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 9}}]},
        {"type": "doc", "content": [{"type": "tableCell", "attrs": {"align": "justify"}}]},
        {"type": "doc", "content": [{"type": "text", "text": "x", "marks": [{"type": "textColor", "attrs": {}}]}]},
        {"type": "doc", "content": [{"type": "text", "text": "x", "marks": [{"type": "textColor", "attrs": {"tone": "purple"}}]}]},
        {"type": "doc", "content": [{"type": "text", "text": "x", "marks": [{"type": "textColor", "attrs": {"tone": "gold", "style": "color:red"}}]}]},
        {"type": "doc", "content": [{"type": "text", "text": 3}]},
    ],
)
def test_validate_content_rejects_malformed_or_unknown_nodes(content):
    with pytest.raises(ContentValidationError):
        validate_content(content)


@pytest.mark.parametrize("node_type", ["paragraph", "heading"])
@pytest.mark.parametrize("alignment", [None, "left", "center", "right", "justify"])
def test_authored_alignment_survives_validation(node_type, alignment):
    attrs = {"textAlign": alignment}
    if node_type == "heading":
        attrs["level"] = 2
    content = {"type": "doc", "content": [{"type": node_type, "attrs": attrs}]}
    assert validate_content(content) is content


@pytest.mark.parametrize("size", [12, 13, 14, 15, 16, 19, 22, 24, 29, 32, 40, 48])
@pytest.mark.parametrize("tone", ["gold", "danger", "success", "info"])
def test_authoring_marks_survive_json_export_without_changing_text(size, tone):
    marks = [
        {"type": "underline"},
        {"type": "knowledgeTextSize", "attrs": {"size": size}},
        {"type": "knowledgeHighlight", "attrs": {"tone": tone}},
    ]
    content = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "编辑格式", "marks": marks},
    ]}]}
    exported = json.loads(json.dumps(validate_content(content)))
    assert exported["content"][0]["content"][0]["marks"] == marks
    assert extract_text(exported) == "编辑格式"


@pytest.mark.parametrize("mark", [
    {"type": "underline", "attrs": {"style": "arbitrary"}},
    *[{"type": "knowledgeTextSize", "attrs": {"size": size}}
      for size in [None, True, "16", 16.0, 17, 0, 49]],
    {"type": "knowledgeTextSize", "attrs": {"size": 16, "unit": "px"}},
    {"type": "knowledgeHighlight", "attrs": {}},
    {"type": "knowledgeHighlight", "attrs": {"tone": []}},
    {"type": "knowledgeHighlight", "attrs": {"tone": "purple"}},
    {"type": "knowledgeHighlight", "attrs": {"tone": "gold", "style": "arbitrary"}},
])
def test_authoring_marks_reject_invalid_attributes(mark):
    with pytest.raises(ContentValidationError):
        validate_content({"type": "doc", "content": [{
            "type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [mark]}],
        }]})


def _details_node():
    return {"type": "details", "content": [
        {"type": "detailsSummary", "content": [{"type": "text", "text": "展开摘要"}]},
        {"type": "detailsContent", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "隐藏正文"}]},
            {"type": "knowledgeImage", "attrs": {"assetId": 9, "caption": "正文图片"}},
        ]},
    ]}


@pytest.mark.parametrize("tone", ["gold", "danger", "success", "info"])
def test_callouts_and_details_are_searchable_and_fully_protected(tone):
    details = _details_node()
    callout = {"type": "knowledgeCallout", "attrs": {"tone": tone}, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "提示内容"}]},
        deepcopy(details),
    ]}
    content = {"type": "doc", "content": [callout, details]}
    assert validate_content(content) is content
    assert extract_text(content) == "提示内容\n展开摘要\n隐藏正文\n正文图片\n展开摘要\n隐藏正文\n正文图片"
    assert extract_text_stream(content) == "提示内容展开摘要隐藏正文展开摘要隐藏正文"
    assert extract_asset_ids(content) == [9]
    signature = protected_structure_signature(content)
    assert signature == [
        {"type": "knowledgeCallout", "node": callout},
        {"type": "details", "node": details},
    ]
    details["content"][0]["content"][0]["text"] = "改动摘要"
    assert protected_structure_signature(content) != signature
    assert signature[1]["node"]["content"][0]["content"][0]["text"] == "展开摘要"


@pytest.mark.parametrize("node", [
    {"type": "paragraph", "attrs": {"textAlign": "start"}},
    {"type": "paragraph", "attrs": {"textAlign": []}},
    {"type": "heading", "attrs": {"level": 2, "textAlign": "start"}},
    {"type": "knowledgeCallout", "content": [{"type": "paragraph"}]},
    {"type": "knowledgeCallout", "attrs": {"tone": []}, "content": [{"type": "paragraph"}]},
    {"type": "knowledgeCallout", "attrs": {"tone": "purple"}, "content": [{"type": "paragraph"}]},
    {"type": "knowledgeCallout", "attrs": {"tone": "info"}},
    {"type": "detailsSummary"},
    {"type": "detailsContent", "content": [{"type": "paragraph"}]},
    {"type": "details"},
    {"type": "details", "content": [{"type": "paragraph"}]},
])
def test_authoring_nodes_reject_invalid_attributes_and_orphan_children(node):
    with pytest.raises(ContentValidationError):
        validate_content({"type": "doc", "content": [node]})


@pytest.mark.parametrize("bad_child", [
    {"type": "text", "text": "x"}, {"type": "hardBreak"},
    {"type": "listItem"}, {"type": "tableCell"}, {"type": "doc"},
])
def test_callout_and_details_body_reject_non_block_children(bad_child):
    details = _details_node()
    details["content"][1]["content"] = [bad_child]
    callout = {"type": "knowledgeCallout", "attrs": {"tone": "info"}, "content": [bad_child]}
    for node in [details, callout]:
        with pytest.raises(ContentValidationError):
            validate_content({"type": "doc", "content": [node]})


@pytest.mark.parametrize("mutation", ["reverse", "duplicate", "empty_body", "block_summary", "break_summary", "open_attr"])
def test_details_requires_upstream_summary_and_body_shape(mutation):
    node = _details_node()
    if mutation == "reverse":
        node["content"].reverse()
    elif mutation == "duplicate":
        node["content"].append(deepcopy(node["content"][0]))
    elif mutation == "empty_body":
        node["content"][1]["content"] = []
    elif mutation in {"block_summary", "break_summary"}:
        node["content"][0]["content"] = [{"type": "paragraph" if mutation == "block_summary" else "hardBreak"}]
    else:
        node["attrs"] = {"open": True}
    with pytest.raises(ContentValidationError):
        validate_content({"type": "doc", "content": [node]})


def test_details_accepts_empty_summary_and_empty_paragraph_body():
    content = {"type": "doc", "content": [{"type": "details", "content": [
        {"type": "detailsSummary"},
        {"type": "detailsContent", "content": [{"type": "paragraph"}]},
    ]}]}
    assert validate_content(content) is content
    assert extract_text(content) == ""
