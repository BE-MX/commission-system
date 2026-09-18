"""Persist linked invoice synchronization steps and the invoice write fence."""
from alembic import op
import sqlalchemy as sa

revision = "158_invoice_linked_sync"
down_revision = "157_invoice_customer_grade"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "linked_sync_id" not in {c["name"] for c in inspector.get_columns("ark_invoices")}:
        op.add_column("ark_invoices", sa.Column("linked_sync_id", sa.String(64), nullable=True,
                                          comment="当前关联同步任务ID；非空时冻结其他写入"))
    if inspector.has_table("ark_invoice_linked_syncs"):
        required = {"id", "invoice_id", "request_key", "request_hash", "status", "before", "after", "steps",
                    "run_token", "lease_until", "created_by", "created_at", "updated_at"}
        if required != {c["name"] for c in inspector.get_columns("ark_invoice_linked_syncs")}:
            raise RuntimeError("Existing linked sync table differs from expected schema")
        return
    op.create_table("ark_invoice_linked_syncs",
        sa.Column("id", sa.String(64), primary_key=True, comment="关联同步任务ID"),
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("ark_invoices.id"), nullable=False, comment="关联发票ID"),
        sa.Column("request_key", sa.String(64), nullable=False, unique=True, comment="保存请求幂等键"),
        sa.Column("request_hash", sa.String(64), nullable=False, comment="请求内容摘要"),
        sa.Column("status", sa.String(24), nullable=False, comment="任务执行状态"),
        sa.Column("before", sa.JSON(), nullable=False, comment="修改前业务快照"),
        sa.Column("after", sa.JSON(), nullable=False, comment="修改后业务快照"),
        sa.Column("steps", sa.JSON(), nullable=False, comment="分步状态与结果"),
        sa.Column("run_token", sa.String(64), nullable=True, comment="执行令牌"),
        sa.Column("lease_until", sa.DateTime(), nullable=True, comment="租约截止时间，北京时间"),
        sa.Column("created_by", sa.Integer(), nullable=False, comment="操作人ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间，北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间，北京时间"))
    op.create_index("ix_ark_invoice_linked_syncs_invoice_id", "ark_invoice_linked_syncs", ["invoice_id"])


def downgrade():
    raise RuntimeError("Linked synchronization audit records must be preserved; forward migration required")
