"""Persistent scheduler results and authenticated cross-server runtime heartbeats."""

import asyncio
import hashlib
import hmac
import json
import logging
import socket
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.operations.db_models import JobRun, RuntimeHeartbeat, RuntimeInstance
from app.operations.schemas import RuntimeHeartbeatAck, RuntimeHeartbeatPayload

logger = logging.getLogger("commission")
_heartbeat_rate_lock = threading.Lock()
_heartbeat_rate_windows: dict[tuple[str, str], deque[float]] = {}
_KNOWN_RUNTIME_NAMES = {
    "shopify-sync": "Shopify 定时同步",
    "openclaw-sales-agent": "OpenClaw 销售 Agent",
    "social-customer-mcp": "社媒客户查询 MCP",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _execution_key(job_id: str, planned_at: datetime, instance_id: str | None = None) -> str:
    raw = f"{instance_id or socket.gethostname()}|{job_id}|{_utc_naive(planned_at).isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _persist_job_event(event, triggered_by: str | None, job_id: str) -> None:
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED, EVENT_JOB_SUBMITTED

    now = _utc_now()
    if event.code in (EVENT_JOB_SUBMITTED, EVENT_JOB_MAX_INSTANCES):
        planned_times = list(getattr(event, "scheduled_run_times", []) or [now])
    else:
        planned_times = [getattr(event, "scheduled_run_time", None) or now]

    with SessionLocal() as db:
        for raw_planned_at in planned_times:
            planned_at = _utc_naive(raw_planned_at)
            key = _execution_key(job_id, planned_at)
            row = db.query(JobRun).filter(JobRun.execution_key == key).one_or_none()
            if row is None:
                row = JobRun(
                    execution_key=key,
                    instance_id=socket.gethostname()[:255],
                    job_id=job_id[:100],
                    planned_at=planned_at,
                    status="running",
                    triggered_by=(triggered_by or "scheduler")[:80],
                )
                db.add(row)

            if event.code == EVENT_JOB_SUBMITTED:
                if row.status not in {"success", "failed", "missed", "skipped"}:
                    row.status = "running"
                    row.started_at = row.started_at or now
                if triggered_by:
                    row.triggered_by = triggered_by[:80]
            else:
                row.finished_at = now
                row.started_at = row.started_at or now
                row.duration_ms = max(0, int((now - row.started_at).total_seconds() * 1000))
                if event.code == EVENT_JOB_EXECUTED:
                    row.status = "success"
                    row.error_digest = None
                elif event.code == EVENT_JOB_ERROR:
                    error = getattr(event, "exception", None)
                    row.status = "failed"
                    row.error_digest = f"任务执行失败（{type(error).__name__}）" if error else "任务执行失败"
                elif event.code == EVENT_JOB_MISSED:
                    row.status = "missed"
                    row.error_digest = "任务错过计划执行时间"
                else:
                    row.status = "skipped"
                    row.error_digest = "达到任务最大并发数，未提交执行"
        db.commit()


def record_job_event(event, triggered_by: str | None = None) -> None:
    """Upsert APScheduler event facts without persisting exception text or traceback."""
    job_id = getattr(event, "job_id", None)
    if not job_id:
        return
    # Completion can race the submission callback. The unique execution key is
    # authoritative; retry once after a duplicate insert so neither fact is lost.
    for attempt in range(2):
        try:
            _persist_job_event(event, triggered_by, job_id)
            return
        except IntegrityError:
            if attempt == 0:
                continue
            exc_name = "IntegrityError"
        except Exception as exc:
            exc_name = type(exc).__name__
            break
    logger.error("job run persistence failed job=%s (%s)", job_id, exc_name)
    print(f"job run persistence failed job={job_id} ({exc_name})", flush=True)


def list_job_runs(*, job_id: str | None, status: str | None, limit: int) -> list[JobRun]:
    with SessionLocal() as db:
        query = db.query(JobRun)
        if job_id:
            query = query.filter(JobRun.job_id == job_id)
        if status:
            query = query.filter(JobRun.status == status)
        rows = query.order_by(desc(JobRun.planned_at), desc(JobRun.id)).limit(limit).all()
        db.expunge_all()
        return rows


def _heartbeat_claim(service_id: str, instance_id: str) -> dict | None:
    raw = str(getattr(get_settings(), "OPERATIONS_HEARTBEAT_TOKEN_HASHES_JSON", "") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    service_claims = parsed.get(service_id)
    if not isinstance(service_claims, dict):
        return None
    value = service_claims.get(instance_id)
    claim = value if isinstance(value, dict) else {"token_hashes": value}
    raw_hashes = claim.get("token_hashes")
    candidates = raw_hashes if isinstance(raw_hashes, list) else [raw_hashes]
    token_hashes = [
        str(item).lower()
        for item in candidates
        if isinstance(item, str) and len(item) == 64
    ]
    if not token_hashes:
        return None
    return {**claim, "token_hashes": token_hashes}


def verify_runtime_heartbeat_token(service_id: str, instance_id: str, token: str) -> bool:
    if len(token) < 24:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matches = False
    claim = _heartbeat_claim(service_id, instance_id)
    for expected in claim["token_hashes"] if claim else []:
        matches = hmac.compare_digest(digest, expected) or matches
    return matches


def allow_runtime_heartbeat(service_id: str, instance_id: str) -> bool:
    """Per-process abuse guard; the reverse proxy remains the distributed rate limiter."""
    limit = max(1, min(120, int(getattr(
        get_settings(), "OPERATIONS_HEARTBEAT_RATE_LIMIT_PER_MINUTE", 12,
    ))))
    now = time.monotonic()
    key = (service_id, instance_id)
    with _heartbeat_rate_lock:
        window = _heartbeat_rate_windows.setdefault(key, deque())
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        if len(_heartbeat_rate_windows) > 1000:
            for stale_key in list(_heartbeat_rate_windows):
                values = _heartbeat_rate_windows[stale_key]
                if not values or now - values[-1] >= 60:
                    _heartbeat_rate_windows.pop(stale_key, None)
        return True


def ingest_runtime_heartbeat(payload: RuntimeHeartbeatPayload) -> RuntimeHeartbeatAck:
    now = _utc_now()
    started_at = _utc_naive(payload.started_at)
    last_activity_at = _utc_naive(payload.last_activity_at) if payload.last_activity_at else None
    if started_at > now + timedelta(minutes=5):
        raise ValueError("started_at 不能晚于当前时间")
    if last_activity_at and last_activity_at > now + timedelta(minutes=5):
        raise ValueError("last_activity_at 不能晚于当前时间")

    claim = _heartbeat_claim(payload.service_id, payload.instance_id)
    if claim is None:
        raise ValueError("运行实例未在服务端登记")
    claimed_capabilities = claim.get("capabilities")
    claimed_dependencies = claim.get("dependencies")
    capabilities = (
        [str(value)[:100] for value in claimed_capabilities[:50]]
        if isinstance(claimed_capabilities, list) else []
    )
    dependencies = (
        [str(value)[:100] for value in claimed_dependencies[:50]]
        if isinstance(claimed_dependencies, list) else []
    )

    with SessionLocal() as db:
        row = db.get(RuntimeInstance, (payload.service_id, payload.instance_id))
        previous_heartbeat_at = row.last_heartbeat_at if row is not None else None
        if row is None:
            max_instances = max(
                1,
                min(
                    100,
                    int(getattr(get_settings(), "OPERATIONS_HEARTBEAT_MAX_INSTANCES_PER_SERVICE", 20)),
                ),
            )
            instance_count = db.query(RuntimeInstance).filter(
                RuntimeInstance.service_id == payload.service_id,
                RuntimeInstance.retired_at.is_(None),
            ).count()
            if instance_count >= max_instances:
                raise ValueError("该服务登记的运行实例已达到上限")
            row = RuntimeInstance(service_id=payload.service_id, instance_id=payload.instance_id)
            db.add(row)
        row.service_name = str(
            claim.get("service_name") or _KNOWN_RUNTIME_NAMES.get(payload.service_id) or payload.service_id
        )[:120]
        row.environment = str(claim.get("environment") or "已登记运行实例")[:80]
        row.version = payload.version
        row.status = payload.status
        row.started_at = started_at
        row.last_activity_at = last_activity_at
        row.last_heartbeat_at = now
        row.capabilities = capabilities
        row.dependencies = dependencies
        row.consecutive_misses = 0
        row.alerted_at = None
        row.retired_at = None
        interval = max(15, int(getattr(get_settings(), "OPERATIONS_HEARTBEAT_INTERVAL_SECONDS", 60)))
        # Keep the latest state on every accepted request, but sample history to
        # prevent one compromised service token from creating an unbounded row flood.
        if previous_heartbeat_at is None or (now - previous_heartbeat_at).total_seconds() >= max(15, interval // 2):
            db.add(RuntimeHeartbeat(
                service_id=payload.service_id,
                instance_id=payload.instance_id,
                reported_status=payload.status,
                last_activity_at=last_activity_at,
                received_at=now,
            ))
        db.commit()

    return RuntimeHeartbeatAck(
        service_id=payload.service_id,
        instance_id=payload.instance_id,
        accepted_at=now.replace(tzinfo=timezone.utc).isoformat(),
        next_heartbeat_within_seconds=interval,
    )


def list_runtime_instances() -> list[RuntimeInstance]:
    with SessionLocal() as db:
        rows = db.query(RuntimeInstance).order_by(
            RuntimeInstance.service_name, RuntimeInstance.instance_id,
        ).filter(RuntimeInstance.retired_at.is_(None)).all()
        db.expunge_all()
        return rows


async def monitor_runtime_heartbeats() -> None:
    """Mark three-cycle silence degraded, alert once, and prune old heartbeat samples."""
    settings = get_settings()
    interval = max(15, int(settings.OPERATIONS_HEARTBEAT_INTERVAL_SECONDS))
    miss_limit = max(1, int(settings.OPERATIONS_HEARTBEAT_MISSED_THRESHOLD))
    now = _utc_now()
    alerts: list[tuple[str, str, str, int, datetime]] = []
    try:
        with SessionLocal() as db:
            stale_cutoff = now - timedelta(seconds=interval * miss_limit)
            retire_cutoff = now - timedelta(hours=max(
                1, int(getattr(settings, "OPERATIONS_HEARTBEAT_INSTANCE_RETIRE_HOURS", 24)),
            ))
            stale_rows = db.query(RuntimeInstance).filter(
                RuntimeInstance.retired_at.is_(None),
                RuntimeInstance.last_heartbeat_at <= stale_cutoff,
            ).with_for_update().all()
            for row in stale_rows:
                age_seconds = max(0, int((now - row.last_heartbeat_at).total_seconds()))
                misses = age_seconds // interval
                row.consecutive_misses = misses
                if row.last_heartbeat_at <= retire_cutoff:
                    row.retired_at = now
                    continue
                row.status = "degraded"
                if row.alerted_at is None:
                    row.alerted_at = now
                    alerts.append((
                        row.service_id, row.service_name, row.instance_id, age_seconds,
                        row.last_heartbeat_at,
                    ))
            cutoff = now - timedelta(days=max(1, int(settings.OPERATIONS_HEARTBEAT_RETENTION_DAYS)))
            db.query(RuntimeHeartbeat).filter(RuntimeHeartbeat.received_at < cutoff).delete(
                synchronize_session=False,
            )
            db.query(RuntimeInstance).filter(
                RuntimeInstance.retired_at.is_not(None),
                RuntimeInstance.last_heartbeat_at < cutoff,
            ).delete(synchronize_session=False)
            db.commit()
    except Exception as exc:
        logger.error("runtime heartbeat monitor failed (%s)", type(exc).__name__)
        print(f"runtime heartbeat monitor failed ({type(exc).__name__})", flush=True)
        return

    if not alerts:
        return
    # Recheck after releasing row locks. A heartbeat committed in the meantime
    # clears alerted_at and must suppress the stale transition notification.
    confirmed_alerts = []
    with SessionLocal() as db:
        for service_id, name, instance_id, age, observed_at in alerts:
            row = db.get(RuntimeInstance, (service_id, instance_id))
            if row and row.alerted_at is not None and row.last_heartbeat_at == observed_at:
                confirmed_alerts.append((service_id, name, instance_id, age, observed_at))
    if not confirmed_alerts:
        return
    try:
        from app.dingtalk.webhook import get_webhook_sender

        lines = ["### 云端运行实例失联", ""]
        lines.extend(
            f"- {name} / {instance_id}：{age}s 未收到心跳"
            for _service_id, name, instance_id, age, _observed_at in confirmed_alerts
        )
        alert_timeout = max(1.0, float(getattr(settings, "OPERATIONS_ALERT_TIMEOUT_SECONDS", 10.0)))
        await asyncio.wait_for(
            get_webhook_sender().send_markdown("云端运行实例告警", "\n".join(lines)),
            timeout=alert_timeout,
        )
    except Exception as exc:
        logger.error("runtime heartbeat alert failed (%s)", type(exc).__name__)
        print(f"runtime heartbeat alert failed ({type(exc).__name__})", flush=True)
        try:
            with SessionLocal() as db:
                alert_keys = {
                    (service_id, instance_id, observed_at)
                    for service_id, _name, instance_id, _age, observed_at in confirmed_alerts
                }
                for row in db.query(RuntimeInstance).all():
                    if (row.service_id, row.instance_id, row.last_heartbeat_at) in alert_keys:
                        row.alerted_at = None
                db.commit()
        except Exception as reset_exc:
            logger.error("runtime heartbeat alert reset failed (%s)", type(reset_exc).__name__)
            print(f"runtime heartbeat alert reset failed ({type(reset_exc).__name__})", flush=True)


def clear_old_job_runs() -> None:
    """Bound scheduler history growth without touching operation audit rows."""
    days = max(7, int(getattr(get_settings(), "OPERATIONS_JOB_RUN_RETENTION_DAYS", 90)))
    try:
        with SessionLocal() as db:
            db.query(JobRun).filter(JobRun.planned_at < _utc_now() - timedelta(days=days)).delete(
                synchronize_session=False,
            )
            db.commit()
    except Exception as exc:
        logger.error("job run cleanup failed (%s)", type(exc).__name__)
        print(f"job run cleanup failed ({type(exc).__name__})", flush=True)


def recover_stale_job_runs() -> None:
    """Close rows left running when this scheduler instance previously stopped."""
    now = _utc_now()
    try:
        with SessionLocal() as db:
            rows = db.query(JobRun).filter(
                JobRun.instance_id == socket.gethostname(),
                JobRun.status == "running",
            ).all()
            for row in rows:
                row.status = "failed"
                row.finished_at = now
                row.duration_ms = (
                    max(0, int((now - row.started_at).total_seconds() * 1000))
                    if row.started_at else None
                )
                row.error_digest = "应用重启前任务未正常结束"
            db.commit()
    except Exception as exc:
        logger.error("stale job run recovery failed (%s)", type(exc).__name__)
        print(f"stale job run recovery failed ({type(exc).__name__})", flush=True)
