"""Durable file publication records, independent of business-row deletion."""
from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, JSON
from app.core.database import Base
from app.core.time import beijing_now


class StorageTransfer(Base):
    __tablename__ = 'ark_storage_transfers'
    __table_args__ = (Index('ix_storage_transfer_claim', 'source_instance', 'status', 'next_attempt_at'),)
    id = Column(String(64), primary_key=True, comment='SHA256 of domain and immutable relative key')
    domain = Column(String(64), nullable=False, comment='Storage domain')
    object_key = Column(String(768), nullable=False, comment='Immutable relative object key')
    source_instance = Column(String(128), nullable=False, comment='Instance owning durable local original')
    file_size = Column(BigInteger, nullable=False, comment='Original byte count')
    sha256 = Column(String(64), nullable=False, comment='Original SHA256')
    content_type = Column(String(128), nullable=False, comment='Content MIME type')
    status = Column(String(16), nullable=False, default='pending', comment='pending/running/ready/deleted')
    attempts = Column(Integer, nullable=False, default=0, comment='Claim count')
    lease_token = Column(String(64), nullable=True, comment='Fencing token')
    lease_until = Column(DateTime, nullable=True, comment='Lease expiry, Beijing time')
    next_attempt_at = Column(DateTime, nullable=False, default=beijing_now, comment='Retry or tombstone reconciliation time')
    last_error = Column(String(128), nullable=True, comment='Redacted failure category')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='Created, Beijing time')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='Updated, Beijing time')


class StorageAlias(Base):
    """Atomic logical names for intentionally replaceable cloud objects."""
    __tablename__ = 'ark_storage_aliases'
    id = Column(String(64), primary_key=True, comment='SHA256 of domain and logical key')
    domain = Column(String(64), nullable=False, comment='Storage domain')
    logical_key = Column(String(768), nullable=False, comment='Stable business name')
    target_key = Column(String(768), nullable=True, comment='Immutable object key; NULL means deleted')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='Created, Beijing time')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='Updated, Beijing time')


class StoragePublication(Base):
    """Same-transaction completion receipts prevent stale multipart retries."""
    __tablename__ = 'ark_storage_publications'
    id = Column(String(64), primary_key=True, comment='SHA256 of domain/key/upload identity')
    response_json = Column(JSON, nullable=False, comment='Immutable successful publication response')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='Created, Beijing time')
