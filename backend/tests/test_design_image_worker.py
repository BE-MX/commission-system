import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker

from app.ai.models import AiPreset, AiProvider
from app.auth.models import ArkUser
from app.design_image import worker
from app.design_image.file_service import StoredImage
from app.design_image.models import (
    DesignImageAsset,
    DesignImageJob,
    DesignImageJobAsset,
    DesignImageMessage,
    DesignImageSession,
)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _seed_job(db, *, mode="generate", created_at=None, parameters=None):
    preset = db.query(AiPreset).filter_by(
        preset_name="design_image_generation"
    ).one_or_none()
    if preset is None:
        provider = AiProvider(
            name="Worker provider", provider_type="direct",
            api_base="https://example.test", api_type="openai",
            is_enabled=True, timeout_sec=30,
        )
        db.add(provider)
        db.flush()
        db.add(AiPreset(
            preset_name="design_image_generation", provider_id=provider.id,
            model="gpt-image-2", parameters={"output_format": "png"},
            is_enabled=True,
        ))
        db.flush()
    owner = ArkUser(
        username=f"worker-owner-{db.query(ArkUser).count()}",
        password_hash="test", real_name="Worker Owner", is_active=True,
    )
    db.add(owner)
    db.flush()
    session = DesignImageSession(
        owner_user_id=owner.id, title="Worker test", status="active"
    )
    db.add(session)
    db.flush()
    message = DesignImageMessage(
        session_id=session.id, role="user", content="make it", status="normal"
    )
    db.add(message)
    db.flush()
    job = DesignImageJob(
        owner_user_id=owner.id,
        session_id=session.id,
        request_message_id=message.id,
        mode=mode,
        status="queued",
        prompt_snapshot="make it",
        parameters=parameters or {"size": "1024x1024", "quality": "medium"},
        preset_name="design_image_generation",
        model="gpt-image-2",
        idempotency_key=f"job-{owner.id}",
        created_at=created_at or _utcnow(),
    )
    db.add(job)
    db.commit()
    return owner, session, message, job


def _png_bytes(color="red"):
    import io

    stream = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(stream, format="PNG")
    return stream.getvalue()


def _result(content):
    return {
        "content": content,
        "tokens_used": 12,
        "usage_detail": {
            "input_tokens": 5, "output_tokens": 7, "total_tokens": 12,
        },
        "duration_ms": 10,
        "log_id": None,
        "provider_attempt_count": 2,
        "request_id": "provider-request",
    }


def test_claim_is_oldest_atomic_conditional_and_returns_detached_snapshot(db):
    older = _seed_job(db, created_at=_utcnow() - timedelta(minutes=2))[3]
    newer = _seed_job(db, created_at=_utcnow() - timedelta(minutes=1))[3]
    older_id = older.id

    first = worker.claim_next_job(db, "worker-a", 120)
    second = worker.claim_next_job(db, "worker-b", 120)

    assert (first.job_id, second.job_id) == (older.id, newer.id)
    assert first.lease_token != second.lease_token
    assert first.worker_id == "worker-a"
    assert worker.claim_next_job(db, "worker-c", 120) is None
    db.close()
    assert first.job_id == older_id


def test_claim_sql_uses_skip_locked_and_status_guard():
    select_sql = str(
        worker._claim_candidate_statement().compile(dialect=mysql.dialect())
    ).upper()
    update_sql = str(
        worker._claim_update_statement(1, "token", "worker", _utcnow()).compile(
            dialect=mysql.dialect()
        )
    ).upper()
    assert "FOR UPDATE SKIP LOCKED" in select_sql
    assert "STATUS = %S" in update_sql
    assert "ARK_DESIGN_IMAGE_JOBS.STATUS = %S" in update_sql


def test_generate_uses_new_session_and_publishes_only_after_storage(
    engine, db, monkeypatch
):
    owner, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    facade_sessions = []
    events = []

    def fake_generate(**kwargs):
        facade_sessions.append(kwargs.pop("db"))
        assert kwargs == {
            "preset_name": "design_image_generation",
            "prompt": "make it",
            "caller_module": "design_image",
            "caller_user_id": owner.id,
            "size": "1024x1024",
            "quality": "medium",
        }
        return _result(
            "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
        )

    def fake_save(image, **kwargs):
        events.append("stored")
        return StoredImage(
            relative_path="1/output/result.png",
            thumbnail_relative_path="1/output/result_thumb.png",
            mime_type=image.mime_type,
            file_size=image.file_size,
            width=image.width,
            height=image.height,
            sha256=image.sha256,
        )

    monkeypatch.setattr(worker.ai_service, "generate_image", fake_generate)
    monkeypatch.setattr(worker.file_service, "save_private_image", fake_save)
    worker.execute_claimed_job(job.id, claim.lease_token)

    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "succeeded"
    assert row.provider_attempt_count == 2
    assert row.claim_count == 1
    assert row.output_asset_id is not None and row.response_message_id is not None
    assert events == ["stored"]
    assert facade_sessions[0] is not db


