"""Process boundary: exporter -> input-only worker -> report importer.

Transport/authentication is supplied by the deployment. The candidate function
has no source Session, no expected results and no network client. A pending
source outbox is acknowledged only when a durable candidate receipt is imported.
"""
from types import SimpleNamespace
import hashlib
from copy import deepcopy
from sqlalchemy import select
from app.commerce_shadow.models import (ShadowObservation, ShadowOutbox, ShadowDataset, ShadowRun,
                                       ShadowResult, ShadowDifference)
from app.commerce_shadow.service import canonical, digest
from app.commerce_shadow.worker import (_candidate, _compare, database_identity, target_fingerprint,
                                       IsolationError, UnsupportedCommand)
from app.core.time import beijing_now
from app.commerce_shadow.diagnostics import report as diagnostic


def collect_observations(source, run, dataset):
    """Input dependency closure, including unallocated payment ancestors."""
    checkpoint = dataset.checkpoint
    rows = list(source.scalars(select(ShadowObservation).where(
        ShadowObservation.id > checkpoint["through_observation_id"],
        ShadowObservation.id <= run.through_observation_id).order_by(ShadowObservation.id)))
    by_event = {row.source_event_id: row for row in rows}
    selected = {row.source_event_id for row in rows if row.invoice_id in run.invoice_ids
        or (row.payment_id and row.payment_id in (run.payment_ids or []))
        or (not row.invoice_id and not row.payment_id and row.local_customer_id in (run.local_customer_ids or []))
        or row.source_event_id in checkpoint.get("source_event_ids", [])}
    missing = []
    while True:
        previous = set(selected)
        aggregates = {}
        for event_id in list(selected):
            row = by_event[event_id]
            aggregates[row.aggregate_key] = max(aggregates.get(row.aggregate_key, 0), row.causal_version)
            for dependency in row.dependencies:
                if dependency in by_event:
                    selected.add(dependency)
                elif dependency not in checkpoint["dependencies"]:
                    missing.append(dependency)
        selected |= {row.source_event_id for row in rows if row.aggregate_key in aggregates
            and checkpoint["watermarks"].get(row.aggregate_key, 0) < row.causal_version <= aggregates[row.aggregate_key]}
        selected |= {row.source_event_id for row in rows if row.resolves_source_event_id in selected}
        if selected == previous:
            break
    return [row for row in rows if row.source_event_id in selected], sorted(set(missing))


def responsibility_scope(source, invoice_ids, payment_ids=()):
    """Read the actual shared payment/production/group closure at this snapshot.

Unlike a transfer this does not UPDATE/lock policy and cannot freeze business.
Registered completeness evidence supplements, never replaces, ledger relations.
"""
    from app.receipt.models import Receipt
    from app.invoice.models import InvoiceItem
    from app.production.local_models import ProductionSupply
    from app.stock.models import ProductionOrderItem
    from app.commerce_transition.models import ResponsibilityGroup, ResponsibilityMember
    invoices, payments, groups = set(invoice_ids), set(payment_ids), set()
    while True:
        previous = (set(invoices), set(payments), set(groups))
        if invoices:
            payments |= set(source.scalars(select(Receipt.batch_id).where(Receipt.invoice_id.in_(invoices), Receipt.batch_id.isnot(None))))
            groups |= set(source.scalars(select(ResponsibilityMember.group_id).where(ResponsibilityMember.invoice_id.in_(invoices))))
            production_ids = set(source.scalars(select(ProductionOrderItem.order_id).join(ProductionSupply,
                ProductionSupply.production_item_id == ProductionOrderItem.id).join(InvoiceItem,
                InvoiceItem.id == ProductionSupply.invoice_item_id).where(InvoiceItem.invoice_id.in_(invoices))))
            if production_ids:
                invoices |= set(source.scalars(select(InvoiceItem.invoice_id).join(ProductionSupply,
                    ProductionSupply.invoice_item_id == InvoiceItem.id).join(ProductionOrderItem,
                    ProductionOrderItem.id == ProductionSupply.production_item_id).where(ProductionOrderItem.order_id.in_(production_ids))))
        if payments:
            invoices |= {identity for identity in source.scalars(select(Receipt.invoice_id).where(Receipt.batch_id.in_(payments))) if identity}
        if groups:
            invoices |= set(source.scalars(select(ResponsibilityMember.invoice_id).where(ResponsibilityMember.group_id.in_(groups))))
        if previous == (invoices, payments, groups):
            break
    incomplete = list(source.scalars(select(ResponsibilityGroup.id).where(ResponsibilityGroup.id.in_(groups),
                                                                        ResponsibilityGroup.complete.is_(False)))) if groups else []
    return invoices, payments, incomplete


