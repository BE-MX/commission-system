"""Private case screenshots, with stable references on every application host."""
import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from app.core.storage import files
from app.core.storage.cos import validate_key

ROOT = Path(__file__).resolve().parents[2] / 'uploads' / 'insight'
PREFIX = '/uploads/insight/'
MAX_BYTES = 5 * 1024 * 1024
FORMATS = {'.jpg': ('JPEG', 'image/jpeg'), '.jpeg': ('JPEG', 'image/jpeg'),
           '.png': ('PNG', 'image/png'), '.webp': ('WEBP', 'image/webp')}


def key(reference):
    if not isinstance(reference, str) or not reference.startswith(PREFIX):
        raise ValueError('Invalid case image reference')
    return validate_key(reference[len(PREFIX):])


def save(stream, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in FORMATS:
        raise ValueError('截图仅支持 JPG、PNG、WebP')
    content = stream.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
        raise ValueError('截图不能为空，且不能超过5MB')
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != FORMATS[suffix][0]:
                raise ValueError('图片格式与扩展名不一致')
            image.verify()
    except (UnidentifiedImageError, OSError):
        raise ValueError('图片已损坏或无法识别') from None
    name = 'case_' + uuid4().hex + suffix
    if not files.put_bytes('insight', name, content, FORMATS[suffix][1]):
        path = files.local_path(ROOT, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return PREFIX + name


def read(reference):
    return files.read_path('insight', key(reference), ROOT)


def image_data(reference):
    path = read(reference)
    content = path.read_bytes()
    if len(content) > MAX_BYTES:
        raise ValueError('截图不能超过5MB')
    mime = FORMATS[Path(key(reference)).suffix.lower()][1]
    return 'data:' + mime + ';base64,' + base64.b64encode(content).decode('ascii')


def response(db, case_id):
    from app.insight.models import InsightCase
    case = db.query(InsightCase).filter(InsightCase.id == case_id,
                                       InsightCase.status != 'archived').first()
    if case is None or not case.image_path:
        raise HTTPException(404, '案例截图不存在')
    reference = case.image_path
    db.rollback()
    path = read(reference)
    if not path.is_file():
        raise HTTPException(404, '案例截图不存在')
    return FileResponse(path, filename=f'case-{case_id}{Path(key(reference)).suffix}',
                        content_disposition_type='inline', headers={'Cache-Control': 'private, no-store',
                                       'X-Content-Type-Options': 'nosniff'})
