"""Display-only invoice item grouping with independent optimistic versioning."""
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException

from app.core.time import beijing_today
from app.invoice.models import InvoiceItemGroup


def load_groups(db, invoice):
    if invoice.item_groups or invoice.id is None:
        return invoice.item_groups
    groups = db.query(InvoiceItemGroup).filter_by(invoice_id=invoice.id).order_by(
        InvoiceItemGroup.sort_order, InvoiceItemGroup.id,
    ).all()
    if groups:
        invoice.item_groups = groups
    return groups


def serialize(invoice):
    return [
        {"key": group.key, "name": group.name, "sort_order": group.sort_order}
        for group in invoice.item_groups
    ]


def version(invoice):
    keys = {group.id: group.key for group in invoice.item_groups}
    value = {
        "groups": serialize(invoice),
        "items": [
            {"id": item.id, "group_key": keys.get(item.group_id)}
            for item in invoice.items
            if item.product_kind != "accessory" and not item.presale_archived
        ],
    }
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _definitions(rows):
    result, keys, names = [], set(), set()
    for row in rows:
        key = row.key.strip()
        name = row.name.strip()
        if not name:
            raise ValueError("分组名称不能为空")
        if key in keys or name.casefold() in names:
            raise ValueError("分组键和分组名称在同一订单内不能重复")
        keys.add(key)
        names.add(name.casefold())
        result.append({"key": key, "name": name, "sort_order": row.sort_order})
    return result


def _default_group(db, invoice):
    if invoice.item_groups:
        return invoice.item_groups[0]
    group = InvoiceItemGroup(
        key=uuid4().hex,
        name=beijing_today().isoformat(),
        sort_order=1,
    )
    invoice.item_groups.append(group)
    db.flush()
    return group


def _sync_explicit(db, invoice, rows):
    definitions = _definitions(rows)
    existing = {group.key: group for group in invoice.item_groups}
    occupied = {row["name"].casefold() for row in definitions}
    for group in existing.values():
        temporary = f"__grouping_{uuid4().hex}"
        while temporary.casefold() in occupied:
            temporary = f"__grouping_{uuid4().hex}"
        group.name = temporary
        occupied.add(temporary.casefold())
    db.flush()
    ordered = []
    for index, row in enumerate(definitions, start=1):
        group = existing.get(row["key"])
        if group is None:
            group = InvoiceItemGroup(key=row["key"])
            invoice.item_groups.append(group)
        group.name = row["name"]
        group.sort_order = row["sort_order"] or index
        ordered.append(group)
    requested = {row["key"] for row in definitions}
    removed = [group for key, group in existing.items() if key not in requested]
    return {group.key: group for group in ordered}, removed


def _remove_groups(invoice, removed):
    for group in removed:
        invoice.item_groups.remove(group)


def prepare_replace(db, invoice, body):
    load_groups(db, invoice)
    prior_group_ids = {item.id: item.group_id for item in invoice.items if item.id}
    definitions = getattr(body, "item_groups", None)
    if definitions is None:
        default = _default_group(db, invoice) if any(
            item.product_kind != "accessory" for item in body.items
        ) or invoice.item_groups else None
        by_key = {group.key: group for group in invoice.item_groups}
        by_id = {group.id: group for group in invoice.item_groups}

        def legacy_group(payload):
            if payload.product_kind == "accessory":
                if payload.group_key:
                    raise ValueError("配件明细不使用产品分组")
                return None
            if payload.group_key:
                if payload.group_key not in by_key:
                    raise ValueError("产品明细所属分组不存在")
                return by_key[payload.group_key]
            return by_id.get(prior_group_ids.get(payload.id)) or default

        return legacy_group

    groups, removed = _sync_explicit(db, invoice, definitions)
    for item in invoice.items:
        if item.group in removed:
            item.group = None
    _remove_groups(invoice, removed)
    db.flush()

    def explicit_group(payload):
        if payload.product_kind == "accessory":
            if payload.group_key:
                raise ValueError("配件明细不使用产品分组")
            return None
        if not payload.group_key or payload.group_key not in groups:
            raise ValueError("每条产品明细都必须归属一个有效分组")
        return groups[payload.group_key]

    return explicit_group


def update_local(db, identity, body, user):
    from app.invoice import edit_authority
    from app.invoice.linked_sync_service import edit_version, ensure_idle

    invoice, current = edit_authority.prepare_local(db, identity, user, "invoice:write")
    if invoice.transaction_mode == "local":
        from app.invoice.native_authority import require_write
        from app.invoice.transition_gate import require_invoice
        from app.customer.access_service import require_customer_access
        current = require_write(db, current, "invoice:write")
        if body.expected_authority_epoch is None:
            raise HTTPException(409, "订单办理权版本不能为空，请重新读取")
        require_invoice(db, invoice, "local", body.expected_authority_epoch)
        require_customer_access(db, customer_id=invoice.local_customer_id, user=current,
            action_permissions=["invoice:write"], manage_permissions=["customer:admin"])

    if invoice.transaction_mode == "local":
        if invoice.status in {"cancelled", "deleted"} or invoice.commerce_status in {"cancelled", "opening"}:
            raise HTTPException(409, "订单已取消或尚未完成承接，不能调整分组")
    else:
        ensure_idle(invoice)
    load_groups(db, invoice)
    if edit_version(invoice) != body.expected_version:
        raise HTTPException(409, "订单业务数据已被修改，请刷新后再调整分组")
    if version(invoice) != body.expected_groups_version:
        raise HTTPException(409, "明细分组已被他人修改，请刷新后再调整")

    current = {
        item.id: item for item in invoice.items
        if item.product_kind != "accessory" and not item.presale_archived
    }
    assignments = list(body.items)
    ids = [row.id for row in assignments]
    if len(ids) != len(set(ids)) or set(ids) != set(current):
        raise ValueError("产品明细已变化，请刷新后再调整分组")

    groups, removed = _sync_explicit(db, invoice, body.item_groups)
    for row in assignments:
        if row.group_key not in groups:
            raise ValueError("产品明细不能移动到已删除的分组")
        current[row.id].group = groups[row.group_key]
    for item in invoice.items:
        if item.group in removed:
            if not item.presale_archived:
                raise ValueError("非空分组不能直接删除，请先移动其中明细")
            item.group = None
    _remove_groups(invoice, removed)
    db.flush()
    return invoice