def export_input_bundle(source, run_id):
    """Production exporter. Reads only, never waits on the candidate process."""
    run = source.get(ShadowRun, run_id)
    if run is None:
        raise ValueError("验证运行不存在")
    dataset = source.get(ShadowDataset, run.dataset_id)
    checkpoint = dataset.checkpoint
    observations, missing = collect_observations(source, run, dataset)
    actual_invoices, actual_payments, incomplete_groups = responsibility_scope(source, run.invoice_ids,
        set(run.payment_ids or []) | {row.payment_id for row in observations if row.payment_id})
    if actual_invoices != set(run.invoice_ids) or {row.invoice_id for row in observations if row.invoice_id} - set(run.invoice_ids):
        missing.append("incomplete_cross_order_closure")
    if incomplete_groups:
        missing.append("shared_responsibility_inventory_incomplete")
    observed_payments = {row.payment_id for row in observations if row.payment_id and (row.action == "payment.register"
        or (row.action == "legacy.receipt.remote" and row.command.get("body", {}).get("payment")
            and row.command.get("body", {}).get("receipt", {}).get("batch_id") == row.payment_id))}
    initial_payments = {int(key.split(":", 1)[1]) for key in checkpoint.get("identity_map", {})
                        if key.startswith("payment:") and key.split(":", 1)[1].isdigit()}
    for payment_id in actual_payments - observed_payments - initial_payments:
        missing.append(f"missing_payment_origin:{payment_id}")
    resolutions = {row.resolves_source_event_id: row for row in observations if row.resolves_source_event_id}
    if not checkpoint["complete"] or not checkpoint["initial_state_verified"]:
        missing.append("checkpoint_not_verified")
    if set(run.invoice_ids) != set(checkpoint["invoice_ids"]):
        missing.append("incomplete_cross_order_closure")
    known = {row.source_event_id for row in observations} | set(checkpoint["dependencies"])
    for observation in observations:
        missing.extend(set(observation.dependencies) - known)
        if observation.outcome == "unknown" and observation.source_event_id not in resolutions:
            missing.append(f"unknown_source_result:{observation.id}")
        resolution = resolutions.get(observation.source_event_id)
        if resolution and (resolution.command != observation.command or resolution.actor_id != observation.actor_id
                or resolution.aggregate_key != observation.aggregate_key or resolution.invoice_id != observation.invoice_id
                or resolution.local_customer_id != observation.local_customer_id or resolution.payment_id != observation.payment_id
                or resolution.contract_revision != observation.contract_revision or resolution.authority_epoch != observation.authority_epoch
                or observation.source_event_id not in resolution.dependencies
                or not (resolution.resolution_evidence or {}).get("terminal_readback_ref")):
            missing.append(f"invalid_resolution:{observation.id}")
    if not observations or observations[-1].id != run.through_observation_id:
        missing.append("observation_watermark_not_covered")
    # Source result/reason/outcome are intentionally excluded. The worker cannot
    # learn that a source rejected and manufacture the same rejection/result.
    commands = [{key: getattr(row, key) for key in ("id", "source_event_id", "aggregate_key", "action",
        "command", "actor_id", "causal_version", "dependencies", "request_hash", "contract_revision", "authority_epoch")}
        for row in observations]
    for command in commands:
        command["command"] = deepcopy(command["command"])
        if command["action"] == "legacy.order.push":
            # Original signed totals remain in source evidence for comparison;
            # the candidate receives the entered lines/fees and calculates its
            # own aggregates. It cannot copy the formal aggregate as its result.
            contract = command["command"].get("body", {}).get("contract", {})
            contract.pop("product_amount", None)
            contract.pop("total_amount", None)
        if command["source_event_id"] in resolutions:
            command["superseded_by"] = resolutions[command["source_event_id"]].source_event_id
    bundle = canonical({"schema_version": 1, "run_id": run.id, "dataset_id": dataset.id,
        "source_fingerprint": hashlib.sha256(database_identity(source.get_bind(), durable=False).encode()).hexdigest(),
        "target_fingerprint": dataset.target_fingerprint, "checkpoint": checkpoint,
        "checkpoint_hash": dataset.checkpoint_hash, "through_observation_id": run.through_observation_id,
        "commands": commands, "missing_dependencies": sorted(set(missing))})
    return {**bundle, "bundle_hash": digest(bundle)}


