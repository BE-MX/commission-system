"""Add immutable administrator account unlock evidence; leave login logs intact."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "176_account_unlock"
down_revision = "175_receipt_recovery"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    op.create_table(
        "ark_account_unlock_audits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="解锁审计ID"),
        sa.Column("user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="被解锁用户ID"),
        sa.Column("operator_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="操作人用户ID"),
        sa.Column("operator_username", sa.String(50), nullable=False, comment="操作人用户名快照"),
        sa.Column("through_login_log_id", sa.BigInteger(), nullable=False, comment="本次解除的失败日志ID上界"),
        sa.Column("failed_count", sa.Integer(), nullable=False, comment="解除时窗口内失败次数"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="北京时间解锁时间"),
        comment="管理员账号解锁审计，原登录日志保留",
    )
    op.create_index("ix_ark_account_unlock_audits_user_id", "ark_account_unlock_audits", ["user_id"])


def downgrade():
    raise RuntimeError("Account unlock audit data must be preserved; use a forward migration")
