"""add gated public pool research output

Revision ID: 113_public_pool_research_v2
Revises: 112_knowledge_editor_ai
"""

from alembic import op
import sqlalchemy as sa


revision = "113_public_pool_research_v2"
down_revision = "112_knowledge_editor_ai"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_sales_public_pool_tasks", sa.Column(
        "gate_status", sa.String(length=16), nullable=False,
        server_default="pending", comment="pending/passed/stopped",
    ))
    op.add_column("ark_sales_public_pool_tasks", sa.Column(
        "gate_snapshot", sa.JSON(), nullable=True, comment="行业门控提交、哈希与深入背调授权",
    ))
    op.add_column("ark_sales_deal_assessments", sa.Column(
        "industry_relevance", sa.String(length=16), nullable=False,
        server_default="uncertain", comment="core/adjacent/uncertain/irrelevant",
    ))
    op.add_column("ark_sales_deal_assessments", sa.Column(
        "industry_relevance_reason", sa.String(length=2000), nullable=False,
        server_default="", comment="行业门控结论与依据",
    ))
    op.add_column("ark_sales_deal_assessments", sa.Column(
        "research_depth", sa.String(length=16), nullable=False,
        server_default="focused", comment="gate_only/focused/deep",
    ))
    op.add_column("ark_sales_deal_assessments", sa.Column(
        "stop_reason", sa.Text(), nullable=True, comment="提前停止深挖原因",
    ))
    op.add_column("ark_sales_deal_assessments", sa.Column(
        "social_profiles", sa.JSON(), nullable=True, comment="社媒账号、活跃度与业务信号",
    ))
    op.add_column("ark_sales_deal_assessments", sa.Column(
        "knowledge_references", sa.JSON(), nullable=True, comment="企业知识库文档版本引用",
    ))
    op.add_column("ark_sales_deal_assessments", sa.Column(
        "commercial_profile", sa.JSON(), nullable=True, comment="客户类型、采购阶段、体量和成交信号",
    ))
def downgrade():
    op.drop_column("ark_sales_deal_assessments", "commercial_profile")
    op.drop_column("ark_sales_deal_assessments", "knowledge_references")
    op.drop_column("ark_sales_deal_assessments", "social_profiles")
    op.drop_column("ark_sales_deal_assessments", "stop_reason")
    op.drop_column("ark_sales_deal_assessments", "research_depth")
    op.drop_column("ark_sales_deal_assessments", "industry_relevance_reason")
    op.drop_column("ark_sales_deal_assessments", "industry_relevance")
    op.drop_column("ark_sales_public_pool_tasks", "gate_snapshot")
    op.drop_column("ark_sales_public_pool_tasks", "gate_status")
