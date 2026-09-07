"""Version management, preview and atomic generation snapshots. Callers commit."""

from copy import deepcopy
from types import SimpleNamespace

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.expo.models import ExpoPromptVersion, ExpoResult, ExpoWig
from app.expo.prompt_catalog import SCENES
from app.expo.prompt_renderer import render_prompt
from app.expo.prompt_schemas import PromptConfig


class PromptError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def serialize_version(row: ExpoPromptVersion, *, detail: bool = False) -> dict:
    data = {"id": row.id, "name": row.name, "hint": row.hint, "revision": row.revision,
            "is_active": bool(row.is_active), "is_default": row.default_slot == 1,
            "updated_at": row.updated_at}
    if detail:
        data["config"] = deepcopy(row.config_json)
    return data


def list_versions(db: Session, *, keyword: str = "", only_active: bool = False,
                  page: int = 1, page_size: int = 20) -> tuple[list, int]:
    query = db.query(ExpoPromptVersion)
    if only_active:
        query = query.filter(ExpoPromptVersion.is_active.is_(True))
    if keyword.strip():
        query = query.filter(ExpoPromptVersion.name.contains(keyword.strip(), autoescape=True))
    total = query.count()
    rows = (query.order_by(ExpoPromptVersion.default_slot.desc(), ExpoPromptVersion.id.asc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return rows, total


def picker_options(db: Session) -> list[dict]:
    # A fresh request always reads current DB rows; no process-local prompt cache.
    rows = (db.query(ExpoPromptVersion).filter(ExpoPromptVersion.is_active.is_(True))
            .order_by(ExpoPromptVersion.default_slot.desc(), ExpoPromptVersion.id.asc()).all())
    return [serialize_version(row) for row in rows]


def get_version(db: Session, version_id: int, *, lock: bool = False) -> ExpoPromptVersion:
    query = db.query(ExpoPromptVersion).filter(ExpoPromptVersion.id == version_id)
    if lock:
        query = query.populate_existing().with_for_update()
    row = query.one_or_none()
    if row is None:
        raise PromptError("提示词版本不存在，请刷新列表", 404)
    return row


def create_version(db: Session, body, user_id: int | None) -> ExpoPromptVersion:
    row = ExpoPromptVersion(name=body.name, hint=body.hint, is_active=body.is_active,
                            config_json=body.config.model_dump(), revision=1, updated_by=user_id)
    db.add(row)
    db.flush()
    return row


def _check_revision(row: ExpoPromptVersion, expected_revision: int) -> None:
    if row.revision != expected_revision:
        raise PromptError("此版本已被其他人修改，请重新打开后再保存", 409)


def update_version(db: Session, version_id: int, body, user_id: int | None) -> ExpoPromptVersion:
    row = get_version(db, version_id, lock=True)
    _check_revision(row, body.expected_revision)
    if row.default_slot == 1 and not body.is_active:
        raise PromptError("默认版本不能停用，请先设置另一个默认版本")
    row.name, row.hint, row.is_active = body.name, body.hint, body.is_active
    row.config_json = body.config.model_dump()
    row.revision += 1
    row.updated_by = user_id
    row.updated_at = beijing_now()
    db.flush()
    return row


def set_default(db: Session, version_id: int, expected_revision: int, user_id: int | None) -> ExpoPromptVersion:
    rows = (db.query(ExpoPromptVersion)
            .filter(or_(ExpoPromptVersion.id == version_id, ExpoPromptVersion.default_slot == 1))
            .order_by(ExpoPromptVersion.id).populate_existing().with_for_update().all())
    target = next((row for row in rows if row.id == version_id), None)
    if target is None:
        raise PromptError("提示词版本不存在，请刷新列表", 404)
    _check_revision(target, expected_revision)
    if not target.is_active:
        raise PromptError("请先启用该版本，再设为默认")
    if target.default_slot == 1:
        return target
    now = beijing_now()
    for row in rows:
        if row.default_slot == 1:
            row.default_slot = None
            row.revision += 1
            row.updated_by, row.updated_at = user_id, now
    db.flush()  # Release the unique slot before assigning it, within this transaction.
    target.default_slot = 1
    target.revision += 1
    target.updated_by, target.updated_at = user_id, now
    db.flush()
    return target


def capture_batch(db: Session, session, rows: list[ExpoResult], version_id: int | None) -> ExpoPromptVersion:
    """No commit here: snapshots and quota deduction belong to one transaction."""
    from app.expo import ai_pipeline

    if version_id is None:
        version = (db.query(ExpoPromptVersion).filter(ExpoPromptVersion.default_slot == 1)
                   .populate_existing().with_for_update().one_or_none())
        if version is None:
            raise PromptError("尚未设置默认提示词版本，请联系管理员配置", 409)
    else:
        version = get_version(db, version_id, lock=True)
    if not version.is_active:
        raise PromptError("所选提示词版本已停用，请重新选择", 409)
    try:
        config = PromptConfig.model_validate(version.config_json).model_dump()
    except ValueError as exc:
        raise PromptError("所选提示词版本配置不完整，请联系管理员修正", 409) from exc
    wig_ids = {row.wig_id for row in rows if row.wig_id is not None}
    wigs = {wig.id: wig for wig in db.query(ExpoWig).filter(ExpoWig.id.in_(wig_ids)).all()} if wig_ids else {}
    snapshots = []
    for row in rows:
        prompt, images, size = render_prompt(session, row, wigs.get(row.wig_id), config, ai_pipeline.to_abs)
        snapshots.append({"version_id": version.id, "version_name": version.name, "revision": version.revision,
                          "text": prompt, "image_paths": [ai_pipeline.to_rel(path) for path in images], "size": size})
    # Validate every row before modifying any row so a bad batch cannot be partly captured.
    for row, snapshot in zip(rows, snapshots):
        row.prompt_version_id = version.id
        row.prompt_snapshot = snapshot
    return version


def read_snapshot(row: ExpoResult) -> tuple[str, list, str | None]:
    from app.expo import ai_pipeline

    snap = row.prompt_snapshot or {}
    if not snap.get("text") or not snap.get("image_paths"):
        raise PromptError("此任务未保存提示词快照，请返回选择页重新生成")
    return snap["text"], [ai_pipeline.to_abs(path) for path in snap["image_paths"]], snap.get("size")


def result_version(row: ExpoResult) -> dict | None:
    snap = row.prompt_snapshot
    if not snap:
        return None
    return {"id": snap["version_id"], "name": snap["version_name"], "revision": snap["revision"]}


def preview(db: Session, body) -> dict:
    from app.expo import ai_pipeline, service

    wig_id = body.wig_id if body.mode == "tryon" else None
    wig = db.get(ExpoWig, wig_id) if wig_id else None
    if wig_id and wig is None:
        raise PromptError("预览发型不存在，请重新选择")
    if wig is None:
        wig = SimpleNamespace(id=0, name="示例发型", wig_description="示例发型描述",
                              composite_prompt="", angle_photos=[], cover_path=None)
    scene_key = body.scene_key
    if body.mode == "scene" and not scene_key:
        scene_key = SCENES[0]["key"]
    row = SimpleNamespace(wig_id=wig.id if body.mode == "tryon" else None,
                          scene_json={"key": scene_key} if scene_key else None,
                          hair_color_json=service.snapshot_hair_color(db, body.hair_color_id) if body.mode == "tryon" and body.hair_color_id else None)
    if body.mode == "tryon" and body.wig_id and body.hair_color_id:
        # Use the same wig/color reference selection as a real generation.
        row = ai_pipeline.build_composite_rows(0, [wig.id], hair_color=row.hair_color_json,
            scene={"key": scene_key, "label": scene_key} if scene_key else None, db=db)[0]
    # Preview has no customer identity or image upload and never calls an AI provider.
    session = SimpleNamespace(photo_path="uploads/expo/photos/preview.jpg")
    text, images, size = render_prompt(session, row, wig, body.config.model_dump(), ai_pipeline.to_abs)
    return {"prompt": text, "image_count": len(images), "size": size}
