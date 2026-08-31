"""Guarded domestic-route cutover.

Dry-run is the default.  A business cutover is accepted only when the exact same
database snapshot was reviewed and supplied back as ``--preflight-token``, and
every item with report history is explicitly reconciled as ``keep_current``.

This script intentionally never applies Alembic migrations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.domestic import progress_service, route_rule_service
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticItemProgress,
    DomesticItemUnit,
    DomesticOrderItem,
    DomesticProduct,
    DomesticReportLog,
    DomesticReportUnit,
    DomesticRouteRule,
    DomesticSkipLog,
    DomesticSkipUnit,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding


TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")


class CutoverError(ValueError):
    """A reviewed cutover precondition was not satisfied."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def require_exact_route(rows: list[ProcessRoute], target_route_name: str) -> ProcessRoute:
    """Refuse missing/ambiguous results even if the current schema is UNIQUE.

    Production collations and damaged legacy databases are still treated as
    untrusted inputs; a cutover never chooses the first row silently.
    """
    exact = [row for row in rows if row.name == target_route_name]
    if not exact:
        raise CutoverError(f"目标路线“{target_route_name}”不存在")
    if len(exact) != 1:
        raise CutoverError(f"目标路线“{target_route_name}”匹配到多条记录，拒绝切换")
    return exact[0]


def _load_target_route(
    db: Session,
    target_route_name: str,
    *,
    lock: bool,
) -> ProcessRoute:
    query = db.query(ProcessRoute).filter(ProcessRoute.name == target_route_name)
    if lock:
        query = query.with_for_update()
    route = require_exact_route(query.all(), target_route_name)
    if route.status != 1:
        raise CutoverError(f"目标路线“{target_route_name}”已停用")
    return route


def _normalize_craft_names(craft_names: list[str] | None) -> list[str]:
    normalized = []
    seen = set()
    for value in craft_names or []:
        name = value.strip()
        if not name:
            raise CutoverError("--craft-name 不能为空")
        if name not in seen:
            normalized.append(name)
            seen.add(name)
    return sorted(normalized)


def _load_route_steps(db: Session, route_id: int) -> list[tuple[ProcessRouteStep, Process]]:
    rows = (
        db.query(ProcessRouteStep, Process)
        .join(Process, Process.id == ProcessRouteStep.process_id)
        .filter(ProcessRouteStep.route_id == route_id)
        .order_by(ProcessRouteStep.step_order.asc())
        .all()
    )
    if not rows:
        raise CutoverError("目标路线没有工序，不能切换")
    if any(process.status != 1 for _step, process in rows):
        disabled = [process.name for _step, process in rows if process.status != 1]
        raise CutoverError(f"目标路线含停用工序：{'、'.join(disabled)}")
    return rows


def _validate_target_rules(db: Session, route_id: int) -> tuple[list[dict], list[dict]]:
    rows = db.query(DomesticRouteRule).filter(
        DomesticRouteRule.route_id == route_id,
    ).order_by(DomesticRouteRule.process_id.asc()).all()
    payload = [
        {
            "process_id": row.process_id,
            "rule_type": row.rule_type,
            "config": row.config_json,
        }
        for row in rows
    ]
    if not payload:
        raise CutoverError("目标路线没有配置条件规则，拒绝切换")
    try:
        route_rule_service.validate_rules(db, route_id, payload)
        display = route_rule_service.list_rules(db, route_id)
    except (TypeError, KeyError, ValueError) as exc:
        raise CutoverError(f"目标路线规则校验失败：{exc}") from exc
    return payload, display


def _worker_coverage(
    db: Session,
    steps: list[tuple[ProcessRouteStep, Process]],
) -> dict:
    process_ids = [step.process_id for step, _process in steps]
    bindings = (
        db.query(UserProcessBinding.process_id, ArkUser.id, ArkUser.real_name)
        .join(ArkUser, ArkUser.id == UserProcessBinding.user_id)
        .filter(
            UserProcessBinding.process_id.in_(process_ids),
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        )
        .order_by(UserProcessBinding.process_id.asc(), ArkUser.id.asc())
        .all()
    )
    by_process: dict[int, list[dict]] = {process_id: [] for process_id in process_ids}
    for process_id, user_id, real_name in bindings:
        by_process[process_id].append({"user_id": user_id, "name": real_name})
    rows = [
        {
            "process_id": step.process_id,
            "process_name": process.name,
            "step_order": step.step_order,
            "workers": by_process[step.process_id],
        }
        for step, process in steps
    ]
    missing = [
        {"process_id": row["process_id"], "process_name": row["process_name"]}
        for row in rows
        if not row["workers"]
    ]
    return {"steps": rows, "missing": missing}


