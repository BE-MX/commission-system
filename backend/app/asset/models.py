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

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(64), nullable=False, comment="维度标识(英文)")
    label = Column(String(64), nullable=False, comment="维度显示名(中文)")
    is_single_select = Column(SmallInteger, nullable=False, default=0, comment="0=多选,1=单选")
    is_system = Column(SmallInteger, nullable=False, default=0, comment="0=自定义,1=系统内置")
    is_required = Column(SmallInteger, nullable=False, default=0, comment="0=选填,1=必填")
    is_visible = Column(SmallInteger, nullable=False, default=1, comment="0=隐藏(前端/folder_upload匹配均不参与),1=可见")
    is_managed = Column(SmallInteger, nullable=False, default=0, comment="1=系统托管,值由派生脚本写入,禁人工编辑")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序权重")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    values = relationship("TagValue", back_populates="dimension", lazy="selectin")

    __table_args__ = (
        Index("idx_tag_dim_name", "name", unique=True),
        Index("idx_tag_dim_sort", "sort_order"),
        {"comment": "标签维度表"},
    )


class TagValue(Base):
    """标签值表"""

    __tablename__ = "ark_tag_values"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    dimension_id = Column(Integer, ForeignKey("ark_tag_dimensions.id"), nullable=False, comment="所属标签维度ID")
    value = Column(String(128), nullable=False, comment="标签值")
    name_en = Column(String(128), nullable=True, comment="英文名(agent 检索用)")
    aliases = Column(JSON, nullable=True, comment="别名数组(中英混合,agent 模糊匹配用)")
    parent_value_id = Column(Integer, ForeignKey("ark_tag_values.id"), nullable=True,
                             comment="父级标签值ID(内容子类→内容大类挂靠)")
    color_hex = Column(String(32), nullable=True, comment="颜色值,支持hex或rgb格式")
    image_path = Column(String(512), nullable=True, comment="标签图片路径")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序权重")
    is_active = Column(SmallInteger, nullable=False, default=1, comment="0=禁用,1=启用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    dimension = relationship("TagDimension", back_populates="values", lazy="joined")

    __table_args__ = (
        Index("idx_tag_val_dim", "dimension_id", "sort_order"),
        Index("idx_tag_val_value", "dimension_id", "value", unique=True),
        {"comment": "标签值表"},
    )


# 素材-标签关联表
asset_tag_association = Table(
    "ark_asset_tags",
    Base.metadata,
    Column("asset_id", Integer, ForeignKey("ark_assets.id"), primary_key=True, comment="素材ID"),
    Column("version_id", Integer, ForeignKey("ark_asset_versions.id"), nullable=True, comment="打标时对应的素材版本ID(可空)"),
    Column("dimension_id", Integer, ForeignKey("ark_tag_dimensions.id"), primary_key=True, comment="标签维度ID"),
    Column("tag_value_id", Integer, ForeignKey("ark_tag_values.id"), primary_key=True, comment="标签值ID"),
    Index("idx_asset_tag_asset", "asset_id"),
    Index("idx_asset_tag_dim", "dimension_id", "tag_value_id"),
    comment="素材-标签关联表（复合主键 asset_id+dimension_id+tag_value_id）",
)


class Asset(Base):
    """素材主表"""

    __tablename__ = "ark_assets"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    file_name = Column(String(255), nullable=False, comment="原始文件名")
    file_type = Column(String(32), nullable=False, comment="image/video/document")
    file_format = Column(String(32), nullable=False, comment="jpg/png/mp4/pdf等")
    storage_path = Column(String(512), nullable=False, comment="服务器存储路径")
    file_size = Column(BigInteger, nullable=False, default=0, comment="文件大小(字节)")
    thumbnail_path = Column(String(512), nullable=True, comment="缩略图路径")
    orientation = Column(String(16), nullable=True, comment="画幅 landscape/portrait/square,自动计算")
    uploader_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="上传人用户ID")
    current_version_id = Column(Integer, ForeignKey("ark_asset_versions.id"), nullable=True, comment="当前生效版本ID")
    status = Column(String(32), nullable=False, default="latest", comment="latest/history/offline")
    download_count = Column(Integer, nullable=False, default=0, comment="累计下载次数")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    versions = relationship("AssetVersion", back_populates="asset", lazy="noload",
                           primaryjoin="Asset.id==AssetVersion.asset_id")
    permissions = relationship("AssetPermission", back_populates="asset", lazy="noload",
                              uselist=False)
    tags = relationship("TagValue", secondary=asset_tag_association, lazy="noload")

    __table_args__ = (
        Index("idx_asset_status", "status"),
        Index("idx_asset_type", "file_type"),
        Index("idx_asset_uploader", "uploader_id"),
        Index("idx_asset_created", "created_at"),
        {"comment": "素材主表"},
    )


