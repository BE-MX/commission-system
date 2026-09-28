"""PCW 每日规则评估服务契约测试。"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.time import beijing_now, beijing_today
from app.customer import pcw_errors, pcw_evaluation_service
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAssignment,
    CustomerConversation,
    CustomerMessage,
)
from app.customer.pcw_evaluation_service import (
    get_evaluation_run,
    run_daily_evaluation,
    run_scheduled_evaluation,
)
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
from tests.test_customer_workflow import _account, _source_record, _user

NOW = beijing_now().replace(microsecond=0)
TODAY = beijing_today()
YESTERDAY = TODAY - timedelta(days=1)


def _assign_primary(db, account, owner):
    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=owner.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=owner.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()


def _pcw_customer(db, *, code: str, user_id: int):
    account, _version = _account(db, code=code)
    owner = _user(db, user_id)
    _assign_primary(db, account, owner)
    return account, owner


def _customer_without_profile(db, *, code: str, user_id: int):
    owner = _user(db, user_id)
    account = CustomerAccount(
        customer_code=code,
        display_name=code,
        canonical_company_name=f"{code} LLC",
        entity_type="registered_company",
        identity_status="verified",
        relationship_stage="discovered",
        relationship_stage_changed_at=NOW,
        relationship_stage_reason="test_seed",
        record_status="active",
        identity_confidence=1,
        profile_completeness=0,
        profile_input_seq=0,
        current_profile_version_id=None,
    )
    db.add(account)
    db.flush()
    _assign_primary(db, account, owner)
    return account, owner


def _conversation(db, account, *, external_id: str, channel: str = "whatsapp"):
    row = CustomerConversation(
        customer_id=account.id,
        source_system="whatsapp",
        source_account_key="acc-1",
        external_conversation_id=external_id,
        channel=channel,
        conversation_status="active",
    )
    db.add(row)
    db.flush()
    return row


def _message(db, account, conv, *, external_id: str, direction: str, sent_at, record_id: int):
    source = _source_record(db, account, record_id=record_id)
    row = CustomerMessage(
        conversation_id=conv.id,
        external_message_id=external_id,
        direction=direction,
        sender_type="customer_contact" if direction == "in" else "ark_user",
        content_type="text",
        content_text=f"msg {external_id}",
        attachment_meta_json=[],
        source_record_id=source.id,
        content_hash=f"{record_id + 7:064x}",
        sent_at=sent_at,
        captured_at=sent_at,
    )
    db.add(row)
    db.flush()
    return row


def _sample_case(db, account, owner, *, stage="awaiting_test", planned=TODAY, record_id=97001):
    source = _source_record(db, account, record_id=record_id)
    from app.customer.models import CustomerOrder

    order = CustomerOrder(
        customer_id=account.id,
        source_system="okki",
        source_account_key="tenant-a",
        external_order_id=f"SO-{account.id}-{record_id}",
        order_no=f"SO-{record_id}",
        order_status="completed",
        account_date=TODAY - timedelta(days=10),
        currency="USD",
        amount_original=0,
        amount_usd=0,
        is_valid_business_order=False,
        invalid_reason="sample",
        source_record_id=source.id,
        source_hash=f"{record_id + 13:064x}",
        synced_at=NOW,
    )
    db.add(order)
    db.flush()
    case = SampleCase(
        customer_id=account.id,
        sample_order_id=order.id,
        item_set_hash=f"{record_id + 29:064x}",
        sample_item_ids_json=[1],
        stage=stage,
        feedback_round=1,
        test_planned_date=planned,
        created_by=owner.id,
    )
    db.add(case)
    db.flush()
    return case


def _run_item(db, run, customer_id):
    return db.query(CustomerEvaluationItem).filter_by(
        run_id=run.id, customer_id=customer_id,
    ).one()


def test_repeat_run_same_day_does_not_duplicate(db):
    """同日同范围重复评估：第二次 run 不产生新事项/行动，计数 reused。"""
    account, _owner = _pcw_customer(db, code="C-PCW-DEDUP", user_id=9201)
    conv = _conversation(db, account, external_id="conv-dedup")
    _message(db, account, conv, external_id="m1", direction="in",
             sent_at=NOW - timedelta(hours=30), record_id=91001)

    run1 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    assert run1.status == "completed"
    assert run1.attempt == 1
    item1 = _run_item(db, run1, account.id)
    assert item1.rules_status == "completed"
    assert len(item1.action_counters_json["created"]) == 1
    assert db.query(CustomerAction).count() == 1
    assert db.query(CustomerWorkItem).count() == 1

    run2 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    assert run2.attempt == 2
    assert run2.run_uid != run1.run_uid
    assert run2.scope_hash == run1.scope_hash
    item2 = _run_item(db, run2, account.id)
    assert item2.action_counters_json["created"] == []
    assert item2.action_counters_json["reused"] == 1
    assert db.query(CustomerAction).count() == 1
    assert db.query(CustomerWorkItem).count() == 1


def test_inquiry_sla_cross_day_cycle_and_resolve(db):
    """跨日去重 + 回复后旧周期解决 + 新 inbound 形成新周期新行动。"""
    account, _owner = _pcw_customer(db, code="C-PCW-SLA", user_id=9202)
    conv = _conversation(db, account, external_id="conv-sla")
    inbound1 = _message(db, account, conv, external_id="m1", direction="in",
                        sent_at=NOW - timedelta(hours=50), record_id=91011)
    key = f"inquiry_sla:conv:{conv.id}"

    # 昨天的评估建立了行动
    run1 = run_daily_evaluation(db, business_date=YESTERDAY, customer_ids=[account.id])
    work_item1 = db.query(CustomerWorkItem).filter_by(business_key=key).one()
    assert work_item1.business_cycle == f"msg:{inbound1.id}"
    action1 = db.query(CustomerAction).filter_by(work_item_id=work_item1.id).one()
    assert action1.status == "pending"
    assert action1.priority == "high"
    assert action1.business_due_at == inbound1.sent_at + timedelta(hours=24)

    # 今天复评：同一未回复周期不产生新行动
    run2 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item2 = _run_item(db, run2, account.id)
    assert item2.action_counters_json["reused"] == 1
    assert item2.action_counters_json["created"] == []
    assert db.query(CustomerAction).count() == 1
    db.refresh(action1)
    assert action1.status == "pending"

    # 我方通过原渠道回复后：旧周期事项解决，遗留行动取消，不新建
    _message(db, account, conv, external_id="m2", direction="out",
             sent_at=NOW - timedelta(hours=40), record_id=91012)
    run3 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item3 = _run_item(db, run3, account.id)
    assert item3.action_counters_json["created"] == []
    assert item3.action_counters_json["resolved"] == 1
    db.refresh(work_item1)
    db.refresh(action1)
    assert work_item1.state == "resolved"
    assert action1.status == "cancelled"
    assert action1.dismissal_reason == "answered_off_channel"
    assert db.query(CustomerAction).count() == 1

    # 新的未回复 inbound 形成新周期 → 新事项新行动
    inbound2 = _message(db, account, conv, external_id="m3", direction="in",
                        sent_at=NOW - timedelta(hours=30), record_id=91013)
    run4 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item4 = _run_item(db, run4, account.id)
    assert len(item4.action_counters_json["created"]) == 1
    items = db.query(CustomerWorkItem).filter_by(business_key=key).all()
    assert len(items) == 2
    new_item = db.query(CustomerWorkItem).filter_by(
        business_key=key, business_cycle=f"msg:{inbound2.id}",
    ).one()
    assert new_item.state == "open"
    assert db.query(CustomerAction).count() == 2


def test_inquiry_sla_escalates_to_urgent_after_72h(db):
    account, _owner = _pcw_customer(db, code="C-PCW-P0", user_id=9203)
    conv = _conversation(db, account, external_id="conv-p0")
    _message(db, account, conv, external_id="m1", direction="in",
             sent_at=NOW - timedelta(hours=80), record_id=91021)
    run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    action = db.query(CustomerAction).one()
    assert action.priority == "urgent"


def test_reorder_window_covered_cancels_pending_action(db):
    """窗口覆盖/关闭后：遗留 pending 行动取消（window_covered）且事项关闭，不被扫描复活。"""
    account, _owner = _pcw_customer(db, code="C-PCW-WIN", user_id=9204)
    window = ReorderWindow(
        customer_id=account.id,
        product_family="hair_extensions",
        anchor_batch_key="batch-001",
        occurrence_key="hair_extensions:batch-001:w1",
        sample_refs_json=["batch-001"],
        median_interval_days=30,
        window_from=TODAY - timedelta(days=3),
        window_to=TODAY + timedelta(days=3),
        confidence="regular",
        state="open",
    )
    db.add(window)
    db.flush()

    run1 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item1 = _run_item(db, run1, account.id)
    assert len(item1.action_counters_json["created"]) == 1
    action = db.query(CustomerAction).one()
    assert action.priority == "high"  # regular → P1
    assert action.thread_group == "reorder"
    db.refresh(window)
    assert window.action_id == action.id
    assert window.work_item_id == action.work_item_id

    # 窗口被新采购批次覆盖
    window.state = "covered"
    db.flush()
    run2 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item2 = _run_item(db, run2, account.id)
    assert item2.action_counters_json["cancelled"] == 1
    assert item2.action_counters_json["created"] == []
    db.refresh(action)
    assert action.status == "cancelled"
    assert action.dismissal_reason == "window_covered"
    work_item = db.get(CustomerWorkItem, action.work_item_id)
    assert work_item.state == "cancelled"

    # 再次扫描：已取消任务不复活
    run3 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item3 = _run_item(db, run3, account.id)
    assert item3.action_counters_json["created"] == []
    assert item3.action_counters_json["cancelled"] == 0
    db.refresh(action)
    assert action.status == "cancelled"
    assert db.query(CustomerAction).count() == 1


def test_single_customer_failure_isolated(db):
    """无档案客户：该 item failed/PROFILE_NOT_READY，其他客户正常完成，run 仍 completed。"""
    ok_account, _ok_owner = _pcw_customer(db, code="C-PCW-OK", user_id=9205)
    bad_account, _bad_owner = _customer_without_profile(db, code="C-PCW-NOPROF", user_id=9206)
    conv = _conversation(db, ok_account, external_id="conv-ok")
    _message(db, ok_account, conv, external_id="m1", direction="in",
             sent_at=NOW - timedelta(hours=30), record_id=91031)

    run = run_daily_evaluation(
        db, business_date=TODAY, customer_ids=[ok_account.id, bad_account.id],
    )
    assert run.status == "completed"
    assert run.expected_count == 2
    assert run.rule_completed == 1
    assert run.rule_failed == 1

    bad_item = _run_item(db, run, bad_account.id)
    assert bad_item.rules_status == "failed"
    assert bad_item.error_code == "PROFILE_NOT_READY"
    assert "待编译" in bad_item.error_message
    assert bad_item.next_retry_at is not None
    # 不为无档案客户创建事项/行动
    assert db.query(CustomerWorkItem).filter_by(customer_id=bad_account.id).count() == 0

    ok_item = _run_item(db, run, ok_account.id)
    assert ok_item.rules_status == "completed"
    assert len(ok_item.action_counters_json["created"]) == 1


def test_dry_run_writes_only_run_and_items(db):
    """dry_run：只统计 would_create，不创建任何 work item/action。"""
    account, _owner = _pcw_customer(db, code="C-PCW-DRY", user_id=9207)
    conv = _conversation(db, account, external_id="conv-dry")
    _message(db, account, conv, external_id="m1", direction="in",
             sent_at=NOW - timedelta(hours=30), record_id=91041)

    run = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id], dry_run=True)
    assert run.run_kind == "dry_run"
    assert run.status == "completed"
    item = _run_item(db, run, account.id)
    counters = item.action_counters_json
    assert counters["created"] == []
    assert len(counters["would_create"]) == 1
    assert counters["would_create"][0]["rule"] == "inquiry_sla"
    assert counters["would_create"][0]["priority"] == "high"
    assert db.query(CustomerWorkItem).count() == 0
    assert db.query(CustomerAction).count() == 0


def test_maintenance_due_creates_and_backfills_occurrence(db):
    """到期实例：建行动并回填 current_action_id；复评时已有 pending 行动则抑制。"""
    account, owner = _pcw_customer(db, code="C-PCW-MNT", user_id=9208)
    plan = MaintenancePlan(
        customer_id=account.id,
        plan_type="manual",
        title="季度回访",
        timezone="Asia/Shanghai",
        typed_payload={"scheduled_at": NOW.isoformat(), "purpose": "季度回访", "channel": "whatsapp"},
        status="active",
        plan_version=1,
        created_by=owner.id,
    )
    db.add(plan)
    db.flush()
    occurrence = MaintenanceOccurrence(
        plan_id=plan.id,
        occurrence_key=f"plan:{plan.id}:{TODAY.isoformat()}",
        occurrence_date=TODAY,
        status="planned",
        occurrence_version=1,
    )
    db.add(occurrence)
    db.flush()

    run1 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item1 = _run_item(db, run1, account.id)
    assert len(item1.action_counters_json["created"]) == 1
    action = db.query(CustomerAction).one()
    assert action.thread_group == "key_account"
    assert action.priority == "normal"
    assert action.channel == "whatsapp"
    db.refresh(occurrence)
    assert occurrence.current_action_id == action.id
    assert occurrence.work_item_id == action.work_item_id
    assert occurrence.status == "due"
    assert occurrence.occurrence_version == 2

    run2 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item2 = _run_item(db, run2, account.id)
    assert item2.action_counters_json["suppressed"] == 1
    assert item2.action_counters_json["created"] == []
    assert db.query(CustomerAction).count() == 1


def test_monitor_event_confirmed_backfills_action(db):
    """已确认监控事件兜底建行动并回写 action_id；复评天然幂等（不再命中）。"""
    account, _owner = _pcw_customer(db, code="C-PCW-MON", user_id=9209)
    event = MonitorEvent(
        customer_id=account.id,
        stable_event_key="website:acme.example:2026-09-20",
        event_type="new_product",
        title="官网发布新产品系列",
        status="confirmed",
        confidence="high",
        row_version=1,
    )
    db.add(event)
    db.flush()

    run1 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item1 = _run_item(db, run1, account.id)
    assert len(item1.action_counters_json["created"]) == 1
    action = db.query(CustomerAction).one()
    assert action.priority == "high"  # confidence=high → P1
    assert action.work_item_id is not None
    work_item = db.get(CustomerWorkItem, action.work_item_id)
    assert work_item.business_key == "monitor_event:website:acme.example:2026-09-20"
    assert work_item.business_cycle == "v1"
    db.refresh(event)
    assert event.action_id == action.id

    run2 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item2 = _run_item(db, run2, account.id)
    assert item2.action_counters_json["created"] == []
    assert db.query(CustomerAction).count() == 1


def test_sample_feedback_due_and_future_planned_not_fired(db):
    """样品计划测试日到期建行动；计划日在未来不触发。"""
    account, owner = _pcw_customer(db, code="C-PCW-SMP", user_id=9210)
    due_case = _sample_case(db, account, owner, stage="awaiting_test", planned=TODAY)
    _sample_case(db, account, owner, stage="delivered",
                 planned=TODAY + timedelta(days=3), record_id=97002)

    run1 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item1 = _run_item(db, run1, account.id)
    assert len(item1.action_counters_json["created"]) == 1
    action = db.query(CustomerAction).one()
    assert action.thread_group == "sample"
    assert action.priority == "high"
    work_item = db.get(CustomerWorkItem, action.work_item_id)
    assert work_item.business_key == f"sample_feedback:case:{due_case.id}"
    assert work_item.business_cycle == "round:1"

    run2 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item2 = _run_item(db, run2, account.id)
    assert item2.action_counters_json["reused"] == 1
    assert db.query(CustomerAction).count() == 1


def test_occurrence_due_hits_at_beijing_midnight(db, monkeypatch):
    """北京时间 00:30 评估：occurrence_date=今天 的实例必须命中。

    occurrence_date 与 business_date 均为 date 直接比较，与具体时刻无关；
    pcw 服务只依赖 app.core.time 的 beijing_now/beijing_today（ZoneInfo
    Asia/Shanghai 显式换算），不读服务器本地时区——grep 自查本模块无
    datetime.now/date.today 调用，服务器非东八区不影响业务日期。
    """
    from datetime import date as _date
    from datetime import datetime as _datetime

    account, owner = _pcw_customer(db, code="C-PCW-MID", user_id=9211)
    fake_now = _datetime(2026, 9, 25, 0, 30)  # 北京时间凌晨 00:30
    monkeypatch.setattr(pcw_evaluation_service, "beijing_now", lambda: fake_now)
    monkeypatch.setattr(pcw_evaluation_service, "beijing_today", lambda: fake_now.date())
    plan = MaintenancePlan(
        customer_id=account.id,
        plan_type="manual",
        title="每日巡访",
        timezone="Asia/Shanghai",
        typed_payload={"scheduled_at": fake_now.isoformat(), "purpose": "每日巡访"},
        status="active",
        plan_version=1,
        created_by=owner.id,
    )
    db.add(plan)
    db.flush()
    db.add(MaintenanceOccurrence(
        plan_id=plan.id,
        occurrence_key=f"plan:{plan.id}:2026-09-25",
        occurrence_date=_date(2026, 9, 25),
        status="planned",
        occurrence_version=1,
    ))
    db.flush()

    run = run_daily_evaluation(db)  # business_date 默认取 beijing_today()
    assert run.business_date == _date(2026, 9, 25)
    item = _run_item(db, run, account.id)
    assert len(item.action_counters_json["created"]) == 1


def test_ai_status_disabled_when_flag_off(db, monkeypatch):
    monkeypatch.setattr(
        pcw_evaluation_service, "get_settings",
        lambda: SimpleNamespace(PCW_AI_ANALYSIS_ENABLED=False),
    )
    account, _owner = _pcw_customer(db, code="C-PCW-AI0", user_id=9212)
    run = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item = _run_item(db, run, account.id)
    assert item.ai_status == "disabled"
    assert run.ai_skipped_unchanged == 0


def test_ai_status_pending_then_skipped_unchanged(db, monkeypatch):
    """AI 开启：首评 pending；输入不变复评 skipped_unchanged；输入变化回到 pending。"""
    monkeypatch.setattr(
        pcw_evaluation_service, "get_settings",
        lambda: SimpleNamespace(PCW_AI_ANALYSIS_ENABLED=True),
    )
    account, _owner = _pcw_customer(db, code="C-PCW-AI1", user_id=9213)

    run1 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item1 = _run_item(db, run1, account.id)
    assert item1.ai_status == "pending"

    run2 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item2 = _run_item(db, run2, account.id)
    assert item2.ai_status == "skipped_unchanged"
    assert item2.input_hash == item1.input_hash
    assert run2.ai_skipped_unchanged == 1

    # 输入变化（新消息，未超 SLA 不产生行动但改变输入指纹）→ 回到 pending
    conv = _conversation(db, account, external_id="conv-ai")
    _message(db, account, conv, external_id="m1", direction="in",
             sent_at=NOW, record_id=91051)
    run3 = run_daily_evaluation(db, business_date=TODAY, customer_ids=[account.id])
    item3 = _run_item(db, run3, account.id)
    assert item3.ai_status == "pending"
    assert item3.input_hash != item1.input_hash


def test_run_kind_invalid_rejected(db):
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        run_daily_evaluation(db, run_kind="bogus")
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "EVALUATION_RUN_KIND_INVALID"


def test_get_evaluation_run_trims_to_actor_scope(db):
    """批次读模型：管理员看全量；普通业务员按当前有效归属裁剪 items 与冻结范围。"""
    account_a, owner_a = _pcw_customer(db, code="C-PCW-GA", user_id=9214)
    account_b, _owner_b = _pcw_customer(db, code="C-PCW-GB", user_id=9215)
    run = run_daily_evaluation(
        db, business_date=TODAY, customer_ids=[account_a.id, account_b.id],
    )
    assert run.expected_count == 2

    admin_view = get_evaluation_run(
        db, run.run_uid, actor_user_id=owner_a.id,
        actor_permissions={"customer:read_all"},
    )
    assert admin_view["items_total"] == 2
    assert len(admin_view["items"]) == 2
    assert admin_view["scope_trimmed"] is False
    assert sorted(admin_view["frozen_scope"]["customer_ids"]) == sorted(
        [account_a.id, account_b.id]
    )
    assert admin_view["run_uid"] == run.run_uid
    assert admin_view["business_date"] == TODAY.isoformat()
    assert admin_view["created_at"].endswith("+08:00")

    owner_view = get_evaluation_run(
        db, run.run_uid, actor_user_id=owner_a.id, actor_permissions=set(),
    )
    assert owner_view["items_total"] == 2
    assert len(owner_view["items"]) == 1
    assert owner_view["items"][0]["customer_id"] == account_a.id
    assert owner_view["scope_trimmed"] is True
    assert owner_view["frozen_scope"]["customer_ids"] == [account_a.id]

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        get_evaluation_run(db, "no-such-run", actor_user_id=owner_a.id, actor_permissions=set())
    assert excinfo.value.status_code == 404


def test_run_scheduled_evaluation_gate_and_wiring(db, monkeypatch):
    """调度入口：开关关闭直接返回；开启时自建会话并以 run_kind=scheduled 调用；异常被吞但记录。"""
    monkeypatch.setattr(
        pcw_evaluation_service, "get_settings",
        lambda: SimpleNamespace(PCW_EVALUATION_ENABLED=False),
    )
    assert run_scheduled_evaluation() is None

    calls = {}

    class _FakeSession:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        pcw_evaluation_service, "get_settings",
        lambda: SimpleNamespace(PCW_EVALUATION_ENABLED=True),
    )
    monkeypatch.setattr(pcw_evaluation_service, "SessionLocal", lambda: _FakeSession())

    def _fake_run(db_arg, *, run_kind, triggered_by=None, **kwargs):
        calls["run_kind"] = run_kind
        calls["triggered_by"] = triggered_by
        return SimpleNamespace(run_uid="u-1", status="completed")

    monkeypatch.setattr(pcw_evaluation_service, "run_daily_evaluation", _fake_run)
    run_scheduled_evaluation()
    assert calls == {"run_kind": "scheduled", "triggered_by": None}

    def _boom(db_arg, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pcw_evaluation_service, "run_daily_evaluation", _boom)
    # 异常不扩散给调度器（logger.exception + print 已记录）
    assert run_scheduled_evaluation() is None
