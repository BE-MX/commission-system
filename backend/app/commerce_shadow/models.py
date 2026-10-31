"""Evidence has no foreign key into a consumable financial/stock ledger.

The source stores observations/outbox/reports; the isolated candidate stores only
Execution and Binding from this module. Expected output is never a domain seed.
"""
from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.core.time import beijing_now


class ShadowObservation(Base):
    __tablename__ = "ark_commerce_shadow_observations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_event_id: Mapped[str] = mapped_column(String(128), unique=True)
    invoice_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    local_customer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    payment_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    aggregate_key: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    contract_revision: Mapped[int] = mapped_column(Integer)
    causal_version: Mapped[int] = mapped_column(Integer)
    authority_epoch: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    outcome: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(160))
    resolves_source_event_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    resolution_evidence: Mapped[dict | None] = mapped_column(JSON)
    command: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    dependencies: Mapped[list] = mapped_column(JSON)
    observed_at: Mapped[object] = mapped_column(DateTime, default=beijing_now)
    __table_args__ = (UniqueConstraint("aggregate_key", "request_key", name="uq_shadow_observation_request"),)


class ShadowOutbox(Base):
    __tablename__ = "ark_commerce_shadow_outbox"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    observation_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(128))
    exported_at: Mapped[object | None] = mapped_column(DateTime)


class ShadowDataset(Base):
    __tablename__ = "ark_commerce_shadow_datasets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint: Mapped[dict] = mapped_column(JSON)
    checkpoint_hash: Mapped[str] = mapped_column(String(64))
    target_fingerprint: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[object] = mapped_column(DateTime, default=beijing_now)


class ShadowRun(Base):
    __tablename__ = "ark_commerce_shadow_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    request_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    calculator_version: Mapped[str] = mapped_column(String(64))
    invoice_ids: Mapped[list] = mapped_column(JSON)
    payment_ids: Mapped[list] = mapped_column(JSON, default=list)
    local_customer_ids: Mapped[list] = mapped_column(JSON, default=list)
    through_observation_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[object] = mapped_column(DateTime, default=beijing_now)
    checked_at: Mapped[object | None] = mapped_column(DateTime)


class ShadowResult(Base):
    __tablename__ = "ark_commerce_shadow_results"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    observation_id: Mapped[int] = mapped_column(BigInteger)
    execution_event_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    candidate_outcome: Mapped[str] = mapped_column(String(24))
    actual: Mapped[dict] = mapped_column(JSON)
    checked_at: Mapped[object] = mapped_column(DateTime, default=beijing_now)
    __table_args__ = (UniqueConstraint("run_id", "observation_id", name="uq_shadow_result_sample"),)


class ShadowDifference(Base):
    __tablename__ = "ark_commerce_shadow_differences"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    observation_id: Mapped[int] = mapped_column(BigInteger)
    invoice_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    local_customer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    payment_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    field: Mapped[str] = mapped_column(String(128))
    expected: Mapped[dict] = mapped_column(JSON)
    actual: Mapped[dict] = mapped_column(JSON)
    classification: Mapped[str] = mapped_column(String(24), default="open")
    created_at: Mapped[object] = mapped_column(DateTime, default=beijing_now)


class ShadowReview(Base):
    __tablename__ = "ark_commerce_shadow_reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    difference_id: Mapped[int] = mapped_column(BigInteger, index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    classification: Mapped[str] = mapped_column(String(24))
    evidence: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[object] = mapped_column(DateTime, default=beijing_now)


class ShadowBinding(Base):
    __tablename__ = "ark_commerce_shadow_binding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), unique=True)
    checkpoint_hash: Mapped[str] = mapped_column(String(64))


class ShadowExecution(Base):
    __tablename__ = "ark_commerce_shadow_executions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    first_run_id: Mapped[str] = mapped_column(String(64))
    source_event_id: Mapped[str] = mapped_column(String(128))
    aggregate_key: Mapped[str] = mapped_column(String(128))
    causal_version: Mapped[int] = mapped_column(Integer)
    contract_revision: Mapped[int] = mapped_column(Integer)
    authority_epoch: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24))
    actual: Mapped[dict] = mapped_column(JSON)
    completed_at: Mapped[object] = mapped_column(DateTime, default=beijing_now)
    __table_args__ = (UniqueConstraint("dataset_id", "source_event_id", name="uq_shadow_execution_source"),)


def _immutable(_mapper, _connection, _target):
    raise ValueError("对比原始证据不可修改或删除")


for _model in (ShadowObservation, ShadowDataset, ShadowResult, ShadowReview, ShadowExecution, ShadowBinding):
    event.listen(_model, "before_update", _immutable)
    event.listen(_model, "before_delete", _immutable)
