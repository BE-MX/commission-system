"""Private-customer enrichment requests using the existing evidence-only research queue."""

from copy import deepcopy

from sqlalchemy import or_

from app.customer.access_service import CustomerAccess, apply_record_access
from app.customer import evidence_service
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.models import CustomerAccount, CustomerAnnotation, CustomerContactPoint, CustomerExternalIdentity, CustomerFact, CustomerResearchTask, CustomerSourceRecord
from app.sales_automation import public_pool_service, service

POLICY_VERSION = "private-enrichment-v1"
RESEARCH_REQUEST = {
    "schema_version": "private_enrichment_v1",
    "focus": ["官网及其与客户的主体关联", "公司业务与经营模式", "公开商业联系方式", "主营产品"],
    "instructions": [
        "保留方舟已有内容；新增材料只作为有来源的候选事实和待审核研究结果，不覆盖已确认信息。",
        "逐项对照 existing_information，冲突在 risk 结论中列出原值、新值、双方来源与待确认原因。",
        "每个新结论附实际打开的来源 URL、采集时间和证据引用；找不到或主体不明时明确标记未核实。",
        "仅核实公开商业联系方式，不猜邮箱、不调查私人关系、不发送消息。",
        "既有档案和订单是内部上下文，不能泄露给搜索引擎，不能冒充本次采集的公开证据。",
        "完成后通过本任务回写方舟，保留 pending 质量审核状态。",
    ],
}


def existing_information(db, account):
    access = CustomerAccess(
        customer_id=account.id, actor_user_id=0, can_manage=False,
        max_data_classification="internal_business", max_visibility_scope="customer_team", run_id=None,
    )
    facts = evidence_service.visible_facts(db, access).filter(
        CustomerFact.verification_status.notin_(("rejected", "superseded")),
    ).order_by(CustomerFact.id.desc()).limit(101).all()
    sources = {row.id: row for row in apply_record_access(
        db.query(CustomerSourceRecord), CustomerSourceRecord, access, logical_object_type="source_record",
    ).all()}
    identities = db.query(CustomerExternalIdentity).filter(
        logical_root_predicate(CustomerExternalIdentity, "external_identity", account.id),
        CustomerExternalIdentity.identifier_type == "website_domain",
        CustomerExternalIdentity.status == "active",
        or_(CustomerExternalIdentity.source_record_id.is_(None), CustomerExternalIdentity.source_record_id.in_(sources)),
    ).all()
    contacts = db.query(CustomerContactPoint).filter(
        logical_root_predicate(CustomerContactPoint, "contact_point", account.id),
        CustomerContactPoint.data_classification.in_(("public_business", "internal_business")),
        or_(CustomerContactPoint.source_record_id.is_(None), CustomerContactPoint.source_record_id.in_(sources)),
    ).all()

    def source_url(row):
        source = sources.get(row.source_record_id)
        return evidence_service._safe_url(source.source_url) if source else None

    revisions = {}
    for row in apply_record_access(
        db.query(CustomerAnnotation), CustomerAnnotation, access,
        visibility_field="visibility", author_field="authored_by", logical_object_type="annotation",
    ).filter(CustomerAnnotation.status == "active", CustomerAnnotation.content_schema_version == "v2").order_by(
        CustomerAnnotation.id.desc(),
    ).all():
        content = row.content_json or {}
        key = content.get("field_key")
        if content.get("revision_kind") == "profile_field_revision" and key and key not in revisions:
            revisions[key] = {"annotation_id": row.id, "field_key": key, "value": content.get("value"),
                              "reason": content.get("reason"), "evidence_refs": content.get("evidence_refs", []),
                              "source": "人工确认的当前档案修订", "created_at": row.created_at.isoformat()}

    return {
        "company_name": account.canonical_company_name,
        "display_name": account.display_name,
        "profile_version_id": account.current_profile_version_id,
        "current_manual_revisions": list(revisions.values()),
        "website_clues": [{"value": row.raw_value, "verification_status": row.verification_status,
                           "source_record_id": row.source_record_id, "source_url": source_url(row)} for row in identities],
        "business_contacts": [{"type": row.point_type, "value": row.raw_value,
                               "verification_status": row.verification_status,
                               "contactability_status": row.contactability_status,
                               "source_url": source_url(row), "source_record_id": row.source_record_id}
                              for row in contacts],
        "facts": evidence_service.serialize_facts(db, facts[:100]),
        "facts_truncated": len(facts) > 100,
    }


def ensure_enrichment_task(db, *, customer_id, operator_id, run_tag, input_snapshot, tier):
    # Serialize repeated clicks and batch requests on the same customer before reading the queue.
    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == customer_id, CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise service.NotFoundError("客户不存在")
    current = db.query(CustomerResearchTask).filter(
        logical_root_predicate(CustomerResearchTask, "research_task", customer_id),
        CustomerResearchTask.customer_id == customer_id,
        CustomerResearchTask.research_policy_version == POLICY_VERSION,
        or_(CustomerResearchTask.task_status.in_(("pending", "running")),
            (CustomerResearchTask.task_status == "completed") &
            CustomerResearchTask.result_review_status.in_(("pending", "revision_requested"))),
    ).order_by(CustomerResearchTask.id.desc()).first()
    if current is not None:
        return current, False
    snapshot = {**input_snapshot, "research_request": deepcopy(RESEARCH_REQUEST),
                "existing_information": existing_information(db, account)}
    return public_pool_service.ensure_research_task(
        db, customer_id=customer_id, task_type="full_research", source_ref_type="manual",
        source_ref_id=run_tag, research_policy_version=POLICY_VERSION,
        input_snapshot=snapshot, selection_reason=[{"reason": "private_customer_enrichment"}],
        tier=tier, created_by=operator_id, physical_owner_only=True,
    )
