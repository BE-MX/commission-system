"""Design Image Studio persistence contract tests."""

from importlib import import_module, util

from sqlalchemy import BigInteger, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.ai.models import AiCallLog
from app.core.config import Settings
from app.core.database import Base


EXPECTED_TABLES = {
    "ark_design_image_sessions",
    "ark_design_image_messages",
    "ark_design_image_assets",
    "ark_design_image_jobs",
    "ark_design_image_job_assets",
}


def _design_image_models():
    spec = util.find_spec("app.design_image.models")
    assert spec is not None, "app.design_image.models must define the new domain"
    return import_module("app.design_image.models")


def test_design_image_tables_and_usage_detail_are_registered():
    _design_image_models()

    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    assert "usage_detail" in AiCallLog.__table__.c
    assert AiCallLog.__table__.c.usage_detail.nullable is True


def test_design_image_tables_expose_the_required_columns():
    _design_image_models()
    expected_columns = {
        "ark_design_image_sessions": {
            "id", "owner_user_id", "title", "status", "created_at", "updated_at",
        },
        "ark_design_image_messages": {
            "id", "session_id", "role", "content", "status", "created_at",
        },
        "ark_design_image_assets": {
            "id", "session_id", "message_id", "asset_type", "storage_path",
            "mime_type", "file_size", "width", "height", "sha256",
            "source_asset_id", "status", "expires_at", "created_by",
            "created_at", "deleted_at",
        },
        "ark_design_image_jobs": {
            "id", "owner_user_id", "session_id", "request_message_id",
            "base_asset_id", "mode", "status", "prompt_snapshot", "parameters",
            "preset_name", "model", "ai_call_log_id", "idempotency_key",
            "output_asset_id", "response_message_id", "retry_of_job_id",
            "claimed_by", "lease_token", "lease_expires_at", "claim_count",
            "provider_attempt_count", "error_code", "error_message",
            "billing_certainty", "input_tokens", "output_tokens", "total_tokens",
            "estimated_cost_microusd", "pricing_snapshot", "started_at",
            "finished_at", "created_at",
        },
        "ark_design_image_job_assets": {
            "id", "job_id", "asset_id", "role", "position",
        },
    }
    for table_name, columns in expected_columns.items():
        assert columns <= set(Base.metadata.tables[table_name].c.keys())


def test_design_image_constraints_indexes_and_fk_types_match_production():
    _design_image_models()
    jobs = Base.metadata.tables["ark_design_image_jobs"]
    job_assets = Base.metadata.tables["ark_design_image_job_assets"]

    job_unique_names = {
        item.name for item in jobs.constraints if isinstance(item, UniqueConstraint)
    }
    job_asset_unique_names = {
        item.name for item in job_assets.constraints if isinstance(item, UniqueConstraint)
    }
    job_asset_checks = {
        item.name for item in job_assets.constraints if isinstance(item, CheckConstraint)
    }
    assert "uq_di_job_owner_idem" in job_unique_names
    assert "uq_di_job_asset" in job_asset_unique_names
    assert "ck_di_job_asset_position" in job_asset_checks

    indexes = {index.name: tuple(col.name for col in index.columns) for index in jobs.indexes}
    assert indexes["idx_di_job_claim"] == (
        "status", "lease_expires_at", "created_at",
    )
    assert indexes["idx_di_job_owner_day"] == (
        "owner_user_id", "created_at", "status",
    )

    mysql_dialect = mysql.dialect()
    for table_name, column_name in (
        ("ark_design_image_sessions", "owner_user_id"),
        ("ark_design_image_assets", "created_by"),
        ("ark_design_image_jobs", "owner_user_id"),
    ):
        column_type = Base.metadata.tables[table_name].c[column_name].type
        assert column_type.dialect_impl(mysql_dialect).unsigned is True

    ai_log_id = jobs.c.ai_call_log_id
    assert isinstance(ai_log_id.type, BigInteger)
    assert getattr(ai_log_id.type.dialect_impl(mysql_dialect), "unsigned", False) is False

    restricted_asset_fks = {
        (fk.parent.name, fk.target_fullname): fk.ondelete
        for table in (jobs, job_assets)
        for fk in table.foreign_keys
        if fk.target_fullname.startswith("ark_design_image_assets.")
    }
    assert restricted_asset_fks
    assert set(restricted_asset_fks.values()) == {"RESTRICT"}


def test_all_design_image_relationships_are_noload():
    models = _design_image_models()

    for model_name in (
        "DesignImageSession",
        "DesignImageMessage",
        "DesignImageAsset",
        "DesignImageJob",
        "DesignImageJobAsset",
    ):
        mapper = getattr(models, model_name).__mapper__
        assert mapper.relationships, f"{model_name} should map its domain relationships"
        assert {rel.lazy for rel in mapper.relationships} == {"noload"}


def test_design_image_settings_have_safe_defaults():
    settings = Settings(_env_file=None)

    assert settings.DESIGN_IMAGE_STORAGE_ROOT == r"D:\WORKSOURCE\design-image"
    assert settings.DESIGN_IMAGE_DAILY_LIMIT == 20
    assert settings.DESIGN_IMAGE_WORKER_CONCURRENCY == 3
    assert settings.DESIGN_IMAGE_WORKER_INTERVAL_SECONDS == 10
    assert settings.DESIGN_IMAGE_LEASE_SECONDS == 420
    assert settings.DESIGN_IMAGE_STALE_SECONDS == 480
    assert settings.DESIGN_IMAGE_DRAFT_TTL_HOURS == 24
    assert settings.DESIGN_IMAGE_MAX_UPLOAD_MB == 20
    assert settings.DESIGN_IMAGE_MAX_PIXELS == 60_000_000