def execute_input_bundle(target_engine, bundle, *, runtime_capabilities=(), production_urls=()):
    """Isolated process entry: only an explicitly supplied candidate engine.

The deployment must run this with candidate-only credentials/settings and
authenticated transport. It cannot accept arbitrary public API seed/URL input.
"""
    if runtime_capabilities:
        raise IsolationError("验证进程不得持有外发、生产上传或真实扫码能力")
    if bundle.get("schema_version") != 1:
        raise IsolationError("验证输入版本不兼容")
    body = {key: value for key, value in bundle.items() if key != "bundle_hash"}
    if digest(body) != bundle["bundle_hash"] or digest(bundle["checkpoint"]) != bundle["checkpoint_hash"]:
        raise IsolationError("验证输入摘要损坏")
    fingerprint = target_fingerprint(target_engine)
    if fingerprint != bundle["target_fingerprint"] or fingerprint == bundle["source_fingerprint"]:
        raise IsolationError("验证目标数据库身份不匹配或与正式来源相同")
    if target_engine.url.get_backend_name() != "sqlite" and not (target_engine.url.database or "").startswith(("commerce_shadow_", "ark_shadow_", "test_")):
        raise IsolationError("验证数据库名称必须明确隔离")
    from sqlalchemy.engine import make_url
    for url in production_urls:
        production = make_url(url)
        if target_engine.url == production or (production.username and production.username == target_engine.url.username):
            raise IsolationError("验证进程不能使用生产数据库身份")
    dataset = SimpleNamespace(id=bundle["dataset_id"], checkpoint=bundle["checkpoint"], checkpoint_hash=bundle["checkpoint_hash"])
    run = SimpleNamespace(id=bundle["run_id"])
    results = []
    missing = list(bundle["missing_dependencies"])
    if not missing:
        for command in bundle["commands"]:
            observation = SimpleNamespace(**command)
            try:
                receipt = _candidate(target_engine, dataset, run, observation)
                results.append({"observation_id": observation.id, "source_event_id": receipt.source_event_id,
                    "input_hash": receipt.input_hash, "execution_event_id": receipt.id,
                    "candidate_outcome": receipt.outcome, "actual": receipt.actual})
            except UnsupportedCommand as exc:
                diagnostic("candidate_blocked", exc)
                missing.append(f"{exc}:{observation.id}")
            except IsolationError:
                raise
            except Exception as exc:
                diagnostic("target_unavailable", exc)
                missing.append(f"target_unavailable:{observation.id}:{type(exc).__name__}")
                break
    return canonical({"run_id": run.id, "dataset_id": dataset.id, "bundle_hash": bundle["bundle_hash"],
        "target_fingerprint": fingerprint, "results": results, "missing_dependencies": sorted(set(missing))})


