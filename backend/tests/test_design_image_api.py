"""API contract tests for the private Design Image Studio."""

from __future__ import annotations

import io
from datetime import datetime
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
        "interaction_json": None,
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
    clarification = _row(
        id=22,
        session_id=11,
        role="assistant",
        content="请选择生成方式",
        status="normal",
        interaction_json={
            "type": "output_mode_confirmation",
            "status": "pending",
            "source_message_id": 21,
            "request_id": "r-1",
            "count": 2,
            "labels": ["正面", "侧面 45°"],
            "request": {
                "base_asset_id": None,
                "reference_asset_ids": [],
                "size": "1024x1024",
                "quality": "medium",
            },
            "selected_mode": None,
            "resolved_at": None,
        },
    )
    turn = service.TurnResult(
        mode="jobs",
        session=session,
        message=message,
        jobs=(job,),
    )
    monkeypatch.setattr(service, "create_turn", lambda *_a, **_k: turn)
    monkeypatch.setattr(service, "get_job", lambda *_a, **_k: job)
    monkeypatch.setattr(
        service,
        "list_active_jobs",
        lambda *_a, **_k: [job],
    )
    monkeypatch.setattr(service, "retry_job", lambda *_a, **_k: turn)
    monkeypatch.setattr(service, "resolve_message_action", lambda *_a, **_k: turn)
    monkeypatch.setattr(service, "get_usage", lambda *_a, **_k: {"task_count": 1})
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        service,
        "open_asset_content",
        lambda *_a, **_k: service.AssetContent(io.BytesIO(b"png"), "image/png", ".png"),
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
        (
            "post",
            "/api/design-image/sessions/11/messages/22/actions",
            {
                "json": {
                    "request_id": "action-1",
                    "action": "choose_output_mode",
                    "mode": "separate",
                }
            },
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


def test_turn_and_retry_use_unified_jobs_array_without_single_job_field(api):
    client, *_ = api
    for method, path, payload in (
        ("post", "/api/design-image/sessions/11/turns", {"request_id": "r-1", "prompt": "生成图片"}),
        ("post", "/api/design-image/jobs/41/retry", {"request_id": "retry-1"}),
        (
            "post",
            "/api/design-image/sessions/11/messages/22/actions",
            {"request_id": "action-1", "action": "choose_output_mode", "mode": "separate"},
        ),
    ):
        response = getattr(client, method)(path, json=payload)
        assert response.status_code in (200, 202), response.text
        data = response.json()["data"]
        assert data["mode"] == "jobs"
        assert [job["id"] for job in data["jobs"]] == [41]
        assert "job" not in data


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


def test_usage_status_is_a_closed_api_enum_and_never_calls_service(api, monkeypatch):
    client, _, _, service = api
    called = []
    monkeypatch.setattr(
        service, "get_usage", lambda *_a, **_k: called.append(True) or {}
    )

    response = client.get("/api/design-image/usage?status=not-a-job-status")

    assert response.status_code == 422
    assert called == []


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
    if error_name == "DesignImageValidationError":
        assert "same-message" not in response.text
        assert "请求参数不正确" in response.text
    else:
        assert "same-message" in response.text


@pytest.mark.parametrize(
    ("error", "status_code", "code", "meta"),
    [
        (
            lambda service: service.DesignImageValidationError(
                "一次最多生成 4 张，请拆成多轮请求。",
                code="multi_output_limit",
                public_meta={"max_outputs": 4},
            ),
            400,
            "multi_output_limit",
            {"max_outputs": 4},
        ),
        (
            lambda service: service.DesignImageQuotaExceededError(
                "今日生成额度不足", remaining=2
            ),
            429,
            "daily_limit_exceeded",
            {"remaining": 2},
        ),
        (
            lambda service: service.DesignImageValidationError(
                "附件已失效，请重新上传后发送新请求。",
                code="attachment_unavailable",
            ),
            400,
            "attachment_unavailable",
            None,
        ),
    ],
)
def test_safe_business_errors_expose_only_stable_code_message_and_meta(
    api, monkeypatch, error, status_code, code, meta
):
    client, _, _, service = api
    monkeypatch.setattr(
        service,
        "create_turn",
        lambda *_a, **_k: (_ for _ in ()).throw(error(service)),
    )

    response = client.post(
        "/api/design-image/sessions/11/turns",
        json={"request_id": "business-error", "prompt": "生成图片"},
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == {
        "code": code,
        "message": str(error(service)),
        "meta": meta,
    }


def test_absent_cross_owner_deleted_and_missing_file_share_404(api, monkeypatch):
    client, _, _, service = api
    for message in ("absent", "cross-owner", "deleted", "physical-missing"):
        monkeypatch.setattr(
            service,
            "open_asset_content",
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
    monkeypatch.setattr(module.file_service, "effective_max_upload_bytes", lambda: 3)
    assert client.post(
        "/api/design-image/sessions/11/assets",
        files={"file": ("huge.png", b"1234", "image/png")},
    ).status_code == 413
    monkeypatch.setattr(
        module.file_service, "effective_max_upload_bytes", lambda: 20 * 1024 * 1024
    )

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


def test_router_rejects_configured_upload_limit_before_service(api, monkeypatch):
    client, _, module, service = api
    called = []
    monkeypatch.setattr(
        module.file_service.get_settings(), "DESIGN_IMAGE_MAX_UPLOAD_MB", 1
    )
    monkeypatch.setattr(
        service, "create_draft_asset", lambda *_a, **_k: called.append(True)
    )

    response = client.post(
        "/api/design-image/sessions/11/assets",
        files={"file": ("large.png", b"x" * (1024 * 1024 + 1), "image/png")},
    )

    assert response.status_code == 413
    assert "1MiB" in response.text
    assert called == []


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
    monkeypatch.setattr(module.file_service, "effective_max_upload_bytes", lambda: 3)
    with pytest.raises(HTTPException) as exc_info:
        await module._read_bounded(upload)
    assert exc_info.value.status_code == 413
    assert upload.closed is True


def test_content_open_uses_owner_asset_and_hides_pre_open_absence(
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
        service.open_asset_content(object(), 7, 31, thumbnail=True)
    assert resolved == ["7/upload/a_thumb.png"]


def test_opened_asset_stream_survives_path_disappearance_and_is_closed(
    api, monkeypatch, tmp_path
):
    client, app, _, service = api
    payload = b"opened-before-delete"
    path = tmp_path / "race.png"
    path.write_bytes(payload)

    class TrackedStream(io.BytesIO):
        was_closed = False

        def close(self):
            self.was_closed = True
            super().close()

    stream = TrackedStream(payload)
    monkeypatch.setattr(
        service,
        "open_asset_content",
        lambda *_a, **_k: service.AssetContent(stream, "image/png", ".png"),
        raising=False,
    )
    path.unlink()

    safe_client = TestClient(app, raise_server_exceptions=False)
    response = safe_client.get("/api/design-image/assets/31/content")

    assert response.status_code == 200
    assert response.content == payload
    assert stream.was_closed is True


def test_prompt_template_include_inactive_requires_admin(api, monkeypatch):
    client, app, _, service = api
    from app.design_image import library_service

    captured = []
    monkeypatch.setattr(
        library_service,
        "list_prompt_templates",
        lambda _db, *, include_inactive=False: captured.append(include_inactive) or [],
    )

    # 只读用户带 include_inactive 被拒，且不进服务层
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["design_image:read"],
    }
    response = client.get("/api/design-image/prompt-templates?include_inactive=true")
    assert response.status_code == 403
    assert captured == []

    # 普通读取不受影响
    response = client.get("/api/design-image/prompt-templates")
    assert response.status_code == 200
    assert captured == [False]

    # admin 可以读取全量
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["design_image:read", "design_image:admin"],
    }
    response = client.get("/api/design-image/prompt-templates?include_inactive=true")
    assert response.status_code == 200
    assert captured == [False, True]
