"""Read-only catalog and purchase targets for factory delivery review."""

from collections import defaultdict
from dataclasses import asdict, replace
from datetime import timedelta
from difflib import SequenceMatcher
import re

from sqlalchemy import or_, select, text

from app.core.config import get_settings
from app.core.time import beijing_today
from app.factory_inbound.matching_rules import (
    Candidate, color_key, compact, extract_invoice_ref, match_candidates, measure,
    normalize_ref, parse_ref,
)
from app.factory_inbound.models import Alias, LineType
from app.invoice import delegation_service, product_service
from app.invoice.models import CustomProduct, Invoice, InvoiceItem
from app.stock.models import ProductionOrder, ProductionOrderItem


def load_catalog(db):
    schema = product_service._schema()
    products = product_service._table_columns(db, "okki_products")
    skus = product_service._table_columns(db, "okki_product_skus")
    name = product_service._quoted_column(products, "product_name", "name")
    product_active = product_service._disable_filter("okki_products", products, alias="p")
    sku_active = product_service._disable_filter("okki_product_skus", skus, alias="s")
    rows = db.execute(text(f"""
        SELECT DISTINCT p.product_id, s.sku_id, COALESCE({name}, '') AS name, p.size, p.color, p.unit,
            CASE WHEN {product_active} THEN 1 ELSE 0 END AS active
        FROM `{schema}`.okki_products p
        LEFT JOIN `{schema}`.okki_product_skus s ON s.product_id = p.product_id AND {sku_active}
        ORDER BY p.product_id, s.sku_id
    """)).all()
    return [Candidate(*row[:6], issue=None if row.active else "小满产品已停用") for row in rows]


def _invoice_ref(invoice):
    return extract_invoice_ref(invoice.invoice_no)


def _stock_ref(order):
    if re.fullmatch(r"#[0-9]{8,9}", order.batch_no or ""):
        return normalize_ref(order.batch_no[5:])
    return None


def _unavailable(order, kind):
    if order.transaction_mode != "legacy":
        return "订单已转本地办理"
    if kind == "invoice":
        if order.status == "cancel_pending" or order.commerce_status == "cancel_pending":
            return "发票取消中"
        if order.status == "cancelled" or order.commerce_status == "cancelled":
            return "发票已取消"
    else:
        if order.deleted_flag:
            return "生产备货订单已删除"
        if order.status != 0:
            return "生产备货订单已完成或终止"
    return None


def can_see_invoice(db, user, invoice):
    permissions = set(user.get("permissions", ()))
    if "super_admin" in user.get("roles", ()):
        return True
    if not {"invoice:read", "invoice:write"} & permissions:
        return False
    return "invoice:read_all" in permissions or delegation_service.can_access_invoice(
        db, int(user["sub"]), invoice
    )


