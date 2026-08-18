"""内贸订单 — SQLAlchemy ORM 模型

表结构见 alembic/versions/081_domestic_orders.py。
relationship 一律 lazy="noload"（红线 9），由查询显式 selectinload。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.core.database import Base

# ark_users.id 实际是 INT UNSIGNED，FK 类型必须完全一致（cerebrum 2026-06-10）
_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DomesticCustomer(Base):
    """内贸客户（店名维度）"""

    __tablename__ = "ark_domestic_customers"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    shop_name = Column(String(120), nullable=False, unique=True, comment="客户店名（业务主标识）")
    custom_code = Column(String(64), unique=True, comment="客户自定义编码")
    membership_level = Column(String(32), comment="会员等级")
    province = Column(String(64), comment="省份")
    city = Column(String(64), comment="城市")
    contact = Column(String(60), comment="联系人")
    phone = Column(String(40), comment="联系电话")
    address = Column(String(255), comment="收货地址")
    remark = Column(String(500), comment="备注")
    balance = Column(Numeric(14, 2), nullable=False, default=0, comment="充值可用余额")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=停用,1=启用")
    created_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="创建人")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")


class DomesticProduct(Base):
    """内贸产品 — 下单选属性后 find-or-create 沉淀，attrs_key 是身份"""

    __tablename__ = "ark_domestic_products"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    attrs_key = Column(String(255), nullable=False, unique=True, comment="属性组合唯一键，find-or-create 依据")
    name = Column(String(255), nullable=False, comment="展示名（属性拼接，创建时快照）")
    product_type = Column(String(16), nullable=False, comment="cap=头套,piece=发片")
    craft = Column(String(64), nullable=False, comment="工艺")
    net_color = Column(String(64), comment="网底颜色（仅头套）")
    size = Column(String(64), nullable=False, comment="尺寸（含「取模定制」）")
    length = Column(String(32), nullable=False, comment="长度")
    density = Column(String(32), nullable=False, comment="发量")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="RESTRICT"),
                      comment="工艺路线，按 craft 映射自动绑定；NULL=未匹配到路线")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=停用,1=启用")
    use_count = Column(Integer, nullable=False, default=0, comment="被下单次数")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index("idx_dom_product_type", "product_type", "status"),
        Index("idx_dom_product_route", "route_id"),
    )


class DomesticCraftRoute(Base):
    """工艺 → 工艺路线映射，新产品据此自动配路线"""

    __tablename__ = "ark_domestic_craft_routes"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    product_type = Column(String(16), nullable=False, comment="cap=头套,piece=发片")
    craft = Column(String(64), nullable=False, comment="工艺值（对应字典 code）")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="RESTRICT"), nullable=False, comment="默认工艺路线")
    updated_by = Column(_UINT, ForeignKey("ark_users.id"), comment="最后维护人")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("product_type", "craft", name="uk_dom_craft_route"),
    )


class DomesticOrder(Base):
    """内贸订单主表"""

    __tablename__ = "ark_domestic_orders"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    domestic_no = Column(String(32), nullable=False, unique=True, comment="系统单号 DO{YYYYMMDD}-{NNN}")
    order_no = Column(String(64), nullable=False, comment="客户订单号（原样文本）")
    order_date = Column(Date, nullable=False, comment="下单日期")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id", ondelete="RESTRICT"), nullable=False, comment="客户")
    order_type = Column(String(16), nullable=False, default="normal", comment="normal=普货,special=特单")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=草稿,1=生产中,2=已完工,3=已发货,4=已终止")
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, comment="订单明细总金额")
    charged_amount = Column(Numeric(14, 2), nullable=False, default=0, comment="已从客户余额扣除金额")
    next_line_no = Column(Integer, nullable=False, default=1, comment="下一条明细的稳定序号")
    item_count = Column(Integer, nullable=False, default=0, comment="当前有效明细行数")
    total_unit_qty = Column(Integer, nullable=False, default=0, comment="当前有效明细总件数")
    request_id = Column(String(64), comment="客户端建单幂等键")
    request_hash = Column(String(64), comment="建单载荷 SHA-256 指纹")
    remark = Column(String(1000), comment="订单备注")
    created_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="下单人")
    deleted_flag = Column(SmallInteger, nullable=False, default=0, comment="0=正常,1=已删除")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    items = relationship("DomesticOrderItem", back_populates="order", lazy="noload",
                         cascade="all, delete-orphan")
    customer = relationship("DomesticCustomer", lazy="noload")

    __table_args__ = (
        Index("idx_dom_order_status", "status", "deleted_flag"),
        Index("idx_dom_order_customer", "customer_id"),
        Index("idx_dom_order_date", "order_date"),
        Index("idx_dom_order_no", "order_no"),
        Index("uq_dom_order_request_id", "request_id", unique=True),
    )


class DomesticOrderItem(Base):
    """内贸订单明细 — 一单多品，每行独立走工艺路线、独立按数量流转"""

    __tablename__ = "ark_domestic_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(Integer, ForeignKey("ark_domestic_orders.id", ondelete="CASCADE"), nullable=False, comment="所属订单")
    line_no = Column(Integer, nullable=False, comment="订单内稳定明细序号 A1/A2/...")
    product_id = Column(Integer, ForeignKey("ark_domestic_products.id", ondelete="RESTRICT"), nullable=False, comment="内贸产品")
    product_name = Column(String(255), nullable=False, comment="产品名快照")
    attrs_snapshot = Column(JSON, comment="属性快照")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="RESTRICT"),
                      comment="下单时锁定的路线快照，后改映射不影响在制单")
    order_qty = Column(Integer, nullable=False, comment="下单数量")
    unit_price = Column(Numeric(14, 2), nullable=False, default=0, comment="产品单价")
    hairstyle = Column(String(1000), comment="发型（文字）")
    hairstyle_images = Column(JSON, comment="发型参考图 [相对路径]")
    color = Column(String(1000), comment="颜色（文字）")
    color_images = Column(JSON, comment="颜色参考图 [相对路径]")
    style_requirement = Column(String(2000), comment="发型要求（文字）")
    style_images = Column(JSON, comment="发型要求图 [相对路径]")
    remark = Column(String(2000), comment="明细备注（文字）")
    remark_images = Column(JSON, comment="备注图 [相对路径]")
    status = Column(SmallInteger, nullable=False, default=0, comment="0=生产中,1=已完工,2=已发货")
    ship_time = Column(DateTime, comment="发货时间")
    ship_weight = Column(Numeric(10, 2), comment="发货克重 g")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    order = relationship("DomesticOrder", back_populates="items", lazy="noload")
    product = relationship("DomesticProduct", lazy="noload")
    progress = relationship("DomesticItemProgress", back_populates="item", lazy="noload",
                            cascade="all, delete-orphan",
                            order_by="DomesticItemProgress.step_order")

    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="uq_dom_item_order_line"),
        Index("idx_dom_item_order", "order_id"),
        Index("idx_dom_item_status", "status"),
        Index("idx_dom_item_product", "product_id"),
    )


class DomesticItemAppendRequest(Base):
    """追加明细幂等记录；即使明细后来删除，请求号也不会被复用。"""

    __tablename__ = "ark_domestic_item_append_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(
        Integer,
        ForeignKey("ark_domestic_orders.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属订单",
    )
    item_id = Column(
        Integer,
        ForeignKey("ark_domestic_order_items.id", ondelete="SET NULL"),
        comment="首次请求创建的明细；删除后置空但保留幂等占位",
    )
    request_id = Column(String(64), nullable=False, comment="客户端追加明细幂等键")
    request_hash = Column(String(64), nullable=False, comment="追加载荷 SHA-256 指纹")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("order_id", "request_id", name="uq_dom_append_order_request"),
        Index("idx_dom_append_item", "item_id"),
    )


class DomesticItemProgress(Base):
    """明细工序进度 — 按数量累计，不是 0/1 流转。

    可报数量(第N道) = completed_qty(第N-1道) − completed_qty(第N道)，首道上游 = order_qty。
    刻意不存冗余的「待做数量」字段：推导值永远自洽，冗余字段必然漂移。
    """

    __tablename__ = "ark_domestic_item_progress"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    item_id = Column(Integer, ForeignKey("ark_domestic_order_items.id", ondelete="CASCADE"), nullable=False, comment="所属明细")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="RESTRICT"), nullable=False, comment="冗余路线ID")
    process_id = Column(Integer, ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, comment="工序")
    step_order = Column(SmallInteger, nullable=False, comment="工序顺序，从1开始")
    completed_qty = Column(Integer, nullable=False, default=0, comment="本道累计完成数量")
    status = Column(SmallInteger, nullable=False, default=0, comment="0=进行中,1=本道已做完")
    first_reported_at = Column(DateTime, comment="首次报工时间")
    last_reported_at = Column(DateTime, comment="最后一次报工时间")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    item = relationship("DomesticOrderItem", back_populates="progress", lazy="noload")

    __table_args__ = (
        UniqueConstraint("item_id", "step_order", name="uk_dom_progress_item_step"),
        Index("idx_dom_progress_item", "item_id"),
        Index("idx_dom_progress_process", "process_id", "status"),
    )


class DomesticReportLog(Base):
    """报工流水 — 支持撤销回减与计件统计。外贸侧没有这张表（撤销即抹掉，不可追溯）"""

    __tablename__ = "ark_domestic_report_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    item_id = Column(Integer, ForeignKey("ark_domestic_order_items.id", ondelete="CASCADE"), nullable=False, comment="所属明细")
    progress_id = Column(Integer, ForeignKey("ark_domestic_item_progress.id", ondelete="CASCADE"), nullable=False, comment="所属进度行")
    process_id = Column(Integer, ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, comment="工序")
    step_order = Column(SmallInteger, nullable=False, comment="工序顺序")
    report_qty = Column(Integer, nullable=False, comment="本次报工数量")
    reported_by_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="报工人")
    reported_by_name = Column(String(60), comment="报工人姓名快照")
    source = Column(String(16), nullable=False, default="mini", comment="mini=小程序,web=主站")
    report_mode = Column(String(16), nullable=False, default="quantity", comment="quantity=数量报工,unit=逐件扫码")
    request_id = Column(String(64), unique=True,
                        comment="客户端幂等键：弱网重试同一个 id 不重复累加数量")
    reported_at = Column(DateTime, nullable=False, comment="报工时间（北京时）")
    revoked = Column(SmallInteger, nullable=False, default=0, comment="0=有效,1=已撤销")
    revoked_at = Column(DateTime, comment="撤销时间")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_dom_log_item", "item_id", "step_order"),
        Index("idx_dom_log_user_time", "reported_by_user_id", "reported_at"),
        Index("idx_dom_log_progress", "progress_id", "revoked"),
    )


class DomesticCustomerLedger(Base):
    """客户充值与订单扣款账本；amount 为有符号变动额。"""

    __tablename__ = "ark_domestic_customer_ledger"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id", ondelete="RESTRICT"), nullable=False)
    order_id = Column(Integer, ForeignKey("ark_domestic_orders.id", ondelete="RESTRICT"))
    transaction_type = Column(String(32), nullable=False, comment="recharge/order_charge/order_adjustment/order_refund")
    amount = Column(Numeric(14, 2), nullable=False, comment="充值/退款为正，扣款为负")
    balance_before = Column(Numeric(14, 2), nullable=False, comment="变动前余额")
    balance_after = Column(Numeric(14, 2), nullable=False, comment="变动后余额")
    business_key = Column(String(128), unique=True, comment="可选幂等键")
    remark = Column(String(500), comment="说明")
    created_by = Column(_UINT, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        Index("idx_dom_ledger_customer_time", "customer_id", "created_at"),
        Index("idx_dom_ledger_order", "order_id"),
    )


class DomesticItemUnit(Base):
    """订单明细中的单件实体；每行对应一个可打印二维码。"""

    __tablename__ = "ark_domestic_item_units"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    item_id = Column(Integer, ForeignKey("ark_domestic_order_items.id", ondelete="CASCADE"), nullable=False)
    unit_no = Column(Integer, nullable=False, comment="明细内单件序号，从1开始")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=数量缩减停用,1=有效")
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("item_id", "unit_no", name="uq_dom_unit_item_no"),
        Index("idx_dom_unit_item_status", "item_id", "status", "unit_no"),
    )


class DomesticReportUnit(Base):
    """一条报工流水实际覆盖的单件清单；撤销时随流水状态一起失效。"""

    __tablename__ = "ark_domestic_report_units"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    log_id = Column(BigInteger, ForeignKey("ark_domestic_report_logs.id", ondelete="CASCADE"), nullable=False, comment="报工流水 ID")
    unit_id = Column(BigInteger, ForeignKey("ark_domestic_item_units.id", ondelete="RESTRICT"), nullable=False, comment="单件 ID")
    progress_id = Column(Integer, ForeignKey("ark_domestic_item_progress.id", ondelete="CASCADE"), nullable=False)
    completed_at = Column(DateTime, nullable=False, comment="该单件在本工序完成时间")

    __table_args__ = (
        UniqueConstraint("log_id", "unit_id", name="uq_dom_report_log_unit"),
        Index("idx_dom_report_unit_progress", "progress_id", "unit_id"),
        Index("idx_dom_report_unit_unit", "unit_id", "progress_id"),
    )
