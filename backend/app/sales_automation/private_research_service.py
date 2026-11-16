"""私海客户完整背调：按业务员圈定有效主负责客户，冻结订单/产品快照并创建 full_research 研究任务。

私海客户大多已经下过订单，因此任务创建时把客户的有效订单与产品明细聚合快照
一并冻结进 input_snapshot.commerce_snapshot，执行研究的 Agent 在任务上下文中
直接看到该客户的成交与产品情况，背调结论可以结合采购历史研判。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, load_only

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.logical_customer_service import (
    logical_root_query,
    logical_root_predicate,
    resolve_canonical_customer_id,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerListProjection,
    CustomerOrder,
    CustomerOrderItem,
    CustomerResearchTask,
    CustomerTargetMatch,
)
from app.sales_automation import public_pool_service, service
from app.sales_automation.private_enrichment_service import existing_information
from app.sales_automation.private_research_policy import (
    LEGACY_ENRICHMENT_POLICY, PRIVATE_RESEARCH_POLICY, PRIVATE_RESEARCH_RESULT,
)

TASK_TYPE = "full_research"
SOURCE_REF_TYPE = "manual"
POLICY_VERSION = "full-research-v1"
PRIVATE_POLICIES = (POLICY_VERSION, LEGACY_ENRICHMENT_POLICY, PRIVATE_RESEARCH_POLICY)
REQUEST_PRIORITY = 100
COOLDOWN_DAYS = 30
RESEARCH_REQUEST = {
    "schema_version": PRIVATE_RESEARCH_RESULT,
    "focus": [
        "主体识别与依据", "公司与经营概况", "联系人与职业身份", "产品与商业模式",
        "社交账号与公开活动", "采购与供应链线索", "风险与冲突", "跟进切入建议", "来源与缺口",
    ],
    "instructions": [
        "按明确公司实体和弱线索两条路径调查，使用公开可访问来源。",
        "用当前任务已有的姓名、个人邮箱、社媒号或平台昵称核实主体。只引用实际采集的来源。",
        "先免费网页检索，再用用户名扫描。弱线索在仍有关键缺口时才启用 Monid。",
        "仅按任务绑定证据，不发送消息、不写回小满。订单和方舟内部数据只用于内部研判。",
        "正文使用 Markdown，区分事实、推断和资料缺口。提交缺口清单及本次运行返回的证据引用。",
    ],
}
RECENT_ORDER_LIMIT = 5
TOP_FAMILY_LIMIT = 8
TOP_PRODUCT_LIMIT = 10


def resolve_owners(db: Session, owners: list[str]) -> dict[int, ArkUser]:
    """把用户ID或登录用户名解析为启用用户；任一无法识别即整体拒绝。"""
    resolved: dict[int, ArkUser] = {}
    unknown: list[str] = []
    inactive: list[str] = []
    for raw in owners:
        key = str(raw).strip()
        if not key:
            continue
        query = db.query(ArkUser)
        user = (
            query.filter(ArkUser.id == int(key)).one_or_none()
            if key.isdigit()
            else query.filter(ArkUser.username == key).one_or_none()
        )
        if user is None:
            unknown.append(key)
        elif not user.is_active or user.deleted_at is not None:
            inactive.append(key)
        else:
            resolved[int(user.id)] = user
    if unknown or inactive:
        parts = []
        if unknown:
            parts.append(f"不存在的用户: {', '.join(unknown)}")
        if inactive:
            parts.append(f"已停用或删除的用户: {', '.join(inactive)}")
        raise service.SalesAutomationError("；".join(parts))
    if not resolved:
        raise service.SalesAutomationError("未指定任何有效业务员")
    return resolved


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _money(value: Any) -> str:
    return format(Decimal(str(value or 0)), "f")


def _current_target_match(db: Session, customer_id: int) -> CustomerTargetMatch | None:
    return (
        db.query(CustomerTargetMatch)
        .filter(
            CustomerTargetMatch.customer_id == customer_id,
            CustomerTargetMatch.is_current.is_(True),
        )
        .order_by(CustomerTargetMatch.match_score.desc())
        .first()
    )


def _commerce_snapshot(db: Session, customer_id: int) -> dict:
    """聚合客户的有效订单与产品明细；全部值预先转成 JSON 安全类型。"""
    projection = db.get(CustomerListProjection, customer_id)
    orders = (
        logical_root_query(db, CustomerOrder, "order", customer_id)
        .filter(CustomerOrder.is_valid_business_order.is_(True))
        .order_by(
            CustomerOrder.account_date.is_(None),
            CustomerOrder.account_date.desc(),
            CustomerOrder.id.desc(),
        )
        .all()
    )
    order_ids = [int(order.id) for order in orders]
    items = (
        db.query(CustomerOrderItem)
        .filter(CustomerOrderItem.order_id.in_(order_ids), CustomerOrderItem.projection_role == 'active')
        .all()
        if order_ids
        else []
    )
    family_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}
    item_type_counts = {"sample": 0, "bulk": 0, "unknown": 0}
    for item in items:
        item_type_counts[item.item_type if item.item_type in item_type_counts else "unknown"] += 1
        if item.product_family:
            family_counts[item.product_family] = family_counts.get(item.product_family, 0) + 1
        if item.product_name:
            product_counts[item.product_name] = product_counts.get(item.product_name, 0) + 1
    top_families = sorted(family_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:TOP_FAMILY_LIMIT]
    top_products = sorted(product_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:TOP_PRODUCT_LIMIT]
    total_amount = sum((Decimal(order.amount_usd) for order in orders), Decimal("0"))
    recent_orders = [
        {
            "order_no": order.order_no,
            "order_name": order.order_name,
            "account_date": _date_text(order.account_date),
            "amount_usd": _money(order.amount_usd),
            "order_status": order.order_status,
            "is_first_return": order.is_first_return,
        }
        for order in orders[:RECENT_ORDER_LIMIT]
    ]
    return {
        "as_of": beijing_now().isoformat(),
        "has_valid_order": bool(orders),
        "valid_order_count": len(orders),
        "valid_order_amount_usd": _money(total_amount),
        "first_order_at": _date_text(orders[-1].account_date) if orders else None,
        "last_order_at": _date_text(orders[0].account_date) if orders else None,
        "item_type_counts": item_type_counts,
        "top_product_families": [
            {"product_family": family, "item_count": count} for family, count in top_families
        ],
        "top_products": [
            {"product_name": name, "item_count": count} for name, count in top_products
        ],
        "recent_orders": recent_orders,
        "primary_product_family": projection.primary_product_family if projection else None,
        "commercial_value_score": _money(projection.commercial_value_score) if projection and projection.commercial_value_score is not None else None,
        "engagement_health": projection.engagement_health if projection else None,
    }


def create_private_research_tasks(
    db: Session,
    *,
    owner_ids: list[int] | None,
    run_tag: str,
    operator_id: int | None,
    limit: int | None = None,
    customer_ids: list[int] | None = None,
    commit: bool = True,
    enrichment: bool = False,
    private_v2: bool = False,
    with_orders: bool = False,
    unresearched: bool = False,
) -> dict:
    """为指定业务员的有效主负责客户批量创建 full_research 研究任务。

    幂等：同一客户同策略版本存在进行中任务时复用原任务；输入快照变化后
    （例如有新订单）允许创建新一轮任务。全局禁止开发（DNC/抑制名单）客户跳过。
    """
    if enrichment and private_v2:
        raise ValueError("请选择一个私海研究策略")
    policy = PRIVATE_RESEARCH_POLICY if private_v2 else LEGACY_ENRICHMENT_POLICY if enrichment else POLICY_VERSION
    assignments_query = (
        db.query(CustomerAssignment)
        .filter(
            CustomerAssignment.assignment_role == "primary",
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        )
        .order_by(CustomerAssignment.customer_id)
    )
    if owner_ids is not None:
        assignments_query = assignments_query.filter(CustomerAssignment.user_id.in_(owner_ids))
    if enrichment or private_v2:
        assignments_query = assignments_query.filter(CustomerAssignment.effective_from <= beijing_now())
    assignments = assignments_query.all()
    candidates: list[tuple[int, int]] = []
    seen: set[int] = set()
    unresolvable: list[int] = []
    for assignment in assignments:
        owner_id = int(assignment.user_id)
        canonical_id = resolve_canonical_customer_id(db, int(assignment.customer_id))
        if canonical_id is None:
            unresolvable.append(int(assignment.customer_id))
            continue
        if canonical_id in seen:
            continue
        seen.add(canonical_id)
        candidates.append((canonical_id, owner_id))

    def _sort_key(pair: tuple[int, int]):
        projection = db.get(CustomerListProjection, pair[0])
        amount = projection.valid_order_amount_usd if projection else None
        return (-(Decimal(amount) if amount is not None else Decimal("0")), pair[0])

    if customer_ids is not None:
        allowed_ids = {int(customer_id) for customer_id in customer_ids}
        candidates = [pair for pair in candidates if pair[0] in allowed_ids]
    if with_orders:
        candidates = [pair for pair in candidates if _has_valid_order(db, pair[0])]
    if unresearched:
        candidates = [pair for pair in candidates if not _has_research_result(db, pair[0])]
    candidates.sort(key=_sort_key)
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]

    summary = {
        "run_tag": run_tag,
        "policy_version": policy,
        "candidate_count": len(candidates),
        "created": 0,
        "reused": 0,
        "skipped_dnc": [],
        "skipped_unresolvable": unresolvable,
        "errors": [],
        "tasks": [],
    }
    for customer_id, owner_id in candidates:
        if public_pool_service.is_development_denied(db, customer_id):
            summary["skipped_dnc"].append(customer_id)
            continue
        tier = public_pool_service._tier_for_customer(db, customer_id)
        match = _current_target_match(db, customer_id)
        account = db.get(CustomerAccount, customer_id)
        input_snapshot = {
            "schema_version": "research_input_v1",
            "customer_id": customer_id,
            "profile_input_seq": account.profile_input_seq,
            "trigger": "manual_private_research",
            "run_tag": run_tag,
            "owner_user_id": owner_id,
            "target_match": {
                "tier": tier,
                "match_score": _money(match.match_score) if match else None,
            },
            "commerce_snapshot": _commerce_snapshot(db, customer_id),
        }
        try:
            if enrichment:
                from app.sales_automation.private_enrichment_service import ensure_enrichment_task

                task, was_created = ensure_enrichment_task(
                    db, customer_id=customer_id, operator_id=operator_id,
                    run_tag=run_tag, input_snapshot=input_snapshot, tier=tier,
                )
                summary["policy_version"] = task.research_policy_version
            elif private_v2:
                task, was_created = _ensure_private_v2_task(
                    db, account, owner_id, operator_id, run_tag, input_snapshot, tier=tier,
                )
            else:
                task, was_created = public_pool_service.ensure_research_task(
                    db,
                    customer_id=customer_id,
                    task_type=TASK_TYPE,
                    source_ref_type=SOURCE_REF_TYPE,
                    source_ref_id=run_tag,
                    research_policy_version=POLICY_VERSION,
                    input_snapshot=input_snapshot,
                    selection_reason=[{
                        "reason": "manual_private_research",
                        "owner_user_id": owner_id,
                        "tier": tier,
                    }],
                    tier=tier,
                    created_by=operator_id,
                )
        except (service.ConflictError, service.NotFoundError, ValueError) as exc:
            summary["errors"].append({"customer_id": customer_id, "error": str(exc)})
            continue
        summary["created" if was_created else "reused"] += 1
        summary["tasks"].append({
            "task_id": int(task.id),
            "customer_id": customer_id,
            "customer_code": account.customer_code,
            "display_name": account.display_name,
            "owner_user_id": owner_id,
            "tier": tier,
            "created": was_created,
        })
    if commit:
        db.commit()
    return summary


def _private_tasks(db, customer_id):
    return db.query(CustomerResearchTask).filter(
        logical_root_predicate(CustomerResearchTask, "research_task", customer_id),
        CustomerResearchTask.customer_id == customer_id,
        CustomerResearchTask.task_type == TASK_TYPE,
        CustomerResearchTask.source_ref_type == SOURCE_REF_TYPE,
        CustomerResearchTask.research_policy_version.in_(PRIVATE_POLICIES),
    )


def _has_valid_order(db, customer_id):
    return logical_root_query(db, CustomerOrder, "order", customer_id).filter(
        CustomerOrder.is_valid_business_order.is_(True),
    ).first() is not None


def _has_research_result(db, customer_id):
    return _private_tasks(db, customer_id).filter(
        CustomerResearchTask.task_status == "completed",
        CustomerResearchTask.result_review_status != "rejected",
        CustomerResearchTask.result_schema_version.in_(("customer_research_v1", PRIVATE_RESEARCH_RESULT)),
    ).first() is not None


def _ensure_private_v2_task(db, account, owner_id, operator_id, run_tag, snapshot, *, tier=None, priority=0):
    info = existing_information(db, account, include_personal=True)
    company = bool(account.canonical_company_name and account.canonical_company_name.strip()) or any(
        row["verification_status"] == "verified" for row in info["website_clues"]
    ) or any(
        row["type"] == "email" and row.get("email_domain_type") == "corporate"
        and row["verification_status"] not in {"disputed", "invalid"} for row in info["business_contacts"]
    )
    snapshot = {
        **snapshot,
        "owner_user_id": owner_id,
        "research_request": RESEARCH_REQUEST,
        "existing_information": info,
        "lead_track": "company" if company else "weak",
    }
    return public_pool_service.ensure_research_task(
        db, customer_id=account.id, task_type=TASK_TYPE, source_ref_type=SOURCE_REF_TYPE,
        source_ref_id=run_tag, research_policy_version=PRIVATE_RESEARCH_POLICY,
        input_snapshot=snapshot, selection_reason=[{"reason": snapshot["trigger"]}],
        tier=tier, created_by=operator_id, physical_owner_only=True, priority=priority,
    )


def _research_status(tasks, now):
    active = next((task for task in tasks if task.task_status == "running"), None)
    active = active or next((task for task in tasks if task.task_status == "pending"), None)
    latest = active or (tasks[0] if tasks else None)
    last_run = max((task.finished_at for task in tasks if task.finished_at is not None), default=None)
    last_request = next((task for task in tasks if task.priority == REQUEST_PRIORITY), None)
    cooldown = last_request.created_at + timedelta(days=COOLDOWN_DAYS) if last_request else None
    remaining = max(0, int((cooldown - now).total_seconds() + 0.999)) if cooldown else 0
    status = latest.task_status if latest else "idle"
    return {
        "status": status,
        "last_run_at": last_run.isoformat() if last_run else None,
        "cooldown_until": cooldown.isoformat() if cooldown else None,
        "cooldown_remaining_seconds": remaining,
        "can_rerun": not remaining and status != "running",
    }


def _current_tasks(db, customer_id):
    return _private_tasks(db, customer_id).filter(CustomerResearchTask.task_status != "superseded").order_by(
        CustomerResearchTask.created_at.desc(), CustomerResearchTask.id.desc(),
    )


def private_research_status(db, *, customer_id):
    tasks = _current_tasks(db, customer_id).options(load_only(
        CustomerResearchTask.task_status, CustomerResearchTask.finished_at,
        CustomerResearchTask.created_at, CustomerResearchTask.priority,
    )).all()
    return _research_status(tasks, beijing_now())


def rerun_private_research(db, *, customer_id, owner_user_id):
    """Create an owner-requested task; the desk caller rechecks current OKKI ownership first."""
    from app.sales_automation.research_run_service import finish_run

    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == customer_id, CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise service.NotFoundError("客户不存在")
    if public_pool_service.is_development_denied(db, customer_id):
        raise service.ConflictError("该客户当前不允许发起背调")
    # A locking read observes committed cooldowns and serializes task claims with replacement.
    tasks = _current_tasks(db, customer_id).populate_existing().with_for_update().all()
    if not _research_status(tasks, beijing_now())["can_rerun"]:
        raise service.ConflictError("背调进行中或仍在冷却期")
    for task in tasks:
        if task.task_status != "pending" and not (
            task.task_status == "completed" and task.result_review_status in {"pending", "revision_requested"}
        ):
            continue
        finish_run(db, task, "cancelled", "research_superseded")
        task.task_status = "superseded"
        task.result_review_status = "superseded"
        task.claimed_by = None
        task.lease_token_hash = None
        task.lease_expires_at = None
    db.flush()
    run_tag = f"private-rerun-{uuid4().hex}"
    _ensure_private_v2_task(db, account, owner_user_id, owner_user_id, run_tag, {
        "schema_version": "research_input_v1",
        "customer_id": customer_id,
        "profile_input_seq": account.profile_input_seq,
        "trigger": "private_research_rerun",
        "run_tag": run_tag,
        "commerce_snapshot": _commerce_snapshot(db, customer_id),
    }, priority=REQUEST_PRIORITY)
    db.commit()
    return private_research_status(db, customer_id=customer_id)


def research_report(db: Session, *, run_tag: str | None = None) -> list[dict]:
    """按 run_tag（缺省全部 full_research 任务）导出背调与分级结果行。"""
    query = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.task_type == TASK_TYPE,
        CustomerResearchTask.source_ref_type == SOURCE_REF_TYPE,
    )
    if run_tag:
        query = query.filter(CustomerResearchTask.source_ref_id == run_tag)
    rows: list[dict] = []
    for task in query.order_by(CustomerResearchTask.id).all():
        account = db.get(CustomerAccount, task.customer_id)
        assignment = (
            db.query(CustomerAssignment)
            .filter(
                CustomerAssignment.customer_id == task.customer_id,
                CustomerAssignment.assignment_role == "primary",
                CustomerAssignment.assignment_status == "active",
                CustomerAssignment.effective_to.is_(None),
            )
            .first()
        )
        owner = db.get(ArkUser, assignment.user_id) if assignment else None
        projection = db.get(CustomerListProjection, task.customer_id)
        match = _current_target_match(db, task.customer_id)
        rows.append({
            "run_tag": task.source_ref_id,
            "task_id": int(task.id),
            "customer_id": task.customer_id,
            "customer_code": account.customer_code if account else None,
            "display_name": account.display_name if account else None,
            "owner_username": owner.username if owner else None,
            "owner_name": owner.real_name if owner else None,
            "tier": task.tier,
            "match_score": _money(match.match_score) if match else None,
            "commercial_value_score": _money(projection.commercial_value_score) if projection and projection.commercial_value_score is not None else None,
            "valid_order_count": projection.valid_order_count if projection else None,
            "valid_order_amount_usd": _money(projection.valid_order_amount_usd) if projection else None,
            "last_order_at": _date_text(projection.last_order_at) if projection else None,
            "task_status": task.task_status,
            "gate_status": task.gate_status,
            "result_review_status": task.result_review_status,
            "research_summary": (task.research_summary or "")[:500],
            "created_at": _date_text(task.created_at),
            "finished_at": _date_text(task.finished_at),
        })
    return rows
