"""Acquisition configuration and unified customer workflow model exports.

Physical search/public-pool workflow tables are owned by ``app.customer`` so
SQLAlchemy registers every table exactly once. This module owns only the
preserved target-profile configuration table.
"""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now
from app.customer.models import PublicPoolBatch, SearchJob, SearchResult, SearchResultSource


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class AcquisitionProfile(Base):
    __tablename__ = "ark_sales_target_profiles"
    __table_args__ = (
        Index("idx_sales_profile_status", "status"),
        Index("ix_sales_target_profile_last_improvement_artifact", "last_improvement_artifact_id"),
        {"comment": "智能获客-目标客户模型"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    profile_key = Column(String(64), nullable=False, default="default", unique=True, comment="画像业务键")
    company_name = Column(String(255), nullable=False, comment="本公司名称")
    company_website = Column(String(512), nullable=True, comment="本公司官网")
    products = Column(JSON, nullable=False, comment="产品能力列表")
    advantages = Column(JSON, nullable=False, comment="竞争优势列表")
    target_countries = Column(JSON, nullable=False, comment="目标国家列表")
    target_industries = Column(JSON, nullable=False, comment="目标行业列表")
    target_roles = Column(JSON, nullable=False, comment="目标联系人角色列表")
    exclusions = Column(JSON, nullable=False, comment="排除条件列表")
    default_language = Column(String(16), nullable=False, default="en", comment="默认开发语言")
    status = Column(String(16), nullable=False, default="active", comment="画像状态 active/inactive")
    created_by = Column(USER_ID, nullable=True, comment="创建人用户ID")
    updated_by = Column(USER_ID, nullable=True, comment="最后更新人用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")
    policy_version = Column(String(32), nullable=False, comment="策略版本")
    policy_json = Column(JSON, nullable=False, comment="target_profile_policy_v1阈值、权重、研究与领取规则")
    policy_snapshot_hash = Column(String(64).with_variant(mysql.CHAR(64), "mysql"), nullable=False, comment="规范快照SHA-256")
    last_improvement_artifact_id = Column(
        BigInteger,
        ForeignKey("ark_agent_artifacts.id", name="fk_sales_target_profile_improvement_artifact"),
        nullable=True,
        comment="最近人工批准改进Artifact",
    )
    policy_applied_at = Column(DateTime, nullable=False, comment="策略生效北京时间")


__all__ = [
    "AcquisitionProfile",
    "SearchJob",
    "SearchResult",
    "SearchResultSource",
    "PublicPoolBatch",
]
