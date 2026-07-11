"""售后领域纯规则：证据、赔偿口径与审核状态迁移。"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class WorkflowError(ValueError):
    """当前状态、角色或决定不允许执行。"""


VALUE_ACTIONS = {
    "free_rework",
    "replacement",
    "resend",
    "cash_refund",
    "discount",
    "order_credit",
    "freight_subsidy",
}

DYNAMIC_VIDEO_ISSUES = {"断发", "脱发", "发干打结", "产品做工"}
ACTION_CODES = {
    "explanation", "care_guidance", "return_inspection", "paid_rework", "free_rework",
    "replacement", "resend", "cash_refund", "discount", "order_credit",
    "freight_subsidy", "custom",
}


@dataclass(frozen=True)
class EvidenceEvaluation:
    score: int
    is_sufficient: bool
    missing_items: list[str]


def _money(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("赔偿成本必须是有效金额") from exc
    if amount < 0:
        raise ValueError("赔偿成本不能小于 0")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _action_cost(action: dict) -> Decimal:
    code = action.get("code")
    if code in {"cash_refund", "discount", "order_credit", "freight_subsidy"}:
        return _money(action.get("amount_usd"))
    if code == "return_inspection":
        return _money(action.get("freight_cost_usd"))
    if code == "paid_rework":
        return _money(action.get("freight_cost_usd"))
    cost = _money(action.get("estimated_cost_usd"))
    if code in {"free_rework", "resend"}:
        cost += _money(action.get("freight_cost_usd"))
    return cost


def classify_compensation(actions: list[dict]) -> tuple[bool, Decimal]:
    """按措施经济实质计算赔偿标记与统一 USD 估算成本。"""
    has_compensation = False
    total = Decimal("0.00")
    for action in actions:
        code = action.get("code")
        is_compensation = code in VALUE_ACTIONS
        if code == "return_inspection":
            is_compensation = action.get("freight_payer") == "company"
        elif code == "paid_rework":
            is_compensation = action.get("freight_payer") == "company"
        elif code == "custom":
            is_compensation = bool(action.get("company_bears_cost"))
        if is_compensation:
            has_compensation = True
            total += _action_cost(action)
    return has_compensation, total.quantize(Decimal("0.01"))


def validate_actions(actions: list[dict]) -> None:
    """校验审批所需的执行细节，避免只批准一个空泛措施名称。"""
    if not actions:
        raise ValueError("至少选择一项处理措施")

    def text(action: dict, field: str, label: str) -> str:
        value = str(action.get(field) or "").strip()
        if not value:
            raise ValueError(f"{label}不能为空")
        return value

    def positive(action: dict, field: str, label: str) -> Decimal:
        value = _money(action.get(field))
        if value <= 0:
            raise ValueError(f"{label}必须大于 0")
        return value

    for action in actions:
        code = action.get("code")
        if code not in ACTION_CODES:
            raise ValueError(f"未知处理措施：{code}")
        if code == "care_guidance":
            text(action, "care_plan", "护理方案")
        elif code == "return_inspection":
            text(action, "return_address", "退回地址")
            payer = text(action, "freight_payer", "运费承担方")
            if payer not in {"customer", "company"}:
                raise ValueError("运费承担方无效")
            text(action, "expected_completion_date", "预计完成日")
            if payer == "company":
                positive(action, "freight_cost_usd", "公司承担运费")
        elif code == "paid_rework":
            positive(action, "service_fee_usd", "二次处理费")
            payer = text(action, "freight_payer", "运费承担方")
            if payer == "company":
                positive(action, "freight_cost_usd", "公司承担运费")
        elif code == "free_rework":
            positive(action, "estimated_cost_usd", "二次处理估算成本")
            if "freight_cost_usd" not in action:
                raise ValueError("请填写二次处理运费")
            _money(action.get("freight_cost_usd"))
        elif code in {"replacement", "resend"}:
            positive(action, "quantity", "换货/补发数量")
            text(action, "product", "换货/补发产品")
            positive(action, "estimated_cost_usd", "换货/补发估算成本")
            if code == "resend":
                if "freight_cost_usd" not in action:
                    raise ValueError("请填写补发运费")
                _money(action.get("freight_cost_usd"))
            text(action, "delivery_date", "预计交付日期")
        elif code == "cash_refund":
            positive(action, "amount_usd", "退款金额")
            text(action, "currency", "退款币种")
        elif code == "discount":
            if _money(action.get("amount_usd")) <= 0 and _money(action.get("discount_percent")) <= 0:
                raise ValueError("折扣比例或折扣金额必须大于 0")
            text(action, "applicable_order", "折扣适用订单")
        elif code == "order_credit":
            positive(action, "amount_usd", "抵扣金额")
            text(action, "expiry_date", "抵扣有效期")
        elif code == "freight_subsidy":
            positive(action, "amount_usd", "运费补贴金额")
            text(action, "currency", "运费补贴币种")
        elif code == "custom":
            text(action, "description", "自定义措施说明")
            if action.get("company_bears_cost"):
                positive(action, "estimated_cost_usd", "自定义措施估算成本")


def evaluate_evidence(
    issue_type: str,
    batch_no: str | None,
    care_note: str | None,
    evidence: list[dict],
) -> EvidenceEvaluation:
    """依据问题类型计算证据完整度，返回可解释的缺失项。"""
    present = {item.get("evidence_type") for item in evidence}
    requirements = [
        ("问题全景图", "overview_image" in present, 25),
        ("问题近景图", "closeup_image" in present, 25),
        ("安装/护理/存储说明", len((care_note or "").strip()) >= 20, 25),
    ]
    if issue_type in DYNAMIC_VIDEO_ISSUES:
        requirements.append(("问题视频", "video" in present, 15))
    if (batch_no or "").strip() and (batch_no or "").strip() != "未知":
        requirements.append(("包装/批次标签", "batch_label" in present, 10))

    missing_items = [label for label, satisfied, _ in requirements if not satisfied]
    possible = sum(weight for _, _, weight in requirements)
    earned = sum(weight for _, satisfied, weight in requirements if satisfied)
    score = round(earned * 100 / possible) if possible else 0
    return EvidenceEvaluation(
        score=score,
        is_sufficient=not missing_items,
        missing_items=missing_items,
    )


def next_status(
    current_status: str,
    actor_role: str,
    decision: str,
    has_compensation: bool,
) -> str:
    """计算审核决定后的状态，不允许跨角色或绕过赔偿终审。"""
    if decision not in {"approve", "return", "reject"}:
        raise WorkflowError("未知审核决定")

    expected_role = {
        "awaiting_supervisor": "supervisor",
        "awaiting_director": "director",
    }.get(current_status)
    if expected_role is None or actor_role != expected_role:
        raise WorkflowError("当前用户不能审核此状态的售后单")
    if current_status == "awaiting_director" and not has_compensation:
        raise WorkflowError("非赔偿单不得进入销售总监终审")
    if decision == "return":
        return "returned"
    if decision == "reject":
        return "rejected"
    if current_status == "awaiting_supervisor" and has_compensation:
        return "awaiting_director"
    return "approved"
