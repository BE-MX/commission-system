"""Runs in APScheduler's sync worker pool, including browser rendering."""
import logging

from app.battle_report.models import BattleReport
from app.battle_report.poster_delivery import due_slot, send_slot, recover_interrupted
from app.battle_report.poster_service import push_ready
from app.core.database import SessionLocal
from app.core.time import beijing_now

logger = logging.getLogger(__name__)


def send_battle_posters_job():
    now = beijing_now()
    if not due_slot(now):
        return
    failed = False
    with SessionLocal() as db:
        failed = bool(recover_interrupted(db, now))
        if not push_ready():
            if failed:
                raise RuntimeError("历史战报发送结果待核对，请查看投递记录")
            return
        ids = [r.id for r in db.query(BattleReport.id).filter(BattleReport.poster_push_enabled.is_(True),
            BattleReport.status == "published", BattleReport.visibility == "activity",
            BattleReport.start_date <= now.date(), BattleReport.end_date >= now.date()).all()]
        for report_id in ids:
            try:
                result = send_slot(db, report_id, now)
                failed |= result.get("status") == "blocked" or any(v["status"] in ("failed", "uncertain") for v in result.get("deliveries", {}).values())
            except Exception as exc:
                db.rollback()
                failed = True
                logger.warning("Battle poster job failed report=%s type=%s", report_id, type(exc).__name__)
                print(f"Battle poster job failed report={report_id} type={type(exc).__name__}", flush=True)
    if failed:
        raise RuntimeError("部分战报海报发送未完成，请查看战报海报设置中的投递记录")
