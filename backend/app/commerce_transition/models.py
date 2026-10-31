"""Coordination records, never a second invoice, stock or money ledger."""
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, DateTime,
                        ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import synonym

from app.core.database import Base
from app.core.time import beijing_now


def identity_string(length):
    return String(length).with_variant(mysql.VARCHAR(length, collation="utf8mb4_bin"), "mysql")


class PlatformPolicy(Base):
    __tablename__ = "ark_commerce_transition_policy"
    id = Column(Integer, primary_key=True, autoincrement=False, comment="Singleton coordination lock, always 1")
    phase = Column(String(24), nullable=False, default="legacy_only", comment="Installed platform phase")
    version = Column(Integer, nullable=False, default=1, comment="Policy optimistic version")
    min_writer_version = Column(Integer, nullable=False, default=1, comment="Minimum compatible writer protocol")
    writer_inventory_verified = Column(Boolean, nullable=False, default=False, comment="All writers inventoried with enforced receipts")
    inventory_evidence = Column(JSON, nullable=True, comment="Writer inventory and enforcement evidence")
    local_ever_effective = Column(Boolean, nullable=False, default=False, comment="Irreversible local economic responsibility marker")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="Beijing policy time")
    __table_args__ = (CheckConstraint("id = 1", name="ck_transition_policy_singleton"),
                     CheckConstraint("phase IN ('legacy_only','transition','local_only')", name="ck_transition_phase"))


class WriterReceipt(Base):
    __tablename__ = "ark_commerce_writer_receipts"
    writer_key = Column(identity_string(128), primary_key=True, comment="Stable worker, script or manual credential identity")
    protocol_version = Column(Integer, nullable=False, comment="Verified route and epoch protocol version")
    status = Column(String(16), nullable=False, comment="compatible/revoked/unknown")
    state = synonym("status")
    evidence = Column(JSON, nullable=False, comment="Enforcement or revocation verification receipt")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="Beijing receipt time")
    __table_args__ = (CheckConstraint("status IN ('compatible','revoked','unknown')", name="ck_transition_writer_state"),)


class InvoiceAuthority(Base):
    __tablename__ = "ark_commerce_invoice_authorities"
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id", ondelete="RESTRICT"), primary_key=True, comment="Only formal invoice identity")
    route = Column(String(16), nullable=False, comment="legacy/local formal owner")
    epoch = Column(Integer, nullable=False, default=1, comment="Authority generation")
    lock_version = Column(Integer, nullable=False, default=1, comment="CAS lock shared by sending and transfer")
    status = Column(String(16), nullable=False, default="active", comment="active/frozen")
    state = synonym("status")
    confirmed_at = Column(DateTime, nullable=True, comment="Beijing route finalization time")
    source_evidence = Column(JSON, nullable=False, comment="Explicit historical source or new draft evidence")
    settled_evidence = Column(JSON, nullable=True, comment="Verified complete economic closure, never inferred from invoice status")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Beijing creation time")
    __table_args__ = (CheckConstraint("route IN ('legacy','local')", name="ck_transition_authority_route"),
                     CheckConstraint("status IN ('active','frozen')", name="ck_transition_authority_state"),
                     CheckConstraint("epoch > 0", name="ck_transition_authority_epoch"))


class AuthorityEvent(Base):
    __tablename__ = "ark_commerce_authority_events"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Append only authority history")
    invoice_id = Column(BigInteger, ForeignKey("ark_commerce_invoice_authorities.invoice_id", ondelete="RESTRICT"), nullable=False, index=True, comment="Invoice ownership")
    epoch = Column(Integer, nullable=False, comment="Resulting generation")
    action = Column(String(32), nullable=False, comment="initialize/draft_route/confirm/freeze/transfer")
    payload = Column(JSON, nullable=False, comment="Evidence and original ownership")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Beijing event time")


class SendingClaim(Base):
    __tablename__ = "ark_commerce_sending_claims"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Persistent external sending responsibility")
    invoice_id = Column(BigInteger, ForeignKey("ark_commerce_invoice_authorities.invoice_id", ondelete="RESTRICT"), nullable=False, index=True, comment="Original formal invoice")
    request_key = Column(identity_string(128), nullable=False, unique=True, comment="Stable original external request identity")
    operation = Column(String(64), nullable=False, comment="External command type")
    route = Column(String(16), nullable=False, comment="Original route")
    epoch = Column(Integer, nullable=False, comment="Original authority epoch")
    payload_hash = Column(String(64), nullable=False, comment="Canonical command digest")
    responsibilities = Column(JSON, nullable=False, comment="Persistent stock and funding references")
    status = Column(String(24), nullable=False, default="sending", comment="sending/unknown/succeeded/failed/not_sent")
    state = synonym("status")
    active_invoice_key = Column(BigInteger, nullable=True, unique=True, comment="One unresolved external responsibility per invoice; terminal NULL")
    external_id = Column(identity_string(128), nullable=True, comment="Original remote economic identity")
    lease_until = Column(DateTime, nullable=True, comment="Observation only; expiration never releases responsibility")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Beijing claim time")
    terminal_at = Column(DateTime, nullable=True, comment="Beijing proven terminal result time")
    __table_args__ = (CheckConstraint("status IN ('sending','unknown','succeeded','failed','not_sent')", name="ck_transition_claim_state"),)


