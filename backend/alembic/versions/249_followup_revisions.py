"""Immutable confirmed-followup revisions and archived attachment evidence.

Revision ID: 249_followup_revisions
Revises: 248_navigation_config
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "249_followup_revisions"
down_revision = "248_navigation_config"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_followup_attachments", sa.Column(
        "archived_at", sa.DateTime(), nullable=True, comment="编辑移除时间；保留文件供修改历史读取"))
    op.add_column("ark_domestic_followup_digests", sa.Column(
        "send_claimed_at", sa.DateTime(), nullable=True, comment="开始发送时间；五分钟租约内编辑不撤回在途通知"))
    op.create_table(
        "ark_domestic_followup_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("followup_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_followups.id"), nullable=False, comment="跟进记录"),
        sa.Column("editor_user_id", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=False, comment="修改人"),
        sa.Column("version", sa.Integer(), nullable=False, comment="保存后的记录版本"),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True, comment="修改请求幂等键"),
        sa.Column("request_hash", sa.String(64), nullable=False, comment="请求内容哈希"),
        sa.Column("reason", sa.String(500), nullable=False, comment="修改原因"),
        sa.Column("before_snapshot", sa.JSON(), nullable=False, comment="修改前记录与关联任务快照"),
        sa.Column("after_snapshot", sa.JSON(), nullable=False, comment="修改后记录与关联任务快照"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="修改时间（北京时间）"),
        sa.UniqueConstraint("followup_id", "version", name="uq_dom_followup_revision"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM ark_domestic_followup_revisions")):
        raise RuntimeError("Followup revision evidence exists; preserve history before downgrade")
    op.drop_table("ark_domestic_followup_revisions")
    op.drop_column("ark_domestic_followup_attachments", "archived_at")
    op.drop_column("ark_domestic_followup_digests", "send_claimed_at")
