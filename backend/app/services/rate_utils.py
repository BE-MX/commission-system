"""提成比例计算 & 公共工具函数"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Union

from sqlalchemy.orm import Session


# 固定比例常量
SALESPERSON_RATE = Decimal("0.0200")       # 业务员固定 2%
SUPERVISOR_RATE_DUAL_DEV = Decimal("0.0150")  # 双开发一级主管 1.5%
SUPERVISOR_RATE_DEFAULT = Decimal("0.0100")   # 默认一级主管 1%
SUPERVISOR_RATE_ZERO = Decimal("0")
SECOND_SUPERVISOR_RATE = Decimal("0.0050")    # 二级主管固定 0.5%


def calc_commission_rates(
    salesperson_id: str,
    salesperson_attribute: Optional[str],
    supervisor_id: Optional[str],
    supervisor_attribute: Optional[str],
    second_supervisor_id: Optional[str] = None,
) -> tuple[Decimal, Decimal, Decimal, str]:
    """
    根据业务员/主管属性计算提成比例。

    Returns:
        (salesperson_rate, supervisor_rate, second_supervisor_rate, rule_note)
    """
    sp_rate = SALESPERSON_RATE

    # 一级主管：无主管 或 主管=业务员
    if not supervisor_id or supervisor_id == salesperson_id:
        sv_rate = SUPERVISOR_RATE_ZERO
        rule_note = "一级主管兼业务员，仅计业务员提成"
    elif salesperson_attribute == "develop" and supervisor_attribute == "develop":
        sv_rate = SUPERVISOR_RATE_DUAL_DEV
        rule_note = "双开发，一级主管1.5%"
    else:
        sv_rate = SUPERVISOR_RATE_DEFAULT
        rule_note = "一级主管1%"

    # 二级主管：有二级主管且不等于业务员即给 0.5%
    sv2_rate = SUPERVISOR_RATE_ZERO
    if second_supervisor_id and second_supervisor_id != salesperson_id:
        sv2_rate = SECOND_SUPERVISOR_RATE
        rule_note += "，二级主管0.5%"

    return sp_rate, sv_rate, sv2_rate, rule_note


def get_employee_attribute_at_date(
    db: Session, employee_id: str, target_date: Optional[date],
) -> Optional[str]:
    """
    根据目标日期查找员工在该时间点的属性（前闭后开区间）。

    规则：
    - 只有一条记录：直接返回
    - target_date < 最早记录：返回最早记录的属性
    - 多条记录：找 effective_start <= target_date < 下一条 effective_start 的区间
    - target_date 为 None：退化为查当前属性（is_current=True）
    """
    from app.models.employee import EmployeeAttributeHistory

    if target_date is None:
        row = db.query(EmployeeAttributeHistory).filter(
            EmployeeAttributeHistory.employee_id == employee_id,
            EmployeeAttributeHistory.is_current == True,
        ).first()
        return row.attribute_type if row else None

    records = (
        db.query(EmployeeAttributeHistory)
        .filter(EmployeeAttributeHistory.employee_id == employee_id)
        .order_by(EmployeeAttributeHistory.effective_start.asc())
        .all()
    )

    if not records:
        return None
    if len(records) == 1:
        return records[0].attribute_type
    if target_date < records[0].effective_start:
        return records[0].attribute_type

    for i, record in enumerate(records):
        next_start = records[i + 1].effective_start if i + 1 < len(records) else None
        if next_start is None or target_date < next_start:
            return record.attribute_type

    return records[-1].attribute_type


def get_employee_attribute_at_date_from_records(
    records: list, target_date: Optional[date],
) -> Optional[str]:
    """
    纯内存版：从已加载的历史记录列表中按日期查找属性。
    records 须按 effective_start 升序排列。
    """
    if not records:
        return None
    if target_date is None:
        for r in records:
            if r.is_current:
                return r.attribute_type
        return None
    if len(records) == 1:
        return records[0].attribute_type
    if target_date < records[0].effective_start:
        return records[0].attribute_type

    for i, record in enumerate(records):
        next_start = records[i + 1].effective_start if i + 1 < len(records) else None
        if next_start is None or target_date < next_start:
            return record.attribute_type

    return records[-1].attribute_type


def to_date(val: Union[str, date, datetime, None]) -> Optional[date]:
    """将字符串或 datetime 安全转换为 date 对象（兼容 SQLite 返回字符串）"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        return datetime.strptime(val[:10], "%Y-%m-%d").date()
    return val
