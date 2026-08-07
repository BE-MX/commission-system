"""Customer image portal persistence contract tests."""

from importlib import import_module, util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import CHAR, BigInteger, CheckConstraint, Integer, JSON, UniqueConstraint, create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import Settings
from app.core.database import Base


EXPECTED_TABLES = {
    "ark_customer_image_products",
    "ark_customer_image_product_assets",
    "ark_customer_image_product_options",
    "ark_customer_image_option_values",
    "ark_customer_image_invites",
    "ark_customer_image_invite_products",
    "ark_customer_image_assets",
    "ark_customer_image_generations",
}
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _models():
    spec = util.find_spec("app.customer_image.models")
    assert spec is not None, "app.customer_image.models must define the new domain"
    return import_module("app.customer_image.models")


def _migration_module():
    path = BACKEND_ROOT / "alembic" / "versions" / "098_customer_image_portal.py"
    spec = util.spec_from_file_location("migration_098_customer_image_portal", path)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_customer_image_migration_is_linear_from_revision_097():
    migration = _migration_module()

    assert migration.revision == "098_customer_image_portal"
    assert migration.down_revision == "097_salary_calc_flags"


def test_customer_image_tables_and_required_columns_are_registered():
    _models()

    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    expected_columns = {
        "ark_customer_image_products": {
            "id", "name", "category", "description", "fixed_prompt",
            "output_prompt", "config_version", "is_published", "sort",
            "created_by", "created_at", "updated_at",
        },
        "ark_customer_image_product_assets": {
            "id", "product_id", "role", "storage_path", "mime_type",
            "file_size", "width", "height", "sha256", "position", "created_at",
            "retired_at",
        },
        "ark_customer_image_product_options": {
            "id", "product_id", "key", "label", "control_type", "required",
            "default_value", "sort", "created_at", "updated_at",
        },
        "ark_customer_image_option_values": {
            "id", "option_id", "value", "label", "prompt_fragment", "color_hex",
            "pantone_code", "sort", "is_active", "created_at", "updated_at",
        },
        "ark_customer_image_invites": {
            "id", "customer_id", "customer_name_snapshot", "created_by",
            "okki_salesperson_id_snapshot", "token_hash", "token_suffix",
            "starts_at", "expires_at", "quota_total", "quota_used",
            "current_logo_asset_id", "revoked_at", "created_at",
        },
        "ark_customer_image_invite_products": {
            "id", "invite_id", "product_id", "created_at",
        },
        "ark_customer_image_assets": {
            "id", "invite_id", "asset_type", "storage_path", "mime_type",
            "file_size", "width", "height", "sha256", "created_at", "deleted_at",
        },
        "ark_customer_image_generations": {
            "id", "invite_id", "product_id", "logo_asset_id", "output_asset_id",
            "request_id", "product_name_snapshot", "config_version_snapshot",
            "option_snapshot", "prompt_snapshot", "reference_asset_ids", "status",
            "claimed_by", "lease_token", "lease_expires_at", "claim_count",
            "provider_attempt_count", "preset_name", "model", "ai_call_log_id",
            "error_code", "error_message", "billing_certainty", "input_tokens",
            "output_tokens", "total_tokens", "estimated_cost_microusd",
            "pricing_snapshot", "quota_refunded_at", "started_at", "finished_at",
            "created_at",
        },
    }
    for table_name, columns in expected_columns.items():
        assert columns <= set(Base.metadata.tables[table_name].c.keys())


def test_invitation_never_persists_plaintext_token():
    models = _models()
    columns = models.CustomerImageInvite.__table__.columns.keys()

    assert "token_hash" in columns
    assert "token_suffix" in columns
    assert "token" not in columns


