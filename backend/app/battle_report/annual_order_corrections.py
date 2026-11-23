"""Owner-verified historical OKKI corrections, read-only and report-specific."""
from datetime import date


# Keep raw company_id intact: these are order corrections, not customer merges.
PAN_OWNER = "55296478"
JOHN_COMPANY = "101592033446449"
PAN_CORRECTIONS = {
    "100348581118834": ("Pan260611", date(2026, 6, 16), "12536643201371", JOHN_COMPANY, "John Watkins", "new_sign"),
    "105647122909622": ("Pan260717", date(2026, 7, 23), "12536643201371", JOHN_COMPANY, "John Watkins", "repeat"),
    "98809111290128": ("Pan 260605", date(2026, 6, 5), "89639526739793", "89639526739793", "Kaelyn Hawley", "new_sign"),
}


def applies(report):
    return (getattr(report, "id", None) == 2 and report.award_kind == "annual_repurchase"
            and report.start_date == date(2026, 1, 1) and report.end_date == date(2026, 12, 31))


def correct_order(report, row):
    """Return an override or fail closed on identity drift; mutate only a copied row."""
    if not applies(report) or row.get("source_type", "okki") != "okki":
        return None, None
    oid = str(row.get("order_id") or "")
    correction = PAN_CORRECTIONS.get(oid)
    if correction is None:
        return None, None
    order_no, day, original, target, name, role = correction
    if (row.get("order_no") != order_no or row.get("account_date") != day
            or str(row.get("user_id")) != PAN_OWNER
            or str(row.get("company_id")) not in {original, target}):
        return "pending", f"订单 {oid} 年度历史裁定身份与当前数据不一致；GMV保留，新签复购指标待核对"
    row.update(cohort_company_id=target, company_name=name)
    return role, None


def linked_customer_scope(report, params, schema):
    """Load John's later transferred orders only when a verified Pan order anchors him."""
    if not applies(report):
        return ""
    anchors = []
    params.update(pan_owner=PAN_OWNER, pan_target=JOHN_COMPANY)
    for index, (oid, correction) in enumerate(PAN_CORRECTIONS.items()):
        order_no, day, original, target, _, _ = correction
        if target != JOHN_COMPANY:
            continue
        prefix = f"pan_{index}"
        params.update({f"{prefix}_id": oid, f"{prefix}_no": order_no,
                       f"{prefix}_day": day, f"{prefix}_original": original})
        anchors.append(f"""(s.order_id = :{prefix}_id AND s.order_no = :{prefix}_no
            AND s.account_date = :{prefix}_day
            AND s.company_id IN (:{prefix}_original, :pan_target))""")
    return f"""OR (o.company_id = :pan_target AND EXISTS (
        SELECT 1 FROM `{schema}`.okki_orders s
        WHERE s.user_id = :pan_owner AND s.user_id IN :users
          AND s.account_date BETWEEN :start AND :end
          AND ({' OR '.join(anchors)})
    ))"""
