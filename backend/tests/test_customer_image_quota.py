"""Atomic quota and immutable generation submission contracts."""

from datetime import datetime, timedelta

import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine, event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker

from app.core.database import Base

from app.ai.image_service import build_image_config_version
from app.ai.models import AiPreset, AiProvider
from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageInviteProduct,
    CustomerImageOptionValue,
    CustomerImageProduct,
    CustomerImageProductAsset,
    CustomerImageProductOption,
)
from app.customer_image.schemas import CustomerImageGenerationCreate


def _ready_invite(db, *, quota_total=2):
    provider = AiProvider(
        name="Customer image provider",
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
            "size": "1536x1024",
            "quality": "high",
            "download_hosts": ["CDN.EXAMPLE.TEST", "cdn.example.test"],
            "rate_card": {"output_image_per_million": "40"},
        },
        is_enabled=True,
    )
    product = CustomerImageProduct(
        name="Mailer Box",
        category="packaging",
        fixed_prompt="Keep the mailer box exact.",
        output_prompt="Render a commercial product image.",
        config_version=3,
        is_published=True,
        created_by=7,
    )
    db.add_all([preset, product])
    db.flush()
    option = CustomerImageProductOption(
        product_id=product.id,
        key="finish",
        label="Finish",
        control_type="single_choice",
        required=True,
        default_value="matte",
    )
    db.add(option)
    db.flush()
    db.add(CustomerImageOptionValue(
        option_id=option.id,
        value="matte",
        label="Matte",
        prompt_fragment="Use a matte finish.",
        is_active=True,
    ))
    invite = CustomerImageInvite(
        customer_id="acme",
        customer_name_snapshot="Acme",
        created_by=7,
        okki_salesperson_id_snapshot="1007",
        token_hash="a" * 64,
        token_suffix="aaaaaa",
        starts_at=datetime.utcnow() - timedelta(minutes=1),
        expires_at=datetime.utcnow() + timedelta(days=1),
        quota_total=quota_total,
        quota_used=0,
    )
    db.add(invite)
    db.flush()
    logo = CustomerImageAsset(
        invite_id=invite.id,
        asset_type="logo",
        storage_path="customer-logo/logo.png",
        mime_type="image/png",
        file_size=10,
        width=100,
        height=80,
        sha256="b" * 64,
    )
    db.add(logo)
    db.flush()
    invite.current_logo_asset_id = logo.id
    db.add(CustomerImageInviteProduct(invite_id=invite.id, product_id=product.id))
    references = [
        CustomerImageProductAsset(
            product_id=product.id,
            role="reference",
            storage_path=f"customer-product/ref-{position}.png",
            mime_type="image/png",
            file_size=10,
            width=100,
            height=80,
            sha256=str(position) * 64,
            position=position,
        )
        for position in (20, 10)
    ]
    db.add_all(references)
    db.commit()
    return invite, product, logo, references, preset, provider


def _payload(product, request_id="request-1"):
    return CustomerImageGenerationCreate(
        product_id=product.id,
        config_version=product.config_version,
        request_id=request_id,
        selections={"finish": "matte"},
        requirement="  Add a festive ribbon.  ",
    )


def test_same_request_replays_original_without_second_quota_use(db):
    from app.customer_image.service import create_generation

    invite, product, *_ = _ready_invite(db, quota_total=1)
    payload = _payload(product)

    first = create_generation(db, invite.id, payload)
    second = create_generation(db, invite.id, payload)

    db.refresh(invite)
    assert first.id == second.id
    assert invite.quota_used == 1
    assert db.query(CustomerImageGeneration).count() == 1


