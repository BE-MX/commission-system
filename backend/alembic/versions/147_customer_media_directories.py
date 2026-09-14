"""Customer media directories (customer-level) and asset directory assignment."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "147_customer_media_directories"
down_revision = "146_ai_site_gateway"
branch_labels = None
depends_on = None


def upgrade():
    uid = mysql.INTEGER(unsigned=True)
    op.create_table("ark_customer_media_directories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("customer_id", sa.String(64), nullable=False, comment="customer_info.company_id"),
        sa.Column("name", sa.String(128), nullable=False, comment="目录名称"),
        sa.Column("created_by", uid, sa.ForeignKey("ark_users.id"), nullable=False, comment="创建人方舟用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="北京时间创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="北京时间更新时间"),
        sa.UniqueConstraint("customer_id", "name", name="uq_customer_media_directory_name"),
        sa.Index("idx_customer_media_directory_customer", "customer_id"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.add_column("ark_customer_media_assets", sa.Column(
        "directory_id", sa.BigInteger(),
        sa.ForeignKey("ark_customer_media_directories.id", ondelete="SET NULL"),
        nullable=True, comment="客户素材目录ID，空为未分类"))
    op.create_index("idx_customer_media_asset_directory", "ark_customer_media_assets", ["batch_id", "directory_id"])


def downgrade():
    op.drop_index("idx_customer_media_asset_directory", table_name="ark_customer_media_assets")
    op.drop_column("ark_customer_media_assets", "directory_id")
    op.drop_table("ark_customer_media_directories")
