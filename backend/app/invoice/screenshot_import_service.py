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
from app.invoice.screenshot_source import external_source_key, normalize_order_name
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

    if not normalize_order_name(extraction.order_name):
        blockers.append("未识别到订单名称，无法安全校验本系统 OKKI 是否存在重复订单")

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

    fees = _resolve_fees(
        extraction,
        calculated_product_amount=Decimal(totals["data"]["calculated_product_amount"]),
    )
    blockers.extend(fees.pop("blockers"))
    warnings.extend(fees.pop("warnings"))
    totals["data"].update({
        "recognized_shipping_fee": str(fees["recognized_shipping_fee"]),
        "recognized_handling_fee": str(fees["recognized_handling_fee"]),
        "recognized_packaging_fee": str(fees["recognized_packaging_fee"]),
        "fallback_shipping_fee": str(fees["fallback_shipping_fee"]),
        "difference": str(fees["difference"]),
    })

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
        warnings.append("本系统 OKKI 匹配到多张同名候选订单；保存并同步时将再次校验重复")
    elif source_order["status"] == "missing":
        if source_order.get("reason") == "non_usd_amount_unavailable":
            warnings.append("非 USD 订单不在导入阶段关联本系统 OKKI；保存并同步时将再次校验重复")
        else:
            warnings.append("本系统 OKKI 暂未发现同一订单；保存并同步时将再次校验重复")

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
            expected_product_amount=_invoice_patch_product_total(invoice_patch),
            recognized_order_amount=extraction.order_amount,
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
            "difference": "0.00",
        },
    }


def _resolve_fees(
    extraction: ScreenshotExtraction,
    *,
    calculated_product_amount: Decimal,
) -> dict:
    shipping = _money(extraction.shipping_fee_amount or 0)
    handling = _money(extraction.handling_fee_amount or 0)
    packaging = _money(extraction.packaging_fee_amount or 0)
    recognized_shipping = shipping
    warnings: list[str] = []

    legacy_total = _money(extraction.additional_fee_amount or 0)
    if legacy_total:
        warnings.append("截图附加费总额已忽略，只按单项费用和订单差额归类")

    local_total = _money(calculated_product_amount + shipping + handling + packaging)
    order_total = _money(extraction.order_amount) if extraction.order_amount is not None else None
    fallback_shipping = Decimal("0.00")
    if order_total is not None:
        difference = _money(order_total - local_total)
        if difference > Decimal("0.00"):
            fallback_shipping = difference
            shipping = _money(shipping + fallback_shipping)
            local_total = _money(local_total + fallback_shipping)
            warnings.append(
                f"有 {fallback_shipping} 费用差额无法明确归属，已统一按运费预填"
            )
        elif difference < Decimal("0.00"):
            warnings.append(
                f"单项费用填入后合计高于截图订单金额 {abs(difference)}，"
                "已保留识别结果且不阻断，请保存前确认"
            )
    final_difference = _money(local_total - (order_total if order_total is not None else local_total))
    return {
        "shipping_fee": shipping,
        "packaging_fee": packaging,
        "handling_fee": handling,
        "recognized_shipping_fee": recognized_shipping,
        "recognized_packaging_fee": packaging,
        "recognized_handling_fee": handling,
        "fallback_shipping_fee": fallback_shipping,
        "difference": final_difference,
        "blockers": [],
        "warnings": warnings,
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
        "surcharge_name": "Handling Fee" if fees["handling_fee"] else None,
        "surcharge_amount": fees["handling_fee"],
        "source_type": "okki_screenshot",
        "source_order_id": (
            str(source_order["order_id"])
            if source_order.get("order_id")
            else external_source_key(customer["company_id"], extraction.order_name)
        ),
        "source_order_no": str(source_order.get("order_no")) if source_order.get("order_no") else None,
        "source_order_name": extraction.order_name,
        "source_image_sha256": source_hash,
        "items": items,
    }


def _norm(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _invoice_patch_product_total(invoice_patch: dict) -> Decimal:
    return _money(sum(
        (Decimal(item.get("total_price") or 0) for item in invoice_patch.get("items") or []),
        Decimal("0"),
    ))
