"""AI extraction and deterministic resolution for OKKI order screenshots."""

import re
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import ArkUserExternalBinding
from app.invoice import delegation_service, import_service, product_service
from app.invoice.models import Invoice
from app.invoice.schemas import ScreenshotExtraction, ScreenshotResolveRequest
from app.invoice.screenshot_ai import extract_screenshot
from app.invoice.screenshot_token import issue_preview_token


def recognize_preview(
    db: Session,
    *,
    image_bytes: bytes,
    content_type: str,
    order_type: str,
    actor_user_id: int,
) -> dict:
    extraction, source_hash = extract_screenshot(
        db, image_bytes=image_bytes, content_type=content_type, actor_user_id=actor_user_id,
    )
    request = ScreenshotResolveRequest(
        extraction=extraction,
        source_image_sha256=source_hash,
        order_type=order_type,
    )
    return resolve_preview(db, request=request, actor_user_id=actor_user_id)


def resolve_preview(db: Session, *, request: ScreenshotResolveRequest, actor_user_id: int) -> dict:
    extraction = request.extraction
    warnings: list[str] = []
    blockers: list[str] = []

    customer_match = _resolve_customer(db, extraction.customer_name, request.customer_id)
    if customer_match["status"] != "matched":
        blockers.append("客户未唯一匹配，请选择正确客户")

    sales_match = _resolve_sales_user(
        db, actor_user_id, extraction.salesperson_name, request.sales_user_id,
    )
    if sales_match["status"] != "matched":
        blockers.append("业务员未唯一匹配，或当前用户没有代创建权限")

    import_preview = None
    if customer_match.get("selected") and extraction.items:
        raw_rows = [_to_import_row(item) for item in extraction.items]
        try:
            import_preview = import_service.preview_import(
                db,
                customer_id=str(customer_match["selected"]["company_id"]),
                order_type=request.order_type,
                currency=extraction.currency or "USD",
                raw_rows=raw_rows,
            )
            _apply_product_selections(
                import_preview,
                request.product_selections,
                set(request.custom_rows),
            )
        except ValueError as exc:
            blockers.append(str(exc))
    elif not extraction.items:
        blockers.append("截图中未识别到产品明细")

    if import_preview:
        for row in import_preview["rows"]:
            if row["status"] == "blocked":
                blockers.extend(row.get("errors") or [f"第 {row['source_row']} 行产品未匹配"])
            warnings.extend(row.get("warnings") or [])

    totals = _validate_totals(extraction)
    blockers.extend(totals["blockers"])
    warnings.extend(totals["warnings"])

    fees = _resolve_fees(extraction)
    blockers.extend(fees.pop("blockers"))
    warnings.extend(fees.pop("warnings"))

    source_order = _match_source_order(
        db,
        extraction=extraction,
        customer=customer_match.get("selected"),
        sales_user=sales_match.get("selected"),
    )
    if source_order.get("duplicate_invoice"):
        blockers.append(
            f"OKKI 订单 {source_order.get('order_no') or source_order.get('order_id')} 已导入发票"
        )
    if source_order["status"] == "ambiguous":
        blockers.append("匹配到多张可能的 OKKI 来源订单，请稍后等待订单同步完整或人工核对")
    elif source_order["status"] == "name_mismatch":
        blockers.append("唯一候选 OKKI 订单的订单名称与截图不一致，请核对或重新识别")
    elif source_order["status"] == "missing":
        if source_order.get("reason") == "non_usd_amount_unavailable":
            warnings.append("非 USD 订单缺少原币金额投影，不自动关联 OKKI 来源订单；将仅用截图指纹去重")
        else:
            warnings.append("业务库暂未同步到这张 OKKI 订单；将仅用截图指纹防止原图重复导入")

    existing_hash = db.query(Invoice.id, Invoice.invoice_no).filter(
        Invoice.source_type == "okki_screenshot",
        Invoice.source_image_sha256 == request.source_image_sha256,
    ).first()
    if existing_hash:
        blockers.append(f"这张截图已创建发票 {existing_hash.invoice_no}")

    invoice_patch = _build_invoice_patch(
        extraction=extraction,
        order_type=request.order_type,
        customer=customer_match.get("selected"),
        sales_user=sales_match.get("selected"),
        import_preview=import_preview,
        source_order=source_order,
        source_hash=request.source_image_sha256,
        fees=fees,
    )
    deduped_blockers = list(dict.fromkeys(blockers))
    deduped_warnings = list(dict.fromkeys(warnings))
    ready = not deduped_blockers
    preview_token = None
    if ready and invoice_patch:
        preview_token = issue_preview_token(
            actor_user_id=actor_user_id,
            invoice_patch=invoice_patch,
            expected_total=extraction.order_amount,
        )
        invoice_patch["source_preview_token"] = preview_token
    return {
        "ready": ready,
        "preview_token": preview_token,
        "source_image_sha256": request.source_image_sha256,
        "order_type": request.order_type,
        "extraction": extraction.model_dump(mode="json"),
        "customer_match": customer_match,
        "sales_match": sales_match,
        "source_order": source_order,
        "import_preview": import_preview,
        "totals": totals["data"],
        "fees": fees,
        "warnings": deduped_warnings,
        "blockers": deduped_blockers,
        "invoice_patch": invoice_patch,
    }


