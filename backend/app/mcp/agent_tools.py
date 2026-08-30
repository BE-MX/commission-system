"""Nine scoped, read-only customer tools backed exclusively by Ark projections."""

from contextlib import contextmanager
from datetime import date, datetime
import json
import logging

from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import event, text

from app.core.database import SessionLocal
from app.customer import agent_service
from app.mcp.auth import MCPAuthError, require_identity


logger = logging.getLogger("commission.mcp.agent_tools")


def _reject_flush(*_args) -> None:
    raise RuntimeError("READ_ONLY_SESSION")


@contextmanager
def _read_session():
    """Consumer tools never commit; database grants remain the outer boundary."""
    db = SessionLocal()
    event.listen(db, "before_flush", _reject_flush)
    try:
        if db.bind is not None and db.bind.dialect.name == "mysql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        with db.no_autoflush:
            yield db
    finally:
        db.rollback()
        db.close()


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _require_agent_identity(ctx, db, *, tool_name: str) -> dict:
    identity = require_identity(ctx, db, tool_name=tool_name)
    if not identity.get("_agent_run"):
        raise MCPAuthError("该工具仅允许受控 Agent Run 调用")
    return identity


def _invoke(ctx, tool_name: str, call):
    with _read_session() as db:
        try:
            user = _require_agent_identity(ctx, db, tool_name=tool_name)
            return _ok(call(db, user))
        except (MCPAuthError, agent_service.CustomerAgentAccessError, ValueError) as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Customer Agent tool failed tool=%s type=%s", tool_name, type(exc).__name__)
            print(f"[mcp.customer] tool={tool_name} failed type={type(exc).__name__}", flush=True)
            return _err("CUSTOMER_TOOL_FAILED")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResolveCustomerInput(_Input):
    value: str = Field(..., min_length=1, max_length=255)
    identifier_type: str | None = Field(None, max_length=32)
    limit: int = Field(10, ge=1, le=50)


class SearchCustomersInput(_Input):
    keyword: str | None = Field(None, max_length=255)
    identifier_type: str | None = Field(None, max_length=32)
    cursor: str | None = Field(None, max_length=2048)
    limit: int = Field(20, ge=1, le=50)


class CustomerInput(_Input):
    customer_id: int = Field(..., ge=1)


class CustomerProfileInput(CustomerInput):
    sections: list[str] | None = Field(None, max_length=20)


class CustomerFactsInput(CustomerInput):
    fact_keys: list[str] | None = Field(None, max_length=50)
    layers: list[str] | None = Field(None, max_length=10)
    statuses: list[str] | None = Field(None, max_length=10)
    cursor: str | None = Field(None, max_length=2048)
    limit: int = Field(50, ge=1, le=50)


class CustomerOrdersInput(CustomerInput):
    date_from: date | None = None
    date_to: date | None = None
    include_items: bool = False
    cursor: str | None = Field(None, max_length=2048)
    limit: int = Field(50, ge=1, le=50)


class CustomerMessagesInput(CustomerInput):
    conversation_id: int | None = Field(None, ge=1)
    query: str | None = Field(None, max_length=255)
    date_from: datetime | None = None
    date_to: datetime | None = None
    cursor: str | None = Field(None, max_length=2048)
    limit: int = Field(20, ge=1, le=50)


class CustomerActionsInput(CustomerInput):
    statuses: list[str] | None = Field(None, max_length=10)
    cursor: str | None = Field(None, max_length=2048)
    limit: int = Field(50, ge=1, le=50)


class CustomerEvidenceInput(CustomerInput):
    fact_ids: list[int] = Field(..., min_length=1, max_length=50)


class CustomerSourceChunksInput(CustomerInput):
    source_record_id: int = Field(..., ge=1)
    locator: dict | None = None
    max_chars: int = Field(2_000, ge=1, le=12_000)


def register_agent_tools(mcp) -> None:
    def register(name, input_type, service_call):
        @mcp.tool(name=name, annotations={"readOnlyHint": True})
        async def tool(params: input_type, ctx: Context) -> str:
            values = params.model_dump(exclude_none=True)
            return _invoke(
                ctx, name, lambda db, user: service_call(db, user=user, **values),
            )
        return tool

    register("resolve_customer", ResolveCustomerInput, agent_service.resolve_customer)
    register("search_customers", SearchCustomersInput, agent_service.search_customers)
    register("get_customer_profile", CustomerProfileInput, agent_service.get_customer_profile)
    register("get_customer_facts", CustomerFactsInput, agent_service.get_customer_facts)
    register("get_customer_orders", CustomerOrdersInput, agent_service.get_customer_orders)
    register("search_customer_messages", CustomerMessagesInput, agent_service.search_customer_messages)
    register("get_customer_actions", CustomerActionsInput, agent_service.get_customer_actions)
    register("get_customer_evidence", CustomerEvidenceInput, agent_service.get_customer_evidence)
    register("get_customer_source_chunks", CustomerSourceChunksInput, agent_service.get_customer_source_chunks)


__all__ = [
    "CustomerActionsInput", "CustomerEvidenceInput", "CustomerFactsInput", "CustomerInput",
    "CustomerMessagesInput", "CustomerOrdersInput", "CustomerProfileInput",
    "CustomerSourceChunksInput", "ResolveCustomerInput", "SearchCustomersInput",
    "register_agent_tools",
]
