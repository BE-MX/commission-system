"""Lease-scoped request, status, candidate binding and accounting."""

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import case, func

from app.agent_runtime.event_service import content_hash
from app.core.config import get_settings
from app.core.time import beijing_now
from app.customer.models import CustomerAccount, CustomerFact, CustomerResearchTask
from app.sales_automation import public_pool_service, research_run_service, service
from app.sales_automation.research_tools_models import ResearchToolCall as Call
from app.sales_automation.research_tools_providers import KEY, OPERATIONS, is_enabled, normalize_target
from app.sales_automation.private_research_policy import is_private_research_v2


def _task(db, task_id, actor_id, agent_id, lease_token, run_id):
    task, input_hash = public_pool_service.validate_research_fact_write(
        db, task_id, actor_id, agent_id, lease_token, run_id,
    )
    if (not is_private_research_v2(task) or (task.input_snapshot or {}).get("lead_track") not in {"company", "weak"}
            or task.gate_status not in {"passed", "not_required"}):
        raise service.ConflictError("外部工具仅供通过门控的私海背调 v2 使用")
    return task, input_hash


def _scoped_call(db, task, run_id, tool, call_id):
    row = db.query(Call).filter_by(id=call_id, task_id=task.id, run_id=run_id, tool=tool,
                                   lease_generation=task.lease_generation).with_for_update().one_or_none()
    if row is None:
        raise service.NotFoundError("当前租约不存在该研究工具调用")
    return row


def _response(row):
    status = "running" if row.status in {"preparing", "submitting", "polling"} else row.status
    return {"call_id": row.id, "tool": row.tool, "operation": row.operation, "status": status,
            "result": (row.response_json or {}).get("result"), "error_code": row.error_code}


def _free_search(data):
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    if not isinstance(data, dict) or data.keys() != {"queries", "outcome"}:
        raise service.SalesAutomationError("扫描需记录免费网页搜索尝试和结果")
    queries = data["queries"]
    if (not isinstance(queries, list) or not 1 <= len(queries) <= 5
            or any(not isinstance(q, str) or not q.strip() or len(q) > 250 or any(ord(c) < 32 for c in q) for q in queries)
            or data["outcome"] not in {"insufficient", "candidate_found"}):
        raise service.SalesAutomationError("免费网页搜索记录无效")
    return {"queries": [q.strip() for q in queries], "outcome": data["outcome"]}