def _resolve_customer(db: Session, name: str | None, selected_id: str | None) -> dict:
    if selected_id:
        candidates = product_service.search_customers(db, keyword=str(selected_id), limit=10)
        exact = [row for row in candidates if str(row["company_id"]) == str(selected_id)]
        return _match_payload(exact, candidates)
    normalized = _norm(name)
    if not normalized:
        return _match_payload([], [])
    candidates = product_service.search_customers(db, keyword=str(name), limit=20)
    exact = [row for row in candidates if _norm(row.get("company_name")) == normalized]
    return _match_payload(exact, candidates)


def _resolve_sales_user(
    db: Session, actor_user_id: int, name: str | None, selected_id: int | None,
) -> dict:
    allowed = delegation_service.list_assignees(db, actor_user_id)
    eligible = [row for row in allowed if row.get("okki_bound")]
    allowed_ids = {int(row["id"]) for row in eligible}
    if selected_id:
        selected = [row for row in eligible if int(row["id"]) == int(selected_id)]
        return _match_payload(selected, eligible)
    bindings = db.query(ArkUserExternalBinding).filter(
        ArkUserExternalBinding.ark_user_id.in_(allowed_ids),
        ArkUserExternalBinding.provider == "okki",
        ArkUserExternalBinding.binding_status == "active",
        ArkUserExternalBinding.deleted_at.is_(None),
    ).all() if allowed_ids else []
    names: dict[int, set[str]] = {int(row["id"]): {
        _norm(row.get("username")), _norm(row.get("real_name")),
    } for row in eligible}
    for binding in bindings:
        names.setdefault(int(binding.ark_user_id), set()).add(_norm(binding.external_display_name))
    wanted = _norm(name)
    matched = [row for row in eligible if wanted and wanted in names.get(int(row["id"]), set())]
    return _match_payload(matched, eligible)


def _match_payload(exact: list[dict], candidates: list[dict]) -> dict:
    selected = exact[0] if len(exact) == 1 else None
    return {
        "status": "matched" if selected else ("ambiguous" if len(candidates) > 1 else "missing"),
        "selected": selected,
        "candidates": candidates,
    }


def _to_import_row(item) -> dict:
    full_name = str(item.product_name or "").strip()
    display = str(item.product_display or "").strip() or full_name.split("/", 1)[0].strip()
    return {
        "source_row": item.source_row,
        "product_no": item.product_no,
        "product": display,
        "length": item.length,
        "color": item.color,
        "weight": item.weight,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
    }


