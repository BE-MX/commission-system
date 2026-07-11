from datetime import date
from decimal import Decimal

import pytest

from app.aftersales.models import (
    AfterSalesAiRun, AfterSalesEvidence, AfterSalesEvent, AfterSalesNotificationLog,
    AfterSalesReview, AfterSalesSopVersion,
)
from app.aftersales.schemas import CaseCreate
from app.aftersales.service import (
    ApprovalConfigurationError,
    VersionConflict,
    WorkflowOperationError,
    close_case,
    create_case,
    execute_case,
    reopen_case,
    review_case,
    save_decision,
    submit_case,
    request_evidence_waiver,
    review_evidence_waiver,
    transfer_approval,
    update_case,
    withdraw_case,
)
from app.auth.models import ArkRole, ArkUser, ArkUserExternalBinding
from app.models.employee import SupervisorRelationHistory


def _user(db, username, external_id, *, dingtalk=True):
    user = ArkUser(
        username=username,
        password_hash="test-hash",
        real_name=username,
        dingtalk_id=f"ding-{username}" if dingtalk else None,
    )
    db.add(user)
    db.flush()
    db.add(
        ArkUserExternalBinding(
            ark_user_id=user.id,
            provider="okki",
            external_account_id=external_id,
            external_display_name=username,
            binding_status="active",
            is_primary=True,
        )
    )
    db.flush()
    return user


def _people(db, *, sales_dingtalk=True, supervisor_dingtalk=True, with_director=True):
    sales = _user(db, "sales", "SP001", dingtalk=sales_dingtalk)
    supervisor = _user(db, "supervisor", "SV001", dingtalk=supervisor_dingtalk)
    director = None
    if with_director:
        director = _user(db, "director", "DIR001")
        role = ArkRole(name="sales_director", label="销售总监", is_system=True)
        db.add(role)
        db.flush()
        director.roles.append(role)
    db.add(
        SupervisorRelationHistory(
            salesperson_id="SP001",
            supervisor_id="SV001",
            effective_start=date(2026, 1, 1),
            is_current=True,
        )
    )
    db.flush()
    return sales, supervisor, director


def _payload():
    return CaseCreate.model_validate(
        {
            "customer_id": "CUST001",
            "customer_name_snapshot": "客户A",
            "customer_grade": "A",
            "order_id": "ORD001",
            "order_no_snapshot": "NO001",
            "purchase_date": date(2026, 7, 1),
            "feedback_date": date(2026, 7, 10),
            "product_id": 1,
            "product_name_snapshot": "Invisible Weft",
            "is_custom_product": False,
            "batch_no": None,
            "color_value": "#2B",
            "length_value": "20 inch",
            "weight_value": Decimal("100"),
            "weight_unit": "g",
            "quantity": Decimal("2"),
            "primary_issue_type": "褪色",
            "problem_description": "客户使用三周后出现明显褪色，已经影响终端客户继续销售。",
            "occurred_stage": "使用几天",
            "care_storage_note": "客户使用无硫酸盐洗发水，低温护理，未游泳或暴晒。",
            "affects_end_customer": "yes",
            "affected_goods_value": Decimal("1150"),
            "affected_goods_currency": "USD",
            "sales_evidence_confirmed": True,
        }
    )


def _ready_case(db, sales, *, compensation=False):
    case = create_case(db, _payload(), sales)
    case.current_status = "awaiting_sales_decision"
    case.evidence_score = 100
    case.evidence_is_sufficient = True
    case.evidence_missing_items_json = []
    case.responsibility_class = "D"
    case.responsibility_reason = "责任暂不明确"
    db.add_all(
        [
            AfterSalesEvidence(
                case_id=case.id,
                evidence_type="overview_image",
                original_filename="overview.jpg",
                storage_path="evidence/overview.jpg",
                mime_type="image/jpeg",
                file_size=100,
                uploaded_by_user_id=sales.id,
            ),
            AfterSalesEvidence(
                case_id=case.id,
                evidence_type="closeup_image",
                original_filename="closeup.jpg",
                storage_path="evidence/closeup.jpg",
                mime_type="image/jpeg",
                file_size=100,
                uploaded_by_user_id=sales.id,
            ),
        ]
    )
    actions = [{
        "code": "return_inspection",
        "freight_payer": "customer",
        "return_address": "LeShine Quality Center",
        "expected_completion_date": "2026-07-20",
    }]
    reply = "Thank you for your feedback. Please return the affected hair for inspection."
    if compensation:
        actions = [{
            "code": "replacement",
            "quantity": "2",
            "product": "Invisible Weft #2B 20 inch",
            "estimated_cost_usd": "360",
            "delivery_date": "2026-07-20",
        }]
        reply = "We propose a replacement, subject to final internal approval."
    save_decision(
        db,
        case.id,
        sales,
        responsibility_class="D",
        responsibility_reason="责任暂不明确",
        responsibility_override_reason=None,
        actions=actions,
        customer_reply_draft=reply,
        requires_return=not compensation,
    )
    return case


