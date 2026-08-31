"""Add domestic conditional route rules and audited skips.

Revision ID: 127_domestic_route_rules
Revises: 126
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "127_domestic_route_rules"
down_revision = "126"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    op.add_column(
        "ark_domestic_report_logs",
        sa.Column("outcome_json", sa.JSON(), nullable=True, comment="决策工序的结果数量分配"),
    )
    op.add_column(
        "ark_domestic_report_units",
        sa.Column("outcome_code", sa.String(32), nullable=True, comment="单件决策结果编码"),
    )

    op.create_table(
        "ark_domestic_route_rules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("route_id", sa.Integer(), nullable=False, comment="共享工艺路线 ID"),
        sa.Column("process_id", sa.Integer(), nullable=False, comment="触发规则的工序 ID"),
        sa.Column("rule_type", sa.String(16), nullable=False, comment="decision/optional"),
        sa.Column("config_json", sa.JSON(), nullable=True, comment="服务端校验后的规则配置"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(["route_id"], ["process_route.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["process_id"], ["process.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["route_id", "process_id"],
            ["process_route_step.route_id", "process_route_step.process_id"],
            ondelete="RESTRICT",
            name="fk_dom_route_rule_step",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_id", "process_id", name="uq_dom_route_rule_process"),
        comment="内贸专用条件路线规则",
    )

    op.create_table(
        "ark_domestic_skip_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("item_id", sa.Integer(), nullable=False, comment="所属订单明细"),
        sa.Column("progress_id", sa.Integer(), nullable=False, comment="被跳过的进度行"),
        sa.Column("skip_qty", sa.Integer(), nullable=False, comment="跳过数量"),
        sa.Column(
            "source",
            sa.String(24),
            nullable=False,
            comment="decision/optional_bypass/manual",
        ),
        sa.Column(
            "skip_mode",
            sa.String(16),
            nullable=True,
            comment="人工跳过模式：quantity/unit；自动跳过为空",
        ),
        sa.Column("reason", sa.String(500), nullable=True, comment="跳过原因；人工放行必填"),
        sa.Column(
            "trigger_report_log_id",
            sa.BigInteger(),
            nullable=True,
            comment="触发本次跳过的报工流水",
        ),
        sa.Column("request_id", sa.String(64), nullable=True, comment="人工放行等入口的幂等键"),
        sa.Column("created_by_user_id", USER_ID, nullable=False, comment="操作人"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column(
            "revoked",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
            comment="0=有效,1=已撤销",
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True, comment="撤销时间"),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["ark_domestic_order_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["progress_id"],
            ["ark_domestic_item_progress.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_report_log_id"],
            ["ark_domestic_report_logs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["ark_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_dom_skip_request_id"),
        comment="内贸工序跳过审计流水",
    )

    op.create_table(
        "ark_domestic_skip_units",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("skip_log_id", sa.BigInteger(), nullable=False, comment="跳过流水 ID"),
        sa.Column("unit_id", sa.BigInteger(), nullable=False, comment="被跳过的单件 ID"),
        sa.Column("progress_id", sa.Integer(), nullable=False, comment="被跳过的进度行"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["skip_log_id"],
            ["ark_domestic_skip_logs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["ark_domestic_item_units.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["progress_id"],
            ["ark_domestic_item_progress.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skip_log_id", "unit_id", name="uq_dom_skip_log_unit"),
        comment="内贸跳过流水对应的逐件清单",
    )


def downgrade() -> None:
    op.drop_table("ark_domestic_skip_units")
    op.drop_table("ark_domestic_skip_logs")
    op.drop_table("ark_domestic_route_rules")
    op.drop_column("ark_domestic_report_units", "outcome_code")
    op.drop_column("ark_domestic_report_logs", "outcome_json")
