"""展会门店/展位配额充值、扣减与流水查询服务。

本层服务只执行 flush，不 commit；调用方（router / 生图端点）负责在完整业务
事务成功后统一 commit，以便把配额扣减与结果写入等操作打包在同一事务内。
"""

import logging
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.expo.models import ExpoQuotaRecord, ExpoStore
from app.expo.store_service import StoreNotFound

logger = logging.getLogger("commission.expo.quota")


class InsufficientQuota(Exception):
    """配额不足，无法扣减。"""


def _current_balance(store: ExpoStore) -> int:
    """计算门店当前可用余额。"""
    return store.total_quota - store.used_quota


def _validate_positive_amount(amount: int) -> None:
    """校验 amount 为正整数。"""
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("amount 必须是正整数")


def get_quota(db: Session, store_id: int) -> dict:
    """获取门店配额快照。

    以 ExpoStore 上的 total_quota / used_quota 为权威读数，
    流水表仅用于审计与历史追溯。
    """
    store = db.get(ExpoStore, store_id)
    if store is None:
        raise StoreNotFound(f"门店 {store_id} 不存在")
    return {
        "store_id": store.id,
        "total_quota": store.total_quota,
        "used_quota": store.used_quota,
        "remaining": _current_balance(store),
    }


def recharge_quota(
    db: Session,
    *,
    store_id: int,
    amount: int,
    operator_user_id: int,
    remark: Optional[str] = None,
) -> ExpoQuotaRecord:
    """为门店充值配额。

    增加 store.total_quota，并写入一条 type='recharge'、amount>0 的流水。
    只 flush，不 commit；调用方负责最终 commit。

    注意：flush 失败时会执行 db.rollback()，调用方应将其视为事务边界，
    或自行使用 savepoint 隔离。
    """
    _validate_positive_amount(amount)

    stmt = (
        select(ExpoStore)
        .where(ExpoStore.id == store_id)
        .with_for_update()
    )
    store = db.execute(stmt).scalar_one_or_none()
    if store is None:
        raise StoreNotFound(f"门店 {store_id} 不存在")

    balance_before = _current_balance(store)
    balance_after = balance_before + amount

    store.total_quota += amount

    record = ExpoQuotaRecord(
        store_id=store_id,
        type="recharge",
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        operator_user_id=operator_user_id,
        remark=remark,
    )
    db.add(record)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        msg = f"[expo] recharge_quota 数据冲突 store={store_id} amount={amount}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise ValueError(f"充值失败，门店或操作人不存在: {exc}") from None
    except SQLAlchemyError as exc:
        db.rollback()
        msg = f"[expo] recharge_quota 失败 store={store_id} amount={amount}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise

    db.refresh(record)
    return record


def deduct_quota(
    db: Session,
    *,
    store_id: int,
    amount: int,
    operator_user_id: int,
    related_id: Optional[int] = None,
    related_type: Optional[str] = None,
    remark: Optional[str] = None,
) -> ExpoQuotaRecord:
    """从门店扣减配额。

    增加 store.used_quota，并写入一条 type='deduct'、amount<0 的流水。
    使用 with_for_update() 锁定门店行，防止并发超扣。
    只 flush，不 commit；调用方负责最终 commit。

    注意：flush 失败时会执行 db.rollback()，调用方应将其视为事务边界，
    或自行使用 savepoint 隔离。
    """
    _validate_positive_amount(amount)

    stmt = (
        select(ExpoStore)
        .where(ExpoStore.id == store_id)
        .with_for_update()
    )
    store = db.execute(stmt).scalar_one_or_none()
    if store is None:
        raise StoreNotFound(f"门店 {store_id} 不存在")

    balance_before = _current_balance(store)
    balance_after = balance_before - amount
    if balance_after < 0:
        raise InsufficientQuota(
            f"门店 {store_id} 配额不足，余额 {balance_before}，需扣减 {amount}"
        )

    store.used_quota += amount

    record = ExpoQuotaRecord(
        store_id=store_id,
        type="deduct",
        amount=-amount,
        balance_before=balance_before,
        balance_after=balance_after,
        related_id=related_id,
        related_type=related_type,
        operator_user_id=operator_user_id,
        remark=remark,
    )
    db.add(record)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        msg = f"[expo] deduct_quota 数据冲突 store={store_id} amount={amount}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise ValueError(f"扣减失败，门店或操作人不存在: {exc}") from None
    except SQLAlchemyError as exc:
        db.rollback()
        msg = f"[expo] deduct_quota 失败 store={store_id} amount={amount}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise

    db.refresh(record)
    return record


def list_quota_records(
    db: Session,
    store_id: int,
    *,
    type_: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[ExpoQuotaRecord], int]:
    """分页查询门店配额变动流水。

    可按 type 过滤；返回 (rows, total)。排序按 created_at 降序，保证同一秒内
    的先后顺序仍与写入顺序一致（created_at 精度为秒时 id 作为次级排序不可靠，
    但 ExpoQuotaRecord.id 自增且与写入顺序严格一致，此处优先业务语义）。
    """
    if type_ is not None and type_ not in {"recharge", "deduct"}:
        raise ValueError(f"type_ 必须是 recharge 或 deduct， got {type_}")

    stmt = select(ExpoQuotaRecord).where(ExpoQuotaRecord.store_id == store_id)
    if type_:
        stmt = stmt.where(ExpoQuotaRecord.type == type_)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    rows = db.execute(
        stmt.order_by(ExpoQuotaRecord.created_at.desc(), ExpoQuotaRecord.id.desc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    return rows, total
