"""Read-only Ark business tools exposed only through governed identity scopes."""

from contextlib import contextmanager
from datetime import date, timedelta
from app.core.time import beijing_today
import json
import logging

from fastapi import HTTPException
from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.models import AgentRun
from app.core.database import SessionLocal
from app.customer.access_service import (
    CustomerAccessDenied,
    apply_record_access,
    require_customer_access,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerEvent,
    CustomerExternalIdentity,
    CustomerListProjection,
)
from app.mcp.auth import MCPAuthError, require_identity
from app.order_intelligence import service as order_service
from app.sales_automation import service as sales_service


logger = logging.getLogger("commission.mcp.agent_tools")


@contextmanager
def _session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str, indent=2)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _known_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


def _unexpected(exc: Exception, fallback: str) -> str:
    logger.warning("Agent MCP business tool failed: %s", type(exc).__name__)
    return _err(fallback)


def _has_perm(user: dict, *codes: str) -> bool:
    return "super_admin" in set(user.get("roles") or []) or bool(set(codes) & set(user.get("permissions") or []))


def _require_agent_identity(ctx, db, *, tool_name: str) -> dict:
    """Agent business tools are callable only inside a governed Run scope."""
    identity = require_identity(ctx, db, tool_name=tool_name)
    if not identity.get("_agent_run"):
        raise MCPAuthError("该工具仅允许受控 Agent Run 调用")
    return identity


def _customer_for_user(
    db,
    customer_id: int,
    user: dict,
    *,
    minimum_classification: str = "public_business",
    minimum_visibility: str = "all_authorized",
) -> CustomerAccount | None:
    access = _customer_access_for_user(db, customer_id, user)
    if (
        access is None
        or not access.allows_classification(minimum_classification)
        or not access.allows_visibility(minimum_visibility)
    ):
        return None
    return db.get(CustomerAccount, customer_id)


def _customer_access_for_user(db, customer_id: int, user: dict):
    try:
        return require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions={
                "customer_radar:read",
                "customer_radar:write",
                "customer_radar:manage",
                "order_intelligence:read",
                "order_intelligence:read_all",
            },
            manage_permissions={
                "customer_radar:manage",
                "order_intelligence:read_all",
            },
        )
    except CustomerAccessDenied:
        return None


def _okki_customer_id(db, customer_id: int) -> str | None:
    identity = db.query(CustomerExternalIdentity).filter(
        CustomerExternalIdentity.customer_id == customer_id,
        CustomerExternalIdentity.source_system == "okki",
        CustomerExternalIdentity.identifier_type.in_(("company_id", "business_id")),
        CustomerExternalIdentity.verification_status == "verified",
        CustomerExternalIdentity.status == "active",
    ).order_by(CustomerExternalIdentity.is_primary.desc(), CustomerExternalIdentity.id).first()
    return identity.normalized_value if identity is not None else None


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(..., ge=1, description="方舟统一客户 ID")


class CustomerOrderInput(CustomerInput):
    date_from: date | None = Field(None, description="起始日期，默认近三年")
    date_to: date | None = Field(None, description="截止日期，默认今天")
    limit: int = Field(50, ge=1, le=100)


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: date | None = None
    date_to: date | None = None


class SearchJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int = Field(..., ge=1)


def _window(start: date | None, end: date | None) -> tuple[date, date]:
    actual_end = end or beijing_today()
    actual_start = start or (actual_end - timedelta(days=1095))
    return order_service.normalize_window(actual_start, actual_end)


