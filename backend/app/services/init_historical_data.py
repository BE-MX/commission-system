"""存量数据初始化服务"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rule_config import build_order_match_query
from app.models.commission import (
    CommissionBatch, SyncedPayment, PaymentCommissionStatus,
)
from app.models.customer import CustomerCommissionSnapshot
from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.services.rate_utils import calc_commission_rates, to_date

logger = logging.getLogger("commission.init")


@dataclass
class InitResult:
    """初始化结果摘要"""
    employees_synced: int = 0
    supervisors_synced: int = 0
    snapshots_created: int = 0
    snapshots_incomplete: int = 0
    payments_synced: int = 0
    payments_marked: int = 0
    errors: list = field(default_factory=list)


def _get_employee_attribute(db: Session, employee_id: str) -> Optional[str]:
    row = db.query(EmployeeAttributeHistory).filter(
        EmployeeAttributeHistory.employee_id == employee_id,
        EmployeeAttributeHistory.is_current == True,
    ).first()
    return row.attribute_type if row else None


def _get_supervisor_id(db: Session, salesperson_id: str) -> Optional[str]:
    row = db.query(SupervisorRelationHistory).filter(
        SupervisorRelationHistory.salesperson_id == salesperson_id,
        SupervisorRelationHistory.is_current == True,
    ).first()
    return row.supervisor_id if row else None


def _get_second_supervisor_id(db: Session, salesperson_id: str) -> Optional[str]:
    row = db.query(SupervisorRelationHistory).filter(
        SupervisorRelationHistory.salesperson_id == salesperson_id,
        SupervisorRelationHistory.is_current == True,
    ).first()
    return row.second_supervisor_id if row else None


def init_customer_snapshots(db: Session, dry_run: bool = False) -> int:
    """
    Step 3: 为存量客户生成归属快照。

    遍历业务库订单，按配置规则匹配，为每个客户生成快照。
    幂等：已有 is_current=True 快照的客户跳过。

    Returns:
        生成的快照数量
    """
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME

    # 获取所有有订单的客户
    sql = f"SELECT DISTINCT company_id FROM `{schema}`.`okki_orders` WHERE company_id IS NOT NULL"
    rows = db.execute(text(sql)).all()
    customer_ids = [str(r[0]) for r in rows]
    logger.info(f"发现 {len(customer_ids)} 个有订单的客户")

    created = 0
    for cid in customer_ids:
        # 幂等检查
        existing = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.customer_id == cid,
            CustomerCommissionSnapshot.is_current == True,
        ).first()
        if existing:
            continue

        # 按规则匹配订单
        match_sql = build_order_match_query(cid)
        order = db.execute(text(match_sql)).mappings().first()

        if not order:
            continue  # 不符合规则的客户跳过

        order = dict(order)
        sp_id = str(order["user_id"])
        sp_attr = _get_employee_attribute(db, sp_id)
        sv_id = _get_supervisor_id(db, sp_id)
        sv_attr = _get_employee_attribute(db, sv_id) if sv_id else None
        sv2_id = _get_second_supervisor_id(db, sp_id)

        is_complete = sp_attr is not None
        sp_rate, sv_rate, sv2_rate = None, None, None
        if is_complete:
            sp_rate, sv_rate, sv2_rate, _ = calc_commission_rates(sp_id, sp_attr, sv_id, sv_attr, sv2_id)

        if not dry_run:
            snapshot = CustomerCommissionSnapshot(
                customer_id=cid,
                first_order_id=str(order["order_id"]),
                first_order_date=to_date(order.get("account_date")),
                salesperson_id=sp_id,
                salesperson_attribute=sp_attr,
                salesperson_rate=sp_rate,
                supervisor_id=sv_id,
                supervisor_attribute=sv_attr,
                supervisor_rate=sv_rate,
                second_supervisor_id=sv2_id,
                second_supervisor_rate=sv2_rate,
                is_complete=is_complete,
                is_current=True,
                source="init",
            )
            db.add(snapshot)

        created += 1

    if not dry_run:
        db.flush()
    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}客户快照: 创建 {created} 条")
    return created


def init_historical_payments(
    db: Session,
    cutoff_date: date,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Step 4: 同步历史回款并标记为已计算。

    将 cutoff_date 之前的回款同步到 synced_payment，
    创建历史批次并在 payment_commission_status 中标记。

    Returns:
        (synced_count, marked_count)
    """
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME

    # 拉取历史回款
    sql = (
        f"SELECT cash_collection_id, order_id, company_id, collection_date, amount_usd "
        f"FROM `{schema}`.`okki_receipts` "
        f"WHERE collection_date < :cutoff"
    )
    rows = db.execute(text(sql), {"cutoff": cutoff_date}).mappings().all()
    logger.info(f"历史回款 (< {cutoff_date}): {len(rows)} 条")

    synced_count = 0
    payment_ids: list[str] = []

    for row in rows:
        pid = str(row["cash_collection_id"])

        # 幂等
        existing = db.query(SyncedPayment).filter(SyncedPayment.payment_id == pid).first()
        if existing:
            payment_ids.append(pid)
            continue

        if not dry_run:
            sp = SyncedPayment(
                payment_id=pid,
                order_id=str(row["order_id"]),
                customer_id=str(row["company_id"]),
                payment_date=to_date(row["collection_date"]),
                payment_amount=Decimal(str(row["amount_usd"])),
            )
            db.add(sp)

        payment_ids.append(pid)
        synced_count += 1

    if not dry_run:
        db.flush()

    # 创建历史批次
    marked_count = 0
    if payment_ids and not dry_run:
        hist_batch = CommissionBatch(
            batch_name=f"历史数据 (< {cutoff_date})",
            period_type="quarterly",
            period_start=date(2020, 1, 1),
            period_end=cutoff_date,
            status="confirmed",
            created_by="system_init",
            confirmed_at=datetime.now(),
            confirmed_by="system_init",
        )
        db.add(hist_batch)
        db.flush()

        for pid in payment_ids:
            existing_pcs = db.query(PaymentCommissionStatus).filter(
                PaymentCommissionStatus.payment_id == pid,
            ).first()
            if not existing_pcs:
                pcs = PaymentCommissionStatus(
                    payment_id=pid,
                    batch_id=hist_batch.id,
                )
                db.add(pcs)
                marked_count += 1

        db.flush()

    logger.info(
        f"{'[DRY-RUN] ' if dry_run else ''}"
        f"历史回款: 同步 {synced_count}, 标记 {marked_count}"
    )
    return synced_count, marked_count


