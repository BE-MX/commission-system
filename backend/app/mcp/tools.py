"""MCP 工具集 — 物流录单 / 查询 / 我的运单。

薄壳:身份(require_identity) → 权限校验 → 调 tracking service → 结构化 JSON 回执。
底层复用 upload_service / shipment_service / polling_service，零业务逻辑重写。
"""

import json
import logging
from contextlib import contextmanager

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.exc import IntegrityError
from mcp.server.fastmcp import Context

from app.core.database import SessionLocal
from app.mcp.auth import require_identity, MCPAuthError
from app.tracking import shipment_service, upload_service
from app.tracking.models import ShipmentTracking
from app.tracking.schemas import WaybillCreate
from app.tracking.upload_service import WaybillConflict
from app.tracking.polling_service import refresh_single

logger = logging.getLogger("commission.mcp.tools")

SUPPORTED_CARRIERS = ["DHL", "FEDEX"]
# MCP 入口 carrier → WaybillCreate.carrier 的 Literal 值（注意 FedEx 大小写）
_CARRIER_TO_WAYBILL = {"DHL": "DHL", "FEDEX": "FedEx"}


@contextmanager
def _session():
    """MCP 工具自管 session（mounted 子 ASGI app 不走 FastAPI get_db 依赖）。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _has_perm(user: dict, *codes: str) -> bool:
    """super_admin 绕过；否则命中任一权限码即通过。"""
    if "super_admin" in user.get("roles", []):
        return True
    perms = set(user.get("permissions", []))
    return any(c in perms for c in codes)


def _visible_under_scope(db, user: dict, waybill_no: str) -> bool:
    """该运单在当前用户的数据范围内是否可见（归属 or read_all/super_admin）。

    复用 shipment_service.apply_data_scope，与 list 口径一致：不可见即视为"未跟踪"，
    既不越权读他人 PII，也不泄露运单是否存在。
    """
    q = db.query(ShipmentTracking).filter(ShipmentTracking.waybill_no == waybill_no)
    q = shipment_service.apply_data_scope(q, db, user)
    return q.first() is not None


def _err(message: str, **extra) -> str:
    return json.dumps({"ok": False, "error": message, **extra}, ensure_ascii=False)


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, **data}, ensure_ascii=False, default=str, indent=2)


def _norm_carrier(raw: str) -> str:
    """归一化到 DHL/FEDEX；不支持则抛 ValueError 并列出支持项。"""
    u = (raw or "").strip().upper().replace(" ", "")
    if u == "FEDEX":
        return "FEDEX"
    if u == "DHL":
        return "DHL"
    raise ValueError(f"暂不支持的物流商 '{raw}'，当前支持：{', '.join(SUPPORTED_CARRIERS)}")


# ── 输入模型 ──────────────────────────────────────────────

class RecordShipmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    waybill_no: str = Field(..., description="物流运单号", min_length=1, max_length=50)
    carrier: str = Field(..., description="物流商，取值 DHL 或 FEDEX")
    recipient_name: str = Field(..., description="收件人姓名", min_length=1, max_length=100)
    recipient_country: str = Field(..., description="收件国家/地区", min_length=1, max_length=100)
    ship_date: str = Field(..., description="发件日期，格式 YYYY-MM-DD，不能是未来日期")


class TrackShipmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    waybill_no: str = Field(..., description="要查询的物流运单号", min_length=1, max_length=50)
    refresh: bool = Field(
        default=False,
        description="是否强制向承运商实时刷新一次（默认 false，返回平台已轮询的最新缓存，避免消耗承运商配额）",
    )


class ListMyShipmentsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: str = Field(default="", description="按状态筛选，如 in_transit/delivered/customs/exception，留空为全部")
    keyword: str = Field(default="", description="运单号/收件人/收件公司模糊搜索，留空为不限")
    limit: int = Field(default=20, description="返回条数上限", ge=1, le=100)


# ── 工具注册 ──────────────────────────────────────────────

def register_tools(mcp) -> None:
    """把 3 个工具注册到传入的 FastMCP 实例。"""

    @mcp.tool(
        name="record_shipment",
        annotations={
            "title": "录入物流运单并启动跟踪",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,  # 同运单号重复调用不会重复建单（返回已存在）
            "openWorldHint": True,
        },
    )
    async def record_shipment(params: RecordShipmentInput, ctx: Context) -> str:
        """录入一张物流运单到平台并自动启动物流跟踪，立即返回当前物流状态。

        归属自动落到调用者（个人 token 对应的业务员）。运单号已存在时不会重复建单。

        Returns: JSON 字符串
          成功: {"ok": true, "waybill_no", "carrier", "tracking_status",
                 "tracking_status_text", "estimated_delivery_date"?, "short_link"?,
                 "shipping_template"}
          已存在: {"ok": true, "already_recorded": true, ...}
          失败: {"ok": false, "error": "<可执行的错误说明>"}
        """
        with _session() as db:
            try:
                user = require_identity(ctx, db)
            except MCPAuthError as e:
                return _err(str(e))

            if not _has_perm(user, "tracking:write"):
                return _err("权限不足：录单需要 tracking:write 权限，请联系管理员分配")

            try:
                carrier = _norm_carrier(params.carrier)
                payload = WaybillCreate(
                    waybill_no=params.waybill_no,
                    carrier=_CARRIER_TO_WAYBILL[carrier],
                    recipient_name=params.recipient_name,
                    recipient_country=params.recipient_country,
                    ship_date=params.ship_date,
                    entry_source="manual",
                )
            except ValueError as e:
                return _err(f"参数校验失败：{e}")
            except Exception as e:  # pydantic ValidationError 等
                return _err(f"参数校验失败：{e}")

            def _already(existing: dict) -> str:
                # 幂等语义:同运单号已存在即返回 already_recorded；只回非敏感字段，
                # 不泄露录入人(created_by)——跨归属撞号时避免暴露"这单是谁录的"
                return _err(
                    f"运单号 {params.waybill_no} 已存在，无需重复录入",
                    already_recorded=True,
                    existing={
                        "waybill_no": existing.get("waybill_no"),
                        "status": existing.get("status"),
                    },
                )

            try:
                data = await upload_service.create_waybill_with_tracking(db, payload, user)
            except WaybillConflict as e:
                return _already(e.existing or {})
            except IntegrityError as e:
                # 并发下前置去重放过、insert 撞唯一约束 → 仍按幂等回执，与 idempotentHint 一致
                db.rollback()
                logger.warning("MCP record_shipment 并发唯一约束冲突 wb=%s: %s", params.waybill_no, e)
                print(f"[mcp.tools] record_shipment race conflict wb={params.waybill_no}", flush=True)
                existing = upload_service.check_waybill_exists(db, params.waybill_no) or {"waybill_no": params.waybill_no}
                return _already(existing)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                logger.exception("MCP record_shipment 失败: %s", e)
                print(f"[mcp.tools] record_shipment failed wb={params.waybill_no} err={e}", flush=True)
                return _err("录入失败，请稍后重试或改用平台页面录入")

            return _ok({
                "waybill_no": data.get("waybill_no"),
                "carrier": data.get("carrier"),
                "tracking_status": data.get("tracking_status", "pending"),
                "tracking_status_text": data.get("tracking_status_text"),
                "estimated_delivery_date": data.get("estimated_delivery_date"),
                "short_link": data.get("short_link"),
                "shipping_template": data.get("shipping_template"),
            })

    @mcp.tool(
        name="track_shipment",
        annotations={
            "title": "查询运单物流状态与轨迹",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def track_shipment(params: TrackShipmentInput, ctx: Context) -> str:
        """查询某个运单的当前物流状态与完整轨迹。

        默认返回平台已轮询的最新数据；refresh=true 时先向承运商实时刷新一次。
        运单未在平台跟踪时，返回提示引导先用 record_shipment 录入。

        Returns: JSON 字符串
          成功: {"ok": true, "waybill_no", "carrier", "current_status",
                 "current_status_text", "current_location", "last_event_time",
                 "estimated_delivery_date", "events": [{event_time, description, location, status_code}]}
          未跟踪: {"ok": false, "error": "...", "not_tracked": true}
        """
        with _session() as db:
            try:
                user = require_identity(ctx, db)
            except MCPAuthError as e:
                return _err(str(e))

            if not _has_perm(user, "tracking:read", "tracking:read_all"):
                return _err("权限不足：查询需要 tracking:read 权限，请联系管理员分配")

            waybill_no = params.waybill_no.strip()

            # 归属校验(先于 refresh/读):不在数据范围内 → 当作未跟踪，既不越权读他人 PII/轨迹，
            # 也不放任 refresh 消耗承运商配额去刷别人的单
            if not _visible_under_scope(db, user, waybill_no):
                return _err(
                    f"运单 {waybill_no} 尚未在平台跟踪，请先用 record_shipment 录入",
                    not_tracked=True,
                )

            if params.refresh:
                try:
                    r = await refresh_single(db, waybill_no)
                    if isinstance(r, dict) and "error" in r:
                        return _err(
                            f"运单 {waybill_no} 尚未在平台跟踪，请先用 record_shipment 录入",
                            not_tracked=True,
                        )
                except Exception as e:  # noqa: BLE001
                    logger.warning("MCP track_shipment 实时刷新失败 wb=%s: %s", waybill_no, e)
                    print(f"[mcp.tools] refresh failed wb={waybill_no} err={e}", flush=True)
                    # 降级:继续返回 DB 已有数据

            detail = shipment_service.get_shipment_detail(db, waybill_no)
            if detail is None:
                return _err(
                    f"运单 {waybill_no} 尚未在平台跟踪，请先用 record_shipment 录入",
                    not_tracked=True,
                )

            events = [
                {
                    "event_time": ev.get("event_time"),
                    "description": ev.get("description"),
                    "location": ev.get("location"),
                    "status_code": ev.get("status_code"),
                }
                for ev in (detail.get("events") or [])
            ]
            return _ok({
                "waybill_no": detail.get("waybill_no"),
                "carrier": detail.get("carrier"),
                "current_status": detail.get("current_status"),
                "current_status_text": detail.get("current_status_text"),
                "current_location": detail.get("current_location"),
                "last_event_time": detail.get("last_event_time"),
                "estimated_delivery_date": detail.get("estimated_delivery_date"),
                "events": events,
            })

    @mcp.tool(
        name="list_my_shipments",
        annotations={
            "title": "列出我名下的运单",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_my_shipments(params: ListMyShipmentsInput, ctx: Context) -> str:
        """列出当前业务员名下的运单（按数据范围权限自动过滤归属）。

        Returns: JSON 字符串
          {"ok": true, "total": int, "count": int,
           "items": [{waybill_no, carrier, current_status, current_status_text,
                      receiver_name, receiver_country, last_event_time, estimated_delivery_date}]}
        """
        with _session() as db:
            try:
                user = require_identity(ctx, db)
            except MCPAuthError as e:
                return _err(str(e))

            if not _has_perm(user, "tracking:read", "tracking:read_all"):
                return _err("权限不足：查询需要 tracking:read 权限，请联系管理员分配")

            try:
                result = shipment_service.list_shipments(
                    db, user,
                    status=params.status, keyword=params.keyword,
                    page=1, page_size=params.limit,
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("MCP list_my_shipments 失败: %s", e)
                print(f"[mcp.tools] list_my_shipments failed err={e}", flush=True)
                return _err("查询失败，请稍后重试")

            items = [
                {
                    "waybill_no": it.get("waybill_no"),
                    "carrier": it.get("carrier"),
                    "current_status": it.get("current_status"),
                    "current_status_text": it.get("current_status_text"),
                    "receiver_name": it.get("receiver_name"),
                    "receiver_country": it.get("receiver_country"),
                    "last_event_time": it.get("last_event_time"),
                    "estimated_delivery_date": it.get("estimated_delivery_date"),
                }
                for it in result.get("items", [])
            ]
            return _ok({
                "total": result.get("total", 0),
                "count": len(items),
                "items": items,
            })
