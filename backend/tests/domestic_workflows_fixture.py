"""Generate browser facts using only the synthetic in-memory test database."""
from datetime import datetime
from tests.conftest import engine as engine_fixture, db as db_fixture
from tests.test_domestic_decision_analytics import dd_seed
from tests.test_domestic_decision_operations import report
from app.domestic_decision.analytics import build_analysis, filter_options


def browser_facts():
    engine = engine_fixture.__wrapped__()
    generator = db_fixture.__wrapped__(engine)
    db = next(generator)
    try:
        seed = dd_seed.__wrapped__(db)
        seed.users[0].real_name = "发型师甲"
        seed.users[1].real_name = "发型师乙"
        make_report = report.__wrapped__(db, seed)
        item = seed.item(seed.order(), qty=10)
        make_report(item, datetime(2026, 10, 1), qty=2, process="做发型")
        other = make_report(item, datetime(2026, 10, 2), qty=3, process="做发型")
        other.reported_by_user_id = seed.users[1].id
        db.flush()
        query = seed.request(start_date="2026-10-01", end_date="2026-10-12")
        analysis = build_analysis(db, seed.actor, query)
        analysis["meta"]["run_id"] = "browser-synthetic-run"
        return {"analysis": analysis, "options": filter_options(db, seed.actor)}
    finally:
        generator.close()
        engine.dispose()
