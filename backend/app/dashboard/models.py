"""工作台配置 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

# ark_users.id 实际是 INT UNSIGNED，FK 类型必须完全一致（cerebrum 2026-06-10）
_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DashboardPreference(Base):
    """每用户一行的工作台布局配置。

    prefs JSON: {version, metrics:{hidden,order}, actions:{hidden,order}}
    卡片 key 真相源在前端注册表（cards.js），服务端只校验形状不校验 key。
    """

    __tablename__ = "ark_dashboard_preference"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(
        _UINT, ForeignKey("ark_users.id", ondelete="CASCADE"),
        nullable=False, unique=True, comment="所属用户，一人一行",
    )
    prefs = Column(JSON, nullable=False, comment="布局配置 {version, metrics:{hidden,order}, actions:{hidden,order}}")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")
