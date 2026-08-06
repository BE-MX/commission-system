"""Exact per-route authorization contract for Design Image Studio."""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.design_image.router import router


ROUTES = [
    ("get", "/api/design-image/config", {}),
    ("post", "/api/design-image/sessions", {"json": {"title": "x"}}),
    ("get", "/api/design-image/sessions", {}),
    ("get", "/api/design-image/sessions/11", {}),
    (
        "post",
        "/api/design-image/sessions/11/assets",
        {"files": {"file": ("x.png", b"x", "image/png")}},
    ),
    ("delete", "/api/design-image/assets/31", {}),
    (
        "post",
        "/api/design-image/sessions/11/turns",
        {"json": {"request_id": "wrong-perm", "prompt": "x"}},
    ),
    ("get", "/api/design-image/jobs/active", {}),
    ("get", "/api/design-image/jobs/41", {}),
    (
        "post",
        "/api/design-image/jobs/41/retry",
        {"json": {"request_id": "wrong-perm-retry"}},
    ),
    ("get", "/api/design-image/assets/31/content", {}),
    ("get", "/api/design-image/usage", {}),
    ("get", "/api/design-image/prompt-templates", {}),
    ("post", "/api/design-image/prompt-templates/seed", {}),
    (
        "post",
        "/api/design-image/prompt-templates",
        {"json": {"category": "scene", "name": "x", "content": "画一张{x}", "options": [{"key": "x", "label": "x", "choices": ["y"]}]}},
    ),
    (
        "put",
        "/api/design-image/prompt-templates/11",
        {"json": {"category": "scene", "name": "x", "content": "画一张{x}", "options": [{"key": "x", "label": "x", "choices": ["y"]}]}},
    ),
    ("delete", "/api/design-image/prompt-templates/11", {}),
    ("get", "/api/design-image/library-assets?scope=public", {}),
    (
        "post",
        "/api/design-image/library-assets",
        {"files": {"file": ("x.png", b"x", "image/png")}},
    ),
    ("delete", "/api/design-image/library-assets/31", {}),
    ("get", "/api/design-image/library-assets/31/content", {}),
    (
        "post",
        "/api/design-image/library-assets/31/clone",
        {"json": {"session_id": 11}},
    ),
]


@pytest.fixture
def wrong_permission_client():
    app = FastAPI()
    app.include_router(router, prefix="/api/design-image")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7",
        "roles": [],
        "permissions": ["design_image:wrong"],
    }
    return TestClient(app)


def test_router_registration_order_permissions_and_architecture_are_static():
    root = Path(__file__).parents[1]
    router_source = (root / "app/design_image/router.py").read_text(encoding="utf-8")
    registry_source = (root / "app/routers.py").read_text(encoding="utf-8")
    assert 'prefix="/api/design-image"' in registry_source
    assert router_source.index('"/jobs/active"') < router_source.index('"/jobs/{job_id}"')
    for forbidden in ("SessionLocal", "AiProvider", "storage_path ==", "owner_user_id =="):
        assert forbidden not in router_source

    tree = ast.parse(router_source)
    actual_permissions = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [
            item
            for item in node.decorator_list
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and isinstance(item.func.value, ast.Name)
            and item.func.value.id == "router"
        ]
        if not decorators:
            continue
        permission_calls = [
            item
            for item in ast.walk(node)
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == "require_permission"
        ]
        assert len(permission_calls) == 1, node.name
        decorator = decorators[0]
        actual_permissions[(decorator.func.attr, decorator.args[0].value)] = (
            permission_calls[0].args[0].value
        )

    assert actual_permissions == {
        ("get", "/config"): "design_image:read",
        ("post", "/sessions"): "design_image:write",
        ("get", "/sessions"): "design_image:read",
        ("get", "/sessions/{session_id}"): "design_image:read",
        ("post", "/sessions/{session_id}/assets"): "design_image:write",
        ("delete", "/assets/{asset_id}"): "design_image:write",
        ("post", "/sessions/{session_id}/turns"): "design_image:write",
        ("get", "/jobs/active"): "design_image:read",
        ("get", "/jobs/{job_id}"): "design_image:read",
        ("post", "/jobs/{job_id}/retry"): "design_image:write",
        ("get", "/assets/{asset_id}/content"): "design_image:read",
        ("get", "/usage"): "design_image:admin",
        ("get", "/prompt-templates"): "design_image:read",
        ("post", "/prompt-templates/seed"): "design_image:admin",
        ("post", "/prompt-templates"): "design_image:admin",
        ("put", "/prompt-templates/{template_id}"): "design_image:admin",
        ("delete", "/prompt-templates/{template_id}"): "design_image:admin",
        ("get", "/library-assets"): "design_image:read",
        ("post", "/library-assets"): "design_image:write",
        ("delete", "/library-assets/{asset_id}"): "design_image:write",
        ("get", "/library-assets/{asset_id}/content"): "design_image:read",
        ("post", "/library-assets/{asset_id}/clone"): "design_image:write",
    }


@pytest.mark.parametrize(("method", "path", "kwargs"), ROUTES)
def test_every_route_rejects_identity_with_only_wrong_permission(
    wrong_permission_client, method, path, kwargs
):
    response = getattr(wrong_permission_client, method)(path, **kwargs)
    assert response.status_code == 403
