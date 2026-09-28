"""私海客户工作台（PCW）：工作台概览读模型。

api-contracts.md 第 5 节读模型；development-spec.md 第 1 节：
customer_scope（primary/collaborator/authorized，客户维度）与旧 action_scope
（mine/visible，行动执行人维度）正交，旧参数语义不变。规则扫描覆盖率（scans）
与来源同步水位（watermarks）分开呈现；水位取来源最近成功同步时间，不以
查询时刻冒充同步时间。

只读服务：不做任何写操作。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import false, func
from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_now_aware, beijing_today, to_beijing_time
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAssignment,
    CustomerSyncCursor,
)
from app.customer.pcw_models import CustomerEvaluationRun, ReorderWindow
from app.whatsapp.models import WhatsAppAccount

CUSTOMER_SCOPES = frozenset({"primary", "collaborator", "authorized"})
ACTION_SCOPES = frozenset({"mine", "visible"})

# 来源水位超过 48 小时未推进视为 stale；无成功记录为 unknown
WATERMARK_STALE_AFTER = timedelta(hours=48)

# 同步游标处于这两个状态视为存在同步缺口
CURSOR_GAP_STATUSES = frozenset({"degraded", "failed"})


def _iso_bj(value: datetime | None) -> str | None:
    if value is None:
        return None
    return to_beijing_time(value).isoformat(timespec="seconds")


def _scope_customer_ids(
    db: Session, *, actor_user_id: int, perms: set, customer_scope: str
) -> list[int]:
    """解析客户范围：authorized 且有 customer:read_all 时为全部 active 客户。"""
    if customer_scope == "authorized" and "customer:read_all" in perms:
        rows = db.query(CustomerAccount.id).filter(
            CustomerAccount.record_status == "active",
        ).all()
        return sorted(int(row.id) for row in rows)
    roles = {
        "primary": ("primary",),
        "collaborator": ("collaborator",),
        "authorized": ("primary", "collaborator"),
    }[customer_scope]
    rows = db.query(CustomerAssignment.customer_id).join(
        CustomerAccount, CustomerAccount.id == CustomerAssignment.customer_id,
    ).filter(
        CustomerAssignment.user_id == actor_user_id,
        CustomerAssignment.assignment_role.in_(roles),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
        CustomerAccount.record_status == "active",
    ).distinct().all()
    return sorted(int(row.customer_id) for row in rows)


def _watermark_entry(
    source: str, synced_through: datetime | None, gap_count: int, now: datetime
) -> dict:
    if synced_through is None:
        status = "unknown"
    elif now - synced_through > WATERMARK_STALE_AFTER:
        status = "stale"
    else:
        status = "fresh"
    return {
        "source": source,
        "status": status,
        "synced_through": _iso_bj(synced_through),
        "gap_count": int(gap_count),
    }


def _collect_watermarks(db: Session, now: datetime) -> list[dict]:
    """按来源列出水位：CustomerSyncCursor 各来源最近成功游标 + WhatsApp 账号最近同步。

    gap_count：该来源处于 degraded/failed 的游标数；WhatsApp 为活跃账号中水位
    缺失或已 stale 的账号数。
    """
    entries: list[dict] = []
    by_source: dict[str, dict] = {}
    rows = db.query(
        CustomerSyncCursor.source_system,
        CustomerSyncCursor.last_success_at,
        CustomerSyncCursor.sync_status,
    ).all()
    for row in rows:
        slot = by_source.setdefault(row.source_system, {"synced": None, "gaps": 0})
        if row.last_success_at is not None and (
            slot["synced"] is None or row.last_success_at > slot["synced"]
        ):
            slot["synced"] = row.last_success_at
        if row.sync_status in CURSOR_GAP_STATUSES:
            slot["gaps"] += 1
    for source, slot in by_source.items():
        entries.append(_watermark_entry(source, slot["synced"], slot["gaps"], now))
    wa_accounts = db.query(
        WhatsAppAccount.status, WhatsAppAccount.last_sync_at,
    ).filter(WhatsAppAccount.status != "revoked").all()
    if wa_accounts:
        active_syncs = [
            account.last_sync_at
            for account in wa_accounts
            if account.status == "active" and account.last_sync_at is not None
        ]
        synced = max(active_syncs) if active_syncs else None
        gaps = sum(
            1
            for account in wa_accounts
            if account.status == "active"
            and (
                account.last_sync_at is None
                or now - account.last_sync_at > WATERMARK_STALE_AFTER
            )
        )
        entries.append(_watermark_entry("whatsapp", synced, gaps, now))
    entries.sort(key=lambda entry: entry["source"])
    return entries


def _latest_run_scans(db: Session, on_date: date) -> dict | None:
    """on_date 当天最新一个批次（attempt 最大）的规则/AI 计数；无批次返回 None。"""
    run = db.query(CustomerEvaluationRun).filter(
        CustomerEvaluationRun.business_date == on_date,
    ).order_by(CustomerEvaluationRun.id.desc()).first()
    if run is None:
        return None
    return {
        "expected": int(run.expected_count),
        "rule_completed": int(run.rule_completed),
        "rule_failed": int(run.rule_failed),
        "ai_completed": int(run.ai_completed),
        "ai_skipped_unchanged": int(run.ai_skipped_unchanged),
        "ai_failed": int(run.ai_failed),
    }


def get_workbench_overview(
    db: Session,
    *,
    actor_user_id: int,
    actor_permissions,
    customer_scope: str = "primary",
    action_scope: str = "mine",
    on_date: date | None = None,
) -> dict:
    """工作台第一屏概览（api-contracts §5 读模型键）。只读，无写操作。

    - customers_total：customer_scope 范围内去重客户数，与列表口径一致；
    - pending_actions：范围内 status=pending 行动数，action_scope=mine 只看
      owner_user_id=actor，visible 看范围内全部；
    - overdue_actions：pending 且 COALESCE(business_due_at, due_at) < 当前北京时间；
      snoozed_until 不影响逾期判定（snoozed 行动本身不计入 pending）；
    - reorder_window_customers：范围内有 open 窗口覆盖 on_date 的去重客户数。
    """
    if customer_scope not in CUSTOMER_SCOPES:
        raise pcw_errors.bad_request(
            "customer_scope 不合法",
            error_code="CUSTOMER_SCOPE_INVALID",
            details={"allowed": sorted(CUSTOMER_SCOPES)},
        )
    if action_scope not in ACTION_SCOPES:
        raise pcw_errors.bad_request(
            "action_scope 不合法",
            error_code="ACTION_SCOPE_INVALID",
            details={"allowed": sorted(ACTION_SCOPES)},
        )
    perms = set(actor_permissions or ())
    now = beijing_now()
    on_date = on_date or beijing_today()
    customer_ids = _scope_customer_ids(
        db, actor_user_id=int(actor_user_id), perms=perms, customer_scope=customer_scope
    )

    pending_query = db.query(CustomerAction).filter(CustomerAction.status == "pending")
    if customer_ids:
        pending_query = pending_query.filter(CustomerAction.customer_id.in_(customer_ids))
    else:
        pending_query = pending_query.filter(false())
    if action_scope == "mine":
        pending_query = pending_query.filter(CustomerAction.owner_user_id == int(actor_user_id))
    pending_actions = pending_query.count()
    affected_customers = pending_query.with_entities(
        func.count(func.distinct(CustomerAction.customer_id))
    ).scalar()
    overdue_actions = pending_query.filter(
        func.coalesce(CustomerAction.business_due_at, CustomerAction.due_at) < now
    ).count()

    if customer_ids:
        reorder_window_customers = db.query(
            func.count(func.distinct(ReorderWindow.customer_id))
        ).filter(
            ReorderWindow.customer_id.in_(customer_ids),
            ReorderWindow.state == "open",
            ReorderWindow.window_from <= on_date,
            ReorderWindow.window_to >= on_date,
        ).scalar()
    else:
        reorder_window_customers = 0

    return {
        "generated_at": beijing_now_aware().isoformat(timespec="seconds"),
        "customer_scope": customer_scope,
        "customers_total": len(customer_ids),
        "pending_actions": int(pending_actions),
        "affected_customers": int(affected_customers or 0),
        "overdue_actions": int(overdue_actions),
        "reorder_window_customers": int(reorder_window_customers or 0),
        "scans": _latest_run_scans(db, on_date),
        "watermarks": _collect_watermarks(db, now),
    }
