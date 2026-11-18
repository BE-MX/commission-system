"""Cache AI explanations for the product sales radar."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "273_product_sales_insights"
down_revision = "272_product_sales_mappings"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    op.create_table(
        "ark_product_sales_ai_insights",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("cache_key", sa.String(64), nullable=False, comment="范围+维度+款+窗口+日期+映射版本的 SHA-256"),
        sa.Column("scope_key", sa.String(160), nullable=False, comment="份额口径：self/user/team/none + ID"),
        sa.Column("dimension", sa.String(24), nullable=False, comment="维度：color_size/category/item"),
        sa.Column("item_key", sa.String(512), nullable=False, comment="款的键值，如「#1B · 18」"),
        sa.Column("window_days", sa.Integer(), nullable=False, comment="对比窗口天数"),
        sa.Column("as_of_date", sa.Date(), nullable=False, comment="解读所依据数据的截止日期（北京时间）"),
        sa.Column("content", sa.Text(), nullable=False, comment="解读正文（Markdown）"),
        sa.Column("source", sa.String(16), nullable=False, comment="ai 模型生成 / rules 规则降级"),
        sa.Column("evidence", sa.JSON(), nullable=False, comment="提交给模型的结构化证据"),
        sa.Column("created_by_user_id", USER_ID, nullable=True, comment="首次生成的方舟用户"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="生成时间"),
        sa.Column("expires_at", sa.DateTime(), nullable=False, comment="复用截止时间（生成后 24 小时）"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["ark_users.id"], ondelete="SET NULL",
                                name="fk_ps_insight_created_by"),
        sa.UniqueConstraint("cache_key", name="uq_ps_insight_cache_key"),
        comment="产品风向标 AI 解读结果缓存",
    )
    op.create_index("idx_ps_insight_expires", "ark_product_sales_ai_insights", ["expires_at"])


def downgrade():
    op.drop_index("idx_ps_insight_expires", table_name="ark_product_sales_ai_insights")
    op.drop_table("ark_product_sales_ai_insights")
