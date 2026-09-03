"""内贸客户预存余额与订单扣款账本。

所有余额变化都先锁客户行，再同时写余额与账本；调用方负责最终 commit。
订单金额变化走差额补扣/退回，避免编辑数量或单价后余额与订单脱节。
先下单后付款（settle_mode='credit'）的客户允许负余额——负余额即欠款，
后续充值自动冲抵；先充值后下单（prepay，默认）的客户余额不得为负。
"""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.domestic import constants as C
from app.domestic.models import (
    DomesticCustomer,
    DomesticCustomerLedger,
    DomesticOrder,
    DomesticOrderItem,
)
from app.domestic.pricing_service import membership_label, resolve_membership


_CENT = Decimal("0.01")
_MAX_MONEY = Decimal("999999999999.99")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def order_total(db: Session, order_id: int) -> Decimal:
    rows = db.query(DomesticOrderItem.order_qty, DomesticOrderItem.unit_price).filter(
        DomesticOrderItem.order_id == order_id
    ).all()
    total = money(sum((money(price) * qty for qty, price in rows), Decimal("0.00")))
    if total > _MAX_MONEY:
        raise ValueError("订单总金额超过系统上限")
    return total


def apply_balance_change(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal,
    transaction_type: str,
    user_id: int,
    order_id: int | None = None,
    remark: str | None = None,
    business_key: str | None = None,
) -> DomesticCustomerLedger | None:
    """Apply one signed balance change. Positive adds funds; negative deducts."""
    amount = money(amount)
    if amount == 0:
        return None

    customer = db.query(DomesticCustomer).filter(
        DomesticCustomer.id == customer_id
    ).populate_existing().with_for_update().first()
    if not customer:
        raise ValueError("客户不存在")

    # Customer row lock serializes same-customer requests. Recheck the key only after
    # acquiring it so two concurrent retries cannot both change the balance.
    if business_key:
        existing = db.query(DomesticCustomerLedger).filter(
            DomesticCustomerLedger.business_key == business_key
        ).with_for_update().first()
        if existing:
            if money(existing.amount) != amount:
                raise ValueError("同一幂等键已用于不同金额，请刷新后重试")
            existing._balance_replayed = True
            return existing

    before = money(customer.balance)
    after = money(before + amount)
    # 先下单后付款（credit）客户允许负余额：负数即欠款，之后充值自动冲抵；
    # prepay 客户维持「余额不得为负」的硬校验。
    if after < 0 and customer.settle_mode != "credit":
        raise ValueError(
            f"客户「{customer.shop_name}」余额不足：当前 ¥{before:.2f}，本次需扣 ¥{-amount:.2f}"
        )
    if after > _MAX_MONEY:
        raise ValueError("客户余额超过系统上限")

    customer.balance = after
    ledger = DomesticCustomerLedger(
        customer_id=customer.id,
        order_id=order_id,
        transaction_type=transaction_type,
        amount=amount,
        balance_before=before,
        balance_after=after,
        business_key=business_key,
        remark=remark,
        created_by=user_id,
    )
    db.add(ledger)
    db.flush()
    return ledger


