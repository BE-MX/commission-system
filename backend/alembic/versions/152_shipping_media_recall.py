"""Add inspection media types and recall version without changing existing photos."""
from alembic import op
import sqlalchemy as sa

revision = "152_shipping_media_recall"
down_revision = ("150_domestic_item_guest", "146_expo_beautify_prompt")
branch_labels = None
depends_on = None


def upgrade():
    # MySQL DDL commits independently. Validate existing columns on a resumed deployment.
    additions = {
        "ark_shipping_inspections": [
            sa.Column("edit_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recalled_at", sa.DateTime(), nullable=True),
            sa.Column("recalled_by", sa.BigInteger(), nullable=True),
        ],
        "ark_shipping_inspection_photos": [
            sa.Column("media_type", sa.String(10), nullable=False, server_default="image"),
        ],
    }
    for table, columns in additions.items():
        existing = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns(table)}
        for column in columns:
            found = existing.get(column.name)
            if found is None:
                op.add_column(table, column)
            elif (not isinstance(found["type"], type(column.type))
                  or found["nullable"] != column.nullable
                  or getattr(found["type"], "length", None) != getattr(column.type, "length", None)):
                raise RuntimeError(f"Incompatible {table}.{column.name}")
            elif column.server_default is not None:
                actual = str(found.get("default") or "").strip("()'\"")
                if actual != str(column.server_default.arg):
                    raise RuntimeError(f"Incompatible default {table}.{column.name}")


def downgrade():
    raise RuntimeError("Shipping media/recall history must be preserved; use a reviewed forward migration")