def _apply_product_selections(preview: dict, selections, custom_rows: set[int]) -> None:
    selected = {item.source_row: (item.product_id, item.sku_id) for item in selections}
    for row in preview["rows"]:
        source_row = row["source_row"]
        if source_row in custom_rows and row.get("can_create_custom"):
            row["matched_product"] = None
            row["errors"] = []
            row["use_custom"] = True
        elif source_row in selected:
            pair = selected[source_row]
            candidate = next((item for item in row.get("candidates", []) if (
                int(item["product_id"]), int(item["sku_id"] or 0)
            ) == pair), None)
            if candidate:
                row["matched_product"] = candidate
                row["errors"] = []
        row["status"] = "blocked" if row.get("errors") else ("warning" if row.get("warnings") else "passed")
    preview["summary"] = {key: sum(row["status"] == key for row in preview["rows"])
                          for key in ("passed", "warning", "blocked")}
    preview["summary"]["total"] = len(preview["rows"])


def _validate_totals(extraction: ScreenshotExtraction) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    calculated = Decimal("0")
    visible_subtotals = Decimal("0")
    for item in extraction.items:
        if item.quantity is None or item.unit_price is None:
            blockers.append(f"第 {item.source_row} 行缺少数量或单价")
            continue
        line_total = _money(Decimal(item.quantity) * item.unit_price)
        calculated += line_total
        if item.subtotal is not None:
            visible_subtotals += _money(item.subtotal)
            if abs(line_total - _money(item.subtotal)) > Decimal("0.01"):
                blockers.append(f"第 {item.source_row} 行单价×数量与截图小计不一致")
        else:
            warnings.append(f"第 {item.source_row} 行未识别到小计，已按单价×数量计算")
    product_amount = extraction.product_amount
    if product_amount is not None and abs(_money(calculated) - _money(product_amount)) > Decimal("0.01"):
        blockers.append("产品明细合计与截图产品总金额不一致")
    fees = extraction.additional_fee_amount or Decimal("0")
    expected_total = _money(calculated + fees)
    if extraction.order_amount is not None and abs(expected_total - _money(extraction.order_amount)) > Decimal("0.01"):
        blockers.append("产品合计加附加费用与截图订单金额不一致")
    if extraction.order_amount is None:
        blockers.append("未识别到订单总金额")
    return {
        "blockers": blockers,
        "warnings": warnings,
        "data": {
            "calculated_product_amount": str(_money(calculated)),
            "visible_subtotal_amount": str(_money(visible_subtotals)),
            "recognized_product_amount": str(product_amount) if product_amount is not None else None,
            "recognized_order_amount": str(extraction.order_amount) if extraction.order_amount is not None else None,
            "difference": str(_money(expected_total - (extraction.order_amount or expected_total))),
        },
    }


def _resolve_fees(extraction: ScreenshotExtraction) -> dict:
    fee = extraction.additional_fee_amount
    if fee is None:
        return {
            "shipping_fee": 0, "packaging_fee": 0, "handling_fee": 0,
            "blockers": [], "warnings": ["未识别到附加费用，费用字段暂按 0 预填，请人工确认"],
        }
    if _money(fee) != Decimal("0.00"):
        return {
            "shipping_fee": 0, "packaging_fee": 0, "handling_fee": 0,
            "blockers": ["截图只有附加费用总额，无法安全拆分包装费、运费和手续费"],
            "warnings": [],
        }
    return {
        "shipping_fee": 0, "packaging_fee": 0, "handling_fee": 0,
        "blockers": [], "warnings": [],
    }


