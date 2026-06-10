"""数据概念治理 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base

# ── 枚举常量 ──────────────────────────────────────────────

LAYER_FINANCIAL = "financial"
LAYER_CUSTOMER = "customer"
LAYER_PRODUCT = "product"
LAYER_PRODUCTION = "production"
LAYER_SALES_PROCESS = "sales_process"
LAYER_LOGISTICS = "logistics"

CONCEPT_LAYERS = [
    LAYER_FINANCIAL, LAYER_CUSTOMER, LAYER_PRODUCT,
    LAYER_PRODUCTION, LAYER_SALES_PROCESS, LAYER_LOGISTICS,
]

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_REVIEW = "review"
STATUS_ACTIVE = "active"
STATUS_DEPRECATED = "deprecated"

CONCEPT_STATUSES = [
    STATUS_DRAFT, STATUS_PENDING, STATUS_IN_PROGRESS,
    STATUS_REVIEW, STATUS_ACTIVE, STATUS_DEPRECATED,
]

PRIORITY_P1 = "P1"
PRIORITY_P2 = "P2"
PRIORITY_P3 = "P3"

CONCEPT_PRIORITIES = [PRIORITY_P1, PRIORITY_P2, PRIORITY_P3]

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

CONCEPT_CONFIDENCES = [CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW]

# 关联类型
REL_PARENT_OF = "parent_of"
REL_COMPOSED_OF = "composed_of"
REL_DERIVED_FROM = "derived_from"
REL_INFLUENCES = "influences"
REL_CONFLICTS_WITH = "conflicts_with"
REL_REQUIRES = "requires"
REL_LEADS = "leads"
REL_LAGS = "lags"

RELATION_TYPES = [
    REL_PARENT_OF, REL_COMPOSED_OF, REL_DERIVED_FROM,
    REL_INFLUENCES, REL_CONFLICTS_WITH, REL_REQUIRES,
    REL_LEADS, REL_LAGS,
]

# 变更操作
ACTION_CREATE = "create"
ACTION_EDIT = "edit"
ACTION_SUBMIT = "submit"
ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_DEPRECATE = "deprecate"
ACTION_ROLLBACK = "rollback"

CHANGE_ACTIONS = [
    ACTION_CREATE, ACTION_EDIT, ACTION_SUBMIT,
    ACTION_APPROVE, ACTION_REJECT, ACTION_DEPRECATE, ACTION_ROLLBACK,
]


class DataConcept(Base):
    """数据概念主表"""

    __tablename__ = "data_concepts"

    id = Column(String(64), primary_key=True, comment="概念ID，snake_case")
    name_zh = Column(String(50), nullable=False, comment="中文名")
    name_en = Column(String(100), nullable=False, comment="英文名")
    layer = Column(
        Enum(*CONCEPT_LAYERS, name="concept_layer"),
        nullable=False,
        comment="所属层级",
    )
    status = Column(
        Enum(*CONCEPT_STATUSES, name="concept_status"),
        nullable=False,
        default=STATUS_DRAFT,
        comment="概念状态",
    )
    priority = Column(
        Enum(*CONCEPT_PRIORITIES, name="concept_priority"),
        nullable=True,
        comment="待补充优先级",
    )
    one_liner = Column(String(60), nullable=True, comment="一句话定义")
    full_definition = Column(Text, nullable=True, comment="完整定义（Markdown）")
    boundary_includes = Column(JSON, nullable=True, comment="包含范围标签列表")
    boundary_excludes = Column(JSON, nullable=True, comment="排除范围标签列表")
    formula = Column(Text, nullable=True, comment="计算公式")
    numerator = Column(String(200), nullable=True, comment="分子")
    denominator = Column(String(200), nullable=True, comment="分母")
    unit = Column(String(20), nullable=True, comment="单位")
    primary_table = Column(String(100), nullable=True, comment="主数据表")
    primary_field = Column(String(100), nullable=True, comment="主字段")
    filter_conditions = Column(JSON, nullable=True, comment="过滤条件列表")
    related_tables = Column(JSON, nullable=True, comment="关联表列表")
    time_granularity = Column(JSON, nullable=True, comment="时间粒度多选")
    entity_granularity = Column(String(100), nullable=True, comment="实体粒度")
    segments = Column(JSON, nullable=True, comment="可切分维度列表")
    owner = Column(String(100), nullable=True, comment="负责人/模块")
    staleness_trigger = Column(Text, nullable=True, comment="失效触发条件")
    confidence = Column(
        Enum(*CONCEPT_CONFIDENCES, name="concept_confidence"),
        nullable=True,
        comment="置信度",
    )
    notes = Column(Text, nullable=True, comment="补充备注")
    created_by = Column(Integer, nullable=True, comment="创建人 user_id")
    updated_by = Column(Integer, nullable=True, comment="最后修改人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("idx_data_concepts_layer", "layer"),
        Index("idx_data_concepts_status", "status"),
    )

    def to_snapshot_dict(self) -> dict:
        """生成完整快照字典（用于变更记录）"""
        return {
            "id": self.id,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "layer": self.layer,
            "status": self.status,
            "priority": self.priority,
            "one_liner": self.one_liner,
            "full_definition": self.full_definition,
            "boundary_includes": self.boundary_includes,
            "boundary_excludes": self.boundary_excludes,
            "formula": self.formula,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unit": self.unit,
            "primary_table": self.primary_table,
            "primary_field": self.primary_field,
            "filter_conditions": self.filter_conditions,
            "related_tables": self.related_tables,
            "time_granularity": self.time_granularity,
            "entity_granularity": self.entity_granularity,
            "segments": self.segments,
            "owner": self.owner,
            "staleness_trigger": self.staleness_trigger,
            "confidence": self.confidence,
            "notes": self.notes,
        }


class ConceptRelationship(Base):
    """概念关联关系表"""

    __tablename__ = "concept_relationships"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_concept_id = Column(
        String(64), ForeignKey("data_concepts.id", ondelete="CASCADE"),
        nullable=False, comment="源概念ID",
    )
    target_concept_id = Column(
        String(64), ForeignKey("data_concepts.id", ondelete="CASCADE"),
        nullable=False, comment="目标概念ID",
    )
    relation_type = Column(
        Enum(*RELATION_TYPES, name="relation_type"),
        nullable=False, comment="关联类型",
    )
    description = Column(String(200), nullable=True, comment="关联备注说明")
    created_by = Column(Integer, nullable=True, comment="创建人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_auto_generated = Column(
        Boolean, nullable=False, default=False,
        comment="是否由系统自动生成",
    )

    __table_args__ = (
        Index("idx_concept_rels_source", "source_concept_id"),
        Index("idx_concept_rels_target", "target_concept_id"),
        UniqueConstraint(
            "source_concept_id", "target_concept_id", "relation_type",
            name="uk_concept_rels_pair",
        ),
    )


class ConceptChangeLog(Base):
    """概念变更记录表"""

    __tablename__ = "concept_change_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    concept_id = Column(
        String(64), ForeignKey("data_concepts.id", ondelete="CASCADE"),
        nullable=False, comment="概念ID",
    )
    timestamp = Column(
        DateTime, nullable=False, default=datetime.utcnow, comment="操作时间",
    )
    operator = Column(String(64), nullable=True, comment="操作人")
    action = Column(
        Enum(*CHANGE_ACTIONS, name="change_action"),
        nullable=False, comment="操作类型",
    )
    changed_fields = Column(JSON, nullable=True, comment="变更字段 before/after")
    comment = Column(String(500), nullable=True, comment="操作备注")
    snapshot = Column(JSON, nullable=True, comment="操作时概念完整快照")

    __table_args__ = (
        Index("idx_change_logs_concept", "concept_id"),
        Index("idx_change_logs_timestamp", "timestamp"),
    )
