"""WhatsApp unlinked chats: owner switch for the B-track daily AI pass."""
from alembic import op
import sqlalchemy as sa

revision = "283_wa_unlinked_ai"
down_revision = "282_client_desk_unlinked"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_whatsapp_accounts", sa.Column(
        "unlinked_ai_allowed", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="持有人明确允许对未绑定活跃单聊做线索初筛",
    ))


def downgrade():
    op.drop_column("ark_whatsapp_accounts", "unlinked_ai_allowed")
