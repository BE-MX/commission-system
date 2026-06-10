"""数据概念治理 — Pydantic 请求/响应模型"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


# ── 概念 CRUD ─────────────────────────────────────────────

class ConceptCreate(BaseModel):
    """创建概念"""
    id: str = Field(..., max_length=64, pattern=r"^[a-z][a-z0-9_]*$", description="概念ID，snake_case")
    name_zh: str = Field(..., max_length=50)
    name_en: str = Field(..., max_length=100)
    layer: str = Field(..., description="financial/customer/product/production/sales_process/logistics")
    priority: Optional[str] = Field(None, description="P1/P2/P3")
    one_liner: Optional[str] = Field(None, max_length=60)
    full_definition: Optional[str] = None
    boundary_includes: Optional[List[str]] = None
    boundary_excludes: Optional[List[str]] = None
    formula: Optional[str] = None
    numerator: Optional[str] = Field(None, max_length=200)
    denominator: Optional[str] = Field(None, max_length=200)
    unit: Optional[str] = Field(None, max_length=20)
    primary_table: Optional[str] = Field(None, max_length=100)
    primary_field: Optional[str] = Field(None, max_length=100)
    filter_conditions: Optional[List[str]] = None
    related_tables: Optional[List[str]] = None
    time_granularity: Optional[List[str]] = None
    entity_granularity: Optional[str] = Field(None, max_length=100)
    segments: Optional[List[str]] = None
    owner: Optional[str] = Field(None, max_length=100)
    staleness_trigger: Optional[str] = None
    confidence: Optional[str] = None
    notes: Optional[str] = None


class ConceptUpdate(BaseModel):
    """更新概念（部分更新，所有字段可选）"""
    name_zh: Optional[str] = Field(None, max_length=50)
    name_en: Optional[str] = Field(None, max_length=100)
    layer: Optional[str] = None
    priority: Optional[str] = None
    one_liner: Optional[str] = Field(None, max_length=60)
    full_definition: Optional[str] = None
    boundary_includes: Optional[List[str]] = None
    boundary_excludes: Optional[List[str]] = None
    formula: Optional[str] = None
    numerator: Optional[str] = Field(None, max_length=200)
    denominator: Optional[str] = Field(None, max_length=200)
    unit: Optional[str] = Field(None, max_length=20)
    primary_table: Optional[str] = Field(None, max_length=100)
    primary_field: Optional[str] = Field(None, max_length=100)
    filter_conditions: Optional[List[str]] = None
    related_tables: Optional[List[str]] = None
    time_granularity: Optional[List[str]] = None
    entity_granularity: Optional[str] = Field(None, max_length=100)
    segments: Optional[List[str]] = None
    owner: Optional[str] = Field(None, max_length=100)
    staleness_trigger: Optional[str] = None
    confidence: Optional[str] = None
    notes: Optional[str] = None


class StatusTransition(BaseModel):
    """状态流转请求"""
    action: str = Field(..., description="claim/submit/approve/reject/deprecate")
    comment: Optional[str] = Field(None, max_length=500, description="操作备注（驳回/废弃时建议填写）")


class ConceptResponse(BaseModel):
    """概念完整响应"""
    id: str
    name_zh: str
    name_en: str
    layer: str
    status: str
    priority: Optional[str] = None
    one_liner: Optional[str] = None
    full_definition: Optional[str] = None
    boundary_includes: Optional[List[str]] = None
    boundary_excludes: Optional[List[str]] = None
    formula: Optional[str] = None
    numerator: Optional[str] = None
    denominator: Optional[str] = None
    unit: Optional[str] = None
    primary_table: Optional[str] = None
    primary_field: Optional[str] = None
    filter_conditions: Optional[List[str]] = None
    related_tables: Optional[List[str]] = None
    time_granularity: Optional[List[str]] = None
    entity_granularity: Optional[str] = None
    segments: Optional[List[str]] = None
    owner: Optional[str] = None
    staleness_trigger: Optional[str] = None
    confidence: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completeness: Optional[float] = None

    class Config:
        from_attributes = True


class ConceptListItem(BaseModel):
    """概念列表项（精简字段）"""
    id: str
    name_zh: str
    name_en: str
    layer: str
    status: str
    priority: Optional[str] = None
    confidence: Optional[str] = None
    owner: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConceptStats(BaseModel):
    """概念进度统计"""
    total: int
    active: int
    pending: int
    in_progress: int
    review: int
    draft: int
    deprecated: int
    by_priority: dict = {}


# ── 关联关系 ──────────────────────────────────────────────

class RelationshipCreate(BaseModel):
    """添加关联关系"""
    target_concept_id: str = Field(..., max_length=64)
    relation_type: str = Field(..., description="关联类型代码")
    description: Optional[str] = Field(None, max_length=200)
    direction: str = Field("forward", description="forward=本概念→目标, reverse=目标→本概念")


class RelationshipResponse(BaseModel):
    """关联关系响应"""
    id: int
    source_concept_id: str
    target_concept_id: str
    relation_type: str
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    is_auto_generated: bool = False
    # 关联概念的名称（前端展示用）
    target_name_zh: Optional[str] = None
    source_name_zh: Optional[str] = None

    class Config:
        from_attributes = True


# ── 变更记录 ──────────────────────────────────────────────

class ChangeLogResponse(BaseModel):
    """变更记录响应"""
    id: int
    concept_id: str
    timestamp: Optional[datetime] = None
    operator: Optional[str] = None
    action: str
    changed_fields: Optional[list] = None
    comment: Optional[str] = None
    snapshot: Optional[dict] = None
    # 概念名称（前端展示用）
    concept_name_zh: Optional[str] = None

    class Config:
        from_attributes = True


class ChangeLogDiff(BaseModel):
    """单条变更 diff"""
    log: ChangeLogResponse
    diffs: list = Field(default_factory=list, description="[{field, before, after}]")


# ── 图谱 ──────────────────────────────────────────────────

class GraphNode(BaseModel):
    node_id: str
    label: str
    label_en: str
    layer: str
    status: str
    priority: Optional[str] = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    description: Optional[str] = None


class GraphData(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


# ── 批量导入 ──────────────────────────────────────────────

class ImportConceptItem(BaseModel):
    """批量导入的单个概念"""
    id: str
    name_zh: str
    name_en: str
    layer: str
    status: str = "active"
    priority: Optional[str] = None
    one_liner: Optional[str] = None
    full_definition: Optional[str] = None
    boundary_includes: Optional[List[str]] = None
    boundary_excludes: Optional[List[str]] = None
    formula: Optional[str] = None
    numerator: Optional[str] = None
    denominator: Optional[str] = None
    unit: Optional[str] = None
    primary_table: Optional[str] = None
    primary_field: Optional[str] = None
    filter_conditions: Optional[List[str]] = None
    related_tables: Optional[List[str]] = None
    time_granularity: Optional[List[str]] = None
    entity_granularity: Optional[str] = None
    segments: Optional[List[str]] = None
    owner: Optional[str] = None
    staleness_trigger: Optional[str] = None
    confidence: Optional[str] = None
    notes: Optional[str] = None


class ImportRelationshipItem(BaseModel):
    """批量导入的单条关联"""
    source: str
    target: str
    relation_type: str
    description: Optional[str] = None


class ImportRequest(BaseModel):
    """批量导入请求"""
    concepts: List[ImportConceptItem] = Field(default_factory=list)
    relationships: List[ImportRelationshipItem] = Field(default_factory=list)


class ImportResult(BaseModel):
    """批量导入结果"""
    concepts_imported: int = 0
    concepts_skipped: int = 0
    relationships_imported: int = 0
    relationships_skipped: int = 0
    errors: List[str] = Field(default_factory=list)
