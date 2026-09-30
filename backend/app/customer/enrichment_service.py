"""Authorized requests and progress for one private customer's enrichment."""

from uuid import uuid4
from app.core.time import beijing_now

from app.customer import evidence_service, pcw_errors, query_service
from app.customer.access_service import apply_record_access, require_customer_access
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerFact, CustomerResearchTask
from app.sales_automation import private_research_service, public_pool_service
from app.sales_automation.private_enrichment_service import POLICY_VERSION

WRITE_PERMISSIONS = ("customer_profile:write", "customer:admin")
READ_PERMISSIONS = ("customer:read", "customer:read_all", *WRITE_PERMISSIONS)


def _access(db, customer_id, user, *, write=False):
    return require_customer_access(
        db, customer_id=customer_id, user=user,
        action_permissions=WRITE_PERMISSIONS if write else READ_PERMISSIONS,
        manage_permissions=("customer:admin",), allow_public_pool=False,
    )


def latest_enrichment(db, customer_id, user):
    access = _access(db, customer_id, user)
    task = apply_record_access(
        db.query(CustomerResearchTask), CustomerResearchTask, access, logical_object_type="research_task",
    ).filter(
        CustomerResearchTask.research_policy_version == POLICY_VERSION,
        CustomerResearchTask.customer_id == access.customer_id,
    ).order_by(
        CustomerResearchTask.id.desc(),
    ).first()
    if task is None:
        return None
    result = query_service.serialize_research_task(task, access, include_content=True)
    facts = evidence_service.visible_facts(db, access).filter(
        CustomerFact.id.in_(task.evidence_fact_ids or []),
    ).all()
    result["evidence"] = evidence_service.serialize_facts(db, facts)
    return result


def request_enrichment(db, customer_id, user):
    access = _access(db, customer_id, user, write=True)
    customer_id = access.customer_id
    db.query(CustomerAccount).filter(CustomerAccount.id == customer_id).with_for_update().one()
    owners = db.query(CustomerAssignment.user_id).filter(
        CustomerAssignment.customer_id == customer_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
        CustomerAssignment.effective_from <= beijing_now(),
    ).all()
    if not owners:
        raise pcw_errors.conflict("仅有有效主负责人的私海客户可发起补全", "PRIVATE_CUSTOMER_REQUIRED")
    if public_pool_service.is_development_denied(db, customer_id):
        raise pcw_errors.conflict("该客户已禁止开发，不能发起信息补全", "CUSTOMER_DEVELOPMENT_DENIED")
    summary = private_research_service.create_private_research_tasks(
        db, owner_ids=[row[0] for row in owners], customer_ids=[customer_id],
        run_tag=f"enrichment-{uuid4().hex}", operator_id=access.actor_user_id,
        enrichment=True, commit=False,
    )
    if summary["errors"] or not summary["tasks"]:
        raise pcw_errors.conflict("客户状态已变化，未创建补全任务，请刷新后重试", "ENRICHMENT_NOT_CREATED")
    task = latest_enrichment(db, customer_id, user)
    return {"created": bool(summary["created"]), "task": task}
