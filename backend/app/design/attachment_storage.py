"""Storage boundary for design request attachments; business access stays in routes."""
import logging
from pathlib import Path

from app.core.storage import files
from app.design.models import DesignRequestAttachment

ROOT = Path(__file__).resolve().parents[2] / 'uploads' / 'design'
logger = logging.getLogger('commission')


def save(key, content, content_type, root=ROOT):
    if not files.put_bytes('design-attachments', key, content, content_type):
        path = files.local_path(root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def read(key, root=ROOT):
    return files.read_path('design-attachments', key, root)


def cleanup_unreferenced(db, key, root=ROOT):
    try:
        if db.query(DesignRequestAttachment.id).filter(DesignRequestAttachment.file_path == key).first() is None:
            files.delete('design-attachments', key, root)
    except Exception as exc:
        db.rollback()
        logger.warning('Design attachment cleanup failed type=%s; preserving file', type(exc).__name__)
        print('[design] attachment cleanup failed; preserving file', flush=True)
