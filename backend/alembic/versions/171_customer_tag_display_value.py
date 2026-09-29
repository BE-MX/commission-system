"""Store each customer's own label text without changing shared tag values."""

from alembic import op
import sqlalchemy as sa


revision = "171_customer_tag_display_value"
down_revision = "170_presale_freight_name"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("ark_customer_media_customer_tags")}
    if "display_value" not in columns:
        op.add_column("ark_customer_media_customer_tags", sa.Column("display_value", sa.String(128), nullable=True))
    bind.execute(sa.text("""
        UPDATE ark_customer_media_customer_tags AS customer_tag
        JOIN ark_tag_values AS tag_value ON tag_value.id = customer_tag.tag_value_id
        SET customer_tag.display_value = tag_value.value
        WHERE customer_tag.display_value IS NULL
    """) if bind.dialect.name == "mysql" else sa.text("""
        UPDATE ark_customer_media_customer_tags
        SET display_value = (SELECT value FROM ark_tag_values WHERE id = tag_value_id)
        WHERE display_value IS NULL
    """))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("ark_customer_media_customer_tags")}
    if "uq_customer_media_customer_tag_name" not in indexes:
        op.create_index(
            "uq_customer_media_customer_tag_name", "ark_customer_media_customer_tags",
            ["customer_id", "dimension_id", "display_value"], unique=True,
        )


def downgrade():
    op.drop_index("uq_customer_media_customer_tag_name", table_name="ark_customer_media_customer_tags")
    op.drop_column("ark_customer_media_customer_tags", "display_value")
