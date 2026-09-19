"""Cloud boundary for Expo's existing public image namespace."""
from pathlib import Path
from app.core.storage import files
from app.core.storage.cos import CosObjectStore, ObjectMissing, validate_key


def key(path, root):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def reference_key(value):
    """Normalize a DB reference across historical Windows/Linux repository roots."""
    normalized = str(value).replace('\\', '/')
    marker = 'uploads/expo/'
    if normalized.startswith(marker):
        relative = normalized[len(marker):]
    elif '/' + marker in normalized:
        relative = normalized.split('/' + marker, 1)[1]
    else:
        raise ValueError('Invalid Expo reference')
    return validate_key(relative)


def publish(path):
    from app.expo.ai_pipeline import UPLOAD_ROOT
    if files.managed('expo'):
        files.publish_local('expo', key(path, UPLOAD_ROOT), path)


def read(path):
    from app.expo.ai_pipeline import UPLOAD_ROOT
    if files.managed('expo'):
        return files.read_path('expo', reference_key(path), UPLOAD_ROOT)
    return path


def exists(path):
    from app.expo.ai_pipeline import UPLOAD_ROOT
    if not files.managed('expo'):
        return Path(path).is_file()
    try:
        CosObjectStore('expo').head(reference_key(path))
        return True
    except ObjectMissing:
        return False


def remove(path):
    from app.expo.ai_pipeline import UPLOAD_ROOT
    if files.managed('expo'):
        files.delete('expo', reference_key(path), UPLOAD_ROOT)
    target = Path(path).resolve()
    if not files.managed('expo') or target.is_relative_to(UPLOAD_ROOT.resolve()):
        target.unlink(missing_ok=True)


def ensure_public_reference(db, relative):
    """Orphan/deleted customer portraits must not remain publicly readable."""
    from fastapi import HTTPException
    from sqlalchemy import or_, func
    from app.expo.models import ExpoSession, ExpoResult
    path = Path(validate_key(relative))
    if path.parts[0] not in {'photos', 'results', 'beautified'}:
        return
    candidates = ['uploads/expo/' + path.as_posix()]
    if path.name.endswith('_disp.jpg'):
        stem = path.name[:-len('_disp.jpg')]
        candidates = ['uploads/expo/' + path.with_name(stem + ext).as_posix()
                      for ext in ('.png', '.jpg', '.jpeg', '.webp')]
    def matches(column):
        normalized = func.replace(column, '\\', '/')
        return or_(normalized.in_(candidates),
                   *(normalized.endswith('/' + value, autoescape=True) for value in candidates))
    has_session = db.query(ExpoSession.id).filter(or_(matches(ExpoSession.photo_path),
                                                     matches(ExpoSession.beautified_photo_path))).first()
    has_result = db.query(ExpoResult.id).filter(matches(ExpoResult.image_path)).first()
    if not has_session and not has_result:
        raise HTTPException(404, '文件不存在或已删除')
