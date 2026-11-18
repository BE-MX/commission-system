"""产品风向标 AI 解读结果缓存（P1）。

存表而非内存：多实例共享、重启不丢、能审计。同一「范围 + 维度 + 款 + 窗口 + 日期 + 映射版本」
24 小时内直接复用，避免重复调用模型。
"""

from sqlalchemy import JSON, BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.auth import models as _auth_models  # noqa: F401 - register ark_users for FK resolution
from app.core.database import Base
from app.core.time import beijing_now

USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class ProductSalesAiInsight(Base):
    __tablename__ = "ark_product_sales_ai_insights"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True, comment="主键")
    cache_key = Column(String(64), nullable=False, comment="范围+维度+款+窗口+日期+映射版本的 SHA-256")
    scope_key = Column(String(160), nullable=False, comment="份额口径：self/user/team/none + ID")
    dimension = Column(String(24), nullable=False, comment="维度：color_size/category/item")
    item_key = Column(String(512), nullable=False, comment="款的键值，如「#1B · 18」")
    window_days = Column(Integer, nullable=False, comment="对比窗口天数")
    as_of_date = Column(Date, nullable=False, comment="解读所依据数据的截止日期（北京时间）")
    content = Column(Text, nullable=False, comment="解读正文（Markdown）")
    source = Column(String(16), nullable=False, comment="ai 模型生成 / rules 规则降级")
    evidence = Column(JSON, nullable=False, comment="提交给模型的结构化证据")
    created_by_user_id = Column(
        USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL", name="fk_ps_insight_created_by"),
        nullable=True, comment="首次生成的方舟用户",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="生成时间")
    expires_at = Column(DateTime, nullable=False, comment="复用截止时间（生成后 24 小时）")

    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_ps_insight_cache_key"),
        Index("idx_ps_insight_expires", "expires_at"),
        {"comment": "产品风向标 AI 解读结果缓存"},
    )
