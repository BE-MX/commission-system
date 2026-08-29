"""Guarded CLI for the one-time unified-customer-domain cutover."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
EVIDENCE_ROOT = BACKEND_ROOT / "tmp/customer-domain-cutover"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.core.time import beijing_now  # noqa: E402
from app.customer.cutover_service import (  # noqa: E402
    AgentHistoryClosure,
    AgentPreservationSnapshot,
    CutoverGuardError,
    CutoverInventory,
    build_inventory,
    build_suppression_manifest,
    canonical_json_bytes,
    expected_customer_schema_sha256,
    resolve_agent_history_closure,
    snapshot_unrelated_agent_rows,
    verify_agent_history_removed,
    verify_expected_customer_table_state,
    verify_frozen_business_ids_removed,
    verify_ready,
    verify_unrelated_unchanged,
)


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def resolve_read_path(value: str | Path) -> Path:
    """Read evidence from anywhere inside this repository, never from outside it."""
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(REPO_ROOT.resolve()):
        raise CutoverGuardError(f"read path must remain inside repository: {candidate}")
    return candidate


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(path.lstat().st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError):
        return path.is_symlink()


def resolve_evidence_output_path(value: str | Path) -> Path:
    """Resolve output only under the repository's fixed gitignored evidence tree."""
    configured_root = EVIDENCE_ROOT
    if configured_root.exists() and _is_reparse_point(configured_root):
        raise CutoverGuardError("fixed evidence root cannot be a symlink/reparse point")
    output_root = configured_root.resolve()
    allowed_parent = (BACKEND_ROOT / "tmp").resolve()
    if not output_root.is_relative_to(allowed_parent):
        raise CutoverGuardError("fixed evidence root escaped backend/tmp")
    lexical_candidate = Path(value)
    if not lexical_candidate.is_absolute():
        lexical_candidate = output_root / lexical_candidate
    current = lexical_candidate.parent
    while current.is_relative_to(BACKEND_ROOT.resolve()):
        if current.exists() and _is_reparse_point(current):
            raise CutoverGuardError(f"evidence output parent is a symlink/reparse point: {current}")
        if current == BACKEND_ROOT.resolve():
            break
        current = current.parent
    candidate = lexical_candidate.resolve()
    if candidate != output_root and not candidate.is_relative_to(output_root):
        raise CutoverGuardError(f"output must remain under fixed evidence root: {candidate}")
    current = candidate.parent
    while current.is_relative_to(BACKEND_ROOT.resolve()):
        if current.exists() and _is_reparse_point(current):
            raise CutoverGuardError(f"evidence output parent is a symlink/reparse point: {current}")
        if current == BACKEND_ROOT.resolve():
            break
        current = current.parent
    return candidate


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverGuardError(f"cannot read canonical JSON file: {path}") from exc


def _write_canonical_json(path: Path, value: Any) -> None:
    path = resolve_evidence_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = resolve_evidence_output_path(path)
    payload = canonical_json_bytes(value) + b"\n"
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=".cutover-", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary_path, path)
    except FileExistsError as exc:
        raise CutoverGuardError(f"evidence already exists and will not be overwritten: {path}") from exc
    except OSError as exc:
        raise CutoverGuardError(f"cannot write cutover evidence at {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _audit_generated_at() -> str:
    value = beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=timespec)


def _report_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def build_preflight_report(db) -> dict[str, Any]:
    inventory = build_inventory(db)
    closure = resolve_agent_history_closure(db, inventory)
    unrelated = snapshot_unrelated_agent_rows(db, closure)
    core = {
        "schema_version": 1,
        "generated_at": _audit_generated_at(),
        "inventory": inventory.to_dict(),
        "agent_history_closure": closure.to_dict(),
        "unrelated_agent_snapshot": unrelated.to_dict(),
    }
    return {**core, "report_sha256": _report_hash(core)}


