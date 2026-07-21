"""training: file_type + remark on digest files

上传附件时可选类型（下拉白名单，存 code）与备注。
两列均可空：老代码+新 schema 过渡期兼容，存量行前端显示"未分类"。

Revision ID: 077_training_file_meta
Revises: 076_pm_hub
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa


revision = "077_training_file_meta"
down_revision = "076_pm_hub"
branch_labels = None
depends_on = None

TABLE = "ark_training_digest_files"


def _existing_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade():
    # MySQL DDL 自动提交不可回滚，逐列幂等检查防半执行状态
    existing = _existing_columns()
    if "file_type" not in existing:
        op.add_column(
            TABLE,
            sa.Column("file_type", sa.String(32), nullable=True,
                      comment="附件类型 code：courseware=课件讲义 photo=现场照片 recording=录音录像 notes=笔记文档 other=其他；NULL=未分类（077 之前的存量）"),
        )
    if "remark" not in existing:
        op.add_column(
            TABLE,
            sa.Column("remark", sa.String(200), nullable=True, comment="附件备注（上传人填写）"),
        )


def downgrade():
    existing = _existing_columns()
    if "remark" in existing:
        op.drop_column(TABLE, "remark")
    if "file_type" in existing:
        op.drop_column(TABLE, "file_type")
