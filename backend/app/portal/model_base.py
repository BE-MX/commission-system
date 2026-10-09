"""Shared column types for portal persistence in commission_db."""

from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import INTEGER

from app.core.time import beijing_now


PREFIX = "ark_order_portal_"
ID = BigInteger().with_variant(Integer(), "sqlite")
USER_ID = Integer().with_variant(INTEGER(unsigned=True), "mysql")


class Record:
    id = Column(ID, primary_key=True, autoincrement=True, comment='数据库主键')
    public_id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()), comment='对外稳定UUID，不承载授权')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='最后修改时间，北京时间')


class Versioned:
    row_version = Column(BigInteger, nullable=False, default=1, comment='并发更新版本')


def reference(table: str, *, nullable=False, unique=False):
    return Column(ID, ForeignKey(PREFIX + table + ".id", ondelete="RESTRICT"),
                  nullable=nullable, unique=unique, comment=f"门户{table}关联记录")


def employee(*, nullable=False):
    return Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=nullable, comment="方舟员工ID，不是客户账号ID")