def test_invitation_token_hash_uses_fixed_width_sha256_storage(monkeypatch):
    models = _models()
    token_hash_type = models.CustomerImageInvite.__table__.c.token_hash.type
    migration = _migration_module()
    migration_token_hash_types = []

    def capture_table(name, *items, **_kwargs):
        if name == "ark_customer_image_invites":
            migration_token_hash_types.extend(
                item.type
                for item in items
                if getattr(item, "name", None) == "token_hash"
            )

    monkeypatch.setattr(migration.op, "create_table", capture_table)
    monkeypatch.setattr(migration.op, "create_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "add_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "create_foreign_key", lambda *_args, **_kwargs: None)
    migration.upgrade()

    assert isinstance(token_hash_type, CHAR)
    assert token_hash_type.length == 64
    assert len(migration_token_hash_types) == 1
    assert isinstance(migration_token_hash_types[0], CHAR)
    assert migration_token_hash_types[0].length == 64


def test_customer_image_constraints_freeze_generation_and_scope_idempotency():
    _models()
    product_assets = Base.metadata.tables["ark_customer_image_product_assets"]
    product_options = Base.metadata.tables["ark_customer_image_product_options"]
    option_values = Base.metadata.tables["ark_customer_image_option_values"]
    invite_products = Base.metadata.tables["ark_customer_image_invite_products"]
    generations = Base.metadata.tables["ark_customer_image_generations"]

    def unique_names(table):
        return {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert "uq_ci_product_asset_role_position" not in unique_names(product_assets)
    assert product_assets.c.retired_at.nullable is True
    assert "uq_ci_product_option_key" in unique_names(product_options)
    assert "uq_ci_option_value" in unique_names(option_values)
    assert "uq_ci_invite_product" in unique_names(invite_products)
    assert "uq_ci_generation_invite_request" in unique_names(generations)
    assert isinstance(generations.c.reference_asset_ids.type, JSON)
    assert generations.c.reference_asset_ids.nullable is False


def test_customer_image_domain_ids_share_sqlite_autoincrement_type():
    models = _models()
    customer_tables = [Base.metadata.tables[name] for name in EXPECTED_TABLES]
    sqlite_type = models.CUSTOMER_IMAGE_ID.dialect_impl(sqlite.dialect())
    mysql_type = models.CUSTOMER_IMAGE_ID.dialect_impl(mysql.dialect())

    assert type(sqlite_type) is Integer
    assert isinstance(mysql_type, BigInteger)
    for table in customer_tables:
        assert table.c.id.type is models.CUSTOMER_IMAGE_ID
        for fk in table.foreign_keys:
            if fk.target_fullname.split(".", 1)[0] in EXPECTED_TABLES:
                assert fk.parent.type is models.CUSTOMER_IMAGE_ID


def test_sqlite_flush_autogenerates_customer_image_ids_without_explicit_values():
    models = _models()
    engine = create_engine("sqlite:///:memory:")
    tables = [ArkUser.__table__, *(Base.metadata.tables[name] for name in EXPECTED_TABLES)]
    Base.metadata.create_all(engine, tables=tables)

    with Session(engine) as session:
        now = datetime.now(UTC)
        user = ArkUser(
            username="ci-owner",
            password_hash="x",
            real_name="CI Owner",
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.flush()

        product = models.CustomerImageProduct(
            name="Wig",
            category="wig",
            fixed_prompt="keep logo exact",
            output_prompt="catalog image",
            created_by=user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(product)
        session.flush()

        invite = models.CustomerImageInvite(
            customer_id="customer-1",
            customer_name_snapshot="Customer One",
            created_by=user.id,
            okki_salesperson_id_snapshot="1007",
            token_hash="a" * 64,
            token_suffix="aaaaaa",
            starts_at=now,
            expires_at=now + timedelta(days=1),
            quota_total=2,
            created_at=now,
        )
        session.add(invite)
        session.flush()

        logo = models.CustomerImageAsset(
            invite_id=invite.id,
            asset_type="logo",
            storage_path="invite/logo.png",
            mime_type="image/png",
            file_size=8,
            width=1,
            height=1,
            sha256="b" * 64,
            created_at=now,
        )
        session.add(logo)
        session.flush()
        invite.current_logo_asset_id = logo.id

        generation = models.CustomerImageGeneration(
            invite_id=invite.id,
            product_id=product.id,
            logo_asset_id=logo.id,
            request_id="request-1",
            product_name_snapshot=product.name,
            config_version_snapshot=product.config_version,
            option_snapshot={},
            prompt_snapshot="prompt",
            reference_asset_ids=[],
            preset_name="design_image_generation",
            created_at=now,
        )
        session.add(generation)
        session.flush()

        assert all(row.id is not None for row in (product, invite, logo, generation))


def test_product_asset_has_retirement_lookup_index_in_model_and_migration():
    _models()
    product_assets = Base.metadata.tables["ark_customer_image_product_assets"]
    migration = _migration_module()
    migration_indexes = []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(migration.op, "create_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, *_args, **_kwargs: migration_indexes.append(name),
    )
    monkeypatch.setattr(migration.op, "add_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "create_foreign_key", lambda *_args, **_kwargs: None)
    try:
        migration.upgrade()
    finally:
        monkeypatch.undo()

    assert "idx_ci_product_asset_current" in {index.name for index in product_assets.indexes}
    assert "idx_ci_product_asset_current" in migration_indexes


def test_invite_quota_and_current_logo_constraints_are_explicit():
    _models()
    invites = Base.metadata.tables["ark_customer_image_invites"]
    check_names = {
        constraint.name
        for constraint in invites.constraints
        if isinstance(constraint, CheckConstraint)
    }
    logo_fk = next(iter(invites.c.current_logo_asset_id.foreign_keys))

    assert {"ck_ci_invite_quota_total_positive", "ck_ci_invite_quota_used_nonnegative"} <= check_names
    assert logo_fk.target_fullname == "ark_customer_image_assets.id"
    assert logo_fk.ondelete == "RESTRICT"
    assert logo_fk.name == "fk_ci_invite_current_logo_asset"
    assert logo_fk.use_alter is True


def test_customer_image_user_foreign_keys_match_unsigned_ark_user_ids():
    _models()
    mysql_dialect = mysql.dialect()

    for table_name, column_name in (
        ("ark_customer_image_products", "created_by"),
        ("ark_customer_image_invites", "created_by"),
    ):
        column_type = Base.metadata.tables[table_name].c[column_name].type
        assert column_type.dialect_impl(mysql_dialect).unsigned is True


def test_customer_image_settings_have_fixed_defaults():
    settings = Settings(_env_file=None)

    assert settings.CUSTOMER_IMAGE_PRESET_NAME == "design_image_generation"
    assert settings.CUSTOMER_IMAGE_WORKER_CONCURRENCY == 2
    assert settings.CUSTOMER_IMAGE_LEASE_SECONDS == 420
    assert settings.CUSTOMER_IMAGE_STALE_SECONDS == 480
    assert settings.CUSTOMER_IMAGE_RETENTION_DAYS == 30
    assert settings.CUSTOMER_IMAGE_PUBLIC_RATE_PER_MINUTE == 30
    assert settings.CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS == 500


@pytest.mark.parametrize(
    "field_name",
    [
        "CUSTOMER_IMAGE_WORKER_CONCURRENCY",
        "CUSTOMER_IMAGE_LEASE_SECONDS",
        "CUSTOMER_IMAGE_STALE_SECONDS",
        "CUSTOMER_IMAGE_RETENTION_DAYS",
        "CUSTOMER_IMAGE_PUBLIC_RATE_PER_MINUTE",
        "CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS",
    ],
)
@pytest.mark.parametrize("invalid_value", [0, -1])
def test_customer_image_numeric_settings_must_be_positive(field_name, invalid_value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field_name: invalid_value})


@pytest.mark.parametrize(
    ("lease_seconds", "stale_seconds"),
    [(420, 420), (421, 420)],
)
def test_customer_image_stale_threshold_must_exceed_lease(lease_seconds, stale_seconds):
    with pytest.raises(ValueError, match="CUSTOMER_IMAGE_STALE_SECONDS.*CUSTOMER_IMAGE_LEASE_SECONDS"):
        Settings(
            _env_file=None,
            CUSTOMER_IMAGE_LEASE_SECONDS=lease_seconds,
            CUSTOMER_IMAGE_STALE_SECONDS=stale_seconds,
        )