class ClaimEvidence(Base):
    __tablename__ = "ark_commerce_claim_evidence"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Append only late and recovery evidence")
    claim_id = Column(BigInteger, ForeignKey("ark_commerce_sending_claims.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Original sending claim")
    outcome = Column(String(24), nullable=False, comment="Observed result, including contradictions")
    evidence = Column(JSON, nullable=False, comment="Immutable callback or original-request readback")
    external_id = Column(identity_string(128), nullable=True, comment="Observed remote identity")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Beijing observation time")


class ResourceScope(Base):
    __tablename__ = "ark_commerce_resource_scopes"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Exclusive physical responsibility scope")
    resource_kind = Column(String(24), nullable=False, comment="sku/material/production")
    resource_key = Column(identity_string(128), nullable=False, comment="Stable physical SKU or material identity")
    warehouse_key = Column(identity_string(128), nullable=False, comment="Warehouse bucket or * for all physical stock")
    route = Column(String(16), nullable=False, comment="Only formal route allowed to use the scope")
    status = Column(String(16), nullable=False, default="active", comment="active/frozen")
    state = synonym("status")
    evidence = Column(JSON, nullable=False, comment="Count checkpoint, old responsibility closure and writer exclusion")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Beijing scope time")
    __table_args__ = (UniqueConstraint("resource_kind", "resource_key", "warehouse_key", name="uq_transition_resource_scope"),)


class BankAccountDomain(Base):
    __tablename__ = "ark_commerce_bank_domains"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Closed collection subject/account/channel domain")
    subject_key = Column(identity_string(96), nullable=False, comment="Receiving legal subject identity")
    account_key = Column(identity_string(96), nullable=False, comment="Stable account identity, no raw account secret")
    channel = Column(identity_string(64), nullable=False, comment="Verified transaction identity channel")
    legacy_identity_complete = Column(Boolean, nullable=False, default=False, comment="All legacy, unallocated and remote entries reconciled")
    enforced = Column(Boolean, nullable=False, default=False, comment="All entry writers constrained or revoked")
    exclusive_route = Column(String(16), nullable=True, comment="Optional whole domain exclusion")
    evidence = Column(JSON, nullable=False, comment="Account inventory, completeness and enforcement receipts")
    version = Column(Integer, nullable=False, default=1, comment="Domain coordination version")
    __table_args__ = (UniqueConstraint("subject_key", "account_key", "channel", name="uq_transition_bank_domain"),)


class BankIdentity(Base):
    __tablename__ = "ark_commerce_bank_identities"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="One real payment economic identity across routes")
    domain_id = Column(BigInteger, ForeignKey("ark_commerce_bank_domains.id", ondelete="RESTRICT"), nullable=False, comment="Verified identity domain")
    transaction_id = Column(identity_string(128), nullable=False, comment="Bank verified nonempty transaction identifier")
    route = Column(String(16), nullable=False, comment="Only formal route consuming this principal")
    currency = Column(String(16), nullable=False, comment="Original currency")
    amount = Column(Numeric(18, 2), nullable=False, comment="Original immutable total principal")
    payer_evidence = Column(JSON, nullable=False, comment="Bank payer evidence, never a fabricated random key")
    payment_ref = Column(identity_string(128), nullable=True, unique=True, comment="One formal money ledger identity, bound in same transaction")
    settled_evidence = Column(JSON, nullable=True, comment="Verified funds and aftersales closure")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Beijing registration time")
    __table_args__ = (UniqueConstraint("domain_id", "transaction_id", name="uq_transition_bank_identity"),
                     CheckConstraint("amount > 0", name="ck_transition_bank_amount"))


class ResponsibilityGroup(Base):
    __tablename__ = "ark_commerce_responsibility_groups"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Shared payment, production or commission responsibility")
    kind = Column(String(24), nullable=False, comment="payment/production/reservation/commission")
    responsibility_key = Column(identity_string(128), nullable=False, comment="Original stable consumed economic identity")
    complete = Column(Boolean, nullable=False, default=False, comment="Full related object set verified")
    evidence = Column(JSON, nullable=False, comment="Original relationship inventory and checkpoint")
    __table_args__ = (UniqueConstraint("kind", "responsibility_key", name="uq_transition_responsibility"),)


class ResponsibilityMember(Base):
    __tablename__ = "ark_commerce_responsibility_members"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Shared liability relationship")
    group_id = Column(BigInteger, ForeignKey("ark_commerce_responsibility_groups.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Original responsibility group")
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Full affected formal invoice identity")
    amount = Column(Numeric(18, 3), nullable=True, comment="Original consumed amount or quantity; not a new available opening")
    __table_args__ = (UniqueConstraint("group_id", "invoice_id", name="uq_transition_responsibility_member"),)


class TransferPreparation(Base):
    __tablename__ = "ark_commerce_transfer_preparations"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="Recoverable frozen responsibility closure transfer")
    request_key = Column(identity_string(128), nullable=False, unique=True, comment="Stable transfer preparation identity")
    source_route = Column(String(16), nullable=False, comment="Original ownership")
    target_route = Column(String(16), nullable=False, comment="Destination ownership")
    status = Column(String(24), nullable=False, comment="waiting/ready/completed")
    state = synonym("status")
    manifest_hash = Column(String(64), nullable=False, comment="Immutable closure and checkpoint digest")
    manifest = Column(JSON, nullable=False, comment="Invoice IDs, original epochs, responsibility closure and checkpoint")
    verification = Column(JSON, nullable=True, comment="Contract/funds/fulfillment/inventory/production/media/commission evidence")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="Beijing preparation time")
    completed_at = Column(DateTime, nullable=True, comment="Beijing atomic ownership switch time")
