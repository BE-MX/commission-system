"""内贸条件路线的逐件通行事实与自动跳过。"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domestic import route_rule_service
from app.domestic.models import (
    DomesticItemProgress,
    DomesticItemUnit,
    DomesticOrderItem,
    DomesticReportLog,
    DomesticReportUnit,
    DomesticRouteRule,
    DomesticSkipLog,
    DomesticSkipUnit,
)
from app.production.models import Process


@dataclass(frozen=True)
class PassageState:
    reported_by_progress: dict[int, set[int]]
    skipped_by_progress: dict[int, set[int]]

    def passed(self, progress_id: int) -> set[int]:
        return self.reported_by_progress.get(progress_id, set()) | self.skipped_by_progress.get(
            progress_id, set()
        )


def runtime_rule_map(db: Session, route_id: int | None) -> dict[int, dict]:
    """读取在制明细锁定路线的规则，不因路线后来停用而阻断存量生产。"""
    if not route_id:
        return {}
    rows = db.query(DomesticRouteRule).filter(
        DomesticRouteRule.route_id == route_id,
    ).all()
    return {
        row.process_id: {
            "process_id": row.process_id,
            "rule_type": row.rule_type,
            "config": row.config_json,
        }
        for row in rows
    }


def load_passage_state(db: Session, item: DomesticOrderItem) -> PassageState:
    """用两次批量查询加载一个明细的全部实际报工与有效跳过身份。"""
    reported_rows = (
        db.query(DomesticReportUnit.progress_id, DomesticReportUnit.unit_id)
        .join(DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id)
        .filter(DomesticReportLog.item_id == item.id, DomesticReportLog.revoked == 0)
        .all()
    )
    skipped_rows = (
        db.query(DomesticSkipUnit.progress_id, DomesticSkipUnit.unit_id)
        .join(DomesticSkipLog, DomesticSkipLog.id == DomesticSkipUnit.skip_log_id)
        .filter(DomesticSkipLog.item_id == item.id, DomesticSkipLog.revoked == 0)
        .all()
    )
    reported: dict[int, set[int]] = {}
    skipped: dict[int, set[int]] = {}
    for progress_id, unit_id in reported_rows:
        reported.setdefault(progress_id, set()).add(unit_id)
    for progress_id, unit_id in skipped_rows:
        skipped.setdefault(progress_id, set()).add(unit_id)
    return PassageState(reported_by_progress=reported, skipped_by_progress=skipped)


def active_units(db: Session, item: DomesticOrderItem) -> list[DomesticItemUnit]:
    return (
        db.query(DomesticItemUnit)
        .filter(DomesticItemUnit.item_id == item.id, DomesticItemUnit.status == 1)
        .order_by(DomesticItemUnit.unit_no.asc())
        .all()
    )


def _row_index(rows: list[DomesticItemProgress]) -> dict[int, int]:
    return {row.id: index for index, row in enumerate(rows)}


def effective_passage_maps(
    rows: list[DomesticItemProgress],
    state: PassageState,
    active_unit_ids: set[int],
    rules: dict[int, dict],
) -> tuple[dict[int, set[int]], dict[int, set[int]], dict[int, set[int]]]:
    """按路线顺序激活预先记录的跳过，防止单件跨过尚未完成的分支。"""
    upstream_by_progress: dict[int, set[int]] = {}
    effective_skipped_by_progress: dict[int, set[int]] = {}
    passed_by_progress: dict[int, set[int]] = {}
    for index, row in enumerate(rows):
        if index == 0:
            upstream = set(active_unit_ids)
        else:
            previous = rows[index - 1]
            if rules.get(previous.process_id, {}).get("rule_type") == route_rule_service.RULE_OPTIONAL:
                upstream = set(upstream_by_progress.get(previous.id, set()))
            else:
                upstream = set(passed_by_progress.get(previous.id, set()))
        reported = state.reported_by_progress.get(row.id, set()) & upstream
        skipped = (state.skipped_by_progress.get(row.id, set()) - reported) & upstream
        upstream_by_progress[row.id] = upstream
        effective_skipped_by_progress[row.id] = skipped
        passed_by_progress[row.id] = reported | skipped
    return upstream_by_progress, effective_skipped_by_progress, passed_by_progress


def upstream_unit_ids(
    item: DomesticOrderItem,
    progress: DomesticItemProgress,
    rows: list[DomesticItemProgress],
    state: PassageState,
    active_unit_ids: set[int],
    rules: dict[int, dict],
) -> set[int]:
    upstream, _skipped, _passed = effective_passage_maps(
        rows, state, active_unit_ids, rules,
    )
    return upstream[progress.id]


def eligible_unit_ids(
    item: DomesticOrderItem,
    progress: DomesticItemProgress,
    rows: list[DomesticItemProgress],
    state: PassageState,
    active_unit_ids: set[int],
    rules: dict[int, dict],
) -> set[int]:
    upstream = upstream_unit_ids(item, progress, rows, state, active_unit_ids, rules)
    return upstream - state.passed(progress.id)


def ordered_report_candidates(
    item: DomesticOrderItem,
    progress: DomesticItemProgress,
    rows: list[DomesticItemProgress],
    state: PassageState,
    units: list[DomesticItemUnit],
    rules: dict[int, dict],
) -> tuple[list[DomesticItemUnit], set[int]]:
    """返回稳定顺序候选及其中需要自动绕过直属 optional 前序的身份。"""
    active_ids = {unit.id for unit in units}
    eligible = eligible_unit_ids(item, progress, rows, state, active_ids, rules)
    index = _row_index(rows)[progress.id]
    bypassable: set[int] = set()
    if index > 0:
        previous = rows[index - 1]
        if rules.get(previous.process_id, {}).get("rule_type") == route_rule_service.RULE_OPTIONAL:
            _upstream, _skipped, passed = effective_passage_maps(
                rows, state, active_ids, rules,
            )
            already_optional = passed.get(previous.id, set())
            bypassable = eligible - already_optional
            priority = (eligible & already_optional, bypassable)
            ordered = [unit for ids in priority for unit in units if unit.id in ids]
            return ordered, bypassable
    return [unit for unit in units if unit.id in eligible], bypassable


def normalize_outcomes(
    rule: dict | None,
    outcomes: dict[str, int] | None,
    *,
    qty: int,
    unit_mode: bool,
) -> dict[str, int] | None:
    if not rule or rule.get("rule_type") != route_rule_service.RULE_DECISION:
        if outcomes:
            raise ValueError("这道工序不是分流判定工序，不能提交结果分配")
        return None

    if not isinstance(outcomes, dict):
        raise ValueError("分流判定工序必须提交结果分配")
    options = rule["config"]["options"]
    option_codes = [option["code"] for option in options]
    unknown = set(outcomes) - set(option_codes)
    if unknown:
        raise ValueError("结果分配包含未配置的选项")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in outcomes.values()):
        raise ValueError("结果数量必须是大于等于 0 的整数")

    if unit_mode:
        normalized = {code: outcomes[code] for code in option_codes if outcomes.get(code, 0) > 0}
        if qty != 1 or len(normalized) != 1 or next(iter(normalized.values()), 0) != 1:
            raise ValueError("逐件扫码只能选择一个结果")
        return normalized

    if set(outcomes) != set(option_codes):
        raise ValueError("数量报工必须包含全部结果选项")
    if sum(outcomes.values()) != qty:
        raise ValueError("结果数量合计必须等于报工数量")
    return {code: outcomes[code] for code in option_codes if outcomes[code] > 0}


def normalize_replay_outcomes(outcomes: dict[str, int] | None) -> dict[str, int] | None:
    """幂等比较只做稳定形态归一化，不依赖可能已修改的当前路线规则。"""
    if outcomes is None:
        return None
    if not isinstance(outcomes, dict):
        raise ValueError("结果分配必须是编码到数量的对象")
    if any(
        not isinstance(code, str)
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for code, value in outcomes.items()
    ):
        raise ValueError("结果数量必须是大于等于 0 的整数")
    normalized = {code: value for code, value in outcomes.items() if value > 0}
    return normalized or None


def allocate_outcomes(
    units: list[DomesticItemUnit],
    outcomes: dict[str, int] | None,
) -> tuple[dict[int, str], dict[str, list[DomesticItemUnit]]]:
    if outcomes is None:
        return {}, {}
    by_unit: dict[int, str] = {}
    by_code: dict[str, list[DomesticItemUnit]] = {}
    cursor = 0
    for code, count in outcomes.items():
        assigned = units[cursor:cursor + count]
        by_code[code] = assigned
        by_unit.update({unit.id: code for unit in assigned})
        cursor += count
    return by_unit, by_code


def create_skip_log(
    db: Session,
    *,
    item: DomesticOrderItem,
    progress: DomesticItemProgress,
    units: list[DomesticItemUnit],
    source: str,
    reason: str,
    trigger_report_log_id: int | None,
    user_id: int,
    skip_mode: str | None = None,
    request_id: str | None = None,
) -> DomesticSkipLog | None:
    if not units:
        return None
    skip_log = DomesticSkipLog(
        item_id=item.id,
        progress_id=progress.id,
        skip_qty=len(units),
        source=source,
        skip_mode=skip_mode,
        reason=reason,
        trigger_report_log_id=trigger_report_log_id,
        request_id=request_id,
        created_by_user_id=user_id,
        revoked=0,
    )
    db.add(skip_log)
    db.flush()
    db.add_all([
        DomesticSkipUnit(
            skip_log_id=skip_log.id,
            unit_id=unit.id,
            progress_id=progress.id,
        )
        for unit in units
    ])
    db.flush()
    return skip_log


def skip_units(db: Session, skip_log_id: int) -> list[DomesticItemUnit]:
    return (
        db.query(DomesticItemUnit)
        .join(DomesticSkipUnit, DomesticSkipUnit.unit_id == DomesticItemUnit.id)
        .filter(DomesticSkipUnit.skip_log_id == skip_log_id)
        .order_by(DomesticItemUnit.unit_no.asc())
        .all()
    )


def assert_no_downstream_actual_work(
    db: Session,
    *,
    item: DomesticOrderItem,
    step_order: int,
    unit_ids: set[int],
) -> None:
    """阻断撤销时只看实际报工；自动/人工跳过本身不算下游工作。"""
    if not unit_ids:
        return
    rows = (
        db.query(
            DomesticItemProgress.step_order,
            Process.name,
            DomesticItemUnit.unit_no,
        )
        .join(
            DomesticReportUnit,
            DomesticReportUnit.progress_id == DomesticItemProgress.id,
        )
        .join(DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id)
        .join(DomesticItemUnit, DomesticItemUnit.id == DomesticReportUnit.unit_id)
        .join(Process, Process.id == DomesticItemProgress.process_id)
        .filter(
            DomesticItemProgress.item_id == item.id,
            DomesticItemProgress.step_order > step_order,
            DomesticReportUnit.unit_id.in_(unit_ids),
            DomesticReportLog.revoked == 0,
        )
        .order_by(
            DomesticItemProgress.step_order.asc(),
            DomesticItemUnit.unit_no.asc(),
        )
        .all()
    )
    if not rows:
        return
    earliest_order, process_name, _unit_no = rows[0]
    earliest_units = []
    seen = set()
    for row_order, _name, unit_no in rows:
        if row_order != earliest_order:
            break
        if unit_no not in seen:
            earliest_units.append(unit_no)
            seen.add(unit_no)
    codes = "、".join(
        _unit_display_code(item, unit_no) for unit_no in earliest_units[:5]
    )
    raise ValueError(
        f"下游工序“{process_name}”已有实际报工单件 {codes}，"
        "请先撤销下一道的报工（即上述最早下游工序）"
    )


def _unit_display_code(item: DomesticOrderItem, unit_no: int) -> str:
    """避免 routing_service 与 unit_service 形成模块级循环导入。"""
    return f"A{item.line_no or 1}-{unit_no:02d}"


def lock_triggered_skips(
    db: Session,
    *,
    trigger_report_log_id: int,
) -> list[DomesticSkipLog]:
    return (
        db.query(DomesticSkipLog)
        .filter(
            DomesticSkipLog.trigger_report_log_id == trigger_report_log_id,
            DomesticSkipLog.revoked == 0,
        )
        .with_for_update()
        .all()
    )


def revoke_locked_skips(rows: list[DomesticSkipLog], *, revoked_at) -> list[int]:
    for row in rows:
        row.revoked = 1
        row.revoked_at = revoked_at
    return [row.id for row in rows]


def create_decision_skips(
    db: Session,
    *,
    item: DomesticOrderItem,
    rows: list[DomesticItemProgress],
    rule: dict,
    assigned_by_code: dict[str, list[DomesticItemUnit]],
    trigger_log: DomesticReportLog,
    user_id: int,
) -> list[DomesticSkipLog]:
    progress_by_process = {row.process_id: row for row in rows}
    created = []
    for option in rule["config"]["options"]:
        units = assigned_by_code.get(option["code"], [])
        for target_process_id in dict.fromkeys(option["skip_process_ids"]):
            if target_process_id not in progress_by_process:
                continue
            skip_log = create_skip_log(
                db,
                item=item,
                progress=progress_by_process[target_process_id],
                units=units,
                source="decision",
                reason=f"分流结果：{option['label']}",
                trigger_report_log_id=trigger_log.id,
                user_id=user_id,
            )
            if skip_log:
                created.append(skip_log)
    return created
