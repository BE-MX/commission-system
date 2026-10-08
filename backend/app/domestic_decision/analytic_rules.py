"""Rules report observable gaps with evidence, never guessed probabilities."""


def build_insights(customers, dimensions, quality, config, finance=None):
    result = []
    def add(key, customer_id, title, explanation, evidence, confidence, next_step):
        result.append({"rule_key": key, "customer_id": customer_id, "title": title, "explanation": explanation,
                       "evidence_refs": evidence, "confidence": confidence, "next_step": next_step,
                       "rule_version": config["rule_version"]})
    for row in customers:
        history = row["history"]
        contact_eligible = row["status"] != 0 and row["lifecycle_status"] not in config["inactive_lifecycle_statuses"]
        if contact_eligible:
            registered = set()
            for recommendation in row.get("recommendations", []):
                key = recommendation["rule_key"]
                if key not in ("own_repeat_combination", "own_half_year_change") or key in registered:
                    continue
                registered.add(key)
                add(key, row["customer_id"], recommendation["title"], recommendation["explanation"], recommendation["evidence_refs"], recommendation["confidence"], recommendation["next_step"])
                result[-1]["source"] = "server_computed_customer_recommendation"
                result[-1]["inventory_delivery"] = recommendation.get("inventory_delivery", "unknown")
        if row.get("risk_candidate", True) and history["cycle_status"] in ("repurchase_window", "delayed", "demand_check"):
            if not contact_eligible:
                continue
            cycle_label = "同群参考周期" if history.get("cycle_basis") == "peer_reference" else "最近购买日正间隔中位数"
            explanation = f"距上次商业购买 {history['recency_days']} 天，{cycle_label} {history['cycle_days']} 天；本期订单 {row['order_count']} 单。"
            if not history["history_complete"]:
                explanation += "完整历史起点尚未确认，仅为系统记录线索。"
            add("repurchase_due", row["customer_id"], f"{row['shop_name']}进入复购观察窗口", explanation,
                history["evidence_refs"][-7:], "medium" if history["history_complete"] else "limited",
                "核对未交付订单与门店当前需求，再安排联系")
    for difference in quality["order_reconciliation"]:
        add("order_reconciliation", None, "订单主表与明细金额需核对",
            f"订单 {difference['order_id']} 主表 {difference['header_amount']} 元，明细 {difference['item_amount']} 元，差额 {difference['difference']} 元。",
            [{"type": "orders", "id": difference["order_id"]}], "high", "核对原订单金额与有效明细，不以差额推断利润")
    for field, coverage in quality["dimension_coverage"].items():
        if coverage["rate"] is not None and not coverage["strong_advice_enabled"]:
            add("low_dimension_coverage", None, f"{field}结构化覆盖不足",
                f"适用明细 {coverage['applicable_count']} 行，已知 {coverage['known_count']} 行，记录覆盖率 {coverage['rate']:.1%}；展示指标加权后的有效覆盖率 " + (f"{coverage['effective_coverage']:.1%}。" if coverage['effective_coverage'] is not None else "不可核验。"),
                [], "high", "补齐或人工审核映射后再判断该维度需求变化")
    amount = sum(r["amount"] for r in customers)
    if amount > 0 and customers:
        top = max(customers, key=lambda r: r["amount"])
        share = top["amount"] / amount
        if share >= 0.5:
            add("customer_concentration", top["customer_id"], "订单需求集中于单一客户",
                f"{top['shop_name']}贡献当前订单额 {share:.1%}，公司客户样本不能代表全行业市场。",
                top["history"]["evidence_refs"][-5:], "high", "核对集中采购背景，并观察其他客户是否同向变化")
    for field, rows in dimensions.items():
        eligible = quality["dimension_coverage"].get(field, {}).get("strong_advice_enabled", False)
        for row in rows:
            if eligible and config.get("trend_comparison_complete") and row["customer_count"] >= 3 and row["amount_change"]["rate"] is not None and row["amount_change"]["rate"] >= 0.2:
                add("observed_product_growth", None, f"{row['label']}成交需求增加",
                    f"匹配产品金额由 {row['previous_amount']} 元变为 {row['amount']} 元，当前涉及 {row['customer_count']} 客户。仅为本公司观察样本。",
                    row["evidence_refs"][:6], "medium", "核对客户采购背景、库存与交期，不据此确定采购量")
    if finance:
        finance_insight_start = len(result)
        by_id = {r["customer_id"]: r for r in customers}
        for row in finance["customers"]:
            if not row["reliable"]:
                add("finance_reconciliation", row["customer_id"], f"{row['shop_name']}资金待核对",
                    f"账户桥接发现 {len(row['anomalies'])} 项缺口或差异，暂停余额预测。",
                    row["evidence_refs"][:6], "high", "核对账本连续性和期初余额")
                continue
            if row["pending_recharge_count"]:
                add("pending_recharge_review", row["customer_id"], f"{row['shop_name']}有充值待审",
                    f"待审 {row['pending_recharge_count']} 笔，申请额 {row['pending_recharge_amount']} 元，未计入已入账充值。",
                    [{"type": "requests", "id": r["id"]} for r in finance["requests"] if r["customer_id"] == row["customer_id"] and r["status"] == "pending"],
                    "high", "先核对待审核申请处理进度，避免重复补款")
            customer = by_id.get(row["customer_id"])
            recency = customer["history"]["recency_days"] if customer else None
            if customer and customer["status"] != 0 and customer["lifecycle_status"] not in config["inactive_lifecycle_statuses"] and not row["pending_recharge_count"] and row["coverage_status"] == "available" and row["coverage_days"] < 14 and customer["history"]["cycle_status"] in ("repurchase_window", "delayed", "demand_check"):
                add("low_balance_observation", row["customer_id"], f"{row['shop_name']}需核对补款需求",
                    f"可靠正余额按最近90天商业扣款毛额估算覆盖 {row['coverage_days']} 天，且进入复购观察窗口；只是需求核对线索。",
                    row["evidence_refs"][-6:], "medium", "先核对下一次订单、未交付情况与实际补款安排")
            if row["positive_balance"] and recency is not None and recency >= config["dormant_days"] and customer and customer["status"] != 0 and customer["lifecycle_status"] not in config["inactive_lifecycle_statuses"]:
                add("idle_balance", row["customer_id"], f"{row['shop_name']}有未使用余额",
                    f"期末正余额 {row['positive_balance']} 元，系统记录距上次商业购买 {recency} 天。",
                    row["evidence_refs"][-5:], "medium" if config["coverage_start"] else "limited", "了解经营计划和产品需求，不自动发起充值")
            if row["debt"] and row["settle_mode"] == "credit":
                add("credit_account_check", row["customer_id"], f"{row['shop_name']}有账户欠款",
                    f"截止时点账户欠款 {row['debt']} 元；缺少账期与逐笔核销证据，不能认定逾期。",
                    row["evidence_refs"][-5:], "high", "由业务与财务核对账户和约定付款安排")
                months = row["monthly_balances"]
                if len(months) == 3 and all(month["debt"] is not None for month in months) and months[0]["debt"] < months[1]["debt"] < months[2]["debt"]:
                    add("credit_debt_growth", row["customer_id"], f"{row['shop_name']}账户欠款连续扩大",
                        "连续完整月末欠款为 " + "、".join(f"{month['month']} {month['debt']} 元" for month in months) + "；无约定账期证据，不认定逾期。",
                        [{"type": "ledger", "id": month["ledger_id"]} for month in months], "high", "业务与财务共同核对扣款、补款和付款计划")
            if row["manual_adjustment_count_30d"] >= 3:
                add("frequent_manual_adjustments", row["customer_id"], f"{row['shop_name']}资金调整需内部核对",
                    f"最近30天人工余额调整 {row['manual_adjustment_count_30d']} 次；频次不等于欺诈证据。",
                    row["evidence_refs"][-6:], "high", "内部核对调整原因与账务凭据")
            if row["recharge_cycle_days"] and row["recharge_recency_days"] > 1.5 * row["recharge_cycle_days"] and not row["pending_recharge_count"] and customer and customer["status"] != 0 and customer["lifecycle_status"] not in config["inactive_lifecycle_statuses"]:
                add("recharge_rhythm_change", row["customer_id"], f"{row['shop_name']}充值节奏发生变化",
                    f"距上次已入账充值 {row['recharge_recency_days']} 天，最近充值日中位间隔 {row['recharge_cycle_days']} 天；余额与购买需求需一起核对。",
                    row["evidence_refs"][-6:], "medium", "了解需求与资金计划，余额较高时优先谈需求而非再次充值")
        for insight in result[finance_insight_start:]:
            insight["requires_finance"] = True
    return result
