"""OKKI screenshot extraction, deterministic matching, and duplicate guards."""

from datetime import date
from decimal import Decimal
from contextlib import contextmanager
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, inspect, text

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.auth.utils import create_access_token
from app.ai.models import AiPreset, AiProvider
from app.bootstrap import seed_ai
from app.core.database import get_db
from app.invoice import screenshot_import_service, service, xiaoman_service
from app.invoice.models import Invoice, InvoiceDelegateGrant
from app.invoice.schemas import InvoiceCreate, ScreenshotExtraction, ScreenshotResolveRequest
from app.invoice.screenshot_ai import extract_screenshot
from app.invoice.screenshot_token import issue_preview_token


SOURCE_HASH = "a" * 64


@contextmanager
def _api_client(db, permissions):
    from app.invoice.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": "27", "username": "katy", "roles": [], "permissions": permissions,
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _sample_extraction(**overrides) -> ScreenshotExtraction:
    payload = {
        "order_name": "凯丽比努尔#260808",
        "order_status": "已完成(已确认)",
        "customer_name": "hair_madebymads",
        "salesperson_name": "Katy",
        "department_name": "乘风",
        "order_date": "2026-08-25",
        "currency": "USD",
        "order_amount": "90.14",
        "product_amount": "90.14",
        "additional_fee_amount": "0",
        "items": [{
            "source_row": 1,
            "product_no": "5730",
            "product_name": "Super Double Drawn Genius Weft/18/#8TP18/60/20g",
            "product_display": "Super Double Drawn Genius Weft",
            "product_model": "B1天才发帘（宽度12\"）",
            "length": "18",
            "color": "#8TP18/60",
            "weight": "20g",
            "quantity": 3,
            "unit_price": "30.048",
            "subtotal": "90.14",
            "confidence": 0.99,
        }],
        "confidence": {"order_amount": 0.99},
    }
    payload.update(overrides)
    return ScreenshotExtraction.model_validate(payload)


def _seed_example(db) -> None:
    db.add(ArkUser(
        id=27, username="katy", password_hash="test", real_name="Katy",
        is_active=True, okki_department_id=24925, okki_department_name="乘风",
    ))
    db.add(ArkUserExternalBinding(
        ark_user_id=27,
        provider="okki",
        external_account_id="57130855",
        external_display_name="Katy",
        binding_status="active",
        is_primary=True,
    ))
    db.execute(text("""
        INSERT INTO lsordertest.customer_info
            (company_id, company_name, country_name)
        VALUES ('105720449849411', 'hair_madebymads', 'Denmark')
    """))
    db.execute(text("ALTER TABLE lsordertest.okki_orders ADD COLUMN name TEXT"))
    db.execute(text("""
        INSERT INTO lsordertest.okki_orders
            (order_id, order_no, name, company_id, amount_usd, user_id,
             account_date, status_name, departments)
        VALUES
            ('105724678036852', '25278', '凯丽比努尔#260808',
             '105720449849411', 90.14, '57130855', '2026-08-25',
             '已完成(已确认)', NULL)
    """))
    db.execute(text("""
        CREATE TABLE lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY,
            product_no TEXT,
            name TEXT,
            model TEXT,
            color TEXT,
            size TEXT,
            unit TEXT,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE lsordertest.okki_inventory (
            product_id INTEGER,
            sku_id INTEGER,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_products
            (product_id, product_no, name, model, color, size, unit, disable_flag)
        VALUES
            (86457591838718, '5730',
             'Super Double Drawn Genius Weft/18/#8TP18/60/20g', '',
             '#8TP18/60', '18', '20g', 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
        VALUES (86457591838718, 86457591838775, 0)
    """))
    db.commit()


def _resolve(db, extraction=None, **overrides):
    request = {
        "extraction": extraction or _sample_extraction(),
        "source_image_sha256": SOURCE_HASH,
        "order_type": "stock",
    }
    request.update(overrides)
    return screenshot_import_service.resolve_preview(
        db,
        request=ScreenshotResolveRequest.model_validate(request),
        actor_user_id=27,
    )


