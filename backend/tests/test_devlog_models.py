"""devlog 表能在共享 SQLite fixture 上建出并往返读写。"""
from datetime import datetime

from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogRelease, DevlogSyncRun


def test_tables_round_trip(db):
    item = DevlogItem(item_key="branch:codex/demo", title="Add demo", item_type="feature", module="invoice",
                      agent="codex", status="pending_merge", status_at=datetime(2026, 11, 23, 9),
                      last_activity_at=datetime(2026, 11, 23, 9), preconditions={}, fingerprint="0" * 64)
    db.add(item)
    db.flush()
    db.add(DevlogEvidence(item_id=item.id, kind="commit", ref="a" * 40, occurred_at=datetime(2026, 11, 23, 9)))
    db.add(DevlogItemEvent(item_id=item.id, from_status=None, to_status="pending_merge",
                           occurred_at=datetime(2026, 11, 23, 9), recorded_at=datetime(2026, 11, 23, 9)))
    db.add(DevlogRelease(revision="b" * 40, release_id="r1", scope="office-and-cloud",
                         released_at=datetime(2026, 11, 23, 14), source="deployer"))
    db.add(DevlogSyncRun(started_at=datetime(2026, 11, 23, 15), finished_at=datetime(2026, 11, 23, 15, 1),
                         sources=[{"name": "git", "ok": True}], item_count=1, failed_keys=[]))
    db.flush()
    assert db.query(DevlogItem).one().stale is False
    assert db.query(DevlogItem).one().superseded is False
    assert db.query(DevlogEvidence).count() == 1



def test_migration_upgrade_and_downgrade_in_isolated_memory():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "alembic/versions/278_devlog_tables.py"
    spec = importlib.util.spec_from_file_location("devlog_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            module.upgrade()
            assert len(inspect(conn).get_table_names()) == 5
            assert inspect(conn).get_foreign_keys("ark_devlog_evidences")[0]["referred_table"] == "ark_devlog_items"
            module.downgrade()
            assert inspect(conn).get_table_names() == []
    engine.dispose()
