"""Freeze original allocation attribution and unique commission consumption."""
from alembic import op
import sqlalchemy as sa

revision = "235_local_commission"
down_revision = "234_aftersales_money_release"
branch_labels = None
depends_on = None


def upgrade():
    for table, columns in (("synced_payment", ("payment_amount",)),
        ("commission_detail", ("payment_amount", "salesperson_commission", "supervisor_commission", "second_supervisor_commission"))):
        previous = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns(table)}
        for column in columns:
            definition = previous[column]
            op.alter_column(table, column, type_=sa.Numeric(14, 2), existing_type=definition["type"],
                existing_nullable=definition["nullable"], existing_server_default=(sa.text(definition["default"]) if definition["default"] is not None else None),
                existing_comment=definition.get("comment"))
    op.create_table("ark_commission_bases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="核销提成依据 ID"),
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("ark_finance_events.id"), nullable=False, unique=True, comment="原核销事件"),
        sa.Column("customer_id", sa.String(64), nullable=False, comment="明确身份的客户 ID"),
        sa.Column("snapshot", sa.JSON(), nullable=True, comment="冻结受益人、比例和名称"),
        sa.Column("pending_reason", sa.String(256), nullable=True, comment="待补全原因"),
        sa.Column("resolved_by", sa.Integer(), nullable=True, comment="补全操作人 ID"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True, comment="补全北京时间"),
        sa.Column("resolution_reason", sa.String(1000), nullable=True, comment="补全依据"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="冻结北京时间"))
    op.create_index("ix_ark_commission_bases_customer_id", "ark_commission_bases", ["customer_id"])
    op.create_table("ark_commission_event_projections",
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("ark_finance_events.id"), primary_key=True, comment="唯一被消费资金事件"),
        sa.Column("basis_id", sa.BigInteger(), sa.ForeignKey("ark_commission_bases.id"), nullable=False, comment="原核销提成依据"),
        sa.Column("payment_id", sa.String(64), nullable=False, unique=True, comment="提成消费身份"),
        sa.Column("salesperson_commission", sa.Numeric(14, 2), nullable=False, comment="业务员提成"),
        sa.Column("supervisor_commission", sa.Numeric(14, 2), nullable=False, comment="一级主管提成"),
        sa.Column("second_supervisor_commission", sa.Numeric(14, 2), nullable=False, comment="二级主管提成"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="投影北京时间"))
    op.create_index("ix_ark_commission_event_projections_basis_id", "ark_commission_event_projections", ["basis_id"])


def downgrade():
    raise RuntimeError("Commission provenance cannot be discarded; use a corrective migration")