class AssetVersion(Base):
    """素材版本历史表"""

    __tablename__ = "ark_asset_versions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    asset_id = Column(Integer, ForeignKey("ark_assets.id"), nullable=False, comment="所属素材ID")
    version_number = Column(Integer, nullable=False, default=1, comment="版本号,从1递增")
    storage_path = Column(String(512), nullable=False, comment="该版本文件存储路径")
    file_size = Column(BigInteger, nullable=False, default=0, comment="文件大小(字节)")
    uploader_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="上传人用户ID")
    remark = Column(Text, nullable=True, comment="版本备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    asset = relationship("Asset", back_populates="versions", foreign_keys=[asset_id])

    __table_args__ = (
        Index("idx_asset_ver_asset", "asset_id", "version_number"),
        {"comment": "素材版本历史表"},
    )


class AssetPermission(Base):
    """素材权限表"""

    __tablename__ = "ark_asset_permissions"

    asset_id = Column(Integer, ForeignKey("ark_assets.id"), primary_key=True, comment="素材ID(主键)")
    permission_group = Column(String(32), nullable=False, default="all",
                              comment="all/design_dept/sales/specific")
    allow_preview = Column(SmallInteger, nullable=False, default=1, comment="0=否,1=是")
    allow_download = Column(SmallInteger, nullable=False, default=1, comment="0=否,1=是")
    specified_user_ids = Column(JSON, nullable=True, comment="指定人员ID数组")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    asset = relationship("Asset", back_populates="permissions")

    __table_args__ = {"comment": "素材权限表"}


class FavoriteFolder(Base):
    """收藏夹表"""

    __tablename__ = "ark_favorite_folders"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="所属用户ID")
    name = Column(String(128), nullable=False, comment="收藏夹名称")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序权重")
    share_token = Column(String(64), nullable=True, comment="分享令牌(NULL=未分享)")
    share_expires_at = Column(DateTime, nullable=True, comment="分享链接过期时间")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    items = relationship("FavoriteItem", back_populates="folder", lazy="selectin")

    __table_args__ = (
        Index("idx_fav_folder_user", "user_id", "sort_order"),
        {"comment": "收藏夹表"},
    )


class FavoriteItem(Base):
    """收藏项表"""

    __tablename__ = "ark_favorite_items"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    folder_id = Column(Integer, ForeignKey("ark_favorite_folders.id"), nullable=False, comment="所属收藏夹ID")
    asset_id = Column(Integer, ForeignKey("ark_assets.id"), nullable=False, comment="素材ID")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序权重")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    folder = relationship("FavoriteFolder", back_populates="items")

    __table_args__ = (
        Index("idx_fav_item_folder", "folder_id", "sort_order"),
        Index("idx_fav_item_asset", "asset_id"),
        {"comment": "收藏项表"},
    )


class DownloadLog(Base):
    """下载日志表"""

    __tablename__ = "ark_download_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    asset_id = Column(Integer, ForeignKey("ark_assets.id"), nullable=False, comment="素材ID")
    user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="下载人用户ID")
    version_number = Column(Integer, nullable=True, comment="下载的版本号")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="下载时间")

    __table_args__ = (
        Index("idx_dl_log_asset", "asset_id"),
        Index("idx_dl_log_user", "user_id"),
        Index("idx_dl_log_created", "created_at"),
        {"comment": "素材下载日志表"},
    )
