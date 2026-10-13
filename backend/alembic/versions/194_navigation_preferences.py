"""Store personal ordered navigation preferences."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "194_navigation_preferences"
down_revision = "193_wa_ai_assistant"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_navigation_preferences",
        sa.Column("user_id", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id", ondelete="CASCADE"), primary_key=True, comment="所属用户，一人一行"),
        sa.Column("items", sa.JSON(), nullable=False, comment="按用户排序的常用导航标识列表"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新北京时间"),
        comment="用户常用导航配置",
    )


def downgrade():
    op.drop_table("ark_navigation_preferences")
