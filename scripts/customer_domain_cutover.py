"""Guarded CLI for the one-time unified-customer-domain cutover."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp/customer-domain-cutover"
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
    resolve_agent_history_closure,
    snapshot_unrelated_agent_rows,
    verify_agent_history_removed,
    verify_expected_customer_table_state,
    verify_ready,
    verify_unrelated_unchanged,
)


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _resolve_explicit_safe_root(safe_root: str | Path | None) -> Path | None:
    if safe_root is None:
        return None
    raw_root = Path(safe_root)
    if not raw_root.is_absolute():
        raise CutoverGuardError("safe output root must be an explicit absolute path")
    resolved_root = raw_root.resolve()
    repository_root = REPO_ROOT.resolve()
    if resolved_root == repository_root:
        raise CutoverGuardError("safe output root must be a dedicated evidence directory")
    if not resolved_root.is_relative_to(repository_root):
        raise CutoverGuardError("safe output root must remain inside the repository")
    return resolved_root


def resolve_safe_path(
    value: str | Path,
    *,
    safe_root: str | Path | None = None,
) -> Path:
    """Resolve a CLI path under the repository or its explicit safe subdirectory."""
    explicit_root = _resolve_explicit_safe_root(safe_root)
    anchor = explicit_root or REPO_ROOT
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = anchor / candidate
    candidate = candidate.resolve()
    allowed_root = explicit_root or REPO_ROOT.resolve()
    if candidate != allowed_root and not candidate.is_relative_to(allowed_root):
        raise CutoverGuardError(
            f"path must remain under the configured safe roots: {candidate}"
        )
    return candidate


def resolve_safe_output_path(
    value: str | Path,
    *,
    safe_root: str | Path | None = None,
) -> Path:
    """Keep generated evidence inside one explicit, non-source output tree."""
    output_root = _resolve_explicit_safe_root(safe_root) or DEFAULT_OUTPUT_ROOT.resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = output_root / candidate
    candidate = candidate.resolve()
    if candidate != output_root and not candidate.is_relative_to(output_root):
        raise CutoverGuardError(f"path must remain under the configured output root: {candidate}")
    return candidate


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverGuardError(f"cannot read canonical JSON file: {path}") from exc


def _write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


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
    return raw


def apply_reset(
    *,
    db,
    stopped_writer_manifest: Mapping[str, Any],
    expected_inventory_sha256: str,
    approved_marker_path: Path,
    subprocess_runner: Callable[..., Any] | None = None,
) -> CutoverInventory:
    """Re-run both guards, then invoke only the repository's fixed Alembic command."""
    inventory = build_inventory(db)
    verify_ready(inventory, stopped_writer_manifest, expected_inventory_sha256)
    marker = _read_json(approved_marker_path)
    if not isinstance(marker, dict) or marker.get("approved") is not True:
        raise CutoverGuardError("approved marker must contain approved=true")
    marker_hash = marker.get("inventory_sha256")
    if marker_hash != expected_inventory_sha256 or marker_hash != inventory.inventory_sha256:
        raise CutoverGuardError("approved marker does not bind the exact inventory SHA-256")

    db.rollback()
    db.close()
    runner = subprocess_runner or subprocess.run
    runner(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
    )
    return inventory


def _command_preflight(args: argparse.Namespace) -> None:
    output = resolve_safe_output_path(args.output, safe_root=args.safe_output_root)
    with SessionLocal() as db:
        report = build_preflight_report(db)
    _write_canonical_json(output, report)
    print(f"Preflight report: {output}")
    print(
        "Next: review inventory_sha256, export suppressions, and collect every stopped writer."
    )


def _candidate_rows(raw: Any) -> tuple[list[dict[str, Any]], bool]:
    confirmed_empty = False
    if isinstance(raw, dict):
        candidates = raw.get("candidates")
        confirmed_empty = raw.get("confirmed_empty") is True
    else:
        candidates = raw
    if not isinstance(candidates, list):
        raise CutoverGuardError("suppression input must be a list or a candidates object")
    parsed: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise CutoverGuardError("each suppression candidate must be an object")
        row = dict(candidate)
        if isinstance(row.get("effective_at"), str):
            try:
                row["effective_at"] = datetime.fromisoformat(row["effective_at"])
            except ValueError as exc:
                raise CutoverGuardError(
                    "suppression effective_at must be an ISO Beijing datetime"
                ) from exc
        parsed.append(row)
    return parsed, confirmed_empty


