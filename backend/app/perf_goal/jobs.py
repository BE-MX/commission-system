"""APScheduler 入口：每日快照与每月 1/10/20 号报告生成投递（含两次补发重试）。

同步函数，在 APScheduler 线程池执行；失败汇总后抛出，沿用 registry 失败告警监听。
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.auth.models import ArkRole, ArkUser
from app.core.database import SessionLocal
from app.core.time import beijing_now, beijing_today
from app.perf_goal import report_ai, snapshots, targets
from app.perf_goal.config_store import load_config
from app.perf_goal.delivery import deliver_report, push_lock
from app.perf_goal.models import PerfReport
from app.perf_goal.teams import all_people, roster

logger = logging.getLogger(__name__)


def perf_snapshot_daily_job() -> None:
    with SessionLocal() as db:
        period = targets.get_active_period(db)
        if period is None:
            logger.info("perf snapshot skipped: no active period")
            return
        counts = snapshots.refresh_year_snapshots(db, period)
        logger.info("perf snapshots refreshed: %s", counts)


def _recipient_map(db: Session, user_ids: set[int]) -> dict[int, dict]:
    if not user_ids:
        return {}
    rows = (db.query(ArkUser)
            .filter(ArkUser.id.in_(user_ids), ArkUser.is_active.is_(True),
                    ArkUser.deleted_at.is_(None)).all())
    return {row.id: {"ark_user_id": row.id, "name": row.real_name,
                     "dingtalk_id": (row.dingtalk_id or "").strip(),
                     "phone": (row.phone or "").strip()} for row in rows}


def _management_user_ids(db: Session) -> set[int]:
    rows = (db.query(ArkUser).join(ArkUser.roles)
            .filter(ArkRole.name.in_(("admin", "supervisor")),
                    ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)).all())
    return {row.id for row in rows}


def _get_or_create_report(db: Session, slot: date, scope: str, user_id: int | None,
                          department_id: int | None, snapshot_id: int | None,
                          ai_preset: str) -> tuple[PerfReport, bool]:
    query = (db.query(PerfReport)
             .filter(PerfReport.slot == slot, PerfReport.scope == scope,
                     PerfReport.user_id.is_(user_id) if user_id is None else PerfReport.user_id == user_id,
                     PerfReport.department_id.is_(department_id) if department_id is None
                     else PerfReport.department_id == department_id))
    report = query.order_by(PerfReport.id).first()
    if report is not None:
        return report, False
    report = PerfReport(slot=slot, scope=scope, user_id=user_id, department_id=department_id,
                        snapshot_id=snapshot_id, ai_preset=ai_preset, status="failed",
                        error="待生成")
    db.add(report)
    db.commit()
    db.refresh(report)
    return report, True


def _generate(db: Session, report: PerfReport, payload: dict, ai_preset: str) -> None:
    if report.status == "generated" and report.content_md:
        return
    try:
        content_md, content_json = report_ai.generate_content(db, payload, ai_preset)
        report.content_md = content_md
        report.content_json = content_json
        report.status = "generated"
        report.error = None
    except Exception as exc:
        logger.warning("perf report generate failed: report=%s type=%s", report.id, type(exc).__name__)
        print(f"[PERF-REPORT] generate failed: report={report.id} type={type(exc).__name__}", flush=True)
        report.status = "failed"
        report.error = f"报告生成失败（{type(exc).__name__}），可在战报推送页重试"
    db.commit()


def run_push(db, period, slot: date) -> dict:
    """冻结快照 → 生成三类报告 → 投递；返回统计，失败数由调用方决定是否告警。"""
    counts = snapshots.refresh_year_snapshots(db, period, as_of=slot)
    config = load_config(db)
    ai_preset = config.get("ai_preset") or "perf_report_analyst"
    roster_data = roster(db, period.id)
    people = all_people(roster_data)
    from app.perf_goal.trend import _listed_user_ids
    listed = _listed_user_ids(db, period.id)

    plan: list[tuple[str, int | None, int | None, str, str]] = []
    # (scope, user_id, department_id, snapshot_scope_id, recipient_user_id)
    for person in people:
        if person["user_id"] in listed:
            plan.append(("person", person["user_id"], None, str(person["user_id"]), person["user_id"]))
    for team in roster_data["teams"]:
        captain_id = team["captain_user_id"]
        if captain_id is None:
            logger.warning("perf report skipped leader report: team=%s captain unbound", team["name"])
            print(f"[PERF-REPORT] leader report skipped: team={team['name']} captain unbound", flush=True)
            continue
        plan.append(("leader", captain_id, team["department_id"], str(team["department_id"]), captain_id))
    for user_id in sorted(_management_user_ids(db)):
        plan.append(("company", user_id, None, "company", user_id))

    recipients = _recipient_map(db, {entry[4] for entry in plan})
    stats_ = {"snapshots": counts, "reports": 0, "generated": 0, "sent": 0,
              "failed": 0, "uncertain": 0, "degraded": 0}
    for scope, user_id, department_id, snapshot_scope_id, recipient_id in plan:
        recipient = recipients.get(recipient_id)
        if recipient is None:
            logger.warning("perf report recipient inactive: user=%s", recipient_id)
            continue
        snapshot = snapshots.get_year_snapshot(db, period.year,
                                               "team" if scope == "leader" else
                                               ("company" if scope == "company" else "person"),
                                               snapshot_scope_id)
        if snapshot is None:
            continue
        report, _created = _get_or_create_report(db, slot, scope, user_id, department_id,
                                                 snapshot.id, ai_preset)
        stats_["reports"] += 1
        payload = dict(snapshot.payload)
        if scope == "leader":
            payload["scope_name"] = f"{payload.get('scope_name', '')}战队·{recipient['name']}"
        elif scope == "person":
            payload["scope_name"] = recipient["name"]
        _generate(db, report, payload, ai_preset)
        if report.status != "generated":
            stats_["failed"] += 1
            continue
        stats_["generated"] += 1
        row = deliver_report(db, report, recipient, payload.get("scope_name", ""))
        if row is None:
            continue
        stats_[row.status if row.status in ("sent", "failed", "uncertain") else "failed"] += 1
        if row.channel == "webhook_at":
            stats_["degraded"] += 1
    return stats_


def perf_report_push_job() -> None:
    slot = beijing_today()
    with SessionLocal() as db:
        period = targets.get_active_period(db)
        if period is None:
            logger.info("perf report push skipped: no active period")
            return
        with push_lock(db) as acquired:
            if not acquired:
                logger.info("perf report push skipped: another run holds the lock")
                return
            db.expire_all()
            stats_ = run_push(db, period, slot)
    logger.info("perf report push finished: %s", stats_)
    print(f"[PERF-REPORT] push finished: {stats_}", flush=True)
    if stats_.get("failed") or stats_.get("uncertain"):
        raise RuntimeError(
            f"绩效报告存在未完成的生成或投递（failed={stats_.get('failed')}, "
            f"uncertain={stats_.get('uncertain')}），请查看战报推送页台账")
