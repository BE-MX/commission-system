import base64
import importlib
import os
from datetime import datetime

import httpx
from sqlalchemy.exc import IntegrityError

from app.ai.models import AiPreset, AiProvider
from scripts import design_image_provider_probe as probe


def _seed_source_preset(db):
    provider = AiProvider(
        name="probe-provider",
        provider_type="direct",
        api_base="https://example.test/v1",
        api_key="encrypted",
        api_type="openai",
        is_enabled=True,
        timeout_sec=60,
    )
    db.add(provider)
    db.flush()
    source = AiPreset(
        preset_name="expo_wig_composite",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={"input_fidelity": "high", "quality": "high"},
        is_enabled=True,
    )
    db.add(source)
    db.flush()
    return provider, source


def test_generation_cases_cover_quality_and_standard_sizes_without_duplicates():
    cases = probe.build_generation_cases()

    assert len(cases) == 5
    assert {(case["quality"], case["size"]) for case in cases} == {
        ("low", "1024x1024"),
        ("medium", "1024x1024"),
        ("high", "1024x1024"),
        ("low", "1024x1536"),
        ("low", "1536x1024"),
    }
    assert all("input_fidelity" not in case for case in cases)


def test_build_edit_files_uses_repeated_image_field_in_source_order():
    images = [
        ("first.png", b"first", "image/png"),
        ("second.jpg", b"second", "image/jpeg"),
    ]

    files = probe.build_edit_files(images)

    assert files == [
        ("image", ("first.png", b"first", "image/png")),
        ("image", ("second.jpg", b"second", "image/jpeg")),
    ]


def test_synthetic_edit_inputs_are_two_distinct_png_images():
    images = probe.build_synthetic_edit_inputs()

    assert [image[0] for image in images] == ["blue-circle.png", "orange-triangle.png"]
    assert all(image[2] == "image/png" for image in images)
    assert all(image[1].startswith(b"\x89PNG\r\n\x1a\n") for image in images)
    assert images[0][1] != images[1][1]


def test_sanitize_response_removes_base64_and_signed_url_details():
    raw = {
        "created": 123,
        "data": [{
            "b64_json": base64.b64encode(b"private-image").decode(),
            "url": "https://cdn.example.test/out.png?token=secret&expires=1",
        }],
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }

    safe = probe.sanitize_response(raw)

    assert safe["data"][0]["b64_json"] == "[omitted base64 image, 20 chars]"
    assert safe["data"][0]["url"] == "https://cdn.example.test/out.png"
    assert safe["usage"] == raw["usage"]


def test_sanitize_response_redacts_secret_keys_and_secrets_inside_text():
    raw = {
        "authorization": "Bearer top-secret-token-value",
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
        "message": (
            "download https://cdn.example.test/out.png?token=secret and use "
            "Bearer another-secret-token plus " + ("A" * 300)
        ),
    }

    safe = probe.sanitize_response(raw)

    assert safe["authorization"] == "[redacted secret]"
    assert safe["api_key"] == "[redacted secret]"
    assert "token=secret" not in safe["message"]
    assert "another-secret-token" not in safe["message"]
    assert "A" * 300 not in safe["message"]


def test_response_record_omits_non_json_response_body():
    response = httpx.Response(
        502,
        request=httpx.Request("POST", "https://example.test/v1/images/generations"),
        text="Bearer leaked-secret-token " + ("B" * 400),
    )

    record = probe._response_record(response, 12)

    assert record["response"] == {"raw_text": "[omitted non-JSON response, 427 chars]"}
    assert "leaked-secret-token" not in str(record)


def test_ensure_probe_preset_creates_independent_gpt_image_2_preset(db):
    provider, source = _seed_source_preset(db)

    preset, created = probe.ensure_probe_preset(db)

    assert created is True
    assert preset.preset_name == "design_image_generation"
    assert preset.provider_id == provider.id
    assert preset.id != source.id
    assert preset.model == "gpt-image-2"
    assert preset.parameters == {"output_format": "png"}
    assert "input_fidelity" not in preset.parameters


def test_ensure_probe_preset_is_idempotent_and_does_not_overwrite(db):
    provider, _ = _seed_source_preset(db)
    existing = AiPreset(
        preset_name="design_image_generation",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={"output_format": "png"},
        description="custom description",
        is_enabled=True,
    )
    db.add(existing)
    db.flush()

    preset, created = probe.ensure_probe_preset(db)

    assert created is False
    assert preset.id == existing.id
    assert preset.description == "custom description"


def test_ensure_probe_preset_rejects_soft_deleted_name(db):
    provider, _ = _seed_source_preset(db)
    db.add(AiPreset(
        preset_name="design_image_generation",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={"output_format": "png"},
        is_enabled=False,
        deleted_at=datetime.utcnow(),
    ))
    db.flush()

    try:
        probe.ensure_probe_preset(db)
    except ValueError as exc:
        assert "软删除" in str(exc)
    else:
        raise AssertionError("expected soft-deleted name to be rejected")


def test_ensure_probe_preset_recovers_from_concurrent_create(db, monkeypatch):
    provider, _ = _seed_source_preset(db)
    db.commit()
    real_commit = db.commit
    real_rollback = db.rollback
    state = {"first": True, "concurrent": None}

    def race_commit():
        if state["first"]:
            state["first"] = False
            raise IntegrityError("insert preset", {}, Exception("duplicate"))
        real_commit()

    def rollback_then_insert_competing_row():
        real_rollback()
        competing = AiPreset(
            preset_name="design_image_generation",
            provider_id=provider.id,
            model="gpt-image-2",
            parameters={"output_format": "png"},
            is_enabled=True,
        )
        db.add(competing)
        real_commit()
        state["concurrent"] = competing

    monkeypatch.setattr(db, "commit", race_commit)
    monkeypatch.setattr(db, "rollback", rollback_then_insert_competing_row)

    preset, created = probe.ensure_probe_preset(db)

    assert created is False
    assert preset.id == state["concurrent"].id


def test_validate_probe_preset_rejects_input_fidelity(db):
    provider, _ = _seed_source_preset(db)
    invalid = AiPreset(
        preset_name="design_image_generation",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={"input_fidelity": "high"},
        is_enabled=True,
    )
    db.add(invalid)
    db.flush()

    try:
        probe.validate_probe_preset(invalid, provider)
    except ValueError as exc:
        assert "input_fidelity" in str(exc)
    else:
        raise AssertionError("expected invalid preset to be rejected")


def test_probe_can_load_explicit_env_file_before_runtime(monkeypatch, tmp_path):
    env_file = tmp_path / "probe.env"
    env_file.write_text("PHASE0_PROBE_SENTINEL=loaded\n", encoding="utf-8")
    monkeypatch.setenv("ARK_PROBE_ENV_FILE", str(env_file))
    os.environ.pop("PHASE0_PROBE_SENTINEL", None)

    importlib.reload(probe)

    assert os.environ["PHASE0_PROBE_SENTINEL"] == "loaded"
    os.environ.pop("PHASE0_PROBE_SENTINEL", None)
