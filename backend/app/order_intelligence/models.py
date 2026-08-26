"""订单经营智能分析持久化模型。

订单事实仍只读来自 lsordertest；本域只持久化 AI 简报后台任务状态和结果。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects import mysql

from app.auth import models as _auth_models  # noqa: F401 - register ark_users for FK resolution
from app.core.database import Base
from app.core.time import beijing_now


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class OrderIntelligenceBriefJob(Base):
    __tablename__ = "ark_order_intelligence_brief_jobs"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
        comment="主键",
    )
    owner_user_id = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="CASCADE"),
        nullable=False,
        comment="提交简报的方舟用户",
    )
    status = Column(String(16), nullable=False, default="queued", comment="queued/running/succeeded/failed")
    active_key = Column(String(64), nullable=True, unique=True, comment="用户级活动任务锁，终态置空")
    date_from = Column(Date, nullable=False, comment="分析开始日期")
    date_to = Column(Date, nullable=False, comment="分析结束日期")
    focus = Column(String(24), nullable=False, default="executive", comment="简报侧重点")
    scope_snapshot = Column(JSON, nullable=False, default=dict, comment="提交时数据权限范围快照")
    content = Column(Text, nullable=True, comment="AI 或规则简报内容")
    source = Column(String(16), nullable=True, comment="ai/rules")
    evidence = Column(JSON, nullable=True, comment="生成简报的结构化证据")
    error_message = Column(String(1000), nullable=True, comment="可行动失败原因")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    started_at = Column(DateTime, nullable=True, comment="开始生成时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = (
        Index("idx_oi_brief_owner_created", "owner_user_id", "created_at"),
        Index("idx_oi_brief_status_updated", "status", "updated_at"),
        {"comment": "订单经营 AI 简报后台任务"},
    )
