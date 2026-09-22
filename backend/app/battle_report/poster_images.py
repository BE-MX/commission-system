"""Short-lived capability URLs; JPEG cache is outside every public uploads mount."""
import hashlib
import hmac
import tempfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image

from app.battle_report.models import BattleReportDelivery
from app.battle_report.poster_renderer import render_posters
from app.core.config import get_settings
from app.core.time import beijing_now_aware, to_beijing_time

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_ROOT = REPO_ROOT / "backend" / "data" / "battle-report-posters"
KINDS = ("team", "personal")
CACHE_SUFFIX = "v1.jpg"


def expiry(delivery):
    return int((to_beijing_time(delivery.created_at) + timedelta(days=7)).timestamp())


def signature(delivery_id, kind, expires):
    message = f"battle-poster:v1:{delivery_id}:{kind}:{expires}".encode()
    return hmac.new(get_settings().JWT_SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def image_url(delivery, kind):
    expires = expiry(delivery)
    query = urlencode({"expires": expires, "signature": signature(delivery.id, kind, expires)})
    return f"{get_settings().BATTLE_REPORT_PUBLIC_BASE_URL.rstrip('/')}/api/battle-reports/poster-images/{delivery.id}/{kind}.jpg?{query}"


def compress_poster(data):
    """Full-page PNG → JPEG that DingTalk markdown can render inline.

    Posters are 1080×thousands of pixels; lossless PNG is too heavy for chat
    previews. Keep readable width and match the festival screenshot pipeline.
    """
    image = Image.open(BytesIO(data)).convert("RGB")
    if image.width > 1080:
        height = round(image.height * 1080 / image.width)
        image = image.resize((1080, height), Image.Resampling.LANCZOS)
    # Pillow's JPEG encoder cannot write large progressive images to BytesIO.
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        path = Path(handle.name)
    try:
        image.save(path, "JPEG", quality=82, optimize=True)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def cached_image(delivery, kind):
    if kind not in KINDS:
        raise HTTPException(404, "海报不存在")
    path = CACHE_ROOT / f"{delivery.id}-{kind}-{CACHE_SUFFIX}"
    if not path.is_file():
        data = render_posters(delivery.snapshot, (kind,))[kind]
        store_image(delivery.id, kind, data)
    return path


def store_image(delivery_id, kind, data):
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    path = CACHE_ROOT / f"{int(delivery_id)}-{kind}-{CACHE_SUFFIX}"
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(compress_poster(data))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def public_image(db, delivery_id, kind, expires, supplied_signature):
    if kind not in KINDS or expires < int(beijing_now_aware().timestamp()) or not hmac.compare_digest(signature(delivery_id, kind, expires), supplied_signature):
        raise HTTPException(404, "海报链接无效或已过期")
    delivery = db.get(BattleReportDelivery, delivery_id)
    if delivery is None or expires != expiry(delivery):
        raise HTTPException(404, "海报不存在")
    return cached_image(delivery, kind)
