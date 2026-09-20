"""Measure this machine's COS path with disposable objects; never print signed URLs."""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import httpx

for _name in ('httpx', 'httpcore', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2'):
    logging.getLogger(_name).disabled = True
    logging.getLogger(_name).propagate = False

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings
from app.core.storage.cos import CosObjectStore, StorageError
from app.core.time import beijing_now


def probe(settings, *, sizes_mib=(1, 12), origin='https://leshine.cloud'):
    settings = settings.model_copy(update={'COS_KEY_PREFIX': 'ark/verification'})
    store = CosObjectStore('probe', settings=settings)
    report = {'measured_at': beijing_now().isoformat(), 'bucket': settings.COS_BUCKET,
              'region': settings.COS_REGION, 'samples': [], 'cleanup_failed': []}
    keys = []
    try:
        with TemporaryDirectory(prefix='ark-storage-probe-') as directory:
            for size in sizes_mib:
                source = Path(directory) / 'sample'
                source.write_bytes(secrets.token_bytes(size * 1024 * 1024))
                key = uuid4().hex + '.bin'
                keys.append(key)
                start = perf_counter()
                uploaded = store.put_file(key, source, 'application/octet-stream')
                elapsed = perf_counter() - start
                row = {'MiB': size, 'upload_seconds': round(elapsed, 3),
                       'upload_MiB_per_second': round(size / elapsed, 3)}
                start = perf_counter()
                store.download(key, Path(directory) / 'download', max_bytes=uploaded.size,
                               expected_sha256=uploaded.sha256)
                row['verified_download_seconds'] = round(perf_counter() - start, 3)
                report['samples'].append(row)
            # Verify create-only semantics of both publication paths before migration.
            original_sha = uploaded.sha256
            source.write_bytes(b'must-not-overwrite')
            try:
                store.put_file(key, source, 'application/octet-stream')
                report['create_only'] = False
            except StorageError:
                store.download(key, Path(directory) / 'unchanged', max_bytes=uploaded.size,
                               expected_sha256=original_sha)
                report['create_only'] = True
            source.write_bytes(secrets.token_bytes(12 * 1024 * 1024))
            try:
                store.put_file(key, source, 'application/octet-stream')
                report['multipart_create_only'] = False
            except StorageError:
                store.download(key, Path(directory) / 'multipart-unchanged', max_bytes=uploaded.size,
                               expected_sha256=original_sha)
                report['multipart_create_only'] = True
            with httpx.Client(timeout=60, trust_env=False, follow_redirects=False) as client:
                signed = store.download_url(key)
                ranged = client.get(signed, headers={'Range': 'bytes=0-15'})
                report['range'] = ranged.status_code == 206 and len(ranged.content) == 16
                endpoint = f'https://{settings.COS_BUCKET}.cos.{settings.COS_REGION}.myqcloud.com/' + store.key(key)
                cors = client.options(endpoint, headers={'Origin': origin, 'Access-Control-Request-Method': 'PUT',
                    'Access-Control-Request-Headers': 'content-type,x-cos-storage-class'})
                report['cors'] = {'status': cors.status_code,
                    'allow_origin': cors.headers.get('access-control-allow-origin'),
                    'allow_methods': cors.headers.get('access-control-allow-methods'),
                    'allow_headers': cors.headers.get('access-control-allow-headers'),
                    'expose_headers': cors.headers.get('access-control-expose-headers')}
                staged_key = uuid4().hex + '.bin'
                keys.append(staged_key)
                headers = {'Content-Type': 'application/octet-stream', 'x-cos-storage-class': 'DEFAULT'}
                url = store._call('get_presigned_url', Key=store.key(staged_key), Method='PUT',
                                  Expired=120, Headers=headers)
                payload = secrets.token_bytes(1024)
                result = client.put(url, headers=headers, content=payload)
                report['signed_put_status'] = result.status_code
                if result.is_success:
                    store.download(staged_key, Path(directory) / 'staged', max_bytes=len(payload),
                                   expected_sha256=hashlib.sha256(payload).hexdigest())
                    report['signed_put_verified'] = True
    finally:
        for key in keys:
            try:
                store.delete(key)
                pending = store._call('list_multipart_uploads', Prefix=store.key(key))
                for upload in pending.get('Upload', []):
                    if upload.get('Key') == store.key(key):
                        store._call('abort_multipart_upload', Key=upload['Key'], UploadId=upload['UploadId'])
            except StorageError:
                report['cleanup_failed'].append(store.key(key))
        # Always retain a redacted partial report, including cleanup failures.
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-file', type=Path, required=True)
    parser.add_argument('--origin', default='https://leshine.cloud')
    parser.add_argument('--apply', action='store_true', required=True)
    args = parser.parse_args()
    report = probe(Settings(_env_file=args.credentials_file), origin=args.origin)
    cors = report.get('cors', {})
    passed = (report.get('create_only') and report.get('multipart_create_only')
              and report.get('range') and report.get('signed_put_verified')
              and not report['cleanup_failed'] and cors.get('status') in (200, 204)
              and cors.get('allow_origin') in (args.origin, '*')
              and 'PUT' in (cors.get('allow_methods') or ''))
    if not passed:
        raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Probe failed ({type(exc).__name__}); credentials and signed URLs withheld', file=sys.stderr)
        raise SystemExit(1) from None
