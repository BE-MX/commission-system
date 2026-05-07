"""add props_requirement and preferred_designer_id to design_schedule_request

Revision ID: 008_add_props_designer
Revises: 007_add_attachment
Create Date: 2026-05-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008_add_props_designer"
down_revision: Union[str, None] = "007_add_attachment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("design_schedule_request",
        sa.Column("props_requirement", sa.String(512), nullable=True, comment="道具要求(字典code，多选用逗号分隔)"),
    )
    op.add_column("design_schedule_request",
        sa.Column("preferred_designer_id", sa.Integer, nullable=True, comment="期望设计师ID(NULL=随机分配)"),
    )


def downgrade() -> None:
    op.drop_column("design_schedule_request", "preferred_designer_id")
    op.drop_column("design_schedule_request", "props_requirement")
