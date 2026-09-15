"""Versioned prompt management for the one-time portrait beautify stage."""

from copy import deepcopy
import hashlib

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import beijing_now
from app.expo.models import ExpoBeautifyPromptVersion
from app.expo.prompt_service import PromptError


def serialize(row: ExpoBeautifyPromptVersion, *, detail: bool = False) -> dict:
    data = {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "revision": row.revision,
        "is_published": row.published_slot == 1,
        "updated_by": row.updated_by,
        "published_by": row.published_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "published_at": row.published_at,
    }
    if detail:
        data["prompt_text"] = row.prompt_text
    return data


def list_versions(db: Session, *, keyword: str = "", page: int = 1, page_size: int = 20):
    query = db.query(ExpoBeautifyPromptVersion)
    if keyword.strip():
        query = query.filter(ExpoBeautifyPromptVersion.name.contains(keyword.strip(), autoescape=True))
    total = query.count()
    rows = (query.order_by(ExpoBeautifyPromptVersion.published_slot.desc(), ExpoBeautifyPromptVersion.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return rows, total


def get_version(db: Session, version_id: int, *, lock: bool = False) -> ExpoBeautifyPromptVersion:
    query = db.query(ExpoBeautifyPromptVersion).filter(ExpoBeautifyPromptVersion.id == version_id)
    if lock:
        query = query.populate_existing().with_for_update()
    row = query.one_or_none()
    if row is None:
        raise PromptError("美颜提示词版本不存在，请刷新列表", 404)
    return row


def create_version(db: Session, body, user_id: int | None) -> ExpoBeautifyPromptVersion:
    row = ExpoBeautifyPromptVersion(
        name=body.name, prompt_text=body.prompt_text, status="draft", revision=1,
        updated_by=user_id,
    )
    db.add(row)
    db.flush()
    return row


def _check_revision(row, expected_revision: int) -> None:
    if row.revision != expected_revision:
        raise PromptError("此版本已被其他人修改，请重新打开后再保存", 409)


def update_version(db: Session, version_id: int, body, user_id: int | None):
    row = get_version(db, version_id, lock=True)
    _check_revision(row, body.expected_revision)
    if row.status != "draft":
        raise PromptError("已发布或已归档版本不可直接修改，请复制为新草稿", 409)
    row.name = body.name
    row.prompt_text = body.prompt_text
    row.revision += 1
    row.updated_by = user_id
    row.updated_at = beijing_now()
    db.flush()
    return row


def publish(db: Session, version_id: int, expected_revision: int, user_id: int | None):
    # Validate the image preset at publish time. The AI facade returns no credentials.
    from app.ai.service import get_image_config_snapshot

    get_image_config_snapshot(db, get_settings().EXPO_BEAUTIFY_PRESET_NAME)
    rows = (db.query(ExpoBeautifyPromptVersion)
            .filter(or_(ExpoBeautifyPromptVersion.id == version_id,
                        ExpoBeautifyPromptVersion.published_slot == 1))
            .order_by(ExpoBeautifyPromptVersion.id).populate_existing().with_for_update().all())
    target = next((row for row in rows if row.id == version_id), None)
    if target is None:
        raise PromptError("美颜提示词版本不存在，请刷新列表", 404)
    _check_revision(target, expected_revision)
    if target.status != "draft":
        raise PromptError("只有草稿可以发布", 409)
    if not target.prompt_text.strip():
        raise PromptError("美颜提示词不能为空")
    now = beijing_now()
    for row in rows:
        if row.published_slot == 1:
            row.published_slot = None
            row.status = "archived"
            row.revision += 1
            row.updated_at = now
    db.flush()
    target.published_slot = 1
    target.status = "published"
    target.revision += 1
    target.published_by = user_id
    target.updated_by = user_id
    target.published_at = now
    target.updated_at = now
    db.flush()
    return target


def archive(db: Session, version_id: int, expected_revision: int, user_id: int | None):
    row = get_version(db, version_id, lock=True)
    _check_revision(row, expected_revision)
    if row.published_slot == 1:
        raise PromptError("当前发布版本不能归档，请先发布替代版本", 409)
    if row.status == "archived":
        return row
    row.status = "archived"
    row.revision += 1
    row.updated_by = user_id
    row.updated_at = beijing_now()
    db.flush()
    return row


def snapshot_published(db: Session) -> dict:
    from app.ai.service import get_image_config_snapshot

    row = (db.query(ExpoBeautifyPromptVersion)
           .filter(ExpoBeautifyPromptVersion.published_slot == 1,
                   ExpoBeautifyPromptVersion.status == "published")
           .populate_existing().with_for_update().one_or_none())
    if row is None:
        raise PromptError("美颜配置暂不可用，请选择原照片生成或联系管理员", 409)
    config = get_image_config_snapshot(db, get_settings().EXPO_BEAUTIFY_PRESET_NAME)
    return {
        "version_id": row.id,
        "version_name": row.name,
        "revision": row.revision,
        "prompt_text": row.prompt_text,
        "prompt_hash": hashlib.sha256(row.prompt_text.encode("utf-8")).hexdigest(),
        "image_config": deepcopy(config),
    }


def availability(db: Session) -> dict:
    try:
        snapshot = snapshot_published(db)
    except (PromptError, ValueError):
        return {"available": False}
    return {
        "available": True,
        "version": {
            "id": snapshot["version_id"], "name": snapshot["version_name"],
            "revision": snapshot["revision"],
        },
    }