def _load_preflight_report(path: Path) -> dict[str, Any]:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise CutoverGuardError("preflight report must be a JSON object")
    _validate_preflight_report(raw)
    return raw


def _validate_preflight_report(raw: Mapping[str, Any]) -> None:
    try:
        reported_hash = raw["report_sha256"]
        core = {key: value for key, value in raw.items() if key != "report_sha256"}
        if reported_hash != _report_hash(core):
            raise CutoverGuardError("preflight report SHA-256 does not match its content")
        CutoverInventory.from_dict(raw["inventory"])
        AgentHistoryClosure.from_dict(raw["agent_history_closure"])
        AgentPreservationSnapshot.from_dict(raw["unrelated_agent_snapshot"])
    except KeyError as exc:
        raise CutoverGuardError(f"preflight report is missing {exc.args[0]}") from exc


def _load_suppression_manifest(path: Path) -> dict[str, Any]:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise CutoverGuardError("suppression manifest must be a JSON object")
    _validate_suppression_manifest(raw)
    return raw


def _validate_suppression_manifest(raw: Mapping[str, Any]) -> None:
    try:
        source_evidence = raw["source_evidence"]
        entries = raw["entries"]
    except KeyError as exc:
        raise CutoverGuardError(f"suppression manifest is missing {exc.args[0]}") from exc
    if not isinstance(source_evidence, list) or not isinstance(entries, list):
        raise CutoverGuardError("suppression source evidence and entries must be lists")
    payload = {
        key: raw[key]
        for key in (
            "schema_version",
            "key_version",
            "inventory_sha256",
            "preflight_report_sha256",
            "source_evidence",
            "entries",
        )
    }
    if raw.get("manifest_sha256") != _report_hash(payload):
        raise CutoverGuardError("suppression manifest SHA-256 does not match its content")
    for evidence in source_evidence:
        if not isinstance(evidence, dict):
            raise CutoverGuardError("suppression source evidence must be objects")
        evidence_payload = {
            key: value for key, value in evidence.items() if key != "evidence_sha256"
        }
        if evidence.get("evidence_sha256") != _report_hash(evidence_payload):
            raise CutoverGuardError("suppression source evidence SHA-256 mismatch")


def validate_execution_receipt(
    receipt: Mapping[str, Any],
    *,
    inventory_sha256: str,
    preflight_report_sha256: str,
    suppression_manifest_sha256: str,
    writer_manifest_sha256: str,
    approved_marker_sha256: str,
    nonce: str,
) -> bool:
    if receipt.get("status") != "succeeded":
        raise CutoverGuardError("cutover execution receipt is not successful")
    bindings = {
        "inventory_sha256": inventory_sha256,
        "preflight_report_sha256": preflight_report_sha256,
        "suppression_manifest_sha256": suppression_manifest_sha256,
        "writer_manifest_sha256": writer_manifest_sha256,
        "approved_marker_sha256": approved_marker_sha256,
        "nonce": nonce,
        "schema_signature_sha256": expected_customer_schema_sha256(),
    }
    for field_name, expected in bindings.items():
        if receipt.get(field_name) != expected:
            raise CutoverGuardError(f"execution receipt does not bind {field_name}")
    _parse_beijing(receipt.get("completed_at"), "execution receipt completed_at")
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _report_hash(payload):
        raise CutoverGuardError("execution receipt SHA-256 does not match its content")
    return True