def _selected_mappings(
    db: Session,
    craft_names: list[str],
    *,
    lock: bool,
) -> list[DomesticCraftRoute]:
    if not craft_names:
        return []
    query = db.query(DomesticCraftRoute).filter(DomesticCraftRoute.craft.in_(craft_names))
    if lock:
        query = query.with_for_update()
    rows = query.order_by(
        DomesticCraftRoute.product_type.asc(), DomesticCraftRoute.craft.asc(),
    ).all()
    found = {row.craft for row in rows}
    missing = sorted(set(craft_names) - found)
    if missing:
        raise CutoverError(f"以下工艺没有路线映射：{'、'.join(missing)}")
    return rows


def _selected_products(
    db: Session,
    mappings: list[DomesticCraftRoute],
    *,
    lock: bool,
) -> list[DomesticProduct]:
    pairs = sorted({(row.product_type, row.craft) for row in mappings})
    if not pairs:
        return []
    query = db.query(DomesticProduct).filter(
        tuple_(DomesticProduct.product_type, DomesticProduct.craft).in_(pairs)
    )
    if lock:
        query = query.with_for_update()
    return query.order_by(DomesticProduct.id.asc()).all()


def _selected_items(
    db: Session,
    products: list[DomesticProduct],
    *,
    lock: bool,
) -> list[DomesticOrderItem]:
    product_ids = [row.id for row in products]
    if not product_ids:
        return []
    query = db.query(DomesticOrderItem).filter(
        DomesticOrderItem.product_id.in_(product_ids)
    )
    if lock:
        query = query.with_for_update()
    return query.order_by(DomesticOrderItem.id.asc()).all()


