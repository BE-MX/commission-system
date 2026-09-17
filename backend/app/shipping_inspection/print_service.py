"""Shared outbound print ordering for the HTML payload and Word export."""
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
    """Stable sort, without mutating source items or inspection/photo ordering."""
    return sorted(items, key=lambda item: (_natural_spec(item.get("spec")), _size(item)))


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
