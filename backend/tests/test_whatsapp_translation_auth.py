from datetime import datetime, timedelta

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser
from app.core.time import beijing_now
from app.main import app
from app.whatsapp_translation.auth import (
    DeviceIdentity,
    require_supported_extension,
    require_translation_device,
)
from app.whatsapp_translation.constants import WHATSAPP_TRANSLATION_WRITE_PERMISSION
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import TranslationDevice
from app.whatsapp_translation.service import get_capabilities


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def add_user_with_role(db, *, username, role_name, permission_code=None):
    role = ArkRole(name=role_name, label=username)
    db.add(role)
    db.flush()
    if permission_code:
        permission = db.scalar(select(ArkPermission).where(ArkPermission.code == permission_code))
        if permission is None:
            permission = ArkPermission(
                code=permission_code,
                module="whatsapp_translation",
                action=permission_code.split(":")[-1],
                label="translation",
            )
            db.add(permission)
            db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    user = ArkUser(username=username, password_hash="test", real_name=username)
    db.add(user)
    db.flush()
    user.roles.append(role)
    db.flush()
    return user


def make_device(db, *, username="worker", role_name="worker_role", token="synthetic-device-token"):
    user = add_user_with_role(
        db,
        username=username,
        role_name=role_name,
        permission_code=WHATSAPP_TRANSLATION_WRITE_PERMISSION,
    )
    device = TranslationDevice(
        user_id=user.id,
        token_hash=_hash(token),
        device_name="Synthetic Device",
        browser_name="Chrome",
        browser_version="140.0.0.0",
        extension_version="1.0.0",
        expires_at=beijing_now().replace(year=2099),
    )
    db.add(device)
    db.commit()
    return user, device, token


@pytest.fixture
def auth_data(db):
    return make_device(db)


def credentials(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def require_device_identity_for_test(db, token, *, extension_version="1.0.0"):
    return require_translation_device(db, credentials(token), extension_version)


def test_existing_device_loses_access_immediately_when_permission_removed(db, auth_data):
    user, device, token = auth_data
    identity = require_device_identity_for_test(db, token)
    assert identity.user_id == user.id

    permission = db.scalar(select(ArkPermission).where(ArkPermission.code == WHATSAPP_TRANSLATION_WRITE_PERMISSION))
    db.query(ArkRolePermission).filter(ArkRolePermission.permission_id == permission.id).delete()
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as error:
        require_device_identity_for_test(db, token)
    assert error.value.error_code == "permission_denied"


def test_auth_never_exposes_hash_or_raw_token(db, auth_data):
    _, _, token = auth_data
    identity = require_device_identity_for_test(db, token)
    dumped = str(identity.model_dump())
    assert "token" not in dumped.lower()
    assert token not in dumped


def test_malformed_unknown_expired_revoked_or_inactive_devices_fail_closed(db, auth_data):
    user, device, token = auth_data
    with pytest.raises(WhatsAppTranslationError) as missing:
        require_translation_device(db, None, "1.0.0")
    assert missing.value.error_code == "invalid_bearer"

    with pytest.raises(WhatsAppTranslationError) as unknown:
        require_device_identity_for_test(db, "not-the-device-token")
    assert unknown.value.error_code == "device_not_found"

    device.expires_at = beijing_now() - timedelta(days=1)
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as expired:
        require_device_identity_for_test(db, token)
    assert expired.value.error_code == "device_expired"

    device.expires_at = beijing_now().replace(year=2099)
    device.is_active = False
    device.revoked_at = beijing_now()
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as revoked:
        require_device_identity_for_test(db, token)
    assert revoked.value.error_code == "device_revoked"

    device.is_active = True
    device.revoked_at = None
    user.is_active = False
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as inactive:
        require_device_identity_for_test(db, token)
    assert inactive.value.error_code == "user_inactive"


def test_super_admin_identity_is_admin(db, auth_data):
    user, device, token = auth_data
    role = ArkRole(name="super_admin", label="Super Admin")
    db.add(role)
    db.flush()
    user.roles.append(role)
    db.commit()
    assert require_device_identity_for_test(db, token).is_admin is True


def test_extension_version_is_validated_and_updated(db, auth_data):
    user, device, token = auth_data
    with pytest.raises(WhatsAppTranslationError) as missing:
        require_device_identity_for_test(db, token, extension_version=None)
    assert missing.value.error_code == "extension_version_invalid"
    with pytest.raises(WhatsAppTranslationError) as malformed:
        require_device_identity_for_test(db, token, extension_version="1.0")
    assert malformed.value.error_code == "extension_version_invalid"

    identity = require_device_identity_for_test(db, token, extension_version="1.2.3")
    assert identity.extension_version == "1.2.3"
    db.refresh(device)
    assert device.extension_version == "1.2.3"


def test_outdated_extension_only_blocks_translation(db, auth_data):
    _, device, token = auth_data
    identity = require_device_identity_for_test(db, token)
    identity = DeviceIdentity(
        user_id=identity.user_id,
        device_id=identity.device_id,
        real_name=identity.real_name,
        extension_version="0.9.0",
        expires_at=identity.expires_at,
        is_admin=identity.is_admin,
    )
    with pytest.raises(WhatsAppTranslationError) as outdated:
        require_supported_extension(identity)
    assert outdated.value.status_code == 426


def test_last_used_at_is_updated(db, auth_data):
    _, device, token = auth_data
    device.last_used_at = None
    db.commit()
    require_device_identity_for_test(db, token)
    db.refresh(device)
    assert device.last_used_at is not None


def test_capabilities_are_exact_and_session_has_no_secrets(db, auth_data):
    identity = require_device_identity_for_test(db, auth_data[2])
    capabilities = get_capabilities()
    assert capabilities["source_languages"] == ["zh-CN", "en", "es", "fr", "ar", "ja", "de", "nl", "sv"]
    assert capabilities["target_languages"] == ["zh-CN", "en", "es", "fr", "ar", "ja"]
    assert capabilities["max_text_chars"] == 4_000
    assert capabilities["rate_per_minute"] == 30
    assert capabilities["daily_input_chars"] == 200_000
    assert capabilities["ai_config_version"] == 1
    assert capabilities["min_extension_version"] == "1.0.0"
    assert "token" not in str(identity.model_dump()).lower()


def test_whatsapp_translation_domain_is_isolated():
    from pathlib import Path

    root = Path(__file__).parents[1] / "app" / "whatsapp_translation"
    for path in root.glob("*.py"):
        assert "from app.whatsapp " not in path.read_text(encoding="utf-8")
        assert "import app.whatsapp " not in path.read_text(encoding="utf-8")


def test_extension_origin_preflight_only():
    client = TestClient(app)
    exact = client.options(
        "/health",
        headers={
            "Origin": "chrome-extension://bnkecbkoidckffckbefjjcbchmngjobi",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert exact.headers.get("access-control-allow-origin") == (
        "chrome-extension://bnkecbkoidckffckbefjjcbchmngjobi"
    )
    unrelated = client.options(
        "/health",
        headers={
            "Origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in unrelated.headers
