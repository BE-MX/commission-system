"""Customer image portal persistence models."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.ai.models import AiCallLog  # noqa: F401 -- registers FK target
from app.auth.models import ArkUser  # noqa: F401 -- registers FK target
from app.core.database import Base


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class CustomerImageProduct(Base):
    __tablename__ = "ark_customer_image_products"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    fixed_prompt = Column(Text, nullable=False)
    output_prompt = Column(Text, nullable=False)
    config_version = Column(Integer, nullable=False, default=1)
    is_published = Column(Boolean, nullable=False, default=False)
    sort = Column(Integer, nullable=False, default=0)
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("config_version > 0", name="ck_ci_product_config_version_positive"),
        Index("idx_ci_product_catalog", "is_published", "category", "sort"),
    )

    assets = relationship("CustomerImageProductAsset", back_populates="product", lazy="noload")
    options = relationship("CustomerImageProductOption", back_populates="product", lazy="noload")
    invite_links = relationship("CustomerImageInviteProduct", back_populates="product", lazy="noload")
    generations = relationship("CustomerImageGeneration", back_populates="product", lazy="noload")


class CustomerImageProductAsset(Base):
    __tablename__ = "ark_customer_image_product_assets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey("ark_customer_image_products.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(16), nullable=False)
    storage_path = Column(String(512), nullable=False)
    mime_type = Column(String(64), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("product_id", "role", "position", name="uq_ci_product_asset_role_position"),
        CheckConstraint("role IN ('cover', 'reference')", name="ck_ci_product_asset_role"),
        CheckConstraint("position >= 0", name="ck_ci_product_asset_position"),
        Index("idx_ci_product_asset_product", "product_id", "role", "position"),
    )

    product = relationship("CustomerImageProduct", back_populates="assets", lazy="noload")


class CustomerImageProductOption(Base):
    __tablename__ = "ark_customer_image_product_options"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey("ark_customer_image_products.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(64), nullable=False)
    label = Column(String(100), nullable=False)
    control_type = Column(String(16), nullable=False)
    required = Column(Boolean, nullable=False, default=False)
    default_value = Column(String(200), nullable=True)
    sort = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("product_id", "key", name="uq_ci_product_option_key"),
        Index("idx_ci_product_option_sort", "product_id", "sort"),
    )

    product = relationship("CustomerImageProduct", back_populates="options", lazy="noload")
    values = relationship("CustomerImageOptionValue", back_populates="option", lazy="noload")


class CustomerImageOptionValue(Base):
    __tablename__ = "ark_customer_image_option_values"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    option_id = Column(BigInteger, ForeignKey("ark_customer_image_product_options.id", ondelete="CASCADE"), nullable=False)
    value = Column(String(200), nullable=False)
    label = Column(String(100), nullable=False)
    prompt_fragment = Column(Text, nullable=False)
    color_hex = Column(String(7), nullable=True)
    pantone_code = Column(String(32), nullable=True)
    sort = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("option_id", "value", name="uq_ci_option_value"),
        Index("idx_ci_option_value_sort", "option_id", "is_active", "sort"),
    )

    option = relationship("CustomerImageProductOption", back_populates="values", lazy="noload")


class CustomerImageInvite(Base):
    __tablename__ = "ark_customer_image_invites"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False)
    customer_name_snapshot = Column(String(200), nullable=False)
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False)
    okki_salesperson_id_snapshot = Column(String(64), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    token_suffix = Column(String(6), nullable=False)
    starts_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    quota_total = Column(Integer, nullable=False)
    quota_used = Column(Integer, nullable=False, default=0)
    current_logo_asset_id = Column(
        BigInteger,
        ForeignKey(
            "ark_customer_image_assets.id",
            name="fk_ci_invite_current_logo_asset",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("quota_total > 0", name="ck_ci_invite_quota_total_positive"),
        CheckConstraint("quota_used >= 0", name="ck_ci_invite_quota_used_nonnegative"),
        CheckConstraint("quota_used <= quota_total", name="ck_ci_invite_quota_within_total"),
        CheckConstraint("expires_at > starts_at", name="ck_ci_invite_expiry_after_start"),
        Index("idx_ci_invite_customer_created", "customer_id", "created_at"),
        Index("idx_ci_invite_creator_created", "created_by", "created_at"),
        Index("idx_ci_invite_expiry", "expires_at", "revoked_at"),
    )

    product_links = relationship("CustomerImageInviteProduct", back_populates="invite", lazy="noload")
    assets = relationship(
        "CustomerImageAsset",
        foreign_keys="CustomerImageAsset.invite_id",
        back_populates="invite",
        lazy="noload",
    )
    current_logo = relationship("CustomerImageAsset", foreign_keys=[current_logo_asset_id], lazy="noload")
    generations = relationship("CustomerImageGeneration", back_populates="invite", lazy="noload")


class CustomerImageInviteProduct(Base):
    __tablename__ = "ark_customer_image_invite_products"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invite_id = Column(BigInteger, ForeignKey("ark_customer_image_invites.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("ark_customer_image_products.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("invite_id", "product_id", name="uq_ci_invite_product"),
        Index("idx_ci_invite_product_product", "product_id", "invite_id"),
    )

    invite = relationship("CustomerImageInvite", back_populates="product_links", lazy="noload")
    product = relationship("CustomerImageProduct", back_populates="invite_links", lazy="noload")


class CustomerImageAsset(Base):
    __tablename__ = "ark_customer_image_assets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invite_id = Column(BigInteger, ForeignKey("ark_customer_image_invites.id", ondelete="RESTRICT"), nullable=False)
    asset_type = Column(String(16), nullable=False)
    storage_path = Column(String(512), nullable=False)
    mime_type = Column(String(64), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("asset_type IN ('logo', 'generated')", name="ck_ci_asset_type"),
        Index("idx_ci_asset_invite_created", "invite_id", "created_at"),
        Index("idx_ci_asset_cleanup", "deleted_at", "created_at"),
    )

    invite = relationship(
        "CustomerImageInvite",
        foreign_keys=[invite_id],
        back_populates="assets",
        lazy="noload",
    )
    logo_generations = relationship(
        "CustomerImageGeneration",
        foreign_keys="CustomerImageGeneration.logo_asset_id",
        back_populates="logo_asset",
        lazy="noload",
    )
    output_generations = relationship(
        "CustomerImageGeneration",
        foreign_keys="CustomerImageGeneration.output_asset_id",
        back_populates="output_asset",
        lazy="noload",
    )


class CustomerImageGeneration(Base):
    __tablename__ = "ark_customer_image_generations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invite_id = Column(BigInteger, ForeignKey("ark_customer_image_invites.id", ondelete="RESTRICT"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("ark_customer_image_products.id", ondelete="RESTRICT"), nullable=False)
    logo_asset_id = Column(BigInteger, ForeignKey("ark_customer_image_assets.id", ondelete="RESTRICT"), nullable=False)
    output_asset_id = Column(BigInteger, ForeignKey("ark_customer_image_assets.id", ondelete="RESTRICT"), nullable=True)
    request_id = Column(String(64), nullable=False)
    product_name_snapshot = Column(String(200), nullable=False)
    config_version_snapshot = Column(Integer, nullable=False)
    option_snapshot = Column(JSON, nullable=False)
    prompt_snapshot = Column(Text, nullable=False)
    reference_asset_ids = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="queued")
    claimed_by = Column(String(128), nullable=True)
    lease_token = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    claim_count = Column(Integer, nullable=False, default=0)
    provider_attempt_count = Column(Integer, nullable=False, default=0)
    preset_name = Column(String(64), nullable=False)
    model = Column(String(128), nullable=True)
    ai_call_log_id = Column(BigInteger, ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    billing_certainty = Column(String(16), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    estimated_cost_microusd = Column(BigInteger, nullable=True)
    pricing_snapshot = Column(JSON, nullable=True)
    quota_refunded_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("invite_id", "request_id", name="uq_ci_generation_invite_request"),
        CheckConstraint("claim_count >= 0", name="ck_ci_generation_claim_count"),
        CheckConstraint("provider_attempt_count >= 0", name="ck_ci_generation_provider_attempt_count"),
        Index("idx_ci_generation_claim", "status", "lease_expires_at", "created_at"),
        Index("idx_ci_generation_invite_created", "invite_id", "created_at"),
    )

    invite = relationship("CustomerImageInvite", back_populates="generations", lazy="noload")
    product = relationship("CustomerImageProduct", back_populates="generations", lazy="noload")
    logo_asset = relationship(
        "CustomerImageAsset",
        foreign_keys=[logo_asset_id],
        back_populates="logo_generations",
        lazy="noload",
    )
    output_asset = relationship(
        "CustomerImageAsset",
        foreign_keys=[output_asset_id],
        back_populates="output_generations",
        lazy="noload",
    )
    ai_call_log = relationship("AiCallLog", lazy="noload")
