import threading
from datetime import datetime

import pytest
from sqlalchemy import select, update

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser
from app.core.time import beijing_now
from app.whatsapp_translation.constants import ERROR_DEVICE_REVOKED, ERROR_PAIRING_STATE
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import TranslationDevice, TranslationPairing
import app.whatsapp_translation.pairing_service as pairing_service
from app.whatsapp_translation.pairing_service import (
    approve_pairing,
    create_pairing,
    exchange_pairing,
    prune_unconsumed_pairings,
    hash_secret,
    reject_pairing,
)
from app.whatsapp_translation.schemas import PairingCreate


def make_user(db, *, username="worker", is_active=True):
    role = ArkRole(name=f"role_{username}", label=username)
    permission = ArkPermission(
        code="whatsapp_translation:write",
        module="whatsapp_translation",
        action="write",
        label="使用 WhatsApp 实时翻译",
    )
    db.add_all([role, permission])
    db.flush()
    db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
    user = ArkUser(
        username=username,
        password_hash="test",
        real_name=username,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    user.roles.append(role)
    db.flush()
    return user


def make_pairing(db, *, token_hash):
    return create_pairing(db, PairingCreate(
        proposed_token_hash=token_hash,
        device_name="Windows · Chrome",
        browser_name="Chrome",
        browser_version="140.0.0.0",
        extension_version="1.0.0",
    ))


def test_pairing_approval_and_exchange_never_store_or_return_plain_token(db):
    token = "device-token-known-only-to-extension"
    token_hash = __import__("hashlib").sha256(token.encode("utf-8")).hexdigest()
    user = make_user(db)
    created = make_pairing(db, token_hash=token_hash)
    approve_pairing(db, created.device_code, user.id)
    first = exchange_pairing(db, created.device_code)
    second = exchange_pairing(db, created.device_code)

    assert first.status == second.status == "ready"
    assert first.device_id == second.device_id
    device = db.get(TranslationDevice, first.device_id)
    db.refresh(device)
    assert device.token_hash == token_hash
    assert token not in str(first.model_dump())
    assert token not in str(second.model_dump())


def get_pairing_model(db, created):
    return db.scalar(
        select(TranslationPairing).where(
            TranslationPairing.device_code_hash == hash_secret(created.device_code)
        )
    )


def count_devices_for_pairing(db, pairing_id):
    from sqlalchemy import func

    pairing = db.get(TranslationPairing, pairing_id)
    if pairing is None or pairing.device_id is None:
        return 0
    return db.scalar(
        select(func.count()).select_from(TranslationDevice).where(
            TranslationDevice.id == pairing.device_id,
        ),
    )


def run_in_two_threads(session, function):
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    results = []
    errors = []

    def worker():
        barrier.wait()
        try:
            with lock:
                results.append(function(session))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    return results


def test_parallel_exchange_creates_one_device(db):
    token_hash = "f" * 64
    user = make_user(db)
    created = make_pairing(db, token_hash=token_hash)
    approve_pairing(db, created.device_code, user.id)
    barrier = threading.Barrier(2)
    results = run_in_two_threads(
        db,
        lambda session: exchange_pairing(session, created.device_code),
    )

    assert {result.device_id for result in results} == {results[0].device_id}
    assert count_devices_for_pairing(db, get_pairing_model(db, created).id) == 1


def test_pairing_states_fail_closed(db):
    user = make_user(db)
    created = make_pairing(db, token_hash="a" * 64)

    pending = exchange_pairing(db, created.device_code)
    assert pending.status == "pending"

    reject_pairing(db, created.device_code, user.id)
    with pytest.raises(WhatsAppTranslationError) as rejected:
        approve_pairing(db, created.device_code, user.id)
    assert rejected.value.error_code == "pairing_state"

    expired_created = make_pairing(db, token_hash="b" * 64)
    expired = get_pairing_model(db, expired_created)
    db.execute(
        update(TranslationPairing)
        .where(TranslationPairing.id == expired.id)
        .values(expires_at=datetime(2000, 1, 1))
    )
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as expired_error:
        approve_pairing(db, expired_created.device_code, user.id)
    assert expired_error.value.error_code == "pairing_expired"

    with pytest.raises(WhatsAppTranslationError) as invalid:
        approve_pairing(db, "not-a-real-code", user.id)
    assert invalid.value.error_code == "pairing_not_found"


def test_duplicate_approval_is_rejected(db):
    user = make_user(db)
    created = make_pairing(db, token_hash="c" * 64)
    approve_pairing(db, created.device_code, user.id)
    with pytest.raises(WhatsAppTranslationError) as error:
        approve_pairing(db, created.device_code, user.id)
    assert error.value.error_code == ERROR_PAIRING_STATE


def test_exchange_enforces_device_limit(db):
    user = make_user(db)
    created = make_pairing(db, token_hash="d" * 64)
    approve_pairing(db, created.device_code, user.id)
    for index in range(5):
        db.add(TranslationDevice(
            user_id=user.id,
            token_hash=f"{index:063d}{index}",
            device_name=f"Device {index}",
            browser_name="Chrome",
            browser_version="140.0.0.0",
            extension_version="1.0.0",
            expires_at=beijing_now().replace(year=2099),
        ))
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as error:
        exchange_pairing(db, created.device_code)
    assert error.value.error_code == "device_limit"


def test_exchange_locks_pairing_owner_before_capacity_check(db, monkeypatch):
    user = make_user(db)
    created = make_pairing(db, token_hash="6" * 64)
    approve_pairing(db, created.device_code, user.id)
    order = []
    monkeypatch.setattr(
        pairing_service,
        "_lock_pairing_owner",
        lambda _db, owner_id: order.append(("lock", owner_id)),
    )
    monkeypatch.setattr(
        pairing_service,
        "_require_device_capacity",
        lambda _db, owner_id: order.append(("capacity", owner_id)),
    )

    exchange_pairing(db, created.device_code)

    assert order == [("lock", user.id), ("capacity", user.id)]


def test_revoked_device_retry_fails(db):
    user = make_user(db)
    created = make_pairing(db, token_hash="e" * 64)
    approve_pairing(db, created.device_code, user.id)
    first = exchange_pairing(db, created.device_code)
    device = db.get(TranslationDevice, first.device_id)
    device.is_active = False
    device.revoked_at = beijing_now()
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as error:
        exchange_pairing(db, created.device_code)
    assert error.value.error_code == ERROR_DEVICE_REVOKED


def test_revoked_device_can_be_replaced_by_new_pairing(db):
    user = make_user(db)
    first_created = make_pairing(db, token_hash="e" * 64)
    approve_pairing(db, first_created.device_code, user.id)
    first = exchange_pairing(db, first_created.device_code)
    device = db.get(TranslationDevice, first.device_id)
    device.is_active = False
    device.revoked_at = beijing_now()
    db.commit()

    second_created = make_pairing(db, token_hash="7" * 64)
    approve_pairing(db, second_created.device_code, user.id)
    second = exchange_pairing(db, second_created.device_code)

    assert second.status == "ready"
    assert second.device_id != first.device_id


def test_inactive_user_exchange_fails(db):
    user = make_user(db)
    created = make_pairing(db, token_hash="1" * 64)
    approve_pairing(db, created.device_code, user.id)
    user.is_active = False
    db.commit()
    user.is_active = False
    db.commit()
    with pytest.raises(WhatsAppTranslationError) as error:
        exchange_pairing(db, created.device_code)
    assert error.value.error_code == "user_inactive"


def test_prune_unconsumed_pairings_older_than_seven_days(db):
    make_pairing(db, token_hash="2" * 64)
    pairing = db.scalar(select(TranslationPairing))
    pairing.created_at = beijing_now() - __import__("datetime").timedelta(days=8)
    db.commit()
    removed = prune_unconsumed_pairings(db)
    assert removed == 1
    assert db.scalar(select(TranslationPairing)) is None
