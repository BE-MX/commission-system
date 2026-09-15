"""Browser station endpoints, with live DB authorization (not delegated JWT claims)."""
import inspect
import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.response import ok
from app.shipping_inspection import file_service, station_service as service

router = APIRouter(prefix='/station')
logger = logging.getLogger('commission')


def login_id(user=Depends(get_current_user)):
    # Every service entry verifies shipping_station:write against current database grants.
    try:
        return int(user['sub'])
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, '无效登录信息') from exc


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qr_raw: str = Field(min_length=1, max_length=512)
    operator_id: int = Field(gt=0)
    request_id: str = Field(min_length=1, max_length=64)


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    edit_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=64)
    remark: str = Field(default='', max_length=500)


async def invoke(db, function, *args, **kwargs):
    try:
        result = function(db, *args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return ok(result)
    except service.StationError as exc:
        db.rollback()
        raise HTTPException(exc.status, {'code': exc.code, 'message': str(exc)}) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, {'code': 'OPERATION_REJECTED', 'message': str(exc)}) from exc
    except Exception as exc:
        db.rollback()
        logger.warning('Shipping station operation failed', exc_info=True)
        print('Shipping station operation failed; refresh to confirm result', flush=True)
        raise HTTPException(500, {'code': 'OPERATION_UNCONFIRMED', 'message': '操作结果未确认，请刷新核对后重试'}) from exc


@router.get('/operators')
async def operators(user=Depends(login_id), db: Session = Depends(get_db)):
    return await invoke(db, service.operators, user)


@router.post('/scan')
async def scan(body: ScanRequest, user=Depends(login_id), db: Session = Depends(get_db)):
    return await invoke(db, service.scan, user, body.operator_id, body.qr_raw, body.request_id)


@router.get('/sessions/{session_id}')
async def refresh(session_id: str, user=Depends(login_id), db: Session = Depends(get_db)):
    return await invoke(db, service.refresh, user, session_id)


def upload_endpoint(media_type):
    async def upload(session_id: str, file: UploadFile = File(...),
                     item_id: str | None = Form(None), edit_version: int = Form(..., ge=0),
                     request_id: str = Form(..., min_length=1, max_length=64),
                     user=Depends(login_id), db: Session = Depends(get_db)):
        return await invoke(db, service.upload, user, session_id, file, item_id, edit_version, request_id, media_type)
    return upload


router.add_api_route('/sessions/{session_id}/photos', upload_endpoint('image'), methods=['POST'])
router.add_api_route('/sessions/{session_id}/videos', upload_endpoint('video'), methods=['POST'])


@router.delete('/sessions/{session_id}/media/{media_id}')
async def delete(session_id: str, media_id: int, edit_version: int = Query(..., ge=0),
                 request_id: str = Query(..., min_length=1, max_length=64),
                 user=Depends(login_id), db: Session = Depends(get_db)):
    return await invoke(db, service.delete_media, user, session_id, media_id, edit_version, request_id)


@router.post('/sessions/{session_id}/submit')
async def submit(session_id: str, body: SubmitRequest, user=Depends(login_id), db: Session = Depends(get_db)):
    return await invoke(db, service.submit, user, session_id, body.edit_version, body.request_id, body.remark)


@router.post('/sessions/{session_id}/end')
async def end(session_id: str, user=Depends(login_id), db: Session = Depends(get_db)):
    return await invoke(db, service.end, user, session_id)


@router.get('/sessions/{session_id}/media/{media_id}')
async def media(session_id: str, media_id: int, user=Depends(login_id), db: Session = Depends(get_db)):
    def path_for(db):
        session = service.session_for(db, user, session_id)
        media = service.media_for(db, session, media_id)
        path = file_service.resolve_path(media.file_path)
        if not path.is_file():
            raise service.StationError('MEDIA_NOT_FOUND', '文件不存在', 404)
        return str(path)
    result = await invoke(db, path_for)
    db.rollback()  # Release row locks before streaming the private object.
    return FileResponse(result['data'], headers={'Cache-Control': 'private, no-store'})
