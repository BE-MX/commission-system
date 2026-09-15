"""Customer media tags: dimension tag_scope + customer media asset tag link table + seed dimension."""

from alembic import op
import sqlalchemy as sa

revision = "151_customer_media_tags"
down_revision = "150_domestic_item_guest"
branch_labels = None
depends_on = None

SEED_DIMENSION_NAME = "customer_general"


def upgrade():
    bind = op.get_bind()

    columns = {c["name"] for c in sa.inspect(bind).get_columns("ark_tag_dimensions")}
    if "tag_scope" not in columns:
        op.add_column("ark_tag_dimensions", sa.Column(
            "tag_scope", sa.String(16), nullable=False, server_default="internal",
            comment="标签使用域 internal=内部素材库/customer=客户标签"))

    indexes = {ix["name"] for ix in sa.inspect(bind).get_indexes("ark_tag_dimensions")}
    if "idx_tag_dim_scope" not in indexes:
        op.create_index("idx_tag_dim_scope", "ark_tag_dimensions", ["tag_scope"])

    if "ark_customer_media_asset_tags" not in sa.inspect(bind).get_table_names():
        op.create_table("ark_customer_media_asset_tags",
            sa.Column("asset_id", sa.BigInteger(),
                      sa.ForeignKey("ark_customer_media_assets.id", ondelete="CASCADE"),
                      primary_key=True, comment="客户素材ID"),
            sa.Column("dimension_id", sa.Integer(),
                      sa.ForeignKey("ark_tag_dimensions.id"),
                      primary_key=True, comment="标签维度ID"),
            sa.Column("tag_value_id", sa.Integer(),
                      sa.ForeignKey("ark_tag_values.id"),
                      primary_key=True, comment="标签值ID"),
            sa.Column("created_at", sa.DateTime(), nullable=False, comment="打标时间"),
            sa.Index("idx_cmt_dim", "dimension_id", "tag_value_id", "asset_id"),
            mysql_engine="InnoDB", mysql_charset="utf8mb4")

    seeded = bind.execute(sa.text(
        "SELECT id FROM ark_tag_dimensions WHERE name = :name"
    ), {"name": SEED_DIMENSION_NAME}).first()
    if not seeded:
        bind.execute(sa.text(
            "INSERT INTO ark_tag_dimensions "
            "(name, label, is_single_select, is_system, is_required, is_visible, is_managed, sort_order, tag_scope, created_at) "
            "VALUES (:name, '客户标签', 0, 1, 0, 1, 0, 0, 'customer', CURRENT_TIMESTAMP)"
        ), {"name": SEED_DIMENSION_NAME})


def downgrade():
    bind = op.get_bind()

    if "ark_customer_media_asset_tags" in sa.inspect(bind).get_table_names():
        bind.execute(sa.text(
            "DELETE FROM ark_customer_media_asset_tags WHERE dimension_id IN "
            "(SELECT id FROM ark_tag_dimensions WHERE name = :name)"
        ), {"name": SEED_DIMENSION_NAME})
        op.drop_table("ark_customer_media_asset_tags")
    bind.execute(sa.text(
        "DELETE FROM ark_tag_values WHERE dimension_id IN "
        "(SELECT id FROM ark_tag_dimensions WHERE name = :name)"
    ), {"name": SEED_DIMENSION_NAME})
    bind.execute(sa.text(
        "DELETE FROM ark_tag_dimensions WHERE name = :name AND tag_scope = 'customer'"
    ), {"name": SEED_DIMENSION_NAME})

    indexes = {ix["name"] for ix in sa.inspect(bind).get_indexes("ark_tag_dimensions")}
    if "idx_tag_dim_scope" in indexes:
        op.drop_index("idx_tag_dim_scope", table_name="ark_tag_dimensions")
    columns = {c["name"] for c in sa.inspect(bind).get_columns("ark_tag_dimensions")}
    if "tag_scope" in columns:
        op.drop_column("ark_tag_dimensions", "tag_scope")
