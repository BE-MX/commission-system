"""New customer-portfolio authorization; legacy order permissions do not grant it."""
from datetime import date, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.response import ok
from app.core.time import beijing_today, beijing_now
from app.domestic.models import DomesticOrder, DomesticOrderItem, DomesticCustomerLedger, DomesticCustomerRequest
from app.domestic_decision import analytics, profiles, scope, run_service, state_service, job_service
from app.domestic_decision.models import DecisionMapping, DecisionConfig, DecisionJob
from app.domestic_decision.schemas import AnalysisRequest
from app.domestic_decision.insight_service import enrich
from app.domestic_decision.state_schemas import ViewCreate, ViewUpdate, ActionCreate, ActionUpdate, JobCreate, PlanCreate, MappingCreate, ConfigUpdate

router = APIRouter()


def decision_db(db: Session = Depends(get_db)):
    # Set isolation before live authorization opens the transaction. All page
    # facts then share one MySQL snapshot, even when server defaults differ.
    if db.get_bind().dialect.name in {"mysql", "mariadb"}:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    return db


def _actor(db, jwt, *permissions):
    return scope.live_actor(db, jwt, "domestic_decision:read", *permissions)


@router.get("/filters")
def filters(db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(analytics.filter_options(db, _actor(db, user)))


@router.post("/analysis-runs")
def analysis(payload: AnalysisRequest, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(run_service.create_run(db, _actor(db, user), payload))


@router.get("/analysis-runs/{run_id}")
def get_analysis(run_id: str, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(run_service.require_run(db, _actor(db, user), run_id).result_json)


@router.get("/analysis-runs/{run_id}/rows")
def rows(run_id: str, kind: str = "orders", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), customer_id: int | None = None, order_id: int | None = None, dimension: str | None = None, value: str | None = None, sort_field: str | None = None, sort_order: str | None = None, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(run_service.rows(db, _actor(db, user), run_id, kind=kind, page=page, page_size=page_size, customer_id=customer_id, order_id=order_id, dimension=dimension, value=value, sort_field=sort_field, sort_order=sort_order))


@router.post("/finance-runs")
def finance(payload: AnalysisRequest, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    result = run_service.create_run(db, _actor(db, user, "domestic_decision_finance:read"), payload)
    return ok({"meta": result["meta"], "finance": result["finance"]})


def _query(start_date, end_date):
    today = beijing_today()
    return AnalysisRequest(start_date=start_date or today.replace(day=1), end_date=end_date or today)


@router.get("/customers/{customer_id}/profile")
def customer_profile(customer_id: int, start_date: date | None = None, end_date: date | None = None, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(enrich(profiles.customer_profile(db, _actor(db, user), customer_id, _query(start_date, end_date))))


@router.get("/salespeople/{user_id}/profile")
def salesperson_profile(user_id: int, start_date: date | None = None, end_date: date | None = None, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(enrich(profiles.salesperson_profile(db, _actor(db, user), user_id, _query(start_date, end_date))))


@router.get("/evidence/{kind}/{entity_id}")
def evidence(kind: str, entity_id: int, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    actor = _actor(db, user)
    kind = {"orders": "order", "items": "item", "requests": "request"}.get(kind, kind)
    types = {
        "order": (DomesticOrder, ("id", "domestic_no", "order_date", "customer_id", "order_kind", "order_category", "order_type", "order_channel", "status", "total_amount", "deleted_flag")),
        "item": (DomesticOrderItem, ("id", "order_id", "line_no", "product_name", "attrs_snapshot", "order_qty", "unit_price", "color", "labor_fee", "membership_level_snapshot", "pricing_version")),
        "ledger": (DomesticCustomerLedger, ("id", "customer_id", "order_id", "transaction_type", "amount", "balance_before", "balance_after", "created_at")),
        "request": (DomesticCustomerRequest, ("id", "customer_id", "request_type", "amount", "status", "created_at", "reviewed_at")),
    }
    if kind not in types:
        raise HTTPException(422, "证据类型不支持")
    if kind in {"ledger", "request"}:
        actor = _actor(db, user, "domestic_decision_finance:read")
    model, keys = types[kind]
    row = db.query(model).filter(model.id == entity_id).first()
    if row is None:
        raise HTTPException(404, "证据不存在")
    customer_id = getattr(row, "customer_id", None)
    if kind == "item":
        customer_id = db.query(DomesticOrder.customer_id).filter(DomesticOrder.id == row.order_id).scalar()
    if customer_id is None:
        raise HTTPException(404, "证据不存在")
    scope.require_customer(db, actor, customer_id)
    if kind == "item" and not run_service.has(actor, "domestic_decision_finance:read"):
        keys = tuple(key for key in keys if key != "membership_level_snapshot")
    data = {key: getattr(row, key) for key in keys}
    if kind == "item":
        from app.domestic_decision.event_hooks import safe_snapshot
        data["attrs_snapshot"] = safe_snapshot(data["attrs_snapshot"])
    return ok(data)


@router.post("/data-quality")
def quality(payload: AnalysisRequest, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    result = analytics.build_analysis(db, _actor(db, user), payload)
    return ok({"meta": result["meta"], "quality": result["quality"]})


@router.get("/views")
def views(db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.list_views(db, _actor(db, user)))


@router.post("/views")
def create_view(payload: ViewCreate, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.save_view(db, _actor(db, user), payload))


@router.patch("/views/{view_id}")
def update_view(view_id: int, payload: ViewUpdate, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.save_view(db, _actor(db, user), payload, view_id))


@router.delete("/views/{view_id}")
def delete_view(view_id: int, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    state_service.delete_view(db, _actor(db, user), view_id)
    return ok(None)


@router.get("/actions")
def actions(db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.list_actions(db, _actor(db, user)))


@router.post("/actions")
def create_action(payload: ActionCreate, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.create_action(db, _actor(db, user, "domestic_decision_action:write"), payload))


@router.patch("/actions/{action_id}")
def update_action(action_id: int, payload: ActionUpdate, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.update_action(db, _actor(db, user, "domestic_decision_action:write"), action_id, payload))


def _create_job(payload, kind, background, db, user):
    result, created = job_service.create_job(db, _actor(db, user, "domestic_decision_report:write"), payload, kind)
    if created:
        background.add_task(job_service.execute_job, result["id"])
    return ok(result)


@router.post("/briefs")
def create_brief(payload: JobCreate, background: BackgroundTasks, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return _create_job(payload, "brief", background, db, user)


@router.post("/exports")
def create_export(payload: JobCreate, background: BackgroundTasks, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return _create_job(payload, "export", background, db, user)


@router.post("/query-plans")
def create_plan(payload: PlanCreate, background: BackgroundTasks, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return _create_job(payload, "plan", background, db, user)


@router.get("/briefs")
def list_briefs(db: Session = Depends(decision_db), user=Depends(get_current_user)):
    actor = _actor(db, user, "domestic_decision_report:write")
    jobs = db.query(DecisionJob).filter_by(owner_user_id=actor["id"], kind="brief").order_by(DecisionJob.created_at.desc()).limit(50).all()
    visible = []
    for job in jobs:
        try:
            visible.append(job_service._job(job_service.get_job(db, actor, job.id)))
        except HTTPException as exc:
            if exc.status_code not in {403, 404}:
                raise
    return ok(visible)


@router.get("/briefs/{job_id}")
@router.get("/exports/{job_id}")
@router.get("/query-plans/{job_id}")
def get_job(job_id: str, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    actor = _actor(db, user, "domestic_decision_report:write")
    return ok(job_service._job(job_service.get_job(db, actor, job_id)))


@router.get("/exports/{job_id}/download")
def download(job_id: str, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    row = job_service.get_job(db, _actor(db, user, "domestic_decision_report:write"), job_id)
    if row.kind != "export" or row.status != "succeeded":
        raise HTTPException(409, "导出尚未完成")
    if row.finished_at < beijing_now() - timedelta(days=1):
        raise HTTPException(410, "下载已过期，请重新生成导出")
    return Response(content=row.result_json["content"], media_type=row.result_json["mime"], headers={"Content-Disposition": f'attachment; filename="domestic-decision-{row.id}.{row.result_json["format"]}"', "Cache-Control": "private, no-store"})


@router.get("/settings")
def settings(db: Session = Depends(decision_db), user=Depends(get_current_user)):
    _actor(db, user, "domestic_decision:admin")
    return ok({"mappings": [{"id": row.id, "property": row.property, "product_type": row.product_type, "raw_value": row.raw_value, "standard_value": row.standard_value, "version": row.version} for row in db.query(DecisionMapping).order_by(DecisionMapping.property, DecisionMapping.id).all()], "config": [{"key": row.key, "value": row.value, "version": row.version} for row in db.query(DecisionConfig).all()]})


@router.post("/mappings")
def mapping(payload: MappingCreate, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.save_mapping(db, _actor(db, user, "domestic_decision:admin"), payload))


@router.put("/settings/{key}")
def config(key: str, payload: ConfigUpdate, db: Session = Depends(decision_db), user=Depends(get_current_user)):
    return ok(state_service.save_config(db, _actor(db, user, "domestic_decision:admin"), key, payload))
