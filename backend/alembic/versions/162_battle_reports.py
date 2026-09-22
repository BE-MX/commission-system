"""Independent time-bounded sales goals and roster snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "162_battle_reports"
down_revision = "161_invoice_lifecycle"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    op.create_table("ark_battle_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, comment="战报名称"),
        sa.Column("start_date", sa.Date(), nullable=False, comment="开始日期（北京时间）"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="结束日期（含当日）"),
        sa.Column("target_deadline", sa.DateTime(), nullable=False, comment="目标填报截止时间（北京时间）"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft", comment="草稿、已发布、归档状态"),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="activity", comment="汇总可见范围"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD", comment="统计币种"),
        sa.Column("basis_version", sa.String(32), nullable=False, server_default="order_gmv_roster_v1", comment="统计口径版本"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="并发修改版本"),
        sa.Column("created_by", sa.Integer(), nullable=False, comment="创建人方舟账号ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"))
    op.create_table("ark_battle_report_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("ark_battle_reports.id"), nullable=False, comment="战报ID"),
        sa.Column("ark_user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="方舟用户ID"),
        sa.Column("okki_user_id", sa.String(100), nullable=False, comment="订单负责人OKKI稳定ID快照"),
        sa.Column("user_name", sa.String(100), nullable=False, comment="姓名快照"),
        sa.Column("team", sa.String(100), nullable=False, comment="活动小组快照"),
        sa.Column("is_captain", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否组长，可查看本组订单"),
        sa.Column("target_usd", sa.Numeric(16, 2), nullable=True, comment="周期美元目标，空值表示未填报"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="并发修改版本"),
        sa.Column("target_updated_at", sa.DateTime(), nullable=True, comment="目标更新时间（北京时间）"),
        sa.UniqueConstraint("report_id", "okki_user_id", name="uq_battle_report_okki"),
        sa.UniqueConstraint("report_id", "ark_user_id", name="uq_battle_report_ark"))
    op.create_index("ix_ark_battle_report_members_report_id", "ark_battle_report_members", ["report_id"])
    op.create_table("ark_battle_report_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("ark_battle_reports.id"), nullable=False, comment="战报ID"),
        sa.Column("actor_id", sa.Integer(), nullable=False, comment="操作人方舟账号ID"),
        sa.Column("action", sa.String(32), nullable=False, comment="审计动作"),
        sa.Column("before", sa.JSON(), nullable=True, comment="修改前内容"),
        sa.Column("after", sa.JSON(), nullable=True, comment="修改后内容"),
        sa.Column("reason", sa.String(500), nullable=False, server_default="", comment="修改原因"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"))
    op.create_index("ix_ark_battle_report_audits_report_id", "ark_battle_report_audits", ["report_id"])


def downgrade():
    raise RuntimeError("Battle report goals and audit history must be preserved; use a forward migration")
