"""Frozen inbound intents and their local allocation effects."""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint

from app.core.database import Base
from app.core.time import beijing_now


class Batch(Base):
    __tablename__ = "ark_factory_inbound_batches"
    __table_args__ = {"comment": "工厂到货确认批次、外部单据凭据及回写状态"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    note_id = Column(BigInteger, ForeignKey("ark_factory_inbound_notes.id"), nullable=False, index=True, comment="到货单ID")
    batch_no = Column(String(48), nullable=False, unique=True, comment="方舟入库批次号")
    idempotency_key = Column(String(64), nullable=False, unique=True, comment="确认幂等键")
    confirmed_by = Column(Integer, nullable=False, comment="确认人ID")
    confirmed_at = Column(DateTime, nullable=False, default=beijing_now, comment="确认时间")
    sync_status = Column(String(16), nullable=False, default="confirmed", comment="小满同步状态")
    writeback_status = Column(String(16), nullable=False, default="none", comment="本地回写状态")
    request_snapshot = Column(JSON, nullable=False, comment="已确认的小满采购入库请求")
    purchase_intent = Column(JSON(none_as_null=True), comment="冻结的采购与入库业务字段")
    sync_checkpoint = Column(JSON(none_as_null=True), comment="远端阶段、发送意图及核对凭据")
    plan_snapshot = Column(JSON, nullable=False, comment="已确认的行、SKU与分配意图")
    xiaoman_inbound_id = Column(BigInteger, unique=True, comment="小满采购入库内部ID")
    xiaoman_serial_id = Column(String(64), comment="小满采购入库单号")
    completion_evidence = Column(JSON, comment="已核验的小满完成回读")
    writeback_at = Column(DateTime, comment="方舟回写生效时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")


class Allocation(Base):
    __tablename__ = "ark_factory_inbound_allocations"
    __table_args__ = (
        UniqueConstraint("batch_id", "line_id", "target_kind", "target_id", name="uq_factory_inbound_batch_target"),
        Index("ix_factory_inbound_target_status", "target_kind", "target_id", "status"),
        {"comment": "工厂到货分配与发票生产单对应"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(BigInteger, ForeignKey("ark_factory_inbound_batches.id"), nullable=False, comment="批次ID")
    line_id = Column(BigInteger, ForeignKey("ark_factory_inbound_lines.id"), nullable=False, comment="到货明细ID")
    target_kind = Column(String(24), nullable=False, comment="生产备货明细或发票明细")
    target_id = Column(BigInteger, nullable=False, comment="目标明细ID")
    quantity = Column(Integer, nullable=False, comment="分配件数")
    status = Column(String(16), nullable=False, default="pending", comment="预占、生效或释放")
    target_snapshot = Column(JSON, nullable=False, comment="订单与SKU核对快照")
