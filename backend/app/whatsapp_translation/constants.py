"""Stable constants for the WhatsApp translation domain."""

PAIRING_STATUSES = ("pending", "approved", "consumed", "expired", "rejected")
TRANSLATION_DIRECTIONS = ("incoming", "outgoing")
TRANSLATION_LANGUAGES = ("zh-CN", "en", "es", "fr", "ar", "ja")
DETECTED_SOURCE_LANGUAGES = TRANSLATION_LANGUAGES + ("de", "nl")
SUPPORTED_SOURCE_LANGUAGES = ("auto",) + DETECTED_SOURCE_LANGUAGES
SUPPORTED_TARGET_LANGUAGES = TRANSLATION_LANGUAGES
WHATSAPP_TRANSLATION_WRITE_PERMISSION = "whatsapp_translation:write"

ERROR_PAIRING_NOT_FOUND = "pairing_not_found"
ERROR_PAIRING_EXPIRED = "pairing_expired"
ERROR_PAIRING_STATE = "pairing_state"
ERROR_PAIRING_PENDING = "pairing_pending"
ERROR_PAIRING_CONFLICT = "pairing_conflict"
ERROR_USER_INACTIVE = "user_inactive"
ERROR_USER_FORBIDDEN = "user_forbidden"
ERROR_DEVICE_LIMIT = "device_limit"
ERROR_DEVICE_REVOKED = "device_revoked"
ERROR_DAILY_QUOTA = "daily_quota_exceeded"
