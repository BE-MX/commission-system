"""系统字典 — API 路由"""


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import get_current_user, require_permission
from app.core.response import ok as _ok
from app.system import service
from app.system.schemas import DictItem, DictItemCreate, DictItemUpdate
from app.system import navigation_service
from app.system.navigation_schemas import NavigationPrefs
from app.core.database import get_db as get_core_db

router = APIRouter()


# Personal preferences are available to every authenticated user, like auth/me.
# No page permission exists; ownership always comes from JWT sub, never payload.
@router.get("/navigation-preferences", summary="读取本人常用导航配置")
def get_navigation_preferences(
    db: Session = Depends(get_core_db),
    current_user: dict = Depends(get_current_user),
):
    return _ok(navigation_service.get_preferences(db, int(current_user["sub"])))


@router.put("/navigation-preferences", summary="保存本人常用导航与顺序")
def save_navigation_preferences(
    payload: NavigationPrefs,
    db: Session = Depends(get_core_db),
    current_user: dict = Depends(get_current_user),
):
    return _ok(navigation_service.save_preferences(db, int(current_user["sub"]), payload))


@router.get("/dict-types")
def list_dict_types(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """所有字典类型 + 各自条目数。任意登录用户可读 (前端下拉数据源)。"""
    return _ok(service.list_types(db))


@router.get("/dicts")
def list_dict_items(
    type: str = Query(..., min_length=1, description="字典类型"),
    only_active: bool = Query(False, description="只看启用项"),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """按字典类型获取条目列表。前端下拉默认 only_active=true。"""
    items = service.list_items(db, type, only_active=only_active)
    return _ok([DictItem.model_validate(it).model_dump(mode="json") for it in items])


@router.post("/dicts")
def create_dict_item(
    data: DictItemCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("dict:write")),
):
    try:
        item = service.create_item(db, data)
    except service.ProtectedDictTypeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _ok(DictItem.model_validate(item).model_dump(mode="json"), "创建成功")


@router.put("/dicts/{item_id}")
def update_dict_item(
    item_id: int,
    data: DictItemUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("dict:write")),
):
    try:
        item = service.update_item(db, item_id, data)
    except service.ProtectedDictTypeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _ok(DictItem.model_validate(item).model_dump(mode="json"), "更新成功")


@router.delete("/dicts/{item_id}")
def delete_dict_item(
    item_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("dict:write")),
):
    try:
        service.delete_item(db, item_id)
    except service.ProtectedDictTypeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _ok(None, "删除成功")
