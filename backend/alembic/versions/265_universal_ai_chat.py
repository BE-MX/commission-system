"""General chat selection, answer identity and private session deletion.

Revision ID: 265_universal_ai_chat
Revises: 264_private_research_tools
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "265_universal_ai_chat"
down_revision = "264_private_research_tools"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "mysql":
        op.alter_column("ark_ai_chat_messages", "content", existing_type=sa.Text(),
                        type_=mysql.MEDIUMTEXT(), existing_nullable=False,
                        existing_comment="Markdown 消息正文")
    op.add_column("ark_ai_chat_sessions", sa.Column("selected_preset_id", sa.Integer(), nullable=True, comment="最近选择的聊天预设编号"))
    op.add_column("ark_ai_chat_sessions", sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="用户删除会话的北京时间"))
    op.add_column("ark_ai_chat_messages", sa.Column("model_snapshot", sa.JSON(), nullable=True, comment="本轮获授权的模型与配置版本快照"))
    op.add_column("ark_ai_chat_messages", sa.Column("reasoning_content", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True, comment="供应商返回的推理内容，不进入历史提示词"))


def downgrade():
    raise RuntimeError("Chat history metadata must be preserved; use a reviewed forward migration")
