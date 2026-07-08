"""物流跟踪 / 运单录入 — 数据模型 (合并自 models/tracking.py + models/waybill.py)"""

from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, Date, DateTime, Boolean,
    Index, func,
)

from app.core.database import Base


# ── 物流跟踪 ────────────────────────────────────────────


class ShipmentStaging(Base):
    """运单暂存表（Accio Work推送缓冲）"""
    __tablename__ = "shipment_staging"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
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
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("idx_staging_processed", "processed", "created_at"),
        Index("idx_staging_waybill", "waybill_no", "carrier"),
        {"comment": "运单暂存表：Accio Work 推送缓冲，处理后转入跟踪表"},
    )


class ShipmentTracking(Base):
    """运单跟踪主表"""
    __tablename__ = "shipment_tracking"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    waybill_no = Column(String(50), nullable=False, comment="运单号")
    carrier = Column(String(30), nullable=False, comment="物流商标识")
    carrier_name = Column(String(50), nullable=False, comment="物流商中文名")
    sender_name = Column(String(100), comment="发件人")
    sender_company = Column(String(200), comment="发件公司")
    receiver_name = Column(String(100), comment="收件人")
    receiver_company = Column(String(200), comment="收件公司")
    receiver_country = Column(String(50), comment="收件国家/地区")
    receiver_city = Column(String(100), comment="收件城市")
    current_status = Column(String(50), nullable=False, server_default="pending", comment="当前状态（承运商原始状态码，初始 pending）")
    current_status_text = Column(String(500), comment="当前状态描述文本")
    current_location = Column(String(200), comment="当前所在位置")
    last_event_time = Column(DateTime, comment="最近物流事件时间")
    shipped_at = Column(DateTime, comment="发出时间")
    delivered_at = Column(DateTime, comment="签收时间")
    estimated_delivery_date = Column(DateTime, comment="预计送达时间，来自承运商API，每次轮询覆盖更新")
    dingtalk_user_id = Column(String(64), nullable=False, comment="提交人钉钉用户ID")
    dingtalk_user_name = Column(String(50), nullable=False, comment="提交人钉钉昵称")
    dingtalk_sheet_row_id = Column(String(64), comment="钉钉表格行ID")
    last_synced_at = Column(DateTime, comment="最近同步回钉钉表格时间")
    is_active = Column(Boolean, nullable=False, server_default="1", comment="是否继续轮询（签收/超期后置0）")
    poll_count = Column(Integer, nullable=False, server_default="0", comment="累计轮询次数")
    last_polled_at = Column(DateTime, comment="最近轮询时间")
    poll_error = Column(String(500), comment="最近轮询错误信息")
    consecutive_errors = Column(Integer, nullable=False, server_default="0", comment="连续错误次数")
    ocr_raw_text = Column(Text, comment="OCR识别原始文本")
    short_code = Column(String(8), unique=True, comment="短链接编码")
    source_image_url = Column(String(500), comment="运单图片URL")
    unified_status = Column(String(30), comment="统一状态码")
    last_pushed_status = Column(String(30), comment="上次推送时的状态，防重复推送")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="最后更新时间")

    __table_args__ = (
        Index("uk_waybill", "waybill_no", "carrier", unique=True),
        Index("idx_tracking_dingtalk_user", "dingtalk_user_id"),
        Index("idx_tracking_status", "current_status"),
        Index("idx_tracking_active_poll", "is_active", "last_polled_at"),
        Index("idx_tracking_created", "created_at"),
        {"comment": "运单跟踪主表：轮询承运商API自动维护物流状态"},
    )


class TrackingEvent(Base):
    """物流事件明细表"""
    __tablename__ = "tracking_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    waybill_no = Column(String(50), nullable=False, comment="运单号")
    carrier = Column(String(30), nullable=False, comment="物流商标识")
    event_time = Column(DateTime, nullable=False, comment="物流事件发生时间")
    status_code = Column(String(50), comment="承运商原始状态码")
    description = Column(String(500), nullable=False, comment="事件描述")
    location = Column(String(200), comment="事件发生位置")
    location_code = Column(String(20), comment="位置编码")
    raw_response = Column(Text, comment="JSON原始响应")
    estimated_delivery_date = Column(DateTime, comment="该次查询时承运商返回的预计送达时间")
    synced_at = Column(DateTime, nullable=False, server_default=func.now(), comment="同步入库时间")

    __table_args__ = (
        Index("idx_event_waybill", "waybill_no", "carrier"),
        Index("idx_event_time", "waybill_no", "event_time"),
        {"comment": "物流事件明细表：轮询承运商API获取的轨迹节点"},
    )


class CarrierConfig(Base):
    """物流商配置表"""
    __tablename__ = "carrier_config"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    carrier = Column(String(30), nullable=False, unique=True, comment="物流商标识")
    carrier_name = Column(String(50), nullable=False, comment="物流商中文名")
    api_type = Column(String(20), nullable=False, comment="API类型")
    api_base_url = Column(String(200), nullable=False, comment="API基础URL")
    api_username = Column(String(100), comment="API账号")
    api_password = Column(String(200), comment="API密码")
    api_key = Column(String(200), comment="API密钥")
    is_active = Column(Boolean, nullable=False, server_default="1", comment="是否启用轮询")
    poll_interval_minutes = Column(Integer, nullable=False, server_default="60", comment="轮询间隔(分钟)")
    max_poll_days = Column(Integer, nullable=False, server_default="90", comment="最长轮询天数(超期停止跟踪)")
    waybill_pattern = Column(String(100), comment="运单号匹配正则")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="最后更新时间")

    __table_args__ = {"comment": "物流商API配置表"}


class ShippingDailyReport(Base):
    """物流日报"""
    __tablename__ = "ark_shipping_daily_reports"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(Integer, nullable=False, comment="所属用户ID")
    report_date = Column(Date, nullable=False, comment="日报日期")
    html_content = Column(Text, nullable=False, comment="日报HTML内容")
    short_url = Column(String(100), comment="日报短链")
    is_pushed = Column(Boolean, nullable=False, server_default="0", comment="是否已推送")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("uk_user_date", "user_id", "report_date", unique=True),
        {"comment": "物流日报"},
    )


# ── 运单录入 (manual + OCR) ─────────────────────────────


class Waybill(Base):
    __tablename__ = "ark_waybills"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    waybill_no = Column(String(50), nullable=False, unique=True, comment="运单号（唯一）")
    carrier = Column(String(50), nullable=False, default="未知", comment="物流商：FedEx/DHL/UPS/未知")
    recipient_name = Column(String(100), nullable=False, comment="收件人姓名")
    recipient_country = Column(String(100), nullable=False, comment="收件国家")
    ship_date = Column(Date, nullable=False, comment="发件日期")
    status = Column(String(20), nullable=False, default="待跟踪", comment="状态：待跟踪/运输中/已签收/异常")
    estimated_delivery_date = Column(DateTime, comment="预计送达时间，来自承运商API，每次轮询覆盖更新")
    entry_source = Column(String(20), nullable=False, default="manual", comment="录入来源：ocr/manual")
    created_by = Column(String(50), nullable=False, comment="录入人（登录用户名）")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="最后更新时间")

    __table_args__ = {"comment": "运单信息表（图片 OCR / 手动录入）"}
