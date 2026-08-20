"""Published-only knowledge tools for authenticated agents."""

import json
from contextlib import contextmanager

from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import SessionLocal
from app.knowledge import service
from app.mcp.auth import MCPAuthError, require_identity


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=128, description="知识库检索关键词")
    limit: int = Field(default=10, ge=1, le=20, description="返回条数，最多20条")


class KnowledgeDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: int = Field(gt=0, description="search_knowledge 返回的 document_id")


@contextmanager
def _session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _search(db, identity: dict, query: str, limit: int) -> str:
    try:
        items = service.search_published(
            db, identity, query, limit=min(max(int(limit), 1), 20), audit_action="mcp_search"
        )
        return _json({"ok": True, "count": len(items), "items": items})
    except service.KnowledgeError as exc:
        return _json({"ok": False, "error": str(exc)})


def _get_document(db, identity: dict, document_id: int) -> str:
    try:
        row = service.get_published_document(
            db, identity, document_id, audit_action="mcp_read"
        )
        return _json({
            "ok": True,
            "document": {
                "document_id": row["document_id"],
                "title": row["title"],
                "content": row["content_text"],
                "version_no": row["version_no"],
            },
        })
    except service.KnowledgeError as exc:
        return _json({"ok": False, "error": str(exc)})


def register_knowledge_tools(mcp) -> None:
    @mcp.tool(
        name="search_knowledge",
        annotations={
            "title": "检索企业知识库",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def search_knowledge(params: KnowledgeSearchInput, ctx: Context) -> str:
        """检索当前账号有权访问的已发布企业知识；草稿和待审版本永不返回。"""
        with _session() as db:
            try:
                identity = require_identity(ctx, db, tool_name="search_knowledge")
            except MCPAuthError as exc:
                return _json({"ok": False, "error": str(exc)})
            return _search(db, identity, params.query, params.limit)

    @mcp.tool(
        name="get_knowledge_document",
        annotations={
            "title": "读取企业知识文档",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_knowledge_document(params: KnowledgeDocumentInput, ctx: Context) -> str:
        """读取当前账号有权访问的单个已发布文档纯文本。"""
        with _session() as db:
            try:
                identity = require_identity(ctx, db, tool_name="get_knowledge_document")
            except MCPAuthError as exc:
                return _json({"ok": False, "error": str(exc)})
            return _get_document(db, identity, params.document_id)
