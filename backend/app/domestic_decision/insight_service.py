"""Attach an auditable contract to program-computed rules and recommendations."""
import hashlib
import json


def enrich(result):
    meta = result["meta"]
    customers = result.get("customers", [result["customer"]] if "customer" in result else [])
    owner = {row["customer_id"]: row.get("owner_user_id") for row in customers}
    quality = result.get("quality", {})
    rates = [row.get("effective_coverage", row["rate"]) for row in quality.get("dimension_coverage", {}).values() if row.get("effective_coverage", row["rate"]) is not None]
    coverage = min(rates) if rates else 0
    customer_count = result.get("summary", {}).get("customer_count", len(customers))
    anomalies = quality.get("order_reconciliation_count", 0) + quality.get("ledger_anomaly_count", 0)
    grade = "high" if not anomalies and coverage >= 0.95 and customer_count >= 30 else "medium" if not anomalies and coverage >= 0.8 and customer_count >= 10 else "low"
    for insight in result.get("insights", []):
        key = {"rule": insight["rule_key"], "customer": insight.get("customer_id"), "period": meta["period"], "data_version": meta["data_version"], "evidence": insight["evidence_refs"]}
        insight.update({
            "insight_id": hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24],
            "category": "finance" if insight.get("requires_finance") else "customer" if insight.get("customer_id") is not None else "product_quality",
            "scope": meta["scope_summary"], "period": meta["period"],
            "facts": [{"description": insight["explanation"], "evidence_refs": insight["evidence_refs"]}],
            "hypotheses": [], "alternative_explanations": [],
            "recommended_action": insight["next_step"], "owner": owner.get(insight.get("customer_id")),
            "due_hint": "核对证据后安排内部跟进", "evidence_grade": "individual" if insight.get("customer_id") is not None else grade,
            "limitations": meta.get("warnings", []), "metric_version": meta["metric_version"],
            "rule_version": meta["rule_version"], "data_version": meta["data_version"], "generated_at": meta["data_as_of"],
        })
    return result
