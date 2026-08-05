"""API contract tests for the private Design Image Studio."""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db


NOW = datetime(2026, 8, 5, 8, 0, 0)


def _row(**values):
    defaults = {
        "id": 1,
        "owner_user_id": 7,
        "session_id": 11,
        "title": "新对话",
        "role": "user",
        "content": "做一张门店海报",
        "asset_type": "upload",
        "mime_type": "image/png",
        "file_size": 123,
        "width": 640,
        "height": 480,
        "source_asset_id": None,
        "status": "queued",
        "mode": "generate",
        "message_id": None,
        "request_message_id": 21,
        "base_asset_id": None,
        "output_asset_id": None,
        "response_message_id": None,
        "retry_of_job_id": None,
        "error_code": None,
        "error_message": None,
        "billing_certainty": None,
        "expires_at": None,
        "started_at": None,
        "finished_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        # Deliberately sensitive fields: serializers must never expose these.
        "storage_path": "7/upload/secret.png",
        "prompt_snapshot": "internal anchor",
        "provider_id": 9,
        "model": "secret-model",
        "preset_name": "secret-preset",
        "parameters": {"size": "1024x1024", "quality": "medium", "secret": 1},
        "pricing_snapshot": {"private": True},
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


@pytest.fixture
def api(monkeypatch, tmp_path):
    from app.design_image import router as module
    from app.design_image import service

    app = FastAPI()
    app.include_router(module.router, prefix="/api/design-image")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7",
        "user_id": 999,
        "roles": [],
        "permissions": [
            "design_image:read",
            "design_image:write",
            "design_image:admin",
        ],
    }

    session = _row(id=11, status="active")
    message = _row(id=21, session_id=11, status="normal")
    asset = _row(id=31, session_id=11, status="draft")
    job = _row(id=41, session_id=11)
    monkeypatch.setattr(service, "get_config", lambda *_a, **_k: {"sizes": ["1024x1024"]})
    monkeypatch.setattr(service, "create_session", lambda *_a, **_k: session)
    monkeypatch.setattr(
        service,
        "list_sessions",
        lambda *_a, **_k: service.SessionPage([session], "next"),
    )
    monkeypatch.setattr(
        service,
        "get_session_detail",
        lambda *_a, **_k: {
            "session": session,
            "messages": [message],
            "assets": [asset],
            "jobs": [job],
        },
    )
    monkeypatch.setattr(service, "create_draft_asset", lambda *_a, **_k: asset)
    monkeypatch.setattr(service, "delete_draft_asset", lambda *_a, **_k: None)
    turn = service.TurnResult(job=job, session=session, message=message, reference_links=[])
    monkeypatch.setattr(service, "create_turn", lambda *_a, **_k: turn)
    monkeypatch.setattr(service, "get_job", lambda *_a, **_k: job)
    monkeypatch.setattr(
        service,
        "get_active_job",
        lambda *_a, **_k: service.ActiveJobResult(job=job, session=session),
    )
    monkeypatch.setattr(service, "retry_job", lambda *_a, **_k: turn)
    monkeypatch.setattr(service, "get_usage", lambda *_a, **_k: {"task_count": 1})
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        service,
        "resolve_asset_content",
        lambda *_a, **_k: service.AssetContent(image, "image/png", ".png"),
    )
    return TestClient(app), app, module, service


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "status"),
    [
        ("get", "/api/design-image/config", {}, 200),
        ("post", "/api/design-image/sessions", {"json": {"title": "灵感"}}, 200),
        ("get", "/api/design-image/sessions?limit=20", {}, 200),
        ("get", "/api/design-image/sessions/11", {}, 200),
        (
            "post",
            "/api/design-image/sessions/11/assets",
            {"files": {"file": ("evil.exe", b"fake", "image/png")}},
            200,
        ),
        ("delete", "/api/design-image/assets/31", {}, 200),
        (
            "post",
            "/api/design-image/sessions/11/turns",
            {"json": {"request_id": "r-1", "prompt": "门店海报"}},
            202,
        ),
        ("get", "/api/design-image/jobs/active", {}, 200),
        ("get", "/api/design-image/jobs/41", {}, 200),
        (
            "post",
            "/api/design-image/jobs/41/retry",
            {"json": {"request_id": "retry-1"}},
            200,
        ),
        ("get", "/api/design-image/usage?owner_user_id=7&status=queued", {}, 200),
    ],
)
def test_every_json_endpoint_returns_ok_envelope_without_sensitive_fields(
    api, method, path, kwargs, status
):
    client, *_ = api
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == 200
    rendered = response.text
    for secret in (
        "storage_path",
        "prompt_snapshot",
        "provider_id",
        "secret-model",
        "secret-preset",
        "pricing_snapshot",
        "internal anchor",
    ):
        assert secret not in rendered