def _item_report_counts(db: Session, item_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    if not item_ids:
        return {}, {}
    total = dict(
        db.query(DomesticReportLog.item_id, func.count(DomesticReportLog.id))
        .filter(DomesticReportLog.item_id.in_(item_ids))
        .group_by(DomesticReportLog.item_id)
        .all()
    )
    effective = dict(
        db.query(DomesticReportLog.item_id, func.count(DomesticReportLog.id))
        .filter(
            DomesticReportLog.item_id.in_(item_ids),
            DomesticReportLog.revoked == 0,
        )
        .group_by(DomesticReportLog.item_id)
        .all()
    )
    return total, effective


def _item_skip_counts(db: Session, item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}
    return dict(
        db.query(DomesticSkipLog.item_id, func.count(DomesticSkipLog.id))
        .filter(DomesticSkipLog.item_id.in_(item_ids))
        .group_by(DomesticSkipLog.item_id)
        .all()
    )


def _unit_identity(db: Session, item_ids: list[int]) -> dict[str, list[dict]]:
    if not item_ids:
        return {}
    rows = db.query(
        DomesticItemUnit.item_id,
        DomesticItemUnit.id,
        DomesticItemUnit.unit_no,
        DomesticItemUnit.status,
    ).filter(DomesticItemUnit.item_id.in_(item_ids)).order_by(
        DomesticItemUnit.item_id.asc(), DomesticItemUnit.unit_no.asc(),
    ).all()
    result: dict[str, list[dict]] = {}
    for item_id, unit_id, unit_no, status in rows:
        result.setdefault(str(item_id), []).append({
            "id": unit_id, "unit_no": unit_no, "status": status,
        })
    return result


def _totals_for_item_ids(db: Session, item_ids: list[int]) -> dict[str, int]:
    if not item_ids:
        return {
            "items": 0,
            "report_logs": 0,
            "report_units": 0,
            "completed_qty": 0,
            "workload_qty": 0,
        }
    report_logs = db.query(func.count(DomesticReportLog.id)).filter(
        DomesticReportLog.item_id.in_(item_ids)
    ).scalar() or 0
    report_units = (
        db.query(func.count(DomesticReportUnit.id))
        .join(DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id)
        .filter(DomesticReportLog.item_id.in_(item_ids))
        .scalar() or 0
    )
    completed = db.query(func.sum(DomesticItemProgress.completed_qty)).filter(
        DomesticItemProgress.item_id.in_(item_ids)
    ).scalar() or 0
    workload = db.query(func.sum(DomesticReportLog.report_qty)).filter(
        DomesticReportLog.item_id.in_(item_ids),
        DomesticReportLog.revoked == 0,
    ).scalar() or 0
    return {
        "items": len(item_ids),
        "report_logs": int(report_logs),
        "report_units": int(report_units),
        "completed_qty": int(completed),
        "workload_qty": int(workload),
    }


def _audit_state(db: Session, item_ids: list[int]) -> dict:
    """Exact affected facts used by the token and reported-history guard."""
    if not item_ids:
        return {"progress": [], "report_logs": [], "report_units": [], "skip_logs": [], "skip_units": []}
    progress = db.query(DomesticItemProgress).filter(
        DomesticItemProgress.item_id.in_(item_ids)
    ).order_by(DomesticItemProgress.item_id.asc(), DomesticItemProgress.step_order.asc()).all()
    logs = db.query(DomesticReportLog).filter(
        DomesticReportLog.item_id.in_(item_ids)
    ).order_by(DomesticReportLog.id.asc()).all()
    log_ids = [row.id for row in logs]
    report_units = db.query(DomesticReportUnit).filter(
        DomesticReportUnit.log_id.in_(log_ids or [0])
    ).order_by(DomesticReportUnit.id.asc()).all()
    skips = db.query(DomesticSkipLog).filter(
        DomesticSkipLog.item_id.in_(item_ids)
    ).order_by(DomesticSkipLog.id.asc()).all()
    skip_ids = [row.id for row in skips]
    skip_units = db.query(DomesticSkipUnit).filter(
        DomesticSkipUnit.skip_log_id.in_(skip_ids or [0])
    ).order_by(DomesticSkipUnit.id.asc()).all()
    return {
        "progress": [{
            "id": row.id, "item_id": row.item_id, "route_id": row.route_id,
            "process_id": row.process_id, "step_order": row.step_order,
            "completed_qty": row.completed_qty, "status": row.status,
        } for row in progress],
        "report_logs": [{
            "id": row.id, "item_id": row.item_id, "progress_id": row.progress_id,
            "process_id": row.process_id, "step_order": row.step_order,
            "report_qty": row.report_qty, "outcome_json": row.outcome_json,
            "request_id": row.request_id, "revoked": row.revoked,
        } for row in logs],
        "report_units": [{
            "id": row.id, "log_id": row.log_id, "unit_id": row.unit_id,
            "progress_id": row.progress_id, "outcome_code": row.outcome_code,
        } for row in report_units],
        "skip_logs": [{
            "id": row.id, "item_id": row.item_id, "progress_id": row.progress_id,
            "skip_qty": row.skip_qty, "source": row.source,
            "trigger_report_log_id": row.trigger_report_log_id,
            "request_id": row.request_id, "revoked": row.revoked,
        } for row in skips],
        "skip_units": [{
            "id": row.id, "skip_log_id": row.skip_log_id,
            "unit_id": row.unit_id, "progress_id": row.progress_id,
        } for row in skip_units],
    }


def _progress_completed_by_item(db: Session, item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}
    return {
        item_id: int(value or 0)
        for item_id, value in db.query(
            DomesticItemProgress.item_id,
            func.sum(DomesticItemProgress.completed_qty),
        ).filter(DomesticItemProgress.item_id.in_(item_ids)).group_by(
            DomesticItemProgress.item_id,
        ).all()
    }


def _build_preflight(
    db: Session,
    *,
    target_route_name: str,
    craft_names: list[str] | None,
    lock: bool,
) -> dict:
    if not isinstance(target_route_name, str) or not target_route_name.strip():
        raise CutoverError("必须提供目标路线精确名称")
    target_route_name = target_route_name.strip()
    normalized_crafts = _normalize_craft_names(craft_names)
    target = _load_target_route(db, target_route_name, lock=lock)
    steps = _load_route_steps(db, target.id)
    raw_rules, display_rules = _validate_target_rules(db, target.id)
    coverage = _worker_coverage(db, steps)
    if coverage["missing"]:
        names = "、".join(row["process_name"] for row in coverage["missing"])
        raise CutoverError(f"目标路线工序未绑定在职人员：{names}")

    mappings = _selected_mappings(db, normalized_crafts, lock=lock)
    products = _selected_products(db, mappings, lock=lock)
    items = _selected_items(db, products, lock=lock)
    item_ids = [row.id for row in items]
    total_logs, effective_logs = _item_report_counts(db, item_ids)
    skip_logs = _item_skip_counts(db, item_ids)
    completed = _progress_completed_by_item(db, item_ids)
    unit_identity = _unit_identity(db, item_ids)

    item_rows = []
    for item in items:
        history_count = int(total_logs.get(item.id, 0))
        skip_history_count = int(skip_logs.get(item.id, 0))
        progress_completed = completed.get(item.id, 0)
        if history_count == 0 and progress_completed != 0:
            raise CutoverError(
                f"明细 {item.id} 没有报工流水但累计完成量为 {progress_completed}，"
                "需先人工核账，不能自动重建"
            )
        item_rows.append({
            "id": item.id,
            "product_id": item.product_id,
            "current_route_id": item.route_id,
            "order_qty": item.order_qty,
            "report_log_count": history_count,
            "skip_log_count": skip_history_count,
            "effective_report_log_count": int(effective_logs.get(item.id, 0)),
            "completed_qty": progress_completed,
            "unit_identity_digest": _digest(unit_identity.get(str(item.id), [])),
        })

    result = {
        "mode": "apply-preflight" if lock else "dry-run",
        "target_route": {
            "id": target.id,
            "name": target.name,
            "status": target.status,
            "rule_valid": True,
            "steps": [
                {
                    "process_id": step.process_id,
                    "process_name": process.name,
                    "step_order": step.step_order,
                }
                for step, process in steps
            ],
            "rules": display_rules,
            "raw_rules_digest": _digest(raw_rules),
        },
        "worker_coverage": coverage,
        "selected_craft_names": normalized_crafts,
        "craft_mappings": [
            {
                "id": row.id,
                "product_type": row.product_type,
                "craft": row.craft,
                "current_route_id": row.route_id,
                "will_change": row.route_id != target.id,
            }
            for row in mappings
        ],
        "products": [
            {
                "id": row.id,
                "name": row.name,
                "product_type": row.product_type,
                "craft": row.craft,
                "current_route_id": row.route_id,
                "will_change": row.route_id != target.id,
            }
            for row in products
        ],
        "items": {
            "no_report": [
                row for row in item_rows
                if row["report_log_count"] == 0 and row["skip_log_count"] == 0
            ],
            # The reconciliation group includes any immutable production audit,
            # including skip-only history, because rebuilding its progress FK parent
            # would erase or detach that evidence.
            "reported": [
                row for row in item_rows
                if row["report_log_count"] > 0 or row["skip_log_count"] > 0
            ],
        },
        "before_totals": _totals_for_item_ids(db, item_ids),
        "unit_identity_digest": _digest(unit_identity),
        "audit_state_digest": _digest(_audit_state(db, item_ids)),
    }
    token_source = dict(result)
    token_source["mode"] = "canonical-preflight"
    result["preflight_token"] = _digest(token_source)
    return result


def preflight(
    db: Session,
    *,
    target_route_name: str,
    craft_names: list[str] | None = None,
) -> dict:
    """Read-only preflight. Calling it never commits or mutates ORM rows."""
    return _build_preflight(
        db,
        target_route_name=target_route_name,
        craft_names=craft_names,
        lock=False,
    )


def _validate_reconciliation(reconciliation: dict, reported_item_ids: set[int]) -> None:
    if not isinstance(reconciliation, dict) or set(reconciliation) != {"reported_items"}:
        raise CutoverError("reconciliation JSON 只能包含 reported_items")
    rows = reconciliation["reported_items"]
    if not isinstance(rows, list):
        raise CutoverError("reconciliation.reported_items 必须是数组")
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"item_id", "action"}:
            raise CutoverError("每条 reported_items 必须且只能包含 item_id/action")
        item_id = row["item_id"]
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
            raise CutoverError("reported_items.item_id 必须是正整数")
        if item_id in seen:
            raise CutoverError(f"reported item {item_id} 重复")
        seen.add(item_id)
        if row["action"] != "keep_current":
            raise CutoverError(
                f"reported item {item_id} 使用了不支持的处置动作：{row['action']}"
            )
    if seen != reported_item_ids:
        missing = sorted(reported_item_ids - seen)
        extra = sorted(seen - reported_item_ids)
        raise CutoverError(
            f"reported_items 必须逐项覆盖且不能多余；missing={missing}, extra={extra}"
        )


