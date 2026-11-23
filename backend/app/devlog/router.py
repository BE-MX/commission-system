"""方舟开发动态 API。

用户端点：devlog:read。
机器端点（红线 3 白名单，开发机采集器专用）：/ingest、/machine/releases，
凭 _require_devlog_machine 校验 token 哈希，不接受用户 JWT。
"""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.devlog import ingest_service, query_service, release_service
from app.devlog.machine_auth import _require_devlog_machine, _require_small_body, MachineBodyRoute
from app.devlog.schemas import IngestIn, ReleaseBackfillIn, ItemType, Agent

router = APIRouter(route_class=MachineBodyRoute)
Database = Annotated[Session, Depends(get_db)]
READ = "devlog:read"


@router.post("/ingest", dependencies=[Depends(_require_devlog_machine), Depends(_require_small_body)])
def ingest(payload: IngestIn, db: Database):
    return ok(ingest_service.ingest(db, payload))


@router.get("/machine/releases", dependencies=[Depends(_require_devlog_machine)])
def machine_releases(db: Database):
    return ok({"items": release_service.list_releases(db)})


@router.post("/machine/releases", dependencies=[Depends(_require_devlog_machine), Depends(_require_small_body)])
def backfill_releases(payload: ReleaseBackfillIn, db: Database):
    return ok({"recorded": release_service.backfill(db, payload.items)})


@router.get("/summary")
def summary(db: Database, start: date, end: date, type: ItemType | None = None,
            module: str | None = Query(default=None, max_length=40), agent: Agent | None = None,
            user=Depends(require_permission(READ))):
    return ok(query_service.summary(db, start=start, end=end, item_type=type, module=module, agent=agent))


@router.get("/items/{item_id}")
def item_detail(item_id: int, db: Database, user=Depends(require_permission(READ))):
    return ok(query_service.item_detail(db, item_id))


@router.get("/pending")
def pending(db: Database, user=Depends(require_permission(READ))):
    return ok({"items": query_service.pending_list(db)})


@router.get("/health")
def health(db: Database, user=Depends(require_permission(READ))):
    return ok(query_service.health(db))
