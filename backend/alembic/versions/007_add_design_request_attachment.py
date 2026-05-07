"""add design_request_attachment table

Revision ID: 007_add_attachment
Revises: 006_add_sys_dict
Create Date: 2026-05-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007_add_attachment"
down_revision: Union[str, None] = "006_add_sys_dict"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "design_request_attachment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer, sa.ForeignKey("design_schedule_request.id"), nullable=False, comment="关联申请ID"),
        sa.Column("file_name", sa.String(256), nullable=False, comment="原始文件名"),
        sa.Column("file_path", sa.String(512), nullable=False, comment="存储路径"),
        sa.Column("file_size", sa.Integer, nullable=False, server_default="0", comment="文件大小(字节)"),
        sa.Column("content_type", sa.String(128), nullable=True, comment="MIME类型"),
        sa.Column("uploaded_by", sa.Integer, nullable=True, comment="上传人ID"),
        sa.Column("uploaded_by_name", sa.String(64), nullable=True, comment="上传人姓名"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now(), comment="创建时间"),
    )
    op.create_index("idx_attachment_request_id", "design_request_attachment", ["request_id"])


def downgrade() -> None:
    op.drop_index("idx_attachment_request_id", table_name="design_request_attachment")
    op.drop_table("design_request_attachment")
