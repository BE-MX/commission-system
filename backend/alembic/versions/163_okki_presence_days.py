"""Persist bounded OKKI active-outbound creation-day snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "163_okki_presence_days"
down_revision = "162_battle_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_okki_outbound_presence_days",
        sa.Column("creation_date", sa.Date(), primary_key=True, comment="OKKI 出库单创建日期（北京时间）"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", comment="pending/ready/error"),
        sa.Column("active_ids", sa.JSON(), nullable=False, comment="两轮一致的有效出库单 ID"),
        sa.Column("active_versions", sa.JSON(), nullable=False, comment="有效出库单列表行版本摘要"),
        sa.Column("detail_order_ids", sa.JSON(), nullable=False, comment="已补查出库单到订单 ID 的关联"),
        sa.Column("retained_order_ids", sa.JSON(), nullable=False, comment="有效出库单关联订单 ID"),
        sa.Column("pending_detail_ids", sa.JSON(), nullable=False, comment="待增量补查关联的有效出库单 ID"),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0", comment="有效出库单数量"),
        sa.Column("snapshot_hash", sa.String(64), nullable=True, comment="有效 ID 集合 SHA-256"),
        sa.Column("last_error", sa.String(255), nullable=True, comment="最近失败的可行动摘要"),
        sa.Column("attempted_at", sa.DateTime(), nullable=False, comment="最近尝试时间（北京时间）"),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True, comment="最近完成时间（北京时间）"),
        comment="按创建日期增量持久化的 OKKI 有效出库单快照",
    )


def downgrade():
    raise RuntimeError("Outbound presence evidence must be retained; use a forward migration")
