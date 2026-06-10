"""数据概念治理 — 变更记录 + diff + 回滚"""

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.governance.models import (
    DataConcept,
    ConceptChangeLog,
    ACTION_EDIT, ACTION_ROLLBACK,
)
from app.governance.schemas import ChangeLogResponse, ChangeLogDiff


def list_change_logs(
    db: Session,
    *,
    concept_id: Optional[str] = None,
    action: Optional[str] = None,
    operator: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
) -> dict:
    """变更历史列表"""
    q = db.query(ConceptChangeLog)

    if concept_id:
        q = q.filter(ConceptChangeLog.concept_id == concept_id)
    if action:
        q = q.filter(ConceptChangeLog.action == action)
    if operator:
        q = q.filter(ConceptChangeLog.operator == operator)

    q = q.order_by(ConceptChangeLog.timestamp.desc())

    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    # 附加概念中文名
    result_items = []
    for log in items:
        data = ChangeLogResponse.model_validate(log).model_dump()
        concept = db.query(DataConcept).filter(DataConcept.id == log.concept_id).first()
        data["concept_name_zh"] = concept.name_zh if concept else None
        result_items.append(data)

    return {
        "items": result_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_change_diff(db: Session, log_id: int) -> dict:
    """获取单条变更的 diff 详情"""
    log = db.query(ConceptChangeLog).filter(ConceptChangeLog.id == log_id).first()
    if not log:
        raise ValueError("变更记录不存在")

    data = ChangeLogResponse.model_validate(log).model_dump()
    concept = db.query(DataConcept).filter(DataConcept.id == log.concept_id).first()
    data["concept_name_zh"] = concept.name_zh if concept else None

    # 构建 diff 列表
    diffs = []
    if log.changed_fields:
        for change in log.changed_fields:
            diffs.append({
                "field": change.get("field", ""),
                "before": change.get("before"),
                "after": change.get("after"),
            })

    return ChangeLogDiff(log=data, diffs=diffs).model_dump()


def rollback_to_version(db: Session, log_id: int, user_id: int) -> dict:
    """回滚到指定版本"""
    log = db.query(ConceptChangeLog).filter(ConceptChangeLog.id == log_id).first()
    if not log:
        raise ValueError("变更记录不存在")

    if not log.snapshot:
        raise ValueError("该变更记录没有快照，无法回滚")

    concept = db.query(DataConcept).filter(DataConcept.id == log.concept_id).first()
    if not concept:
        raise ValueError(f"概念 '{log.concept_id}' 不存在")

    old_snapshot = concept.to_snapshot_dict()

    # 从快照恢复
    snapshot = log.snapshot
    for field in [
        "name_zh", "name_en", "layer", "priority", "one_liner",
        "full_definition", "boundary_includes", "boundary_excludes",
        "formula", "numerator", "denominator", "unit",
        "primary_table", "primary_field", "filter_conditions",
        "related_tables", "time_granularity", "entity_granularity",
        "segments", "owner", "staleness_trigger", "confidence", "notes",
    ]:
        if field in snapshot:
            setattr(concept, field, snapshot[field])

    if "status" in snapshot:
        concept.status = snapshot["status"]

    concept.updated_by = user_id
    db.flush()

    # 记录回滚操作
    changed = []
    for field in [
        "name_zh", "name_en", "one_liner", "full_definition",
        "boundary_includes", "boundary_excludes", "formula",
        "status",
    ]:
        old_val = old_snapshot.get(field)
        new_val = snapshot.get(field)
        if old_val != new_val:
            changed.append({"field": field, "before": old_val, "after": new_val})

    rollback_log = ConceptChangeLog(
        concept_id=concept.id,
        operator=str(user_id),
        action=ACTION_ROLLBACK,
        changed_fields=changed if changed else None,
        comment=f"回滚到变更记录 #{log_id} 的版本",
        snapshot=concept.to_snapshot_dict(),
    )
    db.add(rollback_log)
    db.commit()

    from app.governance.concept_service import get_concept
    return get_concept(db, concept.id)
