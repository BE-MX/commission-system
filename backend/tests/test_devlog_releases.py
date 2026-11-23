"""账本幂等写入；只有 office-and-cloud 算全局发布；CLI 读 stdin JSON。"""
import io
import json
from datetime import datetime

from app.devlog import ledger_cli
from app.devlog.models import DevlogRelease
from app.devlog.release_service import latest_global, list_releases, record_release

REV = "d1f5bbb7f83f0f8d96daf664d2c621bd0be61a3d"


def test_record_is_idempotent_by_release_id(db):
    assert record_release(db, revision=REV, release_id="7dbf", scope="office-and-cloud",
                          released_at=datetime(2026, 11, 23, 14, 2), source="deployer") is True
    assert record_release(db, revision=REV, release_id="7dbf", scope="office-and-cloud",
                          released_at=datetime(2026, 11, 23, 14, 2), source="deployer") is False
    assert db.query(DevlogRelease).count() == 1


def test_latest_global_ignores_partial_scope(db):
    record_release(db, revision=REV, release_id="g", scope="office-and-cloud", released_at=datetime(2026, 11, 23, 14), source="deployer")
    record_release(db, revision="e" * 40, release_id="c", scope="cloud-only", released_at=datetime(2026, 11, 23, 16), source="deployer")
    assert latest_global(db)["revision"] == REV
    assert [r["scope"] for r in list_releases(db)] == ["office-and-cloud", "cloud-only"]


def test_cli_reads_stdin_and_uses_beijing_now(db, monkeypatch, capsys):
    monkeypatch.setattr(ledger_cli, "SessionLocal", lambda: db)
    monkeypatch.setattr(ledger_cli, "beijing_now", lambda: datetime(2026, 11, 23, 14, 2))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"revision": REV, "release_id": "7dbf", "scope": "office-and-cloud"})))
    assert ledger_cli.main() == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"recorded": True}
    assert db.query(DevlogRelease).one().released_at == datetime(2026, 11, 23, 14, 2)