def test_create_case_is_owned_by_creator_and_starts_as_draft(db):
    sales, _, _ = _people(db)

    case = create_case(db, _payload(), sales)

    assert case.case_no.startswith("AS-")
    assert case.creator_user_id == sales.id
    assert case.current_status == "draft"


def test_case_number_uses_highest_daily_sequence_instead_of_row_count(db):
    sales, _, _ = _people(db)
    prefix = f"AS-{date.today():%Y%m%d}-"
    first = create_case(db, _payload(), sales)
    first.case_no = f"{prefix}003"
    db.flush()

    second = create_case(db, _payload(), sales)

    assert second.case_no == f"{prefix}004"


def test_only_creator_can_update_editable_case(db):
    sales, supervisor, _ = _people(db)
    case = create_case(db, _payload(), sales)
    changed = _payload().model_copy(update={"problem_description": "修改后的问题描述超过二十个字符，并清晰说明范围和影响。"})

    with pytest.raises(WorkflowOperationError, match="创建人"):
        update_case(db, case.id, changed, supervisor)


def test_submitted_case_cannot_be_edited(db):
    sales, _, _ = _people(db)
    case = create_case(db, _payload(), sales)
    case.current_status = "awaiting_supervisor"

    with pytest.raises(WorkflowOperationError, match="锁定"):
        update_case(db, case.id, _payload(), sales)


def test_server_recomputes_compensation_from_actions(db):
    sales, _, _ = _people(db)
    case = create_case(db, _payload(), sales)
    case.current_status = "awaiting_sales_decision"

    save_decision(
        db,
        case.id,
        sales,
        responsibility_class="A",
        responsibility_reason="生产问题",
        responsibility_override_reason="根据批次复核修改",
        actions=[{"code": "replacement", "estimated_cost_usd": "360"}],
        customer_reply_draft="Replacement proposal is subject to final internal approval.",
        requires_return=False,
    )

    assert case.has_compensation is True
    assert case.estimated_compensation_usd == Decimal("360.00")


def test_submit_snapshots_supervisor_for_non_compensation(db):
    sales, supervisor, _ = _people(db)
    case = _ready_case(db, sales, compensation=False)

    submitted = submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-1")

    assert submitted.current_status == "awaiting_supervisor"
    assert submitted.supervisor_user_id_snapshot == supervisor.id
    assert submitted.director_user_id_snapshot is None
    assert submitted.current_owner_user_id == supervisor.id
    notice = db.query(AfterSalesNotificationLog).filter_by(case_id=case.id).one()
    assert notice.recipient_user_id == supervisor.id
    assert notice.template_code == "awaiting_supervisor"


def test_compensation_submit_requires_exactly_one_director(db):
    sales, _, _ = _people(db, with_director=False)
    case = _ready_case(db, sales, compensation=True)

    with pytest.raises(ApprovalConfigurationError, match="销售总监"):
        submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-2")


def test_submit_requires_supervisor_dingtalk_binding(db):
    sales, _, _ = _people(db, supervisor_dingtalk=False)
    case = _ready_case(db, sales)

    with pytest.raises(ApprovalConfigurationError, match="钉钉"):
        submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-3")


def test_stale_version_cannot_submit(db):
    sales, _, _ = _people(db)
    case = _ready_case(db, sales)

    with pytest.raises(VersionConflict):
        submit_case(db, case.id, sales, version=case.version - 1, idempotency_key="submit-stale")


def test_non_compensation_finishes_after_supervisor_approval(db):
    sales, supervisor, _ = _people(db)
    case = _ready_case(db, sales, compensation=False)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-4")

    reviewed = review_case(
        db,
        case.id,
        supervisor,
        decision="approve",
        comment="同意",
        version=case.version,
        idempotency_key="review-4",
    )

    assert reviewed.current_status == "approved"
    assert db.query(AfterSalesReview).filter_by(case_id=case.id).count() == 1


def test_compensation_requires_director_after_supervisor(db):
    sales, supervisor, director = _people(db)
    case = _ready_case(db, sales, compensation=True)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-5")
    review_case(
        db, case.id, supervisor, decision="approve", comment="同意上报", version=case.version,
        idempotency_key="review-supervisor-5",
    )

    assert case.current_status == "awaiting_director"
    assert case.current_owner_user_id == director.id
    director_notice = (
        db.query(AfterSalesNotificationLog)
        .filter_by(case_id=case.id, template_code="awaiting_director")
        .one()
    )
    assert director_notice.recipient_user_id == director.id

    review_case(
        db, case.id, director, decision="approve", comment="终审同意", version=case.version,
        idempotency_key="review-director-5",
    )
    assert case.current_status == "approved"
    approved_notice = (
        db.query(AfterSalesNotificationLog)
        .filter_by(case_id=case.id, template_code="approved")
        .one()
    )
    assert approved_notice.recipient_user_id == sales.id


