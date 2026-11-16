"""Authenticated loopback-only username scanner; no business database access."""

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from importlib.resources import as_file, files
from itertools import islice
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from maigret import MaigretDatabase, search
from maigret.result import MaigretCheckStatus
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings

LOG = logging.getLogger("ark.maigret")
SCAN_TIMEOUT = 75


class Settings(BaseSettings):
    PRIVATE_RESEARCH_MAIGRET_TOKEN: str = Field(default="", repr=False)
    PRIVATE_RESEARCH_EGRESS_PROXY: str = Field(default="", repr=False)


class ScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def require_config(settings):
    token = settings.PRIVATE_RESEARCH_MAIGRET_TOKEN
    if len(token) < 24 or not token.isascii() or not token.isprintable():
        raise RuntimeError("scanner token missing or invalid")
    try:
        url = urlsplit(settings.PRIVATE_RESEARCH_EGRESS_PROXY)
        if (url.scheme in {"http", "https", "socks5", "socks5h"} and url.hostname and url.port
                and url.username and url.password and url.path in {"", "/"} and not url.query and not url.fragment):
            return
    except ValueError:
        LOG.warning("scanner proxy configuration invalid")
    raise RuntimeError("authenticated Singapore egress proxy is required")


@asynccontextmanager
async def lifespan(app):
    settings = Settings()
    require_config(settings)
    with as_file(files("maigret").joinpath("resources", "data.json")) as catalog:
        db = MaigretDatabase().load_from_path(str(catalog))
    app.state.sites = dict(islice(db.ranked_sites_dict(top=100, id_type="username").items(), 100))
    if not app.state.sites:
        raise RuntimeError("pinned scanner site database is empty")
    app.state.settings = settings
    app.state.scan_slot = asyncio.Lock()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def authorize_scan(request: Request, call_next):
    if request.url.path == "/scan":
        supplied = request.headers.get("authorization", "")
        token = request.app.state.settings.PRIVATE_RESEARCH_MAIGRET_TOKEN
        if not hmac.compare_digest(supplied.encode("utf-8"), f"Bearer {token}".encode("ascii")):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
async def health(request: Request):
    return {"status": "ok", "sites": len(request.app.state.sites)}


@app.post("/scan")
async def scan(payload: ScanInput, request: Request):
    state = request.app.state
    if state.scan_slot.locked():
        raise HTTPException(429, "scanner_busy")
    async with state.scan_slot:
        try:
            results = await asyncio.wait_for(search(
                username=payload.username, site_dict=state.sites, logger=LOG,
                proxy=state.settings.PRIVATE_RESEARCH_EGRESS_PROXY, timeout=8,
                max_connections=20, no_progressbar=True, retries=0, check_domains=False,
                is_parsing_enabled=False, is_enrich_enabled=False,
            ), timeout=SCAN_TIMEOUT)
        except Exception as exc:
            LOG.warning("username scan unavailable: %s", type(exc).__name__)
            raise HTTPException(503, "scanner_unavailable") from None
    hits = []
    unknown = 0
    connection_failures = 0
    checked = 0
    for name, data in results.items():
        status = data.get("status")
        if status and status.status == MaigretCheckStatus.ILLEGAL:
            continue
        checked += 1
        if status is None or status.status == MaigretCheckStatus.UNKNOWN:
            unknown += 1
            error_name = str(getattr(getattr(status, "error", None), "type", "")).lower()
            if error_name.startswith("connecting failure") or error_name in {
                "proxy", "request timeout", "connection lost", "server disconnected", "request failed",
            }:
                connection_failures += 1
        elif status.is_found():
            hits.append({"site": name, "url": status.site_url_user})
    return {"checked": checked, "unknown": unknown, "connection_failures": connection_failures, "hits": hits}
