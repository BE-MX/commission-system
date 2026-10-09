"""Validate portal launch configuration without creating users or contacting services."""

from urllib.parse import urlsplit


def employee_origin(settings):
    value = settings.PORTAL_EMPLOYEE_ORIGIN
    parsed = urlsplit(value)
    local = parsed.hostname in {'localhost', '127.0.0.1'} and settings.APP_ENV != 'production'
    if not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')):
        raise ValueError('Portal employee origin must be an exact trusted origin')
    return value


def validate_configuration(settings):
    if settings.PORTAL_NOTIFICATION_ENABLED:
        if not settings.PORTAL_ENABLED or not settings.PORTAL_MAIL_ENABLED:
            raise ValueError("Portal notifications require portal and mail delivery")
        employee_origin(settings)
    if not settings.PORTAL_ENABLED:
        if settings.PORTAL_WRITES_ENABLED or settings.PORTAL_INVOICE_ENABLED:
            raise ValueError("Portal transaction switches require PORTAL_ENABLED")
        return
    parsed = urlsplit(settings.PORTAL_ORIGIN)
    local = parsed.hostname in {"localhost", "127.0.0.1"} and settings.APP_ENV != "production"
    if not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("PORTAL_ORIGIN must be an exact origin without path or credentials")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("PORTAL_ORIGIN requires HTTPS")
    csrf_key = settings.PORTAL_CSRF_KEYS.get(settings.PORTAL_CSRF_KEY_VERSION, "")
    mail_key = settings.PORTAL_MAIL_KEYS.get(settings.PORTAL_MAIL_KEY_VERSION, "")
    if len(csrf_key.encode()) < 32 or len(settings.PORTAL_OTP_SECRET.encode()) < 32:
        raise ValueError("Portal CSRF and OTP keys must each have at least 32 bytes")
    if len(mail_key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in mail_key):
        raise ValueError("Portal mail key must encode exactly 32 bytes as hexadecimal")
    csrf_bytes = {key.encode() for key in settings.PORTAL_CSRF_KEYS.values()}
    if any(len(key) < 32 for key in csrf_bytes):
        raise ValueError("Every retained CSRF key must have at least 32 bytes")
    if any(len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key) for key in settings.PORTAL_MAIL_KEYS.values()):
        raise ValueError("Every retained mail key must encode 32 bytes as hexadecimal")
    mail_bytes = {bytes.fromhex(key) for key in settings.PORTAL_MAIL_KEYS.values()}
    otp_bytes = settings.PORTAL_OTP_SECRET.encode()
    if csrf_bytes & mail_bytes or otp_bytes in csrf_bytes | mail_bytes:
        raise ValueError("Portal CSRF, OTP and mail keys must be independent")
    if settings.PORTAL_INVOICE_ENABLED and not settings.PORTAL_WRITES_ENABLED:
        raise ValueError("Portal invoice creation requires portal order submission")
