"""Private JPEG storage shared by upload, OCR and authenticated reads."""

from io import BytesIO
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def validate_jpeg(content):
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != "JPEG" or max(image.size) > 3000 or min(image.size) < 32:
                raise ValueError("Unsupported image format or size")
            image.load()
    except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        logger.warning("Rejected invalid factory inbound JPEG")
        print("[FactoryInbound] Rejected invalid JPEG", flush=True)
        raise HTTPException(422, "请上传扫描生成的有效 JPG 图片") from None


def image_path(relative):
    root = Path(get_settings().FACTORY_INBOUND_STORAGE_ROOT)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root
    if not relative or Path(relative).name != relative or not relative.endswith(".jpg"):
        raise HTTPException(404, "照片不存在")
    target = root / relative
    if target.is_symlink() or target.resolve().parent != root.resolve():
        raise HTTPException(404, "照片不存在")
    return target


def save_image(content):
    path = image_path(f"{uuid4().hex}.jpg")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
    return path.name


def remove_image(relative):
    try:
        image_path(relative).unlink(missing_ok=True)
    except OSError as error:
        logger.warning("Factory inbound image cleanup failed: %s", type(error).__name__)
        print(f"[FactoryInbound] Image cleanup failed: {type(error).__name__}", flush=True)
