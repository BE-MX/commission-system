"""customer media playback and poster keys

Revision ID: 198_customer_media_playback
Revises: 197_battle_awards
Create Date: 2026-10-19

原件继续保存在 object_key；新增 H.264 播放版与首帧海报的对象键，供浏览器直接播放。
MySQL DDL 不可回滚，upgrade 使用存在性判断，便于中断后继续执行。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "198_customer_media_playback"
down_revision = "197_battle_awards"
branch_labels = None
depends_on = None


OBJECT_KEY = sa.String(length=768).with_variant(
    mysql.VARCHAR(length=768, charset="ascii", collation="ascii_bin"),
    "mysql",
)


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    if not _has_column("ark_customer_media_assets", "playback_key"):
        op.add_column("ark_customer_media_assets", sa.Column(
            "playback_key", OBJECT_KEY, nullable=True,
            comment="H.264 浏览器播放版对象键；原件保留",
        ))
    if not _has_column("ark_customer_media_assets", "playback_size"):
        op.add_column("ark_customer_media_assets", sa.Column(
            "playback_size", sa.BigInteger(), nullable=True,
            comment="播放版字节数",
        ))
    # thumbnail_key 由“预留”改为实际海报键只是语义变化，不为列注释重建大表。


def downgrade() -> None:
    if _has_column("ark_customer_media_assets", "playback_size"):
        op.drop_column("ark_customer_media_assets", "playback_size")
    if _has_column("ark_customer_media_assets", "playback_key"):
        op.drop_column("ark_customer_media_assets", "playback_key")