def import_execution_receipts(source, bundle, report):
    """Production report importer; compares against immutable SOURCE evidence.

No candidate command runs in this process. A report is accepted only against
the exact exported command/hash/run. Caller owns source commit and transport ACL.
"""
    run = source.scalar(select(ShadowRun).where(ShadowRun.id == bundle["run_id"]).with_for_update())
    if run is None:
        raise ValueError("验证运行不存在")
    if (report["run_id"] != run.id or report["dataset_id"] != run.dataset_id
            or report["bundle_hash"] != bundle["bundle_hash"]
            or report["target_fingerprint"] != bundle["target_fingerprint"]):
        raise IsolationError("候选回执不属于该输入/数据集/运行")
    current = export_input_bundle(source, run.id)
    if current["bundle_hash"] != bundle["bundle_hash"]:
        raise IsolationError("导出输入水位或摘要已变化")
    prior = {row.observation_id: row for row in source.scalars(select(ShadowResult).where(
        ShadowResult.run_id == run.id).with_for_update().execution_options(populate_existing=True))}
    commands = {row["id"]: row for row in bundle["commands"]}
    # A candidate report can add missing coverage; it can never erase the
    # independently detected source/checkpoint gaps from the exported bundle.
    missing = sorted(set(bundle["missing_dependencies"]) | set(report["missing_dependencies"]))
    difference_count = 0
    applied = 0
    delivered = set()
    for receipt in report["results"]:
        identity = receipt["observation_id"]
        if identity in delivered:
            raise IsolationError("候选回执重复包含同一观察身份")
        command = commands.get(identity)
        if command is None or command["source_event_id"] != receipt["source_event_id"] or command["request_hash"] != receipt["input_hash"]:
            raise IsolationError("候选回执源身份或输入摘要不匹配")
        delivered.add(identity)
        if identity in prior:
            old = prior[identity]
            if (old.execution_event_id != receipt["execution_event_id"] or old.actual != receipt["actual"]
                    or old.candidate_outcome != receipt["candidate_outcome"]):
                raise IsolationError("同一运行候选回执变化")
            difference_count += old.status == "differences"
            applied = max(applied, identity)
            continue
        observation = source.get(ShadowObservation, identity)
        candidate = SimpleNamespace(outcome=receipt["candidate_outcome"], actual=receipt["actual"])
        resolved_unknown = observation.outcome == "unknown" and bool(command.get("superseded_by"))
        try:
            if resolved_unknown:
                if candidate.outcome != "resolved_unknown" or candidate.actual != {
                        "resolved_by": command["superseded_by"], "economic_execution": False}:
                    raise IsolationError("unknown解决标记不能产生经济执行")
                differences = []
            else:
                differences = _compare(observation, candidate)
        except UnsupportedCommand as exc:
            missing.append(f"{exc}:{identity}")
            continue
        source.add(ShadowResult(run_id=run.id, observation_id=identity,
            execution_event_id=receipt["execution_event_id"], status="resolved" if resolved_unknown else "differences" if differences else "consistent",
            candidate_outcome=receipt["candidate_outcome"], actual=receipt["actual"]))
        for field, expected, actual in differences:
            source.add(ShadowDifference(run_id=run.id, observation_id=identity, invoice_id=observation.invoice_id,
                local_customer_id=observation.local_customer_id, payment_id=observation.payment_id,
                field=field, expected={"value": expected}, actual={"value": actual}))
        difference_count += bool(differences)
        applied = max(applied, identity)
        outbox = source.scalar(select(ShadowOutbox).where(ShadowOutbox.observation_id == identity).with_for_update())
        outbox.state, outbox.exported_at, outbox.last_error = "exported", beijing_now(), None
        outbox.attempts += 1
    missing.extend(f"missing_candidate_receipt:{identity}" for identity in set(commands) - delivered)
    for identity in set(commands) - delivered:
        outbox = source.scalar(select(ShadowOutbox).where(ShadowOutbox.observation_id == identity).with_for_update())
        outbox.attempts += 1
        outbox.last_error = next((value[:128] for value in missing if f":{identity}" in value), "coverage_incomplete")
    contiguous = 0
    for command in bundle["commands"]:
        if command["id"] not in delivered:
            break
        contiguous = command["id"]
    watermarks = dict(bundle["checkpoint"]["watermarks"])
    for identity in delivered:
        command = commands[identity]
        watermarks[command["aggregate_key"]] = max(watermarks.get(command["aggregate_key"], 0), command["causal_version"])
    run.status = "incomplete" if missing else "differences" if difference_count else "consistent"
    run.coverage = {"state": run.status, "missing_dependencies": sorted(set(missing)),
        "observed_through": run.through_observation_id, "exported_through": contiguous, "applied_through": contiguous,
        "applied_watermarks": watermarks, "sample_count": len(commands), "difference_samples": difference_count,
        "blocked_samples": len(set(commands) - delivered), "rejection_coverage": "observed_only",
        "resolved_unknown": [command["source_event_id"] for command in bundle["commands"] if command.get("superseded_by")],
        "checkpoint_hash": bundle["checkpoint_hash"], "bundle_hash": bundle["bundle_hash"]}
    run.checked_at = beijing_now()
    source.flush()
    return run