def test_binary_content_is_authenticated_private_and_uses_server_filename(api):
    client, *_ = api
    preview = client.get("/api/design-image/assets/31/content?thumbnail=true")
    assert preview.status_code == 200
    assert preview.content == b"png"
    assert preview.headers["cache-control"] == "private, no-store"
    assert "inline" in preview.headers["content-disposition"]
    assert "evil" not in preview.headers["content-disposition"]

    download = client.get("/api/design-image/assets/31/content?download=true")
    assert "attachment" in download.headers["content-disposition"]
    assert "design-image-31.png" in download.headers["content-disposition"]


def test_user_identity_comes_only_from_authenticated_sub(api, monkeypatch):
    client, _, _, service = api
    captured = []
    monkeypatch.setattr(
        service, "get_config", lambda _db, owner_id: captured.append(owner_id) or {}
    )
    assert client.get("/api/design-image/config").status_code == 200
    assert captured == [7]


def test_user_id_without_sub_is_rejected_before_service_call(api, monkeypatch):
    client, app, _, service = api
    called = []
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 7,
        "roles": [],
        "permissions": ["design_image:read"],
    }
    monkeypatch.setattr(
        service, "get_config", lambda *_a, **_k: called.append(True) or {}
    )

    response = client.get("/api/design-image/config")

    assert response.status_code == 401
    assert called == []


def test_super_admin_permission_bypass_never_bypasses_owner_scope(api, monkeypatch):
    client, app, _, service = api
    captured = []
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": ["super_admin"], "permissions": []
    }
    monkeypatch.setattr(
        service, "get_job", lambda _db, owner_id, _job_id: captured.append(owner_id) or _row(id=41)
    )
    assert client.get("/api/design-image/jobs/41").status_code == 200
    assert captured == [7]


@pytest.mark.parametrize(
    ("path", "permission"),
    [
        ("/api/design-image/config", "design_image:read"),
        ("/api/design-image/sessions", "design_image:write"),
        ("/api/design-image/usage", "design_image:admin"),
    ],
)
def test_representative_routes_enforce_all_three_permissions(api, path, permission):
    client, app, *_ = api
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": []
    }
    method = "post" if path.endswith("sessions") else "get"
    kwargs = {"json": {}} if method == "post" else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert permission in response.text


def test_invalid_token_is_401(api):
    client, app, *_ = api
    app.dependency_overrides.pop(get_current_user)
    response = client.get(
        "/api/design-image/config", headers={"Authorization": "Bearer invalid"}
    )
    assert response.status_code == 401


def test_request_schema_errors_remain_framework_422(api):
    client, *_ = api
    assert client.get("/api/design-image/sessions?limit=0").status_code == 422
    response = client.post(
        "/api/design-image/sessions/11/turns",
        json={"request_id": "bad space", "prompt": ""},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error_name", "expected"),
    [
        ("DesignImageNotFoundError", 404),
        ("DesignImageValidationError", 400),
        ("DesignImageAssetConflictError", 409),
        ("DesignImageActiveJobError", 409),
        ("DesignImageQuotaExceededError", 429),
        ("DesignImageConfigurationError", 503),
        ("DesignImageConsistencyError", 503),
    ],
)
def test_domain_errors_have_explicit_http_mapping(api, monkeypatch, error_name, expected):
    client, _, _, service = api
    error = getattr(service, error_name)("same-message")
    monkeypatch.setattr(service, "get_config", lambda *_a, **_k: (_ for _ in ()).throw(error))
    response = client.get("/api/design-image/config")
    assert response.status_code == expected
    assert "same-message" in response.text


def test_absent_cross_owner_deleted_and_missing_file_share_404(api, monkeypatch):
    client, _, _, service = api
    for message in ("absent", "cross-owner", "deleted", "physical-missing"):
        monkeypatch.setattr(
            service,
            "resolve_asset_content",
            lambda *_a, _message=message, **_k: (_ for _ in ()).throw(
                service.DesignImageNotFoundError("资源不存在")
            ),
        )
        response = client.get("/api/design-image/assets/999/content")
        assert response.status_code == 404
        assert "资源不存在" in response.text


