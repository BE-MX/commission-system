import json
from pathlib import Path, PurePosixPath

import pytest

from scripts import design_image_orphan_recovery as recovery


BATCH = "20260806T010203123456Z"


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "design-images"
    root.mkdir()

    def validate(relative=None):
        candidate = root if relative is None else root.joinpath(*PurePosixPath(relative).parts)
        resolved = Path(candidate).resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            raise RuntimeError("outside test storage")
        return candidate

    monkeypatch.setattr(recovery.file_service, "validate_storage_boundary", validate)
    return root


def _item(source="generated/example.png", content=b"planned image"):
    return {
        "source": source,
        "quarantine": f".orphan-quarantine/{BATCH}/{source}",
        "size": len(content),
        "sha256": recovery.hashlib.sha256(content).hexdigest(),
    }


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class _Barrier:
    connection_id = 731

    def __init__(self, references=()):
        self.references = set(references)
        self.verify_count = 0

    def verify_lock(self):
        self.verify_count += 1

    def referenced_paths(self):
        return set(self.references)


def test_absent_batch_crash_resume_writes_explicit_recovery_journal(isolated_storage):
    item = _item()
    recovery.create_journal("quarantine", BATCH, [item])
    old_journal, old_rel = recovery.create_journal("purge", BATCH, [item], 411)
    recovery.append_journal(old_journal, {
        "event": "intent", "operation": "unlink", "item": item,
    })
    barrier = _Barrier()

    result = recovery.recover_absent_batch(BATCH, barrier)

    assert result["status"] == "recovered_absent_batch"
    assert barrier.verify_count >= 2
    journal = recovery.file_service.validate_storage_boundary(result["journal"])
    events = _events(journal)
    assert events[0]["action"] == "purge"
    assert events[0]["recovery"]["kind"] == "absent_batch_after_incomplete_purge"
    assert events[0]["barrier_connection_id"] == 731
    assert events[1]["event"] == "recovery_coverage"
    assert events[1]["covered_journals"] == [old_rel]
    assert events[-1]["event"] == "run_returned"
    assert events[-1]["recovery_completed"] is True
    assert old_rel not in {result["journal"]}


def test_run_purge_recovery_does_not_append_to_incomplete_old_journal(isolated_storage):
    item = _item()
    recovery.create_journal("quarantine", BATCH, [item])
    old_journal, _ = recovery.create_journal("purge", BATCH, [item], 411)
    recovery.append_journal(old_journal, {
        "event": "intent", "operation": "unlink", "item": item,
    })
    original = old_journal.read_bytes()

    result = recovery.run_purge(BATCH, {"batches": []}, _Barrier())

    assert result["status"] == "recovered_absent_batch"
    assert old_journal.read_bytes() == original


def test_absent_batch_recovery_is_idempotent(isolated_storage):
    item = _item()
    recovery.create_journal("quarantine", BATCH, [item])
    recovery.create_journal("purge", BATCH, [item], 411)
    barrier = _Barrier()

    first = recovery.recover_absent_batch(BATCH, barrier)
    journals_after_first = sorted((isolated_storage / ".orphan-quarantine" / "audit").glob("*.jsonl"))
    second = recovery.recover_absent_batch(BATCH, barrier)

    assert second == {"status": "already_recovered", "journal": first["journal"]}
    assert sorted((isolated_storage / ".orphan-quarantine" / "audit").glob("*.jsonl")) == journals_after_first
    audit = recovery.reconcile_batch(BATCH, "purge")
    assert audit["manual_hold"] is False
    assert all(not result["manual_hold"] for result in audit["results"])


def test_absent_batch_with_completed_old_purge_does_not_create_recovery(isolated_storage):
    item = _item()
    recovery.create_journal("quarantine", BATCH, [item])
    old_journal, old_rel = recovery.create_journal("purge", BATCH, [item], 411)
    recovery.append_journal(old_journal, {"event": "run_returned", "deleted_count": 1})
    before = sorted((isolated_storage / ".orphan-quarantine" / "audit").glob("*.jsonl"))

    result = recovery.recover_absent_batch(BATCH, _Barrier())

    assert result == {"status": "already_purged", "journal": old_rel}
    assert sorted((isolated_storage / ".orphan-quarantine" / "audit").glob("*.jsonl")) == before


def test_absent_batch_rejects_extra_recovery_after_completed_purge(isolated_storage):
    item = _item()
    recovery.create_journal("quarantine", BATCH, [item])
    old_journal, _ = recovery.create_journal("purge", BATCH, [item], 411)
    recovery.append_journal(old_journal, {"event": "run_returned", "deleted_count": 1})
    recovery.create_journal(
        "purge", BATCH, [item], 731,
        recovery={"kind": recovery.RECOVERY_KIND, "covered_journals": []},
    )

    with pytest.raises(RuntimeError, match="unexpected recovery plan"):
        recovery.recover_absent_batch(BATCH, _Barrier())


