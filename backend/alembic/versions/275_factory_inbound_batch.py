"""Persist P2 confirmed batches, verified receipts and allocation states."""

from alembic import op
import sqlalchemy as sa

revision = "275_factory_inbound_batch"
down_revision = "274_factory_inbound_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ark_factory_inbound_batches',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('note_id', sa.BigInteger, sa.ForeignKey('ark_factory_inbound_notes.id'), nullable=False, comment='到货单ID'),
        sa.Column('batch_no', sa.String(48), nullable=False, unique=True, comment='方舟入库批次号'),
        sa.Column('idempotency_key', sa.String(64), nullable=False, unique=True, comment='确认幂等键'),
        sa.Column('confirmed_by', sa.Integer, nullable=False, comment='确认人ID'),
        sa.Column('confirmed_at', sa.DateTime, nullable=False, comment='确认时间'),
        sa.Column('sync_status', sa.String(16), nullable=False, comment='小满同步状态'),
        sa.Column('writeback_status', sa.String(16), nullable=False, comment='本地回写状态'),
        sa.Column('request_snapshot', sa.JSON, nullable=False, comment='已确认的小满采购入库请求'),
        sa.Column('purchase_intent', sa.JSON(none_as_null=True), comment='冻结的采购与入库业务字段'),
        sa.Column('sync_checkpoint', sa.JSON(none_as_null=True), comment='远端阶段、发送意图及核对凭据'),
        sa.Column('plan_snapshot', sa.JSON, nullable=False, comment='已确认的行、SKU与分配意图'),
        sa.Column('xiaoman_inbound_id', sa.BigInteger, unique=True, comment='小满采购入库内部ID'),
        sa.Column('xiaoman_serial_id', sa.String(64), comment='小满采购入库单号'),
        sa.Column('completion_evidence', sa.JSON, comment='已核验的小满完成回读'),
        sa.Column('writeback_at', sa.DateTime, comment='方舟回写生效时间'),
        sa.Column('updated_at', sa.DateTime, nullable=False, comment='更新时间'),
        comment='工厂到货确认批次、外部单据凭据及回写状态',
    )
    op.create_index('ix_ark_factory_inbound_batches_note_id', 'ark_factory_inbound_batches', ['note_id'])
    op.create_table(
        'ark_factory_inbound_allocations',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('batch_id', sa.BigInteger, sa.ForeignKey('ark_factory_inbound_batches.id'), nullable=False, comment='批次ID'),
        sa.Column('line_id', sa.BigInteger, sa.ForeignKey('ark_factory_inbound_lines.id'), nullable=False, comment='到货明细ID'),
        sa.Column('target_kind', sa.String(24), nullable=False, comment='生产备货明细或发票明细'),
        sa.Column('target_id', sa.BigInteger, nullable=False, comment='目标明细ID'),
        sa.Column('quantity', sa.Integer, nullable=False, comment='分配件数'),
        sa.Column('status', sa.String(16), nullable=False, comment='预占、生效或释放'),
        sa.Column('target_snapshot', sa.JSON, nullable=False, comment='订单与SKU核对快照'),
        sa.UniqueConstraint('batch_id', 'line_id', 'target_kind', 'target_id', name='uq_factory_inbound_batch_target'),
        comment='工厂到货分配与发票生产单对应',
    )
    op.create_index('ix_factory_inbound_target_status', 'ark_factory_inbound_allocations', ['target_kind', 'target_id', 'status'])

    op.add_column("ark_factory_inbound_lines", sa.Column("batch_id", sa.BigInteger(), comment="当前确认批次ID"))
    op.create_index("ix_ark_factory_inbound_lines_batch_id", "ark_factory_inbound_lines", ["batch_id"])
    op.create_foreign_key("fk_factory_inbound_line_batch", "ark_factory_inbound_lines",
                          "ark_factory_inbound_batches", ["batch_id"], ["id"])


def downgrade():
    raise RuntimeError("Factory inbound batch and receipt evidence requires an explicit retention decision")
