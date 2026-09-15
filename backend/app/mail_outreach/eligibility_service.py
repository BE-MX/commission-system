"""统一触达资格策略：生成前快评与批准前复查共用同一套规则。

任一规则不满足即 eligible=false；missing 为稳定机器码，reasons 为面向用户的中文说明。
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import beijing_now
from app.customer.access_service import CustomerAccess
from app.customer.models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerSuppressionRegistry,
)
from app.mail_outreach.models import MailOutreachSendJob
from app.sales_automation import public_pool_service

# 冷却期内视为"占用该收件人"的 job 状态（尚未形成最终结论的在途/已接受任务）
_COOLDOWN_JOB_STATUSES = ("scheduled", "claimed", "sending", "provider_accepted")
_RELATIONSHIP_OK_STATUSES = ("identified", "verified")


def evaluate_email_eligibility(
    db: Session,
    access: CustomerAccess,
    customer_id: int,
    contact_id: int,
    contact_point_id: int,
) -> dict:
    """返回 {"eligible": bool, "missing": [机器码], "reasons": [中文说明]}。"""
    missing: list[str] = []
    reasons: list[str] = []

    customer = db.query(CustomerAccount).filter(
        CustomerAccount.id == customer_id,
    ).one_or_none()
    if customer is None or customer.record_status != "active":
        missing.append("customer_record_status")
        reasons.append("客户主档不存在或已非有效状态")

    contact = db.query(CustomerContact).filter(
        CustomerContact.id == contact_id,
        CustomerContact.record_status == "active",
    ).one_or_none()
    relationship = db.query(CustomerContactRelationship).filter(
        CustomerContactRelationship.customer_id == customer_id,
        CustomerContactRelationship.contact_id == contact_id,
        CustomerContactRelationship.effective_to.is_(None),
        CustomerContactRelationship.verification_status.in_(_RELATIONSHIP_OK_STATUSES),
    ).first()
    if contact is None or relationship is None:
        missing.append("contact_relationship")
        reasons.append("联系人与客户的有效关系缺失或未识别")

    point = db.query(CustomerContactPoint).filter(
        CustomerContactPoint.id == contact_point_id,
    ).one_or_none()
    if point is None or point.contact_id != contact_id or point.point_type != "email":
        missing.append("contact_point")
        reasons.append("收件邮箱点不存在或不属于该联系人")
    else:
        if point.verification_status != "valid":
            missing.append("email_verification")
            reasons.append(f"邮箱验证状态为 {point.verification_status}，须为 valid")
        if point.contactability_status != "allowed":
            missing.append("contactability")
            reasons.append(f"可联系状态为 {point.contactability_status}，须为 allowed")
        # 点级抑制：HMAC 注册表已映射到该联系点且仍在生效期
        point_suppressed = db.query(CustomerSuppressionRegistry.id).filter(
            CustomerSuppressionRegistry.mapped_contact_point_id == point.id,
            CustomerSuppressionRegistry.status == "active",
            CustomerSuppressionRegistry.effective_at <= beijing_now(),
        ).first()
        if point_suppressed is not None:
            missing.append("point_suppression")
            reasons.append("该联系点已被抑制注册表命中（退订/硬退信/人工限制）")

    # 客户级抑制：全局或 channel=email 范围的禁止开发
    if public_pool_service.is_development_denied(db, customer_id, "channel", "email"):
        missing.append("customer_suppression")
        reasons.append("客户级禁止开发策略命中（email 通道）")

    if not ((contact and contact.default_language) or (customer and customer.default_language)):
        missing.append("language")
        reasons.append("缺少语言依据：联系人与客户均未记录首选语言")
    if not ((contact and contact.timezone) or (customer and customer.timezone)):
        missing.append("timezone")
        reasons.append("缺少时区：联系人与客户均未记录 IANA 时区")

    cooldown_days = get_settings().MAIL_OUTREACH_RECIPIENT_COOLDOWN_DAYS
    recent_job = db.query(MailOutreachSendJob).filter(
        MailOutreachSendJob.to_contact_point_id == contact_point_id,
        MailOutreachSendJob.status.in_(_COOLDOWN_JOB_STATUSES),
        MailOutreachSendJob.created_at >= beijing_now() - timedelta(days=cooldown_days),
    ).order_by(MailOutreachSendJob.id.desc()).first()
    if recent_job is not None:
        missing.append("recipient_cooldown")
        reasons.append(
            f"收件人冷却期（{cooldown_days} 天）内已存在在途/已接受任务 job#{recent_job.id}"
        )

    return {"eligible": not missing, "missing": missing, "reasons": reasons}


__all__ = ["evaluate_email_eligibility"]
