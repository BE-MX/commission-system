"""培训速递 — 核心 service：CRUD / 发布校验（★必填分区） / 有用反馈 / 删除清理"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.training import file_service
from app.training.models import TrainingDigest, TrainingDigestFeedback, TrainingDigestFile
from app.training.schemas import DigestCreate, DigestSections, DigestUpdate

logger = logging.getLogger("commission")

# 发布校验阈值（强引导的量化底线，前端同步展示）
MIN_HIGHLIGHTS = 3
MAX_HIGHLIGHTS = 5
MIN_REVIEW_CHARS = 15
MAX_SUMMARY_CHARS = 100
READ_CHARS_PER_MINUTE = 400


def can_manage(user: dict, digest: TrainingDigest) -> bool:
    """作者本人或 training:admin（super_admin 绕过）可编辑/删除。"""
    if "super_admin" in user.get("roles", []):
        return True
    if "training:admin" in user.get("permissions", []):
        return True
    return digest.created_by == int(user["sub"])


def create_digest(db: Session, payload: DigestCreate, user_id: int) -> TrainingDigest:
    digest = TrainingDigest(
        title=payload.title.strip(),
        org=(payload.org or "").strip() or None,
        lecturer=(payload.lecturer or "").strip() or None,
        trained_at=payload.trained_at,
        attendees_json=payload.attendees,
        tags_json=payload.tags,
        sections_json=DigestSections().model_dump(),
        status="draft",
        created_by=user_id,
    )
    db.add(digest)
    db.commit()
    db.refresh(digest)
    return digest


def update_digest(db: Session, digest: TrainingDigest, payload: DigestUpdate) -> TrainingDigest:
    if payload.title is not None:
        digest.title = payload.title.strip()
    if payload.org is not None:
        digest.org = payload.org.strip() or None
    if payload.lecturer is not None:
        digest.lecturer = payload.lecturer.strip() or None
    if payload.trained_at is not None:
        digest.trained_at = payload.trained_at
    if payload.attendees is not None:
        digest.attendees_json = payload.attendees
    if payload.tags is not None:
        digest.tags_json = payload.tags
    if payload.summary is not None:
        digest.summary = payload.summary.strip()
    if payload.sections is not None:
        digest.sections_json = payload.sections.model_dump()
    digest.updated_at = datetime.now()
    db.commit()
    db.refresh(digest)
    return digest


def validate_for_publish(digest: TrainingDigest) -> list[str]:
    """★必填分区校验。返回缺失项中文清单（空列表 = 可发布）。"""
    problems: list[str] = []
    summary = (digest.summary or "").strip()
    if not summary:
        problems.append("「一句话总结」未填写")
    elif len(summary) > MAX_SUMMARY_CHARS:
        problems.append(f"「一句话总结」超过 {MAX_SUMMARY_CHARS} 字，请压缩到一句话")

    sections = DigestSections.model_validate(digest.sections_json or {})

    highlights = [h for h in sections.highlights if h.title.strip()]
    if len(highlights) < MIN_HIGHLIGHTS:
        problems.append(f"「重点」至少 {MIN_HIGHLIGHTS} 条（当前 {len(highlights)} 条）")
    elif len(highlights) > MAX_HIGHLIGHTS:
        problems.append(f"「重点」最多 {MAX_HIGHLIGHTS} 条，请合并或删减")

    applications = [a for a in sections.applications if a.point.strip()]
    if not applications:
        problems.append("「可应用点」至少 1 条")
    else:
        for i, app_item in enumerate(applications, start=1):
            if not app_item.roles:
                problems.append(f"「可应用点」第 {i} 条未选适用岗位")
            if not app_item.first_step.strip():
                problems.append(f"「可应用点」第 {i} 条未写落地第一步")

    if len((sections.review or "").strip()) < MIN_REVIEW_CHARS:
        problems.append(f"「参训人点评」至少 {MIN_REVIEW_CHARS} 字——值不值、哪部分水、建议谁重点看")

    return problems


def estimate_read_minutes(digest: TrainingDigest) -> int:
    sections = DigestSections.model_validate(digest.sections_json or {})
    total = len(digest.summary or "")
    for h in sections.highlights:
        total += len(h.title) + len(h.detail)
    total += sum(len(s) for s in sections.new_insights)
    for a in sections.applications:
        total += len(a.point) + len(a.first_step)
    for m in sections.methods:
        total += len(m.name) + len(m.steps)
    total += len(sections.review)
    return max(1, round(total / READ_CHARS_PER_MINUTE))


def publish_digest(db: Session, digest: TrainingDigest) -> TrainingDigest:
    """状态机：draft→published；已发布再编辑后重新 publish 仅刷新时间与阅读时长。"""
    digest.read_minutes = estimate_read_minutes(digest)
    if digest.status != "published":
        digest.status = "published"
        digest.published_at = datetime.now()
    digest.updated_at = datetime.now()
    db.commit()
    db.refresh(digest)
    return digest


def list_digests(
    db: Session,
    *,
    page: int,
    page_size: int,
    user_id: int,
    keyword: str = "",
    tag: str = "",
    status: str = "",
    mine: bool = False,
) -> dict:
    """默认只看已发布；mine=true 看自己创建的全部（含草稿）。"""
    q = db.query(TrainingDigest)
    if mine:
        q = q.filter(TrainingDigest.created_by == user_id)
        if status:
            q = q.filter(TrainingDigest.status == status)
    else:
        q = q.filter(TrainingDigest.status == "published")
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.filter(
            TrainingDigest.title.like(kw)
            | TrainingDigest.org.like(kw)
            | TrainingDigest.lecturer.like(kw)
            | TrainingDigest.summary.like(kw)
        )
    q = q.order_by(TrainingDigest.trained_at.desc(), TrainingDigest.id.desc())
    if tag.strip():
        # JSON 标签过滤：全量取回后内存过滤再分页（速递为低量数据，正确性优先；
        # JSON_CONTAINS 在 SQLite 测试库不可用，LIKE 会被 ensure_ascii 转义坑掉）
        all_rows = q.all()
        wanted = tag.strip()
        filtered = [r for r in all_rows if wanted in (r.tags_json or [])]
        total = len(filtered)
        rows = filtered[(page - 1) * page_size : page * page_size]
    else:
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()

    ids = [r.id for r in rows]
    file_counts: dict[int, int] = {}
    creator_names: dict[int, str] = {}
    if ids:
        for digest_id, cnt in (
            db.query(TrainingDigestFile.digest_id, func.count(TrainingDigestFile.id))
            .filter(TrainingDigestFile.digest_id.in_(ids))
            .group_by(TrainingDigestFile.digest_id)
        ):
            file_counts[digest_id] = cnt
        for uid, real_name, username in (
            db.query(ArkUser.id, ArkUser.real_name, ArkUser.username)
            .filter(ArkUser.id.in_({r.created_by for r in rows}))
        ):
            creator_names[uid] = real_name or username

    items = [_to_list_item(r, file_counts, creator_names) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _to_list_item(r: TrainingDigest, file_counts: dict, creator_names: dict) -> dict:
    return {
        "id": r.id,
        "digest_type": r.digest_type,
        "title": r.title,
        "org": r.org,
        "lecturer": r.lecturer,
        "trained_at": r.trained_at.isoformat() if r.trained_at else None,
        "tags": r.tags_json or [],
        "summary": r.summary,
        "status": r.status,
        "read_minutes": r.read_minutes,
        "view_count": r.view_count,
        "useful_count": r.useful_count,
        "created_by": r.created_by,
        "creator_name": creator_names.get(r.created_by),
        "published_at": r.published_at.isoformat() if r.published_at else None,
        "file_count": file_counts.get(r.id, 0),
    }


def get_detail(db: Session, digest: TrainingDigest, user: dict, *, count_view: bool = True) -> dict:
    user_id = int(user["sub"])
    if count_view and digest.status == "published" and digest.created_by != user_id:
        # 计数用原子 UPDATE，避免读改写竞态
        db.query(TrainingDigest).filter(TrainingDigest.id == digest.id).update(
            {TrainingDigest.view_count: TrainingDigest.view_count + 1}
        )
        db.commit()
        db.refresh(digest)

    files = (
        db.query(TrainingDigestFile)
        .filter(TrainingDigestFile.digest_id == digest.id)
        .order_by(TrainingDigestFile.id)
        .all()
    )
    my_useful = (
        db.query(TrainingDigestFeedback.id)
        .filter(
            TrainingDigestFeedback.digest_id == digest.id,
            TrainingDigestFeedback.user_id == user_id,
            TrainingDigestFeedback.kind == "useful",
        )
        .first()
        is not None
    )
    creator = db.query(ArkUser.real_name, ArkUser.username).filter(ArkUser.id == digest.created_by).first()
    data = _to_list_item(digest, {digest.id: len(files)}, {digest.created_by: (creator[0] or creator[1]) if creator else None})
    data.update(
        {
            "attendees": digest.attendees_json or [],
            "sections": DigestSections.model_validate(digest.sections_json or {}).model_dump(),
            "files": [
                {
                    "id": f.id,
                    "file_name": f.file_name,
                    "file_size": f.file_size,
                    "mime_type": f.mime_type,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in files
            ],
            "my_useful": my_useful,
            "can_edit": can_manage(user, digest),
        }
    )
    return data


def toggle_useful(db: Session, digest: TrainingDigest, user_id: int) -> dict:
    """点一次标记，再点取消。唯一约束兜底并发重复写。"""
    existing = (
        db.query(TrainingDigestFeedback)
        .filter(
            TrainingDigestFeedback.digest_id == digest.id,
            TrainingDigestFeedback.user_id == user_id,
            TrainingDigestFeedback.kind == "useful",
        )
        .first()
    )
    if existing:
        # 按行数确认删除：并发双取消时只有真正删掉行的那个事务扣减，防止双倍下漂
        deleted = (
            db.query(TrainingDigestFeedback)
            .filter(TrainingDigestFeedback.id == existing.id)
            .delete()
        )
        if deleted:
            db.query(TrainingDigest).filter(
                TrainingDigest.id == digest.id, TrainingDigest.useful_count > 0
            ).update({TrainingDigest.useful_count: TrainingDigest.useful_count - 1})
        db.commit()
        marked = False
    else:
        try:
            db.add(TrainingDigestFeedback(digest_id=digest.id, user_id=user_id, kind="useful"))
            db.query(TrainingDigest).filter(TrainingDigest.id == digest.id).update(
                {TrainingDigest.useful_count: TrainingDigest.useful_count + 1}
            )
            db.commit()
        except IntegrityError:
            # 并发重复点击：唯一约束命中，当作已标记成功
            db.rollback()
        marked = True
    db.refresh(digest)
    return {"my_useful": marked, "useful_count": digest.useful_count}


def delete_digest(db: Session, digest: TrainingDigest) -> None:
    """删行 + 清盘。不依赖 FK CASCADE（cerebrum 2026-07-15）：先删子行，文件清理放最后尽力而为。"""
    files = db.query(TrainingDigestFile).filter(TrainingDigestFile.digest_id == digest.id).all()
    paths = [f.storage_path for f in files]
    db.query(TrainingDigestFeedback).filter(TrainingDigestFeedback.digest_id == digest.id).delete()
    db.query(TrainingDigestFile).filter(TrainingDigestFile.digest_id == digest.id).delete()
    db.delete(digest)
    db.commit()
    for p in paths:
        file_service.remove_quietly(p)


def add_file(db: Session, digest: TrainingDigest, *, file_name: str, storage_path: str,
             file_size: int, mime_type: str, uploaded_by: int) -> TrainingDigestFile:
    item = TrainingDigestFile(
        digest_id=digest.id,
        file_name=file_name,
        storage_path=storage_path,
        file_size=file_size,
        mime_type=mime_type,
        uploaded_by=uploaded_by,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def remove_file(db: Session, item: TrainingDigestFile) -> None:
    path = item.storage_path
    db.delete(item)
    db.commit()
    file_service.remove_quietly(path)
