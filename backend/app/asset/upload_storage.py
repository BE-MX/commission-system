"""Bounded, host-independent temporary upload files and tag image publication."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException
from app.core.config import get_settings
from app.core.storage.files import reserve_processing_bytes


@contextmanager
def staged_upload(upload):
    maximum = 500 * 1024 * 1024
    declared = getattr(upload, 'size', None)
    if declared is not None and (declared < 0 or declared > maximum):
        raise HTTPException(413, '单文件不能超过500MiB')
    budget = declared if declared is not None else maximum
    root = Path(get_settings().COS_CACHE_ROOT) / 'asset-upload'
    root.mkdir(parents=True, exist_ok=True)
    with reserve_processing_bytes(budget), TemporaryDirectory(dir=root) as directory:
        target = Path(directory) / 'upload'
        size = 0
        with target.open('xb') as stream:
            while content := upload.file.read(1024 * 1024):
                size += len(content)
                if size > maximum:
                    raise HTTPException(413, '单文件不能超过500MiB')
                if size > budget:
                    raise HTTPException(400, '上传文件大小与声明不一致')
                stream.write(content)
        if not size:
            raise HTTPException(400, '不能上传空文件')
        if declared is not None and size != declared:
            raise HTTPException(400, '上传文件大小与声明不一致')
        yield str(target), size
