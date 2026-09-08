"""Allow optional customer associations on zero-priced production orders."""

from alembic import op
import sqlalchemy as sa

revision = "142_domestic_prod_customer"
down_revision = "141_whatsapp_reply_requests"
branch_labels = None
depends_on = None

TABLE = "ark_domestic_orders"
CONSTRAINT = "ck_dom_order_kind_fields"
KIND_FIELDS = (
    "(order_kind = 'business' AND customer_id IS NOT NULL AND order_category IS NOT NULL AND order_category IN ('normal', 'special')) OR "
    "(order_kind = 'production' AND order_category IS NULL AND "
    "order_type IS NULL AND order_channel IS NULL AND required_ship_date IS NULL AND total_amount = 0 AND charged_amount = 0)"
)
OLD_KIND_FIELDS = KIND_FIELDS.replace(
    "order_kind = 'production' AND ", "order_kind = 'production' AND customer_id IS NULL AND ",
)


def _replace_check(condition):
    if op.get_bind().dialect.name == "mysql":
        # Replace in one DDL statement so the table never loses its sales/price guard.
        op.execute(sa.text(
            f"ALTER TABLE {TABLE} DROP CHECK {CONSTRAINT}, "
            f"ADD CONSTRAINT {CONSTRAINT} CHECK ({condition})"
        ))
    else:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(CONSTRAINT, type_="check")
            batch.create_check_constraint(CONSTRAINT, condition)


def upgrade():
    _replace_check(KIND_FIELDS)


def downgrade():
    linked = op.get_bind().execute(sa.text(
        f"SELECT COUNT(*) FROM {TABLE} WHERE order_kind = 'production' AND customer_id IS NOT NULL"
    )).scalar_one()
    if linked:
        raise RuntimeError("Production orders have customer associations; preserve them and migrate forward")
    _replace_check(OLD_KIND_FIELDS)
