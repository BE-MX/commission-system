"""订单代创建授权与候选业务员。"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.invoice.models import Invoice, InvoiceDelegateGrant


def _active_user_query(db: Session):
    return db.query(ArkUser).filter(
        ArkUser.deleted_at.is_(None),
        ArkUser.is_active.is_(True),
    )


def granted_sales_user_ids(db: Session, delegate_user_id: int) -> set[int]:
    return {
        int(row[0])
        for row in db.query(InvoiceDelegateGrant.sales_user_id).filter(
            InvoiceDelegateGrant.delegate_user_id == delegate_user_id,
        ).all()
    }


def can_act_for(db: Session, delegate_user_id: int, sales_user_id: int) -> bool:
    if delegate_user_id == sales_user_id:
        return _active_user_query(db).filter(ArkUser.id == sales_user_id).first() is not None
    return (
        db.query(InvoiceDelegateGrant.id)
        .join(ArkUser, ArkUser.id == InvoiceDelegateGrant.sales_user_id)
        .filter(
            InvoiceDelegateGrant.delegate_user_id == delegate_user_id,
            InvoiceDelegateGrant.sales_user_id == sales_user_id,
            ArkUser.deleted_at.is_(None),
            ArkUser.is_active.is_(True),
        )
        .first()
        is not None
    )


def ensure_can_delegate(db: Session, delegate_user_id: int, sales_user_id: int) -> ArkUser:
    sales_user = _active_user_query(db).filter(ArkUser.id == sales_user_id).first()
    if sales_user is None:
        raise ValueError("订单归属业务员无效或已停用")
    if not can_act_for(db, delegate_user_id, sales_user_id):
        raise HTTPException(403, "无权替该业务员创建或操作订单")
    return sales_user


def can_access_invoice(db: Session, viewer_user_id: int, invoice: Invoice) -> bool:
    if invoice.sales_user_id == viewer_user_id:
        return True
    return (
        invoice.created_by == viewer_user_id
        and invoice.sales_user_id is not None
        and can_act_for(db, viewer_user_id, invoice.sales_user_id)
    )


def _okki_bound_user_ids(db: Session, user_ids: set[int]) -> set[int]:
    if not user_ids:
        return set()
    return {
        int(user_id)
        for (user_id,) in db.query(ArkUserExternalBinding.ark_user_id).filter(
            ArkUserExternalBinding.ark_user_id.in_(user_ids),
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        ).distinct().all()
    }


def list_assignees(db: Session, delegate_user_id: int) -> list[dict]:
    allowed_ids = granted_sales_user_ids(db, delegate_user_id) | {delegate_user_id}
    users = _active_user_query(db).filter(ArkUser.id.in_(allowed_ids)).order_by(ArkUser.id).all()
    bound_user_ids = _okki_bound_user_ids(db, {user.id for user in users})
    return [
        {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "phone": user.phone,
            "email": user.email,
            "okki_department_id": user.okki_department_id,
            "okki_bound": user.id in bound_user_ids,
            "okki_department_configured": user.okki_department_id is not None,
        }
        for user in users
    ]


def list_grant_candidates(db: Session, delegate_user_id: int) -> list[dict]:
    users = _active_user_query(db).filter(ArkUser.id != delegate_user_id).order_by(ArkUser.real_name).all()
    bound_user_ids = _okki_bound_user_ids(db, {user.id for user in users})
    return [
        {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "okki_bound": user.id in bound_user_ids,
            "okki_department_configured": user.okki_department_id is not None,
        }
        for user in users
    ]


def replace_grants(
    db: Session,
    delegate_user_id: int,
    sales_user_ids: list[int],
    *,
    operator_id: int | None,
) -> None:
    unique_ids = set(sales_user_ids)
    if delegate_user_id in unique_ids:
        raise ValueError("不能授权自己；用户默认可以为自己创建订单")
    if len(unique_ids) != len(sales_user_ids):
        raise ValueError("授权业务员不能重复")
    if unique_ids:
        valid_ids = {
            user_id for (user_id,) in _active_user_query(db)
            .with_entities(ArkUser.id)
            .filter(ArkUser.id.in_(unique_ids)).all()
        }
        if valid_ids != unique_ids:
            raise ValueError("授权业务员包含无效或已停用用户")
    db.query(InvoiceDelegateGrant).filter(
        InvoiceDelegateGrant.delegate_user_id == delegate_user_id,
    ).delete(synchronize_session=False)
    db.add_all([
        InvoiceDelegateGrant(
            delegate_user_id=delegate_user_id,
            sales_user_id=sales_user_id,
            created_by=operator_id,
        )
        for sales_user_id in sorted(unique_ids)
    ])
