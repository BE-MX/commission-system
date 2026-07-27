"""expo 效果图记录出图档位（精致大片 high / 形象速览 medium）

Revision ID: 083_expo_result_quality
Revises: 082_domestic_report_idem
Create Date: 2026-07-27

客户在甄选页自选出图档位，选择随 result 落库而不是只做运行时参数——重试要复现同一档，
排障时也要能回答「这张为什么慢/为什么糙」。nullable：老数据与未指定时回落 preset 配置，
迁移后老代码照常写入（不碰该列）即可，满足「老代码 + 新 schema」过渡期要求。
"""

import sqlalchemy as sa
from alembic import op

revision = "083_expo_result_quality"
down_revision = "082_domestic_report_idem"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ark_expo_results",
        sa.Column(
            "quality", sa.String(16), nullable=True,
            comment="出图档位 high=精致大片 / medium=形象速览；空=用 preset 默认",
        ),
    )


def downgrade():
    op.drop_column("ark_expo_results", "quality")
