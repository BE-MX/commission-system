"""素材管理 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class TagDimension(Base):
    """标签维度表"""

    __tablename__ = "ark_tag_dimensions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, comment="维度标识(英文)")
    label = Column(String(64), nullable=False, comment="维度显示名(中文)")
    is_single_select = Column(SmallInteger, nullable=False, default=0, comment="0=多选,1=单选")
    is_system = Column(SmallInteger, nullable=False, default=0, comment="0=自定义,1=系统内置")
    is_required = Column(SmallInteger, nullable=False, default=0, comment="0=选填,1=必填")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    values = relationship("TagValue", back_populates="dimension", lazy="selectin")

    __table_args__ = (
        Index("idx_tag_dim_name", "name", unique=True),
        Index("idx_tag_dim_sort", "sort_order"),
    )


class TagValue(Base):
    """标签值表"""

    __tablename__ = "ark_tag_values"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dimension_id = Column(Integer, ForeignKey("ark_tag_dimensions.id"), nullable=False)
    value = Column(String(128), nullable=False, comment="标签值")
    color_hex = Column(String(32), nullable=True, comment="颜色值,支持hex或rgb格式")
    image_path = Column(String(512), nullable=True, comment="标签图片路径")
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(SmallInteger, nullable=False, default=1, comment="0=禁用,1=启用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    dimension = relationship("TagDimension", back_populates="values")

    __table_args__ = (
        Index("idx_tag_val_dim", "dimension_id", "sort_order"),
        Index("idx_tag_val_value", "dimension_id", "value", unique=True),
    )


# 素材-标签关联表
asset_tag_association = Table(
    "ark_asset_tags",
    Base.metadata,
    Column("asset_id", Integer, ForeignKey("ark_assets.id"), primary_key=True),
    Column("version_id", Integer, ForeignKey("ark_asset_versions.id"), nullable=True),
    Column("dimension_id", Integer, ForeignKey("ark_tag_dimensions.id"), nullable=False),
    Column("tag_value_id", Integer, ForeignKey("ark_tag_values.id"), nullable=False),
    Index("idx_asset_tag_asset", "asset_id"),
    Index("idx_asset_tag_dim", "dimension_id", "tag_value_id"),
)


class Asset(Base):
    """素材主表"""

    __tablename__ = "ark_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=False, comment="原始文件名")
    file_type = Column(String(32), nullable=False, comment="image/video/document")
    file_format = Column(String(32), nullable=False, comment="jpg/png/mp4/pdf等")
    storage_path = Column(String(512), nullable=False, comment="服务器存储路径")
    file_size = Column(BigInteger, nullable=False, default=0, comment="文件大小(字节)")
    thumbnail_path = Column(String(512), nullable=True, comment="缩略图路径")
    uploader_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    current_version_id = Column(Integer, ForeignKey("ark_asset_versions.id"), nullable=True)
    status = Column(String(32), nullable=False, default="latest", comment="latest/history/offline")
    download_count = Column(Integer, nullable=False, default=0)
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship("AssetVersion", back_populates="asset", lazy="selectin",
                           primaryjoin="Asset.id==AssetVersion.asset_id")
    permissions = relationship("AssetPermission", back_populates="asset", lazy="selectin",
                              uselist=False)
    tags = relationship("TagValue", secondary=asset_tag_association, lazy="selectin")

    __table_args__ = (
        Index("idx_asset_status", "status"),
        Index("idx_asset_type", "file_type"),
        Index("idx_asset_uploader", "uploader_id"),
        Index("idx_asset_created", "created_at"),
    )


class AssetVersion(Base):
    """素材版本历史表"""

    __tablename__ = "ark_asset_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("ark_assets.id"), nullable=False)
    version_number = Column(Integer, nullable=False, default=1)
    storage_path = Column(String(512), nullable=False)
    file_size = Column(BigInteger, nullable=False, default=0)
    uploader_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="versions", foreign_keys=[asset_id])

    __table_args__ = (
        Index("idx_asset_ver_asset", "asset_id", "version_number"),
    )


class AssetPermission(Base):
    """素材权限表"""

    __tablename__ = "ark_asset_permissions"

    asset_id = Column(Integer, ForeignKey("ark_assets.id"), primary_key=True)
    permission_group = Column(String(32), nullable=False, default="all",
                              comment="all/design_dept/sales/specific")
    allow_preview = Column(SmallInteger, nullable=False, default=1, comment="0=否,1=是")
    allow_download = Column(SmallInteger, nullable=False, default=1, comment="0=否,1=是")
    specified_user_ids = Column(JSON, nullable=True, comment="指定人员ID数组")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    asset = relationship("Asset", back_populates="permissions")


class FavoriteFolder(Base):
    """收藏夹表"""

    __tablename__ = "ark_favorite_folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    name = Column(String(128), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    share_token = Column(String(64), nullable=True)
    share_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    items = relationship("FavoriteItem", back_populates="folder", lazy="selectin")

    __table_args__ = (
        Index("idx_fav_folder_user", "user_id", "sort_order"),
    )


class FavoriteItem(Base):
    """收藏项表"""

    __tablename__ = "ark_favorite_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, ForeignKey("ark_favorite_folders.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("ark_assets.id"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    folder = relationship("FavoriteFolder", back_populates="items")

    __table_args__ = (
        Index("idx_fav_item_folder", "folder_id", "sort_order"),
        Index("idx_fav_item_asset", "asset_id"),
    )


class DownloadLog(Base):
    """下载日志表"""

    __tablename__ = "ark_download_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(Integer, ForeignKey("ark_assets.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    version_number = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_dl_log_asset", "asset_id"),
        Index("idx_dl_log_user", "user_id"),
        Index("idx_dl_log_created", "created_at"),
    )