def test_sample_screenshot_resolves_to_authoritative_okki_records(db):
    _seed_example(db)

    result = _resolve(db)

    assert result["ready"] is True
    assert result["customer_match"]["selected"]["company_id"] == "105720449849411"
    assert result["sales_match"]["selected"]["id"] == 27
    assert result["source_order"]["order_id"] == "105724678036852"
    row = result["import_preview"]["rows"][0]
    assert row["matched_product"]["product_id"] == 86457591838718
    assert row["matched_product"]["sku_id"] == 86457591838775
    assert result["totals"]["calculated_product_amount"] == "90.14"
    assert result["invoice_patch"]["source_type"] == "okki_screenshot"
    assert result["invoice_patch"]["items"][0]["price_per_piece"] == Decimal("30.048")


def test_product_number_conflict_blocks_preview(db):
    _seed_example(db)
    db.execute(text("""
        INSERT INTO lsordertest.okki_products
            (product_id, product_no, name, model, color, size, unit, disable_flag)
        VALUES (999, '9999', 'Other Hair/20/#1B/100g', '', '#1B', '20', '100g', 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
        VALUES (999, 1999, 0)
    """))
    extraction = _sample_extraction(items=[{
        **_sample_extraction().items[0].model_dump(),
        "product_no": "9999",
    }])

    result = _resolve(db, extraction)

    assert result["ready"] is False
    assert any("产品编号与" in message for message in result["blockers"])


def test_unmatched_or_unauthorized_salesperson_blocks_preview(db):
    _seed_example(db)
    db.add(ArkUser(id=28, username="other", password_hash="test", real_name="Other", is_active=True))
    db.add(ArkUserExternalBinding(
        ark_user_id=28, provider="okki", external_account_id="999",
        external_display_name="Other", binding_status="active", is_primary=True,
    ))
    db.commit()

    result = _resolve(db, _sample_extraction(salesperson_name="Other"))

    assert result["ready"] is False
    assert result["sales_match"]["selected"] is None
    assert any("代创建权限" in message for message in result["blockers"])


def test_unbound_delegate_cannot_be_selected_for_screenshot_source(db):
    _seed_example(db)
    db.add(ArkUser(id=28, username="other", password_hash="test", real_name="Other", is_active=True))
    db.add(InvoiceDelegateGrant(delegate_user_id=27, sales_user_id=28, created_by=27))
    db.commit()

    result = _resolve(db, sales_user_id=28)

    assert result["ready"] is False
    assert result["sales_match"]["selected"] is None


def test_screenshot_invoice_is_guarded_by_order_and_image_and_cannot_sync(db):
    _seed_example(db)
    preview = _resolve(db)
    invoice = service.create_invoice(
        db,
        InvoiceCreate.model_validate({
            **preview["invoice_patch"],
            "invoice_no": "KATY-KC-0801",
        }),
        user_id=27,
        allow_screenshot_source=True,
    )
    db.commit()

    assert invoice.source_order_no == "25278"
    assert invoice.total_amount == Decimal("90.14")
    assert xiaoman_service.sync_invoice(db, invoice, operator_id=27)["ok"] is False

    duplicate = _resolve(db)
    assert duplicate["ready"] is False
    assert any("已导入发票" in message or "已创建发票" in message for message in duplicate["blockers"])


def test_signed_preview_rejects_client_tampering_before_create(db):
    _seed_example(db)
    preview = _resolve(db)
    patch = {**preview["invoice_patch"], "invoice_no": "KATY-KC-0802"}
    patch["customer_id"] = "tampered"

    with pytest.raises(ValueError, match="内容已被修改"):
        service.create_invoice(
            db, InvoiceCreate.model_validate(patch), user_id=27,
            allow_screenshot_source=True,
        )


def test_signed_preview_rejects_same_total_product_detail_tampering(db):
    _seed_example(db)
    preview = _resolve(db)
    patch = {**preview["invoice_patch"], "invoice_no": "KATY-KC-0802-ITEM"}
    patch["items"] = [{**patch["items"][0], "model": "tampered-model"}]

    with pytest.raises(ValueError, match="内容已被修改"):
        service.create_invoice(
            db, InvoiceCreate.model_validate(patch), user_id=27,
            allow_screenshot_source=True,
        )


