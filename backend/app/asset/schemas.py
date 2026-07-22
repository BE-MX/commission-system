"""素材管理 — Pydantic 模型"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── 标签维度 ────────────────────────────────────────────

class TagDimensionOut(BaseModel):
    id: int
    name: str
    label: str
    is_single_select: int
    is_system: int
    is_required: int
    sort_order: int

    class Config:
        from_attributes = True


class TagValueOut(BaseModel):
    id: int
    dimension_id: int
    value: str
    color_hex: Optional[str] = None
    sort_order: int
    is_active: int

    class Config:
        from_attributes = True


class TagDimensionWithValues(TagDimensionOut):
    values: list[TagValueOut] = []


class TagValueCreate(BaseModel):
    value: str = Field(..., max_length=128)
    color_hex: Optional[str] = Field(None, max_length=32)
    image_path: Optional[str] = Field(None, max_length=512)
    sort_order: int = 0
    name_en: Optional[str] = Field(None, max_length=128)
    aliases: Optional[list[str]] = None
    parent_value_id: Optional[int] = None


class TagDimensionCreate(BaseModel):
    name: str = Field(..., max_length=64)
    label: str = Field(..., max_length=64)
    is_single_select: int = Field(default=0, ge=0, le=1)
    is_required: int = Field(default=0, ge=0, le=1)
    sort_order: int = Field(default=0)


class TagDimensionUpdate(BaseModel):
    label: Optional[str] = Field(None, max_length=64)
    is_single_select: Optional[int] = Field(None, ge=0, le=1)
    is_required: Optional[int] = Field(None, ge=0, le=1)
    sort_order: Optional[int] = None
    is_visible: Optional[int] = Field(None, ge=0, le=1)


# ── 素材 ────────────────────────────────────────────────

class AssetTagItem(BaseModel):
    dimension_id: int
    tag_value_ids: list[int]


class AssetPermissionIn(BaseModel):
    permission_group: str = Field(default="all", pattern="^(all|design_dept|sales|specific)$")
    allow_preview: int = Field(default=1, ge=0, le=1)
    allow_download: int = Field(default=1, ge=0, le=1)
    specified_user_ids: Optional[list[int]] = None


class AssetCreate(BaseModel):
    file_name: str = Field(..., max_length=255)
    file_type: str = Field(..., pattern="^(image|video|document)$")
    file_format: str = Field(..., max_length=32)
    file_size: int = Field(default=0, ge=0)
    remark: Optional[str] = None
    tags: list[AssetTagItem] = []
    permission: AssetPermissionIn = AssetPermissionIn()


class AssetUpdateTags(BaseModel):
    tags: list[AssetTagItem] = []


class AssetUpdateStatus(BaseModel):
    status: str = Field(..., pattern="^(latest|history|offline)$")


class AssetVersionOut(BaseModel):
    id: int
    version_number: int
    file_size: int
    uploader_id: int
    remark: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AssetPermissionOut(BaseModel):
    permission_group: str
    allow_preview: int
    allow_download: int
    specified_user_ids: Optional[list[int]] = None

    class Config:
        from_attributes = True


class AssetOut(BaseModel):
    id: int
    file_name: str
    file_type: str
    file_format: str
    file_size: int
    thumbnail_path: Optional[str] = None
    uploader_id: int
    status: str
    download_count: int
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tags: list[TagValueOut] = []
    permissions: Optional[AssetPermissionOut] = None
    versions: list[AssetVersionOut] = []

    class Config:
        from_attributes = True


class AssetListItem(BaseModel):
    id: int
    file_name: str
    file_type: str
    file_format: str
    file_size: int
    thumbnail_path: Optional[str] = None
    uploader_id: int
    status: str
    download_count: int
    created_at: datetime
    tags: list[TagValueOut] = []

    class Config:
        from_attributes = True


# ── 批量操作 ────────────────────────────────────────────

class BatchDownloadRequest(BaseModel):
    asset_ids: list[int] = Field(..., min_length=1, max_length=100)


# ── 列表查询 ────────────────────────────────────────────

class AssetListRequest(BaseModel):
    file_type: Optional[str] = None
    tag_filters: Optional[dict[str, list[int]]] = None
    keyword: Optional[str] = None
    status: Optional[str] = None
    sort_by: str = Field(default="created_at", pattern="^(created_at|file_name|download_count)$")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=24, ge=1, le=100)


class AssetListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    available_tag_ids: list[int] = []
    items: list[AssetListItem]


# ── 收藏 ────────────────────────────────────────────────

class FavoriteFolderCreate(BaseModel):
    name: str = Field(..., max_length=128)


class FavoriteFolderUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    sort_order: Optional[int] = None


class FavoriteItemCreate(BaseModel):
    asset_id: int


class FavoriteFolderOut(BaseModel):
    id: int
    user_id: int
    name: str
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class FavoriteItemOut(BaseModel):
    id: int
    folder_id: int
    asset_id: int
    sort_order: int
    created_at: datetime
    asset: Optional[AssetListItem] = None

    class Config:
        from_attributes = True


class FavoriteFolderWithItems(FavoriteFolderOut):
    items: list[FavoriteItemOut] = []


# ── 文件夹上传 ──────────────────────────────────────────

class TagMappingItem(BaseModel):
    dimension_id: int
    tag_value_id: int
    dimension_name: Optional[str] = None
    original_value: Optional[str] = None


class FolderUploadValidateRequest(BaseModel):
    folder_path: str = Field(..., min_length=1)


class FolderUploadPreviewRequest(BaseModel):
    folder_path: str = Field(..., min_length=1)
    tag_mapping: dict[str, TagMappingItem] = {}


class FolderUploadExecuteRequest(BaseModel):
    folder_path: str = Field(..., min_length=1)
    tag_mapping: dict[str, TagMappingItem] = {}
    permission: AssetPermissionIn = AssetPermissionIn()
    extra_tags: list[AssetTagItem] = []
    update_duplicates: bool = Field(
        True,
        description="同名同标签文件是否更新为新版本; False 时直接跳过",
    )


# ── 移动端 ──────────────────────────────────────────────

class AssetActionRequest(BaseModel):
    action: str = Field(..., pattern="^(view|download|copy_link)$")


class AssetShareLinkOut(BaseModel):
    url: str
    expires_at: Optional[datetime] = None