def test_duplicate_review_key_returns_same_result_without_duplicate_row(db):
    sales, supervisor, _ = _people(db)
    case = _ready_case(db, sales)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-6")
    old_version = case.version
    first = review_case(
        db, case.id, supervisor, decision="approve", comment="同意", version=old_version,
        idempotency_key="review-6",
    )
    second = review_case(
        db, case.id, supervisor, decision="approve", comment="同意", version=old_version,
        idempotency_key="review-6",
    )

    assert first.id == second.id
    assert db.query(AfterSalesReview).filter_by(case_id=case.id).count() == 1


def test_withdraw_only_before_supervisor_has_reviewed(db):
    sales, _, _ = _people(db)
    case = _ready_case(db, sales)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-7")

    withdraw_case(db, case.id, sales, version=case.version)

    assert case.current_status == "awaiting_sales_decision"
    assert case.current_owner_user_id == sales.id


def test_execution_and_close_require_approved_path(db):
    sales, supervisor, _ = _people(db)
    case = _ready_case(db, sales)
    with pytest.raises(WorkflowOperationError):
        execute_case(db, case.id, sales, "已寄出替换产品", "客户等待收货")

    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-8")
    review_case(
        db, case.id, supervisor, decision="approve", comment="同意", version=case.version,
        idempotency_key="review-8",
    )
    execute_case(db, case.id, sales, "已寄出替换产品", "客户等待收货")
    close_case(db, case.id, sales, "客户确认问题已解决")

    assert case.current_status == "closed"
    assert case.closed_at is not None


def test_reopen_starts_a_clean_resolution_round_and_keeps_history(db):
    sales, supervisor, _ = _people(db)
    admin = _user(db, "reopen-admin", "ADM-REOPEN")
    case = _ready_case(db, sales)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-reopen")
    review_case(
        db, case.id, supervisor, decision="approve", comment="同意", version=case.version,
        idempotency_key="review-reopen",
    )
    execute_case(db, case.id, sales, "已寄出替换产品", "客户等待收货")
    close_case(db, case.id, sales, "客户确认问题已解决")

    reopen_case(db, case.id, admin, "客户反馈替换产品仍有问题")

    assert case.current_status == "returned"
    assert case.current_owner_user_id == sales.id
    assert case.execution_result is None
    assert case.customer_feedback is None
    assert case.approved_at is None
    assert case.closed_at is None
    event = db.query(AfterSalesEvent).filter_by(case_id=case.id, event_type="reopened").one()
    assert event.detail_json["previous_resolution"]["execution_result"] == "已寄出替换产品"
    assert event.detail_json["previous_resolution"]["customer_feedback"] == "客户确认问题已解决"


def test_insufficient_evidence_can_only_submit_after_supervisor_waiver(db):
    sales, supervisor, _ = _people(db)
    case = _ready_case(db, sales)
    db.query(AfterSalesEvidence).filter_by(case_id=case.id).delete()
    case.evidence_score = 0
    case.evidence_is_sufficient = False
    case.evidence_missing_items_json = ["问题全景图", "问题近景图"]
    case.sales_evidence_confirmed = False

    with pytest.raises(WorkflowOperationError, match="证据未达到"):
        submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-no-waiver")

    request_evidence_waiver(
        db, case.id, sales, reason="客户拒绝继续提供照片，主管已与客户确认。",
        version=case.version, idempotency_key="waiver-request-1",
    )
    assert case.current_status == "awaiting_evidence_waiver"
    assert case.current_owner_user_id == supervisor.id

    review_evidence_waiver(
        db, case.id, supervisor, decision="approve", comment="同意基于现有材料继续处理。",
        version=case.version, idempotency_key="waiver-review-1",
    )
    assert case.evidence_waiver_approved is True
    assert case.current_status == "awaiting_sales_decision"

    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-with-waiver")
    assert case.current_status == "awaiting_supervisor"


def test_admin_can_transfer_pending_approval_with_audit_and_notifications(db):
    sales, supervisor, _ = _people(db)
    replacement = _user(db, "replacement-supervisor", "SV002")
    admin = _user(db, "admin", "ADM001")
    case = _ready_case(db, sales)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-transfer")

    transfer_approval(
        db, case.id, admin, replacement, reason="原主管休假，转交当班主管。",
        version=case.version, idempotency_key="transfer-1",
    )

    assert case.supervisor_user_id_snapshot == replacement.id
    assert case.current_owner_user_id == replacement.id
    event = db.query(AfterSalesEvent).filter_by(case_id=case.id, event_type="approval_transferred").one()
    assert event.detail_json["from_user_id"] == supervisor.id
    notices = db.query(AfterSalesNotificationLog).filter_by(case_id=case.id, template_code="approval_transferred").all()
    assert {item.recipient_user_id for item in notices} == {sales.id, supervisor.id, replacement.id}


