"""Preview or apply the authorized business-order channel data conversion.

No schema changes and no financial settlement. Keep a pre-write backup, lock
orders then customers, and require the reviewed snapshot hash before applying.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from sqlalchemy import bindparam, text

from app.core.time import beijing_now

CHANNELS = (("recharge", "充值扣账"), ("cash", "现金结账"))
DICT_TYPE = "domestic_order_channel"


def _rows(connection, sql, **params):
    statement = text(sql)
    for key, value in params.items():
        if isinstance(value, list):
            statement = statement.bindparams(bindparam(key, expanding=True))
    return [dict(row) for row in connection.execute(statement, params).mappings()]


def fingerprint(snapshot):
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def snapshot(connection, *, lock=False):
    suffix = " FOR UPDATE" if lock and connection.dialect.name != "sqlite" else ""
    orders = _rows(connection, "SELECT id,customer_id,order_channel,updated_at FROM ark_domestic_orders WHERE order_kind='business' ORDER BY id" + suffix)
    customer_ids = sorted({row["customer_id"] for row in orders})
    customers = _rows(connection, "SELECT id,settle_mode FROM ark_domestic_customers WHERE id IN :ids ORDER BY id" + suffix, ids=customer_ids) if customer_ids else []
    modes = {row["id"]: row["settle_mode"] for row in customers}
    if any(modes.get(row["customer_id"]) not in ("prepay", "credit") for row in orders):
        raise ValueError("业务订单缺客户或客户结算方式未知，拒绝推断订单渠道")
    dictionaries = _rows(connection, "SELECT * FROM sys_dict WHERE type=:kind ORDER BY id" + suffix, kind=DICT_TYPE)
    if len({row["code"] for row in dictionaries}) != len(dictionaries):
        raise ValueError("订单渠道字典编码重复")
    return {"orders": orders, "customers": customers, "dictionaries": dictionaries}


def summarize(before):
    modes = {row["id"]: row["settle_mode"] for row in before["customers"]}
    channels = ["cash" if modes[row["customer_id"]] == "credit" else "recharge" for row in before["orders"]]
    return {"orders": len(channels), "channels": dict(Counter(channels)),
            "changed_orders": sum(row["order_channel"] != target for row, target in zip(before["orders"], channels)),
            "fingerprint": fingerprint(before)}


def apply_conversion(connection, before):
    """Caller owns the transaction; only labels/codes and order_channel change."""
    now = beijing_now()
    modes = {row["id"]: row["settle_mode"] for row in before["customers"]}
    order_ids = [row["id"] for row in before["orders"]]
    def protected_values():
        orders = _rows(connection, "SELECT * FROM ark_domestic_orders WHERE id IN :ids ORDER BY id", ids=order_ids) if order_ids else []
        return [{key:value for key,value in row.items() if key not in ("order_channel", "updated_at")} for row in orders]
    protected = fingerprint(protected_values())
    for row in before["orders"]:
        target = "cash" if modes[row["customer_id"]] == "credit" else "recharge"
        if row["order_channel"] != target:
            connection.execute(text("UPDATE ark_domestic_orders SET order_channel=:channel,updated_at=:now WHERE id=:id"),
                               {"id": row["id"], "channel": target, "now": now})
    existing = {row["code"]: row for row in before["dictionaries"]}
    for sort, (code, label) in enumerate(CHANNELS):
        if code in existing:
            connection.execute(text("UPDATE sys_dict SET label=:label,sort=:sort,is_active=1,updated_at=:now WHERE id=:id"),
                               {"label": label, "sort": sort, "now": now, "id": existing[code]["id"]})
        else:
            connection.execute(text("INSERT INTO sys_dict (type,code,label,sort,is_active,created_at,updated_at) VALUES (:kind,:code,:label,:sort,1,:now,:now)"),
                               {"kind": DICT_TYPE, "code": code, "label": label, "sort": sort, "now": now})
    # Retain retired values for audit, but never offer them for new selection.
    connection.execute(text("UPDATE sys_dict SET is_active=0,updated_at=:now WHERE type=:kind AND code NOT IN ('recharge','cash') AND is_active=1"),
                       {"kind": DICT_TYPE, "now": now})
    after = snapshot(connection, lock=True)
    if summarize(after)["changed_orders"]:
        raise ValueError("订单渠道转换后核验失败")
    options = [(row["code"], row["label"]) for row in sorted(after["dictionaries"], key=lambda row: (row["sort"], row["id"])) if row["is_active"]]
    if options != list(CHANNELS):
        raise ValueError("渠道选项核验失败")
    if fingerprint(protected_values()) != protected:
        raise ValueError("订单非渠道字段发生变化，拒绝提交")
    return after


def main():
    from app.core.database import engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected", help="fingerprint returned by the read-only preview")
    parser.add_argument("--backup", type=Path, help="new local JSON backup path")
    args = parser.parse_args()
    with engine.begin() as connection:
        before = snapshot(connection, lock=args.apply)
        summary = summarize(before)
        if not args.apply:
            print(json.dumps(summary, ensure_ascii=False))
            return
        if args.expected != fingerprint(before) or not args.backup:
            raise ValueError("必须提供当前预检 fingerprint 和新备份路径")
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with args.backup.open("x", encoding="utf-8") as backup:
            json.dump(before, backup, ensure_ascii=False, default=str, indent=2)
        if fingerprint(json.loads(args.backup.read_text(encoding="utf-8"))) != fingerprint(json.loads(json.dumps(before, default=str))):
            raise ValueError("备份核验失败")
        after = apply_conversion(connection, before)
    print(json.dumps({**summary, "status": "committed", "after_fingerprint": fingerprint(after)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
