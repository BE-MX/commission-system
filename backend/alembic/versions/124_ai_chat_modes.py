"""Pin built-in conversation instructions at the first turn."""

from alembic import op
import sqlalchemy as sa

revision = "124_ai_chat_modes"
down_revision = "123_platform_beijing_time"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_ai_chat_sessions", sa.Column("mode_snapshot", sa.JSON(), nullable=True, comment="首次发送选定的内置规则及版本快照"))


def downgrade():
    op.drop_column("ark_ai_chat_sessions", "mode_snapshot")
