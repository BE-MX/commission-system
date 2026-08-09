import json

import pytest

from app.mcp.knowledge_tools import _get_document, _search


def test_mcp_search_caps_limit_and_uses_published_service(monkeypatch):
    captured = {}

    def fake_search(db, identity, query, *, limit, audit_action):
        captured.update(query=query, limit=limit, audit_action=audit_action, identity=identity)
        return [{"document_id": 8, "title": "制度"}]

    monkeypatch.setattr("app.mcp.knowledge_tools.service.search_published", fake_search)
    identity = {"sub": "2", "permissions": ["knowledge:read"], "roles": []}
    payload = json.loads(_search(object(), identity, "制度", 999))

    assert payload["ok"] is True
    assert captured == {"query": "制度", "limit": 20, "audit_action": "mcp_search", "identity": identity}


def test_mcp_get_returns_plain_text_not_editor_json(monkeypatch):
    monkeypatch.setattr(
        "app.mcp.knowledge_tools.service.get_published_document",
        lambda db, identity, document_id, audit_action: {
            "document_id": document_id,
            "title": "流程",
            "content_text": "只返回纯文本",
            "content_json": {"type": "doc"},
            "version_no": 3,
        },
    )
    payload = json.loads(_get_document(object(), {"sub": "2"}, 7))
    assert payload["ok"] is True
    assert payload["document"]["content"] == "只返回纯文本"
    assert "content_json" not in payload["document"]


@pytest.mark.asyncio
async def test_mcp_server_registers_knowledge_tools():
    from app.mcp.server import mcp

    names = {tool.name for tool in await mcp.list_tools()}
    assert {"search_knowledge", "get_knowledge_document"} <= names