def test_generic_create_rejects_screenshot_provenance(db):
    _seed_example(db)
    preview = _resolve(db)

    with pytest.raises(ValueError, match="必须通过截图预览入口"):
        service.create_invoice(
            db,
            InvoiceCreate.model_validate({
                **preview["invoice_patch"],
                "invoice_no": "KATY-KC-0802-GENERIC",
            }),
            user_id=27,
        )


def test_server_requires_okki_binding_for_source_salesperson(db):
    _seed_example(db)
    preview = _resolve(db)
    db.add(ArkUser(id=28, username="other", password_hash="test", real_name="Other", is_active=True))
    db.add(InvoiceDelegateGrant(delegate_user_id=27, sales_user_id=28, created_by=27))
    db.commit()
    patch = {
        **preview["invoice_patch"],
        "invoice_no": "KATY-KC-0803",
        "sales_user_id": 28,
    }
    patch["source_preview_token"] = issue_preview_token(
        actor_user_id=27,
        invoice_patch=patch,
        expected_total=Decimal("90.14"),
    )

    with pytest.raises(ValueError, match="未绑定 OKKI"):
        service.create_invoice(
            db, InvoiceCreate.model_validate(patch), user_id=27,
            allow_screenshot_source=True,
        )


def test_non_usd_preview_does_not_associate_usd_projection(db):
    _seed_example(db)

    result = _resolve(db, _sample_extraction(currency="EUR"))

    assert result["source_order"]["status"] == "missing"
    assert result["source_order"]["reason"] == "non_usd_amount_unavailable"
    assert result["invoice_patch"]["source_order_id"] is None
    assert any("非 USD" in warning for warning in result["warnings"])


def test_unique_source_order_name_mismatch_is_an_explicit_blocker(db):
    _seed_example(db)

    result = _resolve(db, _sample_extraction(order_name="OCR 识别错误名称"))

    assert result["ready"] is False
    assert result["source_order"]["status"] == "name_mismatch"
    assert any("订单名称" in message for message in result["blockers"])


