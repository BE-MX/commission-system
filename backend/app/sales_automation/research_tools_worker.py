"""Beijing dispatcher. Persist the spend boundary before sending a paid POST."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy.orm import sessionmaker

from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.customer.models import CustomerResearchTask
from app.customer.ownership_service import get_effective_owner
from app.sales_automation import research_tools_providers as providers
from app.sales_automation.research_tools_models import ResearchToolCall as Call
from app.sales_automation.research_tools_service import company_identified, monid_budget_still_valid

logger = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=5)
POLL_FOR = timedelta(hours=1)


def _warn(message, exc):
    # HTTP errors can contain proxy credentials or customer data; log only the class.
    line = f"Private research worker {message}: {type(exc).__name__}"
    logger.warning(line)
    print(line, flush=True)


def _finish(row, status, *, raw=None, result=None, charge=None, error=None):
    row.status = status
    row.charged_microusd = charge
    row.finished_at = beijing_now()
    row.error_code = error
    if raw is not None or result is not None:
        row.response_json = {"raw": raw, "result": result}


def _task_live(task, row):
    return (task is not None and task.agent_run_id == row.run_id and task.lease_generation == row.lease_generation
            and task.task_status == "running" and task.lease_expires_at is not None
            and task.lease_expires_at > beijing_now())


def _set_state(session_factory, task_id, row_id, expected, callback, *, monid_budget=None):
    with session_factory() as db:
        # Parent before child everywhere, including HTTP submit/bind.
        task = db.query(CustomerResearchTask).filter_by(id=task_id).with_for_update().one_or_none()
        row = db.query(Call).filter_by(id=row_id).with_for_update().one_or_none()
        if row is None or row.status != expected:
            return False
        if expected in {"queued", "preparing"} and task is not None:
            if get_effective_owner(db, "research_task", task.id) != task.customer_id:
                task = None
            elif monid_budget is not None:
                reason = None
                if company_identified(db, task, row.run_id):
                    reason = "company_identified"
                elif not monid_budget_still_valid(db, task_id, monid_budget):
                    reason = "budget_unavailable"
                if reason:
                    _finish(row, "cancelled", charge=0, error=reason)
                    db.commit()
                    return False
        changed = callback(task, row)
        db.commit()
        return changed


def _claim(session_factory):
    with session_factory() as db:
        row = db.query(Call.task_id, Call.id).filter_by(status="queued").order_by(Call.id).first()
    if row is None:
        return None
    task_id, row_id = row

    def claim(task, record):
        if not _task_live(task, record):
            _finish(record, "cancelled", charge=0, error="lease_ended")
            return None
        record.status = "preparing"
        record.started_at = beijing_now()
        return task_id, row_id, record.tool, record.operation, record.target, record.reserved_microusd

    return _set_state(session_factory, task_id, row_id, "queued", claim)


def _record_finish(session_factory, task_id, row_id, expected, **kwargs):
    return _set_state(session_factory, task_id, row_id, expected, lambda _, row: _finish(row, **kwargs))


def _scan(session_factory, task_id, row_id, settings, target):
    try:
        raw = providers.scan(settings, target)
        result = providers.scan_result(raw)
    except Exception as exc:
        _warn("scan unavailable", exc)
        _record_finish(session_factory, task_id, row_id, "preparing", status="unavailable", charge=0,
                       error="scan_unavailable", result={"outcome": "unavailable", "candidates": []})
        return
    unavailable = result["outcome"] == "unavailable"
    _record_finish(session_factory, task_id, row_id, "preparing", status="unavailable" if unavailable else "succeeded",
                   raw=raw, result=result, charge=0, error="scan_unavailable" if unavailable else None)


def _handle_monid(session_factory, task_id, row_id, expected, operation, target, reservation, raw):
    status = raw.get("status")
    run_id = raw.get("runId")
    op = providers.OPERATIONS[operation]
    if raw.get("provider") != op.provider or raw.get("endpoint") != op.endpoint:
        return False
    if status in {"RUNNING", "PENDING", "READY"}:
        if expected == "submitting" and isinstance(run_id, str) and providers.RUN_ID.fullmatch(run_id):
            def save_pointer(_, row):
                row.provider_run_id = run_id
                row.status = "polling"
            _set_state(session_factory, task_id, row_id, expected, save_pointer)
            return True
        return expected == "polling"
    if status not in {"COMPLETED", "FAILED", "BLOCKED"}:
        return False
    charge = providers.reported_charge(raw)
    try:
        result = providers.monid_result(operation, target, raw)
    except (AttributeError, TypeError, ValueError) as exc:
        _warn("invalid provider output", exc)
        result = {"outcome": "no_data", "candidates": []}
    provider_response = raw.get("providerResponse")
    code = provider_response.get("httpStatus") if isinstance(provider_response, dict) else None
    error = None
    if status != "COMPLETED":
        error = "provider_failed"
    elif code == 429:
        error = "provider_rate_limited"
    elif code not in (200, 404):
        error = "provider_response_error"
    if charge is None:
        error = "charge_unconfirmed"
    elif charge > reservation:
        error = "charge_over_cap"
    final_status = "uncertain" if charge is None or charge > reservation else ("failed" if error else "succeeded")
    _record_finish(session_factory, task_id, row_id, expected, status=final_status,
                   raw=raw, result=result if not error else None, charge=charge, error=error)
    return True


def _start_monid(session_factory, task_id, row_id, settings, operation, target, reservation):
    with providers.monid_client(settings) as client:
        try:
            payload = providers.monid_prepare(client, operation, target, reservation)
        except Exception as exc:
            _warn("price inspection failed", exc)
            payload = None
        if payload is None:
            _record_finish(session_factory, task_id, row_id, "preparing", status="unavailable", charge=0,
                           error="price_not_verified")
            return

        def arm(task, row):
            if not _task_live(task, row):
                _finish(row, "cancelled", charge=0, error="lease_ended")
                return False
            row.status = "submitting"
            return True

        if not _set_state(session_factory, task_id, row_id, "preparing", arm,
                          monid_budget=settings.PRIVATE_RESEARCH_MONID_BUDGET_MICROUSD):
            return
        try:
            raw = providers.request_json(client, "POST", f"{providers.MONID_BASE}/run", json=payload)
            if _handle_monid(session_factory, task_id, row_id, "submitting", operation, target, reservation, raw):
                return
        except Exception as exc:
            _warn("paid request outcome unknown", exc)
        # A lost response is not permission to replay the POST or release the reservation.
        _record_finish(session_factory, task_id, row_id, "submitting", status="uncertain",
                       error="dispatch_outcome_unknown")


def _poll_and_recover(settings, session_factory):
    now = beijing_now()
    with session_factory() as db:
        stale = db.query(Call.task_id, Call.id, Call.status).filter(
            Call.status.in_(["preparing", "submitting"]), Call.started_at <= now - STALE_AFTER,
        ).limit(25).all()
        polling = db.query(Call.task_id, Call.id, Call.operation, Call.target, Call.reserved_microusd,
                           Call.provider_run_id, Call.started_at).filter_by(status="polling").order_by(Call.id).limit(5).all()
    for task_id, row_id, status in stale:
        paid = status == "submitting"
        _record_finish(session_factory, task_id, row_id, status, status="uncertain" if paid else "unavailable",
                       error="dispatch_outcome_unknown" if paid else "worker_interrupted", charge=None if paid else 0)
    for task_id, row_id, operation, target, reserve, run_id, started_at in polling:
        if started_at <= now - POLL_FOR or not isinstance(run_id, str) or not providers.RUN_ID.fullmatch(run_id):
            _record_finish(session_factory, task_id, row_id, "polling", status="uncertain", error="provider_poll_expired")
            continue
        if not providers.is_enabled(settings, "monid"):
            continue
        try:
            with providers.monid_client(settings) as client:
                raw = providers.request_json(client, "GET", f"{providers.MONID_BASE}/runs/{run_id}")
            if raw.get("runId") == run_id:
                _handle_monid(session_factory, task_id, row_id, "polling", operation, target, reserve, raw)
        except Exception as exc:
            _warn("provider polling temporarily unavailable", exc)


def process_once(settings, session_factory: sessionmaker = SessionLocal):
    _poll_and_recover(settings, session_factory)
    claim = _claim(session_factory)
    if not claim:
        return
    task_id, row_id, tool, operation, target, reservation = claim
    if not providers.is_enabled(settings, tool):
        _record_finish(session_factory, task_id, row_id, "preparing", status="unavailable",
                       charge=0, error="provider_disabled")
    elif tool == "username_scan":
        _scan(session_factory, task_id, row_id, settings, target)
    else:
        _start_monid(session_factory, task_id, row_id, settings, operation, target, reservation)


@asynccontextmanager
async def run_worker(settings):
    stop = asyncio.Event()

    async def loop():
        while not stop.is_set():
            try:
                await asyncio.to_thread(process_once, settings)
            except Exception as exc:
                _warn("iteration failed", exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
            except TimeoutError:
                continue

    worker = asyncio.create_task(loop(), name="private-research-tool-dispatch")
    try:
        yield
    finally:
        stop.set()
        await worker
