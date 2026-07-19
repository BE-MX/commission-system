"""PM Hub 版本评论（评论挂具体版本，划线锚点评论属 Phase 2 另一条线，本文件不涉及）。

规则：
- 评论的宿主是版本：新评论必须挂在未删除版本上（无版本资料没有评论）
- 单层回复：parent_id 只指向顶层评论；回复「回复」时自动拍平挂到顶层父级；
  回复继承线程所在版本（顶层的 version_id），线程不跨版本漂移
- 删除仅限作者本人（资料/版本全站可删是信任制，评论是个人发言，语义不同）
- 软删父评论若仍有活回复，列表返回占位（body 置空 + is_deleted），防孤儿回复
"""

import logging
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.pm.models import PmComment, PmMaterial, PmMaterialVersion, bj_now
from app.pm.service import audit

logger = logging.getLogger("commission")


def get_comment(db: Session, comment_id: int) -> Optional[PmComment]:
    return (
        db.query(PmComment)
        .filter(PmComment.id == comment_id, PmComment.deleted_at.is_(None))
        .first()
    )


def comment_counts(db: Session, material_ids: list[int]) -> dict[int, int]:
    """未删除评论数（占位用的已删父评论不计——计数只反映可读发言量）。"""
    if not material_ids:
        return {}
    rows = (
        db.query(PmComment.material_id, func.count(PmComment.id))
        .filter(PmComment.material_id.in_(material_ids), PmComment.deleted_at.is_(None))
        .group_by(PmComment.material_id)
        .all()
    )
    return dict(rows)


def _to_dict(c: PmComment, version_nos: dict[int, int]) -> dict:
    deleted = c.deleted_at is not None
    return {
        "id": c.id,
        "material_id": c.material_id,
        "parent_id": c.parent_id,
        "body": None if deleted else c.body,
        "author": c.author,
        "status": c.status,
        "version_no": version_nos.get(c.version_id) if c.version_id else None,
        "created_at": c.created_at.isoformat(sep=" ") if c.created_at else None,
        "is_deleted": deleted,
        "replies": [],
    }


def list_comments(db: Session, material_id: int) -> list[dict]:
    """顶层评论（时间正序）+ 嵌套回复。已删顶层仅在有活回复时以占位返回。"""
    comments = (
        db.query(PmComment)
        .filter(PmComment.material_id == material_id)
        .order_by(PmComment.id)
        .all()
    )
    alive = [c for c in comments if c.deleted_at is None]
    alive_parent_ids = {c.parent_id for c in alive if c.parent_id}
    version_ids = {c.version_id for c in comments if c.version_id}
    version_nos: dict[int, int] = {}
    if version_ids:
        rows = (
            db.query(PmMaterialVersion.id, PmMaterialVersion.version_no)
            .filter(PmMaterialVersion.id.in_(version_ids))
            .all()
        )
        version_nos = dict(rows)

    top: dict[int, dict] = {}
    for c in comments:
        if c.parent_id is not None:
            continue
        if c.deleted_at is not None and c.id not in alive_parent_ids:
            continue  # 已删且无活回复：不返回
        top[c.id] = _to_dict(c, version_nos)
    for c in alive:
        if c.parent_id is None:
            continue
        parent = top.get(c.parent_id)
        if parent is None:
            # 父评论已删且无其他活回复的分支不会走到这里；防御性跳过脏数据
            logger.warning("[PM] orphan comment reply id=%s parent=%s", c.id, c.parent_id)
            print(f"[PM] orphan comment reply id={c.id} parent={c.parent_id}", flush=True)
            continue
        parent["replies"].append(_to_dict(c, version_nos))
    return list(top.values())


def create_comment(db: Session, material: PmMaterial, version: PmMaterialVersion,
                   username: str, body: str, parent_id: Optional[int] = None) -> PmComment:
    text = body.strip()
    if not text:
        raise ValueError("评论内容不能为空")
    resolved_parent_id = None
    version_id = version.id
    if parent_id is not None:
        # 父评论查询不过滤软删：已删顶层的线程以占位形式仍然可见（见 list_comments），
        # 续贴必须被允许，否则 UI 上的「回复」是个结构性死按钮（对抗性审查 2026-07-19）
        parent = db.query(PmComment).filter(PmComment.id == parent_id).first()
        if not parent or parent.material_id != material.id:
            raise ValueError("被回复的评论不存在")
        # 单层回复：回复「回复」自动拍平到顶层父级
        resolved_parent_id = parent.parent_id or parent.id
        # 回复继承线程所在版本（顶层的 version_id），不取 URL 版本——线程不跨卡漂移
        top = parent if parent.parent_id is None else db.query(PmComment).filter(PmComment.id == parent.parent_id).first()
        if top and top.version_id:
            version_id = top.version_id
    comment = PmComment(
        material_id=material.id,
        version_id=version_id,
        parent_id=resolved_parent_id,
        body=text[:2048],
        author=username,
        created_at=bj_now(),
    )
    db.add(comment)
    db.flush()
    if version_id == version.id:
        anchored_no = version.version_no
    else:  # 回复继承了线程版本，取其版本号入审计
        v = db.query(PmMaterialVersion.version_no).filter(PmMaterialVersion.id == version_id).first()
        anchored_no = v[0] if v else None
    audit(
        db, material.project_id, username, "create_comment", "comment", comment.id,
        f"{material.name} v{anchored_no}" if anchored_no else material.name,
        {"snippet": text[:120], "material_id": material.id, "reply": resolved_parent_id is not None},
    )
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(db: Session, comment: PmComment, material: PmMaterial, username: str) -> None:
    """软删。权限（仅作者）由 router 层校验——service 不重复判，保持单一职责。"""
    comment.deleted_at = bj_now()
    audit(
        db, material.project_id, username, "delete_comment", "comment", comment.id,
        material.name, {"snippet": (comment.body or "")[:120]},
    )
    db.commit()


def comment_to_dict(db: Session, comment: PmComment) -> dict:
    version_nos: dict[int, int] = {}
    if comment.version_id:
        v = (
            db.query(PmMaterialVersion)
            .filter(PmMaterialVersion.id == comment.version_id)
            .first()
        )
        if v:
            version_nos[v.id] = v.version_no
    return _to_dict(comment, version_nos)
