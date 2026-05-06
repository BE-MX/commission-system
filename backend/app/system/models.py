"""系统字典 — SQLAlchemy 数据模型"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index

from app.core.database import Base


class SysDict(Base):
    __tablename__ = "sys_dict"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(64), nullable=False, comment="字典类型 code")
    code = Column(String(64), nullable=False, comment="字典项 code")
    label = Column(String(128), nullable=False, comment="显示名")
    sort = Column(Integer, nullable=False, default=0, server_default="0", comment="排序")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1", comment="是否启用")
    remark = Column(String(256), nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    __table_args__ = (
        Index("uk_sys_dict_type_code", "type", "code", unique=True),
        Index("idx_sys_dict_type_active", "type", "is_active", "sort"),
    )
