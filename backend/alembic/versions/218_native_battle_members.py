"""Allow native Ark battle members without inventing external identities."""
from alembic import op
import sqlalchemy as sa

revision = "218_native_battle_members"
down_revision = "217_local_trade_projection"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("ark_battle_report_members", "okki_user_id", existing_type=sa.String(100),
        existing_nullable=False, nullable=True, comment="历史订单负责人OKKI稳定ID快照，本地员工可空")


def downgrade():
    raise RuntimeError("Native battle members may have no external identity; restore a verified backup instead")
