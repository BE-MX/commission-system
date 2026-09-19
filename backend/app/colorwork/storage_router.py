"""Machine-only loopback gateway; business authorization stays in Colorwork routes."""
import base64
import hmac
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.storage import files
from app.core.storage.cos import CosObjectStore, validate_key
from app.colorwork import storage_service as service


def authorize(request: Request):
    if (not request.client or request.client.host not in {'127.0.0.1', '::1'}
            or not hmac.compare_digest(request.headers.get('x-ark-storage-key', ''), service.secret())):
        raise HTTPException(403, 'Storage service authentication required')
    if not files.managed(service.DOMAIN):
        raise HTTPException(503, 'Cloud storage is not enabled')


# Service credential and loopback validation replace user-token permissions here.
router = APIRouter(prefix='/storage', dependencies=[Depends(authorize)])


def valid_key(key):
    try:
        return validate_key(key)
    except ValueError:
        raise HTTPException(400, 'Invalid object key') from None


@router.get('/object')
def get_object(key: str = Query(...), offset: int = Query(0, ge=0), length: int | None = Query(None, gt=0), db=Depends(get_db)):
    key = valid_key(key)
    store = CosObjectStore(service.DOMAIN)
    physical, info = service.head(db, key, store)
    if info is None:
        raise HTTPException(404, 'Object not found')
    end = min(info['size'], offset + length) if length is not None else info['size']
    if offset >= info['size'] and info['size'] != 0:
        raise HTTPException(416, 'Range not satisfiable')
    extra = {'Range': f'bytes={offset}-{end - 1}'} if offset or length is not None else {}
    result = store._call('get_object', Key=store.key(physical), **extra)
    stream = result['Body'].get_raw_stream()
    def chunks():
        try:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                yield chunk
        finally:
            stream.close()
    encoded = base64.b64encode(json.dumps(info).encode()).decode()
    return StreamingResponse(chunks(), media_type=info['httpMetadata']['contentType'],
                             headers={'Content-Length':str(max(0, end-offset)), 'X-Ark-Object':encoded, 'Cache-Control':'private, no-store'})


@router.get('/metadata')
def get_metadata(key: str = Query(...), db=Depends(get_db)):
    _, info = service.head(db, valid_key(key))
    if info is None:
        raise HTTPException(404, 'Object not found')
    return info  # Internal R2 adapter protocol; not a user-facing API envelope.


@router.put('/object')
async def put_object(request: Request, key: str = Query(...), db=Depends(get_db)):
    valid_key(key)
    if service.DOMAIN not in get_settings().COS_ENABLED_DOMAINS:
        raise HTTPException(503, 'Cloud writes are paused')
    custom = service.decode_metadata(request.headers.get('x-ark-metadata', 'e30='))
    declared = request.headers.get('x-ark-content-length', request.headers.get('content-length', ''))
    if not declared.isdigit() or int(declared) > service.MAX_BYTES:
        raise HTTPException(413, 'A bounded upload of at most 256MiB is required')
    operation_id = request.headers.get('x-ark-upload-id')
    if operation_id and (len(operation_id) != 64 or any(c not in '0123456789abcdef' for c in operation_id)):
        raise HTTPException(400, 'Invalid upload identity')
    size = int(declared)
    cache = Path(get_settings().COS_CACHE_ROOT)
    cache.mkdir(parents=True, exist_ok=True)
    with files.reserve_processing_bytes(size), TemporaryDirectory(prefix='colorwork-upload-', dir=cache) as directory:
        path = Path(directory) / 'object'
        received = 0
        with path.open('wb') as output:
            async for chunk in request.stream():
                received += len(chunk)
                if received > size:
                    raise HTTPException(413, 'Upload exceeds declared size')
                await run_in_threadpool(output.write, chunk)
        if received != size:
            raise HTTPException(400, 'Incomplete upload')
        return await run_in_threadpool(service.publish, db, key, path,
                                       request.headers.get('content-type', 'application/octet-stream'), custom,
                                       request.headers.get('if-none-match') == '*', operation_id=operation_id)


@router.delete('/object')
def delete_object(key: str = Query(...), db=Depends(get_db)):
    if service.DOMAIN not in get_settings().COS_ENABLED_DOMAINS:
        raise HTTPException(503, 'Cloud writes are paused')
    service.delete(db, valid_key(key))
    return Response(status_code=204)
