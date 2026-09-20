"""COS/LighthouseCOS objects, with bounded streaming and redacted errors."""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re
from urllib.parse import quote
from uuid import uuid4

from app.core.config import get_settings

logger = logging.getLogger('commission')
CHUNK_BYTES = 1024 * 1024
_DOMAIN = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
_INLINE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif',
                 'video/mp4', 'video/quicktime', 'video/webm', 'application/pdf'}


class StorageError(RuntimeError):
    """Safe to expose: never contains credentials, signatures or provider bodies."""


class ObjectMissing(StorageError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str
    content_type: str


def validate_key(value: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 768:
        raise ValueError('Invalid object key')
    if '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid object key')
    if any(part in {'', '.', '..'} for part in value.split('/')):
        raise ValueError('Invalid object key')
    return value


def enabled(domain: str) -> bool:
    return domain in get_settings().COS_ENABLED_DOMAINS


def file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK_BYTES), b''):
            count += len(block)
            digest.update(block)
    return count, digest.hexdigest()


class CosObjectStore:
    def __init__(self, domain: str, *, settings=None, client=None):
        if not _DOMAIN.fullmatch(domain):
            raise ValueError('Invalid storage domain')
        self.settings = settings or get_settings()
        self.bucket = self.settings.COS_BUCKET
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*-\d+', self.bucket):
            raise StorageError('COS bucket is not configured')
        self.prefix = validate_key(self.settings.COS_KEY_PREFIX) + '/' + domain
        self.client = client if client is not None else self._client()

    def _client(self):
        if not self.settings.COS_SECRET_ID or not self.settings.COS_SECRET_KEY:
            raise StorageError('COS credentials are not configured')
        from qcloud_cos import CosConfig, CosS3Client
        # SDK debug logging includes derived signing keys and Authorization values.
        # Its own exception handlers also print provider bodies before ours can redact.
        for name in list(logging.Logger.manager.loggerDict):
            if name == 'qcloud_cos' or name.startswith('qcloud_cos.'):
                sdk_logger = logging.getLogger(name)
                sdk_logger.disabled = True
                sdk_logger.propagate = False
        class CreateOnlyClient(CosS3Client):
            def _get_resumable_uploadid(self, bucket, key):
                # Never take ownership of another worker's incomplete upload.
                # SDK is pinned; retries start a fresh multipart upload.
                return None

            # The high-level uploader drops custom headers at multipart completion.
            # Add the COS create-only header to both publication paths explicitly.
            def put_object(self, *args, **kwargs):
                kwargs['Metadata'] = {**kwargs.get('Metadata', {}), 'x-cos-forbid-overwrite': 'true'}
                return super().put_object(*args, **kwargs)

            def complete_multipart_upload(self, *args, **kwargs):
                kwargs['Metadata'] = {**kwargs.get('Metadata', {}), 'x-cos-forbid-overwrite': 'true'}
                try:
                    return super().complete_multipart_upload(*args, **kwargs)
                except Exception:
                    # A failed create-only completion leaves billable parts unless
                    # explicitly aborted. Only this call's upload ID is eligible.
                    if all(k in kwargs for k in ('Bucket', 'Key', 'UploadId')):
                        try:
                            self.abort_multipart_upload(**{k: kwargs[k] for k in ('Bucket', 'Key', 'UploadId')})
                        except Exception as cleanup_error:
                            logger.warning('COS multipart cleanup failed type=%s', type(cleanup_error).__name__)
                            print('[storage] COS multipart cleanup failed; reconcile pending uploads', flush=True)
                    raise

        return CreateOnlyClient(CosConfig(
            Region=self.settings.COS_REGION, SecretId=self.settings.COS_SECRET_ID,
            SecretKey=self.settings.COS_SECRET_KEY,
            Token=self.settings.COS_SECURITY_TOKEN or None, Scheme='https',
            Timeout=self.settings.COS_REQUEST_TIMEOUT_SECONDS,
        ))

    def key(self, relative: str) -> str:
        return self.prefix + '/' + validate_key(relative)

    def _call(self, method: str, **kwargs):
        try:
            return getattr(self.client, method)(Bucket=self.bucket, **kwargs)
        except Exception as exc:
            # SDK exceptions can contain signed request URLs. Never log their text.
            code = exc.get_error_code() if hasattr(exc, 'get_error_code') else ''
            status = exc.get_status_code() if hasattr(exc, 'get_status_code') else None
            if code == 'NoSuchKey' or (method == 'head_object' and str(status) == '404'):
                raise ObjectMissing('Cloud object does not exist') from None
            logger.warning('COS operation failed operation=%s type=%s', method, type(exc).__name__)
            print(f'[storage] COS operation failed operation={method} type={type(exc).__name__}', flush=True)
            raise StorageError('Cloud storage request failed; retry later') from None

    def head(self, relative: str) -> dict:
        return self._call('head_object', Key=self.key(relative))

    def put_file(self, relative: str, path: Path, content_type: str, *, custom_metadata=None) -> StoredObject:
        path = Path(path)
        before = path.stat()
        size, digest = file_digest(path)
        custom_metadata = custom_metadata or {}
        if any(not re.fullmatch(r'[a-z0-9_-]{1,64}', k) or not isinstance(v, str)
               or not v.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in v)
               for k, v in custom_metadata.items()):
            raise ValueError('Invalid object metadata')
        if sum(len(k) + len(v) for k, v in custom_metadata.items()) > 1800:
            raise ValueError('Object metadata exceeds limit')
        if custom_metadata.get('sha256', digest) != digest:
            raise StorageError('Source checksum disagrees with custom metadata')
        headers = {'x-cos-meta-' + k: v for k, v in custom_metadata.items()}
        headers['x-cos-meta-sha256'] = digest
        self._call('upload_file', Key=self.key(relative), LocalFilePath=str(path),
                   PartSize=8, MAXThread=2, EnableMD5=True, StorageClass='DEFAULT',
                   ContentType=content_type, CacheControl='private, no-store',
                   Metadata=headers)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise StorageError('Source changed during upload; object not committed')
        metadata = self.head(relative)
        if int(metadata.get('Content-Length', -1)) != size or metadata.get('x-cos-meta-sha256') != digest:
            raise StorageError('Uploaded object metadata verification failed')
        return StoredObject(relative, size, digest, content_type)

    def download(self, relative: str, destination: Path, *, max_bytes: int,
                 expected_sha256: str | None = None) -> StoredObject:
        if max_bytes <= 0:
            raise ValueError('A positive download bound is required')
        response = self._call('get_object', Key=self.key(relative))
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name('.' + uuid4().hex + '.part')
        size = 0
        digest = hashlib.sha256()
        try:
            with closing(response['Body'].get_raw_stream()) as stream, temp.open('xb') as output:
                for block in iter(lambda: stream.read(CHUNK_BYTES), b''):
                    size += len(block)
                    if size > max_bytes:
                        raise StorageError('Cloud object exceeds download limit')
                    digest.update(block)
                    output.write(block)
            if size != int(response.get('Content-Length', -1)):
                raise StorageError('Incomplete cloud object')
            if expected_sha256 and digest.hexdigest() != expected_sha256:
                raise StorageError('Cloud object checksum mismatch')
            temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)
        return StoredObject(relative, size, digest.hexdigest(), response.get('Content-Type', 'application/octet-stream'))

    def delete(self, relative: str) -> None:
        self._call('delete_object', Key=self.key(relative))

    def download_url(self, relative: str, *, filename: str = '',
                     content_type: str = 'application/octet-stream', download: bool = True) -> str:
        disposition = 'inline' if not download and content_type in _INLINE_TYPES else 'attachment'
        safe_name = filename.replace('\\', '/').rsplit('/', 1)[-1]
        if safe_name:
            disposition += "; filename*=UTF-8''" + quote(safe_name, safe='')
        return self._call('get_presigned_url', Key=self.key(relative), Method='GET',
                          Expired=self.settings.COS_SIGN_TTL_SECONDS,
                          Params={'response-content-type': content_type,
                                  'response-content-disposition': disposition,
                                  'response-cache-control': 'private, no-store'})
