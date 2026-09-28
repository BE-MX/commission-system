"""One-off battle-poster push. Paste onto production and run from backend/.

Forces the requested slot independently of the 13:00/17:01 schedule.
  .venv\\Scripts\\python.exe scripts\\trigger_battle_posters_once.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.battle_report import poster_delivery
from app.battle_report.models import BattleReport
from app.battle_report.poster_service import push_ready
from app.core.database import SessionLocal
from app.core.time import beijing_now, to_beijing_naive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", default="17:01", help="slot label to deliver, e.g. 17:01 or 13:00")
    parser.add_argument("--redo", action="store_true", help="reset sent/uncertain to failed so this slot resends")
    args = parser.parse_args()
    slot = args.slot

    if not push_ready():
        print("push_ready=False: set BATTLE_REPORT_WEBHOOK_URL and BATTLE_REPORT_PUBLIC_BASE_URL in backend/.env")
        return 1

    poster_delivery.due_slot = lambda _now: slot

    now = to_beijing_naive(beijing_now())
    hour, minute = map(int, slot.split(":"))
    slot_now = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    with SessionLocal() as db:
        ids = [r.id for r in db.query(BattleReport.id).filter(
            BattleReport.poster_push_enabled.is_(True),
            BattleReport.status == "published",
            BattleReport.visibility == "activity",
            BattleReport.start_date <= now.date(),
            BattleReport.end_date >= now.date(),
        ).all()]
        if not ids:
            print("no eligible published battle report with push_enabled")
            return 1
        print(f"reports={ids} slot={slot} date={now.date()}")
        if args.redo:
            from app.battle_report.models import BattleReportDelivery
            slots = ("17:01", "17:00") if slot == "17:01" else (slot,)
            for row in db.query(BattleReportDelivery).filter(
                BattleReportDelivery.report_id.in_(ids),
                BattleReportDelivery.report_date == now.date(),
                BattleReportDelivery.slot.in_(slots),
            ).all():
                states = {k: {**v, "status": "failed", "attempts": 0} for k, v in row.deliveries.items()}
                row.deliveries = states
            db.commit()
            print("redo: existing slot reset to failed")
        failed = False
        for report_id in ids:
            result = poster_delivery.send_slot(db, report_id, slot_now)
            print(f"report={report_id} -> {result}")
            failed |= result.get("status") in {"blocked", "busy"} or any(
                v.get("status") in {"failed", "uncertain"} for v in result.get("deliveries", {}).values()
            )
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
