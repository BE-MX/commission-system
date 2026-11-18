"""Factory delivery drafts and their review history."""

from sqlalchemy import (
    BigInteger, Boolean, Column, Computed, Date, DateTime, ForeignKey, Index,
    Integer, JSON, SmallInteger, String, UniqueConstraint,
)

from app.core.database import Base
from app.core.time import beijing_now


class NoteSequence(Base):
    __tablename__ = "ark_factory_inbound_note_sequences"
    __table_args__ = {"comment": "按北京时间分配工厂入库单流水号"}

    business_date = Column(Date, primary_key=True, comment="北京业务日期")
    last_number = Column(Integer, nullable=False, comment="当日已发流水号")


class Note(Base):
    __tablename__ = "ark_factory_inbound_notes"
    __table_args__ = (
        Index("ix_factory_inbound_recognized", "factory_code", "recognized_delivery_no"),
        Index("ix_factory_inbound_note_owner", "created_by", "created_at"),
        {"comment": "工厂到货单草稿与核对状态"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    inbound_no = Column(String(32), nullable=False, unique=True, comment="方舟入库单号")
    factory_code = Column(String(32), nullable=False, comment="工厂编码")
    recognized_delivery_no = Column(String(32), comment="识别单据编号")
    delivery_no = Column(String(32), comment="人工确认单据编号")
    delivery_key = Column(String(80), Computed(
        "CASE WHEN status = 'voided' OR delivery_no IS NULL THEN NULL "
        "ELSE CONCAT(factory_code, ':', delivery_no) END",
    ), unique=True, comment="未作废记录的单据唯一键")
    duplicate_suspected_note_id = Column(BigInteger, comment="疑似已拍记录ID")
    duplicate_of_note_id = Column(BigInteger, comment="确认重复的原记录ID")
    delivery_month = Column(SmallInteger, comment="单据手写月")
    delivery_day = Column(SmallInteger, comment="单据手写日")
    scan_path = Column(String(255), nullable=False, comment="校正图相对路径")
    original_path = Column(String(255), comment="原图相对路径")
    recognition_status = Column(String(16), nullable=False, default="queued", comment="识别状态")
    recognition_attempt_id = Column(String(32), nullable=False, comment="识别尝试标识")
    recognition_queued_at = Column(DateTime, nullable=False, comment="识别排队时间")
    recognition_started_at = Column(DateTime, comment="识别开始时间")
    recognition_finished_at = Column(DateTime, comment="识别结束时间")
    recognition_error = Column(String(255), comment="面向用户的识别错误")
    recognition_raw = Column(JSON, comment="原始结构化识别结果")
    status = Column(String(16), nullable=False, default="draft", comment="单据状态")
    created_by = Column(Integer, nullable=False, comment="创建人ID")
    version = Column(Integer, nullable=False, default=1, comment="乐观锁版本")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_by = Column(Integer, comment="最后操作人ID")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")


class Line(Base):
    __tablename__ = "ark_factory_inbound_lines"
    __table_args__ = (
        UniqueConstraint("note_id", "line_no", name="uq_factory_inbound_line_no"),
        {"comment": "工厂到货单原始识别及核对明细"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    note_id = Column(BigInteger, ForeignKey("ark_factory_inbound_notes.id"), nullable=False, comment="单据ID")
    line_no = Column(Integer, nullable=False, comment="识别行序号")
    batch_id = Column(BigInteger, ForeignKey("ark_factory_inbound_batches.id", name="fk_factory_inbound_line_batch"), index=True, comment="当前确认批次ID")
    raw = Column(JSON, nullable=False, comment="识别原文与疑点")
    values = Column(JSON, nullable=False, comment="当前核对字段")
    match_status = Column(String(16), nullable=False, comment="匹配状态")
    match_data = Column(JSON, nullable=False, comment="确定性匹配与候选快照")
    decision = Column(JSON, comment="人工候选与路线决定及审计信息")
    selected = Column(Boolean, nullable=False, default=False, comment="核对勾选状态")
    writeback_enabled = Column(Boolean, nullable=False, default=True, comment="回写与对应意图")
    created_by = Column(Integer, nullable=False, comment="创建人ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_by = Column(Integer, comment="最后操作人ID")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")


class LineType(Base):
    __tablename__ = "ark_factory_inbound_line_types"
    __table_args__ = {"comment": "工厂到货单识别行类型"}

    code = Column(String(24), primary_key=True, comment="类型编码")
    label = Column(String(32), nullable=False, comment="类型名称")
    is_inbound = Column(Boolean, nullable=False, comment="是否到货行")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")


class Alias(Base):
    __tablename__ = "ark_factory_inbound_aliases"
    __table_args__ = (
        UniqueConstraint("kind", "factory_term", name="uq_factory_inbound_alias_term"),
        {"comment": "工厂到货工艺、颜色及等级词表"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    kind = Column(String(12), nullable=False, comment="词表类别")
    factory_term = Column(String(128), nullable=False, comment="规范化的工厂写法")
    target = Column(String(128), nullable=False, comment="系统目录词条")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")
    source = Column(String(16), nullable=False, comment="词条来源")
    updated_by = Column(Integer, comment="最后操作人ID")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")


class AliasSuggestion(Base):
    __tablename__ = "ark_factory_inbound_alias_suggestions"
    __table_args__ = {"comment": "工厂到货颜色别名审核建议"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    factory_term = Column(String(128), nullable=False, comment="工厂写法")
    target = Column(String(128), nullable=False, comment="期望系统颜色")
    suggested_by = Column(Integer, nullable=False, comment="建议人ID")
    reviewed_by = Column(Integer, comment="审核人ID")
    status = Column(String(16), nullable=False, default="pending", comment="审核状态")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="建议时间")
    reviewed_at = Column(DateTime, comment="审核时间")


class EditLog(Base):
    __tablename__ = "ark_factory_inbound_edit_logs"
    __table_args__ = {"comment": "工厂到货单编号、明细和作废审核记录"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    note_id = Column(BigInteger, ForeignKey("ark_factory_inbound_notes.id"), nullable=False, index=True, comment="单据ID")
    line_id = Column(BigInteger, comment="明细ID快照")
    action = Column(String(24), nullable=False, comment="变更动作")
    before_data = Column(JSON, comment="变更前快照")
    after_data = Column(JSON, comment="变更后快照")
    created_by = Column(Integer, nullable=False, comment="操作人ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="操作时间")
