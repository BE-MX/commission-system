"""数据概念治理 — 概念 CRUD + 状态流转 + 完整度校验"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.governance.models import (
    DataConcept,
    ConceptChangeLog,
    STATUS_DRAFT, STATUS_PENDING, STATUS_IN_PROGRESS,
    STATUS_REVIEW, STATUS_ACTIVE, STATUS_DEPRECATED,
    ACTION_CREATE, ACTION_EDIT, ACTION_SUBMIT,
    ACTION_APPROVE, ACTION_REJECT, ACTION_DEPRECATE,
)
from app.governance.schemas import (
    ConceptCreate, ConceptUpdate, ConceptResponse,
    ConceptListItem, ConceptStats,
)

# ── 必填字段列表（用于完整度校验） ──────────────────────────

REQUIRED_FIELDS = [
    "name_zh", "name_en", "layer", "one_liner", "full_definition",
    "boundary_includes", "boundary_excludes", "unit",
    "primary_table", "primary_field",
    "time_granularity", "entity_granularity",
    "owner", "staleness_trigger", "confidence",
]

RECOMMENDED_FIELDS = [
    "formula", "filter_conditions", "segments", "notes",
    "numerator", "denominator",
]


# ── 完整度计算 ────────────────────────────────────────────

def compute_completeness(concept: DataConcept) -> dict:
    """计算字段完整度"""
    required_filled = sum(1 for f in REQUIRED_FIELDS if getattr(concept, f, None))
    required_total = len(REQUIRED_FIELDS)
    recommended_filled = sum(1 for f in RECOMMENDED_FIELDS if getattr(concept, f, None))
    recommended_total = len(RECOMMENDED_FIELDS)
    all_filled = required_filled + recommended_filled
    all_total = required_total + recommended_total

    return {
        "required_filled": required_filled,
        "required_total": required_total,
        "recommended_filled": recommended_filled,
        "recommended_total": recommended_total,
        "percentage": round(all_filled / all_total * 100, 1) if all_total else 0,
        "is_submittable": required_filled == required_total,
        "missing_required": [f for f in REQUIRED_FIELDS if not getattr(concept, f, None)],
    }


# ── CRUD ──────────────────────────────────────────────────

def list_concepts(
    db: Session,
    *,
    layer: Optional[str] = None,
    status: Optional[str] = None,
    confidence: Optional[str] = None,
    priority: Optional[str] = None,
    owner: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    sort_field: str = "updated_at",
    sort_order: str = "desc",
) -> dict:
    """概念列表（分页 + 筛选 + 排序）"""
    q = db.query(DataConcept)

    if layer:
        q = q.filter(DataConcept.layer == layer)
    if status:
        q = q.filter(DataConcept.status == status)
    if confidence:
        q = q.filter(DataConcept.confidence == confidence)
    if priority:
        q = q.filter(DataConcept.priority == priority)
    if owner:
        q = q.filter(DataConcept.owner.contains(owner))
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(
            (DataConcept.id.like(kw))
            | (DataConcept.name_zh.like(kw))
            | (DataConcept.name_en.like(kw))
        )

    # 排序映射
    sort_map = {
        "id": DataConcept.id,
        "name_zh": DataConcept.name_zh,
        "updated_at": DataConcept.updated_at,
        "created_at": DataConcept.created_at,
        "status": DataConcept.status,
        "layer": DataConcept.layer,
    }
    sort_col = sort_map.get(sort_field, DataConcept.updated_at)
    if sort_order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [ConceptListItem.model_validate(c).model_dump() for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_concept(db: Session, concept_id: str) -> Optional[dict]:
    """获取单个概念详情"""
    concept = db.query(DataConcept).filter(DataConcept.id == concept_id).first()
    if not concept:
        return None

    data = ConceptResponse.model_validate(concept).model_dump()
    comp = compute_completeness(concept)
    data["completeness"] = comp
    return data


def create_concept(db: Session, payload: ConceptCreate, user_id: int) -> dict:
    """创建概念"""
    existing = db.query(DataConcept).filter(DataConcept.id == payload.id).first()
    if existing:
        raise ValueError(f"概念ID '{payload.id}' 已存在")

    concept = DataConcept(
        **payload.model_dump(exclude_none=True),
        status=STATUS_DRAFT,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(concept)
    db.flush()

    # 变更记录
    _record_change(db, concept.id, user_id, ACTION_CREATE, snapshot=concept.to_snapshot_dict())
    db.commit()

    return get_concept(db, concept.id)


def update_concept(db: Session, concept_id: str, payload: ConceptUpdate, user_id: int) -> dict:
    """更新概念（部分更新 + diff 记录）"""
    concept = db.query(DataConcept).filter(DataConcept.id == concept_id).first()
    if not concept:
        raise ValueError(f"概念 '{concept_id}' 不存在")

    # 只有 draft / in_progress 状态可编辑
    if concept.status not in (STATUS_DRAFT, STATUS_IN_PROGRESS):
        raise ValueError(f"状态 '{concept.status}' 下不可编辑，需先撤回")

    old_snapshot = concept.to_snapshot_dict()
    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        return get_concept(db, concept_id)

    changed = []
    for field, new_val in update_data.items():
        old_val = getattr(concept, field)
        if old_val != new_val:
            changed.append({
                "field": field,
                "before": old_val,
                "after": new_val,
            })
            setattr(concept, field, new_val)

    concept.updated_by = user_id
    db.flush()

    if changed:
        _record_change(
            db, concept_id, user_id, ACTION_EDIT,
            changed_fields=changed,
            snapshot=concept.to_snapshot_dict(),
        )

    db.commit()
    return get_concept(db, concept_id)


# ── 状态流转 ──────────────────────────────────────────────

# 合法状态转换表
_TRANSITIONS = {
    "claim": {
        "from": [STATUS_PENDING],
        "to": STATUS_IN_PROGRESS,
        "action": ACTION_EDIT,
    },
    "submit": {
        "from": [STATUS_DRAFT, STATUS_IN_PROGRESS],
        "to": STATUS_REVIEW,
        "action": ACTION_SUBMIT,
    },
    "approve": {
        "from": [STATUS_REVIEW],
        "to": STATUS_ACTIVE,
        "action": ACTION_APPROVE,
    },
    "reject": {
        "from": [STATUS_REVIEW],
        "to": STATUS_IN_PROGRESS,
        "action": ACTION_REJECT,
    },
    "deprecate": {
        "from": [STATUS_ACTIVE],
        "to": STATUS_DEPRECATED,
        "action": ACTION_DEPRECATE,
    },
}


def transition_status(
    db: Session, concept_id: str, action: str, user_id: int, comment: Optional[str] = None,
) -> dict:
    """状态流转"""
    concept = db.query(DataConcept).filter(DataConcept.id == concept_id).first()
    if not concept:
        raise ValueError(f"概念 '{concept_id}' 不存在")

    rule = _TRANSITIONS.get(action)
    if not rule:
        raise ValueError(f"未知操作 '{action}'，支持: {list(_TRANSITIONS.keys())}")

    if concept.status not in rule["from"]:
        raise ValueError(f"'{action}' 操作要求状态为 {rule['from']}，当前为 '{concept.status}'")

    # 提交审批前检查完整度
    if action == "submit":
        comp = compute_completeness(concept)
        if not comp["is_submittable"]:
            missing = ", ".join(comp["missing_required"])
            raise ValueError(f"必填字段未填完: {missing}")

    old_status = concept.status
    concept.status = rule["to"]
    concept.updated_by = user_id
    db.flush()

    _record_change(
        db, concept_id, user_id, rule["action"],
        changed_fields=[{"field": "status", "before": old_status, "after": rule["to"]}],
        comment=comment,
        snapshot=concept.to_snapshot_dict(),
    )
    db.commit()

    return get_concept(db, concept_id)


def batch_set_pending(db: Session, concept_ids: list[str], priority: str, user_id: int) -> int:
    """批量设置概念为 pending 状态（导入时用）"""
    count = 0
    for cid in concept_ids:
        concept = db.query(DataConcept).filter(DataConcept.id == cid).first()
        if concept and concept.status == STATUS_DRAFT:
            concept.status = STATUS_PENDING
            concept.priority = priority
            concept.updated_by = user_id
            count += 1
    if count:
        db.commit()
    return count


# ── 统计 ──────────────────────────────────────────────────

def get_stats(db: Session) -> dict:
    """概念进度统计"""
    total = db.query(func.count(DataConcept.id)).scalar() or 0
    active = db.query(func.count(DataConcept.id)).filter(DataConcept.status == STATUS_ACTIVE).scalar() or 0
    pending = db.query(func.count(DataConcept.id)).filter(DataConcept.status == STATUS_PENDING).scalar() or 0
    in_progress = db.query(func.count(DataConcept.id)).filter(DataConcept.status == STATUS_IN_PROGRESS).scalar() or 0
    review = db.query(func.count(DataConcept.id)).filter(DataConcept.status == STATUS_REVIEW).scalar() or 0
    draft = db.query(func.count(DataConcept.id)).filter(DataConcept.status == STATUS_DRAFT).scalar() or 0
    deprecated = db.query(func.count(DataConcept.id)).filter(DataConcept.status == STATUS_DEPRECATED).scalar() or 0

    # 按优先级统计待补充
    by_priority = {}
    for p in ("P1", "P2", "P3"):
        by_priority[p] = db.query(func.count(DataConcept.id)).filter(
            DataConcept.priority == p,
            DataConcept.status.in_([STATUS_PENDING, STATUS_IN_PROGRESS]),
        ).scalar() or 0

    return ConceptStats(
        total=total, active=active, pending=pending,
        in_progress=in_progress, review=review, draft=draft,
        deprecated=deprecated, by_priority=by_priority,
    ).model_dump()


# ── 内部辅助 ──────────────────────────────────────────────

def _record_change(
    db: Session,
    concept_id: str,
    user_id: int,
    action: str,
    changed_fields: list | None = None,
    comment: str | None = None,
    snapshot: dict | None = None,
):
    """写变更记录"""
    log = ConceptChangeLog(
        concept_id=concept_id,
        operator=str(user_id),
        action=action,
        changed_fields=changed_fields,
        comment=comment,
        snapshot=snapshot,
    )
    db.add(log)
