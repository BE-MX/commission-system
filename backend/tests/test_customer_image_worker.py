"""Recoverable worker contracts for customer image generations."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
import time

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker

from app.ai.image_service import build_image_config_version
from app.ai.image_job_runtime import (
    ImageInput,
    ImageJobFailure,
    ImageJobResult,
    ImagePayload,
)
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageProduct,
    CustomerImageProductAsset,
)


def _utcnow():
    return datetime.utcnow()


def _queued_generation(db, *, status="queued", lease_token=None):
    provider = AiProvider(
        name="Customer worker provider",
        provider_type="direct",
        api_base="https://images.example.test/v1",
        api_key="encrypted-secret",
        api_type="openai",
        is_enabled=True,
    )
    db.add(provider)
    db.flush()
    preset = AiPreset(
        preset_name="design_image_generation",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={
            "size": "current-size",
            "quality": "current-quality",
            "download_hosts": ["current.example.test"],
            "rate_card": {"output_image_microusd": 9},
        },
        is_enabled=True,
    )
    product = CustomerImageProduct(
        name="Frozen Product",
        category="packaging",
        fixed_prompt="current product prompt must not be read",
        output_prompt="current output prompt must not be read",
        config_version=4,
        is_published=True,
        created_by=17,
    )
    invite = CustomerImageInvite(
        customer_id="worker-customer",
        customer_name_snapshot="Worker Customer",
        created_by=17,
        okki_salesperson_id_snapshot="1017",
        token_hash="7" * 64,
        token_suffix="777777",
        starts_at=_utcnow() - timedelta(minutes=1),
        expires_at=_utcnow() + timedelta(days=1),
        quota_total=3,
        quota_used=1,
    )
    db.add_all([preset, product, invite])
    db.flush()
    logo = CustomerImageAsset(
        invite_id=invite.id,
        asset_type="logo",
        storage_path="customer-logo/frozen-logo.png",
        mime_type="image/png",
        file_size=10,
        width=32,
        height=24,
        sha256="a" * 64,
    )
    references = [
        CustomerImageProductAsset(
            product_id=product.id,
            role="reference",
            storage_path=f"customer-product/frozen-{position}.png",
            mime_type="image/png",
            file_size=10,
            width=32,
            height=24,
            sha256=str(position // 10) * 64,
            position=position,
        )
        for position in (10, 20)
    ]
    db.add_all([logo, *references])
    db.flush()
    invite.current_logo_asset_id = logo.id
    generation = CustomerImageGeneration(
        invite_id=invite.id,
        product_id=product.id,
        logo_asset_id=logo.id,
        request_id=f"worker-{status}-{lease_token or 'none'}",
        product_name_snapshot="Frozen Product",
        config_version_snapshot=3,
        option_snapshot=[{"key": "finish", "value": "frozen"}],
        requirement_snapshot="frozen requirement",
        parameters_snapshot={
            "size": "frozen-size",
            "quality": "frozen-quality",
            "provider_id": provider.id,
            "config_version": {
                "provider_id": provider.id,
                "fingerprint": build_image_config_version(preset, provider),
            },
            "download_hosts": ["frozen.example.test"],
            "input_asset_ids": [logo.id, *(row.id for row in references)],
        },
        prompt_snapshot="FROZEN PROMPT ONLY",
        reference_asset_ids=[row.id for row in references],
        status=status,
        claimed_by="worker-a" if status == "running" else None,
        lease_token=lease_token,
        lease_expires_at=(
            _utcnow() + timedelta(minutes=5) if lease_token else None
        ),
        claim_count=1 if status == "running" else 0,
        preset_name=preset.preset_name,
        model=preset.model,
        pricing_snapshot={"frozen_rate": 7},
    )
    db.add(generation)
    db.commit()
    return generation, invite, product, logo, references, preset, provider


def test_claim_uses_skip_locked_and_transitions_oldest_queue_row(db):
    from app.customer_image import worker

    first, *_ = _queued_generation(db)
    sql = str(
        worker._claim_job_statement().compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).upper()

    claim = worker.claim_next_job(db, worker_id="customer-worker", lease_seconds=60)

    db.refresh(first)
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert claim.job_id == first.id
    assert claim.lease_token
    assert first.status == "running"
    assert first.claimed_by == "customer-worker"
    assert first.claim_count == 1
    assert first.started_at is not None
    assert first.lease_expires_at > first.started_at


def test_snapshot_uses_frozen_logo_references_prompt_and_runtime_parameters(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, product, logo, references, *_ = _queued_generation(
        db, status="running", lease_token="lease-frozen"
    )
    product.fixed_prompt = "MUTATED CURRENT PROMPT"
    references[0].retired_at = _utcnow()
    new_reference = CustomerImageProductAsset(
        product_id=product.id,
        role="reference",
        storage_path="customer-product/new-current.png",
        mime_type="image/png",
        file_size=10,
        width=32,
        height=24,
        sha256="f" * 64,
        position=0,
    )
    new_logo = CustomerImageAsset(
        invite_id=invite.id,
        asset_type="logo",
        storage_path="customer-logo/new-current.png",
        mime_type="image/png",
        file_size=10,
        width=32,
        height=24,
        sha256="e" * 64,
    )
    db.add_all([new_reference, new_logo])
    db.flush()
    invite.current_logo_asset_id = new_logo.id
    db.commit()
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )

    snapshot = worker._load_snapshot(generation.id, "lease-frozen")

    assert snapshot.prompt == "FROZEN PROMPT ONLY"
    assert snapshot.caller_user_id == 17
    assert snapshot.invite_id == invite.id
    assert snapshot.size == "frozen-size"
    assert snapshot.quality == "frozen-quality"
    assert snapshot.download_hosts == frozenset({"frozen.example.test"})
    assert snapshot.pricing_snapshot == {"frozen_rate": 7}
    assert snapshot.input_paths == (
        (logo.storage_path, "image/png"),
        (references[0].storage_path, "image/png"),
        (references[1].storage_path, "image/png"),
    )
    assert "new-current" not in str(snapshot)


def test_recover_stale_running_job_is_terminal_without_refund(db):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="expired-lease"
    )
    generation.lease_expires_at = _utcnow() - timedelta(seconds=1)
    db.commit()

    changed = worker.recover_stale_jobs(
        db, stale_before=_utcnow() - timedelta(minutes=10)
    )

    db.refresh(generation)
    db.refresh(invite)
    assert changed == 1
    assert generation.status == "failed"
    assert generation.error_code == "worker_timeout"
    assert generation.billing_certainty == "unknown"
    assert generation.lease_token is None
    assert generation.quota_refunded_at is None
    assert invite.quota_used == 1


def test_provider_request_uses_customer_audit_and_frozen_values_outside_job_transaction(
    db, monkeypatch
):
    from app.customer_image import worker

    generation, *_ = _queued_generation(
        db, status="running", lease_token="lease-provider"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    snapshot = worker._load_snapshot(generation.id, "lease-provider")
    frozen_input = ImageInput("logo.png", b"logo", "image/png")
    monkeypatch.setattr(worker, "_image_inputs", lambda _snapshot: (frozen_input,))
    captured = {}

    def fake_provider(provider_db, request, *, download_image):
        captured["in_transaction"] = provider_db.in_transaction()
        captured["request"] = request
        captured["download_image"] = download_image
        return ImageJobResult(
            image=ImagePayload(b"result", "image/png"),
            log_id=31,
            provider_attempt_count=1,
            billing_certainty="estimated",
            input_tokens=2,
            output_tokens=3,
            total_tokens=5,
            estimated_cost_microusd=70,
        )

    monkeypatch.setattr(worker.image_runtime, "call_image_provider", fake_provider)

    result = worker._call_provider(snapshot)

    request = captured["request"]
    assert captured["in_transaction"] is False
    assert request.caller_module == "customer_image"
    assert request.caller_user_id == 17
    assert request.prompt == "FROZEN PROMPT ONLY"
    assert request.size == "frozen-size"
    assert request.quality == "frozen-quality"
    assert request.download_hosts == frozenset({"frozen.example.test"})
    assert request.pricing_snapshot == {"frozen_rate": 7}
    assert request.input_images == (frozen_input,)
    assert result.log_id == 31


def test_heartbeat_renews_live_lease_and_wrong_token_cannot_renew(db, monkeypatch):
    from app.customer_image import worker

    generation, *_ = _queued_generation(
        db, status="running", lease_token="lease-heartbeat"
    )
    original_expiry = generation.lease_expires_at
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )

    assert worker._renew_lease(generation.id, "wrong-token", 60) is False
    assert worker._renew_lease(generation.id, "lease-heartbeat", 600) is True
    db.expire_all()
    assert db.get(CustomerImageGeneration, generation.id).lease_expires_at > original_expiry
    heartbeat_calls = []
    monkeypatch.setattr(
        worker,
        "_renew_lease",
        lambda job_id, token, seconds: heartbeat_calls.append(
            (job_id, token, seconds)
        ) or True,
    )
    with worker._lease_heartbeat(generation.id, "lease-heartbeat", 0.03):
        time.sleep(0.06)

    assert len(heartbeat_calls) >= 1
    assert heartbeat_calls[0] == (generation.id, "lease-heartbeat", 0.03)


def test_success_finalization_creates_private_output_and_copies_usage(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-success"
    )
    log = AiCallLog(
        caller_module="customer_image",
        caller_user_id=invite.created_by,
        preset_name="design_image_generation",
        provider_type="direct",
        model="gpt-image-2",
        status="success",
    )
    db.add(log)
    db.commit()
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    snapshot = worker._load_snapshot(generation.id, "lease-success")
    result = ImageJobResult(
        image=ImagePayload(b"result", "image/png"),
        log_id=log.id,
        provider_attempt_count=2,
        billing_certainty="estimated",
        input_tokens=11,
        output_tokens=12,
        total_tokens=23,
        estimated_cost_microusd=456,
    )
    stored = SimpleNamespace(
        relative_path="customer-output/result.png",
        thumbnail_relative_path="customer-output/result_thumb.png",
        mime_type="image/png",
        file_size=77,
        width=640,
        height=480,
        sha256="8" * 64,
    )

    assert worker._finalize_success(snapshot, "lease-success", result, stored) is True

    db.expire_all()
    finished = db.get(CustomerImageGeneration, generation.id)
    output = db.get(CustomerImageAsset, finished.output_asset_id)
    assert finished.status == "succeeded"
    assert finished.ai_call_log_id == log.id
    assert finished.provider_attempt_count == 2
    assert finished.billing_certainty == "estimated"
    assert (finished.input_tokens, finished.output_tokens, finished.total_tokens) == (11, 12, 23)
    assert finished.estimated_cost_microusd == 456
    assert finished.finished_at is not None
    assert finished.claimed_by is finished.lease_token is finished.lease_expires_at is None
    assert output.invite_id == invite.id
    assert output.asset_type == "generated"
    assert output.storage_path == "customer-output/result.png"


def test_refundable_failure_refunds_once_and_missing_log_is_not_linked(
    db, monkeypatch, capsys
):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-refund"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    failure = ImageJobFailure(
        code="validation_error",
        customer_message="图片或参数无效，请调整后重试",
        provider_attempt_count=0,
        log_id=999999,
        refund_eligible=True,
    )

    assert worker.finalize_failure(generation.id, "lease-refund", failure) is True
    db.expire_all()
    first_refunded_at = db.get(CustomerImageGeneration, generation.id).quota_refunded_at
    assert worker.finalize_failure(generation.id, "lease-refund", failure) is False

    db.expire_all()
    failed = db.get(CustomerImageGeneration, generation.id)
    assert failed.status == "failed"
    assert failed.error_code == "validation_error"
    assert failed.ai_call_log_id is None
    assert failed.billing_certainty == "not_billed"
    assert failed.quota_refunded_at == first_refunded_at
    assert db.get(CustomerImageInvite, invite.id).quota_used == 0
    assert "AI call log 999999 is missing" in capsys.readouterr().out


def test_uncertain_provider_failure_does_not_refund(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-uncertain"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    failure = ImageJobFailure(
        code="provider_timeout",
        customer_message="图片服务响应超时，请稍后重试",
        provider_attempt_count=1,
        log_id=None,
        refund_eligible=False,
    )

    assert worker.finalize_failure(generation.id, "lease-uncertain", failure) is True

    db.expire_all()
    failed = db.get(CustomerImageGeneration, generation.id)
    assert failed.billing_certainty == "unknown"
    assert failed.quota_refunded_at is None
    assert db.get(CustomerImageInvite, invite.id).quota_used == 1


def _provider_result(*, attempts=1, log_id=None):
    return ImageJobResult(
        image=ImagePayload(b"provider-image", "image/png"),
        log_id=log_id,
        provider_attempt_count=attempts,
        billing_certainty="estimated",
        input_tokens=4,
        output_tokens=5,
        total_tokens=9,
        estimated_cost_microusd=90,
    )


def _stored_output():
    return SimpleNamespace(
        relative_path="customer-output/executed.png",
        thumbnail_relative_path="customer-output/executed_thumb.png",
        mime_type="image/png",
        file_size=88,
        width=800,
        height=600,
        sha256="6" * 64,
    )


def test_execute_success_normalizes_and_saves_customer_output(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-execute"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(worker, "_call_provider", lambda _snapshot: _provider_result())
    normalized = SimpleNamespace(content=b"normalized")
    monkeypatch.setattr(worker.file_service, "normalize_upload", lambda *_args: normalized)
    save_calls = []
    monkeypatch.setattr(
        worker.file_service,
        "save_private_image",
        lambda image, *, owner_user_id, kind: save_calls.append(
            (image, owner_user_id, kind)
        ) or _stored_output(),
    )

    worker._execute_claimed_job(generation.id, "lease-execute")

    db.expire_all()
    finished = db.get(CustomerImageGeneration, generation.id)
    assert finished.status == "succeeded"
    assert save_calls == [(normalized, invite.id, "customer-output")]
    assert db.get(CustomerImageAsset, finished.output_asset_id).storage_path.endswith(
        "executed.png"
    )


def test_post_provider_storage_failure_never_refunds(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-storage-fail"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(
        worker, "_call_provider", lambda _snapshot: _provider_result(attempts=1)
    )
    monkeypatch.setattr(
        worker.file_service, "normalize_upload", lambda *_args: SimpleNamespace()
    )
    monkeypatch.setattr(
        worker.file_service,
        "save_private_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("disk rejected")),
    )

    worker._execute_claimed_job(generation.id, "lease-storage-fail")

    db.expire_all()
    failed = db.get(CustomerImageGeneration, generation.id)
    assert failed.status == "failed"
    assert failed.provider_attempt_count == 1
    assert failed.quota_refunded_at is None
    assert db.get(CustomerImageInvite, invite.id).quota_used == 1


def test_config_drift_fails_before_provider_and_refunds(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, _product, _logo, _refs, _preset, provider = _queued_generation(
        db, status="running", lease_token="lease-config-drift"
    )
    provider.api_base = "https://changed.example.test/v1"
    db.commit()
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    provider_called = False

    def unexpected_provider(_snapshot):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("configuration drift reached provider")

    monkeypatch.setattr(worker, "_call_provider", unexpected_provider)

    worker._execute_claimed_job(generation.id, "lease-config-drift")

    db.expire_all()
    failed = db.get(CustomerImageGeneration, generation.id)
    assert provider_called is False
    assert failed.status == "failed"
    assert failed.error_code == "validation_error"
    assert failed.quota_refunded_at is not None
    assert db.get(CustomerImageInvite, invite.id).quota_used == 0


def test_late_success_deletes_both_orphan_files(db, monkeypatch):
    from app.customer_image import worker

    generation, *_ = _queued_generation(
        db, status="running", lease_token="lease-late-success"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(worker, "_call_provider", lambda _snapshot: _provider_result())
    monkeypatch.setattr(
        worker.file_service, "normalize_upload", lambda *_args: SimpleNamespace()
    )
    stored = _stored_output()
    monkeypatch.setattr(
        worker.file_service, "save_private_image", lambda *_args, **_kwargs: stored
    )
    monkeypatch.setattr(worker, "_finalize_success", lambda *_args: False)
    deleted = []
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted.append)

    worker._execute_claimed_job(generation.id, "lease-late-success")

    assert deleted == [stored.relative_path, stored.thumbnail_relative_path]


def test_refund_never_makes_zero_quota_negative(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-zero-quota"
    )
    invite.quota_used = 0
    db.commit()
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    failure = ImageJobFailure(
        code="validation_error",
        customer_message="图片或参数无效，请调整后重试",
        provider_attempt_count=0,
        log_id=None,
        refund_eligible=True,
    )

    assert worker.finalize_failure(generation.id, "lease-zero-quota", failure) is True

    db.expire_all()
    failed = db.get(CustomerImageGeneration, generation.id)
    assert db.get(CustomerImageInvite, invite.id).quota_used == 0
    assert failed.quota_refunded_at is None


def test_image_inputs_read_frozen_files_in_logo_then_reference_order(
    db, tmp_path, monkeypatch
):
    from app.customer_image import worker

    generation, *_ = _queued_generation(
        db, status="running", lease_token="lease-input-content"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    snapshot = worker._load_snapshot(generation.id, "lease-input-content")
    resolved = {}
    for index, (relative_path, _mime) in enumerate(snapshot.input_paths):
        path = tmp_path / f"input-{index}.png"
        path.write_bytes(f"content-{index}".encode())
        resolved[relative_path] = path
    monkeypatch.setattr(
        worker.file_service,
        "resolve_private_path",
        lambda relative_path: resolved[relative_path],
    )

    inputs = worker._image_inputs(snapshot)

    assert [item.content for item in inputs] == [
        b"content-0", b"content-1", b"content-2"
    ]
    assert [item.filename for item in inputs] == [
        "image-0.png", "image-1.png", "image-2.png"
    ]


def test_success_with_missing_ai_log_finishes_without_dangling_fk(
    db, monkeypatch, capsys
):
    from app.customer_image import worker

    generation, *_ = _queued_generation(
        db, status="running", lease_token="lease-missing-success-log"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    snapshot = worker._load_snapshot(generation.id, "lease-missing-success-log")
    result = _provider_result(log_id=999998)

    assert worker._finalize_success(
        snapshot, "lease-missing-success-log", result, _stored_output()
    ) is True

    db.expire_all()
    finished = db.get(CustomerImageGeneration, generation.id)
    assert finished.status == "succeeded"
    assert finished.ai_call_log_id is None
    assert "AI call log 999998 is missing" in capsys.readouterr().out


def test_failure_updates_existing_pending_ai_log_with_safe_classification(
    db, monkeypatch
):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-pending-log"
    )
    log = AiCallLog(
        caller_module="customer_image",
        caller_user_id=invite.created_by,
        preset_name="design_image_generation",
        provider_type="direct",
        model="gpt-image-2",
        status="pending",
    )
    db.add(log)
    db.commit()
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    failure = ImageJobFailure(
        code="provider_timeout",
        customer_message="图片服务响应超时，请稍后重试",
        provider_attempt_count=1,
        log_id=log.id,
        refund_eligible=False,
    )

    assert worker.finalize_failure(generation.id, "lease-pending-log", failure) is True

    db.expire_all()
    updated_log = db.get(AiCallLog, log.id)
    assert updated_log.status == "error"
    assert updated_log.error_code == "provider_timeout"
    assert updated_log.error_message == "图片服务响应超时，请稍后重试"


def test_process_queue_claims_only_configured_bounded_batch(db, monkeypatch):
    from app.customer_image import worker
    from app.core.config import get_settings

    first, *_ = _queued_generation(db)
    replicas = []
    for request_id in ("worker-second", "worker-third"):
        replica = CustomerImageGeneration(
            invite_id=first.invite_id,
            product_id=first.product_id,
            logo_asset_id=first.logo_asset_id,
            request_id=request_id,
            product_name_snapshot=first.product_name_snapshot,
            config_version_snapshot=first.config_version_snapshot,
            option_snapshot=deepcopy(first.option_snapshot),
            requirement_snapshot=first.requirement_snapshot,
            parameters_snapshot=deepcopy(first.parameters_snapshot),
            prompt_snapshot=first.prompt_snapshot,
            reference_asset_ids=list(first.reference_asset_ids),
            status="queued",
            preset_name=first.preset_name,
            model=first.model,
            pricing_snapshot=deepcopy(first.pricing_snapshot),
            created_at=first.created_at + timedelta(seconds=len(replicas) + 1),
        )
        db.add(replica)
        replicas.append(replica)
    db.commit()
    second, third = replicas
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "CUSTOMER_IMAGE_WORKER_CONCURRENCY", 2)
    executed = []
    monkeypatch.setattr(
        worker,
        "execute_claimed_job",
        lambda job_id, lease_token: executed.append((job_id, lease_token)),
    )

    worker.process_customer_image_queue()

    db.expire_all()
    assert [job_id for job_id, _token in executed] == [first.id, second.id]
    assert db.get(CustomerImageGeneration, first.id).status == "running"
    assert db.get(CustomerImageGeneration, second.id).status == "running"
    assert db.get(CustomerImageGeneration, third.id).status == "queued"


@pytest.mark.parametrize("read_error", [FileNotFoundError, OSError])
def test_frozen_input_read_failure_is_not_billed_and_refunded_once(
    db, monkeypatch, read_error
):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token=f"lease-input-{read_error.__name__}"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(
        worker.file_service,
        "resolve_private_path",
        lambda _path: (_ for _ in ()).throw(read_error("frozen input missing")),
    )
    provider_called = False

    def unexpected_provider(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("input read failure reached shared runtime")

    monkeypatch.setattr(worker.image_runtime, "call_image_provider", unexpected_provider)

    worker._execute_claimed_job(
        generation.id, f"lease-input-{read_error.__name__}"
    )

    db.expire_all()
    failed = db.get(CustomerImageGeneration, generation.id)
    first_refund = failed.quota_refunded_at
    assert provider_called is False
    assert failed.status == "failed"
    assert failed.billing_certainty == "not_billed"
    assert failed.provider_attempt_count == 0
    assert first_refund is not None
    assert db.get(CustomerImageInvite, invite.id).quota_used == 0
    assert worker.finalize_failure(
        generation.id,
        f"lease-input-{read_error.__name__}",
        ImageJobFailure(
            code="validation_error",
            customer_message="图片或参数无效，请调整后重试",
            provider_attempt_count=0,
            log_id=None,
            refund_eligible=True,
        ),
    ) is False
    db.expire_all()
    assert db.get(CustomerImageGeneration, generation.id).quota_refunded_at == first_refund


def test_commit_ack_error_reconciles_committed_success_and_keeps_output(
    db, monkeypatch
):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-commit-ack"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(worker, "_call_provider", lambda _snapshot: _provider_result())
    monkeypatch.setattr(
        worker.file_service, "normalize_upload", lambda *_args: SimpleNamespace()
    )
    stored = _stored_output()
    monkeypatch.setattr(
        worker.file_service, "save_private_image", lambda *_args, **_kwargs: stored
    )
    real_finalize = worker._finalize_success

    def commit_then_raise(*args):
        assert real_finalize(*args) is True
        raise OSError("commit ACK lost")

    monkeypatch.setattr(worker, "_finalize_success", commit_then_raise)
    deleted = []
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted.append)

    worker._execute_claimed_job(generation.id, "lease-commit-ack")

    db.expire_all()
    finished = db.get(CustomerImageGeneration, generation.id)
    assert finished.status == "succeeded"
    assert db.get(CustomerImageAsset, finished.output_asset_id).storage_path == stored.relative_path
    assert db.get(CustomerImageInvite, invite.id).quota_used == 1
    assert deleted == []


def test_unknown_success_reconciliation_keeps_file_for_audit(db, monkeypatch):
    from app.customer_image import worker

    generation, *_ = _queued_generation(
        db, status="running", lease_token="lease-reconcile-unknown"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(worker, "_call_provider", lambda _snapshot: _provider_result())
    monkeypatch.setattr(
        worker.file_service, "normalize_upload", lambda *_args: SimpleNamespace()
    )
    stored = _stored_output()
    monkeypatch.setattr(
        worker.file_service, "save_private_image", lambda *_args, **_kwargs: stored
    )
    monkeypatch.setattr(
        worker,
        "_finalize_success",
        lambda *_args: (_ for _ in ()).throw(OSError("database ACK unavailable")),
    )
    monkeypatch.setattr(
        worker, "_reconcile_success", lambda *_args: "unknown", raising=False
    )
    deleted = []
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted.append)

    worker._execute_claimed_job(generation.id, "lease-reconcile-unknown")

    db.expire_all()
    assert db.get(CustomerImageGeneration, generation.id).status == "running"
    assert deleted == []


def test_confirmed_uncommitted_success_deletes_output_without_refund(db, monkeypatch):
    from app.customer_image import worker

    generation, invite, *_ = _queued_generation(
        db, status="running", lease_token="lease-reconcile-uncommitted"
    )
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(worker, "_call_provider", lambda _snapshot: _provider_result())
    monkeypatch.setattr(
        worker.file_service, "normalize_upload", lambda *_args: SimpleNamespace()
    )
    stored = _stored_output()
    monkeypatch.setattr(
        worker.file_service, "save_private_image", lambda *_args, **_kwargs: stored
    )
    monkeypatch.setattr(
        worker,
        "_finalize_success",
        lambda *_args: (_ for _ in ()).throw(OSError("commit did not run")),
    )
    deleted = []
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted.append)

    worker._execute_claimed_job(generation.id, "lease-reconcile-uncommitted")

    db.expire_all()
    failed = db.get(CustomerImageGeneration, generation.id)
    assert failed.status == "failed"
    assert failed.provider_attempt_count == 1
    assert failed.quota_refunded_at is None
    assert db.get(CustomerImageInvite, invite.id).quota_used == 1
    assert deleted == [stored.relative_path, stored.thumbnail_relative_path]


def test_unreadable_database_makes_success_reconciliation_unknown(monkeypatch):
    from app.customer_image import worker

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(OSError("database unavailable")),
    )

    assert worker._reconcile_success(123, _stored_output()) == "unknown"
