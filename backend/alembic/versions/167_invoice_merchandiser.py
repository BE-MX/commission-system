"""Invoice designated merchandiser (跟单员) columns."""
from alembic import op
import sqlalchemy as sa

revision = "167_invoice_merchandiser"
down_revision = "166_presale_settlement"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_invoices", sa.Column("merchandiser_id", sa.Integer(), nullable=True, comment="指定跟单员用户ID（ark_users.id）"))
    op.add_column("ark_invoices", sa.Column("merchandiser_name", sa.String(100), nullable=True, comment="跟单员姓名快照"))


def downgrade():
    op.drop_column("ark_invoices", "merchandiser_name")
    op.drop_column("ark_invoices", "merchandiser_id")
