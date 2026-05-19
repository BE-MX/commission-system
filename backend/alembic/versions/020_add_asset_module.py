"""add asset module

Revision ID: 020_add_asset_module
Revises: 019_add_stock_module
Create Date: 2026-05-19 21:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '020_add_asset_module'
down_revision: Union[str, None] = '019_add_stock_module'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# MySQL 兼容: 所有自增主键和外键引用列统一用 unsigned int，避免 3780 外键不匹配错误
_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql')


def upgrade() -> None:
    # ── 标签维度 ─────────────────────────────────────────
    op.create_table(
        'ark_tag_dimensions',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('name', sa.String(64), nullable=False, comment='维度标识(英文)'),
        sa.Column('label', sa.String(64), nullable=False, comment='维度显示名(中文)'),
        sa.Column('is_single_select', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='0=多选,1=单选'),
        sa.Column('is_system', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='0=自定义,1=系统内置'),
        sa.Column('is_required', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='0=选填,1=必填'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_tag_dim_name', 'ark_tag_dimensions', ['name'], unique=True)
    op.create_index('idx_tag_dim_sort', 'ark_tag_dimensions', ['sort_order'], unique=False)

    # ── 标签值 ───────────────────────────────────────────
    op.create_table(
        'ark_tag_values',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('dimension_id', _UINT, sa.ForeignKey('ark_tag_dimensions.id'), nullable=False),
        sa.Column('value', sa.String(128), nullable=False, comment='标签值'),
        sa.Column('color_hex', sa.String(7), nullable=True, comment='颜色十六进制'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('is_active', sa.SmallInteger(), nullable=False, server_default=sa.text("'1'"), comment='0=禁用,1=启用'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_tag_val_dim', 'ark_tag_values', ['dimension_id', 'sort_order'], unique=False)
    op.create_index('idx_tag_val_value', 'ark_tag_values', ['dimension_id', 'value'], unique=True)

    # ── 素材主表 ─────────────────────────────────────────
    op.create_table(
        'ark_assets',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False, comment='原始文件名'),
        sa.Column('file_type', sa.String(32), nullable=False, comment='image/video/document'),
        sa.Column('file_format', sa.String(32), nullable=False, comment='jpg/png/mp4/pdf等'),
        sa.Column('storage_path', sa.String(512), nullable=False, comment='服务器存储路径'),
        sa.Column('file_size', sa.BigInteger(), nullable=False, server_default=sa.text("'0'"), comment='文件大小(字节)'),
        sa.Column('thumbnail_path', sa.String(512), nullable=True, comment='缩略图路径'),
        sa.Column('uploader_id', _UINT, sa.ForeignKey('ark_users.id'), nullable=False),
        sa.Column('current_version_id', _UINT, nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default=sa.text("'latest'"), comment='latest/history/offline'),
        sa.Column('download_count', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_asset_status', 'ark_assets', ['status'], unique=False)
    op.create_index('idx_asset_type', 'ark_assets', ['file_type'], unique=False)
    op.create_index('idx_asset_uploader', 'ark_assets', ['uploader_id'], unique=False)
    op.create_index('idx_asset_created', 'ark_assets', ['created_at'], unique=False)

    # ── 版本历史 ─────────────────────────────────────────
    op.create_table(
        'ark_asset_versions',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('asset_id', _UINT, sa.ForeignKey('ark_assets.id'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.String(512), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('uploader_id', _UINT, sa.ForeignKey('ark_users.id'), nullable=False),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_asset_ver_asset', 'ark_asset_versions', ['asset_id', 'version_number'], unique=False)

    # 素材表补充外键（版本表创建后才能加）
    op.create_foreign_key('fk_asset_current_version', 'ark_assets', 'ark_asset_versions',
                          ['current_version_id'], ['id'])

    # ── 标签关联 ─────────────────────────────────────────
    op.create_table(
        'ark_asset_tags',
        sa.Column('asset_id', _UINT, sa.ForeignKey('ark_assets.id'), primary_key=True),
        sa.Column('version_id', _UINT, sa.ForeignKey('ark_asset_versions.id'), nullable=True),
        sa.Column('dimension_id', _UINT, sa.ForeignKey('ark_tag_dimensions.id'), nullable=False),
        sa.Column('tag_value_id', _UINT, sa.ForeignKey('ark_tag_values.id'), nullable=False),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_asset_tag_asset', 'ark_asset_tags', ['asset_id'], unique=False)
    op.create_index('idx_asset_tag_dim', 'ark_asset_tags', ['dimension_id', 'tag_value_id'], unique=False)

    # ── 权限 ─────────────────────────────────────────────
    op.create_table(
        'ark_asset_permissions',
        sa.Column('asset_id', _UINT, sa.ForeignKey('ark_assets.id'), primary_key=True),
        sa.Column('permission_group', sa.String(32), nullable=False, server_default=sa.text("'all'"), comment='all/design_dept/sales/specific'),
        sa.Column('allow_preview', sa.SmallInteger(), nullable=False, server_default=sa.text("'1'"), comment='0=否,1=是'),
        sa.Column('allow_download', sa.SmallInteger(), nullable=False, server_default=sa.text("'1'"), comment='0=否,1=是'),
        sa.Column('specified_user_ids', sa.JSON(), nullable=True, comment='指定人员ID数组'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )

    # ── 收藏夹 ───────────────────────────────────────────
    op.create_table(
        'ark_favorite_folders',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('user_id', _UINT, sa.ForeignKey('ark_users.id'), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('share_token', sa.String(64), nullable=True),
        sa.Column('share_expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_fav_folder_user', 'ark_favorite_folders', ['user_id', 'sort_order'], unique=False)

    # ── 收藏项 ───────────────────────────────────────────
    op.create_table(
        'ark_favorite_items',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('folder_id', _UINT, sa.ForeignKey('ark_favorite_folders.id'), nullable=False),
        sa.Column('asset_id', _UINT, sa.ForeignKey('ark_assets.id'), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_fav_item_folder', 'ark_favorite_items', ['folder_id', 'sort_order'], unique=False)
    op.create_index('idx_fav_item_asset', 'ark_favorite_items', ['asset_id'], unique=False)

    # ── 下载日志 ─────────────────────────────────────────
    op.create_table(
        'ark_download_logs',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('asset_id', _UINT, sa.ForeignKey('ark_assets.id'), nullable=False),
        sa.Column('user_id', _UINT, sa.ForeignKey('ark_users.id'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_dl_log_asset', 'ark_download_logs', ['asset_id'], unique=False)
    op.create_index('idx_dl_log_user', 'ark_download_logs', ['user_id'], unique=False)
    op.create_index('idx_dl_log_created', 'ark_download_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('ark_download_logs')
    op.drop_table('ark_favorite_items')
    op.drop_table('ark_favorite_folders')
    op.drop_table('ark_asset_permissions')
    op.drop_table('ark_asset_tags')
    op.drop_table('ark_asset_versions')
    op.drop_table('ark_assets')
    op.drop_table('ark_tag_values')
    op.drop_table('ark_tag_dimensions')
