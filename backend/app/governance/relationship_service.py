"""数据概念治理 — 关联关系 CRUD + 双向同步"""

from typing import Optional

from sqlalchemy.orm import Session

from app.governance.models import (
    DataConcept,
    ConceptRelationship,
    REL_CONFLICTS_WITH,
    RELATION_TYPES,
)
from app.governance.schemas import RelationshipResponse


def list_relationships(db: Session, concept_id: str) -> list[dict]:
    """获取概念的所有关联（双向：包括作为 source 和 target 的）"""
    concept = db.query(DataConcept).filter(DataConcept.id == concept_id).first()
    if not concept:
        raise ValueError(f"概念 '{concept_id}' 不存在")

    # 作为 source 的关联
    as_source = db.query(ConceptRelationship).filter(
        ConceptRelationship.source_concept_id == concept_id,
    ).all()

    # 作为 target 的关联
    as_target = db.query(ConceptRelationship).filter(
        ConceptRelationship.target_concept_id == concept_id,
    ).all()

    results = []

    # source → target：正向展示
    for rel in as_source:
        target = db.query(DataConcept).filter(DataConcept.id == rel.target_concept_id).first()
        results.append({
            "id": rel.id,
            "source_concept_id": rel.source_concept_id,
            "target_concept_id": rel.target_concept_id,
            "relation_type": rel.relation_type,
            "description": rel.description,
            "created_by": rel.created_by,
            "created_at": rel.created_at,
            "is_auto_generated": rel.is_auto_generated,
            "direction": "forward",
            "target_name_zh": target.name_zh if target else None,
            "source_name_zh": concept.name_zh,
        })

    # target ← source：反向展示
    for rel in as_target:
        source = db.query(DataConcept).filter(DataConcept.id == rel.source_concept_id).first()
        results.append({
            "id": rel.id,
            "source_concept_id": rel.source_concept_id,
            "target_concept_id": rel.target_concept_id,
            "relation_type": rel.relation_type,
            "description": rel.description,
            "created_by": rel.created_by,
            "created_at": rel.created_at,
            "is_auto_generated": rel.is_auto_generated,
            "direction": "reverse",
            "source_name_zh": source.name_zh if source else None,
            "target_name_zh": concept.name_zh,
        })

    return results


def create_relationship(
    db: Session,
    concept_id: str,
    target_concept_id: str,
    relation_type: str,
    description: Optional[str],
    direction: str,
    user_id: int,
) -> dict:
    """添加关联关系"""
    # 校验概念存在
    source_concept = db.query(DataConcept).filter(DataConcept.id == concept_id).first()
    if not source_concept:
        raise ValueError(f"概念 '{concept_id}' 不存在")
    target_concept = db.query(DataConcept).filter(DataConcept.id == target_concept_id).first()
    if not target_concept:
        raise ValueError(f"目标概念 '{target_concept_id}' 不存在")

    # 不允许与自身建立关联
    if concept_id == target_concept_id:
        raise ValueError("不允许与自身建立关联")

    # 校验关联类型
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"未知关联类型 '{relation_type}'，支持: {RELATION_TYPES}")

    # 根据 direction 确定实际 source 和 target
    if direction == "reverse":
        actual_source = target_concept_id
        actual_target = concept_id
    else:
        actual_source = concept_id
        actual_target = target_concept_id

    # 检查是否重复
    existing = db.query(ConceptRelationship).filter(
        ConceptRelationship.source_concept_id == actual_source,
        ConceptRelationship.target_concept_id == actual_target,
        ConceptRelationship.relation_type == relation_type,
    ).first()
    if existing:
        raise ValueError("该关联已存在，不能重复添加")

    # 创建关联
    rel = ConceptRelationship(
        source_concept_id=actual_source,
        target_concept_id=actual_target,
        relation_type=relation_type,
        description=description,
        created_by=user_id,
    )
    db.add(rel)

    # conflicts_with 双向同步
    if relation_type == REL_CONFLICTS_WITH:
        # 检查反向是否已存在
        reverse_exists = db.query(ConceptRelationship).filter(
            ConceptRelationship.source_concept_id == actual_target,
            ConceptRelationship.target_concept_id == actual_source,
            ConceptRelationship.relation_type == REL_CONFLICTS_WITH,
        ).first()
        if not reverse_exists:
            reverse_rel = ConceptRelationship(
                source_concept_id=actual_target,
                target_concept_id=actual_source,
                relation_type=REL_CONFLICTS_WITH,
                description=description,
                created_by=user_id,
                is_auto_generated=True,
            )
            db.add(reverse_rel)

    db.commit()

    # 重新查询获取完整信息
    return {
        "id": rel.id,
        "source_concept_id": rel.source_concept_id,
        "target_concept_id": rel.target_concept_id,
        "relation_type": rel.relation_type,
        "description": rel.description,
        "created_by": rel.created_by,
        "created_at": rel.created_at,
        "is_auto_generated": rel.is_auto_generated,
    }


def delete_relationship(db: Session, rel_id: int, concept_id: str, user_id: int) -> bool:
    """删除关联关系（同时删除双向关联）"""
    rel = db.query(ConceptRelationship).filter(
        ConceptRelationship.id == rel_id,
    ).first()
    if not rel:
        raise ValueError("关联不存在")

    # 校验关联属于该概念
    if rel.source_concept_id != concept_id and rel.target_concept_id != concept_id:
        raise ValueError("该关联不属于此概念")

    db.delete(rel)

    # 如果是 conflicts_with，同时删除反向关联
    if rel.relation_type == REL_CONFLICTS_WITH:
        reverse_rel = db.query(ConceptRelationship).filter(
            ConceptRelationship.source_concept_id == rel.target_concept_id,
            ConceptRelationship.target_concept_id == rel.source_concept_id,
            ConceptRelationship.relation_type == REL_CONFLICTS_WITH,
        ).first()
        if reverse_rel:
            db.delete(reverse_rel)

    db.commit()
    return True
