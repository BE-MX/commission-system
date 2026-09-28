"""私海客户工作台（PCW）：每日规则评估服务。

设计依据 docs/requirements/private-customer-workbench-prototype/：
- development-spec.md PCW-01：冻结客户范围 + 确定性硬规则每日扫描，AI 只做增量；
- schema-migrations.md 第 1 节：CustomerEvaluationRun/Item 的批次与单客失败隔离语义；
- api-contracts.md 第 3 节：/evaluation-runs 读写契约。

规则 v1（pcw_rules_v1）全部为确定性规则，优先级 P0=urgent / P1=high / P2=normal：
1. inquiry_sla              活跃会话最后一条客户 inbound 超过 24h 无 outbound 回复（>72h 升 P0）
2. sample_feedback_due      样品 delivered/awaiting_test 且计划测试日已到（P1）
3. reorder_window           复购窗口 open 且覆盖业务日（regular=P1 / 其他=P2）；
                            窗口已关闭但事项仍有未执行行动时取消行动并关闭事项
4. maintenance_due          active 计划的实例到期且无当前行动时建行动并回填实例（P2）
5. monitor_event_confirmed  已确认监控事件兜底补建事项+行动并回写 event.action_id

行动创建统一走 pcw_workitem_service.create_pcw_action（事项轮次分配、档案前置校验、
轮次指纹幂等都由它保证）；本服务负责范围冻结、逐客户 savepoint 隔离、失败补偿
登记与批次计数。事项已存在且有 pending/snoozed 行动时不新建（计数 reused），
已结束事项不被扫描复活（计数 suppressed）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.time import (
    beijing_now,
    beijing_now_aware,
    beijing_today,
    to_beijing_time,
)
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAssignment,
    CustomerConversation,
    CustomerMessage,
    CustomerSyncCursor,
)
from app.customer.pcw_idempotency import canonical_request_hash
from app.customer.pcw_models import (
    CustomerEvaluationItem,
    CustomerEvaluationRun,
    CustomerWorkItem,
    MaintenanceOccurrence,
    MaintenancePlan,
    MonitorEvent,
    ReorderWindow,
    SampleCase,
)
from app.customer.pcw_workitem_service import create_pcw_action, ensure_work_item
from app.customer.workflow_service import ACTION_CHANNELS
from app.whatsapp.models import WhatsAppAccount

logger = logging.getLogger(__name__)

DEFAULT_RULE_VERSION = "pcw_rules_v1"
SCOPE_SCHEMA_VERSION = "pcw_evaluation_scope_v1"
COUNTERS_SCHEMA_VERSION = "pcw_action_counters_v1"
ITEM_WATERMARKS_SCHEMA_VERSION = "pcw_item_watermarks_v1"
CHECKPOINT_SCHEMA_VERSION = "pcw_evaluation_checkpoint_v1"
RUN_KINDS = frozenset({"scheduled", "manual", "dry_run"})

# input_hash 输入清单 schema（pcw_evaluation_input_v1）。只纳入规则评估实际读取的
# 来源侧信号；PCW 自己产出/回填的字段（事项、行动、occurrence.current_action_id、
# window.action_id、event.action_id）一律不进指纹，否则每次评估都会改变输入，
# AI 的 skipped_unchanged 永远不命中。字段：
#   conversation_count   客户会话数（全部状态，绑定/关闭变化也触发重分析）
#   message_max_id       全部会话的最大消息ID（新消息改变指纹）
#   reorder_windows      "id:state:window_from:window_to" 有序列表
#   maintenance          "plan_id:plan_status:occurrence_id:occurrence_date" 有序列表
#   sample_cases         "id:stage:test_planned_date" 有序列表
#   monitor_events       "id:status" 有序列表
INPUT_SCHEMA_VERSION = "pcw_evaluation_input_v1"

INQUIRY_SLA_HOURS = 24
INQUIRY_SLA_URGENT_HOURS = 72
RETRY_DELAY_MINUTES = 30
RUN_LEASE_MINUTES = 30
DUE_HOUR_OF_DAY = 18  # 日期级期限统一按北京时间当天 18:00 到期（规则确定性派生，不是承诺）

PRIORITY_URGENT = "urgent"  # P0
PRIORITY_HIGH = "high"      # P1
PRIORITY_NORMAL = "normal"  # P2

# 行动状态：pending/snoozed 视为"未执行"，评估不重复新建；done/dismissed/cancelled 为终态。
OPEN_ACTION_STATUSES = ("pending", "snoozed")
OPEN_ITEM_STATES = ("open", "awaiting_reply")
CLOSED_ITEM_STATES = ("resolved", "cancelled")


@dataclass(frozen=True)
class _EvalContext:
    customer_id: int
    owner_user_id: int | None
    business_date: date
    now: datetime
    rule_version: str


@dataclass(frozen=True)
class _EmitResult:
    outcome: str  # created / reused / planned / suppressed / skipped
    item: CustomerWorkItem | None
    action: CustomerAction | None


def _iso_bj(value: datetime | None) -> str | None:
    if value is None:
        return None
    return to_beijing_time(value).isoformat(timespec="seconds")


def _new_counters() -> dict:
    return {
        "schema_version": COUNTERS_SCHEMA_VERSION,
        "created": [],
        "would_create": [],
        "reused": 0,
        "suppressed": 0,
        "cancelled": 0,
        "resolved": 0,
        "warnings": 0,
    }


def _freeze_scope(db: Session, customer_ids) -> list[int]:
    """冻结评估范围：active 且当前有有效 primary 归属的客户；customer_ids 只缩小范围。"""
    primary_exists = exists().where(and_(
        CustomerAssignment.customer_id == CustomerAccount.id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ))
    query = db.query(CustomerAccount.id).filter(
        CustomerAccount.record_status == "active",
        primary_exists,
    )
    if customer_ids is not None:
        query = query.filter(CustomerAccount.id.in_([int(cid) for cid in customer_ids]))
    return sorted(int(row.id) for row in query.all())


def _primary_assignment_map(db: Session, customer_ids: list[int]) -> dict[int, CustomerAssignment]:
    if not customer_ids:
        return {}
    rows = db.query(CustomerAssignment).filter(
        CustomerAssignment.customer_id.in_(customer_ids),
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).all()
    return {int(row.customer_id): row for row in rows}


def _input_hash(db: Session, customer_id: int) -> str:
    """本客户评估输入轻量指纹（pcw_evaluation_input_v1，schema 见模块头注释）。"""
    conversation_count = db.query(func.count(CustomerConversation.id)).filter(
        CustomerConversation.customer_id == customer_id,
    ).scalar()
    message_max_id = db.query(func.max(CustomerMessage.id)).join(
        CustomerConversation, CustomerMessage.conversation_id == CustomerConversation.id,
    ).filter(CustomerConversation.customer_id == customer_id).scalar()
    windows = db.query(
        ReorderWindow.id, ReorderWindow.state,
        ReorderWindow.window_from, ReorderWindow.window_to,
    ).filter(ReorderWindow.customer_id == customer_id).order_by(ReorderWindow.id).all()
    maintenance = db.query(
        MaintenancePlan.id, MaintenancePlan.status,
        MaintenanceOccurrence.id, MaintenanceOccurrence.occurrence_date,
    ).join(
        MaintenanceOccurrence, MaintenanceOccurrence.plan_id == MaintenancePlan.id,
    ).filter(MaintenancePlan.customer_id == customer_id).order_by(MaintenanceOccurrence.id).all()
    cases = db.query(
        SampleCase.id, SampleCase.stage, SampleCase.test_planned_date,
    ).filter(SampleCase.customer_id == customer_id).order_by(SampleCase.id).all()
    events = db.query(
        MonitorEvent.id, MonitorEvent.status,
    ).filter(MonitorEvent.customer_id == customer_id).order_by(MonitorEvent.id).all()
    payload = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "customer_id": int(customer_id),
        "conversation_count": int(conversation_count or 0),
        "message_max_id": int(message_max_id or 0),
        "reorder_windows": [
            f"{w.id}:{w.state}:{w.window_from.isoformat()}:{w.window_to.isoformat()}" for w in windows
        ],
        "maintenance": [
            f"{m[0]}:{m[1]}:{m[2]}:{m[3].isoformat()}" for m in maintenance
        ],
        "sample_cases": [
            f"{c.id}:{c.stage}:{c.test_planned_date.isoformat() if c.test_planned_date else '-'}"
            for c in cases
        ],
        "monitor_events": [f"{e.id}:{e.status}" for e in events],
    }
    return canonical_request_hash(payload)


def _run_watermarks(db: Session) -> dict:
    """评估时点各来源已授权同步水位快照（轻量：只取每源最近成功时间与 WhatsApp 最近同步）。"""
    sources: dict[str, datetime | None] = {}
    rows = db.query(CustomerSyncCursor.source_system, CustomerSyncCursor.last_success_at).all()
    for row in rows:
        current = sources.get(row.source_system)
        if row.last_success_at is not None and (current is None or row.last_success_at > current):
            sources[row.source_system] = row.last_success_at
        elif row.source_system not in sources:
            sources[row.source_system] = None
    if db.query(WhatsAppAccount.id).first() is not None:
        sources["whatsapp"] = db.query(func.max(WhatsAppAccount.last_sync_at)).filter(
            WhatsAppAccount.status == "active",
        ).scalar()
    return {
        "schema_version": ITEM_WATERMARKS_SCHEMA_VERSION,
        "sources": {key: (value.isoformat() if value else None) for key, value in sorted(sources.items())},
    }


def _insert_run(
    db: Session, *, business_date: date, rule_version: str, kind: str,
    scope_hash: str, frozen_scope: dict, expected: int, triggered_by, now: datetime,
) -> CustomerEvaluationRun:
    """创建批次行；attempt=同 (date, rule_version, scope_hash, kind) 已有批次数+1，并发冲突重试。"""
    last_exc: IntegrityError | None = None
    for _ in range(3):
        attempt = db.query(func.count(CustomerEvaluationRun.id)).filter(
            CustomerEvaluationRun.business_date == business_date,
            CustomerEvaluationRun.rule_version == rule_version,
            CustomerEvaluationRun.scope_hash == scope_hash,
            CustomerEvaluationRun.run_kind == kind,
        ).scalar() + 1
        run = CustomerEvaluationRun(
            run_uid=str(uuid4()),
            business_date=business_date,
            rule_version=rule_version,
            run_kind=kind,
            attempt=attempt,
            scope_hash=scope_hash,
            frozen_scope_json=frozen_scope,
            status="running",
            expected_count=expected,
            rule_completed=0,
            rule_failed=0,
            ai_completed=0,
            ai_skipped_unchanged=0,
            ai_failed=0,
            checkpoint_json={"schema_version": CHECKPOINT_SCHEMA_VERSION, "processed": 0, "completed": False},
            lease_until=now + timedelta(minutes=RUN_LEASE_MINUTES),
            triggered_by=triggered_by,
            created_at=now,
            updated_at=now,
        )
        try:
            with db.begin_nested():
                db.add(run)
                db.flush()
            return run
        except IntegrityError as exc:
            last_exc = exc
            continue
    raise pcw_errors.conflict(
        "并发创建评估批次冲突，请重试", error_code="RETRY_NEW_TRANSACTION"
    ) from last_exc


def _emit_rule_action(
    db: Session, ctx: _EvalContext, counters: dict, dry_run: bool, *,
    rule: str, key: str, cycle: str, work_type: str, title: str,
    thread_group: str, action_type: str, priority: str, reason: str,
    next_action: str, channel: str | None = None, contact_id: int | None = None,
    due: datetime | None = None, context: dict | None = None,
) -> _EmitResult:
    """按稳定键发射一条规则行动；跨日去重与抑制规则集中在这里。"""
    item = db.query(CustomerWorkItem).filter(
        CustomerWorkItem.business_key == key,
        CustomerWorkItem.business_cycle == cycle,
    ).one_or_none()
    if item is not None and item.state in CLOSED_ITEM_STATES:
        # 已结束事项不被扫描复活；新业务周期必须由来源侧产生新 cycle。
        counters["suppressed"] += 1
        return _EmitResult("suppressed", item, None)
    pending = None
    if item is not None and item.state in OPEN_ITEM_STATES:
        pending = db.query(CustomerAction).filter(
            CustomerAction.work_item_id == item.id,
            CustomerAction.status.in_(OPEN_ACTION_STATUSES),
        ).order_by(CustomerAction.id.desc()).first()
    if pending is not None:
        counters["reused"] += 1
        return _EmitResult("reused", item, pending)
    if ctx.owner_user_id is None:
        counters["warnings"] += 1
        logger.warning(
            "pcw evaluation rule skipped: customer=%s key=%s 无有效主负责人",
            ctx.customer_id, key,
        )
        return _EmitResult("skipped", item, None)
    if dry_run:
        counters["would_create"].append({
            "rule": rule, "business_key": key, "business_cycle": cycle,
            "work_type": work_type, "thread_group": thread_group, "priority": priority,
        })
        return _EmitResult("planned", item, None)
    item = ensure_work_item(
        db,
        customer_id=ctx.customer_id,
        business_key=key,
        business_cycle=cycle,
        work_type=work_type,
        title=title,
        context=context,
    )
    if item.state in CLOSED_ITEM_STATES:
        counters["suppressed"] += 1
        return _EmitResult("suppressed", item, None)
    action = create_pcw_action(
        db,
        work_item=item,
        owner_user_id=ctx.owner_user_id,
        action_type=action_type,
        thread_group=thread_group,
        priority=priority,
        reason=reason,
        next_action=next_action,
        channel=channel,
        contact_id=contact_id,
        business_due_at=due,
        due_provenance="rule" if due is not None else None,
        policy_version=ctx.rule_version,
        source_type="rule",
    )
    counters["created"].append({
        "rule": rule, "business_key": key, "business_cycle": cycle,
        "work_type": work_type, "thread_group": thread_group,
        "priority": priority, "action_id": int(action.id),
    })
    return _EmitResult("created", item, action)


def _rule_inquiry_sla(db: Session, ctx: _EvalContext, counters: dict, dry_run: bool) -> None:
    conversations = db.query(CustomerConversation).filter(
        CustomerConversation.customer_id == ctx.customer_id,
        CustomerConversation.conversation_status == "active",
    ).order_by(CustomerConversation.id).all()
    for conv in conversations:
        last_in = db.query(CustomerMessage).filter(
            CustomerMessage.conversation_id == conv.id,
            CustomerMessage.direction == "in",
        ).order_by(CustomerMessage.sent_at.desc(), CustomerMessage.id.desc()).first()
        if last_in is None:
            continue
        answered = db.query(CustomerMessage.id).filter(
            CustomerMessage.conversation_id == conv.id,
            CustomerMessage.direction == "out",
            or_(
                CustomerMessage.sent_at > last_in.sent_at,
                and_(
                    CustomerMessage.sent_at == last_in.sent_at,
                    CustomerMessage.id > last_in.id,
                ),
            ),
        ).first() is not None
        key = f"inquiry_sla:conv:{conv.id}"
        if answered:
            # 客户已收到回复（可能直接走原渠道）：遗留周期事项解决，不新建任务。
            _resolve_answered_inquiry_items(db, ctx, key, counters, dry_run)
            continue
        age = ctx.now - last_in.sent_at
        if age <= timedelta(hours=INQUIRY_SLA_HOURS):
            continue
        cycle = f"msg:{last_in.id}"
        priority = PRIORITY_URGENT if age > timedelta(hours=INQUIRY_SLA_URGENT_HOURS) else PRIORITY_HIGH
        hours = int(age.total_seconds() // 3600)
        _emit_rule_action(
            db, ctx, counters, dry_run,
            rule="inquiry_sla",
            key=key,
            cycle=cycle,
            work_type="inquiry",
            title=f"询盘未回复超过 SLA：会话 {conv.external_conversation_id}",
            thread_group="new_inquiry",
            action_type="message",
            priority=priority,
            reason=(
                f"会话 {conv.external_conversation_id} 最后一条客户消息已 {hours} 小时未回复"
                f"（SLA {INQUIRY_SLA_HOURS} 小时）。"
            ),
            next_action="查看会话上下文并回复客户最新消息。",
            channel=conv.channel if conv.channel in ACTION_CHANNELS else None,
            contact_id=conv.contact_id,
            due=last_in.sent_at + timedelta(hours=INQUIRY_SLA_HOURS),
            context={
                "conversation_id": int(conv.id),
                "last_inbound_message_id": int(last_in.id),
                "last_inbound_sent_at": last_in.sent_at.isoformat(),
            },
        )


def _resolve_answered_inquiry_items(
    db: Session, ctx: _EvalContext, key: str, counters: dict, dry_run: bool
) -> None:
    """会话已有 outbound 覆盖最后 inbound：该会话所有未关闭周期事项标记解决。

    outbound 在最后一条 inbound 之后，自然覆盖同会话全部更早的未回复周期。
    关联的未执行行动取消（dismissal_reason=answered_off_channel），不伪造完成记录。
    """
    items = db.query(CustomerWorkItem).filter(
        CustomerWorkItem.business_key == key,
        CustomerWorkItem.state.in_(OPEN_ITEM_STATES),
    ).all()
    for item in items:
        counters["resolved"] += 1
        if dry_run:
            continue
        actions = db.query(CustomerAction).filter(
            CustomerAction.work_item_id == item.id,
            CustomerAction.status.in_(OPEN_ACTION_STATUSES),
        ).all()
        for action in actions:
            action.status = "cancelled"
            action.dismissal_reason = "answered_off_channel"
            action.row_version = int(action.row_version) + 1
            action.updated_at = ctx.now
        item.state = "resolved"
        item.resolved_at = ctx.now
        item.resolved_by = None  # 系统解决允许为空
        item.row_version = int(item.row_version) + 1
        item.updated_at = ctx.now


def _rule_sample_feedback(db: Session, ctx: _EvalContext, counters: dict, dry_run: bool) -> None:
    cases = db.query(SampleCase).filter(
        SampleCase.customer_id == ctx.customer_id,
        SampleCase.stage.in_(("delivered", "awaiting_test")),
        SampleCase.test_planned_date.is_not(None),
        SampleCase.test_planned_date <= ctx.business_date,
    ).order_by(SampleCase.id).all()
    for case in cases:
        _emit_rule_action(
            db, ctx, counters, dry_run,
            rule="sample_feedback_due",
            key=f"sample_feedback:case:{case.id}",
            cycle=f"round:{case.feedback_round}",
            work_type="sample",
            title=f"样品反馈跟进：样品事项 #{case.id} 计划测试日已到",
            thread_group="sample",
            action_type="message",
            priority=PRIORITY_HIGH,
            reason=(
                f"样品事项 #{case.id}（反馈第 {case.feedback_round} 轮）计划测试日期 "
                f"{case.test_planned_date.isoformat()} 已到，尚未收到客户反馈。"
            ),
            next_action="联系客户确认样品测试进展并收集反馈。",
            due=datetime.combine(case.test_planned_date, time(DUE_HOUR_OF_DAY)),
            context={"sample_case_id": int(case.id), "feedback_round": int(case.feedback_round)},
        )


def _rule_reorder_window(db: Session, ctx: _EvalContext, counters: dict, dry_run: bool) -> None:
    windows = db.query(ReorderWindow).filter(
        ReorderWindow.customer_id == ctx.customer_id,
    ).order_by(ReorderWindow.id).all()
    for window in windows:
        key = f"reorder:{ctx.customer_id}:{window.product_family}"
        cycle = window.occurrence_key
        if window.state != "open":
            _cancel_covered_window(db, ctx, window, key, cycle, counters, dry_run)
            continue
        if not (window.window_from <= ctx.business_date <= window.window_to):
            continue
        priority = PRIORITY_HIGH if window.confidence == "regular" else PRIORITY_NORMAL
        result = _emit_rule_action(
            db, ctx, counters, dry_run,
            rule="reorder_window",
            key=key,
            cycle=cycle,
            work_type="reorder",
            title=f"复购窗口开启：{window.product_family}",
            thread_group="reorder",
            action_type="message",
            priority=priority,
            reason=(
                f"产品族 {window.product_family} 复购观察窗口 "
                f"{window.window_from.isoformat()}~{window.window_to.isoformat()} 生效中"
                f"（置信 {window.confidence}），适合询问采购计划。"
            ),
            next_action="联系客户询问该产品族的近期采购计划。",
            due=datetime.combine(window.window_to, time(DUE_HOUR_OF_DAY)),
            context={"reorder_window_id": int(window.id), "occurrence_key": window.occurrence_key},
        )
        if not dry_run and result.action is not None and result.item is not None:
            # created 与 reused 都回填窗口关联，保证重放后引用完整
            window.work_item_id = result.item.id
            window.action_id = result.action.id
            window.updated_at = ctx.now


def _cancel_covered_window(
    db: Session, ctx: _EvalContext, window: ReorderWindow,
    key: str, cycle: str, counters: dict, dry_run: bool,
) -> None:
    """窗口已被覆盖/关闭：取消遗留未执行行动并关闭事项。"""
    item = None
    if window.work_item_id is not None:
        item = db.get(CustomerWorkItem, window.work_item_id)
    if item is None:
        item = db.query(CustomerWorkItem).filter(
            CustomerWorkItem.business_key == key,
            CustomerWorkItem.business_cycle == cycle,
        ).one_or_none()
    if item is None or item.state not in OPEN_ITEM_STATES:
        return
    actions = db.query(CustomerAction).filter(
        CustomerAction.work_item_id == item.id,
        CustomerAction.status.in_(OPEN_ACTION_STATUSES),
    ).all()
    if not actions:
        return
    counters["cancelled"] += len(actions)
    if dry_run:
        return
    for action in actions:
        action.status = "cancelled"
        action.dismissal_reason = "window_covered"
        action.row_version = int(action.row_version) + 1
        action.updated_at = ctx.now
    item.state = "cancelled"
    item.row_version = int(item.row_version) + 1
    item.updated_at = ctx.now


def _rule_maintenance_due(db: Session, ctx: _EvalContext, counters: dict, dry_run: bool) -> None:
    rows = db.query(MaintenanceOccurrence, MaintenancePlan).join(
        MaintenancePlan, MaintenancePlan.id == MaintenanceOccurrence.plan_id,
    ).filter(
        MaintenancePlan.customer_id == ctx.customer_id,
        MaintenancePlan.status == "active",
        MaintenanceOccurrence.status.in_(("planned", "due")),
        MaintenanceOccurrence.occurrence_date <= ctx.business_date,
    ).order_by(MaintenanceOccurrence.id).all()
    for occurrence, plan in rows:
        if occurrence.current_action_id is not None:
            current = db.get(CustomerAction, occurrence.current_action_id)
            counters["suppressed"] += 1
            if current is None or current.status not in OPEN_ACTION_STATUSES:
                # 实例仍计划内但指向已终态行动：完成链路未回填，告警等人工/补偿处理。
                counters["warnings"] += 1
                logger.warning(
                    "pcw evaluation maintenance occurrence=%s 指向已终态行动 %s，跳过新建",
                    occurrence.id, occurrence.current_action_id,
                )
            continue
        result = _emit_rule_action(
            db, ctx, counters, dry_run,
            rule="maintenance_due",
            key=f"maintenance:plan:{plan.id}",
            cycle=occurrence.occurrence_key,
            work_type="maintenance",
            title=f"维护计划到期：{plan.title}",
            thread_group="key_account",
            action_type="message",
            priority=PRIORITY_NORMAL,
            reason=(
                f"维护计划「{plan.title}」（{plan.plan_type}）实例 "
                f"{occurrence.occurrence_date.isoformat()} 到期。"
            ),
            next_action="按计划内容联系客户并登记结果。",
            channel=(
                plan.typed_payload.get("channel")
                if isinstance(plan.typed_payload, dict)
                and plan.typed_payload.get("channel") in ACTION_CHANNELS
                else None
            ),
            due=datetime.combine(occurrence.occurrence_date, time(DUE_HOUR_OF_DAY)),
            context={"maintenance_plan_id": int(plan.id), "occurrence_id": int(occurrence.id)},
        )
        if not dry_run and result.action is not None and result.item is not None:
            occurrence.work_item_id = result.item.id
            occurrence.current_action_id = result.action.id
            if occurrence.status == "planned":
                occurrence.status = "due"
            occurrence.occurrence_version = int(occurrence.occurrence_version) + 1
            occurrence.updated_at = ctx.now


def _rule_monitor_confirmed(db: Session, ctx: _EvalContext, counters: dict, dry_run: bool) -> None:
    events = db.query(MonitorEvent).filter(
        MonitorEvent.customer_id == ctx.customer_id,
        MonitorEvent.status == "confirmed",
        MonitorEvent.action_id.is_(None),
    ).order_by(MonitorEvent.id).all()
    for event in events:
        priority = (
            PRIORITY_HIGH
            if event.confidence == "high" or event.event_type == "risk"
            else PRIORITY_NORMAL
        )
        result = _emit_rule_action(
            db, ctx, counters, dry_run,
            rule="monitor_event_confirmed",
            key=f"monitor_event:{event.stable_event_key}",
            cycle="v1",
            work_type="monitor",
            title=f"客户动态：{event.title[:200]}",
            thread_group="key_account",
            action_type="message",
            priority=priority,
            reason=f"已确认的客户监控事件（{event.event_type}）：{event.title[:200]}。",
            next_action="查看事件证据，评估是否联系客户。",
            due=None,
            context={"monitor_event_id": int(event.id), "stable_event_key": event.stable_event_key},
        )
        if not dry_run and result.action is not None:
            # 与监控域的确认同事务逻辑互补：兜底回写，重放安全
            event.action_id = result.action.id
            event.updated_at = ctx.now


def _apply_ai_status(db: Session, item: CustomerEvaluationItem, run: CustomerEvaluationRun, *, ai_enabled: bool) -> None:
    """AI 状态登记（真实增量分析由 PCW-03 的分析任务承担，本服务不调用模型）。"""
    if not ai_enabled:
        item.ai_status = "disabled"
        return
    previous = db.query(CustomerEvaluationItem).filter(
        CustomerEvaluationItem.customer_id == item.customer_id,
        CustomerEvaluationItem.rules_status == "completed",
        CustomerEvaluationItem.run_id != run.id,
    ).order_by(CustomerEvaluationItem.id.desc()).first()
    if previous is not None and previous.input_hash == item.input_hash:
        item.ai_status = "skipped_unchanged"
    else:
        item.ai_status = "pending"


def _evaluate_customer(
    db: Session, *, run: CustomerEvaluationRun, customer_id: int,
    assignment: CustomerAssignment | None, business_date: date, now: datetime,
    dry_run: bool, ai_enabled: bool, watermarks: dict,
) -> CustomerEvaluationItem:
    """单客评估：savepoint 隔离，失败只影响该 item，批次继续。"""
    account = db.get(CustomerAccount, customer_id)
    item = CustomerEvaluationItem(
        run_id=run.id,
        customer_id=customer_id,
        assignment_version=f"primary:{assignment.id}" if assignment is not None else None,
        input_hash=_input_hash(db, customer_id),
        watermarks_json=watermarks,
        rules_status="pending",
        ai_status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    counters = _new_counters()
    try:
        with db.begin_nested():
            if account is None or account.record_status != "active":
                raise pcw_errors.not_found(
                    "客户在评估时点已不是有效状态，跳过本期评估",
                    error_code="CUSTOMER_INACTIVE",
                )
            if account.current_profile_version_id is None:
                # 不为无档案客户建假档案/假画像；进入显式待编译队列，重试可见。
                raise pcw_errors.conflict(
                    "客户档案尚未编译：已进入待编译队列，最小可信档案编译完成后下一评估周期自动生成行动",
                    error_code="PROFILE_NOT_READY",
                )
            ctx = _EvalContext(
                customer_id=customer_id,
                owner_user_id=int(assignment.user_id) if assignment is not None else None,
                business_date=business_date,
                now=now,
                rule_version=run.rule_version,
            )
            _rule_inquiry_sla(db, ctx, counters, dry_run)
            _rule_sample_feedback(db, ctx, counters, dry_run)
            _rule_reorder_window(db, ctx, counters, dry_run)
            _rule_maintenance_due(db, ctx, counters, dry_run)
            _rule_monitor_confirmed(db, ctx, counters, dry_run)
            item.rules_status = "completed"
    except pcw_errors.PcwError as exc:
        item.rules_status = "failed"
        item.error_code = exc.error_code
        item.error_message = exc.message[:500]
        item.next_retry_at = now + timedelta(minutes=RETRY_DELAY_MINUTES)
        if exc.error_code == "PROFILE_NOT_READY":
            logger.info(
                "pcw evaluation customer waiting for profile: run=%s customer=%s",
                run.run_uid, customer_id,
            )
        else:
            logger.warning(
                "pcw evaluation customer failed: run=%s customer=%s code=%s",
                run.run_uid, customer_id, exc.error_code, exc_info=True,
            )
    except Exception:
        item.rules_status = "failed"
        item.error_code = "RULE_EVALUATION_ERROR"
        item.error_message = "规则评估异常，已隔离该客户并安排补偿重试"
        item.next_retry_at = now + timedelta(minutes=RETRY_DELAY_MINUTES)
        logger.warning(
            "pcw evaluation customer failed: run=%s customer=%s",
            run.run_uid, customer_id, exc_info=True,
        )
    if item.rules_status == "completed":
        _apply_ai_status(db, item, run, ai_enabled=ai_enabled)
    elif not ai_enabled:
        item.ai_status = "disabled"
    item.action_counters_json = counters
    item.updated_at = beijing_now()
    db.flush()
    return item


def run_daily_evaluation(
    db: Session,
    *,
    business_date: date | None = None,
    rule_version: str = DEFAULT_RULE_VERSION,
    run_kind: str = "manual",
    triggered_by: int | None = None,
    dry_run: bool = False,
    customer_ids=None,
) -> CustomerEvaluationRun:
    """执行一次每日规则评估，返回批次行（不 commit，由调用方提交事务）。

    - business_date 默认 beijing_today()；dry_run=True 时 run_kind 记为 dry_run，
      只统计 action_counters_json（would_create/suppressed/cancelled 等），
      写操作只限 run/item 行，不创建任何 work item/action。
    - 同日同范围同规则版本重复执行由 attempt 递增区分；事项/行动由稳定键去重。
    """
    business_date = business_date or beijing_today()
    if isinstance(business_date, datetime):
        business_date = business_date.date()
    kind = "dry_run" if dry_run else (run_kind or "manual")
    if kind not in RUN_KINDS:
        raise pcw_errors.bad_request("评估批次类型不合法", error_code="EVALUATION_RUN_KIND_INVALID")
    if not rule_version or len(str(rule_version)) > 32:
        raise pcw_errors.bad_request("规则版本不合法", error_code="EVALUATION_RULE_VERSION_INVALID")
    now = beijing_now()
    scope_ids = _freeze_scope(db, customer_ids)
    scope_payload = {"schema_version": SCOPE_SCHEMA_VERSION, "customer_ids": scope_ids}
    # scope_hash 只含规范客户集合，不含冻结时刻，保证同日同范围重复评估可比对
    scope_hash = canonical_request_hash(scope_payload)
    frozen_scope = {
        **scope_payload,
        "frozen_at": beijing_now_aware().isoformat(timespec="seconds"),
    }
    run = _insert_run(
        db,
        business_date=business_date,
        rule_version=rule_version,
        kind=kind,
        scope_hash=scope_hash,
        frozen_scope=frozen_scope,
        expected=len(scope_ids),
        triggered_by=triggered_by,
        now=now,
    )
    assignments = _primary_assignment_map(db, scope_ids)
    ai_enabled = bool(getattr(get_settings(), "PCW_AI_ANALYSIS_ENABLED", False))
    watermarks = _run_watermarks(db)
    completed = failed = ai_skipped = 0
    try:
        for customer_id in scope_ids:
            item = _evaluate_customer(
                db,
                run=run,
                customer_id=customer_id,
                assignment=assignments.get(customer_id),
                business_date=business_date,
                now=now,
                dry_run=(kind == "dry_run"),
                ai_enabled=ai_enabled,
                watermarks=watermarks,
            )
            if item.rules_status == "completed":
                completed += 1
            else:
                failed += 1
            if item.ai_status == "skipped_unchanged":
                ai_skipped += 1
    except Exception:
        run.status = "failed"
        run.updated_at = beijing_now()
        db.flush()
        logger.exception("pcw evaluation run failed: run=%s", run.run_uid)
        raise
    run.rule_completed = completed
    run.rule_failed = failed
    run.ai_completed = 0  # 真实 AI 增量分析由 PCW-03 分析任务承担
    run.ai_failed = 0
    run.ai_skipped_unchanged = ai_skipped
    run.status = "completed"
    run.lease_until = None
    run.checkpoint_json = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "processed": len(scope_ids),
        "completed": True,
    }
    run.updated_at = beijing_now()
    db.flush()
    logger.info(
        "pcw evaluation run finished: run=%s kind=%s expected=%s rule_completed=%s rule_failed=%s",
        run.run_uid, kind, len(scope_ids), completed, failed,
    )
    return run


def get_evaluation_run(
    db: Session,
    run_uid: str,
    *,
    actor_user_id: int,
    actor_permissions,
) -> dict:
    """批次读模型（api-contracts §3）：冻结范围 + 逐客户状态与失败原因。

    管理员（customer:read_all / customer:admin）看全量；其余按当前有效归属裁剪
    items 与 frozen_scope.customer_ids，不泄漏范围外客户。
    """
    run = db.query(CustomerEvaluationRun).filter(
        CustomerEvaluationRun.run_uid == str(run_uid or ""),
    ).one_or_none()
    if run is None:
        raise pcw_errors.not_found("评估批次不存在或无权访问", error_code="EVALUATION_RUN_NOT_FOUND")
    perms = set(actor_permissions or ())
    full_view = bool(perms & {"customer:read_all", "customer:admin"})
    items = db.query(CustomerEvaluationItem).filter(
        CustomerEvaluationItem.run_id == run.id,
    ).order_by(CustomerEvaluationItem.id).all()
    items_total = len(items)
    if full_view:
        visible_ids = {int(item.customer_id) for item in items}
    elif not items:
        visible_ids = set()
    else:
        rows = db.query(CustomerAssignment.customer_id).filter(
            CustomerAssignment.user_id == int(actor_user_id),
            CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
            CustomerAssignment.customer_id.in_([int(item.customer_id) for item in items]),
        ).all()
        visible_ids = {int(row.customer_id) for row in rows}
    visible_items = [item for item in items if int(item.customer_id) in visible_ids]
    frozen_scope = dict(run.frozen_scope_json or {})
    frozen_scope["customer_ids"] = [
        cid for cid in frozen_scope.get("customer_ids", []) if int(cid) in visible_ids
    ]
    return {
        "run_uid": run.run_uid,
        "business_date": run.business_date.isoformat(),
        "rule_version": run.rule_version,
        "run_kind": run.run_kind,
        "attempt": int(run.attempt),
        "status": run.status,
        "scope_hash": run.scope_hash,
        "expected_count": int(run.expected_count),
        "rule_completed": int(run.rule_completed),
        "rule_failed": int(run.rule_failed),
        "ai_completed": int(run.ai_completed),
        "ai_skipped_unchanged": int(run.ai_skipped_unchanged),
        "ai_failed": int(run.ai_failed),
        "frozen_scope": frozen_scope,
        "triggered_by": run.triggered_by,
        "created_at": _iso_bj(run.created_at),
        "updated_at": _iso_bj(run.updated_at),
        "items": [
            {
                "customer_id": int(item.customer_id),
                "assignment_version": item.assignment_version,
                "input_hash": item.input_hash,
                "watermarks": item.watermarks_json,
                "rules_status": item.rules_status,
                "ai_status": item.ai_status,
                "error_code": item.error_code,
                "error_message": item.error_message,
                "action_counters": item.action_counters_json,
                "next_retry_at": _iso_bj(item.next_retry_at),
            }
            for item in visible_items
        ],
        "items_total": items_total,
        "scope_trimmed": len(visible_items) != items_total,
    }


def run_scheduled_evaluation() -> None:
    """APScheduler 入口：自建 SessionLocal（调度场景允许），异常记录后不扩散给调度器。"""
    if not getattr(get_settings(), "PCW_EVALUATION_ENABLED", False):
        return
    try:
        with SessionLocal() as db:
            run = run_daily_evaluation(db, run_kind="scheduled", triggered_by=None)
            run_uid, status = run.run_uid, run.status
            db.commit()
            logger.info("pcw scheduled evaluation finished: run=%s status=%s", run_uid, status)
    except Exception as exc:
        logger.exception("pcw scheduled evaluation failed")
        print(f"pcw scheduled evaluation failed: {type(exc).__name__}", flush=True)
