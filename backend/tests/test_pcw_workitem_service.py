"""PCW 事项与多轮行动基础服务契约测试。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.models import CustomerAnnotation, CustomerAssignment
from app.customer.pcw_models import CustomerWorkItem, MaintenanceOccurrence, MaintenancePlan
from app.customer.pcw_workitem_service import (
    complete_action_v2,
    create_pcw_action,
    dismiss_action_v2,
    ensure_work_item,
    snooze_action_v2,
)
from tests.test_customer_workflow import _account, _user

NOW = beijing_now().replace(microsecond=0)


def _customer_with_profile(db):
    account, _version = _account(db, code="C-PCW-WI")
    owner = _user(db, 9101)
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
    return account, owner


def _open_item(db, account, **kwargs) -> CustomerWorkItem:
    params = dict(
        customer_id=account.id,
        business_key="inquiry_sla:conv:42",
        business_cycle="msg:1001",
        work_type="inquiry",
        title="回复客户关于发束长度的询问",
    )
    params.update(kwargs)
    return ensure_work_item(db, **params)


def _action(db, account, owner, item, **kwargs):
    params = dict(
        owner_user_id=owner.id,
        action_type="message",
        thread_group="new_inquiry",
        priority="high",
        reason="询盘超过SLA未回复",
        next_action="回复客户长度问题",
        channel="whatsapp",
        business_due_at=NOW + timedelta(hours=4),
    )
    params.update(kwargs)
    return create_pcw_action(db, work_item=item, **params)


def test_ensure_work_item_deduplicates_across_scans(db):
    account, _owner = _customer_with_profile(db)
    first = _open_item(db, account)
    second = _open_item(db, account, title="不同标题不改变事项身份")
    assert first.id == second.id
    assert second.title == "回复客户关于发束长度的询问"


def test_create_pcw_action_allocates_rounds_and_replays(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action1 = _action(db, account, owner, item)
    assert action1.work_item_id == item.id
    assert action1.action_round == 1
    assert action1.original_due_at == action1.business_due_at
    db.commit()

    replay = _action(db, account, owner, item)
    # 同轮次指纹已完成后不复用：轮次已分配，新建 round 2
    assert replay.action_round == 2
    assert replay.parent_action_id == action1.id


def test_create_pcw_action_requires_profile(db):
    from app.customer import models as customer_models

    owner = _user(db, 9102)
    account = customer_models.CustomerAccount(
        customer_code="C-PCW-NOPROFILE",
        display_name="C-PCW-NOPROFILE",
        canonical_company_name="NoProfile LLC",
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
    item = ensure_work_item(
        db, customer_id=account.id, business_key="k", business_cycle="c",
        work_type="manual", title="t",
    )
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _action(db, account, owner, item)
    assert excinfo.value.error_code == "PROFILE_NOT_READY"


def test_complete_action_v2_with_followup_advances_round(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    db.commit()
    item_version = db.get(CustomerWorkItem, item.id).row_version

    result = complete_action_v2(
        db,
        action_id=action.id,
        actor_user_id=owner.id,
        expected_action_version=1,
        expected_work_item_version=item_version,
        work_item_transition="await_reply",
        outcome_code="contacted",
        channel="whatsapp",
        occurred_at=NOW,
        summary="已发送色板，等待客户确认。",
        next_step="确认色板是否接受",
        next_step_due_at=NOW + timedelta(days=2),
        followup_action_type="message",
        followup_channel="whatsapp",
        idempotency_key="complete-test-0001-aaaa",
    )
    db.commit()
    assert result["action"]["status"] == "done"
    assert result["event_state"] == "awaiting_reply"
    followup_id = result["followup_action"]["id"]
    assert followup_id != action.id

    from app.customer.models import CustomerAction

    followup = db.get(CustomerAction, followup_id)
    assert followup.work_item_id == item.id
    assert followup.action_round == 2
    assert followup.parent_action_id == action.id

    # 同键重放：返回同一后续行动，不产生新轮次
    replay = complete_action_v2(
        db,
        action_id=action.id,
        actor_user_id=owner.id,
        expected_action_version=1,
        expected_work_item_version=item_version,
        work_item_transition="await_reply",
        outcome_code="contacted",
        channel="whatsapp",
        occurred_at=NOW,
        summary="已发送色板，等待客户确认。",
        next_step="确认色板是否接受",
        next_step_due_at=NOW + timedelta(days=2),
        followup_action_type="message",
        followup_channel="whatsapp",
        idempotency_key="complete-test-0001-aaaa",
    )
    assert replay["followup_action"]["id"] == followup_id

    # 同键不同内容：409
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        complete_action_v2(
            db,
            action_id=action.id,
            actor_user_id=owner.id,
            expected_action_version=1,
            work_item_transition="await_reply",
            outcome_code="contacted",
            channel="whatsapp",
            occurred_at=NOW,
            summary="不同的摘要",
            next_step="确认色板是否接受",
            next_step_due_at=NOW + timedelta(days=2),
            idempotency_key="complete-test-0001-aaaa",
        )
    assert excinfo.value.error_code == "IDEMPOTENCY_CONFLICT"


def test_complete_action_v2_version_conflict_returns_current(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    db.commit()
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        complete_action_v2(
            db,
            action_id=action.id,
            actor_user_id=owner.id,
            expected_action_version=99,
            work_item_transition="resolve",
            outcome_code="contacted",
            channel="whatsapp",
            occurred_at=NOW,
            summary="x",
        )
    assert excinfo.value.error_code == "ACTION_VERSION_CONFLICT"
    assert excinfo.value.details["current_action_version"] == 1


def test_complete_action_v2_unresolved_requires_next_step(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    db.commit()
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        complete_action_v2(
            db,
            action_id=action.id,
            actor_user_id=owner.id,
            expected_action_version=1,
            work_item_transition="await_reply",
            outcome_code="contacted",
            channel="whatsapp",
            occurred_at=NOW,
            summary="已联系但没安排下一步",
        )
    assert excinfo.value.error_code == "NEXT_STEP_REQUIRED"
    db.rollback()
    from app.customer.models import CustomerAction

    assert db.get(CustomerAction, action.id).status == "pending"
    assert db.get(CustomerWorkItem, item.id).state == "open"


def test_complete_action_v2_resolve_closes_work_item(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    db.commit()
    item_version = db.get(CustomerWorkItem, item.id).row_version
    result = complete_action_v2(
        db,
        action_id=action.id,
        actor_user_id=owner.id,
        expected_action_version=1,
        expected_work_item_version=item_version,
        work_item_transition="resolve",
        outcome_code="meeting_booked",
        channel="offline",
        occurred_at=NOW,
        summary="客户确认问题已解决。",
    )
    assert result["event_state"] == "resolved"
    assert result["followup_action"] is None
    db.commit()
    # 已解决事项下不能再创建行动
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        _action(db, account, owner, db.get(CustomerWorkItem, item.id))
    assert excinfo.value.error_code == "WORK_ITEM_CLOSED"


def test_complete_action_v2_dnc_blocks_entire_transaction(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    dnc = CustomerAnnotation(
        customer_id=account.id,
        annotation_type="do_not_contact",
        content_schema_version="v1",
        content_json={"text": "客户要求停止联系"},
        policy_scope_type="global",
        policy_effective_at=NOW - timedelta(days=1),
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=owner.id,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(dnc)
    db.commit()
    item_version = db.get(CustomerWorkItem, item.id).row_version
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        complete_action_v2(
            db,
            action_id=action.id,
            actor_user_id=owner.id,
            expected_action_version=1,
            expected_work_item_version=item_version,
            work_item_transition="await_reply",
            outcome_code="contacted",
            channel="whatsapp",
            occurred_at=NOW,
            summary="尝试联系",
            next_step="x",
            next_step_due_at=NOW + timedelta(days=1),
        )
    assert excinfo.value.error_code == "CONTACT_RESTRICTED"
    db.rollback()
    from app.customer.models import CustomerAction

    assert db.get(CustomerAction, action.id).status == "pending"


def test_occurrence_linked_completion_requires_and_updates_occurrence(db):
    account, owner = _customer_with_profile(db)
    plan = MaintenancePlan(
        customer_id=account.id,
        plan_type="sample",
        title="样品测试反馈",
        timezone="Asia/Shanghai",
        typed_payload={"schema_version": "pcw_sample_v1"},
        status="active",
        plan_version=1,
        created_by=owner.id,
    )
    db.add(plan)
    db.flush()
    item = _open_item(db, account, business_key="sample:1", business_cycle="round:1")
    action = _action(db, account, owner, item)
    occ = MaintenanceOccurrence(
        plan_id=plan.id,
        occurrence_key="sample:1:round:1:feedback",
        work_item_id=item.id,
        current_action_id=action.id,
        occurrence_date=NOW.date(),
        status="due",
        occurrence_version=1,
    )
    db.add(occ)
    db.commit()

    # 缺少 expected_occurrence_version → 400
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        complete_action_v2(
            db,
            action_id=action.id,
            actor_user_id=owner.id,
            expected_action_version=1,
            expected_work_item_version=item.row_version,
            work_item_transition="await_reply",
            outcome_code="contacted",
            channel="whatsapp",
            occurred_at=NOW,
            summary="客户还未测试，约定下周反馈",
            next_step="跟进测试反馈",
            next_step_due_at=NOW + timedelta(days=3),
        )
    assert excinfo.value.error_code == "OCCURRENCE_VERSION_REQUIRED"
    db.rollback()

    result = complete_action_v2(
        db,
        action_id=action.id,
        actor_user_id=owner.id,
        expected_action_version=1,
        expected_work_item_version=item.row_version,
        expected_occurrence_version=1,
        work_item_transition="await_reply",
        outcome_code="contacted",
        channel="whatsapp",
        occurred_at=NOW,
        summary="客户还未测试，约定下周反馈",
        next_step="跟进测试反馈",
        next_step_due_at=NOW + timedelta(days=3),
    )
    db.commit()
    db.refresh(occ)
    assert occ.current_action_id == result["followup_action"]["id"]
    assert occ.occurrence_date == (NOW + timedelta(days=3)).date()
    assert occ.occurrence_version == 2
    assert occ.status in {"planned", "due"}


def test_snooze_keeps_original_due_and_dismiss_requires_reason(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    db.commit()
    original_due = action.original_due_at

    result = snooze_action_v2(
        db,
        action_id=action.id,
        actor_user_id=owner.id,
        expected_action_version=1,
        snoozed_until=NOW + timedelta(days=1),
    )
    assert result["status"] == "snoozed"
    db.refresh(action)
    assert action.original_due_at == original_due

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        dismiss_action_v2(
            db,
            action_id=action.id,
            actor_user_id=owner.id,
            expected_action_version=2,
            dismissal_reason="",
        )
    assert excinfo.value.error_code == "DISMISS_REASON_REQUIRED"
