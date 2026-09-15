"""Beauty prompt lifecycle, snapshot isolation and final-input selection."""

from types import SimpleNamespace
from datetime import datetime
from datetime import timedelta
from io import BytesIO

import pytest
from sqlalchemy.orm import sessionmaker
from PIL import Image

from app.expo import beautify_prompt_service, beautify_service, prompt_service, service
from app.expo.models import ExpoBeautifyPromptVersion, ExpoCustomer, ExpoSession
from app.expo.prompt_renderer import render_prompt
from app.expo.prompt_schemas import BeautifyPromptCreate, BeautifyPromptUpdate
from tests.expo_prompt_support import config
from tests.test_expo_generate_quota import _client


def seed_beauty(db):
    row = ExpoBeautifyPromptVersion(
        name="强美颜 V1", prompt_text="BEAUTIFY ONCE", status="published",
        revision=1, published_slot=1,
    )
    db.add(row)
    db.commit()
    return row


def test_beautify_prompt_draft_revision_publish_and_snapshot(db, monkeypatch):
    first = seed_beauty(db)
    monkeypatch.setattr(
        "app.ai.service.get_image_config_snapshot",
        lambda *_: {"preset_name": "expo_wig_composite", "model": "image", "provider_id": 9, "fingerprint": "abc"},
    )
    draft = beautify_prompt_service.create_version(
        db, BeautifyPromptCreate(name="强美颜 V2", prompt_text="NEW BEAUTY"), 7,
    )
    db.commit()
    draft = beautify_prompt_service.update_version(
        db, draft.id,
        BeautifyPromptUpdate(name="强美颜 V2", prompt_text="NEW BEAUTY 2", expected_revision=1), 7,
    )
    db.commit()
    with pytest.raises(prompt_service.PromptError):
        beautify_prompt_service.update_version(
            db, draft.id,
            BeautifyPromptUpdate(name="冲突", prompt_text="X", expected_revision=1), 7,
        )
    db.rollback()
    published = beautify_prompt_service.publish(db, draft.id, 2, 7)
    snapshot = beautify_prompt_service.snapshot_published(db)
    assert published.revision == 3
    assert snapshot["prompt_text"] == "NEW BEAUTY 2"
    assert snapshot["image_config"]["fingerprint"] == "abc"
    assert first.status == "archived" and first.published_slot is None


@pytest.mark.parametrize("mode", ["tryon", "scene"])
def test_final_generation_uses_selected_source_and_never_finish(mode):
    cfg = config()
    cfg["parts"]["finish"] = "FINISH MUST NOT APPEAR"
    session = SimpleNamespace(
        photo_path="original.jpg", photo_processing_mode="beauty",
        beautify_status="ready", beautified_photo_path="beautified.png",
    )
    row = SimpleNamespace(
        wig_id=1 if mode == "tryon" else None,
        scene_json={"key": "whitecollar" if mode == "tryon" else "cafe"},
        hair_color_json=None,
    )
    wig = SimpleNamespace(
        name="短发", wig_description="short bob", composite_prompt="",
        angle_photos=[], cover_path=None,
    )
    text, images, _ = render_prompt(session, row, wig, cfg, lambda value: value)
    assert images[0] == "beautified.png"
    assert "FINISH MUST NOT APPEAR" not in text


def test_original_generation_never_uses_beautified_path():
    session = SimpleNamespace(
        photo_path="original.jpg", photo_processing_mode="original",
        beautify_status="ready", beautified_photo_path="beautified.png",
    )
    row = SimpleNamespace(wig_id=None, scene_json={"key": "cafe"}, hair_color_json=None)
    _, images, _ = render_prompt(session, row, None, config(), lambda value: value)
    assert images == ["original.jpg"]


