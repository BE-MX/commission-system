"""Same-origin SSO URLs must not depend on a browser or deployment hostname."""
from urllib.parse import parse_qs, urlsplit
import pytest
from app.colorwork.service import build_sso_url
from app.colorwork import service
from types import SimpleNamespace

@pytest.mark.parametrize("view", ["library", "inventory", "master"])
def test_sso_stays_inside_ark(view):
    url = urlsplit(build_sso_url(view, "test-token"))
    assert url.scheme == url.netloc == ""
    assert url.path == "/api/colorwork/workbench/api/auth/ark"
    assert parse_qs(url.query) == {"token": ["test-token"], "view": [view]}


def test_runtime_secrets_are_domain_separated_from_ark_jwt(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(
        COLORWORK_SSO_SECRET="", COLORWORK_SYNC_KEY="", JWT_SECRET_KEY="test-ark-secret",
    ))
    assert service._sso_secret() != "test-ark-secret"
    assert service.sync_secret() != service._sso_secret()
    assert service._sso_secret() == service._sso_secret()