def _command_export_suppressions(args: argparse.Namespace) -> None:
    input_path = resolve_safe_path(args.input, safe_root=args.safe_output_root)
    output_path = resolve_safe_output_path(args.output, safe_root=args.safe_output_root)
    candidates, input_confirmed_empty = _candidate_rows(_read_json(input_path))
    hmac_key = getpass.getpass("Suppression HMAC key (hidden): ")
    manifest = build_suppression_manifest(
        candidates,
        hmac_key,
        args.key_version,
        confirmed_empty=args.confirmed_empty or input_confirmed_empty,
    )
    _write_canonical_json(output_path, manifest.to_dict())
    print(f"HMAC-only suppression manifest: {output_path}")
    print("Next: review ambiguous/unmapped entries and retain them for replay quarantine.")


def _command_verify_ready(args: argparse.Namespace) -> None:
    report_path = resolve_safe_path(args.inventory_report, safe_root=args.safe_output_root)
    writer_path = resolve_safe_path(
        args.stopped_writer_manifest, safe_root=args.safe_output_root
    )
    report = _load_preflight_report(report_path)
    inventory = CutoverInventory.from_dict(report["inventory"])
    verify_ready(inventory, _read_json(writer_path), args.expected_inventory_sha256)
    print(f"Ready: inventory and stopped writers bind {inventory.inventory_sha256}")
    print("Next: create an approved marker binding this hash, then run apply-reset.")


def _command_apply_reset(args: argparse.Namespace) -> None:
    writer_path = resolve_safe_path(
        args.stopped_writer_manifest, safe_root=args.safe_output_root
    )
    marker_path = resolve_safe_path(args.approved_marker, safe_root=args.safe_output_root)
    writer_manifest = _read_json(writer_path)
    if not isinstance(writer_manifest, dict):
        raise CutoverGuardError("stopped-writer manifest must be an object")
    with SessionLocal() as db:
        inventory = apply_reset(
            db=db,
            stopped_writer_manifest=writer_manifest,
            expected_inventory_sha256=args.expected_inventory_sha256,
            approved_marker_path=marker_path,
        )
    print(f"Alembic reset applied for inventory: {inventory.inventory_sha256}")
    print("Next: run verify-after before any writer is resumed.")


def _command_verify_after(args: argparse.Namespace) -> None:
    report_path = resolve_safe_path(args.preflight_report, safe_root=args.safe_output_root)
    report = _load_preflight_report(report_path)
    closure = AgentHistoryClosure.from_dict(report["agent_history_closure"])
    before = AgentPreservationSnapshot.from_dict(report["unrelated_agent_snapshot"])
    with SessionLocal() as db:
        verify_agent_history_removed(db, closure)
        after = snapshot_unrelated_agent_rows(db, closure)
        verify_unrelated_unchanged(before, after)
        verify_expected_customer_table_state(db)
    print("Verified: unrelated Agent history is unchanged and customer tables match cutover state.")
    print("Next: replay suppressions before restoring any customer contact writer.")


def _add_safe_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--safe-output-root",
        help="Explicit absolute root allowed in addition to the repository root.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="Write a read-only cutover report.")
    preflight.add_argument("--output", required=True)
    _add_safe_root(preflight)
    preflight.set_defaults(handler=_command_preflight)

    export = subparsers.add_parser(
        "export-suppressions", help="Build an HMAC-only suppression manifest."
    )
    export.add_argument("--input", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--key-version", required=True)
    export.add_argument("--confirmed-empty", action="store_true")
    _add_safe_root(export)
    export.set_defaults(handler=_command_export_suppressions)

    ready = subparsers.add_parser("verify-ready", help="Validate inventory and writers.")
    ready.add_argument("--inventory-report", required=True)
    ready.add_argument("--stopped-writer-manifest", required=True)
    ready.add_argument("--expected-inventory-sha256", required=True)
    _add_safe_root(ready)
    ready.set_defaults(handler=_command_verify_ready)

    reset = subparsers.add_parser("apply-reset", help="Run guarded Alembic upgrade head.")
    reset.add_argument("--stopped-writer-manifest", required=True)
    reset.add_argument("--expected-inventory-sha256", required=True)
    reset.add_argument("--approved-marker", required=True)
    _add_safe_root(reset)
    reset.set_defaults(handler=_command_apply_reset)

    verify_after = subparsers.add_parser(
        "verify-after", help="Verify preserved Agent rows and final table state."
    )
    verify_after.add_argument("--preflight-report", required=True)
    _add_safe_root(verify_after)
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
