"""Account-scoped assistant API with current employee and source grants."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.whatsapp import assistant_service as service
from app.whatsapp.assistant_runner import run_background
from app.whatsapp.assistant_schemas import AssistantCreate, AssistantTaskUpdate

router = APIRouter()


def call(db, function, *args, **kwargs):
    try:
        result = function(db, *args, **kwargs)
        db.commit()  # release locks before response/background work
        return ok(result)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(403, str(exc)) from None
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except service.AssistantConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None


@router.get('/options', summary='AI消息助手可用性与处理范围')
def options(account_uid: str = Query(..., max_length=80), db: Session = Depends(get_db),
            user=Depends(require_permission('whatsapp:read'))):
    return call(db, service.options, int(user['sub']), account_uid)


@router.post('/runs', summary='生成私有聊天总结与跟进清单')
def create(body: AssistantCreate, background: BackgroundTasks, db: Session = Depends(get_db),
           user=Depends(require_permission('whatsapp:read'))):
    def admit(db):
        run = service.create_run(db, int(user['sub']), **body.model_dump())
        if run.status == 'pending':
            background.add_task(run_background, run.run_uid)
        return service.serialize(run)
    return call(db, admit)


@router.get('/runs', summary='当前员工本账号最近10次分析')
def recent(account_uid: str = Query(..., max_length=80), db: Session = Depends(get_db),
           user=Depends(require_permission('whatsapp:read'))):
    return call(db, service.list_runs, int(user['sub']), account_uid)


@router.get('/runs/requests/{request_uid}', summary='不确定提交结果只读回查')
def request_status(request_uid: str, account_uid: str = Query(..., max_length=80), db: Session = Depends(get_db),
                   user=Depends(require_permission('whatsapp:read'))):
    return call(db, service.find_request, int(user['sub']), account_uid, request_uid)


@router.get('/runs/{run_uid}', summary='当前授权下查看分析进度与结果')
def detail(run_uid: str, db: Session = Depends(get_db), user=Depends(require_permission('whatsapp:read'))):
    return call(db, service.get_run, int(user['sub']), run_uid)


@router.patch('/runs/{run_uid}/tasks/{task_uid}', summary='更新助手内部跟进清单完成状态')
def task(run_uid: str, task_uid: str, body: AssistantTaskUpdate, db: Session = Depends(get_db),
         user=Depends(require_permission('whatsapp:read'))):
    return call(db, service.update_task, int(user['sub']), run_uid, task_uid, completed=body.completed)
