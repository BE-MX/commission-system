"""Move guest names to domestic order items, retaining the legacy header as history."""
from alembic import op
import sqlalchemy as sa

revision = "150_domestic_item_guest"
down_revision = "149_dom_order_review_columns"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"]: c for c in sa.inspect(bind).get_columns("ark_domestic_order_items")}
    if "guest_name" not in columns:
        op.add_column("ark_domestic_order_items", sa.Column("guest_name", sa.String(120), nullable=True))
    else:
        column = columns["guest_name"]
        if not isinstance(column["type"], sa.String) or column["type"].length != 120 or not column["nullable"]:
            raise RuntimeError("Incompatible domestic item guest_name column")
    if "guest_order_date" not in columns:
        op.add_column("ark_domestic_order_items", sa.Column("guest_order_date", sa.Date(), nullable=True))
    else:
        column = columns["guest_order_date"]
        if not isinstance(column["type"], sa.Date) or not column["nullable"]:
            raise RuntimeError("Incompatible domestic item guest_order_date column")
    # Historical guest order dates are unknown and remain NULL.
    # Preserve each historical order's guest on its existing lines; never replace a line name.
    op.execute(sa.text("""
        UPDATE ark_domestic_order_items
        SET guest_name = (
            SELECT guest_name FROM ark_domestic_orders
            WHERE ark_domestic_orders.id = ark_domestic_order_items.order_id
              AND ark_domestic_orders.order_kind = 'business'
        )
        WHERE guest_name IS NULL
    """))


def downgrade():
    raise RuntimeError("Item guest names cannot be collapsed into one order guest without data loss")