@pytest.mark.parametrize(
    ("method", "path", "service_name", "kwargs"),
    [
        ("get", "/api/design-image/sessions/999", "get_session_detail", {}),
        (
            "post",
            "/api/design-image/sessions/999/assets",
            "create_draft_asset",
            {"files": {"file": ("x.png", b"x", "image/png")}},
        ),
        ("delete", "/api/design-image/assets/999", "delete_draft_asset", {}),
        (
            "post",
            "/api/design-image/sessions/999/turns",
            "create_turn",
            {"json": {"request_id": "foreign", "prompt": "x"}},
        ),
        ("get", "/api/design-image/jobs/999", "get_job", {}),
        (
            "post",
            "/api/design-image/jobs/999/retry",
            "retry_job",
            {"json": {"request_id": "foreign-retry"}},
        ),
    ],
)
def test_all_owner_resource_routes_hide_absent_and_cross_owner(
    api, monkeypatch, method, path, service_name, kwargs
):
    client, _, _, service = api
    monkeypatch.setattr(
        service,
        service_name,
        lambda *_a, **_k: (_ for _ in ()).throw(
            service.DesignImageNotFoundError("资源不存在")
        ),
    )
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 404
    assert "资源不存在" in response.text


def test_upload_is_bounded_closes_file_and_rejects_fake_mime(api, monkeypatch):
    client, _, module, service = api
    monkeypatch.setattr(module, "MAX_UPLOAD_BYTES", 3)
    assert client.post(
        "/api/design-image/sessions/11/assets",
        files={"file": ("huge.png", b"1234", "image/png")},
    ).status_code == 413
    monkeypatch.setattr(module, "MAX_UPLOAD_BYTES", 20 * 1024 * 1024)

    monkeypatch.setattr(
        service,
        "create_draft_asset",
        lambda *_a, **_k: (_ for _ in ()).throw(
            module.file_service.ImageValidationError("图片真实格式与声明的 MIME 不匹配")
        ),
    )
    response = client.post(
        "/api/design-image/sessions/11/assets",
        files={"file": ("fake.png", b"not-png", "image/png")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_bounded_reader_always_closes_upload(api, monkeypatch):
    _, _, module, _ = api

    class FakeUpload:
        def __init__(self):
            self.closed = False

        async def read(self, _amount):
            return b"1234"

        async def close(self):
            self.closed = True

    upload = FakeUpload()
    monkeypatch.setattr(module, "MAX_UPLOAD_BYTES", 3)
    with pytest.raises(HTTPException) as exc_info:
        await module._read_bounded(upload)
    assert exc_info.value.status_code == 413
    assert upload.closed is True


def test_content_resolver_uses_owner_asset_and_hides_physical_absence(
    monkeypatch, tmp_path
):
    from app.design_image import service

    asset = _row(id=31, mime_type="image/png", storage_path="7/upload/a.png")
    monkeypatch.setattr(service, "get_asset", lambda *_a, **_k: asset)
    resolved = []

    def resolve(relative_path):
        resolved.append(relative_path)
        return tmp_path / "missing.png"

    monkeypatch.setattr(service.file_service, "resolve_private_path", resolve)
    with pytest.raises(service.DesignImageNotFoundError, match="资源不存在"):
        service.resolve_asset_content(object(), 7, 31, thumbnail=True)
    assert resolved == ["7/upload/a_thumb.png"]


def test_router_registration_order_permissions_and_architecture_are_static():
    root = Path(__file__).parents[1]
    router_source = (root / "app/design_image/router.py").read_text(encoding="utf-8")
    registry_source = (root / "app/routers.py").read_text(encoding="utf-8")
    assert 'prefix="/api/design-image"' in registry_source
    assert router_source.index('"/jobs/active"') < router_source.index('"/jobs/{job_id}"')
    for permission in ("read", "write", "admin"):
        assert f'require_permission("design_image:{permission}")' in router_source
    for forbidden in ("SessionLocal", "AiProvider", "storage_path ==", "owner_user_id =="):
        assert forbidden not in router_source
    tree = ast.parse(router_source)
    route_functions = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
            for decorator in node.decorator_list
        ):
            route_functions.append(node)
    assert len(route_functions) == 12
    for node in route_functions:
        source = ast.get_source_segment(router_source, node) or ""
        assert "Depends(require_permission(" in source, node.name
