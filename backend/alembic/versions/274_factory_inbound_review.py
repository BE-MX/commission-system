"""Create factory delivery OCR and review tables."""

from alembic import op
import sqlalchemy as sa

revision = "274_factory_inbound_review"
down_revision = "273_product_sales_insights"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_factory_inbound_note_sequences",
        sa.Column('business_date', sa.Date, primary_key=True, comment='北京业务日期'),
        sa.Column('last_number', sa.Integer, nullable=False, comment='当日已发流水号'),
        comment='按北京时间分配工厂入库单流水号',
    )
    op.create_table(
        "ark_factory_inbound_notes",
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('inbound_no', sa.String(32), nullable=False, unique=True, comment='方舟入库单号'),
        sa.Column('factory_code', sa.String(32), nullable=False, comment='工厂编码'),
        sa.Column('recognized_delivery_no', sa.String(32), comment='识别单据编号'),
        sa.Column('delivery_no', sa.String(32), comment='人工确认单据编号'),
        sa.Column('delivery_key', sa.String(80), sa.Computed("CASE WHEN status = 'voided' OR delivery_no IS NULL THEN NULL ELSE CONCAT(factory_code, ':', delivery_no) END"), unique=True, comment='未作废记录的单据唯一键'),
        sa.Column('duplicate_suspected_note_id', sa.BigInteger, comment='疑似已拍记录ID'),
        sa.Column('duplicate_of_note_id', sa.BigInteger, comment='确认重复的原记录ID'),
        sa.Column('delivery_month', sa.SmallInteger, comment='单据手写月'),
        sa.Column('delivery_day', sa.SmallInteger, comment='单据手写日'),
        sa.Column('scan_path', sa.String(255), nullable=False, comment='校正图相对路径'),
        sa.Column('original_path', sa.String(255), comment='原图相对路径'),
        sa.Column('recognition_status', sa.String(16), nullable=False, comment='识别状态'),
        sa.Column('recognition_attempt_id', sa.String(32), nullable=False, comment='识别尝试标识'),
        sa.Column('recognition_queued_at', sa.DateTime, nullable=False, comment='识别排队时间'),
        sa.Column('recognition_started_at', sa.DateTime, comment='识别开始时间'),
        sa.Column('recognition_finished_at', sa.DateTime, comment='识别结束时间'),
        sa.Column('recognition_error', sa.String(255), comment='面向用户的识别错误'),
        sa.Column('recognition_raw', sa.JSON, comment='原始结构化识别结果'),
        sa.Column('status', sa.String(16), nullable=False, comment='单据状态'),
        sa.Column('created_by', sa.Integer, nullable=False, comment='创建人ID'),
        sa.Column('version', sa.Integer, nullable=False, comment='乐观锁版本'),
        sa.Column('created_at', sa.DateTime, nullable=False, comment='创建时间'),
        sa.Column('updated_by', sa.Integer, comment='最后操作人ID'),
        sa.Column('updated_at', sa.DateTime, nullable=False, comment='更新时间'),
        comment='工厂到货单草稿与核对状态',
    )
    op.create_index('ix_factory_inbound_recognized', "ark_factory_inbound_notes", ['factory_code', 'recognized_delivery_no'])
    op.create_index('ix_factory_inbound_note_owner', "ark_factory_inbound_notes", ['created_by', 'created_at'])
    op.create_table(
        "ark_factory_inbound_lines",
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('note_id', sa.BigInteger, sa.ForeignKey('ark_factory_inbound_notes.id'), nullable=False, comment='单据ID'),
        sa.Column('line_no', sa.Integer, nullable=False, comment='识别行序号'),
        sa.Column('raw', sa.JSON, nullable=False, comment='识别原文与疑点'),
        sa.Column('values', sa.JSON, nullable=False, comment='当前核对字段'),
        sa.Column('match_status', sa.String(16), nullable=False, comment='匹配状态'),
        sa.Column('match_data', sa.JSON, nullable=False, comment='确定性匹配与候选快照'),
        sa.Column('decision', sa.JSON, comment='人工候选与路线决定及审计信息'),
        sa.Column('selected', sa.Boolean, nullable=False, comment='核对勾选状态'),
        sa.Column('writeback_enabled', sa.Boolean, nullable=False, comment='回写与对应意图'),
        sa.Column('created_by', sa.Integer, nullable=False, comment='创建人ID'),
        sa.Column('created_at', sa.DateTime, nullable=False, comment='创建时间'),
        sa.Column('updated_by', sa.Integer, comment='最后操作人ID'),
        sa.Column('updated_at', sa.DateTime, nullable=False, comment='更新时间'),
        sa.UniqueConstraint('note_id', 'line_no', name='uq_factory_inbound_line_no'),
        comment='工厂到货单原始识别及核对明细',
    )
    op.create_table(
        "ark_factory_inbound_line_types",
        sa.Column('code', sa.String(24), primary_key=True, comment='类型编码'),
        sa.Column('label', sa.String(32), nullable=False, comment='类型名称'),
        sa.Column('is_inbound', sa.Boolean, nullable=False, comment='是否到货行'),
        sa.Column('enabled', sa.Boolean, nullable=False, comment='是否启用'),
        comment='工厂到货单识别行类型',
    )
    op.create_table(
        "ark_factory_inbound_aliases",
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('kind', sa.String(12), nullable=False, comment='词表类别'),
        sa.Column('factory_term', sa.String(128), nullable=False, comment='规范化的工厂写法'),
        sa.Column('target', sa.String(128), nullable=False, comment='系统目录词条'),
        sa.Column('enabled', sa.Boolean, nullable=False, comment='是否启用'),
        sa.Column('source', sa.String(16), nullable=False, comment='词条来源'),
        sa.Column('updated_by', sa.Integer, comment='最后操作人ID'),
        sa.Column('updated_at', sa.DateTime, nullable=False, comment='更新时间'),
        sa.UniqueConstraint('kind', 'factory_term', name='uq_factory_inbound_alias_term'),
        comment='工厂到货工艺、颜色及等级词表',
    )
    op.create_table(
        "ark_factory_inbound_alias_suggestions",
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('factory_term', sa.String(128), nullable=False, comment='工厂写法'),
        sa.Column('target', sa.String(128), nullable=False, comment='期望系统颜色'),
        sa.Column('suggested_by', sa.Integer, nullable=False, comment='建议人ID'),
        sa.Column('reviewed_by', sa.Integer, comment='审核人ID'),
        sa.Column('status', sa.String(16), nullable=False, comment='审核状态'),
        sa.Column('created_at', sa.DateTime, nullable=False, comment='建议时间'),
        sa.Column('reviewed_at', sa.DateTime, comment='审核时间'),
        comment='工厂到货颜色别名审核建议',
    )
    op.create_table(
        "ark_factory_inbound_edit_logs",
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('note_id', sa.BigInteger, sa.ForeignKey('ark_factory_inbound_notes.id'), nullable=False, comment='单据ID'),
        sa.Column('line_id', sa.BigInteger, comment='明细ID快照'),
        sa.Column('action', sa.String(24), nullable=False, comment='变更动作'),
        sa.Column('before_data', sa.JSON, comment='变更前快照'),
        sa.Column('after_data', sa.JSON, comment='变更后快照'),
        sa.Column('created_by', sa.Integer, nullable=False, comment='操作人ID'),
        sa.Column('created_at', sa.DateTime, nullable=False, comment='操作时间'),
        comment='工厂到货单编号、明细和作废审核记录',
    )
    op.create_index('ix_factory_inbound_edit_note_id', "ark_factory_inbound_edit_logs", ['note_id'])

    line_types = sa.table("ark_factory_inbound_line_types", sa.column("code", sa.String),
                          sa.column("label", sa.String), sa.column("is_inbound", sa.Boolean),
                          sa.column("enabled", sa.Boolean))
    op.bulk_insert(line_types, [
        {"code": code, "label": label, "is_inbound": inbound, "enabled": True}
        for code, label, inbound in (
            ("inbound", "到货", True), ("sample", "色样", False), ("altered", "改造", False),
            ("repair", "返修", False), ("crossed_out", "划掉", False), ("unclear", "待核对", False),
        )
    ])
    aliases = sa.table("ark_factory_inbound_aliases", sa.column("kind", sa.String),
                       sa.column("factory_term", sa.String), sa.column("target", sa.String),
                       sa.column("enabled", sa.Boolean), sa.column("source", sa.String),
                       sa.column("updated_at", sa.DateTime))
    for seed in [
        {"kind": kind, "factory_term": term, "target": target, "enabled": True,
         "source": "seed", "updated_at": sa.literal_column("CURRENT_TIMESTAMP")}
        for kind, term, target in (
            ("process", "PU", "Genius Weft"), ("process", "PU打孔", "Genius Weft"),
            ("process", "贴片", "Tape Hair"), ("process", "机织贴片", "Tape Hair"),
            ("color", "GC", "Cookies Cream"),
        )
    ]:
        op.execute(aliases.insert().values(**seed))


def downgrade():
    raise RuntimeError("Factory inbound drafts and review history require an explicit data retention decision")
