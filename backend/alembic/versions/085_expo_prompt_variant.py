"""expo 效果图记录合成版本（真实/柔光/美颜）

Revision ID: 085_expo_prompt_variant
Revises: 084_festival_events
Create Date: 2026-08-01

客户在甄选页必选一个合成版本，三版差别在「修不修皮肤」：真实=只打光不动皮肤纹理，
柔光=更柔的光与更亮的暗部，美颜=真磨皮提亮。选择随 result 落库而不是只做运行时参数——
合成在后台线程里读这一行跑，运行时参数根本传不到；且「客户当时选的哪版」是排障与复现
（同一张为什么长这样）的唯一依据。

nullable + 无默认值：老数据与老代码（不写该列）继续可用，满足「老代码 + 新 schema」
过渡期要求；读取侧对空值回落到默认版本，不依赖数据库默认值。
"""

import sqlalchemy as sa
from alembic import op

revision = "085_expo_prompt_variant"
down_revision = "084_festival_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ark_expo_results",
        sa.Column(
            "prompt_variant", sa.String(16), nullable=True,
            comment="合成版本 real=真实 / soft=柔光 / beauty=美颜；空=回落默认版",
        ),
    )


def downgrade():
    op.drop_column("ark_expo_results", "prompt_variant")
