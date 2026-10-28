"""色板库（公库 / 业务员私库）与色差仪测量 ORM 模型。

私库可见性不落在色板行上：每次请求按 ark_customer_assignments 实时判定，
客户转交后新负责人自动可见。owner_user_id 只记录创建人。
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time import beijing_now

USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
PALETTE_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class ColorLibrarySwatch(Base):
    __tablename__ = "ark_color_library_swatches"
    __table_args__ = (
        CheckConstraint(
            "(library_scope = 'public' AND customer_id IS NULL AND customer_scope_key = 0) "
            "OR (library_scope = 'private' AND customer_id IS NOT NULL AND customer_scope_key = customer_id)",
            name="ck_color_library_swatch_scope",
        ),
        CheckConstraint("size_value > 0", name="ck_color_library_swatch_size"),
        UniqueConstraint(
            "library_scope", "customer_scope_key", "color_code_key", "size_value", "size_unit",
            name="uq_color_library_swatch_identity",
        ),
        Index("ix_color_library_swatch_customer", "customer_id", "record_status"),
        Index("ix_color_library_swatch_scope", "library_scope", "record_status"),
        {"comment": "色板库：公库标准色板与业务员私库客户色板；私库必须绑定客户，同库同客户下色号+尺寸唯一"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    library_scope = Column(String(16), nullable=False, comment="库范围：public=公库，private=私库")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True,
                         comment="私库绑定的统一客户ID；公库为空")
    customer_scope_key = Column(BigInteger, nullable=False, default=0,
                                comment="唯一约束用客户键：私库=customer_id，公库=0（避免 NULL 不参与唯一）")
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="创建人；不参与授权")
    color_code = Column(String(30), nullable=False, comment="色号原文，如 #1C、#8/60、客户自定义编码")
    color_code_key = Column(String(30), nullable=False, comment="色号规范化键（去空格、大写），用于唯一判定")
    size_value = Column(Numeric(5, 1), nullable=False, comment="尺寸数值，如 18.0")
    size_unit = Column(String(8), nullable=False, default="inch", comment="尺寸单位：inch / cm")
    display_name = Column(String(100), nullable=True, comment="展示名称")
    base_swatch_id = Column(BigInteger, ForeignKey("ark_color_library_swatches.id"), nullable=True,
                            comment="对比基准：公库色板ID（优先用其实测平均Lab）")
    base_palette_id = Column(PALETTE_ID, ForeignKey("ark_color_palette.id"), nullable=True,
                             comment="对比基准：公库基础色号ID（无实测色板时使用其Lab）")
    tolerance_de = Column(Numeric(4, 2), nullable=False, default=1.50, comment="允许色差阈值（ΔE00）")
    stat_count = Column(SmallInteger, nullable=False, default=0, comment="参与平均的测量组数（由测量记录重算）")
    stat_lab_l = Column(Numeric(6, 2), nullable=True, comment="平均 L*（重算冗余）")
    stat_lab_a = Column(Numeric(6, 2), nullable=True, comment="平均 a*（重算冗余）")
    stat_lab_b = Column(Numeric(6, 2), nullable=True, comment="平均 b*（重算冗余）")
    stat_mean_de = Column(Numeric(5, 2), nullable=True, comment="组内平均ΔE00：各组到平均Lab的ΔE均值，至少2组")
    stat_max_de = Column(Numeric(5, 2), nullable=True, comment="组内最大ΔE00，至少2组")
    stat_base_de = Column(Numeric(5, 2), nullable=True, comment="平均Lab与基准Lab的ΔE00")
    record_status = Column(String(16), nullable=False, default="active", comment="active=有效，archived=已归档")
    promoted_from_id = Column(BigInteger, ForeignKey("ark_color_library_swatches.id"), nullable=True,
                              comment="公库色板由哪条私库色板晋升而来")
    promotion_status = Column(String(16), nullable=True,
                              comment="私库晋升申请状态：pending=待审核，approved=已纳入，rejected=已驳回")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now,
                        comment="更新时间（北京时间）")

    measurements = relationship(
        "ColorLibraryMeasurement", back_populates="swatch", lazy="noload",
        order_by="ColorLibraryMeasurement.seq_no",
    )


class ColorLibraryMeasurement(Base):
    __tablename__ = "ark_color_library_measurements"
    __table_args__ = (
        UniqueConstraint("swatch_id", "seq_no", name="uq_color_library_measurement_seq"),
        UniqueConstraint("swatch_id", "client_request_id", name="uq_color_library_measurement_request"),
        Index("ix_color_library_measurement_swatch", "swatch_id", "is_included"),
        {"comment": "色板测量组：一行对应色差仪一次 CRC 有效的 44 类测量返回；原始值不可修改，只能剔除"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    swatch_id = Column(BigInteger, ForeignKey("ark_color_library_swatches.id"), nullable=False, comment="所属色板")
    seq_no = Column(Integer, nullable=False, comment="色板内测量序号，从1递增")
    lab_l = Column(Numeric(6, 2), nullable=False, comment="Lab L*（帧字节8-9 int16LE/100）")
    lab_a = Column(Numeric(6, 2), nullable=False, comment="Lab a*（帧字节10-11 int16LE/100）")
    lab_b = Column(Numeric(6, 2), nullable=False, comment="Lab b*（帧字节12-13 int16LE/100）")
    luv_l = Column(Numeric(6, 2), nullable=True, comment="Luv L*")
    luv_u = Column(Numeric(6, 2), nullable=True, comment="Luv u*")
    luv_v = Column(Numeric(6, 2), nullable=True, comment="Luv v*")
    lch_l = Column(Numeric(6, 2), nullable=True, comment="LCh L*")
    lch_c = Column(Numeric(6, 2), nullable=True, comment="LCh C*")
    lch_h = Column(Numeric(6, 2), nullable=True, comment="LCh h（保留原厂App有/无符号规则）")
    yxy_y = Column(Numeric(7, 2), nullable=True, comment="Yxy Y（/100）")
    yxy_x = Column(Numeric(6, 4), nullable=True, comment="Yxy x（/10000）")
    yxy_yy = Column(Numeric(6, 4), nullable=True, comment="Yxy y（/10000）")
    cmyk_c = Column(SmallInteger, nullable=True, comment="设备返回 CMYK C（uint8 原值）")
    cmyk_m = Column(SmallInteger, nullable=True, comment="设备返回 CMYK M")
    cmyk_y = Column(SmallInteger, nullable=True, comment="设备返回 CMYK Y")
    cmyk_k = Column(SmallInteger, nullable=True, comment="设备返回 CMYK K")
    rgb_r = Column(SmallInteger, nullable=True, comment="设备返回 RGB R，仅作预览")
    rgb_g = Column(SmallInteger, nullable=True, comment="设备返回 RGB G")
    rgb_b = Column(SmallInteger, nullable=True, comment="设备返回 RGB B")
    raw_hex = Column(Text, nullable=True, comment="完整 CRC 有效帧 HEX，可离线重解析；手工录入为空")
    source = Column(String(16), nullable=False, comment="device=色差仪，simulation=模拟设备，manual=手工录入")
    receipt_status = Column(String(16), nullable=False, default="matched",
                            comment="matched=请求窗口内匹配，late=超时后到达经人工确认，manual=手工录入")
    device_name = Column(String(64), nullable=True, comment="广播设备名")
    device_sn = Column(String(32), nullable=True, comment="设备信息帧解析的 SN；不是 MAC 或浏览器设备ID")
    device_fw = Column(String(16), nullable=True, comment="设备版本显示值")
    session_id = Column(String(64), nullable=True, comment="前端一次蓝牙连接会话ID")
    client_request_id = Column(String(64), nullable=False, comment="前端幂等键，防止重试重复入库")
    requested_at = Column(DateTime, nullable=True, comment="发送测量指令的北京时间")
    received_at = Column(DateTime, nullable=True, comment="收到测量帧的北京时间")
    is_included = Column(SmallInteger, nullable=False, default=1, comment="1=参与平均，0=已剔除")
    exclude_reason = Column(String(255), nullable=True, comment="剔除原因")
    measured_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="操作人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="入库时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now,
                        comment="更新时间（北京时间）")

    swatch = relationship("ColorLibrarySwatch", back_populates="measurements", lazy="noload")


class ColorLibraryEvent(Base):
    __tablename__ = "ark_color_library_events"
    __table_args__ = (
        Index("ix_color_library_event_swatch", "swatch_id", "id"),
        {"comment": "色板库审计事件：新建、修改属性、剔除/恢复测量、晋升申请与审核"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    swatch_id = Column(BigInteger, ForeignKey("ark_color_library_swatches.id"), nullable=False, comment="色板ID")
    event_type = Column(String(32), nullable=False,
                        comment="created/updated/measured/excluded/restored/promotion_requested/promotion_approved/promotion_rejected/archived")
    detail_json = Column(Text, nullable=True, comment="事件详情 JSON 文本（变更前后值、原因）")
    operated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="操作人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="事件时间（北京时间）")
