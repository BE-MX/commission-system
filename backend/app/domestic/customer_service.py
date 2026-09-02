"""内贸客户 service —— 店名是业务主标识，下单时可就地新建"""

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.domestic import balance_service
from app.domestic import constants as C
from app.domestic.models import DomesticCustomer, DomesticCustomerLedger, DomesticOrder
from app.domestic.pricing_service import membership_label
from app.domestic.schemas import CustomerCreate, CustomerUpdate
from app.system.models import SysDict

logger = logging.getLogger("commission")


# 客户档案可写字段（create/update 共用，财务与启用状态不在内）
CUSTOMER_PROFILE_FIELDS = (
    "province", "city", "contact", "phone", "address",
    "customer_source", "store_type", "customer_level", "lifecycle_status",
    "owner_user_id", "first_contact_date", "first_order_date", "last_order_date",
    "total_order_count", "total_sales_amount", "remark",
)


def get_customer_options(db: Session) -> dict:
    """客户表单下拉值域：来源/门店类型/等级/客户状态（sys_dict）+ 归属销售（在职用户）。"""
    dict_types = [
        C.CUSTOMER_SOURCE_DICT, C.CUSTOMER_STORE_TYPE_DICT,
        C.CUSTOMER_LEVEL_DICT, C.CUSTOMER_LIFECYCLE_DICT,
    ]
    rows = (
        db.query(SysDict)
        .filter(SysDict.type.in_(dict_types), SysDict.is_active.is_(True))
        .order_by(SysDict.type.asc(), SysDict.sort.asc(), SysDict.id.asc())
        .all()
    )
    by_type: dict[str, list[dict]] = {t: [] for t in dict_types}
    for row in rows:
        by_type[row.type].append({"value": row.code, "label": row.label})

    owners = (
        db.query(ArkUser.id, ArkUser.real_name)
        .filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
        .order_by(ArkUser.real_name.asc())
        .all()
    )
    return {
        "customer_source": by_type[C.CUSTOMER_SOURCE_DICT],
        "store_type": by_type[C.CUSTOMER_STORE_TYPE_DICT],
        "customer_level": by_type[C.CUSTOMER_LEVEL_DICT],
        "lifecycle_status": by_type[C.CUSTOMER_LIFECYCLE_DICT],
        "owners": [{"value": uid, "label": name} for uid, name in owners],
    }


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
    initialized_ids = set()
    owner_names: dict[int, str] = {}
    if rows:
        row_ids = [r.id for r in rows]
        order_counts = dict(
            db.query(DomesticOrder.customer_id, func.count(DomesticOrder.id))
            .filter(
                DomesticOrder.customer_id.in_(row_ids),
                DomesticOrder.deleted_flag == 0,
            )
            .group_by(DomesticOrder.customer_id)
            .all()
        )
        initialized_ids = {
            cid for (cid,) in db.query(DomesticCustomerLedger.customer_id)
            .filter(DomesticCustomerLedger.customer_id.in_(row_ids))
            .distinct()
        }
        owner_ids = {r.owner_user_id for r in rows if r.owner_user_id}
        if owner_ids:
            owner_names = dict(
                db.query(ArkUser.id, ArkUser.real_name)
                .filter(ArkUser.id.in_(owner_ids))
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
        "customer_source": r.customer_source,
        "store_type": r.store_type,
        "customer_level": r.customer_level,
        "lifecycle_status": r.lifecycle_status,
        "owner_user_id": r.owner_user_id,
        "owner_name": owner_names.get(r.owner_user_id),
        "first_contact_date": r.first_contact_date.isoformat() if r.first_contact_date else None,
        "first_order_date": r.first_order_date.isoformat() if r.first_order_date else None,
        "last_order_date": r.last_order_date.isoformat() if r.last_order_date else None,
        "total_order_count": r.total_order_count,
        "total_sales_amount": (
            float(r.total_sales_amount) if r.total_sales_amount is not None else None
        ),
        "remark": r.remark,
        "status": r.status,
        "balance": float(r.balance or 0),
        "order_count": order_counts.get(r.id, 0),
        "initialized": r.id in initialized_ids,
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


def _validate_owner(db: Session, owner_user_id: int | None) -> None:
    # 刻意只校验存在性、不卡 is_active：停用用户名下仍可能有历史归属客户需要保留/转移
    if owner_user_id is None:
        return
    if not db.query(ArkUser.id).filter(ArkUser.id == owner_user_id).first():
        raise ValueError("归属销售用户不存在")


def create_customer(db: Session, payload: CustomerCreate, user_id: int) -> DomesticCustomer:
    if db.query(DomesticCustomer).filter(DomesticCustomer.shop_name == payload.shop_name).first():
        raise ValueError(f"客户「{payload.shop_name}」已存在")
    if payload.custom_code and db.query(DomesticCustomer).filter(
        DomesticCustomer.custom_code == payload.custom_code
    ).first():
        raise ValueError(f"客户编码「{payload.custom_code}」已存在")
    _validate_owner(db, payload.owner_user_id)
    customer = DomesticCustomer(
        shop_name=payload.shop_name,
        custom_code=payload.custom_code,
        **{f: getattr(payload, f) for f in CUSTOMER_PROFILE_FIELDS},
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
    if "owner_user_id" in data:
        _validate_owner(db, data["owner_user_id"])
    for field in (*CUSTOMER_PROFILE_FIELDS, "status"):
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


# ── 等级与余额的初始化 / 临时调整（仅 domestic:admin）──────────────


def _customer_snapshot(customer: DomesticCustomer, *, replayed: bool = False) -> dict:
    return {
        "id": customer.id,
        "current_balance": float(customer.balance or 0),
        "membership_level": customer.membership_level,
        "membership_label": membership_label(customer.membership_level),
        "replayed": replayed,
    }


def _lock_customer_row(db: Session, customer_id: int) -> DomesticCustomer:
    customer = db.query(DomesticCustomer).filter(
        DomesticCustomer.id == customer_id
    ).populate_existing().with_for_update().first()
    if customer is None:
        raise ValueError("客户不存在")
    return customer


def initialize_customer(
    db: Session, customer_id: int, payload, user_id: int
) -> dict:
    """期初初始化：只在客户还没有任何资金流水时允许，幂等键固定在客户上。

    等级在这里是显式指定而非充值派生——老客户线下已有余额/约定等级，
    建档时一次写入；之后的充值仍按金额重新核定等级。
    """
    customer = _lock_customer_row(db, customer_id)
    amount = balance_service.money(payload.balance)
    business_key = f"init:{customer.id}"
    existing = db.query(DomesticCustomerLedger).filter(
        DomesticCustomerLedger.business_key == business_key
    ).first()
    if existing is not None:
        if balance_service.money(existing.amount) != amount:
            raise ValueError("该客户已初始化过不同金额，不能重复初始化；请用「临时调整」")
        return _customer_snapshot(customer, replayed=True)
    ledger_count = db.query(func.count(DomesticCustomerLedger.id)).filter(
        DomesticCustomerLedger.customer_id == customer.id
    ).scalar() or 0
    if ledger_count:
        raise ValueError("该客户已有余额流水，不能初始化；请用「临时调整」")

    if amount > 0:
        balance_service.apply_balance_change(
            db,
            customer_id=customer.id,
            amount=amount,
            transaction_type="init",
            user_id=user_id,
            remark=payload.remark or "期初余额初始化",
            business_key=business_key,
        )
        db.refresh(customer)
    if "membership_level" in payload.model_fields_set:
        customer.membership_level = payload.membership_level
    db.commit()
    return _customer_snapshot(customer)


def adjust_customer(
    db: Session, customer_id: int, payload, user_id: int
) -> dict:
    """临时调整：余额可有符号增减，会员等级可显式覆盖或取消。

    等级覆盖是临时的——下一次成功充值仍按当次金额重新核定等级。
    幂等：同一 request_id 重放返回首个结果，不重复入账、不重复写审计行。
    """
    customer = _lock_customer_row(db, customer_id)
    amount = balance_service.money(payload.amount)
    change_level = "membership_level" in payload.model_fields_set
    if amount == 0 and not change_level:
        raise ValueError("没有需要调整的内容：请填余额调整额或选择会员等级")

    business_key = f"adjust:{customer.id}:{payload.request_id}"
    existing = db.query(DomesticCustomerLedger).filter(
        DomesticCustomerLedger.business_key == business_key
    ).first()
    if existing is not None:
        if balance_service.money(existing.amount) != amount:
            raise ValueError("该调整请求号已用于不同金额，请刷新后重新操作")
        return _customer_snapshot(customer, replayed=True)

    if amount != 0:
        balance_service.apply_balance_change(
            db,
            customer_id=customer.id,
            amount=amount,
            transaction_type="adjust",
            user_id=user_id,
            remark=payload.remark,
            business_key=business_key,
        )
        db.refresh(customer)
    if change_level and customer.membership_level != payload.membership_level:
        # 等级变化落一条零金额审计行，和资金流水在同一条时间线上可查。
        # 只调等级时它同时充当幂等行（占住 business_key）。
        db.add(DomesticCustomerLedger(
            customer_id=customer.id,
            transaction_type="level_adjust",
            amount=0,
            balance_before=customer.balance,
            balance_after=customer.balance,
            business_key=(
                None if amount != 0 else business_key
            ),
            remark=(
                f"会员等级临时调整：{membership_label(customer.membership_level)}"
                f" → {membership_label(payload.membership_level)}；{payload.remark}"
            ),
            created_by=user_id,
        ))
        customer.membership_level = payload.membership_level
    db.commit()
    return _customer_snapshot(customer)
