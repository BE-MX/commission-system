from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic_followup import template_service, visibility
from app.domestic_followup.template_schemas import TemplateUpdateIn

router = APIRouter()
_require_read = require_permission("domestic_followup:read")
_require_admin = require_permission("domestic_followup:admin")


@router.get("/templates")
def list_templates(db: Session = Depends(get_db), _user=Depends(_require_read)):
    return ok(template_service.list_active(db))


@router.get("/templates/{code}")
def template_detail(code: str, version: int | None = Query(None, ge=1),
                    db: Session = Depends(get_db), _user=Depends(_require_read)):
    try:
        return ok(template_service.serialize(template_service.get_template(db, code, version)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/admin/templates/{code}/versions")
def template_versions(code: str, db: Session = Depends(get_db), _user=Depends(_require_admin)):
    try:
        return ok(template_service.versions(db, code))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/admin/templates/{code}")
def save_template(code: str, payload: TemplateUpdateIn, db: Session = Depends(get_db), user=Depends(_require_admin)):
    try:
        row = template_service.save_new_version(db, code, payload, visibility.uid(user))
        db.commit()
        return ok(template_service.serialize(row), message=f"已保存为 v{row.version}")
    except template_service.TemplateConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="模板版本发生冲突，请刷新后重试") from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
