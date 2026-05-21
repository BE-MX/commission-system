"""add color module

Revision ID: 022_add_color_module
Revises: 021_add_intelligence_module
Create Date: 2026-05-20 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '022_add_color_module'
down_revision: Union[str, None] = '021_add_intelligence_module'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql')


def upgrade() -> None:
    # ── 表1: 基础色号表 ─────────────────────────────────────
    op.create_table(
        'ark_color_palette',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('industry_code', sa.String(20), nullable=False, comment='行业标准色号，如 #1, #613, #1C/18'),
        sa.Column('brand_code', sa.String(50), nullable=True, comment='品牌特有编码，如 Bellami的Vanilla Latte'),
        sa.Column('display_name', sa.String(100), nullable=False, comment='展示名称（中英双语）'),
        sa.Column('display_name_en', sa.String(100), nullable=True, comment='英文名称'),
        sa.Column('hex_code', sa.CHAR(7), nullable=False, comment='HEX值，如 #6B5A52'),
        sa.Column('rgb_r', sa.SmallInteger(), nullable=False, comment='R 0-255'),
        sa.Column('rgb_g', sa.SmallInteger(), nullable=False, comment='G 0-255'),
        sa.Column('rgb_b', sa.SmallInteger(), nullable=False, comment='B 0-255'),
        sa.Column('lab_l', sa.Numeric(6, 2), nullable=True, comment='CIE LAB - L* (明度 0-100)'),
        sa.Column('lab_a', sa.Numeric(6, 2), nullable=True, comment='CIE LAB - a* (绿红 -128~127)'),
        sa.Column('lab_b_val', sa.Numeric(6, 2), nullable=True, comment='CIE LAB - b* (蓝黄 -128~127)'),
        sa.Column('hsl_h', sa.SmallInteger(), nullable=True, comment='HSL色相 0-360'),
        sa.Column('hsl_s', sa.Numeric(5, 2), nullable=True, comment='HSL饱和度 0-100'),
        sa.Column('hsl_l', sa.Numeric(5, 2), nullable=True, comment='HSL亮度 0-100'),
        sa.Column('undertone', sa.String(16), nullable=True, comment='warm/cool/neutral'),
        sa.Column('luminance_level', sa.String(16), nullable=True, comment='low/medium-low/medium/medium-high/high/very-high'),
        sa.Column('color_family', sa.String(16), nullable=False, comment='black/brown/blonde/red/silver/vibrant'),
        sa.Column('pantone_tcx', sa.String(30), nullable=True, comment='最近Pantone TCX色号'),
        sa.Column('pantone_delta_e', sa.Numeric(4, 2), nullable=True, comment='与Pantone的ΔE2000值'),
        sa.Column('source', sa.String(32), nullable=False, server_default=sa.text("'industry'"), comment='industry/bellami/luxy/great_lengths/leshine/organic_hair'),
        sa.Column('is_leshine_stock', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='0=否,1=是莱莎现有库存色'),
        sa.Column('peak_season', sa.String(64), nullable=True, comment='高峰销售季节 spring/summer/autumn/winter 逗号分隔'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('industry_code', 'source', name='uk_industry_source'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
        mysql_comment='色板数据库-基础色号表',
    )
    op.create_index('idx_palette_family', 'ark_color_palette', ['color_family'], unique=False)
    op.create_index('idx_palette_hex', 'ark_color_palette', ['hex_code'], unique=False)
    op.create_index('idx_palette_luminance', 'ark_color_palette', ['luminance_level'], unique=False)

    # ── 表2: 混合色号表 ─────────────────────────────────────
    op.create_table(
        'ark_color_blend',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('blend_code', sa.String(30), nullable=False, comment='混合编码，如 #8/8/60, #1C/18/46'),
        sa.Column('display_name', sa.String(100), nullable=False, comment='展示名称'),
        sa.Column('display_name_en', sa.String(100), nullable=True, comment='英文名称'),
        sa.Column('blend_type', sa.String(32), nullable=False, comment='piano/ombre/balayage/rooted/tri-blend/multi-blend'),
        sa.Column('computed_hex', sa.CHAR(7), nullable=True, comment='加权混合计算的综合HEX'),
        sa.Column('computed_lab_l', sa.Numeric(6, 2), nullable=True),
        sa.Column('computed_lab_a', sa.Numeric(6, 2), nullable=True),
        sa.Column('computed_lab_b', sa.Numeric(6, 2), nullable=True),
        sa.Column('source', sa.String(32), nullable=False, comment='bellami/luxy/great_lengths/leshine/organic_hair/custom'),
        sa.Column('brand_name', sa.String(100), nullable=True, comment='品牌命名，如 Vanilla Latte'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('blend_code', 'source', name='uk_blend_source'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
        mysql_comment='色板数据库-混合色号表',
    )
    op.create_index('idx_blend_type', 'ark_color_blend', ['blend_type'], unique=False)

    # ── 表3: 混合色成分关联表 ────────────────────────────────
    op.create_table(
        'ark_color_blend_component',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('blend_id', _UINT, sa.ForeignKey('ark_color_blend.id', ondelete='CASCADE'), nullable=False, comment='关联混合色'),
        sa.Column('palette_id', _UINT, sa.ForeignKey('ark_color_palette.id', ondelete='RESTRICT'), nullable=False, comment='关联基础色'),
        sa.Column('position', sa.String(16), nullable=False, server_default=sa.text("'even'"), comment='root/mid/end/highlight/even'),
        sa.Column('weight', sa.Numeric(4, 2), nullable=False, server_default=sa.text("'0.50'"), comment='混合权重，同一blend总和=1'),
        sa.Column('sort_order', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='从发根到发尾排序'),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
        mysql_comment='混合色成分关联',
    )
    op.create_index('idx_blend_component_blend', 'ark_color_blend_component', ['blend_id'], unique=False)

    # ── 表4: 竞品色号监控表 ─────────────────────────────────
    op.create_table(
        'ark_competitor_color_watch',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('brand', sa.String(50), nullable=False, comment='竞品品牌名'),
        sa.Column('color_code', sa.String(30), nullable=False, comment='竞品色号编码'),
        sa.Column('color_name', sa.String(100), nullable=True),
        sa.Column('product_url', sa.String(500), nullable=True, comment='产品页URL'),
        sa.Column('extracted_hex', sa.CHAR(7), nullable=True, comment='OpenCV提取的主色调HEX'),
        sa.Column('extracted_lab_l', sa.Numeric(6, 2), nullable=True),
        sa.Column('extracted_lab_a', sa.Numeric(6, 2), nullable=True),
        sa.Column('extracted_lab_b', sa.Numeric(6, 2), nullable=True),
        sa.Column('nearest_palette_id', _UINT, nullable=True, comment='莱莎色库最近色号ID'),
        sa.Column('match_delta_e', sa.Numeric(4, 2), nullable=True, comment='匹配色差'),
        sa.Column('social_mentions_30d', sa.Integer(), nullable=False, server_default=sa.text("'0'"), comment='近30天社媒提及次数'),
        sa.Column('popularity_score', sa.Numeric(5, 2), nullable=False, server_default=sa.text("'0'"), comment='综合热度分0-100'),
        sa.Column('first_seen', sa.Date(), nullable=False, comment='首次发现日期'),
        sa.Column('last_seen', sa.Date(), nullable=False, comment='最近一次确认在售'),
        sa.Column('is_new_launch', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'"), comment='0=否,1=近期新品'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('brand', 'color_code', name='uk_brand_code'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
        mysql_comment='竞品色号监控',
    )
    op.create_index('idx_comp_color_popularity', 'ark_competitor_color_watch', ['popularity_score'], unique=False)
    op.create_index('idx_comp_color_first_seen', 'ark_competitor_color_watch', ['first_seen'], unique=False)

    # ── 表5: 色彩趋势时序数据表 ─────────────────────────────
    op.create_table(
        'ark_color_trend_data',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('color_family', sa.String(16), nullable=False, comment='black/brown/blonde/red/silver/vibrant'),
        sa.Column('data_source', sa.String(32), nullable=False, comment='sales/social_xpoz/google_trends/competitor_launch/pantone'),
        sa.Column('period_date', sa.Date(), nullable=False, comment='数据日期'),
        sa.Column('period_type', sa.String(16), nullable=False, server_default=sa.text("'weekly'"), comment='daily/weekly/monthly'),
        sa.Column('raw_value', sa.Numeric(10, 2), nullable=False, comment='原始值（销量/提及次数/搜索指数）'),
        sa.Column('normalized_score', sa.Numeric(5, 2), nullable=True, comment='归一化分数0-100'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('color_family', 'data_source', 'period_date', 'period_type', name='uk_family_source_date'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
        mysql_comment='色彩趋势时序数据',
    )
    op.create_index('idx_trend_period', 'ark_color_trend_data', ['period_date'], unique=False)

    # ── 表6: 色板图生成记录 ─────────────────────────────────
    op.create_table(
        'ark_color_swatch_image',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('palette_id', _UINT, sa.ForeignKey('ark_color_palette.id', ondelete='SET NULL'), nullable=True, comment='基础色号'),
        sa.Column('blend_id', _UINT, sa.ForeignKey('ark_color_blend.id', ondelete='SET NULL'), nullable=True, comment='混合色号'),
        sa.Column('prompt', sa.Text(), nullable=False, comment='生成Prompt'),
        sa.Column('model_used', sa.String(50), nullable=False, comment='gpt-image-2/sd-xl/hairdiffusion'),
        sa.Column('image_path', sa.String(500), nullable=False, comment='生成图片存储路径'),
        sa.Column('image_url', sa.String(500), nullable=True, comment='图片访问URL'),
        sa.Column('target_hex', sa.CHAR(7), nullable=False, comment='目标HEX'),
        sa.Column('actual_hex', sa.CHAR(7), nullable=True, comment='实际提取主色HEX'),
        sa.Column('delta_e', sa.Numeric(4, 2), nullable=True, comment='目标与实际的ΔE2000'),
        sa.Column('pass_check', sa.SmallInteger(), nullable=True, comment='0=否,1=通过色差校验'),
        sa.Column('status', sa.String(32), nullable=False, server_default=sa.text("'pending'"), comment='pending/generating/completed/failed/rejected'),
        sa.Column('retry_count', sa.SmallInteger(), nullable=False, server_default=sa.text("'0'")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
        mysql_comment='色板图生成记录',
    )
    op.create_index('idx_swatch_palette', 'ark_color_swatch_image', ['palette_id'], unique=False)
    op.create_index('idx_swatch_blend', 'ark_color_swatch_image', ['blend_id'], unique=False)
    op.create_index('idx_swatch_status', 'ark_color_swatch_image', ['status'], unique=False)

    # ── 表7: Pantone参考色库 ────────────────────────────────
    op.create_table(
        'ark_pantone_reference',
        sa.Column('id', _UINT, autoincrement=True, nullable=False),
        sa.Column('pantone_code', sa.String(20), nullable=False, comment='Pantone TCX编码，如 19-4004 TCX'),
        sa.Column('pantone_name', sa.String(100), nullable=True, comment='Pantone英文名称'),
        sa.Column('hex_code', sa.CHAR(7), nullable=False),
        sa.Column('rgb_r', sa.SmallInteger(), nullable=False),
        sa.Column('rgb_g', sa.SmallInteger(), nullable=False),
        sa.Column('rgb_b', sa.SmallInteger(), nullable=False),
        sa.Column('lab_l', sa.Numeric(6, 2), nullable=True),
        sa.Column('lab_a', sa.Numeric(6, 2), nullable=True),
        sa.Column('lab_b_val', sa.Numeric(6, 2), nullable=True),
        sa.Column('collection', sa.String(16), nullable=False, server_default=sa.text("'tcx'"), comment='tcx/tpg/coated/uncoated'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pantone_code', name='uk_pantone_code'),
        mysql_collate='utf8mb4_unicode_ci',
        mysql_engine='InnoDB',
        mysql_comment='Pantone参考色库',
    )
    op.create_index('idx_pantone_hex', 'ark_pantone_reference', ['hex_code'], unique=False)


def downgrade() -> None:
    op.drop_table('ark_pantone_reference')
    op.drop_table('ark_color_swatch_image')
    op.drop_table('ark_color_trend_data')
    op.drop_table('ark_competitor_color_watch')
    op.drop_table('ark_color_blend_component')
    op.drop_table('ark_color_blend')
    op.drop_table('ark_color_palette')
