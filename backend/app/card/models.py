"""SQLAlchemy models for the sales-card butler module (086 migration).

业务员电子名片（leshine.work/card/<slug>/）背后的数据层：
客户口令 = 客户自己的邮箱或 WhatsApp 号（归一化后存 email_norm / whatsapp_norm）。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time import beijing_now


class CardSalesperson(Base):
    """业务员档案。slug 即静态页目录名与 URL（印在名片二维码里，只增不改）。"""

    __tablename__ = "ark_card_salespersons"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    slug = Column(String(32), nullable=False, unique=True, comment="URL 标识（印刷二维码固化，禁改）")
    name = Column(String(64), nullable=False, comment="英文名，如 Ginny")
    title = Column(String(64), nullable=False, default="Sales Manager", comment="职位")
    email = Column(String(128), nullable=False, comment="业务邮箱")
    whatsapp = Column(String(32), nullable=True, comment="WhatsApp 号（可空，数据到齐后补）")
    avatar_path = Column(String(512), nullable=True, comment="AI 头像相对路径")
    intro = Column(Text, nullable=True, comment="主页介绍文案")
    links_json = Column(JSON, nullable=True, comment="店铺/独立站链接 [{label,url}]")
    is_active = Column(SmallInteger, nullable=False, default=1, comment="1=启用,0=停用")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    customers = relationship("CardCustomer", back_populates="salesperson", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ark_card_salespersons_active", "is_active"),
        {"comment": "名片管家-业务员档案（slug 与印刷二维码绑定）"},
    )


class CardCustomer(Base):
    """客户档案。email_norm / whatsapp_norm 即口令查询口径（小写邮箱 / 纯数字号码）。"""

    __tablename__ = "ark_card_customers"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    salesperson_id = Column(
        BigInteger, ForeignKey("ark_card_salespersons.id", ondelete="CASCADE"),
        nullable=False, comment="归属业务员 ark_card_salespersons.id",
    )
    display_name = Column(String(128), nullable=False, comment="客户称呼（解锁后问候语用）")
    email_norm = Column(String(128), nullable=True, comment="口令-邮箱（小写归一）")
    whatsapp_norm = Column(String(32), nullable=True, comment="口令-WhatsApp（纯数字归一）")
    expo_code = Column(String(64), nullable=False, default="", comment="届次标记，如 2026-08")
    remark = Column(Text, nullable=True, comment="内部备注（不对客户展示）")
    created_by = Column(Integer, nullable=True, comment="录入人 ark_users.id（无 FK，随 expo.operator_user_id 先例）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    salesperson = relationship("CardSalesperson", back_populates="customers")
    entries = relationship("CardEntry", back_populates="customer", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ark_card_customers_sp", "salesperson_id"),
        Index("idx_ark_card_customers_email", "email_norm"),
        Index("idx_ark_card_customers_wa", "whatsapp_norm"),
        {"comment": "名片管家-客户档案（归一化邮箱/WhatsApp 即客户口令）"},
    )


class CardEntry(Base):
    """沟通纪要条目（业务员手工录入，客户解锁后可见）。"""

    __tablename__ = "ark_card_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(
        BigInteger, ForeignKey("ark_card_customers.id", ondelete="CASCADE"),
        nullable=False, comment="归属客户 ark_card_customers.id",
    )
    entry_type = Column(String(16), nullable=False, default="text", comment="text=文字 / image=图片")
    title = Column(String(128), nullable=True, comment="条目标题（可空）")
    content = Column(Text, nullable=True, comment="文字内容")
    attachment_path = Column(String(512), nullable=True, comment="附件相对路径 uploads/card/...")
    created_by = Column(Integer, nullable=True, comment="录入人 ark_users.id（无 FK）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    customer = relationship("CardCustomer", back_populates="entries")

    __table_args__ = (
        Index("idx_ark_card_entries_customer", "customer_id"),
        {"comment": "名片管家-沟通纪要（客户凭口令可见）"},
    )


class CardInquiry(Base):
    """客户在电子主页提交的需求/问题（公开表单落库）。"""

    __tablename__ = "ark_card_inquiries"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    salesperson_id = Column(
        BigInteger, ForeignKey("ark_card_salespersons.id", ondelete="CASCADE"),
        nullable=False, comment="目标业务员 ark_card_salespersons.id",
    )
    customer_id = Column(
        BigInteger, ForeignKey("ark_card_customers.id", ondelete="SET NULL"),
        nullable=True, comment="联系方式命中客户档案时回填（可空）",
    )
    contact = Column(String(128), nullable=False, comment="客户留的联系方式原文")
    message = Column(Text, nullable=False, comment="需求/问题正文")
    status = Column(String(16), nullable=False, default="new", comment="new=未处理 / handled=已处理")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

    __table_args__ = (
        Index("idx_ark_card_inquiries_sp", "salesperson_id", "status"),
        {"comment": "名片管家-客户询盘（公开表单，status 驱动跟进）"},
    )
