"""Model output selects registered evidence and hypotheses, never supplies facts."""
from app.domestic_decision.models import DecisionConfig


def registered_hypotheses(db):
    row = db.query(DecisionConfig).filter(DecisionConfig.key == "ai_hypothesis_options").first()
    return row.value if row and isinstance(row.value, list) else []


def anonymous_facts(facts, customers):
    # Only the model selection contract travels to the provider. Enriched
    # browser fields can contain names or future operational metadata.
    safe = [{key: item[key] for key in ("fact_id", "rule_key", "title", "explanation", "next_step", "evidence_refs") if key in item} for item in facts]
    names = sorted([(row["shop_name"], f"客户匿名标识{row['customer_id']}") for row in customers if row.get("shop_name")], key=lambda pair: len(pair[0]), reverse=True)
    for item in safe:
        for key in ("title", "explanation", "next_step"):
            if isinstance(item.get(key), str):
                for name, alias in names:
                    item[key] = item[key].replace(name, alias)
    return safe


def validate_suggestions(parsed, facts, options):
    if not isinstance(parsed, dict) or set(parsed) != {"suggestions"}:
        raise ValueError("invalid AI envelope")
    suggestions = parsed["suggestions"]
    if not isinstance(suggestions, list) or len(suggestions) > 3:
        raise ValueError("invalid AI suggestions")
    labels = {option["code"]: option["label"] for option in options}
    seen, result = set(), []
    for item in suggestions:
        if not isinstance(item, dict) or set(item) != {"fact_id", "hypothesis_code", "alternative_code"}:
            raise ValueError("AI free text is not an accepted fact")
        index = item["fact_id"]
        if type(index) is not int or not 0 <= index < len(facts) or index in seen:
            raise ValueError("invalid evidence reference")
        if item["hypothesis_code"] not in labels or item["alternative_code"] not in labels:
            raise ValueError("unregistered hypothesis")
        seen.add(index)
        result.append({"fact_id": index, "hypothesis": labels[item["hypothesis_code"]], "alternative_explanation": labels[item["alternative_code"]], "next_step": facts[index]["next_step"], "evidence_refs": facts[index]["evidence_refs"], "requires_finance": facts[index].get("requires_finance", False)})
    return result
