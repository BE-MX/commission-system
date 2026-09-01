"""内贸客户 service —— 店名是业务主标识，下单时可就地新建"""

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domestic.models import DomesticCustomer, DomesticCustomerLedger, DomesticOrder
from app.domestic.pricing_service import membership_label
from app.domestic.schemas import CustomerCreate, CustomerUpdate

logger = logging.getLogger("commission")


def list_customers(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    status: int | None = None,
) -> tuple[list[dict], int]:
    q = db.query(DomesticCustomer)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(
            (DomesticCustomer.shop_name.like(kw))
            | (DomesticCustomer.custom_code.like(kw))
            | (DomesticCustomer.contact.like(kw))
            | (DomesticCustomer.phone.like(kw))
        )
    if status is not None:
        q = q.filter(DomesticCustomer.status == status)

    total = q.count()
    rows = q.order_by(DomesticCustomer.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    order_counts = {}
    if rows:
        order_counts = dict(
            db.query(DomesticOrder.customer_id, func.count(DomesticOrder.id))
            .filter(
                DomesticOrder.customer_id.in_([r.id for r in rows]),
                DomesticOrder.deleted_flag == 0,
            )
            .group_by(DomesticOrder.customer_id)
            .all()
        )

    items = [{
        "id": r.id,
        "shop_name": r.shop_name,
        "custom_code": r.custom_code,
        "membership_level": r.membership_level,
        "membership_label": membership_label(r.membership_level),
        "last_recharge_amount": (
            float(r.last_recharge_amount)
            if r.last_recharge_amount is not None
            else None
        ),
        "last_recharged_at": r.last_recharged_at,
        "province": r.province,
        "city": r.city,
        "contact": r.contact,
        "phone": r.phone,
        "address": r.address,
        "remark": r.remark,
        "status": r.status,
        "balance": float(r.balance or 0),
        "order_count": order_counts.get(r.id, 0),
        "created_at": r.created_at,
    } for r in rows]
    return items, total


def find_or_create_by_shop_name(db: Session, shop_name: str, user_id: int) -> DomesticCustomer:
    """下单时就地新建客户走这里。同名视为同一客户。"""
    name = (shop_name or "").strip()
    if not name:
        raise ValueError("客户店名不能为空")

    existing = db.query(DomesticCustomer).filter(DomesticCustomer.shop_name == name).first()
    if existing:
        return existing

    customer = DomesticCustomer(shop_name=name, status=1, created_by=user_id)
    # savepoint 而非 db.rollback()：下单链路上全事务回滚会牵连已落库的其他行
    savepoint = db.begin_nested()
    db.add(customer)
    try:
        db.flush()
        savepoint.commit()
    except IntegrityError:
        # 并发：两笔下单同时新建同一店名，撞 unique 后改取已存在的行
        savepoint.rollback()
        logger.warning("domestic customer race on shop_name=%s, refetch", name)
        print(f"[domestic] customer race shop_name={name}, refetch", flush=True)
        existing = db.query(DomesticCustomer).filter(DomesticCustomer.shop_name == name).first()
        if existing is None:  # 理论不可达
            raise
        return existing
    return customer


def create_customer(db: Session, payload: CustomerCreate, user_id: int) -> DomesticCustomer:
    if db.query(DomesticCustomer).filter(DomesticCustomer.shop_name == payload.shop_name).first():
        raise ValueError(f"客户「{payload.shop_name}」已存在")
    if payload.custom_code and db.query(DomesticCustomer).filter(
        DomesticCustomer.custom_code == payload.custom_code
    ).first():
        raise ValueError(f"客户编码「{payload.custom_code}」已存在")
    customer = DomesticCustomer(
        shop_name=payload.shop_name,
        custom_code=payload.custom_code,
        province=payload.province,
        city=payload.city,
        contact=payload.contact,
        phone=payload.phone,
        address=payload.address,
        remark=payload.remark,
        balance=0,
        status=1,
        created_by=user_id,
    )
    db.add(customer)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("客户店名或客户编码已存在") from exc
    return customer


def update_customer(db: Session, customer_id: int, payload: CustomerUpdate) -> DomesticCustomer:
    customer = db.query(DomesticCustomer).filter(
        DomesticCustomer.id == customer_id
    ).with_for_update().first()
    if not customer:
        raise ValueError("客户不存在")

    data = payload.model_dump(exclude_unset=True)
    new_name = (data.get("shop_name") or "").strip()
    if new_name and new_name != customer.shop_name:
        if db.query(DomesticCustomer).filter(DomesticCustomer.shop_name == new_name).first():
            raise ValueError(f"客户「{new_name}」已存在")
        customer.shop_name = new_name
    if "custom_code" in data and data["custom_code"] != customer.custom_code:
        if data["custom_code"] and db.query(DomesticCustomer).filter(
            DomesticCustomer.custom_code == data["custom_code"],
            DomesticCustomer.id != customer.id,
        ).first():
            raise ValueError(f"客户编码「{data['custom_code']}」已存在")
        customer.custom_code = data["custom_code"]
    for field in (
        "province", "city", "contact", "phone", "address", "remark", "status",
    ):
        if field in data:
            setattr(customer, field, data[field])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("客户店名或客户编码已存在") from exc
    return customer


def delete_customer(db: Session, customer_id: int) -> None:
    """有订单的客户不删只停用 —— 删了历史订单就查不到客户名了。"""
    customer = db.query(DomesticCustomer).filter(
        DomesticCustomer.id == customer_id
    ).with_for_update().first()
    if not customer:
        raise ValueError("客户不存在")
    used = db.query(func.count(DomesticOrder.id)).filter(
        DomesticOrder.customer_id == customer_id
    ).scalar()
    if used:
        raise ValueError(f"该客户下已有 {used} 张订单，不能删除；可改为停用")
    ledger_count = db.query(func.count(DomesticCustomerLedger.id)).filter(
        DomesticCustomerLedger.customer_id == customer_id
    ).scalar() or 0
    if ledger_count:
        raise ValueError(f"该客户已有 {ledger_count} 条充值或资金流水，不能删除；可改为停用")
    db.delete(customer)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("客户已有业务记录，不能删除；可改为停用") from exc
