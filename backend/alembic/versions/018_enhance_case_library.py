"""enhance case library with SKILL-based fields and user corrections

Revision ID: 018_enhance_case_library
Revises: 017
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018_enhance_case_library"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 基本信息扩展
    op.add_column("ark_case_library", sa.Column("customer_country", sa.String(50), nullable=True, comment="客户国家"))
    op.add_column("ark_case_library", sa.Column("communication_channel", sa.String(50), nullable=True, comment="沟通渠道"))
    op.add_column("ark_case_library", sa.Column("communication_period", sa.String(100), nullable=True, comment="沟通时段"))
    op.add_column("ark_case_library", sa.Column("total_rounds", sa.SmallInteger, nullable=True, comment="总回合数"))
    op.add_column("ark_case_library", sa.Column("final_result", sa.String(50), nullable=True, comment="最终结果(成交/未成交/谈判中/流失)"))
    op.add_column("ark_case_library", sa.Column("background_check_status", sa.String(50), nullable=True, comment="背调状态"))

    # 2. 结构化分析数据(JSON)
    op.add_column("ark_case_library", sa.Column("rounds_analysis", sa.JSON, nullable=True, comment="回合拆解(R1/R2...)"))
    op.add_column("ark_case_library", sa.Column("dimension_scores", sa.JSON, nullable=True, comment="六维度评分"))
    op.add_column("ark_case_library", sa.Column("golden_phrases", sa.JSON, nullable=True, comment="亮点话术"))
    op.add_column("ark_case_library", sa.Column("red_flags", sa.JSON, nullable=True, comment="问题话术"))
    op.add_column("ark_case_library", sa.Column("core_strengths", sa.JSON, nullable=True, comment="核心亮点"))
    op.add_column("ark_case_library", sa.Column("result_analysis", sa.JSON, nullable=True, comment="结果归因"))
    op.add_column("ark_case_library", sa.Column("improvements", sa.JSON, nullable=True, comment="不足与优化方向"))
    op.add_column("ark_case_library", sa.Column("next_actions", sa.JSON, nullable=True, comment="下一步行动清单"))

    # 3. AI 原始输出快照 & 用户评价修正
    op.add_column("ark_case_library", sa.Column("ai_draft", sa.JSON, nullable=True, comment="AI 原始完整输出快照"))
    op.add_column("ark_case_library", sa.Column("user_corrections", sa.JSON, nullable=True, comment="用户评价修正,字段名→修正内容"))

    # 4. 索引
    op.create_index("idx_case_channel", "ark_case_library", ["communication_channel"])
    op.create_index("idx_case_result", "ark_case_library", ["final_result"])


def downgrade() -> None:
    op.drop_index("idx_case_result", table_name="ark_case_library")
    op.drop_index("idx_case_channel", table_name="ark_case_library")

    for col in [
        "customer_country", "communication_channel", "communication_period",
        "total_rounds", "final_result", "background_check_status",
        "rounds_analysis", "dimension_scores", "golden_phrases", "red_flags",
        "core_strengths", "result_analysis", "improvements", "next_actions",
        "ai_draft", "user_corrections",
    ]:
        op.drop_column("ark_case_library", col)