def test_two_workers_can_call_provider_only_once_for_one_job(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    winner = worker.claim_next_job(db, "worker-a", 120)
    assert worker.claim_next_job(db, "worker-b", 120) is None
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    calls = []
    monkeypatch.setattr(
        worker.ai_service, "generate_image",
        lambda **kwargs: calls.append(kwargs) or _result(
            "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
        ),
    )
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/once.png", "1/output/once_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    worker.execute_claimed_job(job.id, winner.lease_token)
    assert len(calls) == 1


def test_provider_url_uses_explicit_allowlist_and_detects_real_mime(monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker.file_service, "download_provider_image",
        lambda url, *, allowed_hosts: calls.append((url, allowed_hosts)) or _png_bytes(),
    )
    normalized = worker._decode_provider_content(
        "https://cdn.example.test/result", frozenset({"cdn.example.test"})
    )
    assert normalized.mime_type == "image/png"
    assert calls == [("https://cdn.example.test/result", {"cdn.example.test"})]
    with pytest.raises(ValueError, match="not configured"):
        worker._decode_provider_content("https://cdn.example.test/result", frozenset())


def test_invalid_provider_payload_keeps_actual_attempt_count(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(
        worker.ai_service, "generate_image",
        lambda **kwargs: _result("not-base64"),
    )
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed"
    assert row.provider_attempt_count == 2


def test_edit_sends_base_then_references_by_position(
    engine, db, tmp_path, monkeypatch
):
    owner, session, _, job = _seed_job(db, mode="edit")
    monkeypatch.setattr(
        worker.get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path)
    )
    paths = []
    for name, payload in (("base.png", b"base"), ("ref2.png", b"ref2"), ("ref1.png", b"ref1")):
        path = tmp_path / str(owner.id) / "upload" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        asset = DesignImageAsset(
            session_id=session.id, asset_type="upload",
            storage_path=f"{owner.id}/upload/{name}", mime_type="image/png",
            file_size=len(payload), width=1, height=1, sha256=name.ljust(64, "0"),
            status="attached", created_by=owner.id,
        )
        db.add(asset)
        db.flush()
        paths.append(asset)
    job.base_asset_id = paths[0].id
    db.add_all([
        DesignImageJobAsset(job_id=job.id, asset_id=paths[1].id, role="reference", position=2),
        DesignImageJobAsset(job_id=job.id, asset_id=paths[2].id, role="reference", position=1),
    ])
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))

    def fake_edit(**kwargs):
        assert [image["content"] for image in kwargs["images"]] == [b"base", b"ref1", b"ref2"]
        return _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())

    monkeypatch.setattr(worker.ai_service, "edit_image", fake_edit)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/x.png", "1/output/x_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    worker.execute_claimed_job(job.id, claim.lease_token)


def test_late_provider_response_cannot_publish_after_stale_recovery(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "slow-worker", 120)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)

    def late_result(**kwargs):
        with factory() as recovery_db:
            stale_job = recovery_db.get(DesignImageJob, job.id)
            stale_job.lease_expires_at = _utcnow() - timedelta(seconds=1)
            recovery_db.commit()
            assert worker.recover_stale_jobs(recovery_db, _utcnow()) == 1
        return _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())

    deleted = []
    monkeypatch.setattr(worker.ai_service, "generate_image", late_result)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/late.png", "1/output/late_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted.append)
    worker.execute_claimed_job(job.id, claim.lease_token)

    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed" and row.error_code == "worker_timeout"
    assert row.output_asset_id is None and row.response_message_id is None
    assert db.query(DesignImageAsset).filter_by(asset_type="output").count() == 0
    assert db.query(DesignImageMessage).filter_by(role="assistant").count() == 0
    assert deleted == ["1/output/late.png", "1/output/late_thumb.png"]


