"""回款增量同步 + 客户归属校验服务"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rule_config import build_order_match_query
from app.models.commission import SyncedPayment
from app.models.customer import CustomerCommissionSnapshot
from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.services.rate_utils import calc_commission_rates, to_date

logger = logging.getLogger("commission.sync")


@dataclass
class SyncResult:
    """回款同步结果"""
    total_payments: int = 0
    new_synced: int = 0
    already_synced: int = 0
    customers_checked: int = 0
    snapshots_auto_created: int = 0
    snapshots_incomplete: int = 0
    incomplete_customers: list = field(default_factory=list)


def _get_employee_attribute(db: Session, employee_id: str) -> Optional[str]:
    """查询员工当前属性（develop/distribute）"""
    row = db.query(EmployeeAttributeHistory).filter(
        EmployeeAttributeHistory.employee_id == employee_id,
        EmployeeAttributeHistory.is_current == True,
    ).first()
    return row.attribute_type if row else None


def _get_supervisor_id(db: Session, salesperson_id: str) -> Optional[str]:
    """查询业务员当前主管ID"""
    row = db.query(SupervisorRelationHistory).filter(
        SupervisorRelationHistory.salesperson_id == salesperson_id,
        SupervisorRelationHistory.is_current == True,
    ).first()
    return row.supervisor_id if row else None


def _find_matching_order(db: Session, customer_id: str) -> Optional[dict]:
    """按配置规则在业务库中查找匹配订单（首单优先）"""
    sql = build_order_match_query(customer_id)
    result = db.execute(text(sql)).mappings().first()
    if result:
        return dict(result)
    return None


def _get_order_by_id(db: Session, order_id: str) -> Optional[dict]:
    """从业务库按 order_id 查询订单"""
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME
    sql = f"SELECT * FROM `{schema}`.`okki_orders` WHERE `order_id` = :oid LIMIT 1"
    result = db.execute(text(sql), {"oid": order_id}).mappings().first()
    if result:
        return dict(result)
    return None


def _create_complete_snapshot(
    db: Session,
    customer_id: str,
    order: dict,
    source: str = "auto",
) -> CustomerCommissionSnapshot:
    """根据匹配订单创建完整归属快照"""
    salesperson_id = str(order["user_id"])

    sp_attr = _get_employee_attribute(db, salesperson_id)
    supervisor_id = _get_supervisor_id(db, salesperson_id)
    sv_attr = _get_employee_attribute(db, supervisor_id) if supervisor_id else None

    sp_rate, sv_rate, _ = calc_commission_rates(
        salesperson_id, sp_attr, supervisor_id, sv_attr,
    )

    snapshot = CustomerCommissionSnapshot(
        customer_id=customer_id,
        first_order_id=str(order["order_id"]),
        first_order_date=to_date(order.get("account_date")),
        salesperson_id=salesperson_id,
        salesperson_attribute=sp_attr,
        salesperson_rate=sp_rate,
        supervisor_id=supervisor_id,
        supervisor_attribute=sv_attr,
        supervisor_rate=sv_rate,
        is_complete=True,
        is_current=True,
        source=source,
    )
    db.add(snapshot)
    return snapshot


def _create_incomplete_snapshot(
    db: Session,
    customer_id: str,
    salesperson_id: str,
    supervisor_id: Optional[str],
) -> CustomerCommissionSnapshot:
    """创建不完整归属快照（需人工补充属性和比例）"""
    snapshot = CustomerCommissionSnapshot(
        customer_id=customer_id,
        salesperson_id=salesperson_id,
        supervisor_id=supervisor_id,
        salesperson_attribute=None,
        salesperson_rate=None,
        supervisor_attribute=None,
        supervisor_rate=None,
        is_complete=False,
        is_current=True,
        source="auto",
    )
    db.add(snapshot)
    return snapshot


def sync_payments(db: Session, date_start: date, date_end: date) -> SyncResult:
    """
    回款增量同步 + 客户归属校验。

    从业务库拉取指定日期范围的回款，增量同步到 synced_payment，
    并为没有归属快照的客户尝试自动生成。

    Args:
        db: 数据库 Session
        date_start: 回款日期起始（含）
        date_end: 回款日期结束（含）

    Returns:
        SyncResult 同步结果摘要
    """
    result = SyncResult()
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME

    # ---- Step 1: 从业务库拉取回款 ----
    sql = (
        f"SELECT cash_collection_id, cash_collection_no, collection_date, "
        f"amount_usd, order_id, company_id, order_no, company_name "
        f"FROM `{schema}`.`okki_receipts` "
        f"WHERE `collection_date` >= :ds AND `collection_date` <= :de"
    )
    rows = db.execute(text(sql), {"ds": date_start, "de": date_end}).mappings().all()
    result.total_payments = len(rows)
    logger.info(f"查询到 {len(rows)} 条回款 ({date_start} ~ {date_end})")

    # ---- Step 2: 增量同步 ----
    customer_ids_this_batch: dict[str, list[str]] = {}  # customer_id → [order_id, ...]

    for row in rows:
        pid = str(row["cash_collection_id"])
        existing = db.query(SyncedPayment).filter(SyncedPayment.payment_id == pid).first()
        if existing:
            result.already_synced += 1
            continue

        sp = SyncedPayment(
            payment_id=pid,
            order_id=str(row["order_id"]),
            customer_id=str(row["company_id"]),
            payment_date=to_date(row["collection_date"]),
            payment_amount=Decimal(str(row["amount_usd"])),
        )
        db.add(sp)
        result.new_synced += 1

        cid = str(row["company_id"])
        customer_ids_this_batch.setdefault(cid, []).append(str(row["order_id"]))

    db.flush()
    logger.info(f"新增同步 {result.new_synced} 条，跳过已同步 {result.already_synced} 条")

    # ---- Step 3: 客户归属校验 ----
    unique_customers = set(customer_ids_this_batch.keys())
    result.customers_checked = len(unique_customers)

    for cid in unique_customers:
        # 检查是否已有当前有效快照
        existing_snap = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.customer_id == cid,
            CustomerCommissionSnapshot.is_current == True,
        ).first()
        if existing_snap:
            continue  # 情况A：已有快照，跳过

        # 情况B：无快照，尝试自动生成
        try:
            # B-1: 按配置规则查找匹配订单
            matched_order = _find_matching_order(db, cid)
            if matched_order:
                _create_complete_snapshot(db, cid, matched_order, source="auto")
                result.snapshots_auto_created += 1
                logger.info(f"客户 {cid} 自动生成完整归属快照（匹配订单 {matched_order['order_id']}）")
                continue

            # B-2: 无匹配订单，从回款关联的订单取人员
            order_ids = customer_ids_this_batch[cid]
            fallback_order = None
            for oid in order_ids:
                fallback_order = _get_order_by_id(db, oid)
                if fallback_order:
                    break

            if fallback_order and fallback_order.get("user_id"):
                sp_id = str(fallback_order["user_id"])
                sv_id = _get_supervisor_id(db, sp_id)
                _create_incomplete_snapshot(db, cid, sp_id, sv_id)
                result.snapshots_incomplete += 1
                result.incomplete_customers.append(cid)
                logger.warning(f"客户 {cid} 生成不完整归属快照（需人工补充）")
            else:
                # 完全找不到任何订单信息
                logger.error(f"客户 {cid} 无法生成归属快照：找不到关联订单")
                result.snapshots_incomplete += 1
                result.incomplete_customers.append(cid)

        except Exception as e:
            logger.error(f"客户 {cid} 归属校验异常: {e}")
            result.incomplete_customers.append(cid)

    db.flush()
    logger.info(
        f"归属校验完成: 自动创建 {result.snapshots_auto_created}, "
        f"不完整 {result.snapshots_incomplete}"
    )

    return result
