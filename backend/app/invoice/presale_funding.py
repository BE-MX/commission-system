"""Offline funding plan for mutable presales; never creates money or sends OKKI writes.

The caller must capture current receipt facts and all reserved/applied allocations
under the invoice/receipt locks. A plan is only a quote, never a payment authority.
Bank charges can fund the batch handling component, never goods or freight.
"""
from dataclasses import dataclass

from app.invoice.settlement_pricing import _cents, _format


@dataclass(frozen=True)
class FundingLot:
    receipt_id: int
    purpose: str
    amount: str
    bank_charge: str = "0"
    allocated_amount: str = "0"
    allocated_charge: str = "0"
    effective: bool = False


def _remaining(lot):
    if (type(lot.receipt_id) is not int or lot.receipt_id <= 0
            or lot.purpose not in {"presale_deposit", "presale_advance"}
            or type(lot.effective) is not bool):
        raise ValueError("Invalid presale funding identity")
    amount, charge, used, used_charge = (
        _cents(value, name) for value, name in (
            (lot.amount, "amount"), (lot.bank_charge, "bank_charge"),
            (lot.allocated_amount, "allocated_amount"),
            (lot.allocated_charge, "allocated_charge")))
    if (amount <= 0 or charge >= amount or used > amount or used_charge > charge
            or used_charge > used or used - used_charge > amount - charge):
        raise ValueError("Presale funding allocations exceed the original payment")
    return amount - used, charge - used_charge


def plan_funding(goods, handling, freight, lots, *, is_final):
    """Use deposits only at manual final; advance principal covers goods + freight.

    Goods includes packaging, excludes handling. All amounts are exact cents.
    Deposits take priority on final. Within each class use ascending receipt ID.
    Pending/failed/uncertain or unverified receipts cannot fund any shipment.
    Every returned application is a reference to its original actual receipt.
    Remaining funds survive a final batch; this function performs no refunds.
    """
    if type(is_final) is not bool:
        raise ValueError("The final batch must be explicitly confirmed")
    g, h, f = (_cents(value, name) for value, name in (
        (goods, "goods"), (handling, "handling"), (freight, "freight")))
    if g + h + f == 0:
        raise ValueError("A shipment must have a positive payable amount")
    lots = tuple(lots)
    if len({lot.receipt_id for lot in lots}) != len(lots):
        raise ValueError("Duplicate presale receipt")
    remaining = {lot.receipt_id: _remaining(lot) for lot in lots}
    ordered = sorted(lots, key=lambda lot: (lot.purpose != "presale_deposit", lot.receipt_id))
    eligible = [lot for lot in ordered if lot.effective
        and (lot.purpose != "presale_deposit" or is_final)]
    # Use eligible charge balances before consuming cash to pay handling.
    # Otherwise an earlier fee-free receipt can waste the only destination of
    # a later receipt's bank-charge balance and incorrectly demand new money.
    handling_allocations = {}
    for lot in eligible:
        gross, charge = remaining[lot.receipt_id]
        handling_part = min(charge, h)
        h -= handling_part
        handling_allocations[lot.receipt_id] = handling_part
        remaining[lot.receipt_id] = (gross - handling_part, charge - handling_part)
    applications = []
    for lot in eligible:
        gross, charge = remaining[lot.receipt_id]
        principal = gross - charge
        handling_part = handling_allocations[lot.receipt_id]
        goods_principal = min(principal, g)
        g -= goods_principal
        principal -= goods_principal
        handling_principal = min(principal, h)
        h -= handling_principal
        principal -= handling_principal
        goods_part = goods_principal + handling_principal + handling_part
        if goods_part:
            applications.append({"receipt_id": lot.receipt_id, "component": "goods",
                "purpose": lot.purpose, "amount": _format(goods_part),
                "bank_charge": _format(handling_part)})
        freight_part = min(principal, f) if lot.purpose == "presale_advance" else 0
        f -= freight_part
        if freight_part:
            applications.append({"receipt_id": lot.receipt_id, "component": "freight",
                "purpose": lot.purpose, "amount": _format(freight_part), "bank_charge": "0.00"})
        remaining[lot.receipt_id] = (gross - goods_principal - handling_principal - freight_part, charge)
    applied = sum(_cents(row["amount"], "application") for row in applications)
    return {"is_final": is_final, "applications": applications,
        "applied_amount": _format(applied), "goods_payment_due": _format(g + h),
        "goods_charge_due": _format(h), "freight_payment_due": _format(f),
        "additional_payment_due": _format(g + h + f),
        "balances": [{"receipt_id": lot.receipt_id, "purpose": lot.purpose,
            "effective": lot.effective, "remaining_amount": _format(remaining[lot.receipt_id][0]),
            "remaining_charge": _format(remaining[lot.receipt_id][1]),
            "remaining_principal": _format(remaining[lot.receipt_id][0] - remaining[lot.receipt_id][1])}
            for lot in sorted(lots, key=lambda lot: lot.receipt_id)]}
