"""Resolve report-scoped human decisions without changing OKKI source facts."""
from collections.abc import Mapping

from app.battle_report.schemas import AwardRules, OrderDecision


def _identity(value):
    return "" if value is None else str(value)


def decision_index(rules: AwardRules | Mapping | None) -> dict[str, OrderDecision]:
    """Validate persisted decisions too; never let duplicate IDs silently win."""
    records = rules.order_decisions if isinstance(rules, AwardRules) else (rules or {}).get("order_decisions", [])
    if not isinstance(records, (list, tuple)) or len(records) > 200:
        raise ValueError("订单裁定列表无效或超过200条")
    index = {}
    for record in records:
        decision = OrderDecision.model_validate(record)
        if decision.order_id in index:
            raise ValueError("订单裁定不能重复提交同一订单")
        index[decision.order_id] = decision
    return index


def resolve_order_role(row: Mapping, mark, index: Mapping[str, OrderDecision]) -> tuple[str, str | None]:
    """A stale or conflicting decision suspends metrics while retaining GMV."""
    oid = _identity(row.get("order_id"))
    decision = index.get(oid)
    suffix = "GMV保留，新签复购指标待核对"
    if decision is None:
        if mark == "是":
            return "new_sign", None
        if mark == "否":
            return "repeat", None
        return "pending", f"订单 {oid} 新成交标记为空或非法；{suffix}"

    drift = [label for field, expected, label in (
        ("order_no", decision.order_no, "订单号"),
        ("company_id", decision.company_id, "客户"),
        ("user_id", decision.owner_id, "负责人"),
    ) if _identity(row.get(field)) != expected]
    if row.get("account_date") != decision.account_date:
        drift.append("核算日期")
    if drift:
        return "pending", f"订单 {oid} 人工裁定的{'、'.join(drift)}与当前数据不一致；{suffix}"

    opposite = {"new_sign": "否", "repeat": "是"}.get(decision.role)
    if opposite is not None and mark == opposite:
        return "pending", f"订单 {oid} 人工裁定与当前新成交标记“{mark}”冲突；{suffix}"
    return decision.role, None
