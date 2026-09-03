from app.core.config import Settings
from app.models import TranslationDevice, TranslationPairing, TranslationUsageDaily


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
    assert settings.WHATSAPP_TRANSLATION_AI_TIMEOUT_SECONDS == 15
    assert settings.WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION == "1.0.0"