def register_agent_tools(mcp) -> None:
    @mcp.tool(name="get_customer_profile", annotations={"readOnlyHint": True})
    async def get_customer_profile(params: CustomerInput, ctx: Context) -> str:
        with _session() as db:
            try:
                user = _require_agent_identity(ctx, db, tool_name="get_customer_profile")
            except MCPAuthError as exc:
                return _err(str(exc))
            if not _has_perm(user, "customer_radar:read", "customer_radar:write", "customer_radar:manage"):
                return _err("权限不足：需要客户经营雷达查看权限")
            access = _customer_access_for_user(db, params.customer_id, user)
            if access is None:
                return _err("客户画像不存在或不在当前账号数据范围内")
            row = db.get(CustomerAccount, params.customer_id)
            internal_context_allowed = (
                access.allows_classification("internal_business")
                and access.allows_visibility("customer_team")
            )
            if not internal_context_allowed:
                return _ok({
                    "customer_id": row.id,
                    "schema_version": "customer_profile_redacted_v1",
                    "redacted": True,
                    "data_classification": "public_business",
                })
            events = apply_record_access(
                db.query(CustomerEvent),
                CustomerEvent,
                access,
            ).order_by(CustomerEvent.occurred_at.desc()).limit(30).all()
            projection = db.get(CustomerListProjection, row.id)
            data = {
                "customer_id": row.id,
                "display_name": row.display_name,
                "canonical_company_name": row.canonical_company_name,
                "events": [{
                    "event_id": item.id,
                    "source": item.event_source,
                    "type": item.event_type,
                    "title": item.event_title,
                    "summary": item.event_summary,
                    "occurred_at": item.occurred_at,
                } for item in events],
                "data_classification": "internal_business",
            }
            data.update({
                "customer_code": row.customer_code,
                "identity_status": row.identity_status,
                "relationship_stage": row.relationship_stage,
                "commercial_value_score": (
                    projection.commercial_value_score if projection else 0
                ),
                "data_quality_score": (
                    projection.data_quality_score if projection else 0
                ),
            })
            return _ok(data)

    @mcp.tool(name="get_customer_order_timeline", annotations={"readOnlyHint": True})
    async def get_customer_order_timeline(params: CustomerOrderInput, ctx: Context) -> str:
        with _session() as db:
            try:
                user = _require_agent_identity(ctx, db, tool_name="get_customer_order_timeline")
            except MCPAuthError as exc:
                return _err(str(exc))
            if not _has_perm(user, "order_intelligence:read", "order_intelligence:read_all"):
                return _err("权限不足：需要订单经营分析查看权限")
            customer = _customer_for_user(
                db,
                params.customer_id,
                user,
                minimum_classification="internal_business",
                minimum_visibility="customer_team",
            )
            external_id = _okki_customer_id(db, customer.id) if customer is not None else None
            if customer is None or not external_id:
                return _err("客户画像不存在、越权或尚未绑定 OKKI 客户 ID")
            try:
                start, end = _window(params.date_from, params.date_to)
                scope = order_service.resolve_scope(db, user)
                return _ok(order_service.get_customer_order_timeline(
                    db, scope, external_id, start, end, limit=params.limit,
                ))
            except (ValueError, HTTPException) as exc:
                return _err(_known_error(exc))
            except Exception as exc:  # noqa: BLE001
                return _unexpected(exc, "订单时间线查询失败，请稍后重试")

    @mcp.tool(name="get_customer_repurchase_analysis", annotations={"readOnlyHint": True})
    async def get_customer_repurchase_analysis(params: CustomerOrderInput, ctx: Context) -> str:
        with _session() as db:
            try:
                user = _require_agent_identity(ctx, db, tool_name="get_customer_repurchase_analysis")
            except MCPAuthError as exc:
                return _err(str(exc))
            if not _has_perm(user, "order_intelligence:read", "order_intelligence:read_all"):
                return _err("权限不足：需要订单经营分析查看权限")
            customer = _customer_for_user(
                db,
                params.customer_id,
                user,
                minimum_classification="internal_business",
                minimum_visibility="customer_team",
            )
            external_id = _okki_customer_id(db, customer.id) if customer is not None else None
            if customer is None or not external_id:
                return _err("客户画像不存在、越权或尚未绑定 OKKI 客户 ID")
            try:
                start, end = _window(params.date_from, params.date_to)
                scope = order_service.resolve_scope(db, user)
                return _ok(order_service.get_customer_repurchase_analysis(
                    db, scope, external_id, start, end,
                ))
            except (ValueError, HTTPException) as exc:
                return _err(_known_error(exc))
            except Exception as exc:  # noqa: BLE001
                return _unexpected(exc, "复购分析查询失败，请稍后重试")

    @mcp.tool(name="get_customer_actions", annotations={"readOnlyHint": True})
    async def get_customer_actions(params: CustomerInput, ctx: Context) -> str:
        with _session() as db:
            try:
                user = _require_agent_identity(ctx, db, tool_name="get_customer_actions")
            except MCPAuthError as exc:
                return _err(str(exc))
            if not _has_perm(user, "customer_radar:read", "customer_radar:write", "customer_radar:manage"):
                return _err("权限不足：需要客户经营雷达查看权限")
            customer = _customer_for_user(
                db,
                params.customer_id,
                user,
                minimum_classification="internal_business",
                minimum_visibility="customer_team",
            )
            if customer is None:
                return _err("客户画像不存在或不在当前账号数据范围内")
            rows = db.query(CustomerAction).filter(
                CustomerAction.customer_id == customer.id,
                CustomerAction.owner_user_id == int(user["sub"]),
            ).order_by(CustomerAction.action_date.desc(), CustomerAction.id.desc()).limit(30).all()
            return _ok([{
                "action_id": row.id,
                "date": row.action_date,
                "group": row.thread_group,
                "reason": row.reason,
                "next_action": row.next_action,
                "status": row.status,
                "source_type": row.source_type,
                "evidence_status": row.evidence_status,
            } for row in rows])

    @mcp.tool(name="get_order_intelligence_snapshot", annotations={"readOnlyHint": True})
    async def get_order_intelligence_snapshot(params: SnapshotInput, ctx: Context) -> str:
        with _session() as db:
            try:
                user = _require_agent_identity(ctx, db, tool_name="get_order_intelligence_snapshot")
            except MCPAuthError as exc:
                return _err(str(exc))
            if not _has_perm(user, "order_intelligence:read", "order_intelligence:read_all"):
                return _err("权限不足：需要订单经营分析查看权限")
            try:
                start, end = _window(params.date_from, params.date_to)
                scope = order_service.resolve_scope(db, user)
                result = order_service.get_overview(db, scope, start, end)
                return _ok({key: result[key] for key in (
                    "window", "scope", "metrics", "forecast", "customer_risk", "data_quality", "definitions"
                )})
            except (ValueError, HTTPException) as exc:
                return _err(_known_error(exc))
            except Exception as exc:  # noqa: BLE001
                return _unexpected(exc, "订单经营快照查询失败，请稍后重试")

    @mcp.tool(name="get_search_job_context", annotations={"readOnlyHint": True})
    async def get_search_job_context(params: SearchJobInput, ctx: Context) -> str:
        with _session() as db:
            try:
                user = _require_agent_identity(ctx, db, tool_name="get_search_job_context")
            except MCPAuthError as exc:
                return _err(str(exc))
            if not _has_perm(user, "sales_automation:read", "sales_automation:invoke"):
                return _err("权限不足：需要智能获客查看权限")
            scope = user.get("_agent_run") or {}
            run = db.get(AgentRun, scope.get("run_id")) if scope else None
            if run is not None and (
                run.business_ref_type != "search_job" or str(params.job_id) != str(run.business_ref_id)
            ):
                return _err("只能读取当前 Agent Run 绑定的搜索任务")
            try:
                row = sales_service.get_search_job(db, params.job_id)
            except ValueError as exc:
                return _err(str(exc))
            except Exception as exc:  # noqa: BLE001
                return _unexpected(exc, "搜索任务上下文查询失败，请稍后重试")
            return _ok({
                "job": {
                    "id": row.id, "name": row.name, "status": row.status,
                    "target_count": row.target_count,
                    "criteria_json": row.criteria_json or {},
                },
                "profile": row.profile_snapshot or {},
                "output_contract": {
                    "identifier": "customer_id",
                    "source_record_first": True,
                    "company_name_nullable": True,
                },
            })
