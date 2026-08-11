"""Add required knowledge library category.

Revision ID: 105_knowledge_category
Revises: 104_ci_generation_snapshots
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "105_knowledge_category"
down_revision = "104_ci_generation_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_knowledge_libraries",
        sa.Column(
            "category",
            sa.String(length=16),
            nullable=True,
            comment="company/department/personal",
        ),
    )
    op.execute(sa.text(
        "UPDATE ark_knowledge_libraries "
        "SET category = 'company' "
        "WHERE category IS NULL"
    ))
    with op.batch_alter_table("ark_knowledge_libraries") as batch_op:
        batch_op.alter_column(
            "category",
            existing_type=sa.String(length=16),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ark_knowledge_libraries") as batch_op:
        batch_op.drop_column("category")

