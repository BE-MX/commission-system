"""内贸订单 — SQLAlchemy ORM 模型

表结构见 alembic/versions/081_domestic_orders.py。
relationship 一律 lazy="noload"（红线 9），由查询显式 selectinload。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
from app.core.time import beijing_now

# ark_users.id 实际是 INT UNSIGNED，FK 类型必须完全一致（cerebrum 2026-06-10）
_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DomesticCustomer(Base):
    """内贸客户（店名维度）"""

    __tablename__ = "ark_domestic_customers"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    shop_name = Column(String(120), nullable=False, unique=True, comment="客户店名（业务主标识）")
    custom_code = Column(String(64), unique=True, comment="客户自定义编码")
    membership_level = Column(String(16), comment="会员等级 silver/black/supreme")
    last_recharge_amount = Column(Numeric(14, 2), comment="最近一次成功充值金额")
    last_recharged_at = Column(DateTime, comment="最近一次成功充值时间（北京时）")
    province = Column(String(64), comment="省份")
    city = Column(String(64), comment="城市")
    contact = Column(String(60), comment="联系人")
    phone = Column(String(40), comment="联系电话")
    address = Column(String(255), comment="收货地址")
    customer_source = Column(String(32), comment="客户来源（sys_dict: domestic_customer_source）")
    store_type = Column(String(32), comment="门店类型（sys_dict: domestic_store_type）")
    customer_level = Column(String(8), comment="客户等级（sys_dict: domestic_customer_level）")
    lifecycle_status = Column(String(16), comment="客户状态（sys_dict: domestic_customer_lifecycle）")
    owner_user_id = Column(_UINT, ForeignKey("ark_users.id"), comment="归属销售")
    first_contact_date = Column(Date, comment="首次联系日期")
    first_order_date = Column(Date, comment="首次下单日期（历史档案口径）")
    last_order_date = Column(Date, comment="最近下单日期（历史档案口径）")
    total_order_count = Column(Integer, comment="累计订单数（历史档案口径，NULL=未录入）")
    total_sales_amount = Column(Numeric(14, 2), comment="累计销售额（历史档案口径，NULL=未录入）")
    remark = Column(String(500), comment="备注")
    balance = Column(Numeric(14, 2), nullable=False, default=0, comment="充值可用余额；credit 客户可为负（欠款）")
    settle_mode = Column(String(16), nullable=False, default="prepay",
                         comment="结算方式：prepay=先充值后下单,credit=先下单后付款")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=停用,1=启用")
    created_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="创建人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = (
        CheckConstraint(
            "membership_level IS NULL OR membership_level IN ('silver', 'black', 'supreme')",
            name="ck_dom_customer_membership_level",
        ),
        CheckConstraint(
            "settle_mode IN ('prepay', 'credit')",
            name="ck_dom_customer_settle_mode",
        ),
    )


class DomesticProduct(Base):
    """内贸产品 — 下单选属性后 find-or-create 沉淀，attrs_key 是身份"""

    __tablename__ = "ark_domestic_products"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    attrs_key = Column(String(255), nullable=False, unique=True, comment="属性组合唯一键，find-or-create 依据")
    name = Column(String(255), nullable=False, comment="展示名（属性拼接，创建时快照）")
    product_type = Column(String(16), nullable=False, comment="cap=头套,piece=发片")
    craft = Column(String(64), nullable=False, comment="头套工艺 / 发片工艺尺寸")
    net_color = Column(String(64), comment="网底颜色（仅头套）")
    size = Column(String(64), comment="尺寸（仅头套，含「取模定制」）")
    length = Column(String(32), nullable=False, comment="长度")
    density = Column(String(32), comment="发量（仅 15 厘米头套）")
    hair_style_series = Column(String(64), comment="发型系列（仅头套）")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="RESTRICT"),
                      comment="工艺路线，按 craft 映射自动绑定；NULL=未匹配到路线")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=停用,1=启用")
    use_count = Column(Integer, nullable=False, default=0, comment="被下单次数")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

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
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("product_type", "craft", name="uk_dom_craft_route"),
    )


class DomesticBasePrice(Base):
    """内贸产品原价；发片尺寸已精确合并进 craft。"""

    __tablename__ = "ark_domestic_base_prices"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    product_type = Column(String(16), nullable=False, comment="cap=头套,piece=发片")
    craft = Column(String(64), nullable=False, comment="头套工艺 / 发片合并工艺尺寸")
    length = Column(String(32), nullable=False, comment="长度")
    original_price = Column(Numeric(14, 2), nullable=False, comment="原价")
    version = Column(Integer, nullable=False, comment="价格版本，从1开始")
    updated_by = Column(_UINT, ForeignKey("ark_users.id"), comment="最后维护人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint(
            "product_type", "craft", "length", name="uq_dom_base_price_product"
        ),
        CheckConstraint(
            "product_type IN ('cap', 'piece')",
            name="ck_dom_base_price_product_type",
        ),
        CheckConstraint(
            "original_price > 0", name="ck_dom_base_price_positive"
        ),
        CheckConstraint("version >= 1", name="ck_dom_base_price_version"),
    )


class DomesticOrder(Base):
    """内贸订单主表"""

    __tablename__ = "ark_domestic_orders"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    domestic_no = Column(String(32), nullable=False, unique=True, comment="系统单号 DO{YYYYMMDD}-{NNN}")
    order_no = Column(String(64), nullable=False, comment="客户订单号（原样文本）")
    order_date = Column(Date, nullable=False, comment="下单日期")
    required_ship_date = Column(Date, comment="要求发货日期（新单必填；存量单为 NULL）")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id", ondelete="RESTRICT"), nullable=False, comment="客户")
    order_category = Column(String(16), nullable=False, default="normal", comment="normal=普货,special=特单")
    order_type = Column(String(32), comment="订单类型（sys_dict: domestic_order_type）")
    order_channel = Column(String(32), comment="订单渠道（sys_dict: domestic_order_channel）")
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
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    items = relationship("DomesticOrderItem", back_populates="order", lazy="noload",
                         cascade="all, delete-orphan")
    customer = relationship("DomesticCustomer", lazy="noload")

    __table_args__ = (
        Index("idx_dom_order_status", "status", "deleted_flag"),
        Index("idx_dom_order_customer", "customer_id"),
        Index("idx_dom_order_date", "order_date"),
        Index("idx_dom_order_required_ship_date", "required_ship_date"),
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
    unit_price = Column(Numeric(14, 2), nullable=False, comment="产品成交价 = 优惠价 + 手工费")
    original_price = Column(Numeric(14, 2), nullable=False, comment="原价快照")
    discount_amount = Column(Numeric(14, 2), nullable=False, comment="优惠金额快照")
    labor_fee = Column(Numeric(14, 2), nullable=False, default=0, comment="手工费（仅普单）")
    membership_level_snapshot = Column(
        String(16), nullable=True, comment="会员等级快照"
    )
    pricing_rule = Column(String(24), nullable=False, comment="定价规则")
    pricing_version = Column(String(32), nullable=False, comment="定价算法版本")
    base_price_version_snapshot = Column(
        Integer, nullable=False, comment="基础价格版本快照"
    )
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
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    order = relationship("DomesticOrder", back_populates="items", lazy="noload")
    product = relationship("DomesticProduct", lazy="noload")
    progress = relationship("DomesticItemProgress", back_populates="item", lazy="noload",
                            cascade="all, delete-orphan",
                            order_by="DomesticItemProgress.step_order")

    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="uq_dom_item_order_line"),
        CheckConstraint(
            "unit_price >= 0", name="ck_dom_item_unit_price_nonnegative"
        ),
        CheckConstraint(
            "discount_amount >= 0", name="ck_dom_item_discount_nonnegative"
        ),
        CheckConstraint(
            "unit_price <= original_price + labor_fee",
            name="ck_dom_item_unit_not_above_original",
        ),
        CheckConstraint(
            "original_price > 0 OR pricing_rule = 'legacy_manual'",
            name="ck_dom_item_original_price_valid",
        ),
        CheckConstraint(
            "base_price_version_snapshot >= 0",
            name="ck_dom_item_base_price_version_nonnegative",
        ),
        CheckConstraint(
            "membership_level_snapshot IS NULL OR "
            "membership_level_snapshot IN ('silver', 'black', 'supreme')",
            name="ck_dom_item_membership_snapshot",
        ),
        CheckConstraint(
            "pricing_rule IN ('base_price', 'member_fixed', "
            "'member_fixed_capped', 'member_reduction', 'manual_override', "
            "'legacy_manual')",
            name="ck_dom_item_pricing_rule",
        ),
        Index("idx_dom_item_order", "order_id"),
        Index("idx_dom_item_status", "status"),
        Index("idx_dom_item_product", "product_id"),
    )


class DomesticOrderPricingRequest(Base):
    """订单定价请求幂等记录。"""

    __tablename__ = "ark_domestic_order_pricing_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(
        Integer,
        ForeignKey("ark_domestic_orders.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属订单",
    )
    request_id = Column(String(64), nullable=False, comment="客户端幂等键")
    operation = Column(
        String(24), nullable=False, comment="submit/reprice_customer"
    )
    request_hash = Column(String(64), nullable=False, comment="请求载荷 SHA-256")
    result_json = Column(JSON, nullable=False, comment="首次定价结果")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

    order = relationship("DomesticOrder", lazy="noload")

    __table_args__ = (
        UniqueConstraint("order_id", "request_id", name="uq_dom_pricing_order_request"),
        CheckConstraint(
            "operation IN ('submit', 'reprice_customer')",
            name="ck_dom_pricing_request_operation",
        ),
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
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

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
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

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
    outcome_json = Column(JSON, comment="决策工序的结果数量分配")
    request_id = Column(String(64), unique=True,
                        comment="客户端幂等键：弱网重试同一个 id 不重复累加数量")
    reported_at = Column(DateTime, nullable=False, comment="报工时间（北京时）")
    revoked = Column(SmallInteger, nullable=False, default=0, comment="0=有效,1=已撤销")
    revoked_at = Column(DateTime, comment="撤销时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

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
    created_at = Column(DateTime, nullable=False, default=beijing_now)

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
    created_at = Column(DateTime, nullable=False, default=beijing_now)

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
    outcome_code = Column(String(32), comment="该单件在决策工序选择的结果编码")
    completed_at = Column(DateTime, nullable=False, comment="该单件在本工序完成时间")

    __table_args__ = (
        UniqueConstraint("log_id", "unit_id", name="uq_dom_report_log_unit"),
        Index("idx_dom_report_unit_progress", "progress_id", "unit_id"),
        Index("idx_dom_report_unit_unit", "unit_id", "progress_id"),
    )


class DomesticRouteRule(Base):
    """内贸专用的路线步骤规则；共享生产路线本身保持线性。"""

    __tablename__ = "ark_domestic_route_rules"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    route_id = Column(
        Integer,
        ForeignKey("process_route.id", ondelete="CASCADE"),
        nullable=False,
        comment="共享工艺路线 ID",
    )
    process_id = Column(
        Integer,
        ForeignKey("process.id", ondelete="RESTRICT"),
        nullable=False,
        comment="触发规则的工序 ID",
    )
    rule_type = Column(String(16), nullable=False, comment="decision/optional")
    config_json = Column(JSON, comment="服务端校验后的规则配置")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("route_id", "process_id", name="uq_dom_route_rule_process"),
        ForeignKeyConstraint(
            ["route_id", "process_id"],
            ["process_route_step.route_id", "process_route_step.process_id"],
            ondelete="RESTRICT",
            name="fk_dom_route_rule_step",
        ),
    )


class DomesticSkipLog(Base):
    """内贸工序跳过审计流水；跳过只改变路线资格，不计入工作量。"""

    __tablename__ = "ark_domestic_skip_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    item_id = Column(
        Integer,
        ForeignKey("ark_domestic_order_items.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属订单明细",
    )
    progress_id = Column(
        Integer,
        ForeignKey("ark_domestic_item_progress.id", ondelete="CASCADE"),
        nullable=False,
        comment="被跳过的进度行",
    )
    skip_qty = Column(Integer, nullable=False, comment="跳过数量")
    source = Column(String(24), nullable=False, comment="decision/optional_bypass/manual")
    skip_mode = Column(String(16), comment="人工跳过模式：quantity/unit；自动跳过为空")
    reason = Column(String(500), comment="跳过原因；人工放行必填")
    trigger_report_log_id = Column(
        BigInteger,
        ForeignKey("ark_domestic_report_logs.id", ondelete="SET NULL"),
        comment="触发本次跳过的报工流水",
    )
    request_id = Column(String(64), unique=True, comment="人工放行等入口的幂等键")
    created_by_user_id = Column(
        _UINT,
        ForeignKey("ark_users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="操作人",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    revoked = Column(SmallInteger, nullable=False, default=0, comment="0=有效,1=已撤销")
    revoked_at = Column(DateTime, comment="撤销时间")


class DomesticSkipUnit(Base):
    """一条跳过流水实际覆盖的单件清单。"""

    __tablename__ = "ark_domestic_skip_units"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    skip_log_id = Column(
        BigInteger,
        ForeignKey("ark_domestic_skip_logs.id", ondelete="CASCADE"),
        nullable=False,
        comment="跳过流水 ID",
    )
    unit_id = Column(
        BigInteger,
        ForeignKey("ark_domestic_item_units.id", ondelete="RESTRICT"),
        nullable=False,
        comment="被跳过的单件 ID",
    )
    progress_id = Column(
        Integer,
        ForeignKey("ark_domestic_item_progress.id", ondelete="CASCADE"),
        nullable=False,
        comment="被跳过的进度行",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("skip_log_id", "unit_id", name="uq_dom_skip_log_unit"),
    )
