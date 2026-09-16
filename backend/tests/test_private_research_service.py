"""私海客户完整背调发起与分级导出的服务级契约测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.auth.models import ArkUser
from app.customer.models import (
    CustomerAccount,
    CustomerAnnotation,
    CustomerAssignment,
    CustomerOrder,
    CustomerOrderItem,
    CustomerResearchTask,
    CustomerTargetMatch,
)
from app.sales_automation import private_research_service, service
from app.sales_automation.models import AcquisitionProfile
from tests.test_customer_workflow import _source_record
from tests.test_public_pool_research import _account

NOW = datetime(2026, 9, 16, 9, 0)


def _sales(db, user_id: int, username: str) -> ArkUser:
    user = ArkUser(
        id=user_id,
        username=username,
        password_hash="test-only",
        real_name=f"业务员{username}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _assign(db, customer_id: int, user_id: int, *, role: str = "primary", status: str = "active") -> CustomerAssignment:
    row = CustomerAssignment(
        customer_id=customer_id,
        user_id=user_id,
        assignment_role=role,
        assignment_status=status,
        assignment_source="admin_assign",
        effective_from=NOW - timedelta(days=30),
        effective_to=None if status == "active" else NOW - timedelta(days=1),
    )
    db.add(row)
    db.flush()
    return row


def _order(db, account: CustomerAccount, *, external_id: str, amount: str, days: int = 10,
           products: tuple[str, ...] = ("Genius Weft",)) -> CustomerOrder:
    source = _source_record(db, account, record_id=account.id * 1000 + sum(map(ord, external_id)) % 900)
    order = CustomerOrder(
        customer_id=account.id,
        source_system="okki",
        source_account_key="test",
        external_order_id=external_id,
        order_no=f"SO-{external_id}",
        account_date=(NOW - timedelta(days=days)).date(),
        amount_usd=amount,
        is_valid_business_order=True,
        source_record_id=source.id,
        source_hash=f"{account.id:064x}",
        synced_at=NOW,
    )
    db.add(order)
    db.flush()
    for index, product in enumerate(products):
        db.add(CustomerOrderItem(
            order_id=order.id,
            product_name=product,
            product_family=f"family-{product}",
            item_type="bulk",
            source_record_id=source.id,
            item_fingerprint=f"{order.id}-{index}".rjust(64, "0"),
        ))
    db.flush()
    return order


def _create(db, owners, **kwargs) -> dict:
    return private_research_service.create_private_research_tasks(
        db,
        owner_ids=owners,
        run_tag=kwargs.pop("run_tag", "test-run"),
        operator_id=kwargs.pop("operator_id", 1),
        **kwargs,
    )


def test_create_tasks_only_for_primary_private_customers(db):
    _sales(db, 1, "alice")
    _sales(db, 2, "bob")
    own = _account(db, "CUS-OWN")
    own_with_orders = _account(db, "CUS-ORDERS")
    _order(db, own_with_orders, external_id="o1", amount="1200", products=("Genius Weft", "Tape In"))
    collaborator_only = _account(db, "CUS-COLLAB")
    ended = _account(db, "CUS-ENDED")
    other_owner = _account(db, "CUS-BOB")
    _assign(db, own.id, 1)
    _assign(db, own_with_orders.id, 1)
    _assign(db, collaborator_only.id, 1, role="collaborator")
    _assign(db, ended.id, 1, status="ended")
    _assign(db, other_owner.id, 2)

    summary = _create(db, [1])

    assert summary["candidate_count"] == 2
    assert summary["created"] == 2
    assert summary["reused"] == 0
    customer_ids = {task["customer_id"] for task in summary["tasks"]}
    assert customer_ids == {own.id, own_with_orders.id}
    tasks = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.task_type == private_research_service.TASK_TYPE,
    ).all()
    assert len(tasks) == 2
    for task in tasks:
        assert task.task_status == "pending"
        assert task.source_ref_type == "manual"
        assert task.source_ref_id == "test-run"
        assert task.research_policy_version == private_research_service.POLICY_VERSION
        assert task.tier == "T3"
        assert task.input_snapshot["trigger"] == "manual_private_research"
        assert task.input_snapshot["owner_user_id"] == 1


def test_commerce_snapshot_freezes_order_and_product_context(db):
    _sales(db, 1, "alice")
    account = _account(db, "CUS-COMMERCE")
    _assign(db, account.id, 1)
    _order(db, account, external_id="old", amount="300", days=40, products=("Tape In",))
    _order(db, account, external_id="new", amount="900", days=5, products=("Genius Weft",))

    _create(db, [1])

    task = db.query(CustomerResearchTask).filter_by(task_type="full_research").one()
    snapshot = task.input_snapshot["commerce_snapshot"]
    assert snapshot["has_valid_order"] is True
    assert snapshot["valid_order_count"] == 2
    assert snapshot["valid_order_amount_usd"] == "1200.00"
    assert snapshot["last_order_at"] == (NOW - timedelta(days=5)).date().isoformat()
    assert snapshot["recent_orders"][0]["order_no"] == "SO-new"
    families = {row["product_family"] for row in snapshot["top_product_families"]}
    assert families == {"family-Genius Weft", "family-Tape In"}
    assert snapshot["item_type_counts"]["bulk"] == 2


def test_tier_comes_from_current_target_match(db):
    _sales(db, 1, "alice")
    account = _account(db, "CUS-TIER")
    _assign(db, account.id, 1)
    profile = AcquisitionProfile(
        profile_key="tier-test",
        company_name="LeShine",
        products=["hair"],
        advantages=[],
        target_countries=["US"],
        target_industries=["hair"],
        target_roles=["buyer"],
        exclusions=[],
        policy_version="v1",
        policy_json={"thresholds": {}, "weights": {}, "research_rules": {}, "claim_rules": {}},
        policy_snapshot_hash="a" * 64,
        policy_applied_at=NOW,
    )
    db.add(profile)
    db.flush()
    db.add(CustomerTargetMatch(
        customer_id=account.id,
        target_profile_id=profile.id,
        policy_version="v1",
        match_score=85,
        score_reasons=[],
        match_status="qualified",
        evidence_fact_ids=[],
        is_current=True,
        match_fingerprint="b" * 64,
        computed_at=NOW,
    ))
    db.flush()

    _create(db, [1])

    task = db.query(CustomerResearchTask).filter_by(task_type="full_research").one()
    assert task.tier == "T1"
    assert task.input_snapshot["target_match"]["match_score"] == "85.00"


def test_rerun_reuses_active_tasks(db):
    _sales(db, 1, "alice")
    account = _account(db, "CUS-IDEM")
    _assign(db, account.id, 1)

    first = _create(db, [1])
    second = _create(db, [1], run_tag="test-run-2")

    assert first["created"] == 1
    assert second["created"] == 0 and second["reused"] == 1
    assert db.query(CustomerResearchTask).filter_by(task_type="full_research").count() == 1


def test_global_dnc_customers_are_skipped(db):
    _sales(db, 1, "alice")
    blocked = _account(db, "CUS-DNC")
    normal = _account(db, "CUS-OK")
    _assign(db, blocked.id, 1)
    _assign(db, normal.id, 1)
    db.add(CustomerAnnotation(
        customer_id=blocked.id,
        annotation_type="do_not_contact",
        content_schema_version="v1",
        content_json={"reason": "客户要求不再开发"},
        policy_scope_type="global",
        policy_effective_at=NOW - timedelta(days=1),
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=1,
    ))
    db.flush()

    summary = _create(db, [1])

    assert summary["created"] == 1
    assert summary["skipped_dnc"] == [blocked.id]
    task = db.query(CustomerResearchTask).filter_by(task_type="full_research").one()
    assert task.customer_id == normal.id


def test_merged_assignment_resolves_to_active_root_and_archived_skipped(db):
    _sales(db, 1, "alice")
    root = _account(db, "CUS-ROOT")
    merged = _account(db, "CUS-MERGED")
    merged.record_status = "merged"
    merged.merged_into_customer_id = root.id
    archived = _account(db, "CUS-ARCHIVED")
    archived.record_status = "archived"
    db.flush()
    _assign(db, merged.id, 1)
    _assign(db, archived.id, 1)

    summary = _create(db, [1])

    assert summary["created"] == 1
    assert summary["tasks"][0]["customer_id"] == root.id
    assert summary["skipped_unresolvable"] == [archived.id]


def test_resolve_owners_rejects_unknown_or_inactive(db):
    _sales(db, 1, "alice")
    disabled = _sales(db, 2, "bob")
    disabled.is_active = False
    db.flush()

    with pytest.raises(service.SalesAutomationError):
        private_research_service.resolve_owners(db, ["alice", "nobody"])
    with pytest.raises(service.SalesAutomationError):
        private_research_service.resolve_owners(db, ["bob"])
    with pytest.raises(service.SalesAutomationError):
        private_research_service.resolve_owners(db, [])

    resolved = private_research_service.resolve_owners(db, ["alice", "1"])
    assert list(resolved) == [1]


def test_report_exports_tier_and_commerce_columns(db):
    _sales(db, 1, "alice")
    account = _account(db, "CUS-REPORT")
    _assign(db, account.id, 1)
    _order(db, account, external_id="r1", amount="500")
    _create(db, [1], run_tag="run-a")
    _sales(db, 2, "bob")
    other = _account(db, "CUS-REPORT-2")
    _assign(db, other.id, 2)
    _create(db, [2], run_tag="run-b")

    rows = private_research_service.research_report(db, run_tag="run-a")

    assert len(rows) == 1
    row = rows[0]
    assert row["run_tag"] == "run-a"
    assert row["owner_username"] == "alice"
    assert row["customer_code"] == "CUS-REPORT"
    assert row["tier"] == "T3"
    assert row["task_status"] == "pending"
    all_rows = private_research_service.research_report(db)
    assert {r["run_tag"] for r in all_rows} == {"run-a", "run-b"}
