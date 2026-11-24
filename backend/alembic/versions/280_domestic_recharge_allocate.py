"""Allow posted recharge ledgers as delivery allocation sources."""
from alembic import op
import sqlalchemy as sa

revision = "280_domestic_recharge_allocate"
down_revision = "279_shipping_waybill_photos"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ark_domestic_receipt_allocations") as batch:
        batch.alter_column("request_id", existing_type=sa.BigInteger(), nullable=True,
                           existing_comment="来源申请ID或客户端幂等键", comment="收款申请ID；充值核销为空")
        # InnoDB already indexes ledger_id for its existing foreign key.
        batch.create_check_constraint("ck_dom_allocation_source", "request_id IS NOT NULL OR ledger_id IS NOT NULL")


def downgrade():
    # Never erase recharge reconciliation evidence to fit the old schema.
    count = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM ark_domestic_receipt_allocations WHERE request_id IS NULL"
    )).scalar()
    if count:
        raise RuntimeError("Recharge allocations exist; preserve them before reverting this schema")
    with op.batch_alter_table("ark_domestic_receipt_allocations") as batch:
        batch.drop_constraint("ck_dom_allocation_source", type_="check")
        batch.alter_column("request_id", existing_type=sa.BigInteger(), nullable=False,
                           existing_comment="收款申请ID；充值核销为空", comment="来源申请ID或客户端幂等键")