def test_beautify_worker_claims_once_and_reuses_ready_asset(db, monkeypatch):
    customer = ExpoCustomer(name="客", phone="13800000000", primary_need="volume", expo_code="t")
    db.add(customer)
    db.flush()
    session = ExpoSession(
        customer_id=customer.id, photo_path="original.jpg", photo_processing_mode="beauty",
        beautify_status="pending", beautify_snapshot={
            "prompt_text": "BEAUTIFY ONCE",
            "image_config": {"preset_name": "expo_wig_composite", "provider_id": 9, "fingerprint": "abc"},
        },
    )
    db.add(session)
    db.commit()
    calls = []
    monkeypatch.setattr(beautify_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr("app.expo.ai_pipeline._prep_image", lambda path: {"filename": "x.jpg", "content": b"x", "content_type": "image/jpeg"})
    monkeypatch.setattr("app.expo.ai_pipeline.to_abs", lambda path: path)
    monkeypatch.setattr("app.expo.ai_pipeline.to_rel", lambda path: "uploads/expo/beautified/ready.png")
    monkeypatch.setattr("app.expo.ai_pipeline.save_ai_image", lambda *args: SimpleNamespace(unlink=lambda **kwargs: None))
    monkeypatch.setattr(beautify_service, "source_hash", lambda path: "output-hash")
    monkeypatch.setattr("app.ai.service.edit_image", lambda **kwargs: calls.append(kwargs) or {"content": "image"})
    beautify_service._run(session.id)
    beautify_service._run(session.id)
    db.refresh(session)
    assert len(calls) == 1
    assert calls[0]["prompt"] == "BEAUTIFY ONCE"
    assert session.beautify_status == "ready"
    assert session.beautified_photo_path.endswith("ready.png")


def test_beautify_publish_and_worker_times_use_beijing_clock(db, monkeypatch):
    seed_beauty(db)
    fixed = datetime(2026, 9, 13, 0, 1)
    monkeypatch.setattr(beautify_prompt_service, "beijing_now", lambda: fixed)
    monkeypatch.setattr(
        "app.ai.service.get_image_config_snapshot",
        lambda *_: {"preset_name": "expo_wig_composite", "model": "image", "provider_id": 9, "fingerprint": "abc"},
    )
    draft = beautify_prompt_service.create_version(
        db, BeautifyPromptCreate(name="跨日版本", prompt_text="PROMPT"), 7,
    )
    db.flush()
    published = beautify_prompt_service.publish(db, draft.id, 1, 7)
    assert published.published_at == fixed
    assert published.updated_at == fixed


def test_beautify_prompt_body_is_admin_only(db, monkeypatch):
    row = seed_beauty(db)
    monkeypatch.setattr(
        "app.ai.service.get_image_config_snapshot",
        lambda *_: {"preset_name": "expo_wig_composite", "model": "image", "provider_id": 9, "fingerprint": "abc"},
    )
    with _client(db, permissions=("expo:admin",)) as (client, admin):
        detail = client.get(f"/api/expo/beautify-prompt-versions/{row.id}")
        assert detail.status_code == 200
        assert detail.json()["data"]["prompt_text"] == "BEAUTIFY ONCE"
    admin.username = "previous-admin"
    db.query(ExpoBeautifyPromptVersion).delete()
    db.commit()
    with _client(db) as (client, _):
        assert client.get(f"/api/expo/beautify-prompt-versions/{row.id}").status_code == 403
        availability = client.get("/api/expo/beautify-availability")
        assert availability.status_code == 200
        assert availability.json()["data"] == {"available": False}


def test_create_beauty_session_freezes_prompt_and_source_hash(db, monkeypatch, tmp_path):
    customer = ExpoCustomer(
        name="客", phone="13800000000", primary_need="volume", expo_code="t",
        consent_at=datetime(2026, 9, 12, 14, 0),
    )
    db.add(customer)
    db.commit()
    monkeypatch.setattr("app.expo.ai_pipeline.PHOTO_DIR", tmp_path)
    monkeypatch.setattr("app.expo.ai_pipeline.ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    monkeypatch.setattr("app.expo.ai_pipeline.downscale_inplace", lambda path: None)
    monkeypatch.setattr("app.expo.ai_pipeline.to_rel", lambda path: f"uploads/expo/photos/{path.name}")
    monkeypatch.setattr(
        beautify_prompt_service, "snapshot_published",
        lambda db: {"version_id": 1, "version_name": "V1", "revision": 1, "prompt_text": "BEAUTY", "image_config": {"fingerprint": "abc"}},
    )
    upload = SimpleNamespace(filename="portrait.jpg", file=BytesIO(b"customer-photo"))
    session = service.create_session(
        db, customer.id, upload, None, photo_processing_mode="beauty",
    )
    assert session.photo_processing_mode == "beauty"
    assert session.beautify_status == "pending"
    assert session.beautify_snapshot["prompt_text"] == "BEAUTY"
    assert session.beautify_snapshot["source_hash"] == beautify_service.source_hash(tmp_path / session.photo_path.split("/")[-1])


def test_create_session_replays_same_client_request_without_duplicate(db, monkeypatch, tmp_path):
    customer = ExpoCustomer(
        name="客", phone="13800000000", primary_need="volume", expo_code="t",
        consent_at=datetime(2026, 9, 12, 14, 0),
    )
    db.add(customer)
    db.commit()
    monkeypatch.setattr("app.expo.ai_pipeline.PHOTO_DIR", tmp_path)
    monkeypatch.setattr("app.expo.ai_pipeline.ensure_dirs", lambda: tmp_path.mkdir(exist_ok=True))
    monkeypatch.setattr("app.expo.ai_pipeline.downscale_inplace", lambda path: None)
    monkeypatch.setattr("app.expo.ai_pipeline.to_rel", lambda path: f"uploads/expo/photos/{path.name}")

    first = service.create_session(
        db, customer.id, SimpleNamespace(filename="portrait.jpg", file=BytesIO(b"same-photo")), None,
        client_request_id="request-1",
    )
    replay = service.create_session(
        db, customer.id, SimpleNamespace(filename="portrait.jpg", file=BytesIO(b"same-photo")), None,
        client_request_id="request-1",
    )
    assert replay.id == first.id
    assert replay._idempotent_replay is True
    assert db.query(ExpoSession).count() == 1

    with pytest.raises(service.SessionRequestConflict, match="同一请求标识"):
        service.create_session(
            db, customer.id, SimpleNamespace(filename="portrait.jpg", file=BytesIO(b"different")), None,
            client_request_id="request-1",
        )


def test_pending_photo_request_replays_after_source_was_consumed(db, monkeypatch, tmp_path):
    customer = ExpoCustomer(
        name="客", phone="13800000000", primary_need="volume", expo_code="t",
        consent_at=datetime(2026, 9, 12, 14, 0),
    )
    db.add(customer)
    db.commit()
    pending = tmp_path / "c1_pending.jpg"
    pending.write_bytes(b"pending-photo")
    photos = tmp_path / "photos"
    photos.mkdir()
    calls = []
    monkeypatch.setattr("app.expo.ai_pipeline.PHOTO_DIR", photos)
    monkeypatch.setattr("app.expo.ai_pipeline.ensure_dirs", lambda: None)
    monkeypatch.setattr("app.expo.ai_pipeline.downscale_inplace", lambda path: None)
    monkeypatch.setattr("app.expo.ai_pipeline.to_rel", lambda path: f"uploads/expo/photos/{path.name}")
    monkeypatch.setattr(
        "app.expo.upload_service.resolve_pending",
        lambda customer_id, name: calls.append((customer_id, name)) or pending,
    )
    monkeypatch.setattr("app.expo.upload_service.photo_filename", lambda customer_id, suffix: f"copy{suffix}")

    first = service.create_session(
        db, customer.id, None, None, pending_name=pending.name, client_request_id="pending-request",
    )
    assert not pending.exists()
    replay = service.create_session(
        db, customer.id, None, None, pending_name=pending.name, client_request_id="pending-request",
    )
    assert replay.id == first.id
    assert len(calls) == 1


def test_concurrent_retry_only_dispatches_once(db, monkeypatch):
    customer = ExpoCustomer(name="客", phone="13800000000", primary_need="volume", expo_code="t")
    session = ExpoSession(
        customer=customer, photo_path="original.jpg", photo_processing_mode="beauty",
        beautify_status="failed", beautify_snapshot={"prompt_text": "BEAUTY"},
    )
    db.add(session)
    db.commit()
    other_db = sessionmaker(bind=db.get_bind())()
    stale_copy = other_db.get(ExpoSession, session.id)
    dispatched = []
    monkeypatch.setattr(beautify_service, "start", lambda session_id: dispatched.append(session_id))

    beautify_service.retry(db, session)
    # 模拟第二个请求拿着失败态对象抵达；CAS 看到数据库已是 pending，不能再次派发。
    second = beautify_service.retry(other_db, stale_copy)
    assert second.beautify_status == "pending"
    assert dispatched == [session.id]
    other_db.close()


def test_pending_beautify_lost_before_thread_start_becomes_retryable(db, monkeypatch):
    old = datetime(2026, 9, 12, 10, 0)
    customer = ExpoCustomer(name="客", phone="13800000000", primary_need="volume", expo_code="t")
    session = ExpoSession(
        customer=customer, photo_path="original.jpg", photo_processing_mode="beauty",
        beautify_status="pending", beautify_snapshot={"prompt_text": "BEAUTY"},
        beautify_queued_at=old, created_at=old, updated_at=old, status="analyzed",
    )
    db.add(session)
    db.commit()
    monkeypatch.setattr(service, "beijing_now", lambda: old + timedelta(seconds=service.STALE_BEAUTIFY_SECS + 1))
    service._heal_stale_beautify(db, session)
    assert session.beautify_status == "failed"
    assert "watchdog" in session.beautify_error_message


def test_admin_preview_returns_ephemeral_data_url_and_removes_files(db, monkeypatch, tmp_path):
    raw = BytesIO()
    Image.new("RGB", (80, 80), "white").save(raw, format="PNG")
    raw.seek(0)
    preview_dir = tmp_path / "previews"
    monkeypatch.setattr(beautify_service, "PREVIEW_DIR", preview_dir)
    monkeypatch.setattr("app.expo.ai_pipeline.downscale_inplace", lambda path: None)
    monkeypatch.setattr(
        "app.ai.service.get_image_config_snapshot",
        lambda *_: {"preset_name": "expo_wig_composite", "provider_id": 9, "fingerprint": "abc"},
    )
    monkeypatch.setattr("app.ai.service.edit_image", lambda **kwargs: {"content": "image"})

    def save_output(*_args):
        path = preview_dir / "preview.png"
        Image.new("RGB", (80, 80), "pink").save(path, format="PNG")
        return path

    monkeypatch.setattr("app.expo.ai_pipeline.save_ai_image", save_output)
    result = beautify_service.preview(
        db, SimpleNamespace(filename="portrait.png", file=raw), "BEAUTY", 7,
    )
    assert result["image_url"].startswith("data:image/png;base64,")
    assert list(preview_dir.iterdir()) == []
