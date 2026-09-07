"""Prompt configuration is admin-only; kiosk receives version labels only."""
import logging
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.expo import prompt_service as service
from app.expo.common import user_id_from_current_user
from app.expo.models import ExpoResult
from app.expo.prompt_catalog import editor_metadata
from app.expo.prompt_schemas import PromptVersionCreate, PromptVersionUpdate, PromptRevisionRequest, PromptPreviewRequest

router = APIRouter()
logger = logging.getLogger("commission.expo")


@contextmanager
def prompt_transaction(db, *, write=False):
    try:
        yield
        if write:
            db.commit()
    except service.PromptError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "版本名称重复或配置已变化，请刷新后重试") from None
    except OperationalError as exc:
        db.rollback()
        error_code = getattr(exc.orig, "args", [None])[0]
        message = f"[expo] prompt database operation failed: {type(exc.orig).__name__}"
        logger.warning(message)
        print(message, flush=True)
        if error_code in (1205, 1213):
            raise HTTPException(409, "配置正在更新，请稍后重试") from None
        raise HTTPException(503, "提示词配置暂时不可用，请稍后重试") from None
    except SQLAlchemyError as exc:
        db.rollback()
        # Avoid logging SQL parameters containing complete prompts.
        message = f"[expo] prompt database error: {type(exc).__name__}"
        logger.error(message)
        print(message, flush=True)
        raise HTTPException(503, "提示词配置暂时不可用，请稍后重试") from None


@router.get("/prompt-versions/picker")
def picker(db: Session = Depends(get_db), _user=Depends(require_permission("expo:write"))):
    with prompt_transaction(db):
        return ok(service.picker_options(db))


@router.get("/prompt-versions/editor")
def editor(_user=Depends(require_permission("expo:admin"))):
    return ok(editor_metadata())


@router.post("/prompt-versions/preview")
def preview(body: PromptPreviewRequest, db: Session = Depends(get_db), _user=Depends(require_permission("expo:admin"))):
    with prompt_transaction(db):
        return ok(service.preview(db, body))


@router.get("/prompt-versions")
def list_versions(keyword: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  db: Session = Depends(get_db), _user=Depends(require_permission("expo:admin"))):
    with prompt_transaction(db):
        rows, total = service.list_versions(db, keyword=keyword, page=page, page_size=page_size)
        return ok(page_result([service.serialize_version(row) for row in rows], total, page, page_size))


@router.get("/prompt-versions/{version_id}")
def detail(version_id: int, db: Session = Depends(get_db), _user=Depends(require_permission("expo:admin"))):
    with prompt_transaction(db):
        return ok(service.serialize_version(service.get_version(db, version_id), detail=True))


@router.post("/prompt-versions")
def create(body: PromptVersionCreate, db: Session = Depends(get_db), user=Depends(require_permission("expo:admin"))):
    with prompt_transaction(db, write=True):
        result = service.serialize_version(service.create_version(db, body, user_id_from_current_user(user)), detail=True)
    return ok(result, code=201)


@router.put("/prompt-versions/{version_id}")
def update(version_id: int, body: PromptVersionUpdate, db: Session = Depends(get_db), user=Depends(require_permission("expo:admin"))):
    with prompt_transaction(db, write=True):
        result = service.serialize_version(service.update_version(db, version_id, body, user_id_from_current_user(user)), detail=True)
    return ok(result)


@router.post("/prompt-versions/{version_id}/default")
def default(version_id: int, body: PromptRevisionRequest, db: Session = Depends(get_db), user=Depends(require_permission("expo:admin"))):
    with prompt_transaction(db, write=True):
        result = service.serialize_version(service.set_default(db, version_id, body.expected_revision, user_id_from_current_user(user)))
    return ok(result)


@router.get("/results/{result_id}/prompt-snapshot")
def snapshot(result_id: int, db: Session = Depends(get_db), _user=Depends(require_permission("expo:admin"))):
    with prompt_transaction(db):
        row = db.get(ExpoResult, result_id)
        if row is None:
            raise HTTPException(404, "效果图不存在")
        return ok(row.prompt_snapshot)