def run_full_init(
    db: Session,
    cutoff_date: Optional[date] = None,
    dry_run: bool = False,
) -> InitResult:
    """
    执行完整的存量数据初始化。

    Steps:
      1. 员工属性 & 主管关系（需预先通过 Excel 导入，此处仅统计）
      2. 客户归属快照
      3. 历史回款同步 & 标记

    Args:
        db: Session
        cutoff_date: 历史回款截止日期，默认今天
        dry_run: 只输出计划，不写入

    Returns:
        InitResult
    """
    if cutoff_date is None:
        cutoff_date = date.today()

    result = InitResult()
    prefix = "[DRY-RUN] " if dry_run else ""

    logger.info(f"{prefix}开始存量数据初始化, cutoff={cutoff_date}")

    # Step 1: 统计已有的员工属性和主管关系
    result.employees_synced = db.query(EmployeeAttributeHistory).filter(
        EmployeeAttributeHistory.is_current == True
    ).count()
    result.supervisors_synced = db.query(SupervisorRelationHistory).filter(
        SupervisorRelationHistory.is_current == True
    ).count()
    logger.info(
        f"{prefix}Step 1: 员工属性 {result.employees_synced} 条, "
        f"主管关系 {result.supervisors_synced} 条"
    )
    if result.employees_synced == 0:
        logger.warning(f"{prefix}未找到员工属性数据，请先通过 Excel 导入")

    # Step 2: 客户归属快照
    try:
        result.snapshots_created = init_customer_snapshots(db, dry_run=dry_run)
    except Exception as e:
        result.errors.append(f"客户快照初始化异常: {e}")
        logger.error(f"客户快照初始化异常: {e}")

    # Step 3: 历史回款
    try:
        synced, marked = init_historical_payments(db, cutoff_date, dry_run=dry_run)
        result.payments_synced = synced
        result.payments_marked = marked
    except Exception as e:
        result.errors.append(f"历史回款初始化异常: {e}")
        logger.error(f"历史回款初始化异常: {e}")

    logger.info(f"{prefix}初始化完成: {result}")
    return result
