"""Poster JPEGs published like festival screenshots for DingTalk.

Production public URL is BATTLE_REPORT_PUBLIC_BASE_URL (https://leshine.cloud).
That domain is the Beijing backend and cannot Playwright-rebuild office posters,
so images go to the shared festival upload namespace (/uploads/festival/...) which
nginx on both sites proxies and every backend can read from COS.
"""
import hashlib
import hmac
import tempfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image

from app.battle_report.models import BattleReportDelivery
from app.battle_report.poster_renderer import render_posters
from app.core.config import get_settings
from app.core.time import beijing_now_aware, to_beijing_time

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_ROOT = REPO_ROOT / "backend" / "data" / "battle-report-posters"
PUBLIC_DOMAIN = "festival"
PUBLIC_PREFIX = "battle-report-posters"
UPLOADS_ROOT = REPO_ROOT / "uploads" / PUBLIC_DOMAIN
KINDS = ("team", "personal")
CACHE_SUFFIX = "v1.jpg"


def expiry(delivery):
    return int((to_beijing_time(delivery.created_at) + timedelta(days=7)).timestamp())


def signature(delivery_id, kind, expires):
    message = f"battle-poster:v1:{delivery_id}:{kind}:{expires}".encode()
    return hmac.new(get_settings().JWT_SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def cache_path(delivery_id, kind):
    return CACHE_ROOT / f"{int(delivery_id)}-{kind}-{CACHE_SUFFIX}"


def public_key(delivery_id, kind, digest):
    # Immutable content-addressed object; redo re-renders and publishes a new key.
    return f"{PUBLIC_PREFIX}/{int(delivery_id)}-{kind}-v1-{digest}{Path(CACHE_SUFFIX).suffix}"


def image_url(delivery, kind):
    path = cache_path(delivery.id, kind)
    if not path.is_file():
        # Force rebuild before building the public URL.
        cached_image(delivery, kind)
        path = cache_path(delivery.id, kind)
    from app.core.storage.cos import file_digest
    digest = file_digest(path)[1]
    key = public_key(delivery.id, kind, digest)
    return f"{get_settings().BATTLE_REPORT_PUBLIC_BASE_URL.rstrip('/')}/uploads/{PUBLIC_DOMAIN}/{key}"


def compress_poster(data):
    """Full-page PNG → JPEG that DingTalk markdown can render inline."""
    image = Image.open(BytesIO(data)).convert("RGB")
    if image.width > 1080:
        height = round(image.height * 1080 / image.width)
        image = image.resize((1080, height), Image.Resampling.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
    try:
        image.save(path, "JPEG", quality=82, optimize=True)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def store_image(delivery_id, kind, data):
    from app.core.storage import files as cloud_files
    from app.core.storage.cos import file_digest

    jpeg = compress_poster(data)
    local = cache_path(delivery_id, kind)
    _atomic_write(local, jpeg)
    # Local public tree so StaticFiles can serve without COS (dev / single-host).
    public_local = UPLOADS_ROOT / PUBLIC_PREFIX / local.name
    _atomic_write(public_local, jpeg)
    digest = file_digest(local)[1]
    key = public_key(delivery_id, kind, digest)
    if cloud_files.managed(PUBLIC_DOMAIN) or cloud_files.enabled(PUBLIC_DOMAIN):
        cloud_files.publish_local(PUBLIC_DOMAIN, key, local)
    return key


def cached_image(delivery, kind):
    if kind not in KINDS:
        raise HTTPException(404, "海报不存在")
    path = cache_path(delivery.id, kind)
    if not path.is_file():
        data = render_posters(delivery.snapshot, (kind,))[kind]
        store_image(delivery.id, kind, data)
        if not path.is_file():
            raise HTTPException(503, "海报缓存写入失败，请稍后重试")
    return path


def public_image(db, delivery_id, kind, expires, supplied_signature):
    """Legacy capability URL (HMAC + 7-day expiry) for non-DingTalk clients."""
    if kind not in KINDS or expires < int(beijing_now_aware().timestamp()) or not hmac.compare_digest(signature(delivery_id, kind, expires), supplied_signature):
        raise HTTPException(404, "海报链接无效或已过期")
    delivery = db.get(BattleReportDelivery, delivery_id)
    if delivery is None or expires != expiry(delivery):
        raise HTTPException(404, "海报不存在")
    return cached_image(delivery, kind)
