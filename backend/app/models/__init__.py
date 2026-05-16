"""数据模型汇总导入"""

from app.models.employee import EmployeeAttributeHistory, SupervisorRelationHistory
from app.models.customer import CustomerCommissionSnapshot
from app.models.commission import (
    SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus,
)
from app.models.business import UserBasic, CustomerInfo, OkkiOrder, OkkiReceipt
from app.tracking.models import (
    ShipmentStaging, ShipmentTracking, TrackingEvent, CarrierConfig,
)
from app.tracking.models import Waybill
from app.models.short_link import ArkShortLink

__all__ = [
    # 提成系统自有表
    "EmployeeAttributeHistory",
    "SupervisorRelationHistory",
    "CustomerCommissionSnapshot",
    "SyncedPayment",
    "CommissionBatch",
    "CommissionDetail",
    "PaymentCommissionStatus",
    # 业务库只读映射
    "UserBasic",
    "CustomerInfo",
    "OkkiOrder",
    "OkkiReceipt",
    # 物流跟踪
    "ShipmentStaging",
    "ShipmentTracking",
    "TrackingEvent",
    "CarrierConfig",
    # 运单录入
    "Waybill",
    # 短链接
    "ArkShortLink",
]
