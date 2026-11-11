"""项目雷达单活调度入口。"""

import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.time import beijing_now, beijing_today
from app.project_radar.analysis import classify_update
from app.project_radar.digest import prepare_due_digests
from app.project_radar.dingtalk_sender import deliver_pending_outbox
from app.project_radar.ingest import retry_ingest_jobs
from app.project_radar.models import RadarGlobalSetting, RadarScanRun
from app.project_radar.scan import scan_all

logger = logging.getLogger("commission.project_radar.scheduler")


def _run_scan(db):
    # The AI facade commits its call logs, so it needs a session outside the scan savepoint.
    with SessionLocal() as ai_db:
        def classify(_scan_db, **kwargs):
            return classify_update(ai_db, **kwargs)

        return scan_all(db, classifier=classify)


def scan_job():
    if not get_settings().PROJECT_RADAR_ENABLED:
        return
    with SessionLocal() as db:
        setting = db.get(RadarGlobalSetting, 1) or RadarGlobalSetting(id=1, scan_time="06:30")
        existing = db.query(RadarScanRun).filter(RadarScanRun.scan_date == beijing_today()).one_or_none()
        if existing or beijing_now().strftime("%H:%M") < setting.scan_time:
            return
        run = _run_scan(db)
        if run.failed_count:
            raise RuntimeError(f"项目雷达扫描失败 {run.failed_count}/{run.total_count} 项")


def digest_job():
    if not get_settings().PROJECT_RADAR_ENABLED:
        return
    with SessionLocal() as db:
        prepare_due_digests(db)
        deliver_pending_outbox(db)


def outbox_job():
    if not get_settings().PROJECT_RADAR_ENABLED:
        return
    with SessionLocal() as db:
        deliver_pending_outbox(db)


def ingest_retry_job():
    if not get_settings().PROJECT_RADAR_ENABLED:
        return
    retry_ingest_jobs()


def deliver_outbox_async():
    with SessionLocal() as db:
        try:
            deliver_pending_outbox(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project radar async outbox failed (%s)", type(exc).__name__)
            print(f"Project radar async outbox failed ({type(exc).__name__})", flush=True)


def scan_async():
    with SessionLocal() as db:
        run = _run_scan(db)
        if run.failed_count:
            raise RuntimeError(f"项目雷达扫描失败 {run.failed_count}/{run.total_count} 项")
