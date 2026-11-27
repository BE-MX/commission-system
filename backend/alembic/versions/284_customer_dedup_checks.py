"""Customer dedup lookup audit table (per-user rate limit and abuse trail)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "284_customer_dedup_checks"
down_revision = "283_wa_unlinked_ai"
branch_labels = None
depends_on = None

_UID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    op.create_table(
        "ark_customer_dedup_checks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("user_id", _UID, nullable=False, comment="发起查重的方舟用户ID（ark_users.id）"),
        sa.Column("auth_channel", sa.String(16), nullable=False, comment="鉴权方式：personal_token=个人令牌，session=登录会话"),
        sa.Column("platform", sa.String(16), nullable=False, comment="识别出的平台：instagram/facebook/whatsapp/wechat/linkedin/pinterest/tiktok/x/yelp/youtube/email"),
        sa.Column("normalized_value", sa.String(500), nullable=False, comment="统一格式后的账号或邮箱"),
        sa.Column("result_status", sa.String(16), nullable=False, comment="查重结论：private=已在私海，public=公海，not_found=未收录，inconclusive=无法可靠判断，pending=查询中或中途失败（仍计入限频）"),
        sa.Column("matched_count", sa.SmallInteger(), nullable=False, comment="命中的客户数"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="查询时间（北京时间）"),
        comment="客户查重调用审计；每次查重一行，用于按人限频和追查批量探查同事私海",
    )
    op.create_index("idx_customer_dedup_checks_user_time", "ark_customer_dedup_checks", ["user_id", "created_at"])


def downgrade():
    op.drop_index("idx_customer_dedup_checks_user_time", table_name="ark_customer_dedup_checks")
    op.drop_table("ark_customer_dedup_checks")
