"""Customer media tags: dimension tag_scope + customer media asset tag link table + seed dimension."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "151_customer_media_tags"
down_revision = "152_shipping_media_recall"
branch_labels = None
depends_on = None

SEED_DIMENSION_NAME = "customer_general"
# Match 020_add_asset_module: MySQL foreign keys must retain signedness.
_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def _check_existing(inspector):
    """MySQL DDL survives a failed upgrade; only resume compatible structures."""
    columns = {c["name"]: c for c in inspector.get_columns("ark_tag_dimensions")}
    scope = columns.get("tag_scope")
    if scope is not None and (
        not isinstance(scope["type"], sa.String)
        or scope["type"].length != 16 or scope["nullable"]
        or str(scope.get("default", "")).strip("'\"") != "internal"
    ):
        raise RuntimeError("Incompatible ark_tag_dimensions.tag_scope; inspect before retrying")
    indexes = {i["name"]: i for i in inspector.get_indexes("ark_tag_dimensions")}
    index = indexes.get("idx_tag_dim_scope")
    if index is not None and (index["column_names"] != ["tag_scope"] or index["unique"]):
        raise RuntimeError("Incompatible idx_tag_dim_scope; inspect before retrying")

    table = "ark_customer_media_asset_tags"
    if table in inspector.get_table_names():
        existing = {c["name"]: c for c in inspector.get_columns(table)}
        for name, parent in (
            ("asset_id", "ark_customer_media_assets"),
            ("dimension_id", "ark_tag_dimensions"),
            ("tag_value_id", "ark_tag_values"),
        ):
            target = next(c["type"] for c in inspector.get_columns(parent) if c["name"] == "id")
            column = existing.get(name)
            if column is None or column["nullable"] or (
                isinstance(column["type"], sa.BigInteger) != isinstance(target, sa.BigInteger)
                or not isinstance(column["type"], sa.Integer)
                or getattr(column["type"], "unsigned", False) != getattr(target, "unsigned", False)
            ):
                raise RuntimeError(f"Incompatible {table}.{name}; inspect before retrying")
        created = existing.get("created_at")
        if created is None or created["nullable"] or not isinstance(created["type"], sa.DateTime):
            raise RuntimeError(f"Incompatible {table}.created_at; inspect before retrying")
        if inspector.get_pk_constraint(table)["constrained_columns"] != ["asset_id", "dimension_id", "tag_value_id"]:
            raise RuntimeError(f"Incompatible {table} primary key; inspect before retrying")
        foreign_keys = inspector.get_foreign_keys(table)
        for name, parent in (("asset_id", "ark_customer_media_assets"),
                             ("dimension_id", "ark_tag_dimensions"),
                             ("tag_value_id", "ark_tag_values")):
            if not any(fk["constrained_columns"] == [name]
                       and fk["referred_table"] == parent and fk["referred_columns"] == ["id"]
                       and (name != "asset_id" or fk.get("options", {}).get("ondelete", "").upper() == "CASCADE")
                       for fk in foreign_keys):
                raise RuntimeError(f"Incompatible {table}.{name} foreign key; inspect before retrying")
        if not any(i["name"] == "idx_cmt_dim" and not i["unique"]
                   and i["column_names"] == ["dimension_id", "tag_value_id", "asset_id"]
                   for i in inspector.get_indexes(table)):
            raise RuntimeError(f"Incompatible {table} index; inspect before retrying")


def upgrade():
    bind = op.get_bind()
    _check_existing(sa.inspect(bind))

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
            sa.Column("dimension_id", _UINT,
                      sa.ForeignKey("ark_tag_dimensions.id"),
                      primary_key=True, comment="标签维度ID"),
            sa.Column("tag_value_id", _UINT,
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
