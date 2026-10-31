"""Production API only queues/reports; it cannot supply a target URL or seed."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from app.auth.dependencies import require_permission
from app.auth.service import get_live_user_authorization
from app.core.database import get_db
from app.core.config import get_settings
from app.core.response import ok
from app.commerce_shadow import service
from app.commerce_shadow.models import (ShadowRun, ShadowDifference, ShadowReview, ShadowResult,
                                       ShadowObservation, ShadowOutbox)
from app.commerce_shadow.schemas import ReplayRequest, ReviewRequest, ExecutionReport
from app.commerce_shadow.diagnostics import report

def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(dependencies=[Depends(private_response)])


def _user(db, claims, action="read"):
    roles, permissions = get_live_user_authorization(db, int(claims["sub"]))
    user = {**claims, "roles": roles, "permissions": permissions}
    if "super_admin" not in roles:
        if f"commerce_shadow:{action}" not in permissions or not {"invoice:read", "receipt:read"}.intersection(permissions):
            raise HTTPException(403, "当前账号无权访问交易对比")
    return user


def _closure_access(db, row, user):
    for identity in row.invoice_ids:
        service.invoice_access(db, identity, user)
    for identity in row.payment_ids or []:
        service.payment_access(db, identity, user)
    for identity in row.local_customer_ids or []:
        service.customer_access(db, identity, user)


def _financial_access(db, observation_id, user):
    observation = db.get(ShadowObservation, observation_id)
    if observation:
        service.observation_access(db, observation, user)


def _visible(db, row, user):
    if row is None:
        return False
    try:
        _closure_access(db, row, user)
        # Coverage itself reveals which financial actions happened.
        from app.commerce_shadow.models import ShadowDataset
        from app.commerce_shadow.transport import collect_observations
        observations, _missing = collect_observations(db, row, db.get(ShadowDataset, row.dataset_id))
        for obs in observations:
            _financial_access(db, obs.id, user)
        return True
    except HTTPException as exc:
        if exc.status_code == 404:
            return False
        raise


@router.get("/status")
def status(db=Depends(get_db), claims=Depends(require_permission("commerce_shadow:read"))):
    user = _user(db, claims)
    visible = []
    for row in db.scalars(select(ShadowObservation).order_by(ShadowObservation.id)):
        try:
            service.observation_access(db, row, user)
            _financial_access(db, row.id, user)
            visible.append(row)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    ids = {row.id for row in visible}
    pending = sum(row.observation_id in ids and row.state != "exported" for row in db.scalars(select(ShadowOutbox)))
    settings = get_settings()
    return ok({"enabled": bool(getattr(settings, "COMMERCE_SHADOW_ENABLED", False)),
        "worker_enabled": bool(getattr(settings, "COMMERCE_SHADOW_WORKER_ENABLED", False)),
        "pending_outbox": pending, "unknown_observations": sum(row.outcome == "unknown" for row in visible),
        "observed_through": max(ids, default=0), "coverage": "not_observed" if not visible else "lagging" if pending else "observed",
        "rejection_coverage": "observed_only"})


@router.get("/runs")
def runs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), dataset_id: str | None = None,
         invoice_id: int | None = Query(None, gt=0), db=Depends(get_db),
         claims=Depends(require_permission("commerce_shadow:read"))):
    user = _user(db, claims)
    query = select(ShadowRun).order_by(ShadowRun.created_at.desc(), ShadowRun.id.desc())
    if dataset_id:
        query = query.where(ShadowRun.dataset_id == dataset_id)
    rows = db.scalars(query)
    result = []
    for row in rows:
        if (invoice_id is None or invoice_id in row.invoice_ids) and _visible(db, row, user):
            result.append(service.describe_run(row))
    start = (page - 1) * page_size
    return ok({"items": result[start:start + page_size], "total": len(result), "page": page, "page_size": page_size})


@router.get("/runs/{identity}")
def run(identity: str, db=Depends(get_db), claims=Depends(require_permission("commerce_shadow:read"))):
    user = _user(db, claims)
    row = db.get(ShadowRun, identity)
    if row is None or not _visible(db, row, user):
        raise HTTPException(404, "对比运行不存在")
    result = service.describe_run(row)
    result["results"] = [{key: getattr(sample, key) for key in ("observation_id", "execution_event_id",
        "status", "candidate_outcome", "actual", "checked_at")} for sample in db.scalars(
            select(ShadowResult).where(ShadowResult.run_id == identity).order_by(ShadowResult.id))]
    return ok(result)


@router.get("/runs/{identity}/input")
def export_input(identity: str, db=Depends(get_db), claims=Depends(require_permission("commerce_shadow:admin"))):
    """Operator transport only. Exporting does not acknowledge the outbox."""
    from app.commerce_shadow.transport import export_input_bundle
    user = _user(db, claims, "admin")
    row = db.get(ShadowRun, identity)
    if row is None or not _visible(db, row, user):
        raise HTTPException(404, "对比运行不存在")
    return ok(export_input_bundle(db, identity))


@router.post("/runs/{identity}/receipts")
def import_receipts(identity: str, body: ExecutionReport, db=Depends(get_db),
                    claims=Depends(require_permission("commerce_shadow:admin"))):
    """Import a candidate-only receipt against a SERVER-derived source bundle."""
    from app.commerce_shadow.transport import export_input_bundle, import_execution_receipts
    user = _user(db, claims, "admin")
    row = db.get(ShadowRun, identity)
    if row is None or not _visible(db, row, user):
        raise HTTPException(404, "对比运行不存在")
    if body.run_id != identity:
        raise HTTPException(409, "候选回执不属于该运行")
    try:
        report_data = service.canonical(body.model_dump())
        bundle = export_input_bundle(db, identity)
        row = import_execution_receipts(db, bundle, report_data)
        db.commit()
        return ok(service.describe_run(row))
    except ValueError as exc:
        db.rollback()
        report("receipt_import_rejected", exc)
        raise HTTPException(409, str(exc)) from None
    except Exception as exc:
        db.rollback()
        report("receipt_import_failed", exc)
        raise


@router.post("/runs")
def replay(body: ReplayRequest, db=Depends(get_db), claims=Depends(require_permission("commerce_shadow:write"))):
    user = _user(db, claims, "write")
    if not getattr(get_settings(), "COMMERCE_SHADOW_ENABLED", False):
        raise HTTPException(409, "交易对比尚未启用")
    try:
        row = service.request_run(db, body, user)
        if not _visible(db, row, user):
            raise HTTPException(404, "对比运行不存在")
        db.commit()
        return ok(service.describe_run(row))
    except ValueError as exc:
        db.rollback()
        report("run_request_rejected", exc)
        raise HTTPException(409, str(exc)) from None
    except Exception as exc:
        db.rollback()
        report("run_request_failed", exc)
        raise


@router.get("/differences")
def differences(run_id: str | None = None, invoice_id: int | None = Query(None, gt=0), dataset_id: str | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                db=Depends(get_db), claims=Depends(require_permission("commerce_shadow:read"))):
    user = _user(db, claims)
    query = select(ShadowDifference).order_by(ShadowDifference.id.desc())
    if run_id:
        query = query.where(ShadowDifference.run_id == run_id)
    if dataset_id:
        query = query.where(ShadowDifference.run_id.in_(select(ShadowRun.id).where(ShadowRun.dataset_id == dataset_id)))
    if invoice_id:
        service.invoice_access(db, invoice_id, user)
        query = query.where(ShadowDifference.invoice_id == invoice_id)
    result = []
    for row in db.scalars(query):
        run_row = db.get(ShadowRun, row.run_id)
        if not run_row or not _visible(db, run_row, user):
            continue
        data = service.describe_difference(row)
        data["reviews"] = [{key: getattr(review, key) for key in ("actor_id", "classification", "evidence", "reviewed_at")}
            for review in db.scalars(select(ShadowReview).where(ShadowReview.difference_id == row.id).order_by(ShadowReview.id))]
        result.append(data)
    start = (page - 1) * page_size
    return ok({"items": result[start:start + page_size], "total": len(result), "page": page, "page_size": page_size})


@router.post("/differences/{identity}/review")
def review(identity: int, body: ReviewRequest, db=Depends(get_db), claims=Depends(require_permission("commerce_shadow:admin"))):
    user = _user(db, claims, "admin")
    existing = db.get(ShadowDifference, identity)
    if not existing or not _visible(db, db.get(ShadowRun, existing.run_id), user):
        raise HTTPException(404, "差异不存在")
    try:
        row = service.review_difference(db, identity, body, user)
        db.commit()
        return ok(service.describe_difference(row))
    except ValueError as exc:
        db.rollback()
        report("review_rejected", exc)
        raise HTTPException(409, str(exc)) from None
    except Exception as exc:
        db.rollback()
        report("review_failed", exc)
        raise
