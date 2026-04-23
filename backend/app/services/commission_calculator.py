"""季度提成计算引擎 + 批次作废/确认"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.commission import (
    CommissionBatch, CommissionDetail, SyncedPayment, PaymentCommissionStatus,
)
from app.models.customer import CustomerCommissionSnapshot

logger = logging.getLogger("commission.calc")


@dataclass
class CalcResult:
    """提成计算结果"""
    total_payments: int = 0
    total_salesperson_commission: Decimal = Decimal("0")
    total_supervisor_commission: Decimal = Decimal("0")
    total_second_supervisor_commission: Decimal = Decimal("0")
    skipped_incomplete: int = 0
    skipped_no_snapshot: int = 0
    errors: list = field(default_factory=list)


def calculate_commission(db: Session, batch_id: int) -> CalcResult:
    """
    对指定批次执行提成计算。

    前置条件：batch status='draft'，对应日期范围的回款已同步。

    Args:
        db: 数据库 Session
        batch_id: 批次 ID

    Returns:
        CalcResult 计算结果摘要
    """
    result = CalcResult()

    # ---- Step 1: 获取批次 ----
    batch = db.query(CommissionBatch).filter(CommissionBatch.id == batch_id).first()
    if not batch:
        raise ValueError(f"批次 {batch_id} 不存在")
    if batch.status != "draft":
        raise ValueError(f"批次状态为 '{batch.status}'，只有 'draft' 可计算")

    period_start = batch.period_start
    period_end = batch.period_end
    logger.info(f"开始计算批次 {batch_id}: {period_start} ~ {period_end}")

    # ---- Step 2: 获取待计算回款（排除已计算的） ----
    already_calculated = (
        db.query(PaymentCommissionStatus.payment_id)
        .subquery()
    )
    pending_payments = (
        db.query(SyncedPayment)
        .filter(
            SyncedPayment.payment_date >= period_start,
            SyncedPayment.payment_date <= period_end,
            ~SyncedPayment.payment_id.in_(
                db.query(already_calculated.c.payment_id)
            ),
        )
        .all()
    )
    logger.info(f"待计算回款 {len(pending_payments)} 条")

    # ---- Step 3: 预加载客户归属快照 ----
    customer_ids = list({p.customer_id for p in pending_payments})
    snapshots_q = (
        db.query(CustomerCommissionSnapshot)
        .filter(
            CustomerCommissionSnapshot.customer_id.in_(customer_ids),
            CustomerCommissionSnapshot.is_current == True,
        )
        .all()
    )
    snapshot_map: dict[str, CustomerCommissionSnapshot] = {
        s.customer_id: s for s in snapshots_q
    }

    # ---- Step 4: 批量计算提成 ----
    detail_rows = []
    status_rows = []

    for payment in pending_payments:
        snapshot = snapshot_map.get(payment.customer_id)

        if not snapshot:
            result.skipped_no_snapshot += 1
            continue

        if not snapshot.is_complete:
            result.skipped_incomplete += 1
            continue

        try:
            amount = Decimal(str(payment.payment_amount))
            fee = Decimal(str(payment.service_fee or 0))
            commission_base = amount - fee

            sp_rate = Decimal(str(snapshot.salesperson_rate))
            sp_commission = commission_base * sp_rate

            sv_id = snapshot.supervisor_id
            sv_rate_val = (
                Decimal(str(snapshot.supervisor_rate))
                if snapshot.supervisor_rate is not None
                else Decimal("0")
            )

            if (
                not sv_id
                or sv_id == snapshot.salesperson_id
                or sv_rate_val == Decimal("0")
            ):
                sv_commission = Decimal("0")
                calc_note = "一级主管兼业务员，仅计业务员提成"
            elif (
                snapshot.salesperson_attribute == "develop"
                and snapshot.supervisor_attribute == "develop"
            ):
                sv_commission = commission_base * Decimal("0.0150")
                calc_note = "双开发，一级主管1.5%"
            else:
                sv_commission = commission_base * sv_rate_val
                calc_note = "一级主管1%"

            sv2_id = snapshot.second_supervisor_id
            sv2_rate_val = (
                Decimal(str(snapshot.second_supervisor_rate))
                if snapshot.second_supervisor_rate is not None
                else Decimal("0")
            )
            if sv2_id and sv2_id != snapshot.salesperson_id and sv2_rate_val > 0:
                sv2_commission = commission_base * sv2_rate_val
                calc_note += "，二级主管0.5%"
            else:
                sv2_commission = Decimal("0")

            detail_rows.append({
                "batch_id": batch_id,
                "payment_id": payment.payment_id,
                "order_id": payment.order_id,
                "customer_id": payment.customer_id,
                "payment_amount": amount,
                "salesperson_id": snapshot.salesperson_id,
                "salesperson_rate": sp_rate,
                "salesperson_commission": sp_commission,
                "supervisor_id": sv_id,
                "supervisor_rate": sv_rate_val if sv_id else None,
                "supervisor_commission": sv_commission,
                "second_supervisor_id": sv2_id,
                "second_supervisor_rate": sv2_rate_val if sv2_id else None,
                "second_supervisor_commission": sv2_commission,
                "calc_rule_note": calc_note,
            })

            status_rows.append({
                "payment_id": payment.payment_id,
                "batch_id": batch_id,
            })

            result.total_payments += 1
            result.total_salesperson_commission += sp_commission
            result.total_supervisor_commission += sv_commission
            result.total_second_supervisor_commission += sv2_commission

        except Exception as e:
            err_msg = f"回款 {payment.payment_id} 计算异常: {e}"
            logger.error(err_msg)
            result.errors.append(err_msg)

    # ---- Step 5: 批量写入 + 更新批次状态 ----
    if detail_rows:
        db.execute(CommissionDetail.__table__.insert(), detail_rows)
    if status_rows:
        db.execute(PaymentCommissionStatus.__table__.insert(), status_rows)
    batch.status = "calculated"
    db.flush()

    logger.info(
        f"批次 {batch_id} 计算完成: "
        f"计算 {result.total_payments} 条, "
        f"业务员合计 {result.total_salesperson_commission}, "
        f"一级主管合计 {result.total_supervisor_commission}, "
        f"二级主管合计 {result.total_second_supervisor_commission}, "
        f"跳过(不完整) {result.skipped_incomplete}, "
        f"跳过(无快照) {result.skipped_no_snapshot}"
    )
    return result


def void_batch(db: Session, batch_id: int) -> None:
    """
    作废批次：释放回款，明细标记 voided。

    仅 status='calculated' 的批次可作废。
    """
    batch = db.query(CommissionBatch).filter(CommissionBatch.id == batch_id).first()
    if not batch:
        raise ValueError(f"批次 {batch_id} 不存在")
    if batch.status != "calculated":
        raise ValueError(f"批次状态为 '{batch.status}'，只有 'calculated' 可作废")

    # 删除回款状态标记（释放回款）
    db.query(PaymentCommissionStatus).filter(
        PaymentCommissionStatus.batch_id == batch_id,
    ).delete(synchronize_session="fetch")

    # 明细标记 voided
    db.query(CommissionDetail).filter(
        CommissionDetail.batch_id == batch_id,
    ).update({"status": "voided"}, synchronize_session="fetch")

    batch.status = "voided"
    db.flush()
    logger.info(f"批次 {batch_id} 已作废")


def confirm_batch(db: Session, batch_id: int, confirmed_by: str) -> None:
    """
    确认批次：明细标记 confirmed。

    仅 status='calculated' 的批次可确认。
    """
    batch = db.query(CommissionBatch).filter(CommissionBatch.id == batch_id).first()
    if not batch:
        raise ValueError(f"批次 {batch_id} 不存在")
    if batch.status != "calculated":
        raise ValueError(f"批次状态为 '{batch.status}'，只有 'calculated' 可确认")

    db.query(CommissionDetail).filter(
        CommissionDetail.batch_id == batch_id,
    ).update({"status": "confirmed"}, synchronize_session="fetch")

    batch.status = "confirmed"
    batch.confirmed_at = datetime.now()
    batch.confirmed_by = confirmed_by
    db.flush()
    logger.info(f"批次 {batch_id} 已确认 (by {confirmed_by})")
