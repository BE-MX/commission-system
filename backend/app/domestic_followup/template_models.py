from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DomesticFollowupTemplate(Base):
    __tablename__ = "ark_dom_followup_templates"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_dom_fu_template_version"),
        Index("ix_dom_fu_template_active", "code", "status"),
        {"comment": "内贸跟进场景模板：不可变版本"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    code = Column(String(8), nullable=False, comment="场景代码 T01-T10")
    version = Column(Integer, nullable=False, comment="模板版本号")
    name = Column(String(60), nullable=False, comment="场景名称")
    status = Column(String(10), nullable=False, default="active", comment="active/retired")
    prep_fields = Column(JSON, nullable=False, default=list, comment="准备卡字段定义")
    record_fields = Column(JSON, nullable=False, default=list, comment="录入字段定义")
    short_form = Column(String(300), nullable=True, comment="一句话起稿")
    guidance = Column(Text, nullable=True, comment="给 AI 的场景要点")
    params = Column(JSON, nullable=False, default=dict, comment="准备、沟通和再联系预算参数")
    avoid = Column(JSON, nullable=False, default=list, comment="禁止补全规则及标黄关键词")
    updated_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=True, comment="最后维护人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
