"""报表中心 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Index,
    ForeignKey,
)

from sqlalchemy.dialects import mysql

from app.core.database import Base


class ReportTemplate(Base):
    """报表模板表"""

    __tablename__ = "ark_report_templates"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    report_code = Column(String(64), nullable=False, comment="报表编码，如 production_order_print")
    name = Column(String(200), nullable=False, comment="显示名称")
    description = Column(String(500), nullable=True, comment="报表描述")
    template_content = Column(
        Text().with_variant(mysql.LONGTEXT, "mysql"),
        nullable=False,
        comment=".mrt 模板 JSON 内容",
    )
    version = Column(Integer, nullable=False, default=1, comment="模板版本号")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=禁用,1=启用")
    created_by = Column(Integer, nullable=True, comment="创建人 user_id")
    updated_by = Column(Integer, nullable=True, comment="最后修改人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = (
        UniqueConstraint("report_code", name="uk_report_code"),
        Index("idx_report_templates_status", "status"),
        {"comment": "报表模板表"},
    )


class ReportTemplateVersion(Base):
    """报表模板版本历史"""

    __tablename__ = "ark_report_template_versions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    template_id = Column(Integer, ForeignKey("ark_report_templates.id", ondelete="CASCADE"), nullable=False, comment="关联 ark_report_templates.id")
    version = Column(Integer, nullable=False, comment="版本号")
    template_content = Column(
        Text().with_variant(mysql.LONGTEXT, "mysql"),
        nullable=False,
        comment=".mrt 模板快照",
    )
    change_summary = Column(String(500), nullable=True, comment="变更说明")
    created_by = Column(Integer, nullable=True, comment="操作人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_template_versions_template_id", "template_id"),
        UniqueConstraint("template_id", "version", name="idx_template_versions_template_version"),
        {"comment": "报表模板版本历史"},
    )