def _identity_key(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _relevant_scan(scan, operation, target):
    if (scan.status not in {"succeeded", "unavailable"} or not scan.free_search
            or scan.started_at is None or scan.error_code in {"provider_disabled", "worker_interrupted"}):
        return False
    candidates = ((scan.response_json or {}).get("result") or {}).get("candidates", [])
    if any((item.get("source_url") or "").rstrip("/").lower() == target for item in candidates):
        return True
    if operation == "hunter_domain_email":
        return any(re.search(r"(?<![a-z0-9.-])" + re.escape(target) + r"(?![a-z0-9.-])", query.lower())
                   for query in scan.free_search["queries"])
    slug = _identity_key(target.rsplit("/", 1)[-1])
    username = _identity_key(scan.target)
    return bool(username and (slug == username or (
        operation == "linkedin_profile" and len(username) >= 5 and slug.startswith(username)
        and slug[len(username):].isdigit()
    )))


def company_identified(db, task, run_id):
    if (task.input_snapshot or {}).get("lead_track") != "weak":
        return True
    # An official company identity observed during the free stage closes A7 as well.
    return db.query(CustomerFact.id).filter(
        CustomerFact.customer_id == task.customer_id, CustomerFact.agent_run_id == run_id,
        CustomerFact.fact_key == "research.source.company_identity",
        CustomerFact.verification_status.notin_(("rejected", "disputed", "superseded")),
    ).with_for_update().first() is not None


def _monid_allocation(rows):
    return sum(row.charged_microusd if row.charged_microusd is not None else row.reserved_microusd
               for row in rows if row.tool == "monid")


def monid_budget_still_valid(db, task_id, limit):
    rows = db.query(Call).filter_by(task_id=task_id, tool="monid").with_for_update().all()
    return _monid_allocation(rows) <= limit and not any(row.error_code == "charge_over_cap" for row in rows)


def submit_call(db, task_id, actor_id, agent_id, lease_token, agent_run_id, *,
                tool, operation, target, idempotency_key, gap=None, free_search=None, maigret_call_id=None):
    task, _ = _task(db, task_id, actor_id, agent_id, lease_token, agent_run_id)
    target = normalize_target(tool, operation, target)
    if not KEY.fullmatch(idempotency_key):
        raise service.SalesAutomationError("研究工具幂等键格式无效")
    # MySQL's configured collation compares ASCII keys case-insensitively.
    idempotency_key = idempotency_key.lower()
    settings = get_settings()
    if tool == "username_scan":
        if gap is not None or maigret_call_id is not None:
            raise service.SalesAutomationError("扫描不接受付费补缺字段")
        free_search = _free_search(free_search)
        lead = _identity_key(target)
        if not any(lead in _identity_key(query) for query in free_search["queries"]):
            raise service.SalesAutomationError("免费搜索记录需包含扫描的用户名线索")
    elif free_search is not None:
        raise service.SalesAutomationError("请先在扫描调用中记录免费网页搜索")
    digest = content_hash({"tool": tool, "operation": operation, "target": target, "gap": gap,
                           "free_search": free_search, "maigret_call_id": maigret_call_id})
    # The parent task already has a row lock; locking read also avoids a stale MySQL RR snapshot.
    rows = db.query(Call).filter_by(task_id=task.id).with_for_update().all()
    current = [row for row in rows if row.run_id == agent_run_id and row.lease_generation == task.lease_generation]
    for old in current:
        if old.idempotency_key == idempotency_key:
            if old.request_hash != digest:
                raise service.ConflictError("该幂等键已用于不同的研究工具请求")
            output = _response(old)
            db.commit()
            return output
    reserve = 0
    if tool == "monid":
        op = OPERATIONS[operation]
        if company_identified(db, task, agent_run_id) or gap not in op.allowed_gaps:
            raise service.ConflictError("付费工具只用于弱线索的指定关键缺口")
        scan = next((item for item in current if item.id == maigret_call_id and item.tool == "username_scan"), None)
        if scan is None or not _relevant_scan(scan, operation, target):
            raise service.ConflictError("付费查询前需完成与该目标相关的免费搜索和用户名扫描")
        if any(row.tool == "monid" and row.operation == operation for row in rows):
            raise service.ConflictError("当前研究任务的该付费接口已调用")
        reserve = op.cap
        if (_monid_allocation(rows) + reserve > settings.PRIVATE_RESEARCH_MONID_BUDGET_MICROUSD
                or any(row.error_code == "charge_over_cap" for row in rows if row.tool == "monid")):
            raise service.ConflictError("当前研究任务付费预算不足")
    elif sum(row.tool == "username_scan" for row in current) >= 5:
        raise service.ConflictError("当前租约的用户名扫描次数已达上限")

    enabled = settings.PRIVATE_RESEARCH_TOOLS_WORKER_ENABLED and is_enabled(settings, tool)
    status = "queued" if enabled else "unavailable"
    row = Call(task_id=task.id, run_id=agent_run_id, lease_generation=task.lease_generation,
               tool=tool, operation=operation, idempotency_key=idempotency_key, request_hash=digest,
               target=target, gap=gap, free_search=free_search, scan_call_id=maigret_call_id, status=status,
               reserved_microusd=reserve if enabled else 0, charged_microusd=None if enabled else 0,
               finished_at=None if enabled else beijing_now(), error_code=None if enabled else "provider_disabled")
    db.add(row)
    db.flush()
    output = _response(row)
    db.commit()
    return output


def get_call(db, task_id, actor_id, agent_id, lease_token, agent_run_id, *, tool, call_id):
    task, _ = _task(db, task_id, actor_id, agent_id, lease_token, agent_run_id)
    return _response(_scoped_call(db, task, agent_run_id, tool, call_id))


def bind_call(db, task_id, actor_id, agent_id, lease_token, agent_run_id, *, tool, call_id, candidate_ids):
    task, input_hash = _task(db, task_id, actor_id, agent_id, lease_token, agent_run_id)
    row = _scoped_call(db, task, agent_run_id, tool, call_id)
    ids = sorted(set(candidate_ids))
    if not ids or len(ids) > 60:
        raise service.SalesAutomationError("请确认至少一项候选证据")
    if row.evidence_refs:
        if ids != row.evidence_refs["candidate_ids"]:
            raise service.ConflictError("同一研究工具调用的候选证据已确认")
        output = row.evidence_refs["receipt"]
        db.commit()
        return output
    if row.status != "succeeded":
        raise service.ConflictError("该研究工具调用尚无可绑定结果")
    candidates = {item["id"]: item for item in row.response_json["result"]["candidates"]}
    if not set(ids) <= candidates.keys():
        raise service.SalesAutomationError("候选证据不属于当前研究工具调用")
    source = "maigret" if tool == "username_scan" else OPERATIONS[row.operation].source
    facts = [
        {
            "fact_key": candidates[i]["fact_type"], "value_type": "object", "value": candidates[i]["value"],
            "fact_layer": "source", "confidence": Decimal("0.40") if tool == "username_scan" else Decimal("0.60"),
            "source_system": tool, "source_entity_type": source, "external_record_id": f"research-tool:{row.id}:{i}",
            "source_url": candidates[i]["source_url"], "source_payload": {"research_tool_call_id": row.id, "candidate_id": i},
            "observed_at": row.finished_at,
        } for i in ids
    ]
    receipt = research_run_service.append_facts_for_run(
        db, task, input_hash, agent_run_id, facts, provider_evidence=True,
    )
    row.evidence_refs = {"candidate_ids": ids, "receipt": receipt}
    db.commit()
    return receipt


def list_spend(db, date_from: date, date_to: date):
    if date_to < date_from or (date_to - date_from).days > 365 or date_to >= date.max:
        raise service.SalesAutomationError("Monid 花费日期范围无效")
    query = db.query(Call).filter(
        Call.tool == "monid", Call.reserved_microusd > 0,
        Call.requested_at >= datetime.combine(date_from, time.min),
        Call.requested_at < datetime.combine(date_to + timedelta(days=1), time.min),
    )
    sums = (func.sum(func.coalesce(Call.charged_microusd, 0)),
            func.sum(case((Call.charged_microusd.is_(None), Call.reserved_microusd), else_=0)), func.count(Call.id))
    day = func.date(Call.requested_at)
    days = query.with_entities(day, *sums).group_by(day).order_by(day.desc()).all()
    customers = (
        query.join(CustomerResearchTask, CustomerResearchTask.id == Call.task_id)
        .join(CustomerAccount, CustomerAccount.id == CustomerResearchTask.customer_id)
        .with_entities(CustomerAccount.id, CustomerAccount.display_name, *sums)
        .group_by(CustomerAccount.id, CustomerAccount.display_name).order_by(CustomerAccount.id).all()
    )

    def amounts(charged, reserve, calls):
        return {"charged_usd": f"{Decimal(charged) / 1_000_000:.6f}",
                "reserved_usd": f"{Decimal(reserve) / 1_000_000:.6f}", "calls": calls}

    return {
        "by_day": [{"day": str(day), **amounts(*values)} for day, *values in days],
        "by_customer": [{"customer_id": cid, "customer_name": name, **amounts(*values)}
                        for cid, name, *values in customers],
    }
