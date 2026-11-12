"""Private-sea board: AI tags, manual tag removals, structured profile, agent trace."""
from alembic import op
import sqlalchemy as sa

revision = "260_client_desk_board"
down_revision = "259_outbound_link_proof"
branch_labels = None
depends_on = None


def upgrade():
    # Columns only: the private-sea contract keeps exactly four domain tables.
    op.add_column(
        "ark_client_desk_states",
        sa.Column("ai_tags", sa.JSON(), nullable=True, comment="AI与风险标签（自动生效）"),
    )
    op.add_column(
        "ark_client_desk_states",
        sa.Column("tag_overrides", sa.JSON(), nullable=True, comment="人工移除的标签编码"),
    )
    op.add_column(
        "ark_client_desk_states",
        sa.Column("profile_json", sa.JSON(), nullable=True, comment="结构化客户画像"),
    )
    op.add_column(
        "ark_client_desk_states",
        sa.Column("profile_dependencies", sa.JSON(), nullable=True, comment="画像与标签授权依赖"),
    )
    op.add_column(
        "ark_client_desk_suggestions",
        sa.Column("agent_trace", sa.JSON(), nullable=True, comment="Agent只读工具步骤"),
    )


def downgrade():
    op.drop_column("ark_client_desk_suggestions", "agent_trace")
    op.drop_column("ark_client_desk_states", "profile_dependencies")
    op.drop_column("ark_client_desk_states", "profile_json")
    op.drop_column("ark_client_desk_states", "tag_overrides")
    op.drop_column("ark_client_desk_states", "ai_tags")