def _match_source_order(db: Session, *, extraction, customer, sales_user) -> dict:
    if not customer or not extraction.order_date or extraction.order_amount is None:
        return {"status": "missing", "candidates": [], "duplicate_invoice": False}
    if str(extraction.currency or "USD").upper() != "USD":
        return {
            "status": "missing",
            "reason": "non_usd_amount_unavailable",
            "candidates": [],
            "duplicate_invoice": False,
        }
    schema = product_service._schema()
    order_columns = product_service._table_columns(db, "okki_orders")
    has_name_column = "name" in order_columns
    name_expr = "name" if has_name_column else "NULL"
    rows = db.execute(text(f"""
        SELECT order_id, order_no, {name_expr} AS name,
               company_id, amount_usd, account_date,
               user_id, status_name
        FROM `{schema}`.okki_orders
        WHERE company_id = :company_id
          AND account_date = :account_date
          AND ABS(amount_usd - :amount) <= 0.01
        ORDER BY order_id DESC
        LIMIT 10
    """), {
        "company_id": str(customer["company_id"]),
        "account_date": extraction.order_date.isoformat(),
        "amount": float(extraction.order_amount),
    }).mappings().all()
    candidates = [dict(row) for row in rows]
    if has_name_column and extraction.order_name:
        named = [row for row in candidates if _norm(row.get("name")) == _norm(extraction.order_name)]
        if len(candidates) == 1 and not named:
            return {
                "status": "name_mismatch",
                "candidates": candidates,
                "duplicate_invoice": False,
            }
        if named:
            candidates = named
    if sales_user and len(candidates) > 1:
        binding = db.query(ArkUserExternalBinding).filter(
            ArkUserExternalBinding.ark_user_id == int(sales_user["id"]),
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        ).first()
        if binding:
            owned = [row for row in candidates if str(row.get("user_id")) == str(binding.external_account_id)]
            if owned:
                candidates = owned
    if len(candidates) != 1:
        return {
            "status": "ambiguous" if len(candidates) > 1 else "missing",
            "candidates": candidates,
            "duplicate_invoice": False,
        }
    selected = candidates[0]
    duplicate = db.query(Invoice.id, Invoice.invoice_no).filter(
        Invoice.source_type == "okki_screenshot",
        Invoice.source_order_id == str(selected["order_id"]),
    ).first()
    return {
        "status": "matched",
        **selected,
        "duplicate_invoice": bool(duplicate),
        "duplicate_invoice_no": duplicate.invoice_no if duplicate else None,
        "candidates": candidates,
    }


def _build_invoice_patch(
    *, extraction, order_type, customer, sales_user, import_preview,
    source_order, source_hash, fees,
) -> dict | None:
    if not customer or not sales_user or not import_preview:
        return None
    items = []
    extraction_by_row = {item.source_row: item for item in extraction.items}
    for row in import_preview["rows"]:
        matched = row.get("matched_product")
        use_custom = bool(row.get("use_custom"))
        if not matched and not use_custom:
            continue
        source = extraction_by_row[row["source_row"]]
        normalized = row["normalized"]
        items.append({
            "product_kind": "hair",
            "item_type": "custom" if use_custom else "stock",
            "product_id": matched.get("product_id") if matched else None,
            "sku_id": matched.get("sku_id") if matched else None,
            "product_name": matched.get("product_name") if matched else (source.product_name or ""),
            "product_display": matched.get("product_display") if matched else normalized["product"],
            "net_weight_grams": matched.get("net_weight_grams") if matched else normalized["weight"],
            "model": source.product_model or "",
            "color": matched.get("color") if matched else normalized["color"],
            "length": matched.get("length") if matched else normalized["length"],
            "quantity": normalized["quantity"],
            "standard_price": row.get("standard_price"),
            "customer_price": row.get("customer_price"),
            "price_per_piece": normalized["unit_price"],
            "discount_amount": 0,
            "total_price": _money(Decimal(normalized["unit_price"]) * Decimal(normalized["quantity"])),
            "price_source": row.get("price_source") or "manual",
        })
    return {
        "order_type": order_type,
        "sales_user_id": int(sales_user["id"]),
        "customer_id": str(customer["company_id"]),
        "customer_name": customer["company_name"],
        "invoice_date": extraction.order_date.isoformat() if extraction.order_date else None,
        "currency": extraction.currency or "USD",
        "shipping_fee": fees["shipping_fee"],
        "internal_accessory": fees["packaging_fee"],
        "surcharge_amount": fees["handling_fee"],
        "source_type": "okki_screenshot",
        "source_order_id": str(source_order.get("order_id")) if source_order.get("order_id") else None,
        "source_order_no": str(source_order.get("order_no")) if source_order.get("order_no") else None,
        "source_order_name": extraction.order_name,
        "source_image_sha256": source_hash,
        "items": items,
    }


def _norm(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
