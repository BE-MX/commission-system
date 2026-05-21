"""add intelligence module

Revision ID: 021_add_intelligence_module
Revises: 020_add_asset_module
Create Date: 2026-05-20 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '021_add_intelligence_module'
down_revision: Union[str, None] = '020_add_asset_module'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql')


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── 扩展现有表: ark_insight_sources ─────────────────────
    src_cols = {c['name'] for c in inspector.get_columns('ark_insight_sources')}
    if 'config_json' not in src_cols:
        op.add_column(
            'ark_insight_sources',
            sa.Column('config_json', sa.JSON(), nullable=True, comment='差异化配置(cron,target_accounts,monitor_fields等)'),
        )

    # 扩展 source_type enum (MySQL 需原生 ALTER)
    op.execute(
        "ALTER TABLE ark_insight_sources "
        "MODIFY COLUMN source_type ENUM("
        "'google_alerts_rss','pinterest_scrape','google_trends_rss',"
        "'amazon_bestseller','competitor_rss','competitor_html','aihot_api',"
        "'xpoz','competitor_monitor','perplexity','amazon','manual'"
        ") NOT NULL"
    )

    # ── 扩展现有表: ark_insight_reports ─────────────────────
    report_cols = {c['name'] for c in inspector.get_columns('ark_insight_reports')}
    if 'date_range_start' not in report_cols:
        op.add_column('ark_insight_reports', sa.Column('date_range_start', sa.Date(), nullable=True))
    if 'date_range_end' not in report_cols:
        op.add_column('ark_insight_reports', sa.Column('date_range_end', sa.Date(), nullable=True))
    if 'item_ids' not in report_cols:
        op.add_column('ark_insight_reports', sa.Column('item_ids', sa.JSON(), nullable=True, comment='使用的情报条目ID列表'))
    if 'config_snapshot' not in report_cols:
        op.add_column('ark_insight_reports', sa.Column('config_snapshot', sa.JSON(), nullable=True, comment='生成时配置快照'))
    if 'is_pinned' not in report_cols:
        op.add_column(
            'ark_insight_reports',
            sa.Column('is_pinned', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='0=否,1=置顶'),
        )
    if 'trigger_type' not in report_cols:
        op.add_column(
            'ark_insight_reports',
            sa.Column('trigger_type', sa.String(32), nullable=False, server_default=sa.text("'manual'"), comment='manual/scheduled'),
        )

    # 扩展 report_type enum
    op.execute(
        "ALTER TABLE ark_insight_reports "
        "MODIFY COLUMN report_type ENUM("
        "'industry_daily','ai_tools','shop_analysis','competitor_analysis','inquiry_analysis',"
        "'intelligence_overview'"
        ") NOT NULL"
    )

    # 扩展现有 status enum (ark_insight_reports)
    op.execute(
        "ALTER TABLE ark_insight_reports "
        "MODIFY COLUMN status ENUM('pending','published','failed','generating','completed') NOT NULL DEFAULT 'pending'"
    )

    # ── 新建表: 情报条目 ────────────────────────────────────
    # 注意: FK 引用列用 sa.Integer() 匹配现有表(非 unsigned)
    op.create_table(
        'ark_insight_items',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('ark_insight_sources.id'), nullable=True, comment='来源信源ID'),
        sa.Column('source_type', sa.String(32), nullable=False, comment='信源类型冗余'),
        sa.Column('collected_at', sa.DateTime(), nullable=False, comment='采集时间'),
        sa.Column('published_at', sa.DateTime(), nullable=True, comment='原始发布时间'),
        sa.Column('original_url', sa.Text(), nullable=True, comment='原始链接(溯源用)'),
        sa.Column('title', sa.String(512), nullable=True, comment='标题'),
        sa.Column('content_mode', sa.String(16), nullable=False, server_default=sa.text("'summary'"), comment='full_text/summary'),
        sa.Column('content_md', mysql.LONGTEXT(), nullable=True, comment='Markdown内容'),
        sa.Column('credibility_score', sa.SmallInteger(), nullable=True, comment='可信度分值1-5'),
        sa.Column('credibility_label', sa.String(32), nullable=True, comment='verified/plausible/uncertain/unverifiable'),
        sa.Column('credibility_note', sa.Text(), nullable=True, comment='可信度说明'),
        sa.Column('tags', sa.JSON(), nullable=True, comment='情报标签数组'),
        sa.Column('item_type', sa.String(64), nullable=True, comment='条目类型'),
        sa.Column('related_competitor', sa.String(128), nullable=True, comment='关联竞品'),
        sa.Column('is_featured', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='0=否,1=精选'),
        sa.Column('status', sa.String(32), nullable=False, server_default=sa.text("'active'"), comment='active/archived/flagged'),
        # XPOZ 专属扩展字段
        sa.Column('xpoz_post_id', sa.String(64), nullable=True, comment='XPOZ帖子唯一ID'),
        sa.Column('like_count', sa.Integer(), nullable=True, comment='点赞数'),
        sa.Column('comment_count', sa.Integer(), nullable=True, comment='评论数'),
        sa.Column('media_type', sa.String(16), nullable=True, comment='photo/video/carousel'),
        sa.Column('ai_signal', sa.String(100), nullable=True, comment='AI提取核心信号'),
        sa.Column('ai_meaning', sa.String(200), nullable=True, comment='AI分析业务意义'),
        sa.Column('ai_action_hint', sa.String(150), nullable=True, comment='AI建议可执行动作'),
        sa.Column('priority', sa.String(16), nullable=False, server_default=sa.text("'medium'"), comment='high/medium/low'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_insight_item_collected', 'ark_insight_items', ['collected_at'], unique=False)
    op.create_index('idx_insight_item_source', 'ark_insight_items', ['source_id'], unique=False)
    op.create_index('idx_insight_item_type', 'ark_insight_items', ['item_type'], unique=False)
    op.create_index('idx_insight_item_cred', 'ark_insight_items', ['credibility_score'], unique=False)
    op.create_index('idx_insight_item_featured', 'ark_insight_items', ['is_featured'], unique=False)
    op.create_index('idx_insight_item_status', 'ark_insight_items', ['status'], unique=False)
    op.create_index('idx_insight_item_xpoz', 'ark_insight_items', ['xpoz_post_id'], unique=True)

    # ── 新建表: 采集日志 ────────────────────────────────────
    op.create_table(
        'ark_insight_collection_logs',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('ark_insight_sources.id'), nullable=True),
        sa.Column('run_at', sa.DateTime(), nullable=False, comment='执行时间'),
        sa.Column('status', sa.String(32), nullable=False, comment='success/partial/failed'),
        sa.Column('items_fetched', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('items_written', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('items_filtered', sa.Integer(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_insight_log_source', 'ark_insight_collection_logs', ['source_id'], unique=False)
    op.create_index('idx_insight_log_run', 'ark_insight_collection_logs', ['run_at'], unique=False)

    # ── 新建表: 定时生成规则 ────────────────────────────────
    op.create_table(
        'ark_insight_schedule_rules',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('rule_name', sa.String(128), nullable=False, comment='规则名称'),
        sa.Column('is_active', sa.SmallInteger(), nullable=False, server_default=sa.text("'1'"), comment='0=禁用,1=启用'),
        sa.Column('cron_expression', sa.String(64), nullable=True, comment='cron表达式'),
        sa.Column('config_json', sa.JSON(), nullable=True, comment='选材规则、生成配置'),
        sa.Column('notify_dingtalk', sa.SmallInteger(), nullable=False, server_default=sa.text("'1'"), comment='0=否,1=是'),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
    )
    op.create_index('idx_insight_rule_active', 'ark_insight_schedule_rules', ['is_active'], unique=False)


def downgrade() -> None:
    op.drop_table('ark_insight_schedule_rules')
    op.drop_table('ark_insight_collection_logs')
    op.drop_table('ark_insight_items')

    # 恢复 report_type enum
    op.execute(
        "ALTER TABLE ark_insight_reports "
        "MODIFY COLUMN report_type ENUM("
        "'industry_daily','ai_tools','shop_analysis','competitor_analysis','inquiry_analysis'"
        ") NOT NULL"
    )

    # 恢复 status enum
    op.execute(
        "ALTER TABLE ark_insight_reports "
        "MODIFY COLUMN status ENUM('pending','published','failed') NOT NULL DEFAULT 'pending'"
    )

    # 删除新增列
    op.drop_column('ark_insight_reports', 'trigger_type')
    op.drop_column('ark_insight_reports', 'is_pinned')
    op.drop_column('ark_insight_reports', 'config_snapshot')
    op.drop_column('ark_insight_reports', 'item_ids')
    op.drop_column('ark_insight_reports', 'date_range_end')
    op.drop_column('ark_insight_reports', 'date_range_start')

    # 恢复 source_type enum
    op.execute(
        "ALTER TABLE ark_insight_sources "
        "MODIFY COLUMN source_type ENUM("
        "'google_alerts_rss','pinterest_scrape','google_trends_rss',"
        "'amazon_bestseller','competitor_rss','competitor_html','aihot_api'"
        ") NOT NULL"
    )

    op.drop_column('ark_insight_sources', 'config_json')