def verify_after(
    *,
    db,
    preflight_report: Mapping[str, Any],
    suppression_manifest: Mapping[str, Any],
    writer_manifest: Mapping[str, Any],
    approved_marker: Mapping[str, Any],
    execution_receipt: Mapping[str, Any],
) -> bool:
    _validate_preflight_report(preflight_report)
    _validate_suppression_manifest(suppression_manifest)
    inventory = CutoverInventory.from_dict(preflight_report["inventory"])
    report_sha256 = str(preflight_report["report_sha256"])
    suppression_sha256 = str(suppression_manifest["manifest_sha256"])
    writer_sha256 = _report_hash(writer_manifest)
    marker_sha256 = _report_hash(approved_marker)
    if (
        suppression_manifest.get("inventory_sha256") != inventory.inventory_sha256
        or suppression_manifest.get("preflight_report_sha256") != report_sha256
    ):
        raise CutoverGuardError("suppression manifest is not bound to original preflight")
    marker_bindings = {
        "inventory_sha256": inventory.inventory_sha256,
        "preflight_report_sha256": report_sha256,
        "suppression_manifest_sha256": suppression_sha256,
        "writer_manifest_sha256": writer_sha256,
    }
    if approved_marker.get("approved") is not True:
        raise CutoverGuardError("verify-after approved marker is not approved")
    for field_name, expected in marker_bindings.items():
        if approved_marker.get(field_name) != expected:
            raise CutoverGuardError(
                f"verify-after approved marker does not bind {field_name}"
            )
    validate_execution_receipt(
        execution_receipt,
        inventory_sha256=inventory.inventory_sha256,
        preflight_report_sha256=report_sha256,
        suppression_manifest_sha256=suppression_sha256,
        writer_manifest_sha256=writer_sha256,
        approved_marker_sha256=marker_sha256,
        nonce=str(approved_marker.get("nonce")),
    )
    closure = AgentHistoryClosure.from_dict(preflight_report["agent_history_closure"])
    before = AgentPreservationSnapshot.from_dict(
        preflight_report["unrelated_agent_snapshot"]
    )
    verify_agent_history_removed(db, closure)
    verify_frozen_business_ids_removed(db, inventory)
    after = snapshot_unrelated_agent_rows(db, closure)
    verify_unrelated_unchanged(before, after)
    verify_expected_customer_table_state(db)
    return True


