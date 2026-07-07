"""expo try-on: hair color params + scene composite mode

Revision ID: 047_expo_color_scene
Revises: 046_perm_metadata
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa


revision = "047_expo_color_scene"
down_revision = "046_perm_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 会话双入口：tryon=AI 换发试戴 / scene=佩戴实拍生成场景效果图
    op.add_column(
        "ark_expo_sessions",
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="tryon"),
    )
    # scene 模式的效果图没有关联发型 → wig_id 放开为可空
    op.alter_column(
        "ark_expo_results", "wig_id",
        existing_type=sa.BigInteger(), nullable=True,
    )
    # 生成时选定的发色快照（palette_id/code/name/hex/undertone/lab），与色板库解耦
    op.add_column("ark_expo_results", sa.Column("hair_color_json", sa.JSON(), nullable=True))
    # scene 模式的场景快照（key/label）
    op.add_column("ark_expo_results", sa.Column("scene_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    # 注意：已存在 scene 结果（wig_id 为 NULL）时，末步改回 NOT NULL 会失败，
    # 需先清理 scene 数据；且 JSON 列先 drop，半途失败快照不可恢复（MySQL DDL 不可回滚）
    op.drop_column("ark_expo_results", "scene_json")
    op.drop_column("ark_expo_results", "hair_color_json")
    op.alter_column(
        "ark_expo_results", "wig_id",
        existing_type=sa.BigInteger(), nullable=False,
    )
    op.drop_column("ark_expo_sessions", "mode")