@pytest.mark.parametrize(
    ("exc", "error_code"),
    [
        (ValueError("bad request"), "validation_error"),
        (TimeoutError("slow"), "provider_timeout"),
        (RuntimeError("boom"), "unknown_error"),
    ],
)
def test_failures_have_stable_actionable_mapping(
    engine, db, monkeypatch, exc, error_code
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    setattr(exc, "provider_attempt_count", 3)
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: (_ for _ in ()).throw(exc))
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed" and row.error_code == error_code
    assert row.error_message and "重试" in row.error_message
    assert row.provider_attempt_count == 3
    assert row.billing_certainty == "unknown"


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (429, "rate limit", "rate_limited"),
        (503, "unavailable", "provider_unavailable"),
        (400, "content_policy moderation", "moderation_blocked"),
    ],
)
def test_http_provider_errors_have_stable_codes(status, body, code):
    response = httpx.Response(status, text=body, request=httpx.Request("POST", "https://provider"))
    exc = httpx.HTTPStatusError(body, request=response.request, response=response)
    assert worker._map_error(exc)[0] == code


def test_recover_stale_only_fails_expired_running_jobs(db):
    expired = _seed_job(db)[3]
    active = _seed_job(db)[3]
    queued = _seed_job(db)[3]
    now = _utcnow()
    for row, expires in ((expired, now - timedelta(seconds=1)), (active, now + timedelta(seconds=60))):
        row.status = "running"
        row.lease_token = f"lease-{row.id}"
        row.claimed_by = "worker"
        row.lease_expires_at = expires
    db.commit()

    assert worker.recover_stale_jobs(db, now) == 1
    db.expire_all()
    assert db.get(DesignImageJob, expired.id).error_code == "worker_timeout"
    assert db.get(DesignImageJob, active.id).status == "running"
    assert db.get(DesignImageJob, queued.id).status == "queued"


def test_heartbeat_renews_live_unexpired_lease_before_stale_recovery(engine, db, monkeypatch):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 1)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    with factory() as force_expired:
        row = force_expired.get(DesignImageJob, job.id)
        row.lease_expires_at = _utcnow() + timedelta(seconds=1)
        force_expired.commit()

    assert worker._renew_lease(job.id, claim.lease_token, 30) is True
    with factory() as recovery_db:
        assert worker.recover_stale_jobs(recovery_db, _utcnow()) == 0
        row = recovery_db.get(DesignImageJob, job.id)
        assert row.status == "running"
        assert row.lease_expires_at > _utcnow() + timedelta(seconds=20)


def test_heartbeat_cannot_revive_expired_lease(engine, db, monkeypatch):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 1)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    with factory() as force_expired:
        row = force_expired.get(DesignImageJob, job.id)
        row.lease_expires_at = _utcnow() - timedelta(seconds=1)
        force_expired.commit()

    assert worker._renew_lease(job.id, claim.lease_token, 30) is False
    with factory() as recovery_db:
        assert worker.recover_stale_jobs(recovery_db, _utcnow()) == 1
        assert recovery_db.get(DesignImageJob, job.id).error_code == "worker_timeout"


def test_cleanup_soft_deletes_only_unreferenced_expired_drafts_then_deletes_files(
    engine, db, monkeypatch
):
    owner, session, _, job = _seed_job(db)
    now = _utcnow()

    def asset(name, expires):
        row = DesignImageAsset(
            session_id=session.id, asset_type="upload", storage_path=f"1/upload/{name}.png",
            mime_type="image/png", file_size=1, width=1, height=1, sha256=name.ljust(64, "0"),
            status="draft", expires_at=expires, created_by=owner.id,
        )
        db.add(row)
        db.flush()
        return row

    orphan = asset("orphan", now - timedelta(hours=1))
    base = asset("base", now - timedelta(hours=1))
    linked = asset("linked", now - timedelta(hours=1))
    current = asset("current", now + timedelta(hours=1))
    job.base_asset_id = base.id
    db.add(DesignImageJobAsset(job_id=job.id, asset_id=linked.id, role="reference", position=0))
    db.commit()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    deleted = []

    def delete_after_commit(path):
        with factory() as verify_db:
            assert verify_db.get(DesignImageAsset, orphan.id).deleted_at is not None
        deleted.append(path)

    monkeypatch.setattr(worker.file_service, "delete_private_file", delete_after_commit)
    assert worker.cleanup_expired_drafts(db, now) == 1
    db.expire_all()
    assert db.get(DesignImageAsset, orphan.id).deleted_at is not None
    assert all(db.get(DesignImageAsset, row.id).deleted_at is None for row in (base, linked, current))
    assert deleted == ["1/upload/orphan.png", "1/upload/orphan_thumb.png"]
