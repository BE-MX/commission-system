"""Xiaoman order sync boundary: field mapping + push orchestration.

POST /v1/invoices/order/push (open.xiaoman.cn/api-3478252) hard rules:
- product rows MUST carry OKKI-side product_id + sku_id or they are silently
  dropped; cost_amount is NOT auto-computed (missing → saved as 0);
- status must be an enterprise-specific code from orderEnums;
- on edit (order_id present) rows without unique_id are deduped by
  product_id+sku_id — fatal for custom lines sharing the generic product,
  so unique_ids are persisted on items and carried across edits;
- locally deleted pushed lines are sent as remove:1 rows (snapshot column
  ark_invoices.xiaoman_removed_lines, cleared on success).

Order-level amounts (amount/product_total_*) are deliberately NOT sent:
OKKI computes them from product_list + cost_list, and the exchange-rate
×100 convention makes hand-fed totals riskier than omission.

Push settings (ark_xiaoman_settings, single row) are also maintained here:
credentials, the generic product used for custom lines, and push defaults.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUserExternalBinding
from app.core.config import get_settings
from app.invoice import okki_client, product_service
from app.invoice.models import CustomProduct, Invoice, InvoiceSyncLog, XiaomanSettings
from app.invoice.service import validate_invoice

logger = logging.getLogger(__name__)


def sync_invoice(db: Session, invoice: Invoice, operator_id: int | None = None) -> dict:
    """Push one invoice to OKKI (create or edit). Never raises for expected
    failures — state + sync log are always persisted.

    Commits ONCE itself right after OKKI accepts (order_id + audit log): the
    write-backs after that can fail (concurrent edit / crash), and an accepted
    order with no local record means the next sync creates a duplicate REAL
    order. Caller (router) owns the final commit for everything else.
    """
    issues = validate_invoice(invoice)
    if issues:
        return {"ok": False, "message": "发票未通过同步前校验", "issues": issues}

    # 推单前对账：OKKI 侧后来建品的 custom 行自动回填真实 ID（07-07 设计 3.1）
    try:
        product_service.reconcile_custom_products(db)
    except Exception as exc:  # noqa: BLE001 - 对账失败不阻断推单，custom 行走通用产品兜底
        logger.warning("custom product reconcile before push failed: %s", exc)
        print(f"[xiaoman] reconcile before push failed: {exc}", flush=True)

    payload, line_binding, issues = build_push_payload(db, invoice)
    if issues:
        return {"ok": False, "message": "推单前置校验未通过", "issues": issues}
    # 本次实际推送的删行快照——成功后只清这个值（并发编辑可能又写入了新快照）
    removed_snapshot = invoice.xiaoman_removed_lines

    action = "update" if invoice.xiaoman_order_id else "create"
    try:
        data = okki_client.push_order(db, payload)
    except okki_client.OkkiApiError as exc:
        _mark_sync_failed(db, invoice, str(exc), action, payload, operator_id)
        return {"ok": False, "message": str(exc), "issues": []}
    except Exception as exc:  # noqa: BLE001 - 意外异常也必须落状态+日志
        logger.warning("OKKI push unexpected failure invoice=%s: %s", invoice.id, exc)
        print(f"[xiaoman] push unexpected failure invoice={invoice.id}: {exc}", flush=True)
        _mark_sync_failed(db, invoice, f"推单异常：{exc}", action, payload, operator_id)
        return {"ok": False, "message": f"推单异常：{exc}", "issues": []}

    order_id = (data or {}).get("order_id")
    if action == "create" and not order_id:
        # 响应异常（无 order_id）不能标成功：本地记不住单号，重推必然重复建单
        message = "OKKI 响应异常（未返回 order_id）：请先到 OKKI 后台确认订单是否已生成，再决定是否重试"
        _mark_sync_failed(db, invoice, message, action, payload, operator_id, response=data)
        return {"ok": False, "message": message, "issues": []}

    # 第一段落库：order_id + 审计日志立即固化（此后任何回写失败都不会丢单号）
    if order_id:
        invoice.xiaoman_order_id = str(order_id)
    _write_sync_log(
        db, invoice, action=action, success=True,
        payload=payload, response=data, error=None, operator_id=operator_id,
    )
    db.commit()

    # 第二段：unique_id 回写与状态收尾（由 router 的 commit 落库）
    unassigned = _assign_unique_ids(invoice, line_binding, (data or {}).get("product_list") or [])
    if unassigned:
        # OKKI 静默丢行（product_id/sku_id 失效等）：订单已建但缺行，必须让用户看见
        message = (
            f"OKKI 已受理订单（order_id={invoice.xiaoman_order_id}），"
            f"但有 {unassigned} 行未出现在响应中（可能被静默忽略），"
            "请核对 OKKI 订单明细后重推补齐"
        )
        _mark_sync_failed(db, invoice, message, action, payload, operator_id, response=data)
        return {"ok": False, "message": message, "issues": [], "xiaoman_order_id": invoice.xiaoman_order_id}

    invoice.sync_status = "synced"
    invoice.status = "synced"
    invoice.sync_error = None
    invoice.synced_at = datetime.utcnow()
    if removed_snapshot:
        # 条件清空：只清本次推送时的快照值，避免覆盖推送期间并发编辑新写入的删行
        db.execute(
            update(Invoice)
            .where(Invoice.id == invoice.id, Invoice.xiaoman_removed_lines == removed_snapshot)
            .values(xiaoman_removed_lines=None)
        )
    return {
        "ok": True,
        "message": "已同步到小满",
        "issues": [],
        "xiaoman_order_id": invoice.xiaoman_order_id,
    }


def build_push_payload(
    db: Session, invoice: Invoice
) -> tuple[dict | None, list[tuple], list[dict]]:
    """Map an Ark invoice onto the OKKI push body.

    Returns (payload, line_binding, issues); line_binding pairs each real
    product row with its InvoiceItem for response unique_id write-back.
    Any issue aborts the push — partial orders are worse than no order.
    """
    issues: list[dict] = []
    settings_row = get_settings_row(db)

    # 客户：发票客户选自 customer_info（OKKI CRM 投影），company_id 即 OKKI 数字 ID
    company_id = str(invoice.customer_id or "").strip()
    if not company_id.isdigit():
        issues.append({"field": "customer_id", "message": f"客户 ID「{company_id}」不是 OKKI 数字 ID，无法推单"})

    # 订单状态：企业专属枚举 code，硬编码或漏配都会被 OKKI 静默忽略
    default_status = str((settings_row.default_order_status if settings_row else None) or "").strip()
    if not default_status.isdigit():
        issues.append({"field": "default_order_status", "message": "未配置默认订单状态：订单管理 → OKKI 推单设置"})

    # 业绩归属：业务员必须已绑定 OKKI 账号——管钱字段宁可失败也不静默归属 token 账号
    okki_user_id = _resolve_okki_user_id(db, invoice.sales_user_id)
    if okki_user_id is None:
        who = invoice.sales_user_name or (f"ID {invoice.sales_user_id}" if invoice.sales_user_id else "未设置")
        issues.append({"field": "sales_user_id", "message": f"业务员（{who}）未绑定 OKKI 账号：系统管理 → 外部账号绑定"})

    order_id: int | None = None
    if invoice.xiaoman_order_id:
        if str(invoice.xiaoman_order_id).isdigit():
            order_id = int(invoice.xiaoman_order_id)
        else:
            issues.append({"field": "xiaoman_order_id", "message": f"已存 OKKI 订单 ID「{invoice.xiaoman_order_id}」非法，请联系管理员核对"})

    product_rows, line_binding, line_issues = _build_product_rows(db, invoice, settings_row, editing=order_id is not None)
    issues.extend(line_issues)
    if issues:
        return None, [], issues

    payload: dict = {
        # 订单名 = 方舟发票号 + 客户名，OKKI 列表一眼可溯源
        "name": f"{invoice.invoice_no} {invoice.customer_name}".strip(),
        "account_date": invoice.invoice_date.isoformat(),
        "currency": invoice.currency or (settings_row.default_currency if settings_row else None) or "USD",
        "company_id": int(company_id),
        "status": int(default_status),
        # 不传 user_id（操作人）：OKKI 会按该用户校验订单编辑权限、无权限报 404，
        # 默认落 token 授权账号最稳；业绩归属/创建人/处理人用绑定的业务员
        "create_user": okki_user_id,
        "handler": [okki_user_id],
        "users": [{"user_id": okki_user_id, "rate": 100}],
        "product_list": product_rows,
    }
    if order_id is not None:
        payload["order_id"] = order_id
        payload["product_list"] = product_rows + _build_remove_rows(db, invoice, settings_row)
    remark = "\n".join(
        part for part in (
            (invoice.remark or "").strip() or None,
            f"Payment term: {invoice.payment_term}" if invoice.payment_term else None,
        ) if part
    )
    cost_list = _build_cost_list(invoice)
    if order_id is not None:
        # 编辑语义下空值也要发：字段缺省可能被 OKKI 当"不修改"，运费改 0 / 清空备注
        # 就永远同步不过去（首个真单需人工核对此语义，见 implementation-notes）
        payload["remark"] = remark
        payload["cost_list"] = cost_list
    else:
        if remark:
            payload["remark"] = remark
        if cost_list:
            payload["cost_list"] = cost_list
    return payload, line_binding, []


def _resolve_okki_user_id(db: Session, ark_user_id: int | None) -> int | None:
    if not ark_user_id:
        return None
    binding = (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.ark_user_id == ark_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .order_by(ArkUserExternalBinding.is_primary.desc(), ArkUserExternalBinding.id)
        .first()
    )
    if binding is None or not str(binding.external_account_id or "").strip().isdigit():
        return None
    return int(binding.external_account_id)


def _build_product_rows(
    db: Session, invoice: Invoice, settings_row: XiaomanSettings | None, *, editing: bool
) -> tuple[list[dict], list[tuple], list[dict]]:
    issues: list[dict] = []
    rows: list[dict] = []
    line_binding: list[tuple] = []

    custom_ids = [i.custom_product_id for i in invoice.items if i.item_type == "custom" and i.custom_product_id]
    custom_rows = {
        row.id: row
        for row in (db.query(CustomProduct).filter(CustomProduct.id.in_(custom_ids)).all() if custom_ids else [])
    }
    generic_ok = bool(settings_row and settings_row.generic_product_id and settings_row.generic_sku_id)

    for idx, item in enumerate(invoice.items, start=1):
        prefix = f"items[{idx}]"
        row: dict = {
            "count": int(item.quantity),
            "unit_price": float(item.price_per_piece),
            # OKKI 不自动算小计，不传当 0 重存
            "cost_amount": float(item.total_price),
        }
        if editing and item.xiaoman_unique_id and str(item.xiaoman_unique_id).isdigit():
            row["unique_id"] = int(item.xiaoman_unique_id)
        product_id, sku_id = item.product_id, item.sku_id
        if item.item_type == "custom":
            custom = custom_rows.get(item.custom_product_id)
            if custom and custom.okki_product_id and custom.okki_sku_id:
                # OKKI 侧已建品并回填 → 临时产品转正，走真实 ID
                product_id, sku_id = custom.okki_product_id, custom.okki_sku_id
            elif generic_ok:
                product_id, sku_id = settings_row.generic_product_id, settings_row.generic_sku_id
                # 通用产品行透传真实描述，OKKI 订单行显示真实产品
                row["product_name"] = item.product_name
                if item.model:
                    row["product_model"] = item.model
                if item.net_weight_grams:
                    row["unit"] = item.net_weight_grams
            else:
                issues.append({"field": prefix, "message": "生产单产品需先配置通用产品：订单管理 → OKKI 推单设置"})
                continue
        if not (product_id and sku_id):
            issues.append({"field": prefix, "message": "缺少 OKKI product_id/sku_id，无法推单"})
            continue
        row["product_id"] = int(product_id)
        row["sku_id"] = int(sku_id)
        rows.append(row)
        line_binding.append((item, row))

    if editing:
        # 官方硬约束：编辑推单时无 unique_id 的行按 product_id+sku_id 去重只留一条。
        # 一次新增多条同产品行（最典型：多条共用通用产品的生产明细）会被 OKKI 静默并掉，
        # 必须前置拦截——分多次推送，每次推完行会拿到 unique_id。
        fresh_counts: dict[tuple[int, int], int] = defaultdict(int)
        for row in rows:
            if not row.get("unique_id"):
                fresh_counts[(row["product_id"], row["sku_id"])] += 1
        if any(count > 1 for count in fresh_counts.values()):
            issues.append({
                "field": "items",
                "message": "编辑推单一次只能新增一条相同产品的明细（OKKI 按产品去重会静默合并多条生产单通用产品行）：请先推送保存，再添加下一条后重推",
            })
    return rows, line_binding, issues


def _build_remove_rows(db: Session, invoice: Invoice, settings_row: XiaomanSettings | None) -> list[dict]:
    """remove:1 rows for pushed lines deleted locally since the last push.

    unique_id anchors the OKKI-side line; product/sku are best-effort echoes
    (backfill/generic resolution may have shifted since the original push).
    """
    try:
        snapshots = json.loads(invoice.xiaoman_removed_lines or "[]")
    except ValueError:
        snapshots = []
    rows: list[dict] = []
    for snap in snapshots:
        unique_id = snap.get("unique_id")
        if not unique_id or not str(unique_id).isdigit():
            continue
        row: dict = {"unique_id": int(unique_id), "remove": 1}
        product_id, sku_id = snap.get("product_id"), snap.get("sku_id")
        if not (product_id and sku_id):
            custom = db.get(CustomProduct, snap["custom_product_id"]) if snap.get("custom_product_id") else None
            if custom and custom.okki_product_id and custom.okki_sku_id:
                product_id, sku_id = custom.okki_product_id, custom.okki_sku_id
            elif settings_row and settings_row.generic_product_id and settings_row.generic_sku_id:
                product_id, sku_id = settings_row.generic_product_id, settings_row.generic_sku_id
        if product_id and sku_id:
            row["product_id"] = int(product_id)
            row["sku_id"] = int(sku_id)
        rows.append(row)
    return rows


def _build_cost_list(invoice: Invoice) -> list[dict]:
    """Shipping fee + surcharge as absolute-value additions (percent_type=0)."""
    costs: list[dict] = []
    shipping = float(invoice.shipping_fee or 0)
    if shipping > 0:
        name = f"Shipping fee ({invoice.express_channel})" if invoice.express_channel else "Shipping fee"
        costs.append({"cost_name": name, "percent_type": 0, "percent_amount": shipping, "cost": shipping})
    surcharge = float(invoice.surcharge_amount or 0)
    if surcharge > 0:
        costs.append({
            "cost_name": invoice.surcharge_name or "Surcharge",
            "percent_type": 0,
            "percent_amount": surcharge,
            "cost": surcharge,
        })
    return costs


def _assign_unique_ids(invoice: Invoice, line_binding: list[tuple], response_rows: list[dict]) -> int:
    """Write OKKI line unique_ids back onto items; return the unassigned count.

    Rows pushed with a unique_id keep it. New rows claim unclaimed response
    unique_ids grouped by (product_id, sku_id), in order — same-identity rows
    are interchangeable, so positional assignment within a group is safe.
    A non-zero return means OKKI silently dropped rows — caller must surface it.
    """
    known = {str(row.get("unique_id")) for _item, row in line_binding if row.get("unique_id")}
    pool: dict[tuple[str, str], list] = defaultdict(list)
    for resp in response_rows:
        uid = resp.get("unique_id")
        if uid is None or str(uid) in known:
            continue
        pool[(str(resp.get("product_id")), str(resp.get("sku_id")))].append(uid)
    unassigned = 0
    for item, row in line_binding:
        if row.get("unique_id"):
            continue
        uids = pool.get((str(row.get("product_id")), str(row.get("sku_id"))))
        if uids:
            item.xiaoman_unique_id = str(uids.pop(0))
        else:
            unassigned += 1
    if unassigned:
        logger.warning("invoice %s: %s line(s) missing unique_id from OKKI response", invoice.id, unassigned)
        print(f"[xiaoman] invoice {invoice.id}: {unassigned} line(s) missing unique_id in response", flush=True)
    return unassigned


def _mark_sync_failed(
    db: Session,
    invoice: Invoice,
    message: str,
    action: str,
    payload: dict | None,
    operator_id: int | None,
    response: dict | None = None,
) -> None:
    invoice.sync_status = "sync_failed"
    invoice.status = "sync_failed"
    invoice.sync_error = message
    _write_sync_log(
        db, invoice, action=action, success=False,
        payload=payload, response=response, error=message, operator_id=operator_id,
    )


def _write_sync_log(
    db: Session,
    invoice: Invoice,
    *,
    action: str,
    success: bool,
    payload: dict | None,
    response: dict | None,
    error: str | None,
    operator_id: int | None,
) -> None:
    # payload 无凭证（token 在 header），原样落审计
    db.add(InvoiceSyncLog(
        invoice_id=invoice.id,
        action=action,
        success=1 if success else 0,
        request_digest=json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
        response_body=json.dumps(response, ensure_ascii=False, default=str) if response is not None else None,
        error_message=error,
        operator_id=operator_id,
    ))


def list_sync_logs(db: Session, invoice_id: int, limit: int = 50) -> list[dict]:
    rows = (
        db.query(InvoiceSyncLog)
        .filter(InvoiceSyncLog.invoice_id == invoice_id)
        .order_by(InvoiceSyncLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "action": row.action,
            "success": bool(row.success),
            "error_message": row.error_message,
            "response_body": row.response_body,
            "created_at": row.created_at,
        }
        for row in rows
    ]


# ── push settings (single row) ───────────────────────────────

def get_settings_row(db: Session) -> XiaomanSettings | None:
    return db.query(XiaomanSettings).order_by(XiaomanSettings.id).first()


def get_or_create_settings(db: Session) -> XiaomanSettings:
    row = get_settings_row(db)
    if row is not None:
        return row
    # 固定 id=1：并发首次保存时靠主键冲突挡住第二行，savepoint 回滚后改读赢家行
    try:
        with db.begin_nested():
            row = XiaomanSettings(id=1, default_currency="USD")
            db.add(row)
    except IntegrityError:
        row = get_settings_row(db)
        if row is None:
            raise
    return row


def _mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 12:
        return "****"
    return f"{token[:4]}****{token[-4:]}"


def serialize_settings(row: XiaomanSettings | None) -> dict:
    settings = get_settings()
    client_configured = bool(settings.OKKI_CLIENT_ID and settings.OKKI_CLIENT_SECRET)
    if row is None:
        return {
            "generic_product_no": None,
            "generic_product_id": None,
            "generic_sku_id": None,
            "default_order_status": None,
            "default_currency": "USD",
            "has_token": False,
            "access_token_masked": None,
            "token_expires_at": None,
            "client_configured": client_configured,
            "updated_by": None,
            "updated_at": None,
        }
    return {
        "generic_product_no": row.generic_product_no,
        "generic_product_id": row.generic_product_id,
        "generic_sku_id": row.generic_sku_id,
        "default_order_status": row.default_order_status,
        "default_currency": row.default_currency,
        "has_token": bool(row.access_token),
        "access_token_masked": _mask_token(row.access_token),
        "token_expires_at": row.token_expires_at.isoformat() if row.token_expires_at else None,
        "client_configured": client_configured,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def resolve_generic_product(db: Session, product_no: str) -> dict | None:
    """Look up one okki product by product_no and list its enabled skus.

    okki_products / okki_inventory are read-only projections of the OKKI cloud
    library — this is the authoritative source for generic_product_id/sku_id.
    """
    schema = product_service._schema()
    product_columns = product_service._table_columns(db, "okki_products")
    if "product_no" not in product_columns:
        return None
    name_expr = product_service._quoted_column(product_columns, "product_name", "name")
    row = db.execute(text(f"""
        SELECT p.product_id, {name_expr} AS product_name, p.product_no
        FROM `{schema}`.okki_products p
        WHERE {product_service._disable_filter("okki_products", product_columns, alias="p")}
          AND p.product_no = :no
        ORDER BY p.product_id
        LIMIT 1
    """), {"no": product_no}).mappings().first()
    if row is None:
        return None
    inventory_columns = product_service._table_columns(db, "okki_inventory")
    # LIMIT 200 是 update_settings 校验 sku 归属的口径上限——超过它的 sku 会被误判"不属于该产品"
    skus = db.execute(text(f"""
        SELECT DISTINCT sku_id
        FROM `{schema}`.okki_inventory
        WHERE product_id = :pid
          AND {product_service._disable_filter("okki_inventory", inventory_columns)}
        ORDER BY sku_id
        LIMIT 200
    """), {"pid": row["product_id"]}).scalars().all()
    return {
        "product_id": int(row["product_id"]),
        "product_name": str(row["product_name"] or ""),
        "product_no": str(row["product_no"] or ""),
        "skus": [int(s) for s in skus if s is not None],
    }


def update_settings(
    db: Session,
    *,
    generic_product_no: str | None,
    generic_sku_id: int | None,
    default_order_status: str | None,
    default_currency: str,
    access_token: str | None,
    token_expires_at: datetime | None,
    user_id: int | None,
) -> XiaomanSettings:
    """Apply the admin form. access_token semantics: None keeps the stored
    token, empty string clears it, anything else overwrites it.

    generic_product_id/sku_id are resolved server-side from product_no — the
    client-picked sku is only accepted when it belongs to that product.
    """
    row = get_or_create_settings(db)

    product_no = (generic_product_no or "").strip() or None
    if product_no:
        resolved = resolve_generic_product(db, product_no)
        if resolved is None:
            raise ValueError(f"产品编号 {product_no} 在 OKKI 产品库中不存在或已停用")
        # 存库内规范值而非用户输入（MySQL CI 排序下 p001 也能解析到 P001）
        row.generic_product_no = resolved["product_no"] or product_no
        row.generic_product_id = resolved["product_id"]
        if generic_sku_id is not None:
            if generic_sku_id not in resolved["skus"]:
                raise ValueError(f"SKU {generic_sku_id} 不属于产品 {product_no}")
            row.generic_sku_id = generic_sku_id
        elif len(resolved["skus"]) == 1:
            row.generic_sku_id = resolved["skus"][0]
        else:
            row.generic_sku_id = None
    else:
        row.generic_product_no = None
        row.generic_product_id = None
        row.generic_sku_id = None

    row.default_order_status = (default_order_status or "").strip() or None
    row.default_currency = (default_currency or "USD").strip() or "USD"

    if access_token is not None:
        token = access_token.strip()
        row.access_token = token or None
        # 手动覆盖 token 时表单里的过期时间是旧 token 的残值，不可信：
        # 保守按"刚签发"算 8 小时；清除 token 则联动清空
        token_expires_at = datetime.utcnow() + timedelta(hours=8) if token else None
    row.token_expires_at = token_expires_at

    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    return row
