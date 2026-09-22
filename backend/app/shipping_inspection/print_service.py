"""Shared outbound item ordering for printing, Word export and scanner clients."""
import logging
import re

logger = logging.getLogger(__name__)


def _natural_spec(value):
    text = str(value or "").strip().upper()
    # Unicode order keeps 天才 before 平行; locale/pinyin ordering does not.
    return (not bool(text), tuple(
        (0, int(part)) if part.isascii() and part.isdigit() else (1, part)
        for part in re.split(r"([0-9]+)", text) if part
    ))


def _size(item):
    value = str(item.get("size") or "").strip()
    if not value:
        # Legacy products encode size as the first segment after the category.
        parts = re.split(r"[/／]", str(item.get("product_name") or ""))
        value = parts[1].strip() if len(parts) > 1 else ""
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(?:寸|英寸|["″]|in(?:ch(?:es)?)?)?', value, re.I)
    return float(match[1]) if match else float("inf")


def sort_outbound_print_items(items: list[dict]) -> list[dict]:
    """Stable sort by spec and size, without mutating source items or media links."""
    return sorted(items, key=lambda item: (_natural_spec(item.get("spec")), _size(item)))


OTHER_ACCESSORY_NAME = "other items"


def is_other_accessory(item: dict) -> bool:
    """Name 为 Other Items 的配件打印时忽略；产品行及名为 Other 的配件不受影响。"""
    if str(item.get("product_kind") or "hair") != "accessory":
        return False
    return str(item.get("product_name") or "").strip().lower() == OTHER_ACCESSORY_NAME


def _product_id_key(value) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(text))
    except ValueError:
        return text


def _accessory_product_ids(db) -> set[str]:
    """OKKI product_id 命中配件身份（标准价或发票明细）即视为配件。"""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    keys: set[str] = set()
    for sql in (
        "SELECT DISTINCT product_id FROM ark_std_prices "
        "WHERE product_kind = 'accessory' AND product_id IS NOT NULL",
        "SELECT DISTINCT product_id FROM ark_invoice_items "
        "WHERE product_kind = 'accessory' AND product_id IS NOT NULL",
    ):
        try:
            for row in db.execute(text(sql)):
                key = _product_id_key(row[0])
                if key:
                    keys.add(key)
        except SQLAlchemyError as exc:
            logger.warning("product_kind lookup failed: %s", exc)
            print(f"[shipping_print] product_kind lookup failed: {exc}", flush=True)
    return keys


def annotate_print_items(db, items: list[dict]) -> list[dict]:
    """打印/Word 专用：补 product_kind，去掉 Name=Other Items 的配件；不改动扫描/验货明细。"""
    accessory_ids = _accessory_product_ids(db)
    result = []
    for item in items or []:
        product_id = _product_id_key(item.get("product_id"))
        kind = "accessory" if product_id and product_id in accessory_ids else "hair"
        annotated = {**item, "product_kind": kind}
        if is_other_accessory(annotated):
            continue
        result.append(annotated)
    return result


def _with_live_outbound_handler(db, record: dict) -> dict:
    """Printed responsibility belongs to handlers, not the API account creator."""
    from fastapi import HTTPException
    from sqlalchemy.exc import SQLAlchemyError
    from app.invoice import okki_client

    invoice_id = record.get("outbound_invoice_id")
    if not invoice_id:
        # Legacy mirror schemas without the OKKI invoice bridge retain their
        # explicitly mapped owner; production uses the bridge and live handlers.
        return record
    try:
        detail = okki_client.get_outbound_info(db, str(invoice_id))
        if str(detail.get("outbound_invoice_id")) != str(invoice_id):
            raise ValueError("出库单详情ID不一致")
        handlers = detail.get("handler_info")
        if not isinstance(handlers, list):
            raise ValueError("出库单处理人数据缺失")
        names = []
        for handler in handlers:
            if not isinstance(handler, dict) or not str(handler.get("nickname") or "").strip():
                raise ValueError("出库单处理人姓名缺失")
            name = str(handler["nickname"]).strip()
            if name not in names:
                names.append(name)
        db.commit()  # Persist a lazily refreshed OKKI token before the read request closes.
        return {**record, "owner_name": " / ".join(names) or None}
    except (okki_client.OkkiApiError, ValueError, SQLAlchemyError) as exc:
        db.rollback()
        logger.warning("Outbound print handler lookup failed id=%s: %s", invoice_id, exc)
        print(f"[shipping_print] handler lookup failed id={invoice_id}: {exc}", flush=True)
        raise HTTPException(status_code=502, detail="读取出库单负责人失败，请稍后重试") from exc


def with_owner_chinese_name(db, record: dict) -> dict:
    """Resolve an English owner through account usernames or confirmed OKKI names."""
    from sqlalchemy import func, or_, select
    from app.auth.models import ArkUser, ArkUserExternalBinding

    record = _with_live_outbound_handler(db, record)
    name = str(record.get("owner_name") or "").strip()
    if not name or re.search(r"[\u3400-\u9fff]", name):
        return record
    bound_users = select(ArkUserExternalBinding.ark_user_id).where(
        ArkUserExternalBinding.provider == "okki",
        ArkUserExternalBinding.binding_status == "active",
        ArkUserExternalBinding.deleted_at.is_(None),
        func.lower(func.trim(ArkUserExternalBinding.external_display_name)) == name.lower(),
    )
    matches = (db.query(ArkUser.id, ArkUser.real_name)
        .filter(ArkUser.deleted_at.is_(None), or_(
            func.lower(func.trim(ArkUser.username)) == name.lower(),
            ArkUser.id.in_(bound_users),
        )).all())
    if len(matches) != 1:
        return record
    chinese_name = (matches[0].real_name or "").strip()
    if not re.search(r"[\u3400-\u9fff]", chinese_name):
        return record
    return {**record, "owner_name": f"{name}（{chinese_name}）"}
