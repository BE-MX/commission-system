"""External edits cannot silently rewrite goods already referenced by returns."""
from fastapi import HTTPException
from sqlalchemy import select

from app.sales_return.models import ReturnItem, SalesReturn
from app.sales_return.policy import money


def verify(db, snapshot):
    parents = db.scalars(select(SalesReturn).where(SalesReturn.order_id == snapshot["order_id"],
                                                  SalesReturn.status == "effective")).all()
    if not parents:
        return
    current_lines = {line["source_key"]: line for line in snapshot["lines"]}
    current_payments = {payment["payment_id"]: payment for payment in snapshot["payments"]}
    for parent in parents:
        old = parent.snapshot
        for key in ("customer_id", "currency", "owner_okki_user_id", "invoice_id", "gmv_eligible", "order_role", "departments"):
            if old.get(key) != snapshot.get(key):
                raise HTTPException(409, "原单身份、业绩归属或计入资格与已生效退货快照不一致，请先核对差异")
        for key in ("account_date", "raw_new_deal"):
            if key in old and old[key] != snapshot.get(key):
                raise HTTPException(409, "原核算日期或成交分类与已生效退货快照不一致，请先核对差异")
        if any(money(old[key]) != money(snapshot[key]) for key in ("goods_amount", "goods_amount_usd")):
            raise HTTPException(409, "原订单货款或美元折算与已入账退货快照不一致，请先核对差异")
        for previous in old.get("payments", []):
            current = current_payments.get(previous["payment_id"])
            if current is None or any(previous.get(key) != current.get(key) for key in
                    ("currency", "principal", "principal_usd", "commission_basis_usd")):
                raise HTTPException(409, "原回款本金、币种或计提依据已被外部修改，请先核对已生效退货")
    items = db.scalars(select(ReturnItem).where(ReturnItem.return_id.in_([parent.id for parent in parents]))).all()
    for item in items:
        current = current_lines.get(item.source_key)
        frozen = item.source_snapshot
        if current is None or any(str(getattr(item, key)) != str(current[key]) for key in
                ("outbound_id", "outbound_line_id", "order_line_id", "product_id", "sku_id")):
            raise HTTPException(409, "已退货的原出库行身份发生外部变动，请先核对原单")
        if (int(frozen.get("shipped_quantity", frozen["quantity"])) != int(current["quantity"])
                or any(money(frozen[key]) != money(current[key]) for key in ("net_amount", "net_amount_usd"))):
            raise HTTPException(409, "已退货原出库行的数量或净货值被外部修改，请先核对差异")
