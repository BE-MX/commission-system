"""数据概念治理 — API 路由"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission, require_any_permission
from app.core.database import get_db
from app.schemas.common import ResponseModel

from app.governance.concept_service import (
    list_concepts as _list_concepts,
    get_concept as _get_concept,
    create_concept as _create_concept,
    update_concept as _update_concept,
    transition_status as _transition_status,
    get_stats as _get_stats,
)
from app.governance.relationship_service import (
    list_relationships as _list_relationships,
    create_relationship as _create_relationship,
    delete_relationship as _delete_relationship,
)
from app.governance.changelog_service import (
    list_change_logs as _list_change_logs,
    get_change_diff as _get_change_diff,
    rollback_to_version as _rollback_to_version,
)
from app.governance.import_service import (
    import_concepts as _import_concepts,
    export_concepts as _export_concepts,
    seed_governance_data as _seed_data,
)
from app.governance.schemas import (
    ConceptCreate, ConceptUpdate, StatusTransition,
    RelationshipCreate, ImportRequest,
)

router = APIRouter()


# ── 概念 CRUD ─────────────────────────────────────────────

@router.get("/concepts")
def api_list_concepts(
    layer: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    confidence: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    owner: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_field: str = Query("updated_at", pattern=r"^(id|name_zh|updated_at|created_at|status|layer)$"),
    sort_order: str = Query("desc", pattern=r"^(asc|desc)$"),
    _user: dict = Depends(require_any_permission("governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    data = _list_concepts(
        db, layer=layer, status=status, confidence=confidence,
        priority=priority, owner=owner, keyword=keyword,
        page=page, page_size=page_size,
        sort_field=sort_field, sort_order=sort_order,
    )
    return ResponseModel(data=data)


@router.get("/stats")
def api_get_stats(
    _user: dict = Depends(require_any_permission("governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    data = _get_stats(db)
    return ResponseModel(data=data)


@router.get("/concepts/{concept_id}")
def api_get_concept(
    concept_id: str,
    _user: dict = Depends(require_any_permission("governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    data = _get_concept(db, concept_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"概念 '{concept_id}' 不存在")
    return ResponseModel(data=data)


@router.post("/concepts")
def api_create_concept(
    payload: ConceptCreate,
    _user: dict = Depends(require_any_permission("governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    user_id = _user.get("sub")
    try:
        data = _create_concept(db, payload, user_id=int(user_id))
        return ResponseModel(code=201, message="创建成功", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/concepts/{concept_id}")
def api_update_concept(
    concept_id: str,
    payload: ConceptUpdate,
    _user: dict = Depends(require_any_permission("governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    user_id = _user.get("sub")
    try:
        data = _update_concept(db, concept_id, payload, user_id=int(user_id))
        return ResponseModel(data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/concepts/{concept_id}/status")
def api_transition_status(
    concept_id: str,
    payload: StatusTransition,
    _user: dict = Depends(require_any_permission("governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    user_id = _user.get("sub")
    try:
        data = _transition_status(
            db, concept_id, payload.action, user_id=int(user_id),
            comment=payload.comment,
        )
        return ResponseModel(data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 关联关系 ──────────────────────────────────────────────

@router.get("/concepts/{concept_id}/relationships")
def api_list_relationships(
    concept_id: str,
    _user: dict = Depends(require_any_permission("governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    try:
        data = _list_relationships(db, concept_id)
        return ResponseModel(data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/concepts/{concept_id}/relationships")
def api_create_relationship(
    concept_id: str,
    payload: RelationshipCreate,
    _user: dict = Depends(require_any_permission("governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    user_id = _user.get("sub")
    try:
        data = _create_relationship(
            db, concept_id,
            target_concept_id=payload.target_concept_id,
            relation_type=payload.relation_type,
            description=payload.description,
            direction=payload.direction,
            user_id=int(user_id),
        )
        return ResponseModel(code=201, message="关联已添加", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/concepts/{concept_id}/relationships/{rel_id}")
def api_delete_relationship(
    concept_id: str,
    rel_id: int,
    _user: dict = Depends(require_permission("governance:admin")),
    db: Session = Depends(get_db),
):
    user_id = _user.get("sub")
    try:
        _delete_relationship(db, rel_id, concept_id, user_id=int(user_id))
        return ResponseModel(message="关联已删除")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 变更记录 ──────────────────────────────────────────────

@router.get("/change-logs")
def api_list_change_logs(
    concept_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    operator: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    # governance_log:read=变更历史页面码（063 拆分），保留旧码兼容
    _user: dict = Depends(require_any_permission("governance_log:read", "governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    data = _list_change_logs(
        db, concept_id=concept_id, action=action, operator=operator,
        page=page, page_size=page_size,
    )
    return ResponseModel(data=data)


@router.get("/change-logs/{log_id}/diff")
def api_get_change_diff(
    log_id: int,
    _user: dict = Depends(require_any_permission("governance_log:read", "governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    try:
        data = _get_change_diff(db, log_id)
        return ResponseModel(data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/change-logs/{log_id}/rollback")
def api_rollback(
    log_id: int,
    _user: dict = Depends(require_permission("governance:admin")),
    db: Session = Depends(get_db),
):
    user_id = _user.get("sub")
    try:
        data = _rollback_to_version(db, log_id, user_id=int(user_id))
        return ResponseModel(message="已回滚", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 图谱数据 ──────────────────────────────────────────────

@router.get("/graph")
def api_get_graph(
    # governance_graph:read=全景关系图页面码（063 拆分），保留旧码兼容
    _user: dict = Depends(require_any_permission("governance_graph:read", "governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    from app.governance.models import DataConcept, ConceptRelationship
    from app.governance.schemas import GraphNode, GraphEdge, GraphData

    concepts = db.query(DataConcept).all()
    rels = db.query(ConceptRelationship).filter(
        ConceptRelationship.is_auto_generated == False,  # noqa: E712
    ).all()

    nodes = [
        GraphNode(
            node_id=c.id,
            label=c.name_zh,
            label_en=c.name_en,
            layer=c.layer,
            status=c.status,
            priority=c.priority,
        )
        for c in concepts
    ]

    edges = [
        GraphEdge(
            source=r.source_concept_id,
            target=r.target_concept_id,
            relation_type=r.relation_type,
            description=r.description,
        )
        for r in rels
    ]

    data = GraphData(nodes=nodes, edges=edges).model_dump()
    return ResponseModel(data=data)


# ── 批量导入/导出 ─────────────────────────────────────────

@router.post("/import")
def api_import(
    payload: ImportRequest,
    _user: dict = Depends(require_permission("governance:admin")),
    db: Session = Depends(get_db),
):
    user_id = _user.get("sub")
    data = _import_concepts(db, payload, user_id=int(user_id))
    return ResponseModel(data=data)


@router.get("/export")
def api_export(
    format: str = Query("json", pattern=r"^(json|markdown)$"),
    _user: dict = Depends(require_any_permission("governance:read", "governance:write", "governance:admin")),
    db: Session = Depends(get_db),
):
    data = _export_concepts(db, format=format)
    return ResponseModel(data=data)


@router.post("/seed")
def api_seed(
    _user: dict = Depends(require_permission("governance:admin")),
    db: Session = Depends(get_db),
):
    """初始化种子数据（幂等）"""
    data = _seed_data(db)
    return ResponseModel(data=data)