def recharge_customer(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal,
    user_id: int,
    remark: str | None = None,
    request_id: str | None = None,
) -> dict:
    request_id = request_id.strip() if isinstance(request_id, str) else ""
    if not request_id:
        raise ValueError("充值幂等键不能为空")
    if not 8 <= len(request_id) <= 64:
        raise ValueError("充值幂等键长度必须为 8 到 64 个字符")
    amount = money(amount)
    if amount <= 0:
        raise ValueError("充值金额必须大于 0")
    business_key = f"recharge:{customer_id}:{request_id}"
    customer = db.query(DomesticCustomer).filter(
        DomesticCustomer.id == customer_id,
    ).populate_existing().with_for_update().first()
    if not customer:
        raise ValueError("客户不存在")
    if customer.owner_user_id != user_id:
        raise ValueError("客户不存在")
    ledger = apply_balance_change(
        db,
        customer_id=customer_id,
        amount=amount,
        transaction_type="recharge",
        user_id=user_id,
        remark=remark,
        business_key=business_key,
    )
    replayed = bool(getattr(ledger, "_balance_replayed", False))
    customer = db.query(DomesticCustomer).filter(
        DomesticCustomer.id == customer_id
    ).one()
    membership_change = None
    if not replayed:
        previous_level = customer.membership_level
        current_level = resolve_membership(amount)
        if current_level != previous_level:
            membership_change = {"from": previous_level, "to": current_level}
        customer.membership_level = current_level
        customer.last_recharge_amount = amount
        customer.last_recharged_at = ledger.created_at
    db.commit()
    return {
        "ledger_id": ledger.id,
        "amount": float(ledger.amount),
        "ledger_balance_after": float(ledger.balance_after),
        "current_balance": float(customer.balance),
        "membership_level": customer.membership_level,
        "membership_label": membership_label(customer.membership_level),
        "last_recharge_amount": (
            float(customer.last_recharge_amount)
            if customer.last_recharge_amount is not None
            else None
        ),
        "last_recharged_at": customer.last_recharged_at,
        "membership_change": membership_change,
        "replayed": replayed,
    }


def sync_order_finance(
    db: Session,
    order: DomesticOrder,
    *,
    user_id: int,
    reason: str,
) -> Decimal:
    """Recalculate total and, for submitted orders, settle the charge delta."""
    total = order_total(db, order.id)
    order.total_amount = total
    if order.status in (C.ORDER_DRAFT, C.ORDER_TERMINATED):
        return total

    charged = money(order.charged_amount)
    delta = money(total - charged)
    if delta:
        transaction_type = "order_charge" if charged == 0 and delta > 0 else "order_adjustment"
        apply_balance_change(
            db,
            customer_id=order.customer_id,
            amount=-delta,
            transaction_type=transaction_type,
            user_id=user_id,
            order_id=order.id,
            remark=reason,
        )
    order.charged_amount = total
    return total


def refund_order_charge(
    db: Session,
    order: DomesticOrder,
    *,
    user_id: int,
    reason: str,
) -> Decimal:
    charged = money(order.charged_amount)
    if charged <= 0:
        return Decimal("0.00")
    apply_balance_change(
        db,
        customer_id=order.customer_id,
        amount=charged,
        transaction_type="order_refund",
        user_id=user_id,
        order_id=order.id,
        remark=reason,
    )
    order.charged_amount = Decimal("0.00")
    return charged


def list_customer_ledger(
    db: Session,
    *,
    customer_id: int,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    if not db.query(DomesticCustomer.id).filter(DomesticCustomer.id == customer_id).first():
        raise ValueError("客户不存在")
    q = db.query(DomesticCustomerLedger).filter(DomesticCustomerLedger.customer_id == customer_id)
    total = q.count()
    rows = q.order_by(
        DomesticCustomerLedger.created_at.desc(), DomesticCustomerLedger.id.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    user_names = dict(db.query(ArkUser.id, ArkUser.real_name).filter(
        ArkUser.id.in_({row.created_by for row in rows} or {0})
    ).all())
    order_nos = dict(db.query(DomesticOrder.id, DomesticOrder.domestic_no).filter(
        DomesticOrder.id.in_({row.order_id for row in rows if row.order_id} or {0})
    ).all())
    return [{
        "id": row.id,
        "transaction_type": row.transaction_type,
        "amount": float(row.amount),
        "balance_before": float(row.balance_before),
        "balance_after": float(row.balance_after),
        "order_id": row.order_id,
        "domestic_no": order_nos.get(row.order_id),
        "remark": row.remark,
        "created_by_name": user_names.get(row.created_by),
        "created_at": row.created_at,
    } for row in rows], total
