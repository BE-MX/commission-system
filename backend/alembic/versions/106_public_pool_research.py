"""Public-pool research batches, subjects, evidence and deal assessment.

Revision ID: 106_public_pool_research
Revises: 105_knowledge_category
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "106_public_pool_research"
down_revision = "105_knowledge_category"
branch_labels = None
depends_on = None


USER_ID = mysql.INTEGER(unsigned=True)


def _audit_columns():
    return [
        sa.Column("created_by", USER_ID, nullable=True, comment="创建人用户ID"),
        sa.Column("updated_by", USER_ID, nullable=True, comment="最后更新人用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
    ]


def upgrade():
    op.create_table(
        "ark_sales_research_subjects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("subject_type", sa.String(32), nullable=False, comment="研究主体类型 okki_customer/lead_company"),
        sa.Column("external_key", sa.String(160), nullable=False, comment="跨来源稳定身份键"),
        sa.Column("source_system", sa.String(32), nullable=False, server_default="okki", comment="来源系统"),
        sa.Column("source_customer_id", sa.String(64), nullable=True, comment="来源客户ID，不建立跨库外键"),
        sa.Column("linked_company_id", sa.BigInteger(), nullable=True, comment="识别出官网后关联的智能获客公司ID"),
        sa.Column("display_name", sa.String(255), nullable=False, comment="客户或公司显示名称"),
        sa.Column("country", sa.String(128), nullable=True, comment="国家或地区"),
        sa.Column("primary_email", sa.String(320), nullable=True, comment="来源主邮箱"),
        sa.Column("email_domain_type", sa.String(16), nullable=False, server_default="unknown", comment="corporate/free/unknown"),
        sa.Column("primary_phone", sa.String(64), nullable=True, comment="来源主电话或WhatsApp"),
        sa.Column("website", sa.String(512), nullable=True, comment="来源或核验后的官网"),
        sa.Column("seed_tier", sa.String(16), nullable=False, comment="初筛档位 T1/T2/T3"),
        sa.Column("eligibility_status", sa.String(16), nullable=False, server_default="eligible", comment="eligible/cooldown/blocked"),
        sa.Column("completeness_score", sa.Float(), nullable=False, server_default="0", comment="来源信息完整度0-100"),
        sa.Column("order_count", sa.Integer(), nullable=False, server_default="0", comment="历史有效订单数"),
        sa.Column("order_amount_usd", sa.DECIMAL(15, 2), nullable=False, server_default="0", comment="历史订单金额USD"),
        sa.Column("last_order_at", sa.DateTime(), nullable=True, comment="最近历史订单日期"),
        sa.Column("contact_snapshot", sa.JSON(), nullable=False, comment="来源联系人摘要"),
        sa.Column("source_snapshot", sa.JSON(), nullable=False, comment="只读业务库来源快照"),
        sa.Column("source_snapshot_hash", sa.String(64), nullable=False, comment="来源快照SHA-256"),
        sa.Column("last_selected_at", sa.DateTime(), nullable=True, comment="最近进入研究批次时间"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["linked_company_id"], ["ark_sales_companies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_key", name="uq_sales_subject_external_key"),
        sa.UniqueConstraint("source_system", "source_customer_id", name="uq_sales_subject_source_customer"),
        comment="智能获客-统一研究主体",
    )
    op.create_index("idx_sales_subject_tier_selected", "ark_sales_research_subjects", ["seed_tier", "eligibility_status", "last_selected_at"])
    op.create_index("idx_sales_subject_linked_company", "ark_sales_research_subjects", ["linked_company_id"])

    op.create_table(
        "ark_sales_public_pool_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("batch_date", sa.Date(), nullable=False, comment="批次业务日期"),
        sa.Column("policy_version", sa.String(32), nullable=False, server_default="v1", comment="抽样策略版本"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", comment="pending/running/completed/failed"),
        sa.Column("quota_per_tier", sa.Integer(), nullable=False, server_default="20", comment="每档目标客户数"),
        sa.Column("quotas", sa.JSON(), nullable=False, comment="各档目标配额"),
        sa.Column("audit_snapshot", sa.JSON(), nullable=False, comment="生成时公海数据审计快照"),
        sa.Column("result_counts", sa.JSON(), nullable=False, comment="各档实际选取与任务状态统计"),
        sa.Column("idempotency_key", sa.String(96), nullable=False, comment="批次生成幂等键"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="生成开始时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="生成完成时间"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="生成失败原因"),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_sales_pool_batch_idem"),
        comment="智能获客-公海每日研究批次",
    )
    op.create_index("idx_sales_pool_batch_date_status", "ark_sales_public_pool_batches", ["batch_date", "status"])

    op.create_table(
        "ark_sales_public_pool_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("batch_id", sa.BigInteger(), nullable=False, comment="所属批次ID"),
        sa.Column("subject_id", sa.BigInteger(), nullable=False, comment="研究主体ID"),
        sa.Column("tier", sa.String(16), nullable=False, comment="抽样档位 T1/T2/T3"),
        sa.Column("selection_rank", sa.Integer(), nullable=False, comment="档位内抽样顺序"),
        sa.Column("selection_reason", sa.JSON(), nullable=False, comment="入选原因"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", comment="pending/running/completed/failed/skipped"),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="pending", comment="pending/approved/rejected"),
        sa.Column("claimed_by", sa.String(128), nullable=True, comment="Agent标识"),
        sa.Column("lease_token_hash", sa.String(64), nullable=True, comment="Agent租约令牌SHA-256"),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True, comment="租约过期时间"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0", comment="执行次数"),
        sa.Column("research_summary", sa.Text(), nullable=True, comment="本轮研究摘要"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="完成时间"),
        sa.Column("reviewed_by", USER_ID, nullable=True, comment="审核业务员用户ID"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True, comment="审核时间"),
        sa.Column("opportunity_id", sa.BigInteger(), nullable=True, comment="确认后生成的客户机会ID"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["batch_id"], ["ark_sales_public_pool_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["ark_sales_research_subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["ark_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["ark_customer_opportunities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "subject_id", name="uq_sales_pool_task_batch_subject"),
        comment="智能获客-公海客户研究任务",
    )
    op.create_index("idx_sales_pool_task_claim", "ark_sales_public_pool_tasks", ["status", "lease_expires_at", "created_at"])
    op.create_index("idx_sales_pool_task_review", "ark_sales_public_pool_tasks", ["review_status", "tier", "finished_at"])

    op.create_table(
        "ark_sales_deal_assessments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("task_id", sa.BigInteger(), nullable=False, comment="公海研究任务ID"),
        sa.Column("subject_id", sa.BigInteger(), nullable=False, comment="研究主体ID"),
        sa.Column("grade", sa.String(4), nullable=False, comment="成交优先级 A/B/C/D"),
        sa.Column("deal_likelihood", sa.String(16), nullable=False, comment="high/medium/low"),
        sa.Column("evidence_confidence", sa.String(16), nullable=False, comment="high/medium/low"),
        sa.Column("identity_decision", sa.String(24), nullable=False, comment="confirmed/candidate/unverifiable/rejected"),
        sa.Column("business_quality_score", sa.Float(), nullable=False, server_default="0", comment="业务质量分0-100"),
        sa.Column("deal_score", sa.Float(), nullable=False, server_default="0", comment="成交可能性分0-100"),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0", comment="结合证据置信度后的排序分"),
        sa.Column("score_factors", sa.JSON(), nullable=False, comment="确定性评分维度及理由"),
        sa.Column("supplier_status", sa.String(32), nullable=False, server_default="unknown", comment="unknown/stable/looking/switching"),
        sa.Column("pain_points", sa.JSON(), nullable=False, comment="已证实或待核验痛点"),
        sa.Column("product_fit", sa.JSON(), nullable=False, comment="产品匹配点"),
        sa.Column("recommended_strategy", sa.Text(), nullable=False, comment="建议跟进策略"),
        sa.Column("outreach_type", sa.String(32), nullable=False, comment="reactivation/new_development/intent_probe"),
        sa.Column("opening_message_en", sa.Text(), nullable=True, comment="供人工审核的英文开场草稿"),
        sa.Column("risks", sa.JSON(), nullable=False, comment="风险与待核验项"),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False, comment="研判使用的证据引用快照"),
        sa.Column("provider", sa.String(64), nullable=False, server_default="agent", comment="研判执行方"),
        sa.Column("model", sa.String(128), nullable=True, comment="模型快照"),
        sa.Column("assessment_version", sa.String(32), nullable=False, server_default="v1", comment="评分规则版本"),
        sa.Column("completed_at", sa.DateTime(), nullable=False, comment="研判完成时间"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["task_id"], ["ark_sales_public_pool_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["ark_sales_research_subjects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_sales_assessment_task"),
        comment="智能获客-成交可能性研判",
    )
    op.create_index("idx_sales_assessment_priority", "ark_sales_deal_assessments", ["grade", "priority_score", "completed_at"])
    op.create_index("idx_sales_assessment_subject", "ark_sales_deal_assessments", ["subject_id", "completed_at"])

    op.add_column("ark_sales_contacts", sa.Column("subject_id", sa.BigInteger(), nullable=True, comment="统一研究主体ID"))
    op.alter_column("ark_sales_contacts", "company_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_foreign_key("fk_sales_contact_subject", "ark_sales_contacts", "ark_sales_research_subjects", ["subject_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_sales_contact_subject_identity", "ark_sales_contacts", ["subject_id", "identity_key"])

    op.add_column("ark_sales_research_runs", sa.Column("subject_id", sa.BigInteger(), nullable=True, comment="统一研究主体ID"))
    op.alter_column("ark_sales_research_runs", "company_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_foreign_key("fk_sales_research_subject", "ark_sales_research_runs", "ark_sales_research_subjects", ["subject_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_sales_research_subject_idem", "ark_sales_research_runs", ["subject_id", "idempotency_key"])


def downgrade():
    op.drop_constraint("uq_sales_research_subject_idem", "ark_sales_research_runs", type_="unique")
    op.drop_constraint("fk_sales_research_subject", "ark_sales_research_runs", type_="foreignkey")
    op.execute("DELETE FROM ark_sales_research_runs WHERE company_id IS NULL")
    op.drop_column("ark_sales_research_runs", "subject_id")
    op.alter_column("ark_sales_research_runs", "company_id", existing_type=sa.BigInteger(), nullable=False)

    op.drop_constraint("uq_sales_contact_subject_identity", "ark_sales_contacts", type_="unique")
    op.drop_constraint("fk_sales_contact_subject", "ark_sales_contacts", type_="foreignkey")
    op.execute("DELETE FROM ark_sales_contacts WHERE company_id IS NULL")
    op.drop_column("ark_sales_contacts", "subject_id")
    op.alter_column("ark_sales_contacts", "company_id", existing_type=sa.BigInteger(), nullable=False)

    op.drop_index("idx_sales_assessment_subject", table_name="ark_sales_deal_assessments")
    op.drop_index("idx_sales_assessment_priority", table_name="ark_sales_deal_assessments")
    op.drop_table("ark_sales_deal_assessments")
    op.drop_index("idx_sales_pool_task_review", table_name="ark_sales_public_pool_tasks")
    op.drop_index("idx_sales_pool_task_claim", table_name="ark_sales_public_pool_tasks")
    op.drop_table("ark_sales_public_pool_tasks")
    op.drop_index("idx_sales_pool_batch_date_status", table_name="ark_sales_public_pool_batches")
    op.drop_table("ark_sales_public_pool_batches")
    op.drop_index("idx_sales_subject_linked_company", table_name="ark_sales_research_subjects")
    op.drop_index("idx_sales_subject_tier_selected", table_name="ark_sales_research_subjects")
    op.drop_table("ark_sales_research_subjects")