def _lock_cutover_scope(db: Session, plan: dict) -> None:
    """Lock child state after item locks, matching the live reporting lock order."""
    item_ids = [
        row["id"]
        for group in ("no_report", "reported")
        for row in plan["items"][group]
    ]
    if not item_ids:
        return
    db.query(DomesticItemProgress.id).filter(
        DomesticItemProgress.item_id.in_(item_ids)
    ).with_for_update().all()
    db.query(DomesticItemUnit.id).filter(
        DomesticItemUnit.item_id.in_(item_ids)
    ).with_for_update().all()
    log_ids = [row[0] for row in db.query(DomesticReportLog.id).filter(
        DomesticReportLog.item_id.in_(item_ids)
    ).with_for_update().all()]
    if log_ids:
        db.query(DomesticReportUnit.id).filter(
            DomesticReportUnit.log_id.in_(log_ids)
        ).with_for_update().all()
    skip_ids = [row[0] for row in db.query(DomesticSkipLog.id).filter(
        DomesticSkipLog.item_id.in_(item_ids)
    ).with_for_update().all()]
    if skip_ids:
        db.query(DomesticSkipUnit.id).filter(
            DomesticSkipUnit.skip_log_id.in_(skip_ids)
        ).with_for_update().all()


def apply_cutover(
    db: Session,
    *,
    target_route_name: str,
    craft_names: list[str],
    preflight_token: str,
    reconciliation: dict,
) -> dict:
    """Apply a reviewed cutover as one transaction, or leave no writes."""
    normalized_crafts = _normalize_craft_names(craft_names)
    if not normalized_crafts:
        raise CutoverError("apply 至少一个 --craft-name")
    if not isinstance(preflight_token, str) or TOKEN_RE.fullmatch(preflight_token) is None:
        raise CutoverError("预检令牌格式不正确")

    # End any read-only preflight transaction held by an interactive caller. Apply
    # then starts from locking/current reads instead of a MySQL RR snapshot.
    db.rollback()
    try:
        locked_plan = _build_preflight(
            db,
            target_route_name=target_route_name,
            craft_names=normalized_crafts,
            lock=True,
        )
        _lock_cutover_scope(db, locked_plan)
        # Recompute after every affected child row is locked. Report writers lock the
        # item first, so no new report can enter this scope past this point.
        locked_plan = _build_preflight(
            db,
            target_route_name=target_route_name,
            craft_names=normalized_crafts,
            lock=True,
        )
        if locked_plan["preflight_token"] != preflight_token:
            raise CutoverError("预检后数据已变化，请重新 dry-run、复核并使用新令牌")

        reported_ids = {row["id"] for row in locked_plan["items"]["reported"]}
        _validate_reconciliation(reconciliation, reported_ids)
        before_totals = locked_plan["before_totals"]
        before_unit_digest = locked_plan["unit_identity_digest"]
        before_reported_digest = _digest(_audit_state(db, sorted(reported_ids)))
        target_id = locked_plan["target_route"]["id"]

        mapping_ids = [row["id"] for row in locked_plan["craft_mappings"]]
        product_ids = [row["id"] for row in locked_plan["products"]]
        if mapping_ids:
            db.query(DomesticCraftRoute).filter(
                DomesticCraftRoute.id.in_(mapping_ids)
            ).update({DomesticCraftRoute.route_id: target_id}, synchronize_session=False)
        if product_ids:
            db.query(DomesticProduct).filter(
                DomesticProduct.id.in_(product_ids)
            ).update({DomesticProduct.route_id: target_id}, synchronize_session=False)

        rebuilt_item_ids = []
        for row in locked_plan["items"]["no_report"]:
            item = db.query(DomesticOrderItem).filter(
                DomesticOrderItem.id == row["id"]
            ).with_for_update().one()
            count = progress_service.init_item_progress(db, item, route_id=target_id)
            if count != len(locked_plan["target_route"]["steps"]):
                raise CutoverError(
                    f"明细 {item.id} 重建得到 {count} 道工序，与目标路线不一致"
                )
            progress_service.sync_progress_statuses(db, item)
            progress_service.recalc_item_status(db, item)
            rebuilt_item_ids.append(item.id)
        db.flush()

        all_item_ids = [
            row["id"]
            for group in ("no_report", "reported")
            for row in locked_plan["items"][group]
        ]
        after_totals = _totals_for_item_ids(db, all_item_ids)
        after_unit_digest = _digest(_unit_identity(db, all_item_ids))
        if after_totals != before_totals:
            raise CutoverError(
                f"切换前后数量/工作量不守恒：before={before_totals}, after={after_totals}"
            )
        if after_unit_digest != before_unit_digest:
            raise CutoverError("切换前后单件身份不守恒，已回滚")
        after_reported_digest = _digest(_audit_state(db, sorted(reported_ids)))
        if after_reported_digest != before_reported_digest:
            raise CutoverError("有生产审计历史的明细发生变化，已回滚")

        result = {
            "mode": "applied",
            "target_route": locked_plan["target_route"],
            "selected_craft_names": normalized_crafts,
            "updated_mapping_ids": mapping_ids,
            "updated_product_ids": product_ids,
            "rebuilt_item_ids": rebuilt_item_ids,
            "kept_reported_item_ids": sorted(reported_ids),
            "before_totals": before_totals,
            "after_totals": after_totals,
            "unit_identity_conserved": True,
        }
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def capture_database_fingerprint(db: Session) -> str:
    """Small deterministic fingerprint used by tests to prove dry-run/rollback."""
    tables = (
        (DomesticCraftRoute, ("id", "product_type", "craft", "route_id")),
        (DomesticProduct, ("id", "name", "product_type", "craft", "route_id")),
        (DomesticOrderItem, ("id", "product_id", "route_id", "order_qty", "status")),
        (DomesticItemProgress, ("id", "item_id", "route_id", "process_id", "step_order", "completed_qty")),
        (DomesticItemUnit, ("id", "item_id", "unit_no", "status")),
        (DomesticReportLog, ("id", "item_id", "progress_id", "report_qty", "revoked")),
        (DomesticReportUnit, ("id", "log_id", "unit_id", "progress_id")),
        (DomesticSkipLog, ("id", "item_id", "progress_id", "skip_qty", "source", "revoked")),
        (DomesticSkipUnit, ("id", "skip_log_id", "unit_id", "progress_id")),
    )
    snapshot = {}
    for model, fields in tables:
        rows = db.query(model).order_by(model.id.asc()).all()
        snapshot[model.__tablename__] = [
            {field: getattr(row, field) for field in fields}
            for row in rows
        ]
    return _digest(snapshot)


