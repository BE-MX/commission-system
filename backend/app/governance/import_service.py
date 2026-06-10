"""数据概念治理 — 批量导入 + 导出"""

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.governance.models import (
    DataConcept,
    ConceptRelationship,
    STATUS_ACTIVE, STATUS_PENDING, STATUS_DRAFT,
)
from app.governance.schemas import ImportRequest, ImportResult


def import_concepts(db: Session, payload: ImportRequest, user_id: int) -> dict:
    """批量导入概念 + 关联关系（幂等 upsert）"""
    result = ImportResult()

    # 导入概念
    for item in payload.concepts:
        try:
            existing = db.query(DataConcept).filter(DataConcept.id == item.id).first()
            if existing:
                # upsert: 更新已有概念的字段（不覆盖 status）
                data = item.model_dump(exclude_none=True, exclude={"status"})
                for field, val in data.items():
                    if field != "id":
                        setattr(existing, field, val)
                result.concepts_skipped += 1
            else:
                concept = DataConcept(
                    **item.model_dump(exclude_none=True),
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(concept)
                result.concepts_imported += 1
        except Exception as e:
            result.errors.append(f"概念 '{item.id}': {str(e)}")

    db.flush()

    # 导入关联关系
    for rel_item in payload.relationships:
        try:
            # 校验两端概念存在
            source = db.query(DataConcept).filter(DataConcept.id == rel_item.source).first()
            target = db.query(DataConcept).filter(DataConcept.id == rel_item.target).first()
            if not source:
                result.errors.append(f"关联源概念 '{rel_item.source}' 不存在")
                continue
            if not target:
                result.errors.append(f"关联目标概念 '{rel_item.target}' 不存在")
                continue

            existing = db.query(ConceptRelationship).filter(
                ConceptRelationship.source_concept_id == rel_item.source,
                ConceptRelationship.target_concept_id == rel_item.target,
                ConceptRelationship.relation_type == rel_item.relation_type,
            ).first()

            if existing:
                result.relationships_skipped += 1
            else:
                rel = ConceptRelationship(
                    source_concept_id=rel_item.source,
                    target_concept_id=rel_item.target,
                    relation_type=rel_item.relation_type,
                    description=rel_item.description,
                    created_by=user_id,
                )
                db.add(rel)
                result.relationships_imported += 1
        except Exception as e:
            result.errors.append(f"关联 '{rel_item.source}->{rel_item.target}': {str(e)}")

    db.commit()
    return result.model_dump()


def export_concepts(db: Session, format: str = "json") -> dict:
    """导出所有概念"""
    concepts = db.query(DataConcept).order_by(DataConcept.layer, DataConcept.id).all()
    relationships = db.query(ConceptRelationship).order_by(ConceptRelationship.id).all()

    if format == "json":
        return _export_json(concepts, relationships)
    elif format == "markdown":
        return _export_markdown(concepts, relationships)
    else:
        raise ValueError(f"不支持的导出格式: {format}")


def _export_json(concepts, relationships) -> dict:
    """导出为 JSON 结构"""
    concepts_data = []
    for c in concepts:
        concepts_data.append(c.to_snapshot_dict())

    rels_data = []
    for r in relationships:
        rels_data.append({
            "source": r.source_concept_id,
            "target": r.target_concept_id,
            "relation_type": r.relation_type,
            "description": r.description,
        })

    return {
        "format": "json",
        "content": json.dumps(
            {"concepts": concepts_data, "relationships": rels_data},
            ensure_ascii=False, indent=2, default=str,
        ),
    }


def _export_markdown(concepts, relationships) -> dict:
    """导出为 Markdown"""
    lines = ["# 莱莎数据概念定义清单\n"]
    lines.append(f"> 导出时间: {_now_str()}\n")
    lines.append(f"> 概念总数: {len(concepts)} | 关联总数: {len(relationships)}\n\n")

    # 按层级分组
    from app.governance.models import CONCEPT_LAYERS
    layer_names = {
        "financial": "财务", "customer": "客户", "product": "产品",
        "production": "生产", "sales_process": "销售过程", "logistics": "物流",
    }

    for layer in CONCEPT_LAYERS:
        layer_concepts = [c for c in concepts if c.layer == layer]
        if not layer_concepts:
            continue

        lines.append(f"## {layer_names.get(layer, layer)}\n")
        for c in layer_concepts:
            lines.append(f"### {c.name_zh} (`{c.id}`)\n")
            lines.append(f"- 英文名: {c.name_en}")
            lines.append(f"- 状态: {c.status}")
            if c.one_liner:
                lines.append(f"- 一句话定义: {c.one_liner}")
            if c.confidence:
                lines.append(f"- 置信度: {c.confidence}")
            if c.owner:
                lines.append(f"- 负责人: {c.owner}")
            lines.append("")

    # 关联关系
    lines.append("---\n\n## 关联关系\n")
    for r in relationships:
        desc = f" — {r.description}" if r.description else ""
        lines.append(f"- `{r.source_concept_id}` --[{r.relation_type}]--> `{r.target_concept_id}`{desc}")
    lines.append("")

    return {"format": "markdown", "content": "\n".join(lines)}


def _now_str() -> str:
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


# ── 种子数据 ──────────────────────────────────────────────

SEED_CONCEPTS_ACTIVE = [
    {"id": "sales_revenue", "name_zh": "销售额", "name_en": "Sales Revenue", "layer": "financial", "confidence": "high", "owner": "财务"},
    {"id": "collection_amount", "name_zh": "回款额", "name_en": "Collection Amount", "layer": "financial", "confidence": "high", "owner": "财务"},
    {"id": "gross_profit", "name_zh": "毛利额", "name_en": "Gross Profit", "layer": "financial", "confidence": "medium", "owner": "财务"},
    {"id": "average_order_value", "name_zh": "客单价", "name_en": "Average Order Value", "layer": "financial", "confidence": "high", "owner": "财务"},
    {"id": "order_count", "name_zh": "订单数量", "name_en": "Order Count", "layer": "financial", "confidence": "high", "owner": "财务"},
    {"id": "customer_count", "name_zh": "客户数量", "name_en": "Customer Count", "layer": "customer", "confidence": "high", "owner": "客户管理"},
    {"id": "new_customer_count", "name_zh": "新签客户数", "name_en": "New Customer Count", "layer": "customer", "confidence": "high", "owner": "客户管理"},
    {"id": "product_sales_volume", "name_zh": "产品销量", "name_en": "Product Sales Volume", "layer": "product", "confidence": "high", "owner": "产品"},
    {"id": "inventory_level", "name_zh": "库存量", "name_en": "Inventory Level", "layer": "product", "confidence": "high", "owner": "产品"},
    {"id": "safety_stock", "name_zh": "安全库存", "name_en": "Safety Stock", "layer": "product", "confidence": "medium", "owner": "产品"},
    {"id": "process_completion_rate", "name_zh": "工序完成率", "name_en": "Process Completion Rate", "layer": "production", "confidence": "high", "owner": "生产"},
    {"id": "process_duration", "name_zh": "工序耗时", "name_en": "Process Duration", "layer": "production", "confidence": "medium", "owner": "生产"},
    {"id": "inquiry_conversion_rate", "name_zh": "询盘转化率", "name_en": "Inquiry Conversion Rate", "layer": "sales_process", "confidence": "medium", "owner": "销售"},
    {"id": "inquiry_volume", "name_zh": "询盘量", "name_en": "Inquiry Volume", "layer": "sales_process", "confidence": "medium", "owner": "销售"},
    {"id": "order_lead_time", "name_zh": "订单交付周期", "name_en": "Order Lead Time", "layer": "logistics", "confidence": "medium", "owner": "物流"},
]

SEED_CONCEPTS_PENDING = [
    {"id": "commission_amount", "name_zh": "提成金额", "name_en": "Commission Amount", "layer": "financial", "priority": "P1", "owner": "提成系统"},
    {"id": "cogs", "name_zh": "产品直接成本", "name_en": "COGS", "layer": "financial", "priority": "P1", "owner": "财务"},
    {"id": "on_time_delivery_rate", "name_zh": "交货准时率", "name_en": "On-Time Delivery Rate", "layer": "logistics", "priority": "P1", "owner": "物流"},
    {"id": "customer_ownership", "name_zh": "客户归属", "name_en": "Customer Ownership", "layer": "customer", "priority": "P2", "owner": "客户管理"},
    {"id": "repurchase_rate", "name_zh": "复购率", "name_en": "Repurchase Rate", "layer": "customer", "priority": "P2", "owner": "客户管理"},
    {"id": "salesperson_score", "name_zh": "业务员绩效得分", "name_en": "Salesperson Score", "layer": "sales_process", "priority": "P2", "owner": "销售"},
    {"id": "return_rate", "name_zh": "产品退货率", "name_en": "Return Rate", "layer": "product", "priority": "P3", "owner": "产品"},
    {"id": "customer_lifetime_value", "name_zh": "客户生命周期价值", "name_en": "Customer Lifetime Value", "layer": "customer", "priority": "P3", "owner": "客户管理"},
    {"id": "capacity_utilization", "name_zh": "产能利用率", "name_en": "Capacity Utilization", "layer": "production", "priority": "P3", "owner": "生产"},
]

SEED_RELATIONSHIPS = [
    {"source": "sales_revenue", "target": "product_sales_volume", "relation_type": "parent_of", "description": "产品销售额是销售额的子集"},
    {"source": "sales_revenue", "target": "gross_profit", "relation_type": "influences", "description": "销售额影响毛利额"},
    {"source": "sales_revenue", "target": "collection_amount", "relation_type": "influences", "description": "销售额是回款的上限"},
    {"source": "sales_revenue", "target": "collection_amount", "relation_type": "conflicts_with", "description": "时间差：下单≠付款"},
    {"source": "sales_revenue", "target": "order_count", "relation_type": "composed_of", "description": "销售额 = 订单数量 × 客单价"},
    {"source": "collection_amount", "target": "commission_amount", "relation_type": "influences", "description": "回款是提成计算的触发单元"},
    {"source": "gross_profit", "target": "sales_revenue", "relation_type": "derived_from", "description": "毛利 = 销售额 - COGS"},
    {"source": "gross_profit", "target": "cogs", "relation_type": "requires", "description": "计算毛利必须先有成本数据"},
    {"source": "product_sales_volume", "target": "inventory_level", "relation_type": "influences", "description": "销量减少库存"},
    {"source": "inventory_level", "target": "safety_stock", "relation_type": "influences", "description": "库存低于安全线触发预警"},
    {"source": "safety_stock", "target": "commission_amount", "relation_type": "influences", "description": ""},
    {"source": "order_lead_time", "target": "inventory_level", "relation_type": "requires", "description": "有库存则交期短"},
    {"source": "inquiry_conversion_rate", "target": "new_customer_count", "relation_type": "influences", "description": "转化率决定新客数"},
    {"source": "new_customer_count", "target": "sales_revenue", "relation_type": "influences", "description": "新客增量拉动销售额"},
]


def seed_governance_data(db: Session) -> dict:
    """初始化种子数据（幂等）"""
    imported_concepts = 0
    skipped_concepts = 0
    imported_rels = 0
    skipped_rels = 0

    # 导入 active 概念
    for item in SEED_CONCEPTS_ACTIVE:
        existing = db.query(DataConcept).filter(DataConcept.id == item["id"]).first()
        if existing:
            skipped_concepts += 1
            continue
        concept = DataConcept(
            id=item["id"],
            name_zh=item["name_zh"],
            name_en=item["name_en"],
            layer=item["layer"],
            status=STATUS_ACTIVE,
            confidence=item.get("confidence"),
            owner=item.get("owner"),
        )
        db.add(concept)
        imported_concepts += 1

    # 导入 pending 概念
    for item in SEED_CONCEPTS_PENDING:
        existing = db.query(DataConcept).filter(DataConcept.id == item["id"]).first()
        if existing:
            skipped_concepts += 1
            continue
        concept = DataConcept(
            id=item["id"],
            name_zh=item["name_zh"],
            name_en=item["name_en"],
            layer=item["layer"],
            status=STATUS_PENDING,
            priority=item.get("priority"),
            owner=item.get("owner"),
        )
        db.add(concept)
        imported_concepts += 1

    db.flush()

    # 导入关联关系
    for item in SEED_RELATIONSHIPS:
        existing = db.query(ConceptRelationship).filter(
            ConceptRelationship.source_concept_id == item["source"],
            ConceptRelationship.target_concept_id == item["target"],
            ConceptRelationship.relation_type == item["relation_type"],
        ).first()
        if existing:
            skipped_rels += 1
            continue

        # 校验两端存在
        src = db.query(DataConcept).filter(DataConcept.id == item["source"]).first()
        tgt = db.query(DataConcept).filter(DataConcept.id == item["target"]).first()
        if not src or not tgt:
            continue

        # conflicts_with 双向
        rel = ConceptRelationship(
            source_concept_id=item["source"],
            target_concept_id=item["target"],
            relation_type=item["relation_type"],
            description=item.get("description"),
        )
        db.add(rel)
        imported_rels += 1

        if item["relation_type"] == "conflicts_with":
            rev = ConceptRelationship(
                source_concept_id=item["target"],
                target_concept_id=item["source"],
                relation_type="conflicts_with",
                description=item.get("description"),
                is_auto_generated=True,
            )
            db.add(rev)

    db.commit()

    return {
        "concepts_imported": imported_concepts,
        "concepts_skipped": skipped_concepts,
        "relationships_imported": imported_rels,
        "relationships_skipped": skipped_rels,
    }
