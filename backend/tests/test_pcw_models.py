"""私海客户工作台（PCW）模型骨架冒烟测试。"""

from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.customer.models import CustomerAction
from app.customer.pcw_models import CustomerEvaluationRun, CustomerWorkItem
from tests.test_customer_workflow import _account, _user

NOW = datetime(2026, 9, 24, 9, 0)


def test_work_item_business_key_cycle_unique(db):
    account, _profile = _account(db, code="C-PCW-WI")
    db.add(CustomerWorkItem(
        customer_id=account.id, business_key="inquiry:msg-1", business_cycle="2026-09",
        work_type="inquiry", title="官网询盘跟进",
    ))
    db.flush()
    db.add(CustomerWorkItem(
        customer_id=account.id, business_key="inquiry:msg-1", business_cycle="2026-09",
        work_type="inquiry", title="重复事项",
    ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_evaluation_run_attempt_unique(db):
    base = dict(
        business_date=date(2026, 9, 24), rule_version="pcw_rules_v1", run_kind="scheduled",
        attempt=1, scope_hash="0" * 64, frozen_scope_json={"customer_ids": [1]},
    )
    db.add(CustomerEvaluationRun(run_uid=str(uuid4()), **base))
    db.flush()
    db.add(CustomerEvaluationRun(run_uid=str(uuid4()), **base))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_action_pcw_extension_defaults(db):
    _user(db, 1)
    account, profile = _account(db, code="C-PCW-ACT")
    row = CustomerAction(
        customer_id=account.id, owner_user_id=1, profile_version_id=profile.id,
        action_type="email", thread_group="public_pool",
        priority="high", reason="样品已签收", next_action="确认测试安排",
        action_date=NOW.date(), status="pending", policy_version="pcw-test",
        source_type="manual", source_event_ids=[], evidence_fact_ids=[], feedback_json={},
        action_fingerprint="ab" * 32, evidence_status="valid", generated_at=NOW,
    )
    db.add(row)
    db.flush()
    assert row.work_item_id is None
    assert row.action_round is None
    assert row.parent_action_id is None
    assert row.original_due_at is None
    assert row.business_due_at is None
    assert row.due_provenance is None
    assert row.row_version == 1
