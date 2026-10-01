"""任务中心 HTTP 薄适配层。

权限：task:read（查看）/ task:write（建、改、删、AI 草稿）。数据按 JWT sub 隔离，
跨 owner 访问一律 404。统一信封 ok()；领域异常转 HTTPException，409 带 code 供前端分支处理。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.task import ai_service, brief_service, module_service, service
from app.task.errors import TaskError
from app.task.schemas import (
    CustomModuleCreate, DraftRequest, LinkCreate, MoveInput, StatusChange, TaskCreate, TaskUpdate,
)

router = APIRouter()
READ = ("task:read", "task:write")
WRITE = ("task:write",)


def _owner(user: dict) -> int:
    return int(user["sub"])


def _call(db: Session, fn, *args, commit: bool = False, **kwargs):
    try:
        result = fn(db, *args, **kwargs)
        if commit:
            db.commit()
        return result
    except TaskError as exc:
        db.rollback()
        detail = {"message": str(exc), "code": exc.code, **exc.extra} if exc.code else str(exc)
        raise HTTPException(exc.status_code, detail) from exc


@router.get("/items", summary="任务树")
def list_items(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(service.list_tree(db, _owner(user)))


@router.post("/items", summary="新建任务")
def create_item(payload: TaskCreate, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.create_task, _owner(user), commit=True, **payload.model_dump())
    return ok(service.serialize_task(task))


@router.get("/items/{task_id}", summary="任务详情")
def get_item(task_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(db, service.task_detail, _owner(user), task_id))


@router.patch("/items/{task_id}", summary="修改任务字段")
def update_item(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db),
                user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.update_task, _owner(user), task_id, payload.model_dump(exclude_unset=True), commit=True)
    return ok(service.serialize_task(task))


@router.post("/items/{task_id}/status", summary="变更状态")
def change_status(task_id: int, payload: StatusChange, db: Session = Depends(get_db),
                  user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.change_status, _owner(user), task_id, payload.status, reason=payload.reason,
                 confirm_open_children=payload.confirm_open_children, commit=True)
    return ok(service.serialize_task(task))


@router.post("/items/{task_id}/move", summary="调整父任务")
def move_item(task_id: int, payload: MoveInput, db: Session = Depends(get_db),
              user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.move_task, _owner(user), task_id, payload.parent_id, commit=True)
    return ok(service.serialize_task(task))


@router.delete("/items/{task_id}", summary="删除任务（连同子任务进回收站）")
def delete_item(task_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    _call(db, service.delete_task, _owner(user), task_id, commit=True)
    return ok({"deleted": True})


@router.post("/items/{task_id}/restore", summary="从回收站恢复")
def restore_item(task_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.restore_task, _owner(user), task_id, commit=True)
    return ok(service.serialize_task(task))


@router.get("/trash", summary="回收站")
def trash(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(service.list_trash(db, _owner(user)))


@router.post("/items/{task_id}/links", summary="挂文档/原型/链接")
def add_link(task_id: int, payload: LinkCreate, db: Session = Depends(get_db),
             user: dict = Depends(require_any_permission(*WRITE))):
    link = _call(db, service.add_link, _owner(user), task_id, commit=True, **payload.model_dump())
    return ok(service.serialize_link(link))


@router.delete("/links/{link_id}", summary="移除关联")
def remove_link(link_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    _call(db, service.remove_link, _owner(user), link_id, commit=True)
    return ok({"deleted": True})


@router.get("/stats", summary="页头统计")
def stats(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(service.stats(db, _owner(user)))


@router.get("/modules", summary="模块注册表（含本人私有分类）")
def modules(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(module_service.list_modules(db, _owner(user)))


@router.post("/modules/custom", summary="新建私有分类")
def add_custom_module(payload: CustomModuleCreate, db: Session = Depends(get_db),
                      user: dict = Depends(require_any_permission(*WRITE))):
    key = _call(db, module_service.add_custom, _owner(user), payload.title, commit=True)
    return ok({"key": key})


@router.delete("/modules/custom/{key}", summary="停用私有分类")
def remove_custom_module(key: str, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    _call(db, module_service.deactivate_custom, _owner(user), key, commit=True)
    return ok({"deactivated": True})


@router.post("/ai/draft", summary="一句话生成任务草稿（不写库）")
def ai_draft(payload: DraftRequest, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    return ok(_call(db, ai_service.draft_task, _owner(user), payload.text,
                    module_key=payload.module_key, parent_id=payload.parent_id))


@router.get("/brief/today", summary="今日简报（没有则即时生成，不推送）")
def brief_today(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    row = _call(db, brief_service.get_or_create_brief, _owner(user), commit=True)
    return ok(brief_service.serialize_brief(row))