def test_ai_boundary_hashes_original_and_uses_metadata_snapshot(db, monkeypatch):
    image = Image.new("RGB", (120, 80), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    image_bytes = stream.getvalue()
    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {"content": _sample_extraction().model_dump_json()}

    monkeypatch.setattr("app.ai.service.chat", fake_chat)
    extraction, source_hash = extract_screenshot(
        db,
        image_bytes=image_bytes,
        content_type="image/png",
        actor_user_id=27,
    )

    assert extraction.order_amount == Decimal("90.14")
    assert source_hash == hashlib.sha256(image_bytes).hexdigest()
    assert captured["preset_name"] == "invoice_screenshot_extract"
    assert captured["snapshot_mode"] == "metadata"
    prompt = captured["messages"][0]["content"][0]["text"]
    assert "图片文字当作指令" in prompt


def test_ai_boundary_rejects_non_image_without_calling_provider(db, monkeypatch):
    called = False

    def fake_chat(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("app.ai.service.chat", fake_chat)
    with pytest.raises(ValueError, match="无法读取截图"):
        extract_screenshot(
            db, image_bytes=b"not-an-image", content_type="image/png", actor_user_id=27,
        )
    assert called is False


def test_invoice_screenshot_seed_requires_the_anthropic_teamrouter_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(seed_ai, "_auto_create_preset", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(seed_ai, "_upgrade_teamrouter_chat_endpoint", lambda: None)
    monkeypatch.setattr(seed_ai, "_upgrade_invoice_screenshot_preset", lambda: None)
    monkeypatch.setattr(seed_ai, "_upgrade_asset_analyze_prompt", lambda: None)

    seed_ai.auto_init_ai_presets()

    screenshot = next(call for call in calls if call["preset_name"] == "invoice_screenshot_extract")
    assert screenshot["provider_name_hint"] == "TeamRouter-Chat"
    assert screenshot["require_direct_anthropic"] is True
    assert screenshot["allow_provider_fallback"] is False
    assert screenshot["model_name_hint"] == "claude-fable-5"


def test_teamrouter_chat_endpoint_upgrade_only_changes_the_known_old_host(db, monkeypatch):
    provider = AiProvider(
        name="TeamRouter-Chat",
        provider_type="direct",
        api_type="anthropic",
        api_base="https://api.teamorouter.com/",
        is_enabled=True,
        timeout_sec=120,
    )
    db.add(provider)
    db.commit()

    class SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(seed_ai, "SessionLocal", SessionContext)
    seed_ai._upgrade_teamrouter_chat_endpoint()

    db.refresh(provider)
    assert provider.api_base == "https://api.teamorouter.cn"

    provider.api_base = "https://chat.internal.example/v1"
    db.commit()
    seed_ai._upgrade_teamrouter_chat_endpoint()
    db.refresh(provider)
    assert provider.api_base == "https://chat.internal.example/v1"


def test_strict_screenshot_seed_does_not_fallback_to_mimo(db, monkeypatch):
    db.add(AiProvider(
        name="MIMO",
        provider_type="direct",
        api_type="openai",
        api_base="https://example.invalid/v1",
        is_enabled=True,
        timeout_sec=120,
    ))
    db.commit()

    class SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(seed_ai, "SessionLocal", SessionContext)
    seed_ai._auto_create_preset(
        preset_name="invoice_screenshot_extract",
        system_prompt="extract",
        parameters={"max_tokens": 4096},
        description="screenshot",
        provider_name_hint="TeamRouter-Chat",
        require_direct_anthropic=True,
        allow_provider_fallback=False,
        model_name_hint="claude-fable-5",
    )

    assert db.query(AiPreset).filter(AiPreset.preset_name == "invoice_screenshot_extract").first() is None


def test_existing_mimo_screenshot_preset_is_repaired_idempotently(db, monkeypatch):
    mimo = AiProvider(
        name="MIMO", provider_type="direct", api_type="openai",
        api_base="https://mimo.example/v1", is_enabled=True, timeout_sec=120,
    )
    target = AiProvider(
        name="TeamRouter-Chat", provider_type="direct", api_type="anthropic",
        api_base="https://api.teamorouter.cn", is_enabled=True, timeout_sec=120,
    )
    db.add_all([mimo, target])
    db.flush()
    preset = AiPreset(
        preset_name="invoice_screenshot_extract",
        provider_id=mimo.id,
        model="mimo-v2.5-pro",
        system_prompt="管理员自定义提示词",
        parameters={"temperature": 0},
        description="customized",
        is_enabled=False,
    )
    db.add(preset)
    db.commit()

    class SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(seed_ai, "SessionLocal", SessionContext)
    seed_ai._upgrade_invoice_screenshot_preset()
    seed_ai._upgrade_invoice_screenshot_preset()

    db.refresh(preset)
    assert preset.provider_id == target.id
    assert preset.model == "claude-fable-5"
    assert preset.system_prompt == "管理员自定义提示词"
    assert preset.parameters == {"temperature": 0}
    assert preset.is_enabled is False

    preset.model = "mimo-v2.5-pro"
    db.commit()
    seed_ai._upgrade_invoice_screenshot_preset()
    db.refresh(preset)
    assert preset.provider_id == target.id
    assert preset.model == "claude-fable-5"


def test_screenshot_preset_upgrade_waits_for_an_enabled_target(db, monkeypatch):
    mimo = AiProvider(
        name="MIMO", provider_type="direct", api_type="openai",
        api_base="https://mimo.example/v1", is_enabled=True, timeout_sec=120,
    )
    target = AiProvider(
        name="TeamRouter-Chat", provider_type="direct", api_type="anthropic",
        api_base="https://api.teamorouter.cn", is_enabled=False, timeout_sec=120,
    )
    db.add_all([mimo, target])
    db.flush()
    preset = AiPreset(
        preset_name="invoice_screenshot_extract", provider_id=mimo.id,
        model="mimo-v2.5-pro", is_enabled=True,
    )
    db.add(preset)
    db.commit()

    class SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(seed_ai, "SessionLocal", SessionContext)
    seed_ai._upgrade_invoice_screenshot_preset()
    db.refresh(preset)
    assert preset.provider_id == mimo.id

    target.is_enabled = True
    db.commit()
    seed_ai._upgrade_invoice_screenshot_preset()
    db.refresh(preset)
    assert preset.provider_id == target.id
    assert preset.model == "claude-fable-5"


def test_screenshot_preview_endpoint_requires_write_permission(db):
    with _api_client(db, ["invoice:read"]) as client:
        response = client.post(
            "/api/invoice/import/screenshot/preview",
            files={"image": ("order.png", b"not-used", "image/png")},
        )

    assert response.status_code == 403


def test_screenshot_preview_endpoint_accepts_multipart_and_actor(db, monkeypatch):
    captured = {}

    def fake_recognize(_db, **kwargs):
        captured.update(kwargs)
        return {"ready": False, "blockers": ["test"]}

    monkeypatch.setattr(screenshot_import_service, "recognize_preview", fake_recognize)
    with _api_client(db, ["invoice:write"]) as client:
        response = client.post(
            "/api/invoice/import/screenshot/preview?order_type=production",
            files={"image": ("order.png", b"png-bytes", "image/png")},
        )

    assert response.status_code == 200
    assert response.json()["data"]["ready"] is False
    assert captured == {
        "image_bytes": b"png-bytes",
        "content_type": "image/png",
        "order_type": "production",
        "actor_user_id": 27,
    }


def test_screenshot_preview_rejects_oversized_upload_before_ai(db, monkeypatch):
    called = False

    def fake_recognize(_db, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(screenshot_import_service, "recognize_preview", fake_recognize)
    with _api_client(db, ["invoice:write"]) as client:
        response = client.post(
            "/api/invoice/import/screenshot/preview",
            files={"image": ("order.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
        )

    assert response.status_code == 400
    assert "10MB" in response.text
    assert called is False


def test_dedicated_screenshot_create_endpoint_accepts_signed_preview(db):
    _seed_example(db)
    preview = _resolve(db)
    payload = InvoiceCreate.model_validate({
        **preview["invoice_patch"],
        "invoice_no": "KATY-KC-0804",
    }).model_dump(mode="json")

    with _api_client(db, ["invoice:write"]) as client:
        response = client.post(
            "/api/invoice/import/screenshot/create",
            json=payload,
        )

    assert response.status_code == 201
    assert response.json()["data"]["source_type"] == "okki_screenshot"


def test_dedicated_screenshot_create_endpoint_rejects_manual_payload(db):
    _seed_example(db)

    with _api_client(db, ["invoice:write"]) as client:
        response = client.post(
            "/api/invoice/import/screenshot/create",
            json={
                "order_type": "stock",
                "customer_id": "105720449849411",
                "customer_name": "hair_madebymads",
                "invoice_date": "2026-08-25",
                "currency": "USD",
                "sales_user_id": 27,
                "items": [],
            },
        )

    assert response.status_code == 400
    assert "只接受" in response.text


def test_confidence_values_must_be_probabilities():
    with pytest.raises(ValueError, match="confidence"):
        _sample_extraction(confidence={"order_amount": 1.5})


def test_extracted_source_rows_must_be_unique():
    line = _sample_extraction().items[0].model_dump()
    with pytest.raises(ValueError, match="source_row"):
        _sample_extraction(items=[line, line])


def test_migration_119_upgrades_and_downgrades_legacy_invoice_table():
    path = Path(__file__).parents[1] / "alembic/versions/119_invoice_screenshot_src.py"
    spec = importlib.util.spec_from_file_location("migration_119", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.down_revision == "118_agent_runtime"
    migration_engine = create_engine("sqlite:///:memory:")

    with migration_engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ark_invoices (id INTEGER PRIMARY KEY, invoice_no TEXT NOT NULL)"
        ))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        columns = {item["name"] for item in inspect(connection).get_columns("ark_invoices")}
        indexes = {item["name"]: item["unique"] for item in inspect(connection).get_indexes("ark_invoices")}
        assert {
            "source_type", "source_order_id", "source_order_no",
            "source_order_name", "source_image_sha256",
        } <= columns
        assert indexes["uq_invoice_source_order"] == 1
        assert indexes["uq_invoice_source_image"] == 1
        migration.upgrade()  # operationally retry-safe
        migration.downgrade()
        columns = {item["name"] for item in inspect(connection).get_columns("ark_invoices")}
        assert not any(name.startswith("source_") for name in columns)
