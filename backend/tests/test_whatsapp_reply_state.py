from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai.models import AiPreset, AiProvider
from app.bootstrap.seed_whatsapp_reply import reply_parameters, seed_reply_presets
from app.core import time as core_time
from app.core.config import get_settings
from app.whatsapp_translation import reply_state
from app.whatsapp_translation.models import ReplyRequestRecord
from app.whatsapp_translation.errors import WhatsAppTranslationError
from tests.reply_support import request, seed_reply


def migration():
    spec = spec_from_file_location("reply_migration", Path(__file__).parents[1] / "alembic/versions/141_whatsapp_reply_requests.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_round_trip_preserves_existing_tables():
    engine = create_engine("sqlite://")
    module = migration()
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE ark_whatsapp_translation_devices (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO ark_users VALUES (1)")
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert "ark_whatsapp_reply_requests" in inspect(connection).get_table_names()
        columns = {column["name"] for column in inspect(connection).get_columns("ark_whatsapp_reply_requests")}
        assert columns == set(ReplyRequestRecord.__table__.columns.keys())
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM ark_users").scalar_one() == 1
        module.downgrade()
        assert "ark_whatsapp_reply_requests" not in inspect(connection).get_table_names()
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM ark_users").scalar_one() == 1
    engine.dispose()


def test_mysql_migration_matches_unsigned_production_foreign_keys():
    module = migration()
    buffer = StringIO()
    module.op = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": buffer}))
    module.upgrade()
    sql = buffer.getvalue()
    assert "device_id BIGINT UNSIGNED NOT NULL" in sql
    assert "user_id INTEGER UNSIGNED NOT NULL" in sql
    assert "uq_war_device_request" in sql
    assert "FOREIGN KEY(device_id) REFERENCES ark_whatsapp_translation_devices (id)" in sql
    orm = str(CreateTable(ReplyRequestRecord.__table__).compile(dialect=mysql.dialect()))
    assert "device_id BIGINT UNSIGNED NOT NULL" in orm
    assert "user_id INTEGER UNSIGNED NOT NULL" in orm


def test_reply_table_has_only_metadata_fields():
    fields = set(ReplyRequestRecord.__table__.columns.keys())
    assert fields == {"id", "user_id", "device_id", "request_id", "payload_hash", "owner_id", "status", "input_chars", "source_revisions", "timings_ms", "error_code", "created_at", "lease_until", "finished_at"}


def test_beijing_day_quota_rolls_over_even_when_server_clock_is_utc(db, monkeypatch):
    identity, *_, settings = seed_reply(db, monkeypatch)
    instant = [datetime(2026, 9, 7, 15, 59, 59, tzinfo=timezone.utc)]

    class UtcHostClock:
        @staticmethod
        def now(tz=None):
            return instant[0].astimezone(tz) if tz else instant[0].replace(tzinfo=None)

    monkeypatch.setattr(core_time, "datetime", UtcHostClock)
    monkeypatch.setattr(settings, "WHATSAPP_REPLY_DAILY_REQUESTS", 1)
    first, _ = reply_state.reserve_request(db, identity, request(), settings)
    assert first.created_at == datetime(2026, 9, 7, 23, 59, 59)
    assert first.lease_until == datetime(2026, 9, 8, 0, 0, 39)
    reply_state.finish_request(db, first.id, status="failed")
    with pytest.raises(WhatsAppTranslationError):
        reply_state.reserve_request(db, identity, request(), settings)
    instant[0] += timedelta(seconds=2)
    second, _ = reply_state.reserve_request(db, identity, request(), settings)
    assert second.created_at.date().isoformat() == "2026-09-08"


def test_cache_is_bounded_and_expires_without_reading_result(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(reply_state.time, "monotonic", lambda: clock[0])
    cache = reply_state.EphemeralReplyCache(max_entries=2, ttl=5)
    try:
        cache.put(1, "synthetic-one")
        cache.put(2, "synthetic-two")
        cache.put(3, "synthetic-three")
        assert cache.get(1) is None
        assert cache.get(2) == "synthetic-two"
        clock[0] = 106
        # Run the scheduled expiry callback, not lazy result retrieval.
        cache._expire()
        assert cache._values == {}
    finally:
        cache.clear()


def test_seed_creates_separate_disabled_presets_and_preserves_existing(db):
    settings = get_settings()
    provider = AiProvider(name="reply-seed-provider", provider_type="direct", api_base="https://synthetic.invalid", is_enabled=True)
    db.add(provider)
    db.flush()
    base = AiPreset(preset_name=settings.WHATSAPP_TRANSLATION_PRESET_NAME, provider_id=provider.id, model="synthetic-model", parameters={"thinking": {"type": "disabled"}, "max_tokens": 4096}, system_prompt="keep translation prompt", is_enabled=True)
    db.add(base)
    db.commit()
    assert seed_reply_presets(db) == 2
    result = db.query(AiPreset).filter(AiPreset.preset_name.in_([settings.WHATSAPP_REPLY_PLANNER_PRESET, settings.WHATSAPP_REPLY_GENERATOR_PRESET])).all()
    assert len(result) == 2 and all(not row.is_enabled for row in result)
    assert all(row.parameters.get("response_format") == {"type": "json_object"} for row in result)
    result[0].system_prompt = "administrator customization"
    db.commit()
    assert seed_reply_presets(db) == 0
    db.refresh(result[0])
    db.refresh(base)
    assert result[0].system_prompt == "administrator customization"
    assert base.parameters == {"thinking": {"type": "disabled"}, "max_tokens": 4096}
    assert base.system_prompt == "keep translation prompt"


def test_reply_parameters_replace_translation_schema_without_mutating_source():
    source = {"temperature": .1, "response_format": {"type": "json_schema", "json_schema": {"name": "translation_only"}}, "messages": ["synthetic"], "max_tokens": 4096}
    result = reply_parameters(source, 1400)
    assert result == {"temperature": .1, "response_format": {"type": "json_object"}, "max_tokens": 1400}
    assert source["response_format"]["type"] == "json_schema"
    assert source["max_tokens"] == 4096
    assert "response_format" not in reply_parameters(source, 1400, "anthropic")
