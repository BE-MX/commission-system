"""Announcement library binding, publication outbox and weekly reports."""
from alembic import op
import sqlalchemy as sa

revision = '155_announcements'
down_revision = '154_okki_outbound_tasks'
branch_labels = None
depends_on = None

def _schemas():
    return {
        'ark_announcement_config': [
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True, autoincrement='auto', comment='主键'),
            sa.Column('library_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_libraries.id'), nullable=False, unique=True, comment='公告知识库ID'),
            sa.Column('group_name', sa.String(length=120), nullable=False, comment='公告群名称'),
            sa.Column('conversation_id', sa.String(length=256), nullable=False, comment='钉钉群会话ID'),
            sa.Column('robot_code', sa.String(length=128), nullable=False, comment='应用机器人编码'),
            sa.Column('delivery_enabled', sa.Boolean(), nullable=False, comment='自动推送开关'),
            sa.Column('channel_verified', sa.Boolean(), nullable=False, comment='图文通道已验证'),
            sa.Column('weekly_enabled', sa.Boolean(), nullable=False, comment='每周汇总开关'),
            sa.Column('weekly_hour', sa.Integer(), nullable=False, comment='周一北京时间小时'),
            sa.Column('weekly_minute', sa.Integer(), nullable=False, comment='周一北京时间分钟'),
            sa.Column('preset_name', sa.String(length=100), nullable=False, comment='周报AI方案名称'),
            sa.Column('executor_id', sa.Integer(), nullable=False, comment='后台执行方舟用户ID'),
            sa.Column('version', sa.Integer(), nullable=False, comment='配置版本'),
            sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        ],
        'ark_announcement_items': [
            sa.Column('document_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_documents.id'), nullable=False, primary_key=True, autoincrement='auto', comment='公告知识文档ID'),
            sa.Column('pinned', sa.Boolean(), nullable=False, comment='是否置顶'),
            sa.Column('withdrawn_at', sa.DateTime(), nullable=True, comment='撤回时间'),
            sa.Column('withdrawal_reason', sa.String(length=500), nullable=True, comment='撤回原因'),
            sa.Column('published_at', sa.DateTime(), nullable=True, comment='最后发布时间'),
            sa.Column('published_by', sa.Integer(), nullable=True, comment='最后发布人ID'),
        ],
        'ark_announcement_revision_meta': [
            sa.Column('revision_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_revisions.id'), nullable=False, primary_key=True, autoincrement='auto', comment='知识修订ID'),
            sa.Column('category_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_documents.id'), nullable=False, comment='类别目录ID'),
            sa.Column('category_name', sa.String(length=256), nullable=False, comment='类别名称快照'),
            sa.Column('important', sa.Boolean(), nullable=False, comment='重要标记'),
            sa.Column('effective_at', sa.DateTime(), nullable=True, comment='生效时间'),
            sa.Column('expires_at', sa.DateTime(), nullable=True, comment='截止时间'),
            sa.Column('change_note', sa.String(length=500), nullable=False, comment='更新说明'),
        ],
        'ark_announcement_publications': [
            sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='主键'),
            sa.Column('document_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_documents.id'), nullable=False, comment='公告知识文档ID'),
            sa.Column('revision_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_revisions.id'), nullable=False, comment='知识修订ID'),
            sa.Column('kind', sa.String(length=16), nullable=False, comment='发布事件类型'),
            sa.Column('title', sa.String(length=256), nullable=False, comment='公告标题快照'),
            sa.Column('reason', sa.String(length=500), nullable=True, comment='撤回说明'),
            sa.Column('actor_id', sa.Integer(), nullable=False, comment='操作用户ID'),
            sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
            sa.UniqueConstraint('document_id', 'revision_id', 'kind', name='uq_announcement_publication'),
        ],
        'ark_announcement_weekly': [
            sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='主键'),
            sa.Column('library_id', sa.BigInteger(), sa.ForeignKey('ark_knowledge_libraries.id'), nullable=False, comment='公告知识库ID'),
            sa.Column('period_start', sa.DateTime(), nullable=False, comment='统计区间起点（北京时间）'),
            sa.Column('period_end', sa.DateTime(), nullable=False, comment='统计区间终点（不含）'),
            sa.Column('status', sa.String(length=24), nullable=False, comment='处理状态'),
            sa.Column('sources', sa.JSON(), nullable=False, comment='冻结来源及版本'),
            sa.Column('body', sa.Text(), nullable=False, comment='周报正文'),
            sa.Column('error', sa.String(length=200), nullable=True, comment='脱敏处理说明'),
            sa.Column('attempts', sa.Integer(), nullable=False, comment='尝试次数'),
            sa.Column('lease_token', sa.String(length=40), nullable=True, comment='领取租约令牌'),
            sa.Column('lease_until', sa.DateTime(), nullable=True, comment='租约截止时间'),
            sa.Column('config_version', sa.Integer(), nullable=False, comment='配置版本快照'),
            sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
            sa.Column('generation', sa.Integer(), nullable=False, comment='周报版本号'),
            sa.Column('auto_send', sa.Boolean(), nullable=False, comment='完成后自动发送'),
            sa.Column('history', sa.JSON(), nullable=False, comment='历史周报版本'),
            sa.UniqueConstraint('library_id', 'period_start', name='uq_announcement_weekly_period'),
        ],
        'ark_announcement_deliveries': [
            sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='主键'),
            sa.Column('source_key', sa.String(length=80), nullable=False, comment='投递来源唯一业务键'),
            sa.Column('publication_id', sa.BigInteger(), sa.ForeignKey('ark_announcement_publications.id'), nullable=True, comment='发布事件ID'),
            sa.Column('weekly_id', sa.BigInteger(), sa.ForeignKey('ark_announcement_weekly.id'), nullable=True, comment='周报ID'),
            sa.Column('sequence', sa.Integer(), nullable=False, comment='消息序号'),
            sa.Column('target', sa.String(length=256), nullable=False, comment='目标群快照'),
            sa.Column('robot_code', sa.String(length=128), nullable=False, comment='应用机器人编码'),
            sa.Column('config_version', sa.Integer(), nullable=False, comment='配置版本快照'),
            sa.Column('payload', sa.JSON(), nullable=False, comment='冻结消息内容与授权指纹'),
            sa.Column('status', sa.String(length=24), nullable=False, comment='处理状态'),
            sa.Column('attempts', sa.Integer(), nullable=False, comment='尝试次数'),
            sa.Column('next_attempt_at', sa.DateTime(), nullable=False, comment='下次尝试时间'),
            sa.Column('lease_token', sa.String(length=40), nullable=True, comment='领取租约令牌'),
            sa.Column('lease_until', sa.DateTime(), nullable=True, comment='租约截止时间'),
            sa.Column('error', sa.String(length=200), nullable=True, comment='脱敏处理说明'),
            sa.Column('receipt', sa.String(length=256), nullable=True, comment='钉钉接口回执'),
            sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
            sa.Column('sent_at', sa.DateTime(), nullable=True, comment='投递时间'),
            sa.UniqueConstraint('source_key', 'sequence', name='uq_announcement_delivery_part'),
        ],
    }

