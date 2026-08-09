"""Retention cleanup contracts for invitation-owned customer image assets."""

from datetime import datetime, timedelta

import pytest

from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageProduct,
)


NOW = datetime(2026, 8, 10, 3, 30, 0)


def _invite(db, *, expires_at, suffix="111111"):
    row = CustomerImageInvite(
        customer_id=f"C-{suffix}",
        customer_name_snapshot="Retention Customer",
        created_by=17,
        okki_salesperson_id_snapshot="1017",
        token_hash=suffix * 10 + "abcd",
        token_suffix=suffix,
        starts_at=expires_at - timedelta(days=1),
        expires_at=expires_at,
        quota_total=3,
    )
    db.add(row)
    db.flush()
    return row


def _asset(db, invite, *, name="logo.png", asset_type="logo"):
    row = CustomerImageAsset(
        invite_id=invite.id,
        asset_type=asset_type,
        storage_path=f"customer-logo/{invite.id}/{name}",
        mime_type="image/png",
        file_size=10,
        width=8,
        height=8,
        sha256=("a" if asset_type == "logo" else "b") * 64,
    )
    db.add(row)
    db.flush()
    return row


def _generation(db, invite, logo, *, status):
    product = CustomerImageProduct(
        name=f"Product {invite.id}", category="box", fixed_prompt="x",
        output_prompt="y", created_by=17, is_published=True,
    )
    db.add(product)
    db.flush()
    row = CustomerImageGeneration(
        invite_id=invite.id,
        product_id=product.id,
        logo_asset_id=logo.id,
        request_id=f"request-{invite.id}",
        product_name_snapshot=product.name,
        config_version_snapshot=1,
        option_snapshot={},
        prompt_snapshot="prompt",
        reference_asset_ids=[],
        preset_name="design_image_generation",
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def test_cleanup_waits_exactly_thirty_days_and_commits_before_exact_file_deletes(db, monkeypatch):
    from app.customer_image import worker

    invite = _invite(db, expires_at=NOW - timedelta(days=29, hours=23))
    logo = _asset(db, invite)
    output = _asset(db, invite, name="result.png", asset_type="generated")
    db.commit()
    deleted_paths = []

    def delete_after_commit(path):
        db.expire_all()
        assert db.get(CustomerImageAsset, logo.id).deleted_at == NOW
        assert db.get(CustomerImageAsset, output.id).deleted_at == NOW
        deleted_paths.append(path)

    monkeypatch.setattr(worker.file_service, "delete_private_file", delete_after_commit)
    assert worker.cleanup_expired_invite_assets(db, NOW, retention_days=30) == 0
    assert deleted_paths == []

    invite.expires_at = NOW - timedelta(days=30)
    db.commit()
    assert worker.cleanup_expired_invite_assets(db, NOW, retention_days=30) == 2
    assert deleted_paths == [
        logo.storage_path,
        worker.file_service._thumbnail_path(logo.storage_path),
        output.storage_path,
        worker.file_service._thumbnail_path(output.storage_path),
    ]


@pytest.mark.parametrize("status", ["queued", "running"])
def test_cleanup_preserves_every_asset_for_invite_with_unfinished_generation(db, monkeypatch, status):
    from app.customer_image import worker

    invite = _invite(db, expires_at=NOW - timedelta(days=31), suffix="222222")
    logo = _asset(db, invite)
    _asset(db, invite, name="result.png", asset_type="generated")
    _generation(db, invite, logo, status=status)
    db.commit()
    deleted_paths = []
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted_paths.append)

    assert worker.cleanup_expired_invite_assets(db, NOW, retention_days=30) == 0
    assert deleted_paths == []
    assert all(asset.deleted_at is None for asset in db.query(CustomerImageAsset).all())


def test_cleanup_soft_delete_failure_never_deletes_files(db, monkeypatch):
    from app.customer_image import worker

    invite = _invite(db, expires_at=NOW - timedelta(days=31), suffix="333333")
    _asset(db, invite)
    db.commit()
    deleted_paths = []
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted_paths.append)
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db down")))

    with pytest.raises(RuntimeError, match="db down"):
        worker.cleanup_expired_invite_assets(db, NOW, retention_days=30)
    assert deleted_paths == []


def test_cleanup_retries_exact_files_after_best_effort_delete_failure(db, monkeypatch):
    from app.customer_image import worker

    invite = _invite(db, expires_at=NOW - timedelta(days=31), suffix="444444")
    asset = _asset(db, invite)
    db.commit()
    attempts = []
    fail_once = {asset.storage_path}

    def flaky_delete(path):
        attempts.append(path)
        if path in fail_once:
            fail_once.remove(path)
            raise OSError("temporary ACL failure")

    monkeypatch.setattr(worker.file_service, "delete_private_file", flaky_delete)
    assert worker.cleanup_expired_invite_assets(db, NOW, retention_days=30) == 1
    assert db.get(CustomerImageAsset, asset.id).deleted_at == NOW
    assert worker.cleanup_expired_invite_assets(db, NOW + timedelta(days=1), retention_days=30) == 0
    assert attempts.count(asset.storage_path) == 2


def test_daily_cleanup_wrapper_uses_configured_retention_and_own_session(monkeypatch):
    from app.customer_image import worker

    calls = []

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *_args): return None

    monkeypatch.setattr(worker, "SessionLocal", FakeSession)
    monkeypatch.setattr(worker, "get_settings", lambda: type("S", (), {"CUSTOMER_IMAGE_RETENTION_DAYS": 30})())
    monkeypatch.setattr(
        worker,
        "cleanup_expired_invite_assets",
        lambda db, now, retention_days: calls.append((db, now, retention_days)) or 2,
    )
    assert worker.process_customer_image_cleanup() == 2
    assert calls[0][0].__class__ is FakeSession
    assert calls[0][2] == 30
