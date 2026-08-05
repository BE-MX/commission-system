"""Audit, quarantine, reconcile, and purge orphan design-image files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.design_image import file_service
from app.design_image.models import DesignImageAsset


QUARANTINE_NAME = ".orphan-quarantine"
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
RECOVERY_KIND = "absent_batch_after_incomplete_purge"


def reject_link(path: Path) -> None:
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & REPARSE:
        raise RuntimeError(f"refuse symlink/reparse point: {path}")


def walk_files(base: Path, *, skip_quarantine=False, directories=None):
    reject_link(base)
    stack = [base]
    while stack:
        current = stack.pop()
        reject_link(current)
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                reject_link(path)
                if entry.is_dir(follow_symlinks=False):
                    if skip_quarantine and path.parent == base and path.name == QUARANTINE_NAME:
                        continue
                    if directories is not None:
                        directories.append(path)
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path
                else:
                    raise RuntimeError(f"refuse special file: {path}")


def _paths_from_rows(rows) -> set[str]:
    result = set()
    for (raw,) in rows:
        rel = PurePosixPath(raw)
        if rel.is_absolute() or ".." in rel.parts:
            raise RuntimeError(f"invalid DB storage_path: {raw}")
        result.add(rel.as_posix())
        result.add(str(rel.with_name(f"{rel.stem}_thumb{rel.suffix}")))
    return result


def referenced_paths() -> set[str]:
    with SessionLocal() as db:
        rows = db.query(DesignImageAsset.storage_path).filter(
            DesignImageAsset.deleted_at.is_(None)
        ).all()
    return _paths_from_rows(rows)


class MysqlAssetReadBarrier:
    """Hold one physical MySQL session until purge auditing is durable."""

    def __init__(self, db_engine=engine, session_factory=SessionLocal):
        self.engine = db_engine
        self.session_factory = session_factory
        self.connection = None
        self.cursor = None
        self.connection_id = None
        self.locked = False

    def __enter__(self):
        if self.engine.dialect.name != "mysql":
            raise RuntimeError("purge write barrier requires a MySQL database")
        self.connection = self.engine.raw_connection()
        try:
            self.cursor = self.connection.cursor()
            self.cursor.execute("SET SESSION lock_wait_timeout = 10")
            self.cursor.execute("LOCK TABLES ark_design_image_assets READ")
            self.locked = True
            self.cursor.execute("SELECT CONNECTION_ID()")
            self.connection_id = int(self.cursor.fetchone()[0])
            self.verify_lock()
            return self
        except BaseException:
            self._cleanup()
            raise

    def verify_lock(self) -> None:
        with self.session_factory() as db:
            verifier_id = int(db.execute(text("SELECT CONNECTION_ID()")).scalar_one())
            if verifier_id == self.connection_id:
                raise RuntimeError("barrier verifier reused the lock-owning connection")
            count = db.execute(text("""
                SELECT COUNT(*)
                FROM performance_schema.metadata_locks AS ml
                JOIN performance_schema.threads AS th
                  ON th.THREAD_ID = ml.OWNER_THREAD_ID
                WHERE th.PROCESSLIST_ID = :connection_id
                  AND ml.OBJECT_SCHEMA = DATABASE()
                  AND ml.OBJECT_NAME = 'ark_design_image_assets'
                  AND ml.OBJECT_TYPE = 'TABLE'
                  AND ml.LOCK_STATUS = 'GRANTED'
                  AND ml.LOCK_TYPE = 'SHARED_READ_ONLY'
            """), {"connection_id": self.connection_id}).scalar_one()
            if count != 1:
                raise RuntimeError("owned MySQL READ barrier is absent/ambiguous; keep services offline")
            db.execute(text("SELECT COUNT(*) FROM ark_design_image_assets")).scalar_one()

    def referenced_paths(self) -> set[str]:
        self.cursor.execute(
            "SELECT storage_path FROM ark_design_image_assets WHERE deleted_at IS NULL"
        )
        return _paths_from_rows(self.cursor.fetchall())

    def _invalidate_or_dispose(self, error: BaseException) -> None:
        try:
            self.connection.invalidate(error)
            return
        except BaseException:
            raw = (getattr(self.connection, "dbapi_connection", None) or
                   getattr(self.connection, "driver_connection", None))
            try:
                if raw is None:
                    raise RuntimeError("physical DBAPI connection is unavailable")
                detach = getattr(self.connection, "detach", None)
                if detach is not None:
                    detach()
                raw.close()
            except BaseException as disposal_error:
                raise RuntimeError(
                    "could not invalidate or dispose the lock-owning physical connection"
                ) from disposal_error

    def _cleanup(self) -> None:
        cleanup_error = None
        try:
            if self.locked:
                self.cursor.execute("UNLOCK TABLES")
                self.locked = False
                self.cursor.execute("SELECT 1")
                self.cursor.fetchone()
        except BaseException as exc:
            cleanup_error = exc
        try:
            if self.cursor is not None:
                self.cursor.close()
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is not None and self.connection is not None:
            self._invalidate_or_dispose(cleanup_error)
        try:
            if self.connection is not None:
                self.connection.close()
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
            self._invalidate_or_dispose(exc)
        if cleanup_error is not None:
            raise RuntimeError(
                "barrier cleanup uncertain; physical connection invalidated; keep services offline"
            ) from cleanup_error

    def __exit__(self, exc_type, exc, traceback):
        self._cleanup()
        return False


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def append_journal(path: Path, event: dict) -> None:
    event = {"recorded_at": datetime.now(timezone.utc).isoformat(), **event}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def create_journal(action: str, batch: str, items: list[dict],
                   barrier_connection_id: int | None = None, *, recovery=None,
                   min_age_hours: int = 24) -> tuple[Path, str]:
    run_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") +
              f"-{os.getpid()}-{uuid4().hex[:8]}")
    relative = (PurePosixPath(QUARANTINE_NAME) / "audit" /
                f"{batch}.{action}.{run_id}.jsonl").as_posix()
    journal = file_service.validate_storage_boundary(relative)
    journal.parent.mkdir(parents=True, exist_ok=True)
    file_service.validate_storage_boundary(relative)
    plan = {
        "event": "plan", "action": action, "batch": batch, "items": items,
        "min_age_hours": min_age_hours,
        "barrier_connection_id": barrier_connection_id,
    }
    if recovery is not None:
        plan["recovery"] = recovery
    with journal.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "recorded_at": datetime.now(timezone.utc).isoformat(), **plan,
        }, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return journal, relative


def valid_batch_name(batch: str) -> bool:
    try:
        return datetime.strptime(batch, "%Y%m%dT%H%M%S%fZ").strftime(
            "%Y%m%dT%H%M%S%fZ"
        ) == batch
    except (TypeError, ValueError):
        return False


def read_journal(path: Path) -> list[dict]:
    reject_link(path)
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                raise RuntimeError(f"invalid journal JSON: {path.name}") from None
            if not isinstance(event, dict):
                raise RuntimeError(f"invalid journal event: {path.name}")
            events.append(event)
    if not events:
        raise RuntimeError(f"empty journal: {path.name}")
    plan = events[0]
    if plan.get("event") != "plan" or plan.get("action") not in {"quarantine", "purge"}:
        raise RuntimeError(f"invalid journal plan: {path.name}")
    if not valid_batch_name(plan.get("batch", "")) or not isinstance(plan.get("items"), list):
        raise RuntimeError(f"invalid journal batch/items: {path.name}")
    return events


def plan_journals(*, batch=None, action=None):
    audit = file_service.validate_storage_boundary(
        (PurePosixPath(QUARANTINE_NAME) / "audit").as_posix()
    )
    if not audit.exists():
        return [], []
    root = file_service.validate_storage_boundary()
    records, errors = [], []
    try:
        paths = list(walk_files(audit))
    except Exception as exc:
        return [], [f"audit tree unreadable: {exc}"]
    for journal in paths:
        if journal.suffix.lower() != ".jsonl":
            errors.append(f"unexpected audit file: {journal.name}")
            continue
        try:
            events = read_journal(journal)
        except Exception as exc:
            errors.append(str(exc))
            continue
        plan = events[0]
        if batch is not None and plan["batch"] != batch:
            continue
        if action is not None and plan["action"] != action:
            continue
        records.append({
            "journal": journal, "journal_rel": journal.relative_to(root).as_posix(),
            "plan": plan, "events": events,
        })
    return records, errors


def validate_quarantine_items(batch: str, items: list[dict]) -> list[dict]:
    sources, targets = set(), set()
    prefix = PurePosixPath(QUARANTINE_NAME) / batch
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("quarantine plan item is invalid; manual hold")
        source, target = item.get("source"), item.get("quarantine")
        size, sha256 = item.get("size"), item.get("sha256")
        if not isinstance(source, str) or not source or "\\" in source or ":" in source:
            raise RuntimeError("quarantine plan source is invalid; manual hold")
        path = PurePosixPath(source)
        if (path.is_absolute() or path.as_posix() != source or not path.parts or
                any(part in {"", ".", ".."} for part in path.parts) or
                path.parts[0] == QUARANTINE_NAME):
            raise RuntimeError(f"quarantine plan source traverses boundary: {source}; manual hold")
        if target != (prefix / path).as_posix():
            raise RuntimeError(f"quarantine target mismatch for {source}; manual hold")
        if source in sources or target in targets:
            raise RuntimeError(f"duplicate quarantine plan path: {source}; manual hold")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RuntimeError(f"invalid quarantine size for {source}; manual hold")
        try:
            if not isinstance(sha256, str) or len(sha256) != 64:
                raise ValueError
            int(sha256, 16)
        except ValueError:
            raise RuntimeError(f"invalid quarantine sha256 for {source}; manual hold") from None
        sources.add(source)
        targets.add(target)
    return items


def validate_purge_plan_subset(items: list[dict], authorized: list[dict]) -> None:
    allowed = {item["quarantine"]: item for item in authorized}
    seen = set()
    for item in items:
        target = item.get("quarantine") if isinstance(item, dict) else None
        expected = allowed.get(target)
        if target in seen or expected is None or any(
            item.get(field) != expected.get(field)
            for field in ("source", "quarantine", "size", "sha256")
        ):
            raise RuntimeError(f"purge plan exceeds quarantine authorization: {target}; manual hold")
        seen.add(target)


def validate_batch_tree(batch, authorized, files, directories) -> None:
    expected_files = {item["quarantine"] for item in authorized}
    prefix = PurePosixPath(QUARANTINE_NAME) / batch
    expected_dirs = set()
    for target in map(PurePosixPath, expected_files):
        for index in range(len(prefix.parts) + 1, len(target.parts)):
            expected_dirs.add(PurePosixPath(*target.parts[:index]).as_posix())
    extra_files = sorted(set(files) - expected_files)
    extra_dirs = sorted(set(directories) - expected_dirs)
    if extra_files or extra_dirs:
        raise RuntimeError(json.dumps({
            "error": "batch tree contains unauthorized entries; manual hold",
            "extra_files": extra_files, "extra_directories": extra_dirs,
        }, ensure_ascii=False))


def authorized_quarantine_plan(batch: str):
    records, errors = plan_journals(batch=batch)
    if errors:
        raise RuntimeError(f"audit journal errors; manual hold: {errors}")
    quarantine = [r for r in records if r["plan"]["action"] == "quarantine"]
    if len(quarantine) != 1:
        raise RuntimeError(f"expected exactly one quarantine plan, found {len(quarantine)}; manual hold")
    authorized = validate_quarantine_items(batch, quarantine[0]["plan"]["items"])
    for record in (r for r in records if r["plan"]["action"] == "purge"):
        validate_purge_plan_subset(record["plan"]["items"], authorized)
    return quarantine[0], authorized


def file_observation(relative: str, expected: dict) -> dict:
    path = file_service.validate_storage_boundary(relative)
    if not os.path.lexists(path):
        return {"path": relative, "exists": False, "matches": None}
    reject_link(path)
    if not path.is_file():
        return {"path": relative, "exists": True, "matches": False, "conflict": "not_regular_file"}
    size, sha256 = path.stat(follow_symlinks=False).st_size, digest(path)
    return {"path": relative, "exists": True, "size": size, "sha256": sha256,
            "matches": size == expected["size"] and sha256 == expected["sha256"]}


def reconcile_items(action: str, items: list[dict]) -> dict:
    states, manual_hold = [], False
    for item in items:
        target = file_observation(item["quarantine"], item)
        if action == "quarantine":
            source = file_observation(item["source"], item)
            if source["exists"] and source["matches"] and not target["exists"]:
                state = "not_moved"
            elif not source["exists"] and target["exists"] and target["matches"]:
                state = "moved"
            else:
                state, manual_hold = "conflict_manual_hold", True
            states.append({"item": item, "state": state, "source_observation": source,
                           "quarantine_observation": target})
        else:
            if not target["exists"]:
                state = "deleted_according_to_plan_intent"
            elif target["matches"]:
                state = "not_deleted"
            else:
                state, manual_hold = "conflict_manual_hold", True
            states.append({"item": item, "state": state, "quarantine_observation": target})
    return {"action": action, "manual_hold": manual_hold, "states": states}


def reconcile_record(record: dict) -> dict:
    result = reconcile_items(record["plan"]["action"], record["plan"]["items"])
    append_journal(record["journal"], {
        "event": "reconcile_observation", "truth_source": "current_filesystem",
        "manual_hold": result["manual_hold"], "states": result["states"],
    })
    return {"journal": record["journal_rel"], **result}


def reconcile_batch(batch: str, action=None) -> dict:
    if not valid_batch_name(batch):
        raise RuntimeError("batch is not an exact generated batch")
    records, errors = plan_journals(batch=batch)
    quarantine = [r for r in records if r["plan"]["action"] == "quarantine"]
    if errors or len(quarantine) != 1:
        return {"batch": batch, "manual_hold": True, "audit_errors": errors or [
            f"expected one quarantine plan, found {len(quarantine)}"
        ], "results": []}
    selected = records if action is None else [r for r in records if r["plan"]["action"] == action]
    results = [reconcile_record(record) for record in selected]
    return {"batch": batch, "manual_hold": any(r["manual_hold"] for r in results),
            "audit_errors": [], "results": results}


def quarantine_inventory() -> dict:
    root = file_service.validate_storage_boundary()
    qroot = file_service.validate_storage_boundary(QUARANTINE_NAME)
    batches, invalid = [], []
    if qroot.exists():
        reject_link(qroot)
        with os.scandir(qroot) as entries:
            for entry in entries:
                path = Path(entry.path)
                reject_link(path)
                if path.name == "audit" and entry.is_dir(follow_symlinks=False):
                    continue
                if entry.is_dir(follow_symlinks=False) and valid_batch_name(path.name):
                    batches.append(path.name)
                else:
                    invalid.append(path.relative_to(root).as_posix())
    plans, errors = plan_journals(action="quarantine")
    planned = {record["plan"]["batch"] for record in plans}
    unjournaled = sorted(set(batches) - planned)
    return {"batches": sorted(batches), "unjournaled_batches": unjournaled,
            "journal_without_batch": sorted(planned - set(batches)),
            "invalid_entries": sorted(invalid), "audit_errors": errors,
            "manual_hold": bool(unjournaled or invalid or errors)}


def assert_existing_batches_safe(inventory: dict) -> None:
    for batch in sorted(set(inventory["batches"] + inventory["journal_without_batch"])):
        prior_purge = reconcile_batch(batch, "purge")
        observed = prior_purge if prior_purge["results"] else reconcile_batch(batch, "quarantine")
        if observed["manual_hold"]:
            raise RuntimeError(f"existing quarantine batch conflicts: {observed}")


def _validate_absent_recovery(batch, authorized, old_records, barrier):
    batch_root = file_service.validate_storage_boundary(
        (PurePosixPath(QUARANTINE_NAME) / batch).as_posix()
    )
    if os.path.lexists(batch_root):
        raise RuntimeError("absent-batch recovery requires the exact batch directory to be absent")
    covered = {}
    for record in old_records:
        validate_purge_plan_subset(record["plan"]["items"], authorized)
        observed = reconcile_items("purge", record["plan"]["items"])
        if observed["manual_hold"] or any(s["state"] != "deleted_according_to_plan_intent" for s in observed["states"]):
            raise RuntimeError(f"old purge plan is not fully absent: {record['journal_rel']}")
        for item in record["plan"]["items"]:
            covered[item["source"]] = item
    for item in authorized:
        source = file_observation(item["source"], item)
        target = file_observation(item["quarantine"], item)
        if item["source"] in covered:
            if source["exists"] or target["exists"]:
                raise RuntimeError(f"covered purge item has reappeared: {item['source']}")
        elif not (source["exists"] and source["matches"] and not target["exists"]):
            raise RuntimeError(f"uncovered quarantine item cannot be explained: {item['source']}")
    barrier.verify_lock()
    references = barrier.referenced_paths()
    conflict = sorted(set(covered) & references)
    if conflict:
        raise RuntimeError(f"DB references covered purge paths: {conflict}")
    return [covered[key] for key in sorted(covered)]


def recover_absent_batch(batch: str, barrier) -> dict:
    """Durably attest an already-absent batch without altering old journals."""
    barrier.verify_lock()
    _quarantine, authorized = authorized_quarantine_plan(batch)
    records, errors = plan_journals(batch=batch, action="purge")
    if errors:
        raise RuntimeError(f"audit journal errors; manual hold: {errors}")
    recovery_records = [r for r in records if r["plan"].get("recovery")]
    old_records = [r for r in records if not r["plan"].get("recovery")]
    if not old_records:
        raise RuntimeError("absent batch has no old authorized purge plan; manual hold")
    if len(recovery_records) > 1:
        raise RuntimeError("multiple recovery plans for one batch; manual hold")
    covered_items = _validate_absent_recovery(batch, authorized, old_records, barrier)
    covered_journals = sorted(r["journal_rel"] for r in old_records)
    completed_old = [
        record for record in old_records
        if any(event.get("event") == "run_returned" for event in record["events"])
    ]
    if completed_old:
        if recovery_records:
            raise RuntimeError("unexpected recovery plan after a completed old purge; manual hold")
        completed = sorted(completed_old, key=lambda record: record["journal_rel"])[-1]
        return {"status": "already_purged", "journal": completed["journal_rel"]}
    if recovery_records:
        record = recovery_records[0]
        metadata = record["plan"].get("recovery", {})
        if (metadata.get("kind") != RECOVERY_KIND or
                metadata.get("covered_journals") != covered_journals or
                record["plan"]["items"] != covered_items):
            raise RuntimeError("existing recovery plan does not match current authorized evidence")
        if any(event.get("event") == "run_returned" and event.get("recovery_completed") is True
               for event in record["events"]):
            return {"status": "already_recovered", "journal": record["journal_rel"]}
        journal, relative = record["journal"], record["journal_rel"]
    else:
        metadata = {"kind": RECOVERY_KIND, "covered_journals": covered_journals}
        journal, relative = create_journal(
            "purge", batch, covered_items, barrier.connection_id, recovery=metadata
        )
    append_journal(journal, {
        "event": "recovery_coverage", "covered_journals": covered_journals,
        "barrier_connection_id": barrier.connection_id,
    })
    barrier.verify_lock()
    append_journal(journal, {
        "event": "run_returned", "recovery_completed": True,
        "covered_journals": covered_journals,
        "barrier_connection_id": barrier.connection_id,
    })
    return {"status": "recovered_absent_batch", "journal": relative}


def run_purge(batch: str, inventory: dict, barrier) -> dict:
    barrier.verify_lock()
    if batch not in inventory["batches"]:
        return recover_absent_batch(batch, barrier)
    _quarantine, authorized = authorized_quarantine_plan(batch)
    previous = reconcile_batch(batch, "purge")
    if previous["manual_hold"]:
        raise RuntimeError(f"previous purge reconciliation requires manual hold: {previous}")
    if not previous["results"]:
        before = reconcile_batch(batch, "quarantine")
        if before["manual_hold"]:
            raise RuntimeError(f"quarantine reconciliation requires manual hold: {before}")
    root = file_service.validate_storage_boundary()
    batch_rel = (PurePosixPath(QUARANTINE_NAME) / batch).as_posix()
    batch_root = file_service.validate_storage_boundary(batch_rel)
    directories = []
    files = [p.relative_to(root).as_posix() for p in walk_files(batch_root, directories=directories)]
    validate_batch_tree(batch, authorized, files, [p.relative_to(root).as_posix() for p in directories])
    prior_deleted = {state["item"]["source"] for result in previous["results"]
                     for state in result["states"]}
    prepared = []
    for item in authorized:
        observation = reconcile_items("quarantine", [item])["states"][0]
        if item["source"] in prior_deleted:
            if (not observation["source_observation"]["exists"] and
                    not observation["quarantine_observation"]["exists"]):
                continue
            raise RuntimeError(
                f"previously purged item reappeared; manual hold: {item}"
            )
        if observation["state"] == "moved":
            prepared.append((file_service.validate_storage_boundary(item["quarantine"]), item))
        elif observation["state"] == "not_moved":
            continue
        else:
            raise RuntimeError(f"authorized item cannot be safely classified; manual hold: {item}")
    journal, relative = create_journal("purge", batch, [r for _, r in prepared], barrier.connection_id)
    deleted = []
    for path, item in prepared:
        barrier.verify_lock()
        path = file_service.validate_storage_boundary(item["quarantine"])
        if not os.path.lexists(path):
            append_journal(journal, {"event": "skipped", "reason": "already_absent", "item": item})
            continue
        reject_link(path)
        if not path.is_file() or path.stat(follow_symlinks=False).st_size != item["size"] or digest(path) != item["sha256"]:
            raise RuntimeError(f"quarantine file changed after plan: {item['quarantine']}")
        append_journal(journal, {"event": "intent", "operation": "unlink", "item": item})
        final_references = barrier.referenced_paths()
        if item["source"] in final_references:
            append_journal(journal, {"event": "blocked", "reason": "now_referenced", "item": item})
            raise RuntimeError(f"DB now references quarantined path: {item['source']}")
        path.unlink()
        append_journal(journal, {"event": "syscall_returned", "operation": "unlink",
                                 "durability_claimed": False, "item": item})
        deleted.append(item)
    barrier.verify_lock()
    for directory in sorted(set(directories), key=lambda p: len(p.parts), reverse=True):
        reject_link(directory)
        directory.rmdir()
    batch_root.rmdir()
    result = reconcile_items("purge", [r for _, r in prepared])
    append_journal(journal, {"event": "reconcile_observation", "truth_source": "current_filesystem", **result})
    barrier.verify_lock()
    append_journal(journal, {"event": "run_returned", "durability_claimed": False,
                             "deleted_count": len(deleted),
                             "barrier_connection_id": barrier.connection_id})
    if result["manual_hold"]:
        raise RuntimeError(f"post-purge reconciliation requires manual hold: {result}")
    return {"status": "purged", "journal": relative, "reconciliation": result}


def scan_or_quarantine(action: str, min_age_hours: int) -> dict:
    root = file_service.validate_storage_boundary()
    cutoff = datetime.now(timezone.utc).timestamp() - timedelta(hours=min_age_hours).total_seconds()
    inventory, refs, candidates = quarantine_inventory(), referenced_paths(), []
    for path in walk_files(root, skip_quarantine=True):
        relative = path.relative_to(root).as_posix()
        info = path.stat(follow_symlinks=False)
        if relative not in refs and info.st_mtime <= cutoff:
            candidates.append((relative, info.st_size, info.st_mtime))
    if action == "scan":
        return {"action": action, "min_age_hours": min_age_hours,
                "referenced_count": len(refs),
                "candidates": [{"path": r, "size": s,
                                "mtime_utc": datetime.fromtimestamp(m, timezone.utc).isoformat()}
                               for r, s, m in candidates], "quarantine_inventory": inventory}
    if os.getenv("DESIGN_IMAGE_ORPHAN_APPLY") != "QUARANTINE" or inventory["manual_hold"]:
        raise RuntimeError("quarantine requires APPLY=QUARANTINE and no inventory manual hold")
    assert_existing_batches_safe(inventory)
    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    prepared = []
    for relative, size, mtime in candidates:
        source = file_service.validate_storage_boundary(relative)
        if relative in referenced_paths() or not source.is_file() or source.stat(follow_symlinks=False).st_mtime > cutoff:
            continue
        target_rel = (PurePosixPath(QUARANTINE_NAME) / batch / relative).as_posix()
        item = {"source": relative, "quarantine": target_rel, "size": size,
                "mtime_utc": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                "sha256": digest(source)}
        prepared.append((source, file_service.validate_storage_boundary(target_rel), item))
    journal, relative = create_journal("quarantine", batch, [i for _, _, i in prepared],
                                        min_age_hours=min_age_hours)
    batch_root = file_service.validate_storage_boundary(
        (PurePosixPath(QUARANTINE_NAME) / batch).as_posix()
    )
    batch_root.mkdir(parents=True, exist_ok=False)
    file_service.validate_storage_boundary(
        (PurePosixPath(QUARANTINE_NAME) / batch).as_posix()
    )
    moved = []
    for source, target, item in prepared:
        if item["source"] in referenced_paths():
            append_journal(journal, {"event": "skipped", "reason": "now_referenced", "item": item})
            continue
        source = file_service.validate_storage_boundary(item["source"])
        if not source.is_file() or source.stat(follow_symlinks=False).st_mtime > cutoff:
            append_journal(journal, {"event": "skipped", "reason": "missing_or_too_new", "item": item})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        file_service.validate_storage_boundary(item["quarantine"])
        if os.path.lexists(target):
            raise RuntimeError(f"quarantine target already exists: {item['quarantine']}")
        if (source.stat(follow_symlinks=False).st_size != item["size"] or
                digest(source) != item["sha256"]):
            raise RuntimeError(f"source changed or target exists: {item['source']}")
        append_journal(journal, {"event": "intent", "operation": "replace", "item": item})
        os.replace(source, target)
        append_journal(journal, {"event": "syscall_returned", "operation": "replace",
                                 "durability_claimed": False, "item": item})
        moved.append(item)
    observed = reconcile_items("quarantine", [i for _, _, i in prepared])
    append_journal(journal, {"event": "reconcile_observation", "truth_source": "current_filesystem", **observed})
    append_journal(journal, {"event": "run_returned", "durability_claimed": False,
                             "moved_count": len(moved)})
    if observed["manual_hold"]:
        raise RuntimeError(f"post-quarantine reconciliation requires manual hold: {observed}")
    return {"action": action, "batch": batch, "journal": relative, "reconciliation": observed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("scan", "quarantine"):
        command = commands.add_parser(name)
        command.add_argument("--min-age-hours", type=int,
                             default=os.getenv("DESIGN_IMAGE_ORPHAN_MIN_AGE_HOURS", "24"))
    for name in ("reconcile", "purge"):
        command = commands.add_parser(name)
        command.add_argument("--batch", required=True)
        if name == "reconcile":
            command.add_argument("--reconcile-action", choices=("quarantine", "purge"),
                                 required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.action in {"scan", "quarantine"}:
        if args.min_age_hours < 24:
            raise RuntimeError("min age hours must be >= 24")
        result = scan_or_quarantine(args.action, args.min_age_hours)
    else:
        if not args.batch or not valid_batch_name(args.batch):
            raise RuntimeError("--batch must be one exact generated batch")
        inventory = quarantine_inventory()
        if inventory["manual_hold"]:
            raise RuntimeError(f"quarantine inventory requires manual hold: {inventory}")
        if args.action == "reconcile":
            result = {"action": "reconcile", "inventory": inventory,
                      "reconciliation": reconcile_batch(args.batch, args.reconcile_action)}
        else:
            if (os.getenv("DESIGN_IMAGE_ORPHAN_APPLY") != "PURGE" or
                    os.getenv("DESIGN_IMAGE_ORPHAN_WRITE_FREEZE") != "OFFLINE_CONFIRMED"):
                raise RuntimeError("purge requires APPLY=PURGE and WRITE_FREEZE=OFFLINE_CONFIRMED")
            with MysqlAssetReadBarrier() as barrier:
                result = run_purge(args.batch, inventory, barrier)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
