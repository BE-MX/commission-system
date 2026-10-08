"""Real Uvicorn proxy middleware must not replace the portal's trusted TCP peer."""
import asyncio
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.portal import router
from app.portal.errors import PortalError


@pytest.mark.parametrize('peer,headers,accepted', [
    ('127.0.0.1', [(b'x-real-ip', b'203.0.113.7')], True),
    ('127.0.0.1', [(b'x-real-ip', b'203.0.113.7'), (b'x-forwarded-for', b'203.0.113.7')], False),
    ('203.0.113.7', [(b'x-real-ip', b'127.0.0.1')], False),
])
def test_forwarded_headers_must_be_removed_to_preserve_peer(monkeypatch, peer, headers, accepted):
    monkeypatch.setattr(router, 'get_settings', lambda: SimpleNamespace(PORTAL_TRUSTED_PROXY_IPS=['127.0.0.1']))
    observed = []
    async def endpoint(scope, receive, send):
        try: observed.append(router._require_portal_proxy(Request(scope)))
        except PortalError as error: observed.append(error.status)
    middleware = ProxyHeadersMiddleware(endpoint, trusted_hosts=['127.0.0.1'])
    asyncio.run(middleware({'type':'http', 'client':(peer, 12345), 'headers':headers, 'scheme':'http'}, None, None))
    assert observed == (['203.0.113.7'] if accepted else [403])