def test_super_admin_proxy_review_requires_reason_and_is_audited(db):
    sales, _, _ = _people(db)
    proxy = _user(db, "proxy-admin", "ADM002")
    case = _ready_case(db, sales)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-proxy")

    with pytest.raises(WorkflowOperationError, match="代理原因"):
        review_case(
            db, case.id, proxy, decision="approve", comment="同意", version=case.version,
            idempotency_key="proxy-review-missing", allow_proxy=True, proxy_reason="",
        )

    review_case(
        db, case.id, proxy, decision="approve", comment="同意", version=case.version,
        idempotency_key="proxy-review-ok", allow_proxy=True, proxy_reason="指定主管无法登录，紧急代审。",
    )
    proxy_event = db.query(AfterSalesEvent).filter_by(case_id=case.id, event_type="review_proxied").one()
    assert proxy_event.detail_json["proxy_reason"] == "指定主管无法登录，紧急代审。"


def test_missing_creator_dingtalk_does_not_rollback_final_approval(db):
    sales, supervisor, _ = _people(db, sales_dingtalk=False)
    case = _ready_case(db, sales)
    submit_case(db, case.id, sales, version=case.version, idempotency_key="submit-no-sales-ding")

    review_case(
        db, case.id, supervisor, decision="approve", comment="同意", version=case.version,
        idempotency_key="review-no-sales-ding",
    )

    assert case.current_status == "approved"
    notice = db.query(AfterSalesNotificationLog).filter_by(case_id=case.id, template_code="approved").one()
    assert notice.status == "failed"
    assert notice.recipient_dingtalk_id is None


def test_idempotency_key_cannot_be_reused_across_cases(db):
    sales, _, _ = _people(db)
    first = _ready_case(db, sales)
    second = _ready_case(db, sales)
    submit_case(db, first.id, sales, version=first.version, idempotency_key="shared-key")

    with pytest.raises(WorkflowOperationError, match="其他售后单"):
        submit_case(db, second.id, sales, version=second.version, idempotency_key="shared-key")


def test_changing_ai_responsibility_requires_server_side_reason(db):
    sales, _, _ = _people(db)
    case = _ready_case(db, sales)
    sop = AfterSalesSopVersion(
        version_no="test-override", original_filename="sop.docx", storage_path="sop/test.docx",
        file_hash="f" * 64, change_summary="test", effective_date=date(2026, 7, 1),
        parse_status="parsed", uploaded_by_user_id=sales.id,
    )
    db.add(sop)
    db.flush()
    db.add(AfterSalesAiRun(
        case_id=case.id, sop_version_id=sop.id, run_no=1, status="success",
        output_json={"responsibility": {"class": "D"}}, created_by_user_id=sales.id,
    ))
    db.flush()

    with pytest.raises(WorkflowOperationError, match="修改 AI 责任判定"):
        save_decision(
            db, case.id, sales, responsibility_class="A", responsibility_reason="SOP 3.2",
            responsibility_override_reason=None, actions=case.selected_actions_json,
            customer_reply_draft=case.customer_reply_draft, requires_return=True,
        )


def test_ai_failed_manual_decision_requires_sop_basis_and_english_reply(db):
    sales, _, _ = _people(db)
    case = _ready_case(db, sales)
    case.current_status = "ai_failed"

    with pytest.raises(WorkflowOperationError, match="SOP 条款"):
        save_decision(
            db, case.id, sales, responsibility_class="D", responsibility_reason="人工判断",
            responsibility_override_reason=None, actions=case.selected_actions_json,
            customer_reply_draft=case.customer_reply_draft, requires_return=True,
        )
    with pytest.raises(WorkflowOperationError, match="SOP 条款"):
        save_decision(
            db, case.id, sales, responsibility_class="D", responsibility_reason="SOP 待定",
            responsibility_override_reason=None, actions=case.selected_actions_json,
            customer_reply_draft=case.customer_reply_draft, requires_return=True,
        )
    with pytest.raises(WorkflowOperationError, match="英文话术"):
        save_decision(
            db, case.id, sales, responsibility_class="D", responsibility_reason="无适用条款",
            responsibility_override_reason=None, actions=case.selected_actions_json,
            customer_reply_draft="这是中文客户回复，内容足够长但不是英文话术。", requires_return=True,
        )
