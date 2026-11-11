"""项目雷达 API；个人数据默认仅本人可见。"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.core.time import beijing_today
from app.project_radar.deep_link import verify_detail_token
from app.project_radar.digest import prepare_due_digests, prepare_digest
from app.project_radar.dingtalk_inbound import handle_inbound
from app.project_radar.ingest import (
    create_job, job_dict, reanalyze_subscription_async, run_job_async, select_candidates,
)
from app.project_radar.models import (
    RadarDigest, RadarGlobalSetting, RadarIngestJob, RadarOutbox, RadarScanRun,
    RadarSubscription, RadarTarget, RadarUserSetting,
)
from app.project_radar.schemas import (
    CandidateSelection, DingTalkInbound, GlobalSettingPayload, IngestRequest,
    SubscriptionPatch, UserSettingPayload,
)
from app.project_radar.service import (
    list_subscriptions, remove_subscription, serialize_subscription, update_subscription,
)
from app.system.models import SysDict

router = APIRouter()


def _uid(user: dict) -> int:
    return int(user["sub"])


def _owned_job(db: Session, user_id: int, job_id: int) -> RadarIngestJob:
    job = db.query(RadarIngestJob).filter_by(id=job_id, user_id=user_id).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="收录任务不存在")
    return job


def _owned_subscription(db: Session, user_id: int, subscription_id: int) -> RadarSubscription:
    row = db.query(RadarSubscription).filter_by(
        id=subscription_id, user_id=user_id, removed_at=None,
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在或不属于你")
    return row


@router.get("/subscriptions")
def subscriptions(
    view: str = "all", keyword: str = "", item_type: str = "", module: str = "", read_state: str = "",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db), user: dict = Depends(require_permission("project_radar:read")),
):
    return ok(list_subscriptions(
        db, _uid(user), view=view, keyword=keyword[:200], item_type=item_type,
        module=module, read_state=read_state, page=page, page_size=page_size,
    ))


@router.post("/ingest")
def ingest(data: IngestRequest, background: BackgroundTasks, db: Session = Depends(get_db),
           user: dict = Depends(require_permission("project_radar:write"))):
    job = create_job(db, _uid(user), data.raw_input, channel="web")
    should_start = job.status in {"queued", "failed"}
    db.commit()
    if should_start:
        background.add_task(run_job_async, job.id)
    return ok(job_dict(job), "已收到，正在读取")


@router.get("/jobs/{job_id}")
def ingest_job(job_id: int, db: Session = Depends(get_db), user: dict = Depends(require_permission("project_radar:read"))):
    return ok(job_dict(_owned_job(db, _uid(user), job_id)))


@router.post("/jobs/{job_id}/select")
def choose_candidates(job_id: int, data: CandidateSelection, db: Session = Depends(get_db),
                      user: dict = Depends(require_permission("project_radar:write"))):
    _owned_job(db, _uid(user), job_id)
    result = select_candidates(db, _uid(user), data.selection, job_id=job_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ok(result, result["message"])


@router.get("/subscriptions/{subscription_id}")
def subscription_detail(subscription_id: int, db: Session = Depends(get_db),
                        user: dict = Depends(require_permission("project_radar:read"))):
    row = _owned_subscription(db, _uid(user), subscription_id)
    return ok(serialize_subscription(db, row))


@router.patch("/subscriptions/{subscription_id}")
def patch_subscription(subscription_id: int, data: SubscriptionPatch, db: Session = Depends(get_db),
                       user: dict = Depends(require_permission("project_radar:write"))):
    try:
        row = update_subscription(db, _uid(user), subscription_id, data.model_dump(exclude_unset=True))
        db.commit()
        return ok(serialize_subscription(db, row), "已保存")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/subscriptions/{subscription_id}")
def delete_subscription(subscription_id: int, db: Session = Depends(get_db),
                        user: dict = Depends(require_permission("project_radar:write"))):
    try:
        row = remove_subscription(db, _uid(user), subscription_id)
        db.commit()
        return ok({"id": row.id}, "已移出雷达，30 天内重新收录可恢复笔记与状态")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/subscriptions/{subscription_id}/reanalyze")
def reanalyze(subscription_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
              user: dict = Depends(require_permission("project_radar:write"))):
    _owned_subscription(db, _uid(user), subscription_id)
    background.add_task(reanalyze_subscription_async, _uid(user), subscription_id)
    return ok({"id": subscription_id, "status": "reading"}, "正在重新分析，已锁定字段保持你的版本")


@router.get("/health")
def health(db: Session = Depends(get_db), user: dict = Depends(require_permission("project_radar:read"))):
    today = beijing_today()
    scan = db.query(RadarScanRun).filter(RadarScanRun.scan_date == today).one_or_none()
    digest = db.query(RadarDigest).filter(RadarDigest.user_id == _uid(user), RadarDigest.digest_date == today).one_or_none()
    limited = db.query(RadarTarget).join(RadarSubscription).filter(
        RadarSubscription.user_id == _uid(user), RadarSubscription.removed_at.is_(None),
        RadarTarget.read_state.in_(["limited", "failed"]),
    ).distinct().count()
    failed_outbox = db.query(RadarOutbox).filter(RadarOutbox.user_id == _uid(user), RadarOutbox.status == "failed").count()
    return ok({
        "scan": None if not scan else {
            "status": scan.status, "total": scan.total_count, "success": scan.success_count,
            "failed": scan.failed_count, "started_at": scan.started_at.isoformat(sep=" ", timespec="minutes"),
        },
        "digest": None if not digest else {"status": digest.status, "item_count": digest.item_count, "content": digest.content},
        "limited_count": limited, "failed_outbox_count": failed_outbox,
    })


@router.get("/settings")
def settings(db: Session = Depends(get_db), user: dict = Depends(require_permission("project_radar:read"))):
    row = db.get(RadarUserSetting, _uid(user)) or RadarUserSetting(user_id=_uid(user))
    global_row = db.get(RadarGlobalSetting, 1) or RadarGlobalSetting(id=1)
    types = db.query(SysDict).filter(SysDict.type.in_(["project_radar_type", "ark_module"]), SysDict.is_active.is_(True)).order_by(SysDict.type, SysDict.sort).all()
    return ok({
        "digest_time": row.digest_time, "send_empty": row.send_empty, "sleepy_reminder": row.sleepy_reminder,
        "scan_time": global_row.scan_time, "normal_push_cooldown_days": global_row.normal_push_cooldown_days,
        "types": [{"code": item.code, "label": item.label} for item in types if item.type == "project_radar_type"],
        "modules": [{"code": item.code, "label": item.label} for item in types if item.type == "ark_module"],
        "github_star_sync": {"enabled": False, "phase": 2}, "agent_scan": {"enabled": False, "phase": 2},
    })


@router.put("/settings")
def save_settings(data: UserSettingPayload, db: Session = Depends(get_db),
                  user: dict = Depends(require_permission("project_radar:write"))):
    row = db.get(RadarUserSetting, _uid(user))
    if row is None:
        row = RadarUserSetting(user_id=_uid(user))
        db.add(row)
    row.digest_time = data.digest_time
    row.send_empty = data.send_empty
    row.sleepy_reminder = data.sleepy_reminder
    db.commit()
    return ok({"digest_time": row.digest_time, "send_empty": row.send_empty, "sleepy_reminder": row.sleepy_reminder}, "设置已保存")


@router.put("/settings/global")
def save_global_settings(data: GlobalSettingPayload, db: Session = Depends(get_db),
                         user: dict = Depends(require_permission("project_radar:admin"))):
    row = db.get(RadarGlobalSetting, 1) or RadarGlobalSetting(id=1)
    db.add(row)
    row.scan_time = data.scan_time
    row.normal_push_cooldown_days = data.normal_push_cooldown_days
    db.commit()
    return ok({"scan_time": row.scan_time, "normal_push_cooldown_days": row.normal_push_cooldown_days}, "全局设置已保存")


@router.post("/digest")
def send_digest_now(db: Session = Depends(get_db), user: dict = Depends(require_permission("project_radar:admin"))):
    digest = prepare_digest(db, _uid(user))
    db.commit()
    return ok(None if not digest else {"id": digest.id, "status": digest.status}, "早报已进入发件箱")


@router.get("/public/{subscription_id}")
def public_detail(subscription_id: int, user_id: int, token: str, db: Session = Depends(get_db)):
    # 机器白名单：仅限短期签名、绑定本人和单订阅的只读详情，不能修改数据。
    settings = get_settings()
    secret = settings.PROJECT_RADAR_DETAIL_SECRET or settings.JWT_SECRET_KEY
    if not verify_detail_token(secret, token, user_id, subscription_id):
        raise HTTPException(status_code=403, detail="详情链接无效或已过期")
    row = db.query(RadarSubscription).filter_by(id=subscription_id, user_id=user_id, removed_at=None).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ok(serialize_subscription(db, row))


@router.post("/inbound/dingtalk")
def inbound_dingtalk(data: DingTalkInbound, background: BackgroundTasks, db: Session = Depends(get_db),
                     x_project_radar_token: str = Header(default="")):
    # 机器对机器白名单：仅北京 project-radar-bot 持服务 token 调用；用户权限在业务层逐条校验。
    expected = get_settings().PROJECT_RADAR_INBOUND_TOKEN
    if not expected or not hmac.compare_digest(x_project_radar_token, expected):
        raise HTTPException(status_code=401, detail="机器接入未授权")
    result = handle_inbound(db, message_id=data.message_id, dingtalk_id=data.dingtalk_id, text=data.text)
    if result.get("job_id") and result["reply"].startswith(("收到", "上一个")):
        background.add_task(run_job_async, result["job_id"])
    if result.get("deliver"):
        from app.project_radar.scheduler import deliver_outbox_async
        background.add_task(deliver_outbox_async)
    return ok(result)