def _parse_beijing(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CutoverGuardError(f"{field_name} must be ISO datetime") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise CutoverGuardError(f"{field_name} must be an explicit Beijing datetime")
    return value.astimezone(BEIJING_TIMEZONE)


def apply_reset(
    *,
    db,
    preflight_report: Mapping[str, Any],
    suppression_manifest: Mapping[str, Any],
    stopped_writer_manifest: Mapping[str, Any],
    expected_inventory_sha256: str,
    approved_marker_path: Path,
    subprocess_runner: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> CutoverInventory:
    """Validate the complete evidence chain and invoke the fixed Alembic command."""
    _validate_preflight_report(preflight_report)
    inventory = build_inventory(db)
    _validate_suppression_manifest(suppression_manifest)
    report_sha256 = preflight_report.get("report_sha256")
    if not isinstance(report_sha256, str):
        raise CutoverGuardError("preflight report hash is required")
    if preflight_report.get("inventory", {}).get("inventory_sha256") != inventory.inventory_sha256:
        raise CutoverGuardError("live inventory does not match the preflight report")
    suppression_sha256 = suppression_manifest.get("manifest_sha256")
    if (
        suppression_manifest.get("inventory_sha256") != inventory.inventory_sha256
        or suppression_manifest.get("preflight_report_sha256") != report_sha256
        or not isinstance(suppression_sha256, str)
    ):
        raise CutoverGuardError("suppression manifest has wrong inventory/report binding")
    writer_sha256 = _report_hash(stopped_writer_manifest)
    verify_ready(
        inventory,
        stopped_writer_manifest,
        expected_inventory_sha256,
        report_sha256,
        now=now,
    )
    marker = _read_json(approved_marker_path)
    if not isinstance(marker, dict) or marker.get("approved") is not True:
        raise CutoverGuardError("approved marker must contain approved=true")
    expected_bindings = {
        "inventory_sha256": inventory.inventory_sha256,
        "preflight_report_sha256": report_sha256,
        "suppression_manifest_sha256": suppression_sha256,
        "writer_manifest_sha256": writer_sha256,
    }
    for field_name, expected in expected_bindings.items():
        if marker.get(field_name) != expected:
            raise CutoverGuardError(f"approved marker does not bind {field_name}")
    nonce = marker.get("nonce")
    if not isinstance(nonce, str) or len(nonce.strip()) < 16 or nonce != nonce.strip():
        raise CutoverGuardError("approved marker requires a stable nonce")
    current = now or beijing_now().replace(tzinfo=BEIJING_TIMEZONE)
    expires_at = _parse_beijing(marker.get("expires_at"), "approved marker expires_at")
    if expires_at <= current or expires_at - current > timedelta(minutes=5):
        raise CutoverGuardError("approved marker is expired or exceeds five-minute lifetime")
    marker_sha256 = _report_hash(marker)
    contract = {
        "schema_version": 1,
        "approved": True,
        "nonce": nonce,
        "evidence_root": str(EVIDENCE_ROOT.resolve()),
        "issued_at": current.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
        **expected_bindings,
        "approved_marker_sha256": marker_sha256,
    }
    contract["contract_sha256"] = _report_hash(contract)
    contract_path = resolve_evidence_output_path(f"migration-contract-{nonce}.json")
    try:
        _write_canonical_json(contract_path, contract)
    except CutoverGuardError as exc:
        raise CutoverGuardError(
            f"cannot stage migration contract (exit=not-started); evidence={contract_path}; "
            "keep all writers stopped and repair the evidence directory"
        ) from exc

    db.rollback()
    db.close()
    runner = subprocess_runner or subprocess.run
    try:
        runner(
            [
                sys.executable,
                "-m",
                "alembic",
                "-x",
                f"customer_cutover_contract={contract_path}",
                "upgrade",
                "head",
            ],
            cwd=BACKEND_ROOT,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        exit_code = getattr(exc, "returncode", "not-started")
        raise CutoverGuardError(
            f"Alembic cutover failed (exit={exit_code}); evidence={contract_path}; "
            "keep all writers stopped and inspect the migration receipt"
        ) from exc
    return inventory


def _command_preflight(args: argparse.Namespace) -> None:
    output = resolve_evidence_output_path(args.output)
    with SessionLocal() as db:
        report = build_preflight_report(db)
    _write_canonical_json(output, report)
    print(f"Preflight report: {output}")
    print(
        "Next: review inventory_sha256, export suppressions, and collect every stopped writer."
    )


def _command_export_suppressions(args: argparse.Namespace) -> None:
    input_path = resolve_read_path(args.input)
    report_path = resolve_read_path(args.preflight_report)
    output_path = resolve_evidence_output_path(args.output)
    source_manifest = _read_json(input_path)
    if not isinstance(source_manifest, dict):
        raise CutoverGuardError("authoritative source manifest must be an object")
    report = _load_preflight_report(report_path)
    inventory = CutoverInventory.from_dict(report["inventory"])
    hmac_key = getpass.getpass("Suppression HMAC key (hidden): ")
    with SessionLocal() as db:
        manifest = build_suppression_manifest(
            db, source_manifest, hmac_key, args.key_version,
            inventory_sha256=inventory.inventory_sha256,
            preflight_report_sha256=report["report_sha256"],
            now=beijing_now().replace(tzinfo=BEIJING_TIMEZONE),
        )
    _write_canonical_json(output_path, manifest.to_dict())
    print(f"HMAC-only suppression manifest: {output_path}")
    print("Next: review ambiguous/unmapped entries and retain them for replay quarantine.")


def _command_verify_ready(args: argparse.Namespace) -> None:
    report_path = resolve_read_path(args.inventory_report)
    writer_path = resolve_read_path(args.stopped_writer_manifest)
    report = _load_preflight_report(report_path)
    inventory = CutoverInventory.from_dict(report["inventory"])
    verify_ready(
        inventory, _read_json(writer_path), args.expected_inventory_sha256,
        report["report_sha256"],
    )
    print(f"Ready: inventory and stopped writers bind {inventory.inventory_sha256}")
    print("Next: create an approved marker binding this hash, then run apply-reset.")


def _command_apply_reset(args: argparse.Namespace) -> None:
    report = _load_preflight_report(resolve_read_path(args.preflight_report))
    suppression = _load_suppression_manifest(resolve_read_path(args.suppression_manifest))
    writer_path = resolve_read_path(args.stopped_writer_manifest)
    marker_path = resolve_read_path(args.approved_marker)
    writer_manifest = _read_json(writer_path)
    if not isinstance(writer_manifest, dict):
        raise CutoverGuardError("stopped-writer manifest must be an object")
    with SessionLocal() as db:
        inventory = apply_reset(
            db=db,
            preflight_report=report,
            suppression_manifest=suppression,
            stopped_writer_manifest=writer_manifest,
            expected_inventory_sha256=args.expected_inventory_sha256,
            approved_marker_path=marker_path,
        )
    print(f"Alembic reset applied for inventory: {inventory.inventory_sha256}")
    print("Next: run verify-after before any writer is resumed.")


def _command_verify_after(args: argparse.Namespace) -> None:
    report_path = resolve_read_path(args.preflight_report)
    report = _load_preflight_report(report_path)
    suppression = _load_suppression_manifest(resolve_read_path(args.suppression_manifest))
    writer = _read_json(resolve_read_path(args.stopped_writer_manifest))
    marker = _read_json(resolve_read_path(args.approved_marker))
    receipt = _read_json(resolve_read_path(args.execution_receipt))
    if not all(isinstance(item, dict) for item in (writer, marker, receipt)):
        raise CutoverGuardError("verify-after evidence files must be JSON objects")
    with SessionLocal() as db:
        verify_after(
            db=db,
            preflight_report=report,
            suppression_manifest=suppression,
            writer_manifest=writer,
            approved_marker=marker,
            execution_receipt=receipt,
        )
    print("Verified: approval receipt, retired IDs, Agent history, and schema all match.")
    print("Next: replay suppressions before restoring any customer contact writer.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="Write a read-only cutover report.")
    preflight.add_argument("--output", required=True)
    preflight.set_defaults(handler=_command_preflight)

    export = subparsers.add_parser(
        "export-suppressions", help="Build an HMAC-only suppression manifest."
    )
    export.add_argument("--input", required=True)
    export.add_argument("--preflight-report", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--key-version", required=True)
    export.set_defaults(handler=_command_export_suppressions)

    ready = subparsers.add_parser("verify-ready", help="Validate inventory and writers.")
    ready.add_argument("--inventory-report", required=True)
    ready.add_argument("--stopped-writer-manifest", required=True)
    ready.add_argument("--expected-inventory-sha256", required=True)
    ready.set_defaults(handler=_command_verify_ready)

    reset = subparsers.add_parser("apply-reset", help="Run guarded Alembic upgrade head.")
    reset.add_argument("--preflight-report", required=True)
    reset.add_argument("--suppression-manifest", required=True)
    reset.add_argument("--stopped-writer-manifest", required=True)
    reset.add_argument("--expected-inventory-sha256", required=True)
    reset.add_argument("--approved-marker", required=True)
    reset.set_defaults(handler=_command_apply_reset)

    verify_after = subparsers.add_parser(
        "verify-after", help="Verify preserved Agent rows and final table state."
    )
    verify_after.add_argument("--preflight-report", required=True)
    verify_after.add_argument("--suppression-manifest", required=True)
    verify_after.add_argument("--stopped-writer-manifest", required=True)
    verify_after.add_argument("--approved-marker", required=True)
    verify_after.add_argument("--execution-receipt", required=True)
    verify_after.set_defaults(handler=_command_verify_after)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except CutoverGuardError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
