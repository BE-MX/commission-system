"""内贸条件路线规则的校验、持久化与读取。"""

import re

from sqlalchemy.orm import Session

from app.domestic.models import DomesticRouteRule
from app.production.models import Process, ProcessRoute, ProcessRouteStep


RULE_REQUIRED = "required"
RULE_DECISION = "decision"
RULE_OPTIONAL = "optional"

_STORED_RULE_TYPES = {RULE_DECISION, RULE_OPTIONAL}
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _route_context(db: Session, route_id: int):
    route = db.query(ProcessRoute).filter(
        ProcessRoute.id == route_id,
        ProcessRoute.status == 1,
    ).first()
    if route is None:
        raise ValueError("路线不存在或已停用")

    rows = (
        db.query(ProcessRouteStep, Process)
        .join(Process, Process.id == ProcessRouteStep.process_id)
        .filter(ProcessRouteStep.route_id == route_id)
        .order_by(ProcessRouteStep.step_order.asc())
        .all()
    )
    step_by_process = {step.process_id: step for step, _process in rows}
    process_by_id = {process.id: process for _step, process in rows}
    return step_by_process, process_by_id


def validate_rules(db: Session, route_id: int, rules: list[dict]) -> None:
    """校验一组将全量覆盖保存的非默认规则。"""

    step_by_process, process_by_id = _route_context(db, route_id)
    seen_process_ids: set[int] = set()

    for rule in rules:
        process_id = rule.get("process_id")
        if process_id in seen_process_ids:
            raise ValueError("同一工序只能配置一条规则")
        seen_process_ids.add(process_id)

        if process_id not in step_by_process:
            raise ValueError("工序不属于该路线")
        if process_by_id[process_id].status != 1:
            raise ValueError("工序不存在或已停用")

        rule_type = rule.get("rule_type")
        if rule_type not in _STORED_RULE_TYPES:
            raise ValueError("不支持的规则类型")

        config = rule.get("config")
        if rule_type == RULE_OPTIONAL:
            if config is not None:
                raise ValueError("可选工序不能配置结果选项")
            continue

        options = config.get("options") if isinstance(config, dict) else None
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError("分流判定至少需要两个结果选项")

        codes: set[str] = set()
        trigger_order = step_by_process[process_id].step_order
        for option in options:
            code = option.get("code") if isinstance(option, dict) else None
            if not isinstance(code, str) or _CODE_PATTERN.fullmatch(code) is None:
                raise ValueError("结果编码格式不合法")
            if code in codes:
                raise ValueError("结果编码不能重复")
            codes.add(code)

            label = option.get("label")
            if not isinstance(label, str) or not label.strip():
                raise ValueError("结果名称不能为空")

            targets = option.get("skip_process_ids")
            if not isinstance(targets, list):
                raise ValueError("跳过目标必须是工序 ID 列表")
            for target_id in targets:
                if target_id not in step_by_process:
                    raise ValueError("跳过目标不属于该路线")
                if process_by_id[target_id].status != 1:
                    raise ValueError("跳过目标工序不存在或已停用")
                if step_by_process[target_id].step_order <= trigger_order:
                    raise ValueError("跳过目标必须位于触发工序之后")


def _normalized_config(rule: dict):
    if rule["rule_type"] == RULE_OPTIONAL:
        return None
    return {
        "options": [{
            "code": option["code"],
            "label": option["label"].strip(),
            "skip_process_ids": list(option["skip_process_ids"]),
        } for option in rule["config"]["options"]],
    }


def list_rules(db: Session, route_id: int) -> list[dict]:
    """按路线步骤顺序返回规则，并派生可信的目标工序名称。"""

    step_by_process, process_by_id = _route_context(db, route_id)
    rows = (
        db.query(DomesticRouteRule)
        .filter(DomesticRouteRule.route_id == route_id)
        .all()
    )
    rows = [row for row in rows if row.process_id in step_by_process]
    rows.sort(key=lambda row: step_by_process[row.process_id].step_order)

    result = []
    for row in rows:
        config = None
        if row.rule_type == RULE_DECISION:
            config = {"options": []}
            for option in row.config_json["options"]:
                target_ids = [
                    target_id
                    for target_id in option["skip_process_ids"]
                    if target_id in step_by_process
                ]
                config["options"].append({
                    "code": option["code"],
                    "label": option["label"],
                    "skip_process_ids": target_ids,
                    "skip_processes": [
                        {"id": target_id, "name": process_by_id[target_id].name}
                        for target_id in target_ids
                    ],
                })
        result.append({
            "process_id": row.process_id,
            "process_name": process_by_id[row.process_id].name,
            "step_order": step_by_process[row.process_id].step_order,
            "rule_type": row.rule_type,
            "config": config,
        })
    return result


def rule_map(db: Session, route_id: int) -> dict[int, dict]:
    return {rule["process_id"]: rule for rule in list_rules(db, route_id)}


def save_rules(db: Session, route_id: int, rules: list[dict]) -> list[dict]:
    """全量覆盖路线规则；调用方负责提交或回滚事务。"""

    validate_rules(db, route_id, rules)
    db.query(DomesticRouteRule).filter(
        DomesticRouteRule.route_id == route_id,
    ).delete(synchronize_session=False)
    for rule in rules:
        db.add(DomesticRouteRule(
            route_id=route_id,
            process_id=rule["process_id"],
            rule_type=rule["rule_type"],
            config_json=_normalized_config(rule),
        ))
    db.flush()
    return list_rules(db, route_id)
