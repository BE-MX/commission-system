"""提成比例计算 & 公共工具函数"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Union


# 固定比例常量
SALESPERSON_RATE = Decimal("0.0200")       # 业务员固定 2%
SUPERVISOR_RATE_DUAL_DEV = Decimal("0.0150")  # 双开发主管 1.5%
SUPERVISOR_RATE_DEFAULT = Decimal("0.0100")   # 默认主管 1%
SUPERVISOR_RATE_ZERO = Decimal("0")


def calc_commission_rates(
    salesperson_id: str,
    salesperson_attribute: Optional[str],
    supervisor_id: Optional[str],
    supervisor_attribute: Optional[str],
) -> tuple[Decimal, Decimal, str]:
    """
    根据业务员/主管属性计算提成比例。

    Returns:
        (salesperson_rate, supervisor_rate, rule_note)
    """
    sp_rate = SALESPERSON_RATE

    # 无主管 或 主管=业务员
    if not supervisor_id or supervisor_id == salesperson_id:
        return sp_rate, SUPERVISOR_RATE_ZERO, "主管兼业务员，仅计业务员提成"

    # 双开发
    if salesperson_attribute == "develop" and supervisor_attribute == "develop":
        return sp_rate, SUPERVISOR_RATE_DUAL_DEV, "双开发，主管1.5%"

    # 其他组合
    return sp_rate, SUPERVISOR_RATE_DEFAULT, "主管1%"


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
