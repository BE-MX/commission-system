"""Store certified order associations from completed supplier update seconds."""
from alembic import op
import sqlalchemy as sa

revision = "259_outbound_link_proof"
down_revision = "258_followup_deal_override"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_outbound_link_proofs",
        sa.Column("source_key", sa.String(64), primary_key=True, comment="小满接口地址与应用身份摘要"),
        sa.Column("outbound_id", sa.String(64), primary_key=True, comment="小满出库单 ID"),
        sa.Column("remote_version", sa.String(19), nullable=False, comment="小满出库单北京时间更新版本"),
        sa.Column("listed_at", sa.String(19), nullable=False, comment="小满有效列表响应的北京时间"),
        sa.Column("remote_status", sa.String(12), nullable=False, comment="已核验的小满出库状态"),
        sa.Column("remote_quantity", sa.String(64), nullable=False, comment="已核验的小满出库总数量"),
        sa.Column("order_ids", sa.JSON(), nullable=False, comment="完整明细关联的小满销售订单 ID"),
        mysql_engine="InnoDB",
    )


def downgrade():
    # These rows are derived provider evidence. The mirror can rebuild them.
    op.drop_table("ark_outbound_link_proofs")