class MatchingContext:
    def __init__(self, db, refs, order_choices=(), *, load_products=True):
        self.db = db
        self.types = {row.code: row for row in db.scalars(select(LineType).where(LineType.enabled))}
        self.aliases = defaultdict(dict)
        for row in db.scalars(select(Alias).where(Alias.enabled)):
            self.aliases[row.kind][row.factory_term] = row.target
        self.orders = defaultdict(list)
        self.ignored = defaultdict(list)
        products = load_catalog(db) if load_products else []
        self.catalog = [item for item in products if item.issue is None]
        self.by_product = defaultdict(list)
        self.exact = {}
        for item in products:
            if item.sku_id is not None and not item.issue:
                self.exact[item.product_id, item.sku_id] = item
            self.by_product[item.product_id].append(item)
        self.by_order = defaultdict(list)
        self.targets = {}
        self._load_targets(refs, order_choices)

    def _load_targets(self, refs, order_choices):
        refs = {ref: parse_ref(ref) for ref in refs if parse_ref(ref)}
        if not refs and not order_choices:
            return
        since = beijing_today() - timedelta(days=get_settings().FACTORY_INBOUND_ORDER_LOOKBACK_DAYS)
        stocks = self.db.scalars(select(ProductionOrder).where(ProductionOrder.created_at >= since))
        invoices = self.db.scalars(select(Invoice).where(
            Invoice.created_at >= since, Invoice.status != "deleted",
            or_(Invoice.order_type == "production", Invoice.transaction_mode == "legacy"),
        ))
        used_stocks, used_invoices = {}, {}
        for kind, rows, ref_from, used in (
            ("production_order", stocks, _stock_ref, used_stocks),
            ("invoice", invoices, _invoice_ref, used_invoices),
        ):
            for order in rows:
                ref = ref_from(order)
                parsed = parse_ref(ref)
                if not parsed:
                    continue
                keys = [key for key, possibilities in refs.items() if possibilities & parsed]
                if kind == "invoice" and order.order_type != "production":
                    if order.order_type in {"stock", "presale"}:
                        for key in keys:
                            self.ignored[key].append({"kind": order.order_type, "ref": ref})
                    continue
                if not keys and (kind, order.id) not in order_choices:
                    continue
                used[order.id] = (order, ref)
                for key in keys:
                    self.orders[key].append((kind, order.id))

        if used_stocks:
            for item in self.db.scalars(select(ProductionOrderItem).where(
                ProductionOrderItem.order_id.in_(used_stocks)
            )):
                self.by_order["production_order", item.order_id].append(item)
        legacy_invoice_ids = [key for key, (row, _) in used_invoices.items() if row.transaction_mode == "legacy"]
        if legacy_invoice_ids:
            for item, custom in self.db.execute(select(InvoiceItem, CustomProduct).outerjoin(
                CustomProduct, CustomProduct.id == InvoiceItem.custom_product_id,
            ).where(
                InvoiceItem.invoice_id.in_(legacy_invoice_ids), InvoiceItem.product_kind != "accessory",
            )):
                self.by_order["invoice", item.invoice_id].append((item, custom))
        for kind, used in (("production_order", used_stocks), ("invoice", used_invoices)):
            for order_id, (order, ref) in used.items():
                items = self.by_order[kind, order_id]
                self.targets[kind, order_id] = {
                    "id": order_id, "kind": kind, "ref": ref,
                    "date": order.created_at.date().isoformat(), "reason": _unavailable(order, kind),
                    "line_count": len(items), "quantity": sum(
                        item.order_qty if kind == "production_order" else item[0].quantity for item in items
                    ),
                }

    def _products_for(self, order):
        if not order:
            return self.catalog
        kind, order_id = order
        result = {}
        for value in self.by_order[order]:
            if kind == "invoice":
                item, custom = value
                pid = custom.okki_product_id if custom else item.product_id
                sid = custom.okki_sku_id if custom else item.sku_id
                product = self.exact.get((pid, sid))
                if not product:
                    product = Candidate(pid or 0, None, item.product_display or "", item.length,
                                        item.color, item.net_weight_grams, issue="小满未建品或 SKU 未启用")
                ordered = remaining = item.quantity
            else:
                item = value
                catalog = self.by_product.get(item.product_id, [])
                if not catalog:
                    continue
                product = catalog[0]
                if len(catalog) != 1 or product.sku_id is None or product.issue:
                    product = replace(product, sku_id=None, issue=product.issue or "生产备货明细无法唯一确定小满 SKU")
                ordered = item.order_qty
                remaining = max(0, ordered - item.received_qty) if item.status == 0 else 0
            key = (product.product_id, product.sku_id, product.color, product.size, product.weight)
            previous = result.get(key)
            result[key] = replace(
                product, ordered=ordered + (previous.ordered if previous else 0),
                remaining=remaining + (previous.remaining if previous else 0),
            )
        return list(result.values())

    def match(self, values, decision):
        ref = normalize_ref(values.get("order_ref_raw"))
        line_type = self.types.get(values.get("line_type"))
        length = measure(values.get("length_raw"), "length")
        weight = measure(values.get("weight_raw"), "weight")
        raw_color = values.get("color_raw")
        quantity = values.get("quantity")
        grade = self.aliases["grade"].get(compact(values.get("grade_raw")))
        process = self.aliases["process"].get(compact(values.get("process_raw")))
        hits = self.orders.get(ref, [])
        orders = [self.targets[key] for key in hits]
        data = {"orders": orders, "candidates": [], "references": [], "order_ref": ref,
                "ignored_orders": self.ignored.get(ref, []),
                "length_in": str(length) if length else None, "weight_g": str(weight) if weight else None}

        def result(status, reason=None):
            return status, {**data, "reason": reason}

        if not line_type:
            return result("blocked", "请选择有效的行类型")
        if line_type.code == "unclear":
            return result("blocked", "请核对并选择行类型")
        if not line_type.is_inbound:
            return result("skipped", line_type.label)
        if not all((length, weight, raw_color, quantity)):
            return result("blocked", "请补齐长度、颜色、克重和数量")
        if compact(values.get("quantity_unit")) not in {"条", "片", "根", "件", "PCS", "PIECE", "PIECES"}:
            return result("blocked", "请核对数量单位，须为条、片、根或件")
        if not process:
            return result("blocked", "请核对工艺写法或维护工艺词表")
        if values.get("order_ref_raw") and not parse_ref(ref):
            return result("blocked", "请核对生产单号或清空后重新匹配")

        chosen = decision.get("order") or {}
        chosen_key = (chosen.get("kind"), chosen.get("id"))
        order = chosen_key if chosen_key in hits else hits[0] if len(hits) == 1 else None
        route = decision.get("route")
        if route == "reselect":
            return result("decide", "请更正生产单号后重新匹配")
        if route not in {"cross", "inbound_only"}:
            if chosen and chosen_key not in hits:
                return result("choose" if hits else "blocked", "原选订单已变化，请重新核对")
            if len(hits) > 1 and order is None:
                return result("choose", "单号对应多张订单，请选择订单")
            if order:
                data["order"] = self.targets[order]
                if data["order"]["reason"]:
                    blocked_reason = data["order"]["reason"]
                    data["allowed_routes"] = ["inbound_only"]
                    if blocked_reason not in {"发票取消中", "订单已转本地办理"} or order[0] == "production_order":
                        data["allowed_routes"].append("cross")
                    return result("decide", blocked_reason)
        else:
            order = None
        data["route"] = route or ("order" if order else "cross")

        explicit_grade = values.get("grade_source") == "explicit"
        products = self._products_for(order)
        status, matched = match_candidates(
            products, length=length, weight=weight, color=raw_color, process=process,
            grade=grade if explicit_grade else None, quantity=quantity, aliases=self.aliases["color"],
        )
        for row in matched:
            reason = row.issue
            if row.sku_id is None:
                reason = reason or "小满 SKU 不存在或未启用"
            data["candidates"].append({
                **asdict(row), "name": row.name if row.sku_id is not None else "未绑定小满 SKU 的产品",
                "issue": reason, "quantity_match": row.remaining == quantity,
            })
        if not matched:
            if order:
                if order[0] == "production_order" and any(
                    item.product_id not in self.by_product for item in self.by_order[order]
                ):
                    return result("blocked", "生产备货订单含小满目录无法识别的明细，请核对产品档案")
                data["allowed_routes"] = ["inbound_only", "cross"] if order[0] == "production_order" else ["inbound_only"]
                return result("decide", f"订单 {data['order']['ref']} 中没有此产品")
            nearby = [row for row in products if row.sku_id and measure(row.size, "length") == length
                      and measure(row.weight, "weight") == weight and process.casefold() in row.name.casefold()]
            nearby.sort(key=lambda row: -SequenceMatcher(None, color_key(raw_color), color_key(row.color)).ratio())
            data["references"] = [asdict(row) for row in nearby[:3]]
            return result("blocked", "找不到启用的匹配产品，请核对规格")
        chosen_sku = decision.get("sku_id")
        if chosen_sku is not None:
            candidate = next((row for row in data["candidates"] if row["sku_id"] == chosen_sku), None)
            if candidate is None:
                return result("choose", "原选 SKU 已变化，请重新选择产品")
        else:
            candidate = data["candidates"][0] if len(matched) == 1 else None
        if not candidate:
            return result(status, "请核对等级与规格，再选择产品")
        data["product"] = candidate
        if candidate["issue"]:
            return result("blocked", candidate["issue"])
        if order and candidate["remaining"] == 0:
            data["allowed_routes"] = ["inbound_only", "cross"] if order[0] == "production_order" else ["inbound_only"]
            return result("decide", "该订单的产品已入满")
        if order and order[0] == "production_order" and candidate["remaining"] < quantity:
            return result("blocked", f"超出该生产备货订单剩余数量 {quantity - candidate['remaining']} 件")
        if order and order[0] == "invoice" and candidate["remaining"] < quantity:
            data["excess_quantity"] = quantity - candidate["remaining"]
        if not order and not (explicit_grade and grade) and not chosen_sku:
            return result("confirm", "未写明可识别的等级，请核对并选择产品")
        if explicit_grade and not grade and not chosen_sku:
            return result("confirm", f"未知等级写法 {values['grade_raw']}，请核对产品")
        if status == "confirm" and not (decision.get("confirm_conversion") or chosen_sku):
            return result("confirm", f"请核对颜色换算 {raw_color} → {candidate['color']}")
        return result("matched")
