"""Imported source rows, specialist decisions and immutable export files."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, JSON, LargeBinary, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import deferred

from app.core.database import Base
from app.core.time import beijing_now


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class ImportBatch(Base):
    __tablename__ = "ark_cross_border_imports"
    __table_args__ = {"comment": "跨境申报导入文件批次"}

    id = Column(Integer, primary_key=True, comment="导入批次")
    file_kind = Column(String(10), nullable=False, comment="订单或收款单")
    file_name = Column(String(255), nullable=False, comment="源文件名")
    file_sha256 = Column(String(64), nullable=False, unique=True, comment="文件内容摘要")
    row_count = Column(Integer, nullable=False, comment="源文件行数")
    added = Column(Integer, nullable=False, default=0, comment="新增条目数")
    suspected = Column(Integer, nullable=False, default=0, comment="本批未出现的同号旧条目数")
    content_hashes = Column(JSON, nullable=False, comment="本批条目内容摘要列表，保留批次成员关系")
    imported_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="导入人")
    imported_at = Column(DateTime, nullable=False, default=beijing_now, comment="导入北京时间")


class ImportedRow:
    id = Column(Integer, primary_key=True, comment="条目主键")
    order_no = Column(String(20), nullable=False, index=True, comment="阿里信保订单号")
    occurrence = Column(Integer, nullable=False, comment="相同内容出现序号")
    content_hash = Column(String(64), nullable=False, unique=True, comment="条目稳定身份")
    base_json = Column(JSON, nullable=False, comment="对应传输企业原始行")
    first_import_id = Column(Integer, ForeignKey("ark_cross_border_imports.id"), nullable=False, comment="首次导入批次")
    first_row_no = Column(Integer, nullable=False, comment="首次源表行号")
    last_import_id = Column(Integer, ForeignKey("ark_cross_border_imports.id"), nullable=False, comment="最近出现批次")


class Declaration(ImportedRow, Base):
    __tablename__ = "ark_cross_border_declarations"
    __table_args__ = {"comment": "跨境申报订单条目"}

    head_json = Column(JSON, nullable=False, comment="原始订单头")
    line_json = Column(JSON, nullable=False, comment="对应原始订单明细")
    suspected_changed = Column(Boolean, nullable=False, default=False, comment="最近同号导入未出现")
    status = Column(String(10), nullable=False, default="active", comment="有效或已作废")


class Receipt(ImportedRow, Base):
    __tablename__ = "ark_cross_border_receipts"
    __table_args__ = {"comment": "跨境申报收款条目"}

    receipt_json = Column(JSON, nullable=False, comment="原始收款单行")


class Review(Base):
    __tablename__ = "ark_cross_border_reviews"
    __table_args__ = {"comment": "跨境申报人工核对审计"}

    id = Column(Integer, primary_key=True, comment="审计序号")
    content_hash = Column(String(64), ForeignKey("ark_cross_border_declarations.content_hash"), nullable=False, index=True, comment="决定对应的申报身份")
    action = Column(String(30), nullable=False, comment="核对动作")
    target = Column(BigInteger, comment="指定或确认交运的运单跟踪ID")
    reason = Column(String(500), nullable=False, comment="专员核实原因")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="操作人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="操作北京时间")


class ExportBatch(Base):
    __tablename__ = "ark_cross_border_exports"
    __table_args__ = {"comment": "报关文件与生成审计"}

    id = Column(Integer, primary_key=True, comment="导出记录")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="导出人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="导出北京时间")
    content_hashes = Column(JSON, nullable=False, comment="按文件顺序导出的申报身份")
    order_file = deferred(Column(LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql"), nullable=False, comment="报关订单原文件"))
    receipt_file = deferred(Column(LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql"), nullable=False, comment="报关收款单原文件"))
