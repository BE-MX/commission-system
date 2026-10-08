"""Personal views and evidence-backed internal actions."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from datetime import timedelta
from app.core.time import beijing_today, beijing_now
from app.domestic.models import DomesticCustomer, DomesticOrder, DomesticCustomerLedger, DomesticCustomerRequest
from app.domestic_decision import scope
from app.domestic_decision.models import DecisionAction, DecisionView, DecisionMapping, DecisionConfig
from app.domestic_decision.run_service import require_run, has


def _view(row):
    return {"id": row.id, "name": row.name, "query": row.query_json, "time_mode": row.time_mode, "shared": bool(row.shared), "version": row.version, "owner_user_id": row.owner_user_id}


def list_views(db, actor):
    return [_view(row) for row in db.query(DecisionView).filter((DecisionView.owner_user_id == actor["id"]) | (DecisionView.shared == 1)).order_by(DecisionView.updated_at.desc()).limit(100).all()]


def save_view(db, actor, payload, view_id=None):
    row = db.query(DecisionView).filter(DecisionView.id == view_id, DecisionView.owner_user_id == actor["id"]).with_for_update().first() if view_id else None
    if view_id and row is None:
        raise HTTPException(404, "个人视图不存在")
    if row and row.version != payload.expected_version:
        raise HTTPException(409, "视图已变更，请刷新")
    if row is None:
        row = DecisionView(owner_user_id=actor["id"], version=1)
        db.add(row)
    else:
        row.version += 1
    row.name, row.query_json = payload.name.strip(), payload.query.model_dump(mode="json")
    row.time_mode, row.shared = payload.time_mode, int(payload.shared)
    if not row.name:
        raise HTTPException(422, "视图名称不能为空")
    db.commit()
    return _view(row)


def delete_view(db, actor, view_id):
    row = db.query(DecisionView).filter(DecisionView.id == view_id, DecisionView.owner_user_id == actor["id"]).first()
    if not row:
        raise HTTPException(404, "个人视图不存在")
    db.delete(row)
    db.commit()


def _trigger(db, customer_id, include_finance=False):
    orders = db.query(DomesticOrder.id, DomesticOrder.status, DomesticOrder.deleted_flag, DomesticOrder.total_amount, DomesticOrder.updated_at).filter(DomesticOrder.customer_id == customer_id, DomesticOrder.order_kind == "business").order_by(DomesticOrder.id).all()
    payload = [tuple(str(v) for v in order) for order in orders]
    if include_finance:
        payload += [tuple(str(v) for v in entry) for entry in db.query(DomesticCustomerLedger.id, DomesticCustomerLedger.amount).filter(DomesticCustomerLedger.customer_id == customer_id).order_by(DomesticCustomerLedger.id).all()]
        payload += [tuple(str(v) for v in entry) for entry in db.query(DomesticCustomerRequest.id, DomesticCustomerRequest.status, DomesticCustomerRequest.amount, DomesticCustomerRequest.reviewed_at).filter(DomesticCustomerRequest.customer_id == customer_id).order_by(DomesticCustomerRequest.id).all()]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def _action(row):
    return {"id": row.id, "customer_id": row.customer_id, "assignee_user_id": row.assignee_user_id, "rule_key": row.rule_key, "title": row.title, "evidence": row.evidence_json, "due_date": row.due_date.isoformat(), "status": row.status, "result": row.result, "result_type": row.result_type, "condition_changed": bool(row.condition_changed), "version": row.version, "created_at": row.created_at.isoformat()}


def _visible_actions(db, actor):
    ids = scope.customer_query(db, actor).with_entities(DomesticCustomer.id)
    return db.query(DecisionAction).filter(DecisionAction.customer_id.in_(ids))


def _reassign_transferred(db, row):
    customer = db.query(DomesticCustomer).filter(DomesticCustomer.id == row.customer_id).populate_existing().first()
    former_owner = row.trigger_json.get("customer_owner_user_id")
    if customer and former_owner != customer.owner_user_id and customer.owner_user_id is not None:
        row.assignee_user_id = customer.owner_user_id
        row.trigger_json = {**row.trigger_json, "customer_owner_user_id": customer.owner_user_id}
        row.version += 1


def list_actions(db, actor):
    rows = _visible_actions(db, actor).order_by(DecisionAction.due_date, DecisionAction.id.desc()).limit(500).with_for_update().all()
    visible = []
    for row in rows:
        _reassign_transferred(db, row)
        finance = row.trigger_json.get("includes_finance", False)
        if finance and not has(actor, "domestic_decision_finance:read"):
            continue
        if row.status in {"todo", "in_progress"} and _trigger(db, row.customer_id, finance) != row.trigger_json.get("fingerprint"):
            if not row.condition_changed:
                row.condition_changed = 1
                row.version += 1
        visible.append(_action(row))
    db.commit()
    return visible


def create_action(db, actor, payload):
    customer = scope.require_customer(db, actor, payload.customer_id)
    customer = db.query(DomesticCustomer).filter(DomesticCustomer.id == payload.customer_id).with_for_update().populate_existing().one()
    if not has(actor, "domestic_decision:read_all") and customer.owner_user_id != actor["id"]:
        raise HTTPException(404, "客户不存在或不在当前范围")
    request_hash = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    existing = db.query(DecisionAction).filter_by(owner_user_id=actor["id"], request_key=payload.request_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "请求号已用于其他行动内容")
        if existing.trigger_json.get("includes_finance") and not has(actor, "domestic_decision_finance:read"):
            raise HTTPException(403, "需要资金阅读权限")
        return _action(existing)
    run = require_run(db, actor, payload.run_id, fresh=True)
    insight = next((item for item in run.result_json.get("insights", []) if item.get("customer_id") == payload.customer_id and item["rule_key"] == payload.rule_key), None)
    if insight is None:
        raise HTTPException(422, "建议不在当前证据中，请刷新")
    if payload.due_date < beijing_today():
        raise HTTPException(422, "行动期限不能早于今天")
    finance = insight.get("requires_finance", False)
    fingerprint = _trigger(db, payload.customer_id, finance)
    period = run.result_json["meta"]["period"]
    business_key = {"customer_id": payload.customer_id, "rule_key": payload.rule_key, "period": period, "fingerprint": fingerprint}
    source_key = hashlib.sha256(json.dumps(business_key, sort_keys=True).encode()).hexdigest()
    recent = db.query(DecisionAction).filter(
        DecisionAction.customer_id == payload.customer_id,
        DecisionAction.rule_key == payload.rule_key,
    ).order_by(DecisionAction.id.desc()).with_for_update().all()
    for row in recent:
        _reassign_transferred(db, row)
        unchanged = row.trigger_json.get("fingerprint") == fingerprint
        same_window = row.trigger_json.get("period") == period
        within_week = row.created_at >= beijing_now() - timedelta(days=7)
        if unchanged and (same_window or within_week or row.status in {"todo", "in_progress"}):
            db.commit()
            return _action(row)
        if not unchanged and row.status in {"todo", "in_progress"} and not row.condition_changed:
            row.condition_changed = 1
            row.version += 1
    meta = {key: run.result_json["meta"].get(key) for key in ["run_id", "period", "data_as_of", "metric_version", "mapping_version", "rule_version"]}
    row = DecisionAction(
        owner_user_id=actor["id"], assignee_user_id=actor["id"], customer_id=payload.customer_id,
        source_key=source_key, request_key=payload.request_key, request_hash=request_hash,
        rule_key=payload.rule_key, title=insight["title"], evidence_json={"insight": insight, "meta": meta},
        trigger_json={"fingerprint": fingerprint, "period": period, "includes_finance": finance, "customer_owner_user_id": customer.owner_user_id},
        due_date=payload.due_date, status="todo", condition_changed=0, version=1,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(DecisionAction).filter(DecisionAction.owner_user_id == actor["id"], (DecisionAction.source_key == source_key) | (DecisionAction.request_key == payload.request_key)).first()
        if not existing or existing.customer_id != payload.customer_id or existing.rule_key != payload.rule_key:
            raise HTTPException(409, "行动请求冲突，请刷新")
        if existing.request_key == payload.request_key and existing.request_hash != request_hash:
            raise HTTPException(409, "请求号已用于其他行动内容")
        return _action(existing)
    return _action(row)


def update_action(db, actor, action_id, payload):
    row = _visible_actions(db, actor).filter(DecisionAction.id == action_id).with_for_update().first()
    if row is None:
        raise HTTPException(404, "行动不存在")
    _reassign_transferred(db, row)
    if row.assignee_user_id != actor["id"]:
        raise HTTPException(403, "只能更新本人负责的行动")
    if row.trigger_json.get("includes_finance") and not has(actor, "domestic_decision_finance:read"):
        raise HTTPException(403, "需要资金阅读权限")
    if row.version != payload.expected_version:
        raise HTTPException(409, "行动已变更，请刷新")
    if row.status in {"done", "dismissed"} and payload.status != row.status:
        raise HTTPException(409, "已结束行动不能重新开启，请创建新行动")
    if payload.status == "done" and (not payload.result.strip() or payload.result_type is None):
        raise HTTPException(422, "完成行动需要记录实际结果及结果类型")
    row.status, row.result, row.result_type = payload.status, payload.result.strip(), payload.result_type
    row.version += 1
    db.commit()
    return _action(row)


def save_mapping(db, actor, payload):
    row = db.query(DecisionMapping).filter_by(property=payload.property, product_type=payload.product_type, raw_value=payload.raw_value.strip()).with_for_update().first()
    if row and row.version != payload.expected_version:
        raise HTTPException(409, "映射已变化，请刷新并提供版本")
    if row is None:
        row = DecisionMapping(property=payload.property, product_type=payload.product_type, raw_value=payload.raw_value.strip(), version=1)
        db.add(row)
    else:
        row.version += 1
    row.standard_value, row.updated_by = payload.standard_value.strip(), actor["id"]
    if not row.raw_value or not row.standard_value:
        raise HTTPException(422, "映射值不能为空")
    db.commit()
    return {"id": row.id, "version": row.version}


def save_config(db, actor, key, payload):
    value = payload.value
    if key == "coverage_start":
        from datetime import date
        if value is not None:
            try:
                value = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise HTTPException(422, "覆盖起点需为有效日期")
    elif key == "aftersales_order_types":
        from app.system.models import SysDict
        codes = {row.code for row in db.query(SysDict).filter(SysDict.type == "domestic_order_type").all()}
        if not isinstance(value, list) or not set(value).issubset(codes):
            raise HTTPException(422, "售后类型必须取运行时订单字典")
    elif key == "quality_threshold":
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not 0.5 <= value <= 1:
            raise HTTPException(422, "覆盖门槛需在0.5到1之间")
    elif key == "dormant_days":
        if not isinstance(value, int) or isinstance(value, bool) or not 30 <= value <= 365:
            raise HTTPException(422, "沉默天数需为30到365")
    elif key == "ai_daily_limit":
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 50:
            raise HTTPException(422, "每日AI请求上限需为1到50")
    elif key == "inactive_lifecycle_statuses":
        from app.system.models import SysDict
        codes = {row.code for row in db.query(SysDict).filter(SysDict.type == "domestic_customer_lifecycle").all()}
        if not isinstance(value, list) or any(not isinstance(code, str) for code in value) or not set(value).issubset(codes):
            raise HTTPException(422, "停联状态需取客户生命周期字典")
    elif key == "coverage_refund_ratio_limit":
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise HTTPException(422, "退款占扣款门槛需在0到1之间")
    else:
        raise HTTPException(422, "配置项不支持")
    row = db.query(DecisionConfig).filter_by(key=key).with_for_update().first()
    if (row.version if row else 0) != payload.expected_version:
        raise HTTPException(409, "配置已变化，请刷新")
    if row is None:
        row = DecisionConfig(key=key, version=1)
        db.add(row)
    else:
        row.version += 1
    row.value, row.updated_by, row.updated_at = value, actor["id"], beijing_now()
    db.commit()
    return {"key": key, "value": value, "version": row.version}
