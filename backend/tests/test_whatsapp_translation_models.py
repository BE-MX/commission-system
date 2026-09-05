from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models import TranslationDevice, TranslationPairing, TranslationUsageDaily
from app.whatsapp_translation import schemas


def test_translation_tables_exclude_chat_plaintext():
    tables = (
        TranslationPairing.__table__,
        TranslationDevice.__table__,
        TranslationUsageDaily.__table__,
    )
    names = {column.name for table in tables for column in table.columns}
    assert not names.intersection({
        "text", "message", "translation", "contact_name", "phone", "chat_id", "html",
    })
    assert TranslationDevice.__table__.c.token_hash.type.length == 64
    assert TranslationPairing.__table__.c.device_code_hash.type.length == 64
    assert TranslationPairing.__table__.c.proposed_token_hash.type.length == 64


def test_usage_unique_constraint_is_beijing_day_user_device():
    constraints = {
        constraint.name for constraint in TranslationUsageDaily.__table__.constraints
    }
    assert "uq_wat_usage_day_user_device" in constraints


def test_whatsapp_translation_settings_defaults():
    settings = Settings()
    assert settings.WHATSAPP_TRANSLATION_EXTENSION_ORIGIN == (
        "chrome-extension://bnkecbkoidckffckbefjjcbchmngjobi"
    )
    assert settings.WHATSAPP_TRANSLATION_PRESET_NAME == "whatsapp_text_translation"
    assert settings.WHATSAPP_TRANSLATION_PAIRING_TTL_MINUTES == 10
    assert settings.WHATSAPP_TRANSLATION_DEVICE_TTL_DAYS == 180
    assert settings.WHATSAPP_TRANSLATION_MAX_DEVICES_PER_USER == 5
    assert settings.WHATSAPP_TRANSLATION_RATE_PER_MINUTE == 30
    assert settings.WHATSAPP_TRANSLATION_DAILY_INPUT_CHARS == 200_000
    assert settings.WHATSAPP_TRANSLATION_MAX_TEXT_CHARS == 4_000
    assert settings.WHATSAPP_TRANSLATION_AI_TIMEOUT_SECONDS == 40
    assert settings.WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION == "1.0.0"


def test_request_and_model_output_use_configured_text_limit(monkeypatch):
    monkeypatch.setattr(
        schemas,
        "get_settings",
        lambda: SimpleNamespace(WHATSAPP_TRANSLATION_MAX_TEXT_CHARS=10_000),
    )
    text = "a" * 5_000

    request = schemas.TranslateRequest(
        request_id="4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63",
        direction="incoming",
        source_language="auto",
        target_language="zh-CN",
        text=text,
    )
    output = schemas.TranslationModelOutput(
        translated_text=text,
        detected_source_language="en",
    )

    assert request.text == text
    assert output.translated_text == text


def test_configured_text_limit_is_still_enforced(monkeypatch):
    monkeypatch.setattr(
        schemas,
        "get_settings",
        lambda: SimpleNamespace(WHATSAPP_TRANSLATION_MAX_TEXT_CHARS=5),
    )

    with pytest.raises(ValueError, match="1-5"):
        schemas.TranslateRequest(
            request_id="4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63",
            direction="incoming",
            source_language="auto",
            target_language="zh-CN",
            text="123456",
        )
