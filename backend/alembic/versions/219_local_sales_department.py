"""Reference stable local department dictionary identities from sales roster."""
from alembic import op
import sqlalchemy as sa

revision = "219_local_sales_department"
down_revision = "218_native_battle_members"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_sales_roster", sa.Column("department_id", sa.Integer(), nullable=True, comment="本地销售部门字典稳定ID"))
    op.create_foreign_key("fk_sales_roster_department", "ark_sales_roster", "sys_dict", ["department_id"], ["id"], ondelete="RESTRICT")


def downgrade():
    raise RuntimeError("Restore a verified backup; native department assignments must not be silently discarded")
