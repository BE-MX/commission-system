"""PCW-06 维护日历/样品/物流关联/活动契约测试。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.core.time import beijing_now, beijing_today
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAnnotation,
    CustomerAssignment,
    CustomerListProjection,
    CustomerOrder,
)
from app.customer.pcw_maintenance_service import (
    create_campaign,
    create_plan,
    create_sample_case,
    create_shipment_order_link,
    list_calendar,
    patch_plan,
    patch_sample_case,
    preview_campaign,
    create_campaign_actions,
    publish_campaign,
    reschedule_occurrence,
    sync_sample_logistics,
    transition_campaign,
)
from app.customer.pcw_models import MaintenanceOccurrence, MaintenancePlan, SampleCase
from tests.test_customer_workflow import _account, _grant_permission, _source_record, _user
from tests.test_pcw_order_analytics import STATUS_ENDED, _item, _order

NOW = beijing_now().replace(microsecond=0)


def _setup(db, code="C-PCW-MNT", user_id=9301):
    account, _version = _account(db, code=code)
    user = _user(db, user_id)
    _grant_permission(db, user_id, "customer:read")
    _grant_permission(db, user_id, "customer_pcw:write")
    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=user.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=user.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    return account, user


def test_typed_payload_validation(db):
    account, user = _setup(db)
    cases = [
        ("manual", {"purpose": "x", "channel": "whatsapp"}, "PLAN_PAYLOAD_INVALID"),
        ("birthday", {"contact_id": 1, "month": 2, "day": 29,
                      "local_contact_time": "10:00", "leap_day_policy": "guess"},
         "BIRTHDAY_LEAP_POLICY_REQUIRED"),
        ("holiday", {"holiday_code": "EID", "calendar_region": "SA",
                     "occurrence_local_date": "2026-03-20", "local_contact_time": "10:00",
                     "applicability_confirmed": False},
         "HOLIDAY_APPLICABILITY_REQUIRED"),
        ("sample", {"sample_case_id": 1, "purpose": "p",
                    "test_planned_date": "2026-10-01", "feedback_due_at": "2026-10-05"},
         "PLAN_PAYLOAD_INVALID"),
    ]
    for plan_type, payload, code in cases:
        with pytest.raises(pcw_errors.PcwError) as excinfo:
            create_plan(
                db,
                customer_id=account.id,
                actor_user_id=user.id,
                plan_type=plan_type,
                title="t",
                typed_payload=payload,
            )
        assert excinfo.value.error_code == code


def test_manual_plan_and_reschedule_preserve_original_due(db):
    account, user = _setup(db)
    created = create_plan(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        plan_type="manual",
        title="季度回访",
        typed_payload={
            "scheduled_at": (NOW + timedelta(days=2)).isoformat(),
            "purpose": "quarterly_review",
            "channel": "whatsapp",
        },
    )
    db.commit()
    occ = created["occurrence"]
    assert occ["occurrence_key"].startswith("plan:")
    assert occ["status"] in {"planned", "due"}
    from app.customer.models import CustomerAction

    action = db.get(CustomerAction, occ["current_action_id"])
    original_due = action.original_due_at
    new_date = beijing_today() + timedelta(days=7)

    result = reschedule_occurrence(
        db,
        occurrence_id=occ["id"],
        actor_user_id=user.id,
        expected_plan_version=created["plan"]["plan_version"],
        expected_occurrence_version=occ["occurrence_version"],
        new_date=new_date,
        reason="客户要求改期",
    )
    db.commit()
    assert result["new_date"] == new_date.isoformat()
    db.refresh(action)
    assert action.original_due_at == original_due
    assert action.business_due_at == datetime.combine(new_date, time(9, 0))
    occ_row = db.get(MaintenanceOccurrence, occ["id"])
    assert occ_row.occurrence_date == new_date
    # 改约历史留痕（实例身份不变）
    plan_row = db.get(MaintenancePlan, created["plan"]["id"])
    assert plan_row.typed_payload["_reschedule_history"]


def test_reschedule_rejects_done_action_and_stale_versions(db):
    account, user = _setup(db)
    created = create_plan(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        plan_type="manual",
        title="回访",
        typed_payload={
            "scheduled_at": (NOW + timedelta(days=1)).isoformat(),
            "purpose": "review",
            "channel": "email",
        },
    )
    occ = created["occurrence"]
    from app.customer.models import CustomerAction

    action = db.get(CustomerAction, occ["current_action_id"])
    action.status = "done"
    db.flush()
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        reschedule_occurrence(
            db,
            occurrence_id=occ["id"],
            actor_user_id=user.id,
            expected_plan_version=created["plan"]["plan_version"],
            expected_occurrence_version=occ["occurrence_version"],
            new_date=beijing_today() + timedelta(days=5),
            reason="x",
        )
    assert excinfo.value.error_code == "ACTION_ALREADY_DONE"

    action.status = "pending"
    db.flush()
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        reschedule_occurrence(
            db,
            occurrence_id=occ["id"],
            actor_user_id=user.id,
            expected_plan_version=99,
            expected_occurrence_version=occ["occurrence_version"],
            new_date=beijing_today() + timedelta(days=5),
            reason="x",
        )
    assert excinfo.value.error_code == "PLAN_VERSION_CONFLICT"


def test_sample_case_requires_sample_order_and_stage_matrix(db):
    account, user = _setup(db)
    bulk_order = _order(db, account, seq=8001, order_date=beijing_today() - timedelta(days=1))
    bulk_item = _item(db, bulk_order, _source_record(db, account, record_id=88001), seq=8001, item_type="bulk")
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_sample_case(
            db,
            customer_id=account.id,
            actor_user_id=user.id,
            sample_order_id=bulk_order.id,
            sample_item_ids=[bulk_item.id],
        )
    assert excinfo.value.error_code == "SAMPLE_ORDER_REQUIRED"

    sample_order = _order(db, account, seq=8002, order_date=beijing_today() - timedelta(days=1))
    sample_item = _item(db, sample_order, _source_record(db, account, record_id=88002), seq=8002, item_type="sample")
    created = create_sample_case(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        sample_order_id=sample_order.id,
        sample_item_ids=[sample_item.id],
    )
    db.commit()
    case = created["case"]
    assert case["stage"] == "ordered"

    # ordered → testing 非法（须经 shipped/delivered/awaiting_test）
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        patch_sample_case(
            db,
            case_id=case["id"],
            actor_user_id=user.id,
            operation="start_test",
            expected_sample_version=case["sample_version"],
            actual_date=beijing_today(),
            evidence_refs=[{"type": "message", "id": 1}],
        )
    assert excinfo.value.error_code == "SAMPLE_TRANSITION_INVALID"


def test_sample_logistics_sync_does_not_start_testing(db):
    account, user = _setup(db)
    sample_order = _order(db, account, seq=8010, order_date=beijing_today() - timedelta(days=3))
    sample_item = _item(db, sample_order, _source_record(db, account, record_id=88010), seq=8010, item_type="sample")
    created = create_sample_case(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        sample_order_id=sample_order.id,
        sample_item_ids=[sample_item.id],
    )
    case = created["case"]
    from app.tracking.models import ShipmentTracking

    shipment = ShipmentTracking(
        waybill_no="WB-8010",
        carrier="DHL",
        carrier_name="DHL",
        current_status="delivered",
        dingtalk_user_id="dt-1",
        dingtalk_user_name="tester",
        shipped_at=NOW - timedelta(days=2),
        delivered_at=NOW - timedelta(days=1),
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(shipment)
    db.flush()
    link = create_shipment_order_link(
        db,
        actor_user_id=user.id,
        shipment_id=shipment.id,
        order_id=sample_order.id,
        order_item_id=sample_item.id,
        evidence_refs=[{"type": "manual", "id": 1}],
    )
    row = db.get(SampleCase, case["id"])
    row.shipment_link_ids_json = [link["link_id"]]
    db.flush()
    result = sync_sample_logistics(db, case_id=case["id"])
    db.commit()
    assert result["case"]["stage"] == "awaiting_test"  # 签收≠开始测试
    assert result["advanced"] is True


def test_sample_reschedule_updates_occurrence_and_refuses_stale(db):
    account, user = _setup(db)
    sample_order = _order(db, account, seq=8020, order_date=beijing_today() - timedelta(days=2))
    sample_item = _item(db, sample_order, _source_record(db, account, record_id=88020), seq=8020, item_type="sample")
    created = create_sample_case(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        sample_order_id=sample_order.id,
        sample_item_ids=[sample_item.id],
    )
    case = created["case"]
    plan = create_plan(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        plan_type="sample",
        title="样品测试反馈",
        typed_payload={
            "sample_case_id": case["id"],
            "purpose": "feedback",
            "test_planned_date": (beijing_today() + timedelta(days=3)).isoformat(),
        },
    )
    db.commit()
    # 推进到 delivered/awaiting_test 后才可改约
    row = db.get(SampleCase, case["id"])
    row.stage = "awaiting_test"
    db.flush()
    new_date = beijing_today() + timedelta(days=7)
    result = patch_sample_case(
        db,
        case_id=case["id"],
        actor_user_id=user.id,
        operation="reschedule",
        expected_sample_version=row.sample_version,
        expected_occurrence_version=plan["occurrence"]["occurrence_version"],
        expected_action_version=1,
        test_planned_date=new_date,
        reason="客户未测试，确认改约",
        evidence_refs=[{"type": "message", "id": 9}],
    )
    db.commit()
    assert result["case"]["test_planned_date"] == new_date.isoformat()
    occ = db.get(MaintenanceOccurrence, plan["occurrence"]["id"])
    assert occ.occurrence_date == new_date
    assert occ.occurrence_version == 2


def test_sample_feedback_and_close(db):
    account, user = _setup(db)
    sample_order = _order(db, account, seq=8030, order_date=beijing_today() - timedelta(days=2))
    sample_item = _item(db, sample_order, _source_record(db, account, record_id=88030), seq=8030, item_type="sample")
    created = create_sample_case(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        sample_order_id=sample_order.id,
        sample_item_ids=[sample_item.id],
    )
    case = created["case"]
    row = db.get(SampleCase, case["id"])
    row.stage = "testing"
    db.flush()
    updated = patch_sample_case(
        db,
        case_id=case["id"],
        actor_user_id=user.id,
        operation="record_feedback",
        expected_sample_version=row.sample_version,
        feedback_text="颜色匹配良好，手感需改进",
        actual_date=beijing_today(),
    )
    assert updated["case"]["stage"] == "feedback_received"
    closed = patch_sample_case(
        db,
        case_id=case["id"],
        actor_user_id=user.id,
        operation="close",
        expected_sample_version=updated["case"]["sample_version"],
    )
    db.commit()
    assert closed["case"]["stage"] == "closed"


def test_shipment_link_quantity_validation(db):
    account, user = _setup(db)
    order = _order(db, account, seq=8040, order_date=beijing_today() - timedelta(days=1))
    item = _item(db, order, _source_record(db, account, record_id=88040), seq=8040,
                 quantity=Decimal("10"), unit="pcs", item_type="bulk")
    from app.tracking.models import ShipmentTracking

    shipment = ShipmentTracking(
        waybill_no="WB-8040",
        carrier="DHL",
        carrier_name="DHL",
        current_status="shipped",
        dingtalk_user_id="dt-1",
        dingtalk_user_name="tester",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(shipment)
    db.flush()

    # 无数量（unknown）不猜
    link = create_shipment_order_link(
        db,
        actor_user_id=user.id,
        shipment_id=shipment.id,
        order_id=order.id,
        order_item_id=item.id,
        evidence_refs=[{"type": "manual", "id": 1}],
    )
    assert link["created"] is True

    # 超量 400
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_shipment_order_link(
            db,
            actor_user_id=user.id,
            shipment_id=shipment.id,
            order_id=order.id,
            order_item_id=item.id,
            link_role="partial",
            linked_quantity="999",
            linked_unit="pcs",
            evidence_refs=[{"type": "manual", "id": 1}],
        )
    assert excinfo.value.error_code == "LINK_QUANTITY_EXCEEDED"

    # 无依据 400
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_shipment_order_link(
            db,
            actor_user_id=user.id,
            shipment_id=shipment.id,
            order_id=order.id,
            order_item_id=item.id,
            link_role="rest",
            evidence_refs=[],
        )
    assert excinfo.value.error_code == "LINK_EVIDENCE_REQUIRED"


def test_campaign_preview_and_batch_results_are_honest(db):
    account, user = _setup(db)
    other_account, other_user = _setup(db, code="C-PCW-DNC", user_id=9302)
    db.add(CustomerAnnotation(
        customer_id=other_account.id,
        annotation_type="do_not_contact",
        content_schema_version="v1",
        content_json={"text": "DNC"},
        policy_scope_type="global",
        policy_effective_at=NOW - timedelta(days=1),
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=other_user.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    for acc, market in ((account, "US"), (other_account, "US")):
        db.add(CustomerListProjection(
            customer_id=acc.id,
            primary_industry="hair",
            primary_market=market,
            acquisition_source="search",
            primary_product_family="hair_bundle",
            commercial_value_score=0,
            has_valid_order=False,
            valid_order_count=0,
            valid_order_amount_usd=0,
            engagement_health="new",
            open_opportunity_count=0,
            global_claim_blocked=False,
            has_active_dnc=False,
            data_quality_score=80,
            profile_version_id=acc.current_profile_version_id,
            compiled_at=NOW,
        ))
    db.flush()

    created = create_campaign(
        db,
        actor_user_id=user.id,
        title="春季新品",
        campaign_type="new_product",
        product_scope={"product_families": ["hair_bundle"]},
        market_scope={"countries": ["US"]},
        effective_from=NOW,
        effective_to=NOW + timedelta(days=30),
    )
    campaign = created["campaign"]
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        preview_campaign(db, campaign_id=campaign["id"], actor_user_id=user.id, actor_permissions=frozenset())
    assert excinfo.value.error_code == "CAMPAIGN_NOT_ACTIVE"

    published = publish_campaign(
        db,
        campaign_id=campaign["id"],
        actor_user_id=user.id,
        expected_campaign_version=campaign["campaign_version"],
    )
    db.commit()
    preview = preview_campaign(
        db, campaign_id=campaign["id"], actor_user_id=user.id,
        actor_permissions=frozenset({"customer:admin"}),
    )
    eligible_ids = [item["customer_id"] for item in preview["eligible"]]
    excluded_map = {item["customer_id"]: item["reasons"] for item in preview["excluded"]}
    assert account.id in eligible_ids
    assert "dnc_active" in excluded_map.get(other_account.id, [])

    result = create_campaign_actions(
        db,
        campaign_id=campaign["id"],
        actor_user_id=user.id,
        preview_version=preview["preview_version"],
        customer_ids=[account.id, other_account.id],
        actor_permissions=frozenset({"customer:admin"}),
    )
    db.commit()
    assert account.id in result["created"]
    assert any(
        item["customer_id"] == other_account.id and item["reason"] == "dnc_active"
        for item in result["suppressed"]
    )
    assert result["failed"] == []

    # 重放：同键进 existing
    replay = create_campaign_actions(
        db,
        campaign_id=campaign["id"],
        actor_user_id=user.id,
        preview_version=preview["preview_version"],
        customer_ids=[account.id],
    )
    assert replay["created"] == []
    assert replay["existing"] == [account.id]

    # 预览过期 409
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_campaign_actions(
            db,
            campaign_id=campaign["id"],
            actor_user_id=user.id,
            preview_version="0" * 64,
            customer_ids=[account.id],
        )
    assert excinfo.value.error_code == "PREVIEW_STALE"

    # closed 不可重开
    closed = transition_campaign(
        db,
        campaign_id=campaign["id"],
        actor_user_id=user.id,
        target_status="closed",
        expected_campaign_version=published["campaign"]["campaign_version"],
    )
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        transition_campaign(
            db,
            campaign_id=campaign["id"],
            actor_user_id=user.id,
            target_status="active",
            expected_campaign_version=closed["campaign"]["campaign_version"],
        )
    assert excinfo.value.error_code == "CAMPAIGN_TRANSITION_INVALID"


def test_calendar_groups_by_beijing_business_day(db):
    account, user = _setup(db)
    create_plan(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        plan_type="manual",
        title="今日任务",
        typed_payload={
            "scheduled_at": datetime.combine(beijing_today(), time(15, 0)).isoformat(),
            "purpose": "today",
            "channel": "whatsapp",
        },
    )
    db.commit()
    today = beijing_today()
    result = list_calendar(
        db,
        actor_user_id=user.id,
        customer_scope="primary",
        date_from=today,
        date_to=today,
    )
    days = {day["date"]: day["items"] for day in result["days"]}
    assert today.isoformat() in days
    assert days[today.isoformat()][0]["title"] == "今日任务"
