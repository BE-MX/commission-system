"""物流跟踪相关数据模型"""

from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, DateTime, Boolean,
    Index, func,
)
from app.core.database import Base


class ShipmentStaging(Base):
    """运单暂存表（Accio Work推送缓冲）"""
    __tablename__ = "shipment_staging"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    waybill_no = Column(String(50), nullable=False, comment="运单号")
    carrier = Column(String(30), nullable=False, comment="物流商标识")
    carrier_name = Column(String(50), comment="物流商中文名")
    sender_name = Column(String(100), comment="发件人")
    sender_company = Column(String(200), comment="发件公司")
    receiver_name = Column(String(100), comment="收件人")
    receiver_company = Column(String(200), comment="收件公司")
    receiver_country = Column(String(50), comment="收件国家/地区")
    receiver_city = Column(String(100), comment="收件城市")
    ocr_raw_text = Column(Text, comment="OCR识别原始文本")
    source_image_url = Column(String(500), comment="运单图片URL")
    dingtalk_user_id = Column(String(64), nullable=False, comment="提交人钉钉用户ID")
    dingtalk_user_name = Column(String(50), nullable=False, comment="提交人钉钉昵称")
    processed = Column(Boolean, nullable=False, server_default="0", comment="是否已处理")
    processed_at = Column(DateTime, comment="处理时间")
    process_result = Column(String(100), comment="处理结果")
    process_note = Column(String(500), comment="处理备注")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_staging_processed", "processed", "created_at"),
        Index("idx_staging_waybill", "waybill_no", "carrier"),
    )


class ShipmentTracking(Base):
    """运单跟踪主表"""
    __tablename__ = "shipment_tracking"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    waybill_no = Column(String(50), nullable=False, comment="运单号")
    carrier = Column(String(30), nullable=False, comment="物流商标识")
    carrier_name = Column(String(50), nullable=False, comment="物流商中文名")
    sender_name = Column(String(100))
    sender_company = Column(String(200))
    receiver_name = Column(String(100))
    receiver_company = Column(String(200))
    receiver_country = Column(String(50))
    receiver_city = Column(String(100))
    current_status = Column(String(50), nullable=False, server_default="pending")
    current_status_text = Column(String(500))
    current_location = Column(String(200))
    last_event_time = Column(DateTime)
    shipped_at = Column(DateTime)
    delivered_at = Column(DateTime)
    dingtalk_user_id = Column(String(64), nullable=False)
    dingtalk_user_name = Column(String(50), nullable=False)
    dingtalk_sheet_row_id = Column(String(64))
    last_synced_at = Column(DateTime)
    is_active = Column(Boolean, nullable=False, server_default="1")
    poll_count = Column(Integer, nullable=False, server_default="0")
    last_polled_at = Column(DateTime)
    poll_error = Column(String(500))
    ocr_raw_text = Column(Text)
    short_code = Column(String(8), unique=True, comment="短链接编码")
    source_image_url = Column(String(500))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uk_waybill", "waybill_no", "carrier", unique=True),
        Index("idx_tracking_dingtalk_user", "dingtalk_user_id"),
        Index("idx_tracking_status", "current_status"),
        Index("idx_tracking_active_poll", "is_active", "last_polled_at"),
        Index("idx_tracking_created", "created_at"),
    )


class TrackingEvent(Base):
    """物流事件明细表"""
    __tablename__ = "tracking_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    waybill_no = Column(String(50), nullable=False)
    carrier = Column(String(30), nullable=False)
    event_time = Column(DateTime, nullable=False)
    status_code = Column(String(50))
    description = Column(String(500), nullable=False)
    location = Column(String(200))
    location_code = Column(String(20))
    raw_response = Column(Text, comment="JSON原始响应")
    synced_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_event_waybill", "waybill_no", "carrier"),
        Index("idx_event_time", "waybill_no", "event_time"),
    )


class CarrierConfig(Base):
    """物流商配置表"""
    __tablename__ = "carrier_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    carrier = Column(String(30), nullable=False, unique=True)
    carrier_name = Column(String(50), nullable=False)
    api_type = Column(String(20), nullable=False)
    api_base_url = Column(String(200), nullable=False)
    api_username = Column(String(100))
    api_password = Column(String(200))
    api_key = Column(String(200))
    is_active = Column(Boolean, nullable=False, server_default="1")
    poll_interval_minutes = Column(Integer, nullable=False, server_default="60")
    max_poll_days = Column(Integer, nullable=False, server_default="90")
    waybill_pattern = Column(String(100))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