def upgrade():
    bind = op.get_bind()
    columns = {c['name']: c for c in sa.inspect(bind).get_columns('ark_knowledge_libraries')}
    if 'managed_by' not in columns:
        op.add_column('ark_knowledge_libraries', sa.Column('managed_by', sa.String(32), nullable=True))
    elif not isinstance(columns['managed_by']['type'], sa.String) or columns['managed_by']['type'].length != 32:
        raise RuntimeError('Incompatible knowledge managed_by column')
    for name, schema in _schemas().items():
        inspector = sa.inspect(bind)
        if not inspector.has_table(name):
            op.create_table(name, *schema)
        else:
            actual = {c['name']: c for c in inspector.get_columns(name)}
            for column in (c for c in schema if isinstance(c, sa.Column)):
                existing = actual.get(column.name)
                expected_type = column.type.compile(dialect=bind.dialect).upper()
                actual_type = str(existing['type']).upper() if existing else ''
                compatible = actual_type == expected_type or (isinstance(column.type, sa.Boolean) and actual_type in {'BOOLEAN', 'BOOL', 'TINYINT(1)'})
                if existing is None or existing['nullable'] != column.nullable or not compatible:
                    raise RuntimeError(f'Incompatible announcement column: {name}.{column.name}')
            primary = [c.name for c in schema if isinstance(c, sa.Column) and c.primary_key]
            if inspector.get_pk_constraint(name)['constrained_columns'] != primary:
                raise RuntimeError(f'Incompatible announcement primary key: {name}')
            uniques = {tuple(c['column_names']) for c in inspector.get_unique_constraints(name)}
            expected_uniques = {(c.name,) for c in schema if isinstance(c, sa.Column) and c.unique}
            expected_uniques |= {tuple(c.name for c in constraint.columns) for constraint in schema if isinstance(constraint, sa.UniqueConstraint)}
            # Unbound UniqueConstraints retain their explicit column arguments.
            expected_uniques |= {tuple(constraint._pending_colargs) for constraint in schema if isinstance(constraint, sa.UniqueConstraint)}
            expected_uniques.discard(())
            if not expected_uniques.issubset(uniques):
                raise RuntimeError(f'Missing announcement uniqueness: {name}')
    indexes = {
        'ark_announcement_publications': [('ix_announcement_publication_time', ['created_at'])],
        'ark_announcement_deliveries': [('ix_announcement_delivery_status', ['status'])],
    }
    for table, entries in indexes.items():
        existing = {i['name'] for i in sa.inspect(bind).get_indexes(table)}
        for name, columns in entries:
            if name not in existing:
                op.create_index(name, table, columns)

def downgrade():
    raise RuntimeError('Announcement history must be preserved; use a reviewed forward migration')
