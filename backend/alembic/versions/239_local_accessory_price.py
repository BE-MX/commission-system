"""Keep native accessory price identity separate from preserved external IDs."""
from alembic import op
import sqlalchemy as sa

revision = "239_local_accessory_price"
down_revision = "238_local_sales_department"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("ark_std_prices", "accessory_model", existing_type=sa.String(128), type_=sa.String(200), existing_nullable=True)
    op.add_column("ark_std_prices", sa.Column("local_sku_id", sa.BigInteger(), nullable=True,
        comment="本地配件SKU，禁止与OKKI数字ID混用"))
    op.create_foreign_key("fk_std_price_local_sku", "ark_std_prices", "ark_catalog_skus",
                          ["local_sku_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_std_price_local_sku", "ark_std_prices", ["local_sku_id"])


def downgrade():
    raise RuntimeError("Restore a verified backup; native accessory prices must not be discarded")
