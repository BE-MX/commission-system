"""系统字典 — API 路由"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.system import service
from app.system.schemas import DictItem, DictItemCreate, DictItemUpdate

router = APIRouter()


def _ok(data, message: str = "ok"):
    return {"code": 200, "message": message, "data": data}


@router.get("/dict-types")
def list_dict_types(db: Session = Depends(get_db)):
    """所有字典类型 + 各自条目数。"""
    return _ok(service.list_types(db))


@router.get("/dicts")
def list_dict_items(
    type: str = Query(..., min_length=1, description="字典类型"),
    only_active: bool = Query(False, description="只看启用项"),
    db: Session = Depends(get_db),
):
    """按字典类型获取条目列表。前端下拉默认 only_active=true。"""
    items = service.list_items(db, type, only_active=only_active)
    return _ok([DictItem.model_validate(it).model_dump(mode="json") for it in items])


@router.post("/dicts")
def create_dict_item(
    data: DictItemCreate,
    db: Session = Depends(get_db),
):
    item = service.create_item(db, data)
    return _ok(DictItem.model_validate(item).model_dump(mode="json"), "创建成功")


@router.put("/dicts/{item_id}")
def update_dict_item(
    item_id: int,
    data: DictItemUpdate,
    db: Session = Depends(get_db),
):
    item = service.update_item(db, item_id, data)
    return _ok(DictItem.model_validate(item).model_dump(mode="json"), "更新成功")


@router.delete("/dicts/{item_id}")
def delete_dict_item(
    item_id: int,
    db: Session = Depends(get_db),
):
    service.delete_item(db, item_id)
    return _ok(None, "删除成功")
