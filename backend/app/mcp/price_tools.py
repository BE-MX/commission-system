"""Read-only product and standard-price lookups for authenticated MCP agents."""

import json
import logging
from contextlib import contextmanager

from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import SessionLocal
from app.invoice import price_service, product_service
from app.mcp.auth import MCPAuthError, require_identity

logger = logging.getLogger("commission.mcp.price_tools")


class StandardPriceInput(BaseModel):
    """Exact dimensions for one standard hair-price matrix cell."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    product_display: str = Field(
        min_length=1,
        max_length=128,
        description="产品系列/等级名称，例如 Super Double Drawn Genius Weft",
    )
    length: str = Field(min_length=1, max_length=32, description="长度，例如 20、20 inch 或 20寸")
    unit: str = Field(min_length=1, max_length=32, description="单件克重，例如 20g")
    color: str = Field(min_length=1, max_length=64, description="色号，例如 #1B、18P613")


class ProductMatchInput(BaseModel):
    """Exact structured product-catalog match dimensions."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(min_length=1, max_length=128, description="产品型号")
    color: str = Field(min_length=1, max_length=128, description="色号")
    size: str = Field(min_length=1, max_length=64, description="长度/规格")
    unit: str = Field(min_length=1, max_length=64, description="单件克重或单位")


@contextmanager
def _session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _can_read_price(identity: dict) -> bool:
    return (
        "super_admin" in identity.get("roles", [])
        or "invoice_price:read" in identity.get("permissions", [])
    )


def _get_standard_price(
    db,
    identity: dict,
    *,
    product_display: str,
    length: str,
    unit: str,
    color: str,
) -> str:
    """Resolve exactly one standard matrix cell without customer pricing data."""
    if not _can_read_price(identity):
        return _json({
            "ok": False,
            "error": "权限不足：需要 invoice_price:read 权限，请联系管理员分配",
        })

    try:
        resolved = price_service.resolve_price(
            db,
            customer_id=None,
            product_display=product_display,
            length=length,
            unit=unit,
            color=color,
        )
    except Exception as exc:  # noqa: BLE001 - MCP must not expose database details
        logger.exception("MCP standard price lookup failed")
        print(f"[mcp.price_tools] standard price lookup failed type={type(exc).__name__}", flush=True)
        return _json({"ok": False, "error": "标准价格查询失败，请稍后重试"})
    standard_price = resolved["standard_price"]
    if standard_price is None:
        return _json({
            "ok": False,
            "error": "未匹配到标准价格，请核对产品系列、长度、克重和色号后重试；不得据此自行估价",
        })

    return _json({
        "ok": True,
        "price": {
            "product_display": product_display,
            "length": price_service.normalize_length(length),
            "unit": price_service.normalize_text(unit),
            "color": color,
            "color_type": resolved["color_type"],
            "color_type_source": resolved["color_type_source"],
            "standard_reference_price": standard_price,
            "currency": resolved["currency"],
            "quote_status": "reference_only",
            "requires_quote_confirmation": True,
        },
    })


def _find_product(
    db,
    identity: dict,
    *,
    model: str,
    color: str,
    size: str,
    unit: str,
) -> str:
    """Match the structured product catalog without exporting it in bulk."""
    if not _can_read_price(identity):
        return _json({
            "ok": False,
            "error": "权限不足：需要 invoice_price:read 权限，请联系管理员分配",
        })
    try:
        result = product_service.match_product(
            db,
            model=model,
            color=color,
            size=size,
            unit=unit,
        )
    except Exception as exc:  # noqa: BLE001 - MCP must not expose database details
        logger.exception("MCP product lookup failed")
        print(f"[mcp.price_tools] product lookup failed type={type(exc).__name__}", flush=True)
        return _json({"ok": False, "error": "产品查询失败，请稍后重试"})
    return _json({"ok": True, **result})


def register_price_tools(mcp) -> None:
    """Register exact, read-only product and standard-price lookups."""

    @mcp.tool(
        name="get_standard_price",
        annotations={
            "title": "查询标准参考价格",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_standard_price(params: StandardPriceInput, ctx: Context) -> str:
        """查询一个产品规格对应的当前标准参考价。

        本工具只读、一次只返回一个标准价格矩阵格，不提供整表遍历、客户价格、
        客户调价规则或正式报价。调用账号必须具有 invoice_price:read 权限。

        Args:
            params: 产品系列、长度、克重和色号四个精确查询条件。
            ctx: FastMCP 注入的 HTTP 请求上下文，用于解析个人 Bearer token。

        Returns:
            JSON 字符串。成功时包含 standard_reference_price、currency、color_type、
            quote_status=reference_only 和 requires_quote_confirmation=true；失败时包含
            ok=false 与可执行的权限或匹配提示。
        """
        with _session() as db:
            try:
                identity = require_identity(ctx, db)
            except MCPAuthError as exc:
                return _json({"ok": False, "error": str(exc)})
            return _get_standard_price(
                db,
                identity,
                product_display=params.product_display,
                length=params.length,
                unit=params.unit,
                color=params.color,
            )

    @mcp.tool(
        name="find_product",
        annotations={
            "title": "匹配产品目录",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def find_product(params: ProductMatchInput, ctx: Context) -> str:
        """按型号、色号、规格和单位匹配当前结构化产品目录。

        本工具只返回精确条件命中的有限候选，不提供整目录导出。调用账号必须具有
        invoice_price:read 权限；唯一命中时 item 有值，多条或零条命中时由
        is_unique=false 与 matches 列表引导 Agent 补充或修正条件。

        Args:
            params: 型号、色号、规格和单位四个精确查询条件。
            ctx: FastMCP 注入的 HTTP 请求上下文，用于解析个人 Bearer token。

        Returns:
            JSON 字符串，包含 ok、is_unique、item 和 matches；不包含客户、订单、
            库存或客户价格规则。
        """
        with _session() as db:
            try:
                identity = require_identity(ctx, db)
            except MCPAuthError as exc:
                return _json({"ok": False, "error": str(exc)})
            return _find_product(
                db,
                identity,
                model=params.model,
                color=params.color,
                size=params.size,
                unit=params.unit,
            )
