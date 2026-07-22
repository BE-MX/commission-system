"""Standalone stateless Streamable HTTP MCP application."""

import asyncio
import contextlib
import logging

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.exc import SQLAlchemyError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .auth import BearerAuthMiddleware
from .config import get_settings
from .models import SocialCustomerSearchInput, SocialCustomerSearchResult
from .query_service import SocialCustomerQueryService, create_db_engine

logger = logging.getLogger("social_customer_mcp")
settings = get_settings()
engine = create_db_engine()
query_service = SocialCustomerQueryService(engine)

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=settings.allowed_hosts,
    allowed_origins=settings.allowed_origins,
)

mcp = FastMCP(
    "social_customer_mcp",
    instructions=(
        "按邮箱、社交账号或联系人电话精确查询莱莎客户资料。"
        "只读；每次必须且只能提供一种查询条件。"
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=transport_security,
)


@mcp.tool(
    name="social_customer_search",
    annotations={
        "title": "查询社媒客户资料",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def social_customer_search(
    params: SocialCustomerSearchInput,
    ctx: Context,
) -> SocialCustomerSearchResult:
    """通过邮箱、社交账号或联系人电话精确查询客户及归属用户。

    Args:
        params: email、social_account、contact_phone 必须且只能填写一个；支持 limit/offset 分页。

    Returns:
        结构化结果包含 customer_company、customer_name、contact_name、customer_email、
        contact_email、contact_phone、social_platform、social_account、owner_user_name。
        客户没有负责人时 owner_user_name 固定为“未进入私海”。

    该工具不会模糊搜索、不会修改数据库，也不会返回未命中条件的其他客户。
    """
    try:
        return await asyncio.to_thread(query_service.search, params)
    except SQLAlchemyError:
        logger.exception("social customer database query failed")
        raise ToolError("客户查询暂时不可用，请稍后重试；持续失败请联系服务管理员") from None
    except Exception as exc:
        logger.error("unexpected social customer query failure: %s", type(exc).__name__)
        raise ToolError("客户查询失败，请稍后重试；持续失败请联系服务管理员") from None


async def health(_request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "social_customer_mcp"})


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with mcp.session_manager.run():
        yield
    engine.dispose()


_mcp_app = mcp.streamable_http_app()
_starlette_app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Mount("/", app=_mcp_app),
    ],
    lifespan=lifespan,
)
app = BearerAuthMiddleware(_starlette_app, settings.token.get_secret_value())
