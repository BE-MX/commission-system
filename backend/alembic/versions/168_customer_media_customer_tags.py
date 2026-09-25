"""Keep customer labels across bookings and backfill labels already used by media."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "168_customer_media_customer_tags"
down_revision = "167_invoice_merchandiser"
branch_labels = None
depends_on = None

_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    bind = op.get_bind()
    if "ark_customer_media_customer_tags" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "ark_customer_media_customer_tags",
            sa.Column("customer_id", sa.String(64), primary_key=True, comment="customer_info.company_id"),
            sa.Column("dimension_id", _UINT, sa.ForeignKey("ark_tag_dimensions.id"), primary_key=True),
            sa.Column("tag_value_id", _UINT, sa.ForeignKey("ark_tag_values.id"), primary_key=True),
            sa.Column("created_by", _UINT, sa.ForeignKey("ark_users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Index("idx_customer_media_customer_tag_value", "tag_value_id", "customer_id"),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            comment="客户标签集合，跨预约与拍摄任务复用",
        )

    # Historical asset labels become reusable customer labels. A file may be removed
    # without erasing the customer's label vocabulary, so only live files seed it.
    bind.execute(sa.text("""
        INSERT INTO ark_customer_media_customer_tags
            (customer_id, dimension_id, tag_value_id, created_by, created_at)
        SELECT b.customer_id, t.dimension_id, t.tag_value_id,
               MIN(a.uploaded_by), MIN(a.created_at)
        FROM ark_customer_media_asset_tags AS t
        JOIN ark_customer_media_assets AS a ON a.id = t.asset_id
        JOIN ark_customer_media_batches AS b ON b.id = a.batch_id
        LEFT JOIN ark_customer_media_customer_tags AS existing
          ON existing.customer_id = b.customer_id
         AND existing.dimension_id = t.dimension_id
         AND existing.tag_value_id = t.tag_value_id
        WHERE a.deleted_at IS NULL AND existing.customer_id IS NULL
        GROUP BY b.customer_id, t.dimension_id, t.tag_value_id
    """))


def downgrade():
    op.drop_table("ark_customer_media_customer_tags")
