"""At-least-once exporter and independently committed isolated-domain replay.

Source and target cannot form a distributed transaction. The target execution
receipt is committed WITH its domain change; a lost source ack reads that receipt
and never runs a second economic effect. Failed delivery retains source outbox.
"""
import hashlib
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.commerce_shadow.models import ShadowRun, ShadowExecution, ShadowBinding
from app.commerce_shadow.dispatcher import execute, UnsupportedCommand
from app.commerce_shadow.diagnostics import report


class IsolationError(ValueError):
    pass


def database_identity(engine, *, durable=True):
    url = engine.url
    if url.get_backend_name() == "sqlite":
        if not url.database or url.database == ":memory:":
            if durable:
                raise IsolationError("验证库必须为可恢复的独立持久数据库")
            return f"sqlite:memory:{id(engine)}"
        return "sqlite:" + str(Path(url.database).resolve()).casefold()
    host = (url.host or "localhost").casefold()
    if host in {"127.0.0.1", "::1"}:
        host = "localhost"
    return f"{url.get_backend_name()}:{host}:{url.port or 3306}/{url.database}"


def target_fingerprint(engine):
    return hashlib.sha256(database_identity(engine).encode()).hexdigest()


def assert_isolated(source_engine, target_engine, *, runtime_capabilities=(), production_urls=()):
    if runtime_capabilities:
        raise IsolationError("验证进程不得持有外发、生产上传或真实扫码能力")
    if source_engine is target_engine or database_identity(source_engine, durable=False) == database_identity(target_engine):
        raise IsolationError("验证库不能与正式来源库相同")
    for url in production_urls:
        # URL parsing only; never connect to production.
        from sqlalchemy.engine import make_url
        production = make_url(url)
        if target_engine.url == production:
            raise IsolationError("验证进程不能使用生产连接")
        if production.username and target_engine.url.username == production.username:
            raise IsolationError("验证进程不能使用生产数据库身份")
    if target_engine.url.get_backend_name() != "sqlite" and not (target_engine.url.database or "").startswith(("commerce_shadow_", "ark_shadow_", "test_")):
        raise IsolationError("验证数据库名称必须明确隔离")


def bind_target(target, dataset):
    """Bind a separately prepared checkpoint once; never imports expected rows."""
    from app.commerce_transition.models import BankAccountDomain
    from app.commerce_shadow.service import digest
    row = target.scalar(select(ShadowBinding).where(ShadowBinding.id == 1).with_for_update())
    if row and (row.dataset_id != dataset.id or row.checkpoint_hash != dataset.checkpoint_hash):
        raise IsolationError("该验证库已绑定其他数据集或检查点")
    if not isinstance(dataset.checkpoint, dict):
        raise IsolationError("验证数据集缺少独立准备的检查点")
    for expected in dataset.checkpoint.get("bank_domains", []):
        domain = target.scalar(select(BankAccountDomain).where(BankAccountDomain.subject_key == expected["subject_key"],
            BankAccountDomain.account_key == expected["account_key"], BankAccountDomain.channel == expected["channel"]))
        if domain is None or any(getattr(domain, key) != expected[key] for key in
                ("legacy_identity_complete", "enforced", "exclusive_route")) or digest(domain.evidence) != expected["evidence_hash"]:
            raise IsolationError("隔离银行账户域基础配置与已核验检查点不符")
    if row:
        return
    # Forbidden source idempotency/output seeds are checked BEFORE first replay.
    from app.finance.models import FinanceEvent
    from app.invoice.models import InvoiceCommerceEvent
    from app.inventory.models import StockLedger
    for model in (FinanceEvent, InvoiceCommerceEvent, StockLedger):
        if target.scalar(select(func.count()).select_from(model)):
            raise IsolationError("检查点不能导入正式结果或领域幂等流水")
    from app.commerce_shadow.dispatcher import verify_conservation
    if not verify_conservation(target, checkpoint=dataset.checkpoint)["passed"]:
        raise IsolationError("检查点初始责任不守恒")
    target.add(ShadowBinding(id=1, dataset_id=dataset.id, checkpoint_hash=dataset.checkpoint_hash))
    from app.commerce_transition.models import PlatformPolicy, WriterReceipt
    policy = target.get(PlatformPolicy, 1)
    if policy is not None and policy.phase != "local_only":
        raise IsolationError("隔离目标只能安装本地验证策略")
    if policy is None:
        target.add(PlatformPolicy(id=1, phase="local_only", version=1, min_writer_version=1,
            writer_inventory_verified=True, inventory_evidence={"isolated_replay": dataset.id},
            local_ever_effective=False))
    if target.get(WriterReceipt, "isolated-replay") is None:
        target.add(WriterReceipt(writer_key="isolated-replay", protocol_version=1, state="compatible",
            evidence={"no_external_credentials": True, "dataset_id": dataset.id}))
    target.flush()


