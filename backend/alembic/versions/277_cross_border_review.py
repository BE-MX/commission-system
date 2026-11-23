"""Persist DHL imports, specialist reviews and downloadable customs files."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "277_cross_border_review"
down_revision = "276_invoice_alibaba_order"
branch_labels = None
depends_on = None


def upgrade():
    user_id_type = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql')
    op.create_table('ark_cross_border_imports',
    sa.Column('id', sa.Integer(), nullable=False, comment='导入批次'),
    sa.Column('file_kind', sa.String(length=10), nullable=False, comment='订单或收款单'),
    sa.Column('file_name', sa.String(length=255), nullable=False, comment='源文件名'),
    sa.Column('file_sha256', sa.String(length=64), nullable=False, comment='文件内容摘要'),
    sa.Column('row_count', sa.Integer(), nullable=False, comment='源文件行数'),
    sa.Column('added', sa.Integer(), nullable=False, comment='新增条目数'),
    sa.Column('suspected', sa.Integer(), nullable=False, comment='本批未出现的同号旧条目数'),
    sa.Column('content_hashes', sa.JSON(), nullable=False, comment='本批条目内容摘要列表，保留批次成员关系'),
    sa.Column('imported_by', user_id_type, nullable=False, comment='导入人'),
    sa.Column('imported_at', sa.DateTime(), nullable=False, comment='导入北京时间'),
    sa.ForeignKeyConstraint(['imported_by'], ['ark_users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_sha256'),
    comment='跨境申报导入文件批次'
    )
    op.create_table('ark_cross_border_declarations',
    sa.Column('head_json', sa.JSON(), nullable=False, comment='原始订单头'),
    sa.Column('line_json', sa.JSON(), nullable=False, comment='对应原始订单明细'),
    sa.Column('suspected_changed', sa.Boolean(), nullable=False, comment='最近同号导入未出现'),
    sa.Column('status', sa.String(length=10), nullable=False, comment='有效或已作废'),
    sa.Column('id', sa.Integer(), nullable=False, comment='条目主键'),
    sa.Column('order_no', sa.String(length=20), nullable=False, comment='阿里信保订单号'),
    sa.Column('occurrence', sa.Integer(), nullable=False, comment='相同内容出现序号'),
    sa.Column('content_hash', sa.String(length=64), nullable=False, comment='条目稳定身份'),
    sa.Column('base_json', sa.JSON(), nullable=False, comment='对应传输企业原始行'),
    sa.Column('first_import_id', sa.Integer(), nullable=False, comment='首次导入批次'),
    sa.Column('first_row_no', sa.Integer(), nullable=False, comment='首次源表行号'),
    sa.Column('last_import_id', sa.Integer(), nullable=False, comment='最近出现批次'),
    sa.ForeignKeyConstraint(['first_import_id'], ['ark_cross_border_imports.id'], ),
    sa.ForeignKeyConstraint(['last_import_id'], ['ark_cross_border_imports.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_hash'),
    comment='跨境申报订单条目'
    )
    op.create_index(op.f('ix_ark_cross_border_declarations_order_no'), 'ark_cross_border_declarations', ['order_no'], unique=False)
    op.create_table('ark_cross_border_receipts',
    sa.Column('receipt_json', sa.JSON(), nullable=False, comment='原始收款单行'),
    sa.Column('id', sa.Integer(), nullable=False, comment='条目主键'),
    sa.Column('order_no', sa.String(length=20), nullable=False, comment='阿里信保订单号'),
    sa.Column('occurrence', sa.Integer(), nullable=False, comment='相同内容出现序号'),
    sa.Column('content_hash', sa.String(length=64), nullable=False, comment='条目稳定身份'),
    sa.Column('base_json', sa.JSON(), nullable=False, comment='对应传输企业原始行'),
    sa.Column('first_import_id', sa.Integer(), nullable=False, comment='首次导入批次'),
    sa.Column('first_row_no', sa.Integer(), nullable=False, comment='首次源表行号'),
    sa.Column('last_import_id', sa.Integer(), nullable=False, comment='最近出现批次'),
    sa.ForeignKeyConstraint(['first_import_id'], ['ark_cross_border_imports.id'], ),
    sa.ForeignKeyConstraint(['last_import_id'], ['ark_cross_border_imports.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_hash'),
    comment='跨境申报收款条目'
    )
    op.create_index(op.f('ix_ark_cross_border_receipts_order_no'), 'ark_cross_border_receipts', ['order_no'], unique=False)
    op.create_table('ark_cross_border_reviews',
    sa.Column('id', sa.Integer(), nullable=False, comment='审计序号'),
    sa.Column('content_hash', sa.String(length=64), nullable=False, comment='决定对应的申报身份'),
    sa.Column('action', sa.String(length=30), nullable=False, comment='核对动作'),
    sa.Column('target', sa.BigInteger(), nullable=True, comment='指定或确认交运的运单跟踪ID'),
    sa.Column('reason', sa.String(length=500), nullable=False, comment='专员核实原因'),
    sa.Column('created_by', user_id_type, nullable=False, comment='操作人'),
    sa.Column('created_at', sa.DateTime(), nullable=False, comment='操作北京时间'),
    sa.ForeignKeyConstraint(['content_hash'], ['ark_cross_border_declarations.content_hash'], ),
    sa.ForeignKeyConstraint(['created_by'], ['ark_users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    comment='跨境申报人工核对审计'
    )
    op.create_index(op.f('ix_ark_cross_border_reviews_content_hash'), 'ark_cross_border_reviews', ['content_hash'], unique=False)
    op.create_table('ark_cross_border_exports',
    sa.Column('id', sa.Integer(), nullable=False, comment='导出记录'),
    sa.Column('created_by', user_id_type, nullable=False, comment='导出人'),
    sa.Column('created_at', sa.DateTime(), nullable=False, comment='导出北京时间'),
    sa.Column('content_hashes', sa.JSON(), nullable=False, comment='按文件顺序导出的申报身份'),
    sa.Column('order_file', sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), 'mysql'), nullable=False, comment='报关订单原文件'),
    sa.Column('receipt_file', sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), 'mysql'), nullable=False, comment='报关收款单原文件'),
    sa.ForeignKeyConstraint(['created_by'], ['ark_users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    comment='报关文件与生成审计'
    )


def downgrade():
    raise RuntimeError("Cross-border declarations and audit evidence require an explicit retention decision")