def test_absent_batch_recovery_rejects_unauthorized_old_purge_plan(isolated_storage):
    authorized = _item()
    unauthorized = _item("generated/other.png", b"other")
    recovery.create_journal("quarantine", BATCH, [authorized])
    recovery.create_journal("purge", BATCH, [unauthorized], 411)

    with pytest.raises(RuntimeError, match="exceeds quarantine authorization"):
        recovery.recover_absent_batch(BATCH, _Barrier())

    records, _ = recovery.plan_journals(batch=BATCH)
    assert not any(record["plan"].get("recovery") for record in records)


def test_absent_batch_recovery_rejects_uncovered_missing_item(isolated_storage):
    first = _item("generated/first.png", b"first")
    second = _item("generated/second.png", b"second")
    recovery.create_journal("quarantine", BATCH, [first, second])
    recovery.create_journal("purge", BATCH, [first], 411)

    with pytest.raises(RuntimeError, match="uncovered quarantine item"):
        recovery.recover_absent_batch(BATCH, _Barrier())


def test_quarantine_preflight_rejects_conflicting_existing_batch(monkeypatch):
    inventory = {"batches": [BATCH], "journal_without_batch": []}
    monkeypatch.setattr(recovery, "reconcile_batch", lambda *args, **kwargs: {
        "results": [{"action": "quarantine"}], "manual_hold": True,
    })

    with pytest.raises(RuntimeError, match="existing quarantine batch conflicts"):
        recovery.assert_existing_batches_safe(inventory)


class _Dialect:
    def __init__(self, name):
        self.name = name


class _Cursor:
    def __init__(self, fail_unlock=False):
        self.fail_unlock = fail_unlock
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        if command == "UNLOCK TABLES" and self.fail_unlock:
            raise OSError("unlock failed")

    def fetchone(self):
        return (987,)

    def fetchall(self):
        return []

    def close(self):
        pass


class _Connection:
    def __init__(self, fail_unlock=False):
        self.cursor_value = _Cursor(fail_unlock)
        self.invalidated = []
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def invalidate(self, error):
        self.invalidated.append(error)

    def close(self):
        self.closed = True


class _Engine:
    def __init__(self, name, connection=None):
        self.dialect = _Dialect(name)
        self.connection = connection
        self.raw_called = False

    def raw_connection(self):
        self.raw_called = True
        return self.connection


def test_barrier_invalidates_connection_when_unlock_fails():
    connection = _Connection(fail_unlock=True)
    engine = _Engine("mysql", connection)
    barrier = recovery.MysqlAssetReadBarrier(engine, lambda: None)
    barrier.verify_lock = lambda: None

    with pytest.raises(RuntimeError, match="cleanup uncertain"):
        with barrier:
            pass

    assert connection.invalidated
    assert connection.closed


def test_barrier_disposes_physical_connection_when_invalidation_fails():
    class RawConnection:
        closed = False

        def close(self):
            self.closed = True

    connection = _Connection(fail_unlock=True)
    connection.dbapi_connection = RawConnection()
    connection.detached = False
    connection.invalidate = lambda error: (_ for _ in ()).throw(OSError("invalidate failed"))
    connection.detach = lambda: setattr(connection, "detached", True)
    barrier = recovery.MysqlAssetReadBarrier(_Engine("mysql", connection), lambda: None)
    barrier.verify_lock = lambda: None

    with pytest.raises(RuntimeError, match="cleanup uncertain"):
        with barrier:
            pass

    assert connection.detached is True
    assert connection.dbapi_connection.closed is True


def test_barrier_rejects_non_mysql_before_checking_out_connection():
    engine = _Engine("sqlite")

    with pytest.raises(RuntimeError, match="requires a MySQL database"):
        recovery.MysqlAssetReadBarrier(engine, lambda: None).__enter__()

    assert engine.raw_called is False


@pytest.mark.parametrize("source", ["../outside.png", "/absolute.png", "C:/drive.png"])
def test_quarantine_plan_rejects_paths_outside_storage(source):
    item = _item()
    item["source"] = source

    with pytest.raises(RuntimeError, match="invalid|boundary"):
        recovery.validate_quarantine_items(BATCH, [item])


def test_cli_uses_direct_subcommands_and_exact_batch_option():
    args = recovery.build_parser().parse_args([
        "reconcile", "--batch", BATCH, "--reconcile-action", "purge",
    ])

    assert args.action == "reconcile"
    assert args.batch == BATCH
    assert args.reconcile_action == "purge"


def test_destructive_cli_requires_explicit_batch_and_reconcile_scope():
    parser = recovery.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["purge"])
    with pytest.raises(SystemExit):
        parser.parse_args(["reconcile", "--batch", BATCH])