def _read_reconciliation(path: str | None) -> dict:
    if not path:
        raise CutoverError("--apply 必须提供 --reconciliation-file")
    file_path = Path(path)
    try:
        value = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CutoverError(f"无法读取 reconciliation JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise CutoverError("reconciliation JSON 顶层必须是对象")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="内贸条件工艺路线预检与受控切换（默认只读）",
    )
    parser.add_argument(
        "--target-route-name", required=True,
        help="目标工艺路线的精确名称（不接受 ID 或模糊匹配）",
    )
    parser.add_argument(
        "--craft-name", action="append", default=[],
        help="要切换的工艺精确名称；可重复。apply 时至少一个",
    )
    parser.add_argument("--apply", action="store_true", help="执行受控切换；省略即只读预检")
    parser.add_argument("--preflight-token", help="刚复核的 dry-run 输出 token")
    parser.add_argument("--reconciliation-file", help="reported item 的逐项复核 JSON 文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        if args.apply:
            if not args.preflight_token:
                raise CutoverError("--apply 必须提供 --preflight-token")
            result = apply_cutover(
                db,
                target_route_name=args.target_route_name,
                craft_names=args.craft_name,
                preflight_token=args.preflight_token,
                reconciliation=_read_reconciliation(args.reconciliation_file),
            )
        else:
            result = preflight(
                db,
                target_route_name=args.target_route_name,
                craft_names=args.craft_name,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except CutoverError as exc:
        db.rollback()
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
