"""Battle poster calendar and durable per-slot delivery ledger."""
from alembic import op
import sqlalchemy as sa

revision = "164_battle_posters"
down_revision = "163_okki_presence_days"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_battle_reports", sa.Column("work_dates", sa.JSON(), nullable=True, comment="北京时间计时工作日，ISO 日期数组"))
    op.add_column("ark_battle_reports", sa.Column("poster_push_enabled", sa.Boolean(), nullable=False, server_default=sa.false(), comment="13:00/17:00 群海报开关"))
    op.create_table("ark_battle_report_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("ark_battle_reports.id"), nullable=False, comment="战报ID"),
        sa.Column("report_date", sa.Date(), nullable=False, comment="投递日期（北京时间）"),
        sa.Column("slot", sa.String(5), nullable=False, comment="投递时段：13:00 或 17:00"),
        sa.Column("snapshot", sa.JSON(), nullable=False, comment="两张海报共同的不可变业务快照"),
        sa.Column("destination_hash", sa.String(64), nullable=False, comment="Webhook 指纹，不存凭据"),
        sa.Column("deliveries", sa.JSON(), nullable=False, comment="两张图独立状态；不确定送达不自动重试"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="快照创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="状态更新时间（北京时间）"),
        sa.UniqueConstraint("report_id", "report_date", "slot", name="uq_battle_delivery_slot"))
    op.create_index("ix_ark_battle_report_deliveries_report_id", "ark_battle_report_deliveries", ["report_id"])


def downgrade():
    raise RuntimeError("Preserve delivery history; use a forward migration")
