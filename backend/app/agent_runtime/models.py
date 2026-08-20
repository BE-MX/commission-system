"""ORM models for the governed Agent runtime control plane."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
LONG_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")
MEDIUM_TEXT = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class AgentProfile(Base):
    __tablename__ = "ark_agent_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    profile_key = Column(String(64), nullable=False, comment="稳定Profile业务键")
    version = Column(Integer, nullable=False, comment="不可变配置版本")
    name = Column(String(120), nullable=False, comment="显示名称")
    description = Column(String(500), comment="能力与边界说明")
    runtime = Column(String(32), nullable=False, comment="dsh/openclaw/native")
    mode = Column(String(20), nullable=False, comment="interactive/scheduled/shadow")
    model_preset = Column(String(64), nullable=False, comment="方舟AI Preset名称")
    system_prompt = Column(LONG_TEXT, nullable=False, comment="该版本系统提示词")
    prompt_hash = Column(String(64), nullable=False, comment="系统提示词SHA-256")
    skill_manifest = Column(JSON, nullable=False, default=list, comment="Skill及版本清单")
    tool_allowlist = Column(JSON, nullable=False, default=list, comment="允许工具名列表")
    limits_json = Column(JSON, nullable=False, default=dict, comment="步数/并发/Token/超时限制")
    policy_json = Column(JSON, nullable=False, default=dict, comment="数据与执行策略")
    output_schema = Column(JSON, nullable=False, default=dict, comment="成果JSON Schema")
    status = Column(String(16), nullable=False, default="active", comment="active/inactive")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("profile_key", "version", name="uq_agent_profile_key_version"),
        Index("idx_agent_profile_status", "status", "profile_key", "version"),
        {"comment": "Agent不可变配置版本"},
    )


class AgentSession(Base):
    __tablename__ = "ark_agent_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False)
    profile_id = Column(BigInteger, ForeignKey("ark_agent_profiles.id", ondelete="RESTRICT"), nullable=False)
    title = Column(String(255), nullable=False)
    context_type = Column(String(40))
    context_id = Column(String(128))
    runtime_session_id = Column(String(255))
    status = Column(String(16), nullable=False, default="active")
    last_event_seq = Column(Integer, nullable=False, default=0)
    summary_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_session_owner", "owner_user_id", "status", "updated_at"),
        Index("idx_agent_session_context", "context_type", "context_id"),
        {"comment": "Agent业务会话"},
    )


class AgentRun(Base):
    __tablename__ = "ark_agent_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    session_id = Column(BigInteger, ForeignKey("ark_agent_sessions.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(BigInteger, ForeignKey("ark_agent_profiles.id", ondelete="RESTRICT"), nullable=False)
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    trigger_type = Column(String(32), nullable=False)
    source_runtime = Column(String(32), nullable=False)
    mode = Column(String(20), nullable=False)
    business_ref_type = Column(String(40))
    business_ref_id = Column(String(128))
    input_json = Column(JSON, nullable=False, default=dict)
    context_snapshot = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="queued")
    cancel_requested = Column(Boolean, nullable=False, default=False)
    claimed_by = Column(String(128))
    lease_token_hash = Column(String(64))
    lease_expires_at = Column(DateTime)
    runtime_run_id = Column(String(255))
    attempt_no = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    steps_used = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Numeric(14, 6), nullable=False, default=0)
    error_code = Column(String(64))
    error_message = Column(String(1000))
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_agent_run_owner_idem"),
        Index("idx_agent_run_claim", "status", "lease_expires_at", "created_at"),
        Index("idx_agent_run_owner", "owner_user_id", "updated_at"),
        Index("idx_agent_run_business", "business_ref_type", "business_ref_id"),
        {"comment": "Agent单次任务与租约状态"},
    )


class AgentEvent(Base):
    __tablename__ = "ark_agent_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(BigInteger, ForeignKey("ark_agent_sessions.id", ondelete="CASCADE"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    event_id = Column(String(128), nullable=False)
    event_type = Column(String(64), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    actor_type = Column(String(32), nullable=False)
    visibility = Column(String(16), nullable=False, default="user")
    payload_json = Column(JSON, nullable=False, default=dict)
    raw_payload_cipher = Column(MEDIUM_TEXT)
    source_event_ids = Column(JSON, nullable=False, default=list)
    payload_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence_no", name="uq_agent_event_run_seq"),
        UniqueConstraint("run_id", "event_id", name="uq_agent_event_run_event"),
        Index("idx_agent_event_session", "session_id", "created_at"),
        Index("idx_agent_event_type", "event_type", "created_at"),
        {"comment": "Agent追加式运行事件"},
    )


class AgentArtifact(Base):
    __tablename__ = "ark_agent_artifacts"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id", ondelete="CASCADE"), nullable=False)
    artifact_type = Column(String(64), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    title = Column(String(255))
    content_json = Column(JSON, nullable=False, default=dict)
    evidence_json = Column(JSON, nullable=False, default=list)
    content_sha256 = Column(String(64), nullable=False)
    validation_status = Column(String(20), nullable=False, default="pending")
    validation_errors = Column(JSON, nullable=False, default=list)
    decision_status = Column(String(20), nullable=False, default="draft")
    decided_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"))
    decided_at = Column(DateTime)
    feedback_note = Column(String(1000))
    business_ref_type = Column(String(40))
    business_ref_id = Column(String(128))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "artifact_type", "content_sha256", name="uq_agent_artifact_content"),
        Index("idx_agent_artifact_run", "run_id", "artifact_type"),
        Index("idx_agent_artifact_decision", "decision_status", "created_at"),
        {"comment": "Agent结构化成果与业务决策"},
    )

