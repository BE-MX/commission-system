"""add api_type to ark_ai_providers

Revision ID: 033
Revises: 032
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_ai_providers",
        sa.Column(
            "api_type",
            sa.Enum("openai", "anthropic", name="ai_api_type"),
            nullable=False,
            server_default="openai",
            comment="API 协议类型: openai=Chat Completions, anthropic=Messages",
        ),
    )


def downgrade() -> None:
    op.drop_column("ark_ai_providers", "api_type")
    op.execute("DROP TYPE IF EXISTS ai_api_type")
