"""客户归属重置、快照补全、Excel 导入服务"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.customer import CustomerCommissionSnapshot
from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.services.rate_utils import calc_commission_rates

logger = logging.getLogger("commission.customer")


@dataclass
class ImportResult:
    """Excel 导入结果"""
    total_rows: int = 0
    success: int = 0
    failed: int = 0
    failures: list = field(default_factory=list)


def _get_employee_attribute(db: Session, employee_id: str) -> Optional[str]:
    """查询员工当前属性"""
    row = db.query(EmployeeAttributeHistory).filter(
        EmployeeAttributeHistory.employee_id == employee_id,
        EmployeeAttributeHistory.is_current == True,
    ).first()
    return row.attribute_type if row else None


def _get_supervisor_id(db: Session, salesperson_id: str) -> Optional[str]:
    """查询业务员当前主管"""
    row = db.query(SupervisorRelationHistory).filter(
        SupervisorRelationHistory.salesperson_id == salesperson_id,
        SupervisorRelationHistory.is_current == True,
    ).first()
    return row.supervisor_id if row else None


def _invalidate_current_snapshot(db: Session, customer_id: str) -> None:
    """将客户的当前快照标记失效"""
    db.query(CustomerCommissionSnapshot).filter(
        CustomerCommissionSnapshot.customer_id == customer_id,
        CustomerCommissionSnapshot.is_current == True,
    ).update({"is_current": False}, synchronize_session="fetch")


def _exists_in_business_table(db: Session, table: str, pk_field: str, pk_value: str) -> bool:
    """检查业务库中是否存在指定记录"""
    schema = get_settings().BUSINESS_DB_NAME
    sql = f"SELECT 1 FROM `{schema}`.`{table}` WHERE `{pk_field}` = :v LIMIT 1"
    return db.execute(text(sql), {"v": pk_value}).first() is not None


def reset_customer_attribution(
    db: Session,
    customer_id: str,
    new_salesperson_id: str,
    new_supervisor_id: Optional[str],
    salesperson_attribute: str,
    supervisor_attribute: Optional[str],
    reason: str,
    operator: str,
) -> CustomerCommissionSnapshot:
    """
    人工重置客户归属。

    旧快照 is_current → False，新快照按规则算比例。
    仅影响后续回款。

    Args:
        db: Session
        customer_id: 客户ID
        new_salesperson_id: 新业务员ID
        new_supervisor_id: 新主管ID（可选）
        salesperson_attribute: 业务员属性 develop/distribute
        supervisor_attribute: 主管属性（可选）
        reason: 重置原因
        operator: 操作人

    Returns:
        新创建的快照
    """
    # 旧快照失效
    _invalidate_current_snapshot(db, customer_id)

    # 计算比例
    sp_rate, sv_rate, _ = calc_commission_rates(
        new_salesperson_id, salesperson_attribute,
        new_supervisor_id, supervisor_attribute,
    )

    now = datetime.now()
    snapshot = CustomerCommissionSnapshot(
        customer_id=customer_id,
        salesperson_id=new_salesperson_id,
        salesperson_attribute=salesperson_attribute,
        salesperson_rate=sp_rate,
        supervisor_id=new_supervisor_id,
        supervisor_attribute=supervisor_attribute,
        supervisor_rate=sv_rate,
        is_complete=True,
        is_current=True,
        source="manual",
        is_manual_reset=True,
        reset_reason=reason,
        operator=operator,
        operated_at=now,
    )
    db.add(snapshot)
    db.flush()
    logger.info(f"客户 {customer_id} 归属已重置 (by {operator})")
    return snapshot


def complete_snapshot(
    db: Session,
    snapshot_id: int,
    salesperson_attribute: str,
    supervisor_attribute: Optional[str],
    operator: str,
) -> CustomerCommissionSnapshot:
    """
    补全不完整的归属快照。

    填入属性值，按规则计算提成比例，标记 is_complete=True。

    Args:
        db: Session
        snapshot_id: 快照ID
        salesperson_attribute: 业务员属性 develop/distribute
        supervisor_attribute: 主管属性（可选）
        operator: 操作人

    Returns:
        更新后的快照
    """
    snapshot = db.query(CustomerCommissionSnapshot).filter(
        CustomerCommissionSnapshot.id == snapshot_id,
    ).first()
    if not snapshot:
        raise ValueError(f"快照 {snapshot_id} 不存在")
    if snapshot.is_complete:
        raise ValueError(f"快照 {snapshot_id} 已完整，无需补全")

    sp_rate, sv_rate, _ = calc_commission_rates(
        snapshot.salesperson_id, salesperson_attribute,
        snapshot.supervisor_id, supervisor_attribute,
    )

    snapshot.salesperson_attribute = salesperson_attribute
    snapshot.salesperson_rate = sp_rate
    snapshot.supervisor_attribute = supervisor_attribute
    snapshot.supervisor_rate = sv_rate
    snapshot.is_complete = True
    snapshot.operator = operator
    snapshot.operated_at = datetime.now()
    db.flush()

    logger.info(f"快照 {snapshot_id} (客户 {snapshot.customer_id}) 已补全 (by {operator})")
    return snapshot


def import_snapshots_from_excel(db: Session, file_path: str, operator: str) -> ImportResult:
    """
    从 Excel 文件批量导入客户归属快照。

    Excel 模板列（从第2行开始，第1行为表头）：
      A: 客户ID (company_id)
      B: 业务员ID (user_id)
      C: 业务员属性 (开发/分配)
      D: 业务主管ID (user_id)
      E: 主管属性 (开发/分配)

    Args:
        db: Session
        file_path: Excel 文件路径
        operator: 操作人

    Returns:
        ImportResult 导入结果
    """
    result = ImportResult()

    wb = load_workbook(file_path, data_only=True)
    ws = wb.active

    attr_map = {"开发": "develop", "分配": "distribute"}

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[0]:
            break
        result.total_rows += 1

        try:
            company_id = str(row[0]).strip()
            sp_id = str(row[1]).strip()
            sp_attr_raw = str(row[2]).strip()
            sv_id = str(row[3]).strip() if row[3] else None
            sv_attr_raw = str(row[4]).strip() if row[4] else None

            # 属性映射
            sp_attr = attr_map.get(sp_attr_raw, sp_attr_raw)
            sv_attr = attr_map.get(sv_attr_raw, sv_attr_raw) if sv_attr_raw else None

            # 校验 company_id
            if not _exists_in_business_table(db, "customer_info", "company_id", company_id):
                raise ValueError(f"客户 {company_id} 在业务库中不存在")

            # 校验业务员
            if not _exists_in_business_table(db, "user_basic", "user_id", sp_id):
                raise ValueError(f"业务员 {sp_id} 在业务库中不存在")

            # 校验主管
            if sv_id and not _exists_in_business_table(db, "user_basic", "user_id", sv_id):
                raise ValueError(f"主管 {sv_id} 在业务库中不存在")

            # 属性值校验
            if sp_attr not in ("develop", "distribute"):
                raise ValueError(f"业务员属性无效: '{sp_attr_raw}'，应为 开发/分配")
            if sv_attr and sv_attr not in ("develop", "distribute"):
                raise ValueError(f"主管属性无效: '{sv_attr_raw}'，应为 开发/分配")

            # 计算比例
            sp_rate, sv_rate, _ = calc_commission_rates(sp_id, sp_attr, sv_id, sv_attr)

            # 旧快照失效
            _invalidate_current_snapshot(db, company_id)

            # 创建新快照
            snapshot = CustomerCommissionSnapshot(
                customer_id=company_id,
                salesperson_id=sp_id,
                salesperson_attribute=sp_attr,
                salesperson_rate=sp_rate,
                supervisor_id=sv_id,
                supervisor_attribute=sv_attr,
                supervisor_rate=sv_rate,
                is_complete=True,
                is_current=True,
                source="import",
                operator=operator,
                operated_at=datetime.now(),
            )
            db.add(snapshot)
            result.success += 1

        except Exception as e:
            err = f"第 {row_idx} 行: {e}"
            result.failures.append(err)
            result.failed += 1
            logger.warning(f"Excel导入失败 - {err}")

    db.flush()
    wb.close()
    logger.info(f"Excel导入完成: 成功 {result.success}, 失败 {result.failed}")
    return result
