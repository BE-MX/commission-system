"""Read-only runtime inventory plus bounded controls for in-process jobs."""

import asyncio
import ipaddress
import json
import logging
import platform
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.operations.models import JOB_METADATA
from app.operations.schemas import (
    JobActionResult,
    OperationsOverview,
    RuntimeServiceView,
    SchedulerJobView,
    SchedulerView,
)
from app.core.database import SessionLocal
from app.operations.db_models import OperationAudit, SchedulerJobPolicy
from app.schedulers.registry import get_active_scheduler, get_job_runtime_snapshot, submit_job_now

logger = logging.getLogger("commission")
_overview_cache: tuple[float, OperationsOverview] | None = None
_overview_task: asyncio.Task | None = None
_VALID_ACTIONS = {"run", "pause", "resume"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_endpoint(url: str) -> str | None:
    """Expose only the origin; paths may also contain credentials."""
    if not url:
        return None
    try:
        parsed = urlsplit(url)
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _scheduler_view() -> SchedulerView:
    settings = get_settings()
    scheduler = get_active_scheduler()
    runtime = get_job_runtime_snapshot()
    jobs: list[SchedulerJobView] = []
    if scheduler:
        for job in scheduler.get_jobs():
            metadata = JOB_METADATA.get(job.id)
            state = runtime.get(job.id, {})
            next_run = getattr(job, "next_run_time", None)
            jobs.append(SchedulerJobView(
                id=job.id,
                name=metadata.name if metadata else job.name or job.id,
                domain=metadata.domain if metadata else "未归类",
                owner=metadata.owner if metadata else "待指定",
                trigger=str(job.trigger),
                registered=True,
                next_run_at=next_run.isoformat() if next_run else None,
                paused=next_run is None,
                running_instances=int(state.get("running_instances") or 0),
                last_started_at=state.get("last_started_at"),
                last_finished_at=state.get("last_finished_at"),
                last_status=state.get("last_status") or "never",
                last_error=state.get("last_error"),
            ))
    registered_ids = {item.id for item in jobs}
    for job_id, metadata in JOB_METADATA.items():
        if job_id in registered_ids:
            continue
        jobs.append(SchedulerJobView(
            id=job_id,
            name=metadata.name,
            domain=metadata.domain,
            owner=metadata.owner,
            trigger="未在当前实例注册",
            registered=False,
            paused=True,
            last_status="disabled",
        ))
    jobs.sort(key=lambda item: (item.domain, item.name))
    return SchedulerView(
        enabled=bool(settings.SCHEDULER_ENABLED),
        running=bool(scheduler and scheduler.running),
        timezone=settings.SCHEDULER_TIMEZONE,
        expected_job_count=len(JOB_METADATA),
        registered_job_count=len(registered_ids),
        jobs=jobs,
    )


async def _probe_service(item: dict, timeout_seconds: float) -> RuntimeServiceView:
    health_url = str(item.get("health_url") or "").strip()
    safe_endpoint = _safe_endpoint(health_url)
    management = str(item.get("management") or "observed")
    if management not in {"managed", "observed", "unmanaged"}:
        management = "unmanaged"
    base = dict(
        id=str(item["id"]),
        name=str(item["name"]),
        category=str(item.get("category") or "外部服务"),
        environment=str(item.get("environment") or "生产"),
        owner=str(item.get("owner") or "待指定"),
        management=management,
        endpoint=safe_endpoint,
    )
    if not health_url:
        management = base["management"]
        return RuntimeServiceView(
            **base,
            status="unmanaged" if management == "unmanaged" else "unconfigured",
            detail=str(item.get("detail") or "尚未配置健康检查地址"),
        )
    if not safe_endpoint:
        return RuntimeServiceView(**base, status="unconfigured", detail="健康检查地址格式无效")
    parsed_health = urlsplit(health_url)
    health_host = (parsed_health.hostname or "").lower()
    allowed_hosts = {
        host.strip().lower()
        for host in str(getattr(get_settings(), "OPERATIONS_ALLOWED_HEALTH_HOSTS", "")).split(",")
        if host.strip()
    }
    if health_host not in allowed_hosts:
        return RuntimeServiceView(**base, status="unconfigured", detail="健康检查主机不在部署 allowlist")
    try:
        address = ipaddress.ip_address(health_host)
        blocked_address = address.is_link_local or address.is_multicast or address.is_unspecified
    except ValueError:
        blocked_address = False
    if blocked_address:
        return RuntimeServiceView(**base, status="unconfigured", detail="健康检查地址属于受限网络范围")

    raw_headers = item.get("headers")
    headers = raw_headers if isinstance(raw_headers, dict) else {}
    normalized_headers = {
        str(name): str(value)
        for name, value in headers.items()
        if str(name).lower() in {"authorization", "x-api-key"}
    }

    started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            response = await client.get(
                health_url,
                headers={"User-Agent": "ark-operations-probe/1.0", **normalized_headers},
            )
        latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        healthy = 200 <= response.status_code < 300
        return RuntimeServiceView(
            **base,
            status="healthy" if healthy else "degraded",
            detail="健康检查通过" if healthy else f"健康检查返回 HTTP {response.status_code}",
            checked_at=_now_iso(),
            latency_ms=latency_ms,
        )
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("operations health probe failed for %s (%s)", item.get("id"), error_type)
        print(f"operations health probe failed for {item.get('id')} ({error_type})", flush=True)
        return RuntimeServiceView(
            **base,
            status="degraded",
            detail=f"健康检查失败：{error_type}",
            checked_at=_now_iso(),
        )


def _service_catalog() -> list[dict]:
    settings = get_settings()
    catalog = [
        {
            "id": "ark-api",
            "name": "方舟主应用 API",
            "category": "平台服务",
            "environment": settings.APP_ENV,
            "owner": "平台研发",
            "management": "managed",
            "detail": "随当前应用进程运行",
        },
        {
            "id": "ark-mcp",
            "name": "方舟 MCP 网关",
            "category": "MCP 服务",
            "environment": settings.APP_ENV,
            "owner": "平台研发",
            "management": "managed",
            "detail": "随当前应用进程挂载 /mcp",
        },
        {
            "id": "social-customer-mcp",
            "name": "社媒客户查询 MCP",
            "category": "MCP 服务",
            "environment": "leshine.work 云端",
            "owner": "销售运营",
            "management": "observed",
            "health_url": settings.OPERATIONS_SOCIAL_MCP_HEALTH_URL,
        },
        {
            "id": "whatsapp-connector",
            "name": "WhatsApp Connector",
            "category": "同步服务",
            "environment": "办公室主实例",
            "owner": "销售运营",
            "management": "managed",
            "health_url": f"{settings.WHATSAPP_CONNECTOR_BASE_URL.rstrip('/')}/health" if settings.WHATSAPP_CONNECTOR_BASE_URL else "",
            "headers": {"Authorization": f"Bearer {settings.WHATSAPP_CONNECTOR_API_KEY}"} if settings.WHATSAPP_CONNECTOR_API_KEY else {},
        },
        {
            "id": "okki",
            "name": "OKKI 开放平台",
            "category": "外部集成",
            "environment": "SaaS",
            "owner": "订单运营",
            "management": "observed",
            "detail": "API 凭证已配置" if settings.OKKI_CLIENT_ID and settings.OKKI_CLIENT_SECRET else "API 凭证未完整配置",
            "configuration_only": True,
            "configured": bool(settings.OKKI_CLIENT_ID and settings.OKKI_CLIENT_SECRET),
        },
        {
            "id": "shopify-sync",
            "name": "Shopify 定时同步",
            "category": "同步服务",
            "environment": "leshine.work 云端",
            "owner": "电商运营",
            "management": "unmanaged" if not settings.OPERATIONS_SHOPIFY_HEALTH_URL else "observed",
            "health_url": settings.OPERATIONS_SHOPIFY_HEALTH_URL,
            "detail": "仓库内没有运行定义，需在云端同步任务增加健康上报" if not settings.OPERATIONS_SHOPIFY_HEALTH_URL else "",
        },
        {
            "id": "openclaw-sales-agent",
            "name": "OpenClaw 销售 Agent",
            "category": "Agent 服务",
            "environment": "外部执行器",
            "owner": "销售运营",
            "management": "unmanaged" if not settings.OPERATIONS_OPENCLAW_HEALTH_URL else "observed",
            "health_url": settings.OPERATIONS_OPENCLAW_HEALTH_URL,
            "detail": "当前为 stdio MCP 进程，需增加独立心跳或 sidecar" if not settings.OPERATIONS_OPENCLAW_HEALTH_URL else "",
        },
    ]
    if settings.OPERATIONS_EXTERNAL_SERVICES_JSON.strip():
        try:
            custom = json.loads(settings.OPERATIONS_EXTERNAL_SERVICES_JSON)
            if not isinstance(custom, list):
                raise ValueError("must be a list")
            for item in custom[:20]:
                if isinstance(item, dict) and item.get("id") and item.get("name"):
                    catalog.append(item)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("invalid OPERATIONS_EXTERNAL_SERVICES_JSON: %s", exc)
            print(f"invalid OPERATIONS_EXTERNAL_SERVICES_JSON: {exc}", flush=True)
    return catalog


async def _build_overview() -> OperationsOverview:
    settings = get_settings()
    services: list[RuntimeServiceView] = []
    probe_items: list[dict] = []
    for item in _service_catalog():
        if item.get("id") in {"ark-api", "ark-mcp"}:
            is_api = item["id"] == "ark-api"
            services.append(RuntimeServiceView(
                id=item["id"], name=item["name"], category=item["category"],
                environment=item["environment"], owner=item["owner"], management="managed",
                status="healthy" if is_api else "unknown",
                detail=item["detail"] if is_api else "随进程挂载，尚未执行协议级会话探测",
                checked_at=_now_iso(),
            ))
        elif item.get("configuration_only"):
            services.append(RuntimeServiceView(
                id=item["id"], name=item["name"], category=item["category"],
                environment=item["environment"], owner=item["owner"], management="observed",
                status="unknown" if item.get("configured") else "unconfigured",
                detail=item["detail"], checked_at=_now_iso(),
            ))
        else:
            probe_items.append(item)
    if probe_items:
        services.extend(await asyncio.gather(*(
            _probe_service(item, settings.OPERATIONS_PROBE_TIMEOUT_SECONDS) for item in probe_items
        )))
    services.sort(key=lambda item: (item.category, item.name))
    scheduler = _scheduler_view()
    summary = {
        "healthy_services": sum(item.status == "healthy" for item in services),
        "attention_services": sum(item.status != "healthy" for item in services),
        "registered_jobs": scheduler.registered_job_count,
        "failed_jobs": sum(item.last_status in {"failed", "missed", "skipped"} for item in scheduler.jobs),
    }
    return OperationsOverview(
        instance={
            "hostname": socket.gethostname(),
            "environment": settings.APP_ENV,
            "platform": platform.system(),
            "role": "scheduler-primary" if scheduler.enabled else "application-replica",
        },
        scheduler=scheduler,
        services=services,
        summary=summary,
        generated_at=_now_iso(),
    )


async def get_overview() -> OperationsOverview:
    """Share short-lived probe results across viewers to avoid outbound probe storms."""
    global _overview_cache, _overview_task
    settings = get_settings()
    now = time.monotonic()
    ttl = max(0.0, float(getattr(settings, "OPERATIONS_CACHE_TTL_SECONDS", 20.0)))
    if _overview_cache and now - _overview_cache[0] < ttl:
        return _overview_cache[1]
    if _overview_task is None:
        _overview_task = asyncio.create_task(_build_overview())
    try:
        overview = await asyncio.shield(_overview_task)
        _overview_cache = (time.monotonic(), overview)
        return overview
    finally:
        if _overview_task and _overview_task.done():
            _overview_task = None


def _create_control_audit(
    *, actor_user_id: int | None, actor_name: str, source_ip: str | None,
    job_id: str, action: str,
) -> int:
    try:
        with SessionLocal() as db:
            row = OperationAudit(
                actor_user_id=actor_user_id,
                actor_name=actor_name[:80],
                source_ip=source_ip[:45] if source_ip else None,
                instance_id=socket.gethostname()[:255],
                job_id=job_id[:100],
                action=action[:20],
                result="requested",
                detail="等待执行",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return int(row.id)
    except Exception as exc:
        logger.error("operations audit write failed (%s)", type(exc).__name__)
        print(f"operations audit write failed ({type(exc).__name__})", flush=True)
        raise ValueError("运维审计不可用，为避免无记录操作，本次请求已拒绝") from exc


def _finish_control_audit(audit_id: int, result: str, detail: str) -> None:
    try:
        with SessionLocal() as db:
            row = db.get(OperationAudit, audit_id)
            if row is None:
                raise RuntimeError("audit row missing")
            row.result = result[:20]
            row.detail = detail[:255]
            db.commit()
    except Exception as exc:
        logger.error("operations audit finalize failed (%s)", type(exc).__name__)
        print(f"operations audit finalize failed ({type(exc).__name__})", flush=True)


def _set_paused_policy(job_id: str, paused: bool, actor_user_id: int | None) -> None:
    with SessionLocal() as db:
        instance_id = socket.gethostname()[:255]
        policy = db.get(SchedulerJobPolicy, (instance_id, job_id))
        if policy is None:
            policy = SchedulerJobPolicy(instance_id=instance_id, job_id=job_id)
            db.add(policy)
        policy.paused = int(paused)
        policy.updated_by = actor_user_id
        db.commit()


def _restore_paused_policy(job_id: str, actor_user_id: int | None) -> None:
    try:
        _set_paused_policy(job_id, True, actor_user_id)
    except Exception as exc:
        logger.critical("operations pause policy rollback failed (%s)", type(exc).__name__)
        print(f"operations pause policy rollback failed ({type(exc).__name__})", flush=True)


def control_job(
    job_id: str,
    action: str,
    actor_name: str,
    *,
    actor_user_id: int | None = None,
    source_ip: str | None = None,
) -> JobActionResult:
    global _overview_cache
    scheduler = get_active_scheduler()
    if action not in _VALID_ACTIONS:
        raise ValueError("不支持的任务操作")
    audit_id = _create_control_audit(
        actor_user_id=actor_user_id, actor_name=actor_name, source_ip=source_ip,
        job_id=job_id, action=action,
    )
    try:
        if scheduler is None or not scheduler.running:
            raise ValueError("当前实例未启用调度器，不能执行任务操作")
        job = scheduler.get_job(job_id)
        if job is None or job_id not in JOB_METADATA:
            raise ValueError("任务不存在或不允许通过运行中心操作")

        if action == "run":
            if getattr(job, "next_run_time", None) is None:
                raise ValueError("任务已暂停，请先恢复后再立即执行")
            submit_job_now(scheduler, job_id)
            message = "已提交一次性立即执行，原计划不变"
        elif action == "pause":
            _set_paused_policy(job_id, True, actor_user_id)
            try:
                scheduler.pause_job(job_id)
            except Exception:
                _set_paused_policy(job_id, False, actor_user_id)
                raise
            message = "任务已暂停，重启后仍保持"
        elif action == "resume":
            _set_paused_policy(job_id, False, actor_user_id)
            try:
                scheduler.resume_job(job_id)
            except Exception:
                _restore_paused_policy(job_id, actor_user_id)
                raise
            message = "任务已恢复"
    except ValueError as exc:
        _finish_control_audit(audit_id, "rejected", str(exc))
        raise
    except Exception as exc:
        _finish_control_audit(audit_id, "failed", f"操作失败（{type(exc).__name__}）")
        raise

    _finish_control_audit(audit_id, "accepted", message)
    _overview_cache = None
    logger.warning("operations job control actor=%s action=%s job_id=%s", actor_name, action, job_id)
    print(f"operations job control actor={actor_name} action={action} job_id={job_id}", flush=True)
    return JobActionResult(job_id=job_id, action=action, message=message)