def test_generation_freezes_logo_product_options_assets_and_preset(db):
    from app.customer_image.service import create_generation

    invite, product, logo, references, preset, provider = _ready_invite(db)
    generation = create_generation(db, invite.id, _payload(product))

    assert generation.status == "queued"
    assert generation.logo_asset_id == logo.id
    assert generation.product_name_snapshot == "Mailer Box"
    assert generation.config_version_snapshot == 3
    assert generation.option_snapshot == [
        {"key": "finish", "label": "Finish", "value": "matte", "value_label": "Matte"}
    ]
    assert generation.requirement_snapshot == "Add a festive ribbon."
    assert generation.reference_asset_ids == [references[1].id, references[0].id]
    assert generation.preset_name == "design_image_generation"
    assert generation.model == "gpt-image-2"
    assert generation.pricing_snapshot == {"output_image_per_million": "40"}
    assert generation.parameters_snapshot == {
        "size": "1536x1024",
        "quality": "high",
        "provider_id": provider.id,
        "config_version": {
            "provider_id": provider.id,
            "fingerprint": build_image_config_version(preset, provider),
        },
        "download_hosts": ["cdn.example.test"],
        "input_asset_ids": [logo.id, references[1].id, references[0].id],
    }
    assert "encrypted-secret" not in str(generation.parameters_snapshot)

    frozen = (
        generation.prompt_snapshot,
        generation.option_snapshot,
        generation.requirement_snapshot,
        generation.parameters_snapshot,
        generation.reference_asset_ids,
        generation.pricing_snapshot,
    )
    product.fixed_prompt = "changed"
    product.config_version = 4
    invite.current_logo_asset_id = None
    preset.parameters = {"size": "1024x1024", "quality": "low"}
    references[0].retired_at = datetime.utcnow()
    db.commit()
    db.refresh(generation)
    assert frozen == (
        generation.prompt_snapshot,
        generation.option_snapshot,
        generation.requirement_snapshot,
        generation.parameters_snapshot,
        generation.reference_asset_ids,
        generation.pricing_snapshot,
    )


def test_last_quota_slot_accepts_only_one_new_request(db):
    from app.customer_image.service import CustomerImageQuotaError, create_generation

    invite, product, *_ = _ready_invite(db, quota_total=1)
    accepted = create_generation(db, invite.id, _payload(product, "winner"))
    with pytest.raises(CustomerImageQuotaError):
        create_generation(db, invite.id, _payload(product, "loser"))

    db.expire_all()
    assert accepted.id is not None
    assert db.get(CustomerImageInvite, invite.id).quota_used == 1
    assert db.query(CustomerImageGeneration).count() == 1


def test_duplicate_insert_rolls_back_only_savepoint_and_replays_winner(db, monkeypatch):
    from app.customer_image import service

    invite, product, *_ = _ready_invite(db, quota_total=2)
    payload = _payload(product)
    winner = service.create_generation(db, invite.id, payload)
    original_lookup = service._existing_generation
    lookup_count = 0

    def stale_then_current(session, invite_id, request_id):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return None
        return original_lookup(session, invite_id, request_id)

    rollback_count = 0
    original_rollback = db.rollback

    def tracked_rollback():
        nonlocal rollback_count
        rollback_count += 1
        return original_rollback()

    monkeypatch.setattr(service, "_existing_generation", stale_then_current)
    monkeypatch.setattr(db, "rollback", tracked_rollback)

    replay = service.create_generation(db, invite.id, payload)

    db.expire_all()
    assert replay.id == winner.id
    assert db.get(CustomerImageInvite, invite.id).quota_used == 1
    assert db.query(CustomerImageGeneration).count() == 1
    assert rollback_count == 0


def test_quota_sql_locks_invite_and_increments_only_when_capacity_remains():
    from app.customer_image import service

    lock_sql = str(
        service._locked_invite_statement(7).compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).upper()
    quota_sql = str(
        service._quota_increment_statement(7).compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).upper()

    assert "FOR UPDATE" in lock_sql
    assert "QUOTA_USED < ARK_CUSTOMER_IMAGE_INVITES.QUOTA_TOTAL" in quota_sql
    assert "QUOTA_USED=(ARK_CUSTOMER_IMAGE_INVITES.QUOTA_USED + 1)" in quota_sql


def test_concurrent_last_slot_never_overconsumes_quota(tmp_path):
    from app.customer_image.service import CustomerImageQuotaError, create_generation

    race_engine = create_engine(
        f"sqlite:///{tmp_path / 'customer-image-quota.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(race_engine, "connect")
    def _configure_sqlite(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(race_engine)
    factory = sessionmaker(bind=race_engine, expire_on_commit=False)
    with factory() as setup:
        invite, product, *_ = _ready_invite(setup, quota_total=1)
        invite_id = invite.id
        product_id = product.id
        config_version = product.config_version

    start = Barrier(2)

    def submit(request_id):
        with factory() as session:
            start.wait()
            try:
                generation = create_generation(
                    session,
                    invite_id,
                    CustomerImageGenerationCreate(
                        product_id=product_id,
                        config_version=config_version,
                        request_id=request_id,
                        selections={"finish": "matte"},
                    ),
                )
                return ("accepted", generation.id)
            except CustomerImageQuotaError:
                return ("quota", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, ("race-a", "race-b")))

    with factory() as verify:
        assert sorted(status for status, _ in outcomes) == ["accepted", "quota"]
        assert verify.get(CustomerImageInvite, invite_id).quota_used == 1
        assert verify.query(CustomerImageGeneration).count() == 1
