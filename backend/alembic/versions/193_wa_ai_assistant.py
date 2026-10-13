"""Private range summaries and checklist; expand only, preserving prior data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '193_wa_ai_assistant'
down_revision = '192_wa_sync_fencing'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ark_whatsapp_assistant_runs',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True, comment='运行记录ID'),
        sa.Column('run_uid', sa.String(64), nullable=False, unique=True, comment='分析运行唯一标识'),
        sa.Column('account_uid', sa.String(80), sa.ForeignKey('ark_whatsapp_accounts.account_uid'), nullable=False, comment='来源账号唯一标识'),
        sa.Column('requested_by', mysql.INTEGER(unsigned=True), sa.ForeignKey('ark_users.id'), nullable=False, comment='请求人方舟用户ID'),
        sa.Column('client_request_uid', sa.String(64), nullable=False, comment='客户端幂等请求标识'),
        sa.Column('conversation_uid', sa.String(120), nullable=True, comment='单会话范围，空值表示整个账号'),
        sa.Column('start_at', sa.DateTime(), nullable=False, comment='包含的开始北京时间'),
        sa.Column('end_at', sa.DateTime(), nullable=False, comment='包含的结束北京时间'),
        sa.Column('status', sa.String(20), nullable=False, comment='运行状态及失效标记'),
        sa.Column('active_slot', sa.Integer(), nullable=True, comment='在途唯一占位，终态为空'),
        sa.Column('session_generation', sa.Integer(), nullable=False, comment='接纳时账号代次'),
        sa.Column('consent_version', sa.Integer(), nullable=False, comment='接纳时授权版本'),
        sa.Column('message_count', sa.Integer(), nullable=False, comment='范围内完整消息数'),
        sa.Column('conversation_count', sa.Integer(), nullable=False, comment='范围内聊天对象数'),
        sa.Column('processed_conversations', sa.Integer(), nullable=False, comment='已处理对象数'),
        sa.Column('input_manifest', sa.JSON(), nullable=False, comment='输入哈希和知识引用元数据，不复制聊天正文'),
        sa.Column('result_json', sa.JSON(), nullable=True, comment='当前有效逐对象摘要建议及清单'),
        sa.Column('task_state', sa.JSON(), nullable=False, comment='报告内跟进项勾选状态'),
        sa.Column('warnings_json', sa.JSON(), nullable=False, comment='覆盖缺口及知识不足提示'),
        sa.Column('error_code', sa.String(64), nullable=True, comment='失败或失效分类'),
        sa.Column('error_message', sa.String(240), nullable=True, comment='不包含原始聊天的处理提示'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建北京时间'),
        sa.Column('started_at', sa.DateTime(), nullable=True, comment='开始北京时间'),
        sa.Column('finished_at', sa.DateTime(), nullable=True, comment='结束北京时间'),
        sa.UniqueConstraint('requested_by', 'client_request_uid', name='uk_wa_assistant_request'),
        sa.UniqueConstraint('account_uid', 'requested_by', 'active_slot', name='uk_wa_assistant_active'),
        comment='私有WhatsApp时间段分析与内部跟进清单')
    op.create_index('idx_wa_assistant_owner_account', 'ark_whatsapp_assistant_runs', ['requested_by', 'account_uid', 'created_at'])


def downgrade():
    raise RuntimeError('Assistant reports are business records; roll back code without deleting results')