def _candidate(target_engine, dataset, run, observation):
    with Session(target_engine, expire_on_commit=False) as target:
        target.info["commerce_shadow_execution_only"] = True
        with target.begin():
            if target_engine.dialect.name == "sqlite":
                # sqlite3 legacy transaction control does not BEGIN on SELECT;
                # force a real transaction before domain SAVEPOINTs so domain
                # effects and the durable execution receipt commit together.
                target.connection().exec_driver_sql("BEGIN IMMEDIATE")
            # A singleton binding lock serializes all objects in a dataset,
            # including payment/inventory cross-order causality.
            bind_target(target, dataset)
            prior = target.scalar(select(ShadowExecution).where(ShadowExecution.dataset_id == dataset.id,
                ShadowExecution.source_event_id == observation.source_event_id))
            if prior:
                if prior.input_hash != observation.request_hash:
                    raise IsolationError("已应用源身份的输入摘要变化")
                return prior
            checkpoint = dataset.checkpoint
            if observation.action.startswith(("payment.", "allocation.")) and not checkpoint.get("bank_domains"):
                raise UnsupportedCommand("missing_bank_domain_checkpoint")
            seen = {row.source_event_id for row in target.scalars(select(ShadowExecution).where(
                ShadowExecution.dataset_id == dataset.id))}
            if set(observation.dependencies) - seen - set(checkpoint["dependencies"]):
                raise UnsupportedCommand("missing_causal_dependency")
            previous = target.scalar(select(func.max(ShadowExecution.causal_version)).where(
                ShadowExecution.dataset_id == dataset.id, ShadowExecution.aggregate_key == observation.aggregate_key))
            previous = max(previous or 0, checkpoint["watermarks"].get(observation.aggregate_key, 0))
            if observation.causal_version != previous + 1:
                raise UnsupportedCommand("missing_or_late_causal_version")
            latest = target.scalar(select(ShadowExecution).where(ShadowExecution.dataset_id == dataset.id,
                ShadowExecution.aggregate_key == observation.aggregate_key).order_by(ShadowExecution.causal_version.desc()).limit(1))
            minimum_revision = max(latest.contract_revision if latest else 0,
                checkpoint.get("contract_revisions", {}).get(observation.aggregate_key, 0))
            minimum_epoch = max(latest.authority_epoch if latest else 0,
                checkpoint.get("authority_epochs", {}).get(observation.aggregate_key, 0))
            if observation.contract_revision < minimum_revision or observation.authority_epoch < minimum_epoch:
                raise UnsupportedCommand("late_contract_revision_or_authority_epoch")
            source_epoch = observation.command.get("body", {}).get("expected_authority_epoch")
            if source_epoch is not None and source_epoch != observation.authority_epoch:
                raise UnsupportedCommand("source_authority_epoch_mismatch")
            event_id = uuid4().hex
            try:
                # Economic rejection must rollback ALL candidate changes first.
                if getattr(observation, "superseded_by", None):
                    # A causal audit marker advances observation coverage but
                    # executes NO economic command. Only the resolved terminal
                    # input later receives an independent domain execution.
                    actual = {"resolved_by": observation.superseded_by, "economic_execution": False}
                    outcome = "resolved_unknown"
                else:
                    with target.begin_nested():
                        actual = execute(target, dataset_id=dataset.id, execution_event_id=event_id,
                            action=observation.action, command=observation.command, actor_id=observation.actor_id,
                            checkpoint=dataset.checkpoint)
                    outcome = "accepted"
            except UnsupportedCommand:
                raise
            except ValidationError as exc:
                report("invalid_typed_command", exc)
                raise UnsupportedCommand("invalid_typed_command") from None
            except (ValueError, HTTPException) as exc:
                report("candidate_rejected", exc)
                outcome = "rejected"
                # Only a stable category, never SQL parameters/credentials.
                actual = {"metrics": {}, "reason_code": str(exc.detail) if isinstance(exc, HTTPException) else str(exc)}
            row = ShadowExecution(id=event_id, dataset_id=dataset.id, first_run_id=run.id,
                source_event_id=observation.source_event_id, aggregate_key=observation.aggregate_key,
                causal_version=observation.causal_version, contract_revision=observation.contract_revision,
                authority_epoch=observation.authority_epoch, input_hash=observation.request_hash,
                outcome=outcome, actual=actual)
            target.add(row)
            target.flush()
        return row


def _compare(observation, candidate):
    if candidate.actual.get("invariants", {}).get("passed") is False:
        return [("conservation", "passed", candidate.actual["invariants"])]
    if observation.outcome != candidate.outcome:
        return [("outcome", observation.outcome, candidate.outcome)]
    if observation.outcome == "rejected":
        # Formal and candidate rejection reasons are independently retained.
        reason = observation.result.get("reason_code") if observation.resolves_source_event_id else observation.reason_code
        return [] if reason and reason == candidate.actual.get("reason_code") else [
            ("reason_code", reason, candidate.actual.get("reason_code"))]
    expected = observation.result.get("metrics", observation.result)
    actual = candidate.actual.get("metrics", {})
    if not expected:
        raise UnsupportedCommand("missing_expected_metrics")
    return [(key, value, actual.get(key)) for key, value in expected.items()
            if key not in actual or not _same_value(value, actual[key])]


def _same_value(left, right):
    from decimal import Decimal, InvalidOperation
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(_same_value(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right and type(left) is type(right)
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError):
        return left == right


def run_replay(source, run_id, target_engine, *, runtime_capabilities=(), production_urls=()):
    """Local isolated-test orchestrator. Production uses the process-boundary API.

    Exporter/importer own source credentials; execute_input_bundle runs in a
    separate candidate-only process. This helper proves the same protocol while
    retaining independent target transactions and durable execution receipts.
    """
    assert_isolated(source.get_bind(), target_engine, runtime_capabilities=runtime_capabilities,
                    production_urls=production_urls)
    from app.commerce_shadow.transport import export_input_bundle, execute_input_bundle, import_execution_receipts
    run = source.get(ShadowRun, run_id)
    if run is None:
        raise ValueError("验证运行不存在")
    if run.status in {"consistent", "differences"}:
        return run
    bundle = export_input_bundle(source, run_id)
    report = execute_input_bundle(target_engine, bundle, runtime_capabilities=runtime_capabilities,
                                  production_urls=production_urls)
    return import_execution_receipts(source, bundle, report)
