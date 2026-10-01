"""Customer site entries are governed service notes, not inferred engagement metrics."""

import pytest

from app.customer import pcw_errors
from app.customer.service_asset_service import list_assets, register_asset, revoke_asset
from tests.test_customer_workbench_lifecycle import _actor, _customer_with_profile


def test_service_entry_registration_replay_and_revocation(db):
    account, owner = _customer_with_profile(db)
    payload = {"asset_type": "customer_website", "entry_url": "https://example.com/catalog?lang=en#internal",
        "purpose": "Show confirmed products to this customer", "known_issue": "Selection page still needs review"}
    first = register_asset(db, _actor(owner), account.id, payload, "service-register-001")
    same = register_asset(db, _actor(owner), account.id, payload, "service-register-001")
    assert same == first
    assert first["entry_url"] == "https://example.com/catalog?lang=en"
    assert "visits" not in first and "orders" not in first
    assert [row["asset_id"] for row in list_assets(db, _actor(owner), account.id)["items"]] == [first["asset_id"]]
    revoked = revoke_asset(db, _actor(owner), account.id, first["asset_id"],
        {"expected_asset_version": 1, "reason": "Customer switched to another entry"}, "service-revoke-0001")
    assert revoked["status"] == "revoked"
    assert list_assets(db, _actor(owner), account.id)["items"] == []


def test_service_entry_rejects_unscoped_customer_and_fake_scheme(db):
    account, owner = _customer_with_profile(db)
    payload = {"asset_type": "customer_website", "entry_url": "javascript:alert(1)",
        "purpose": "Present customer catalog"}
    with pytest.raises(pcw_errors.PcwError) as caught:
        register_asset(db, _actor(owner), account.id, payload, "service-register-002")
    assert caught.value.error_code == "SERVICE_ENTRY_URL_INVALID"
    outsider = {"sub": "9102", "permissions": ["customer_pcw:read", "customer_pcw:write"], "roles": []}
    with pytest.raises(pcw_errors.PcwError) as caught:
        list_assets(db, outsider, account.id)
    assert caught.value.status_code == 404
