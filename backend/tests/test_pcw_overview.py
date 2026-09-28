"""PCW 工作台概览读模型测试。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.time import beijing_now, beijing_today
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAction,
    CustomerAssignment,
    CustomerSyncCursor,
)
from app.customer.pcw_evaluation_service import run_daily_evaluation
from app.customer.pcw_models import ReorderWindow
from app.customer.pcw_overview_service import get_workbench_overview
from app.whatsapp.models import WhatsAppAccount
from tests.test_customer_workflow import _account, _user

NOW = beijing_now().replace(microsecond=0)
TODAY = beijing_today()
YESTERDAY = TODAY - timedelta(days=1)


def _assign(db, account, user, role):
    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=user.id,
        assignment_role=role,
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=user.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()


def _raw_action(db, account, owner_id, seq, *, status="pending",
                business_due_at=None, due_at=None, snoozed_until=None):
    row = CustomerAction(
        customer_id=account.id,
        owner_user_id=owner_id,
        action_type="message",
        thread_group="new_inquiry",
        priority="high",
        reason="测试行动",
        next_action="跟进客户",
        action_date=(business_due_at or due_at or NOW).date(),
        status=status,
        snoozed_until=snoozed_until,
        feedback_json={},
        source_event_ids=[],
        evidence_fact_ids=[],
        profile_version_id=account.current_profile_version_id,
        source_type="rule",
        policy_version="pcw_rules_v1",
        action_fingerprint=f"{seq:064x}",
        evidence_status="valid",
        generated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        original_due_at=business_due_at or due_at,
        business_due_at=business_due_at,
        due_at=due_at,
    )
    db.add(row)
    db.flush()
    return row


def test_customer_scope_and_action_scope_counts(db):
    """primary/collaborator/authorized 三范围 × mine/visible 两口径计数正确。"""
    user_a = _user(db, 9601)
    user_b = _user(db, 9602)
    user_c = _user(db, 9603)
    c1, _ = _account(db, code="C-OV-1")
    c2, _ = _account(db, code="C-OV-2")
    c3, _ = _account(db, code="C-OV-3")
    _assign(db, c1, user_a, "primary")
    _assign(db, c1, user_b, "collaborator")
    _assign(db, c2, user_b, "primary")
    # c3 无有效归属（公海）
    _raw_action(db, c1, user_a.id, 1)
    _raw_action(db, c1, user_b.id, 2)
    _raw_action(db, c2, user_b.id, 3)
    _raw_action(db, c3, user_a.id, 4)

    overview = get_workbench_overview(
        db, actor_user_id=user_a.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    assert overview["customers_total"] == 1
    assert overview["pending_actions"] == 1
    assert overview["affected_customers"] == 1
    assert overview["generated_at"].endswith("+08:00")

    overview = get_workbench_overview(
        db, actor_user_id=user_a.id, actor_permissions=set(),
        customer_scope="primary", action_scope="visible",
    )
    assert overview["customers_total"] == 1
    assert overview["pending_actions"] == 2  # c1 上 A 和 B 的行动都可见
    assert overview["affected_customers"] == 1

    overview = get_workbench_overview(
        db, actor_user_id=user_b.id, actor_permissions=set(),
        customer_scope="collaborator", action_scope="mine",
    )
    assert overview["customers_total"] == 1
    assert overview["pending_actions"] == 1

    overview = get_workbench_overview(
        db, actor_user_id=user_b.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    assert overview["customers_total"] == 1
    assert overview["pending_actions"] == 1

    # authorized 且有 customer:read_all → 全部 active 客户（含公海 c3）
    overview = get_workbench_overview(
        db, actor_user_id=user_c.id, actor_permissions={"customer:read_all"},
        customer_scope="authorized", action_scope="visible",
    )
    assert overview["customers_total"] == 3
    assert overview["pending_actions"] == 4
    assert overview["affected_customers"] == 3

    overview = get_workbench_overview(
        db, actor_user_id=user_c.id, actor_permissions={"customer:read_all"},
        customer_scope="authorized", action_scope="mine",
    )
    assert overview["customers_total"] == 3
    assert overview["pending_actions"] == 0
    assert overview["affected_customers"] == 0

    # authorized 但无 read_all → 退化为本人归属范围（C 无归属）
    overview = get_workbench_overview(
        db, actor_user_id=user_c.id, actor_permissions=set(),
        customer_scope="authorized", action_scope="visible",
    )
    assert overview["customers_total"] == 0
    assert overview["pending_actions"] == 0


def test_invalid_scope_values_rejected(db):
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        get_workbench_overview(
            db, actor_user_id=1, actor_permissions=set(), customer_scope="everything",
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "CUSTOMER_SCOPE_INVALID"

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        get_workbench_overview(
            db, actor_user_id=1, actor_permissions=set(), action_scope="all",
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "ACTION_SCOPE_INVALID"


def test_overdue_uses_business_due_and_ignores_snoozed_until(db):
    """逾期判定：COALESCE(business_due_at, due_at) < now；snoozed_until 不影响。"""
    user = _user(db, 9610)
    account, _ = _account(db, code="C-OV-DUE")
    _assign(db, account, user, "primary")
    _raw_action(db, account, user.id, 11, business_due_at=NOW - timedelta(hours=2))
    # business_due_at 为空时回退 due_at
    _raw_action(db, account, user.id, 12, due_at=NOW - timedelta(hours=3))
    # business_due_at 优先于 due_at：合法改约后不再逾期
    _raw_action(db, account, user.id, 13,
                business_due_at=NOW + timedelta(days=2), due_at=NOW - timedelta(days=3))
    # snoozed 行动不计入 pending/overdue，即使原期限已过
    _raw_action(db, account, user.id, 14, status="snoozed",
                business_due_at=NOW - timedelta(hours=5),
                snoozed_until=NOW + timedelta(days=1))

    overview = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    assert overview["pending_actions"] == 3
    assert overview["overdue_actions"] == 2


def test_watermarks_fresh_stale_unknown_and_gaps(db):
    """水位：>48h 为 stale；无成功记录为 unknown；gap_count 统计异常游标/掉线账号。"""
    user = _user(db, 9620)
    account, _ = _account(db, code="C-OV-WM")
    _assign(db, account, user, "primary")
    db.add(CustomerSyncCursor(
        source_system="okki", resource_type="orders", scope_key="default",
        sync_status="idle", generation=1, last_counts_json={},
        last_success_at=NOW - timedelta(hours=72),
    ))
    db.add(CustomerSyncCursor(
        source_system="okki", resource_type="messages", scope_key="default",
        sync_status="degraded", generation=1, last_counts_json={},
        last_success_at=NOW - timedelta(hours=70),
    ))
    db.add(CustomerSyncCursor(
        source_system="alibaba", resource_type="customers", scope_key="default",
        sync_status="idle", generation=1, last_counts_json={},
        last_success_at=NOW - timedelta(hours=1),
    ))
    db.add(CustomerSyncCursor(
        source_system="website", resource_type="pages", scope_key="default",
        sync_status="failed", generation=1, last_counts_json={},
        last_success_at=None,
    ))
    db.add(WhatsAppAccount(
        account_uid="wa-1", ark_user_id=user.id, status="active",
        last_sync_at=NOW - timedelta(hours=50),
    ))
    db.add(WhatsAppAccount(
        account_uid="wa-2", ark_user_id=user.id, status="active",
        last_sync_at=NOW - timedelta(hours=1),
    ))
    db.flush()

    overview = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    watermarks = {entry["source"]: entry for entry in overview["watermarks"]}
    assert watermarks["okki"]["status"] == "stale"
    assert watermarks["okki"]["gap_count"] == 1  # degraded 游标
    assert watermarks["alibaba"]["status"] == "fresh"
    assert watermarks["alibaba"]["gap_count"] == 0
    assert watermarks["website"]["status"] == "unknown"
    assert watermarks["website"]["synced_through"] is None
    assert watermarks["website"]["gap_count"] == 1  # failed 游标
    # whatsapp 取活跃账号最近同步的最大值 → fresh；50h 未同步的账号计入缺口
    assert watermarks["whatsapp"]["status"] == "fresh"
    assert watermarks["whatsapp"]["gap_count"] == 1
    assert watermarks["okki"]["synced_through"].endswith("+08:00")


def test_scans_latest_run_of_the_day(db):
    """scans 取 on_date 当天最新一个批次；无批次为 None。"""
    user = _user(db, 9630)
    account, _ = _account(db, code="C-OV-SCAN")
    _assign(db, account, user, "primary")

    overview = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    assert overview["scans"] is None

    run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    overview = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    assert overview["scans"]["expected"] == 1
    assert overview["scans"]["rule_completed"] == 1
    assert overview["scans"]["rule_failed"] == 0
    assert overview["scans"]["ai_completed"] == 0

    # 同日更新的批次（空范围）覆盖旧批次
    run_daily_evaluation(db, business_date=TODAY, customer_ids=[])
    overview = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    assert overview["scans"]["expected"] == 0

    overview = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine", on_date=YESTERDAY,
    )
    assert overview["scans"] is None


def test_reorder_window_customers_counts_open_covering_only(db):
    """reorder_window_customers：范围内 open 且窗口覆盖 on_date 的去重客户数。"""
    user = _user(db, 9640)
    c1, _ = _account(db, code="C-OV-RW1")
    c2, _ = _account(db, code="C-OV-RW2")
    _assign(db, c1, user, "primary")
    _assign(db, c2, user, "primary")
    db.add(ReorderWindow(
        customer_id=c1.id, product_family="hair_extensions",
        anchor_batch_key="b1", occurrence_key="hair_extensions:b1:w1",
        sample_refs_json=["b1"], median_interval_days=30,
        window_from=TODAY - timedelta(days=2), window_to=TODAY + timedelta(days=2),
        confidence="regular", state="open",
    ))
    db.add(ReorderWindow(
        customer_id=c2.id, product_family="hair_wig",
        anchor_batch_key="b2", occurrence_key="hair_wig:b2:w1",
        sample_refs_json=["b2"], median_interval_days=30,
        window_from=TODAY - timedelta(days=2), window_to=TODAY + timedelta(days=2),
        confidence="regular", state="covered",
    ))
    db.add(ReorderWindow(
        customer_id=c2.id, product_family="hair_bundle",
        anchor_batch_key="b3", occurrence_key="hair_bundle:b3:w1",
        sample_refs_json=["b3"], median_interval_days=30,
        window_from=TODAY + timedelta(days=10), window_to=TODAY + timedelta(days=20),
        confidence="regular", state="open",
    ))
    db.flush()

    overview = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
    )
    # c2 的 covered 窗口与未来窗口都不计数
    assert overview["reorder_window_customers"] == 1

    future = get_workbench_overview(
        db, actor_user_id=user.id, actor_permissions=set(),
        customer_scope="primary", action_scope="mine",
        on_date=TODAY + timedelta(days=15),
    )
    assert future["reorder_window_customers"] == 1
