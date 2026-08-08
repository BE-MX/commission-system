"""智能获客：目标模型、搜索任务、公司、联系人与研究证据

Revision ID: 099_sales_automation
Revises: 098_salary_leave_source
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "099_sales_automation"
down_revision = "098_salary_leave_source"
branch_labels = None
depends_on = None

_UID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def _audit_columns():
    return [
        sa.Column("created_by", _UID, nullable=True, comment="创建人用户ID"),
        sa.Column("updated_by", _UID, nullable=True, comment="最后更新人用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
    ]


def upgrade() -> None:
    op.create_table(
        "ark_sales_target_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("profile_key", sa.String(64), nullable=False, comment="画像业务键"),
        sa.Column("company_name", sa.String(255), nullable=False, comment="本公司名称"),
        sa.Column("company_website", sa.String(512), nullable=True, comment="本公司官网"),
        sa.Column("products", sa.JSON(), nullable=False, comment="产品能力列表"),
        sa.Column("advantages", sa.JSON(), nullable=False, comment="竞争优势列表"),
        sa.Column("target_countries", sa.JSON(), nullable=False, comment="目标国家列表"),
        sa.Column("target_industries", sa.JSON(), nullable=False, comment="目标行业列表"),
        sa.Column("target_roles", sa.JSON(), nullable=False, comment="目标联系人角色列表"),
        sa.Column("exclusions", sa.JSON(), nullable=False, comment="排除条件列表"),
        sa.Column("default_language", sa.String(16), nullable=False, comment="默认开发语言"),
        sa.Column("status", sa.String(16), nullable=False, comment="画像状态 active/inactive"),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_key", name="uq_ark_sales_target_profiles_profile_key"),
        comment="智能获客-目标客户模型",
    )
    op.create_index("idx_sales_profile_status", "ark_sales_target_profiles", ["status"])

    op.create_table(
        "ark_sales_search_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("profile_id", sa.BigInteger(), nullable=False, comment="目标客户模型ID"),
        sa.Column("name", sa.String(255), nullable=False, comment="搜索任务名称"),
        sa.Column("status", sa.String(16), nullable=False, comment="pending/running/completed/failed"),
        sa.Column("adapter", sa.String(64), nullable=False, comment="搜索适配器"),
        sa.Column("target_count", sa.Integer(), nullable=False, comment="目标公司数量"),
        sa.Column("criteria", sa.JSON(), nullable=False, comment="用户补充搜索条件"),
        sa.Column("profile_snapshot", sa.JSON(), nullable=False, comment="创建任务时画像快照"),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="创建任务幂等键"),
        sa.Column("ingestion_receipts", sa.JSON(), nullable=False, comment="Agent批次幂等回执"),
        sa.Column("result_count", sa.Integer(), nullable=False, comment="原始候选数"),
        sa.Column("created_count", sa.Integer(), nullable=False, comment="新建公司数"),
        sa.Column("deduplicated_count", sa.Integer(), nullable=False, comment="去重公司数"),
        sa.Column("error_code", sa.String(64), nullable=True, comment="失败代码"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="可行动失败原因"),
        sa.Column("claimed_by", sa.String(128), nullable=True, comment="Agent标识"),
        sa.Column("lease_token_hash", sa.String(64), nullable=True, comment="Agent租约令牌SHA-256"),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True, comment="租约过期时间"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, comment="执行次数"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="完成时间"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["profile_id"], ["ark_sales_target_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_ark_sales_search_jobs_idempotency_key"),
        comment="智能获客-Agent搜索任务",
    )
    op.create_index(
        "idx_sales_job_claim", "ark_sales_search_jobs", ["status", "lease_expires_at", "created_at"]
    )

    op.create_table(
        "ark_sales_companies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("normalized_domain", sa.String(253), nullable=False, comment="归一化官网域名"),
        sa.Column("name", sa.String(255), nullable=False, comment="公司名称"),
        sa.Column("website", sa.String(512), nullable=False, comment="公司官网"),
        sa.Column("country", sa.String(128), nullable=True, comment="国家或地区"),
        sa.Column("industry", sa.String(255), nullable=True, comment="行业"),
        sa.Column("description", sa.Text(), nullable=True, comment="公司简介"),
        sa.Column("status", sa.String(16), nullable=False, comment="candidate/approved/rejected"),
        sa.Column("match_score", sa.Float(), nullable=False, comment="目标画像匹配分0-100"),
        sa.Column("score_reasons", sa.JSON(), nullable=False, comment="可解释评分理由"),
        sa.Column("owner_user_id", _UID, nullable=True, comment="确认后的负责人用户ID"),
        sa.Column("approved_at", sa.DateTime(), nullable=True, comment="确认进入客户池时间"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_domain", name="uq_ark_sales_companies_normalized_domain"),
        comment="智能获客-候选公司主档",
    )
    op.create_index("idx_sales_company_status_score", "ark_sales_companies", ["status", "match_score"])

    op.create_table(
        "ark_sales_search_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("job_id", sa.BigInteger(), nullable=False, comment="搜索任务ID"),
        sa.Column("company_id", sa.BigInteger(), nullable=False, comment="候选公司ID"),
        sa.Column("request_key", sa.String(64), nullable=False, comment="Agent提交批次键"),
        sa.Column("source_provider", sa.String(64), nullable=False, comment="来源适配器"),
        sa.Column("source_url", sa.String(1024), nullable=False, comment="发现证据URL"),
        sa.Column("captured_at", sa.DateTime(), nullable=False, comment="来源采集时间"),
        sa.Column("raw_payload", sa.JSON(), nullable=True, comment="原始候选数据快照"),
        sa.Column("rank", sa.Integer(), nullable=True, comment="在本次搜索中的排名"),
        sa.Column("score", sa.Float(), nullable=False, comment="本次搜索匹配分"),
        sa.Column("status", sa.String(16), nullable=False, comment="结果状态 active/ignored"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["job_id"], ["ark_sales_search_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["ark_sales_companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "company_id", name="uq_sales_result_job_company"),
        comment="智能获客-搜索任务结果与来源快照",
    )
    op.create_index("idx_sales_result_job_rank", "ark_sales_search_results", ["job_id", "rank"])
    op.create_index("idx_sales_result_company_created", "ark_sales_search_results", ["company_id", "created_at"])

    op.create_table(
        "ark_sales_contacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("company_id", sa.BigInteger(), nullable=False, comment="候选公司ID"),
        sa.Column("identity_key", sa.String(64), nullable=False, comment="公司范围内联系人身份哈希"),
        sa.Column("name", sa.String(255), nullable=True, comment="联系人姓名"),
        sa.Column("role", sa.String(255), nullable=True, comment="联系人职位"),
        sa.Column("email", sa.String(320), nullable=True, comment="原始邮箱"),
        sa.Column("email_normalized", sa.String(320), nullable=True, comment="归一化邮箱"),
        sa.Column("email_status", sa.String(16), nullable=False, comment="unknown/valid/risky/invalid"),
        sa.Column("verified_at", sa.DateTime(), nullable=True, comment="邮箱验证时间"),
        sa.Column("source_provider", sa.String(64), nullable=False, comment="来源适配器"),
        sa.Column("source_url", sa.String(1024), nullable=False, comment="联系人证据URL"),
        sa.Column("captured_at", sa.DateTime(), nullable=False, comment="来源采集时间"),
        sa.Column("confidence", sa.Float(), nullable=True, comment="来源置信度0-1"),
        sa.Column("status", sa.String(16), nullable=False, comment="联系人状态 active/inactive"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["ark_sales_companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "identity_key", name="uq_sales_contact_identity"),
        comment="智能获客-联系人与邮箱验证",
    )
    op.create_index("idx_sales_contact_company_status", "ark_sales_contacts", ["company_id", "status"])
    op.create_index("idx_sales_contact_email", "ark_sales_contacts", ["email_normalized"])

    op.create_table(
        "ark_sales_research_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("company_id", sa.BigInteger(), nullable=False, comment="候选公司ID"),
        sa.Column("status", sa.String(16), nullable=False, comment="pending/running/completed/failed"),
        sa.Column("summary", sa.Text(), nullable=True, comment="企业研究摘要"),
        sa.Column("outreach_angles", sa.JSON(), nullable=False, comment="建议触达角度"),
        sa.Column("risks", sa.JSON(), nullable=False, comment="风险与待核验项"),
        sa.Column("provider", sa.String(64), nullable=False, comment="研究执行方"),
        sa.Column("model", sa.String(128), nullable=True, comment="模型快照"),
        sa.Column("idempotency_key", sa.String(64), nullable=True, comment="公司范围内研究幂等键"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="完成时间"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["company_id"], ["ark_sales_companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_sales_research_company_idem"),
        comment="智能获客-Agent企业研究执行",
    )
    op.create_index("idx_sales_research_company_status", "ark_sales_research_runs", ["company_id", "status", "created_at"])

    op.create_table(
        "ark_sales_research_facts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("run_id", sa.BigInteger(), nullable=False, comment="研究执行ID"),
        sa.Column("fact_type", sa.String(64), nullable=False, comment="事实类型"),
        sa.Column("claim", sa.Text(), nullable=False, comment="结构化事实陈述"),
        sa.Column("fact_hash", sa.String(64), nullable=False, comment="事实内容哈希"),
        sa.Column("source_url", sa.String(1024), nullable=False, comment="事实来源URL"),
        sa.Column("source_url_hash", sa.String(64), nullable=False, comment="来源URL哈希"),
        sa.Column("captured_at", sa.DateTime(), nullable=False, comment="来源采集时间"),
        sa.Column("confidence", sa.Float(), nullable=False, comment="置信度0-1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, comment="展示顺序"),
        sa.Column("status", sa.String(16), nullable=False, comment="事实状态 active/disputed"),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["run_id"], ["ark_sales_research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "fact_hash", "source_url_hash", name="uq_sales_fact_source"),
        comment="智能获客-可追溯企业研究事实",
    )
    op.create_index("idx_sales_fact_run_sort", "ark_sales_research_facts", ["run_id", "sort_order"])


def downgrade() -> None:
    op.drop_index("idx_sales_fact_run_sort", table_name="ark_sales_research_facts")
    op.drop_table("ark_sales_research_facts")
    op.drop_index("idx_sales_research_company_status", table_name="ark_sales_research_runs")
    op.drop_table("ark_sales_research_runs")
    op.drop_index("idx_sales_contact_email", table_name="ark_sales_contacts")
    op.drop_index("idx_sales_contact_company_status", table_name="ark_sales_contacts")
    op.drop_table("ark_sales_contacts")
    op.drop_index("idx_sales_result_company_created", table_name="ark_sales_search_results")
    op.drop_index("idx_sales_result_job_rank", table_name="ark_sales_search_results")
    op.drop_table("ark_sales_search_results")
    op.drop_index("idx_sales_company_status_score", table_name="ark_sales_companies")
    op.drop_table("ark_sales_companies")
    op.drop_index("idx_sales_job_claim", table_name="ark_sales_search_jobs")
    op.drop_table("ark_sales_search_jobs")
    op.drop_index("idx_sales_profile_status", table_name="ark_sales_target_profiles")
    op.drop_table("ark_sales_target_profiles")
