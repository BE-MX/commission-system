"""MCP server 装配 — FastMCP 实例 + 工具注册 + mount/lifespan 接入主 app。

对外暴露:
  - mount_mcp(app):把 streamable-http ASGI 子应用挂到主 app 的 /mcp
  - mcp_session_lifespan():主 app lifespan 内需 `async with` 包住，驱动 session manager

传输:Streamable HTTP + 无状态 JSON(stateless_http + json_response)——第三方 agent
远程接入的标准形态，无需维持会话，易于水平扩展。
"""

import logging

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.mcp.tools import register_tools
from app.mcp.asset_tools import register_asset_tools

logger = logging.getLogger("commission.mcp.server")

# DNS-rebinding 防护默认开启且 allowed_hosts=[] → 拒绝一切 Host(含生产域名)返回 421。
# 该防护是为本地 stdio 类服务防浏览器恶意 JS 设计的;本服务是 Nginx 后、token 鉴权的
# 公网 Web 服务,由远程 agent 用任意 Host 访问,真正安全边界是 Bearer token,故关闭之。
_transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

# streamable_http_path 设为 "/"，再 mount 到 "/mcp"，最终对外端点为 /mcp（不叠成 /mcp/mcp）
mcp = FastMCP(
    "leshine_tracking_mcp",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=_transport_security,
)
register_tools(mcp)
register_asset_tools(mcp)

# 构建 ASGI 子应用（同时初始化 session_manager）
_mcp_asgi_app = mcp.streamable_http_app()


def mount_mcp(app: FastAPI) -> None:
    """把 MCP streamable-http 子应用挂到主 app 的 /mcp 路径。"""
    app.mount("/mcp", _mcp_asgi_app)
    logger.info(
        "MCP server mounted at /mcp (tools: record_shipment/track_shipment/list_my_shipments"
        "/list_asset_taxonomy/search_assets)"
    )


def mcp_session_lifespan():
    """返回 session manager 的 async 上下文，供主 app lifespan 包裹。"""
    return mcp.session_manager.run()
