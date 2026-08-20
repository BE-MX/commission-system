"""Read-only Ark business tools exposed only through governed identity scopes."""

from contextlib import contextmanager
from datetime import date, timedelta
import json
import logging

from fastapi import HTTPException
from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.models import AgentRun
from app.core.database import SessionLocal
from app.insight.models import CustomerAction, CustomerProfile, CustomerProfileEvent
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


def _profile_for_user(db, profile_id: int, user: dict) -> CustomerProfile | None:
    run_scope = user.get("_agent_run") or {}
    bound_profile_id = run_scope.get("customer_profile_id")
    if bound_profile_id is not None and str(bound_profile_id) != str(profile_id):
        return None
    row = db.query(CustomerProfile).filter(CustomerProfile.id == profile_id).one_or_none()
    if row is None:
        return None
    if "super_admin" in set(user.get("roles") or []) or "customer_radar:manage" in set(user.get("permissions") or []):
        return row
    return row if row.owner_user_id == int(user["sub"]) else None


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: int = Field(..., ge=1, description="方舟客户画像 ID")


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
    actual_end = end or date.today()
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
            row = _profile_for_user(db, params.profile_id, user)
            if row is None:
                return _err("客户画像不存在或不在当前账号数据范围内")
            events = db.query(CustomerProfileEvent).filter(
                CustomerProfileEvent.profile_id == row.id,
            ).order_by(CustomerProfileEvent.occurred_at.desc()).limit(30).all()
            return _ok({
                "profile_id": row.id,
                "customer_external_id": row.customer_external_id,
                "customer_name": row.customer_name,
                "customer_company": row.customer_company,
                "customer_region": row.customer_region,
                "tags": row.profile_tags or [],
                "judgement": row.profile_judgement,
                "signals": row.profile_signals_json or {},
                "priority_score": row.priority_score,
                "last_event_at": row.last_event_at,
                "events": [{
                    "event_id": item.id,
                    "source": item.event_source,
                    "type": item.event_type,
                    "title": item.event_title,
                    "summary": item.event_summary,
                    "score": item.event_score,
                    "occurred_at": item.occurred_at,
                } for item in events],
            })

    @mcp.tool(name="get_customer_order_timeline", annotations={"readOnlyHint": True})
    async def get_customer_order_timeline(params: CustomerOrderInput, ctx: Context) -> str:
        with _session() as db:
            try:
                user = _require_agent_identity(ctx, db, tool_name="get_customer_order_timeline")
            except MCPAuthError as exc:
                return _err(str(exc))
            if not _has_perm(user, "order_intelligence:read", "order_intelligence:read_all"):
                return _err("权限不足：需要订单经营分析查看权限")
            profile = _profile_for_user(db, params.profile_id, user)
            if profile is None or not profile.customer_external_id:
                return _err("客户画像不存在、越权或尚未绑定 OKKI 客户 ID")
            try:
                start, end = _window(params.date_from, params.date_to)
                scope = order_service.resolve_scope(db, user)
                return _ok(order_service.get_customer_order_timeline(
                    db, scope, profile.customer_external_id, start, end, limit=params.limit,
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
            profile = _profile_for_user(db, params.profile_id, user)
            if profile is None or not profile.customer_external_id:
                return _err("客户画像不存在、越权或尚未绑定 OKKI 客户 ID")
            try:
                start, end = _window(params.date_from, params.date_to)
                scope = order_service.resolve_scope(db, user)
                return _ok(order_service.get_customer_repurchase_analysis(
                    db, scope, profile.customer_external_id, start, end,
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
            profile = _profile_for_user(db, params.profile_id, user)
            if profile is None:
                return _err("客户画像不存在或不在当前账号数据范围内")
            rows = db.query(CustomerAction).filter(
                CustomerAction.profile_id == profile.id,
            ).order_by(CustomerAction.action_date.desc(), CustomerAction.id.desc()).limit(30).all()
            return _ok([{
                "action_id": row.id,
                "date": row.action_date,
                "group": row.thread_group,
                "reason": row.action_reason,
                "next_action": row.suggested_next_action,
                "status": row.action_status,
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
                    "target_count": row.target_count, "criteria": row.criteria or {},
                },
                "profile": row.profile_snapshot or {},
                "output_contract": {
                    "identity": "normalized company website domain",
                    "required_fields": ["name", "website", "source_url", "captured_at", "tool_call_id"],
                    "forbidden": ["invented company", "unsourced claim", "personal email guess"],
                },
            })
