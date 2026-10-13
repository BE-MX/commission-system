"""系统字典 — SQLAlchemy 数据模型"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index, ForeignKey, JSON
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now


class SysDict(Base):
    __tablename__ = "sys_dict"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    type = Column(String(64), nullable=False, comment="字典类型 code")
    code = Column(String(64), nullable=False, comment="字典项 code")
    label = Column(String(128), nullable=False, comment="显示名")
    sort = Column(Integer, nullable=False, default=0, server_default="0", comment="排序，越小越靠前")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1", comment="是否启用")
    remark = Column(String(256), nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间"
    )

    __table_args__ = (
        Index("uk_sys_dict_type_code", "type", "code", unique=True),
        Index("idx_sys_dict_type_active", "type", "is_active", "sort"),
        {"comment": "系统字典表"},
    )


class NavigationPreference(Base):
    """Personal ordered route names; navigation.js owns labels and access rules."""

    __tablename__ = "ark_navigation_preferences"
    user_id = Column(
        Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
        ForeignKey("ark_users.id", ondelete="CASCADE"), primary_key=True,
        comment="所属用户，一人一行",
    )
    items = Column(JSON, nullable=False, comment="按用户排序的常用导航标识列表")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新北京时间")
