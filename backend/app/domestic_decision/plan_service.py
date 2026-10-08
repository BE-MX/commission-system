"""Natural language only prepares a validated plan; applying it is a UI action."""
import json
import logging
import re
from datetime import timedelta
from fastapi import HTTPException
from app.ai.service import chat
from app.core.time import beijing_today
from app.domestic import constants as C
from app.domestic_decision import analytics
from app.domestic_decision.schemas import AnalysisRequest
from app.domestic_decision.scope import has_permission

logger = logging.getLogger("commission.domestic_decision")
FIELDS = {"工艺": "craft", "发色": "color", "颜色": "color", "网底色": "net_color", "尺码": "size", "尺寸": "size", "发长": "length", "长度": "length", "发量": "density", "系列": "hair_style_series", "省份": "province", "城市": "city", "来源": "customer_source", "门店类型": "store_type", "渠道": "order_channel"}


def _validate(plan, options):
    customer_ids = {row["value"] for row in options["customers"]}
    owner_ids = {row["value"] for row in options["owners"]}
    if not set(plan.customer_ids).issubset(customer_ids) or not set(plan.owner_ids).issubset(owner_ids):
        raise HTTPException(404, "查询计划包含范围外客户或人员")
    if plan.scope == "all" and not options["permissions"]["all"]:
        raise HTTPException(403, "没有全量客户范围权限")
    for field, values in plan.filters.items():
        if field not in options["dimensions"] or not set(values).issubset({row["value"] for row in options["dimensions"][field]}):
            raise HTTPException(422, "查询计划包含未注册或不可见筛选值")
    if any(field not in options["dimensions"] for field in plan.dimensions):
        raise HTTPException(422, "查询计划包含不可见维度")
    if plan.finance_related_customers and not options["permissions"]["finance"]:
        raise HTTPException(403, "没有资金阅读权限")
    return plan


def _rules(question, base, options):
    query = base.model_dump(mode="json")
    today = beijing_today()
    match = re.search(r"近\s*(\d+)\s*天", question)
    if match:
        days = int(match.group(1))
        query["end_date"] = today.isoformat()
        query["start_date"] = (today - timedelta(days=days - 1)).isoformat()
    elif "本月" in question:
        query["start_date"], query["end_date"] = today.replace(day=1).isoformat(), today.isoformat()
    if "全公司" in question or "全部业务员" in question:
        query["scope"] = "all"
    customers = [row["value"] for row in options["customers"] if row["label"] in question]
    owners = [row["value"] for row in options["owners"] if row["label"] in question]
    if customers:
        query["customer_ids"] = customers
    if owners:
        query["owner_ids"] = owners
    for field, labels in [("product_type", C.PRODUCT_TYPES), ("order_category", C.ORDER_CATEGORIES)]:
        chosen = [code for code, label in labels.items() if label in question and code in {row["value"] for row in options["dimensions"].get(field, [])}]
        if chosen:
            query["filters"][field] = chosen
    dimensions = []
    for term, field in sorted(FIELDS.items(), key=lambda item: question.find(item[0]) if item[0] in question else 10000):
        if term in question and field not in dimensions and field in options["dimensions"]:
            dimensions.append(field)
    if dimensions:
        query["dimensions"] = dimensions[:2]
    if "件数" in question or "数量" in question:
        query["metric"] = "quantity"
    elif "客户数" in question:
        query["metric"] = "customer_count"
    return AnalysisRequest.model_validate(query)


def create_plan(db, actor, base, question):
    options = analytics.filter_options(db, actor)
    finance_intent = any(word in question for word in ["充值", "余额", "欠款", "资金", "会员", "信用"])
    if finance_intent and not options["permissions"]["finance"]:
        raise HTTPException(403, "查询涉及资金，需要资金阅读权限")
    rule_plan = _validate(_rules(question, base, options), options)
    plan, source = rule_plan, "rules"
    try:
        response = chat(db, preset_name="domestic_decision_plan", messages=[{"role": "system", "content": "把用户问题转换成只读内贸分析查询计划。只输出JSON对象，只有query字段，其值严格遵守输入的query_schema。客户、人员、筛选与维度只能选输入的授权值域；不得SQL、调用工具、写数据、新增客户或输出自由文本。日期不超过查询schema上限。此处只准备计划，用户在页面检查后才应用。"}, {"role": "user", "content": json.dumps({"question": question, "today": beijing_today().isoformat(), "current_query": base.model_dump(mode="json"), "query_schema": AnalysisRequest.model_json_schema(), "authorized_options": options}, ensure_ascii=False)}], caller_module="domestic_decision", caller_user_id=actor["id"], snapshot_mode="metadata", timeout_sec=30, enforce_total_timeout=True)
        parsed = json.loads(response["content"])
        if not isinstance(parsed, dict) or set(parsed) != {"query"}:
            raise ValueError("invalid plan envelope")
        plan = _validate(AnalysisRequest.model_validate(parsed["query"]), options)
        source = "ai"
    except Exception as exc:
        logger.warning("domestic query plan fallback: %s", type(exc).__name__)
    names = {row["value"]: row["label"] for row in options["customers"]}
    descriptions = [f"{plan.start_date.isoformat()} 至 {plan.end_date.isoformat()}", "全量授权客户" if plan.scope == "all" else "本人当前客户", f"指标：{plan.metric}"]
    if plan.customer_ids:
        descriptions.append("客户：" + "、".join(names[value] for value in plan.customer_ids))
    if plan.filters:
        descriptions.append("条件：" + json.dumps(plan.filters, ensure_ascii=False))
    return {"query": plan.model_dump(mode="json"), "explanation": "；".join(descriptions), "target_tab": "finance" if finance_intent else "customers" if "复购" in question or "客户" in question else "products" if dimensions_or_product(plan) else "overview", "signals": ["repurchase_due"] if "复购" in question else [], "requires_apply": True, "notice": "请核对计划后点击应用。只读查询尚未执行；规则解析仅识别可确认的日期、客户、产品和维度。" if source == "rules" else "模型计划已通过字段、日期和值域校验；核对后应用，不执行SQL或业务变更"}, source


def dimensions_or_product(plan):
    return bool(plan.filters.get("product_type") or plan.dimensions != ["craft", "length"])
