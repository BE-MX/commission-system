"""Offline money conservation and source identity tests; no database or network."""
from decimal import Decimal
from itertools import product

import pytest

from app.invoice.presale_funding import FundingLot, plan_funding


def lot(identity, amount, purpose="presale_advance", **fields):
    return FundingLot(identity, purpose, amount, effective=True, **fields)


def test_veronika_advance_covers_goods_and_freight_once():
    result = plan_funding("627", "0", "38", [lot(1062, "1077")], is_final=False)
    assert result["additional_payment_due"] == "0.00"
    assert result["applied_amount"] == "665.00"
    assert result["balances"][0]["remaining_amount"] == "412.00"
    assert result["applications"] == [
        {"receipt_id": 1062, "component": "goods", "purpose": "presale_advance", "amount": "627.00", "bank_charge": "0.00"},
        {"receipt_id": 1062, "component": "freight", "purpose": "presale_advance", "amount": "38.00", "bank_charge": "0.00"}]


def test_deposit_is_reserved_until_manual_final_even_with_all_current_goods():
    result = plan_funding("627", "0", "38", [lot(1062, "1077", "presale_deposit")], is_final=False)
    assert result["applications"] == []
    assert result["additional_payment_due"] == "665.00"
    assert result["balances"][0]["remaining_amount"] == "1077.00"


def test_final_deposit_excess_remains_without_implicit_refund():
    result = plan_funding("627", "0", "38", [lot(1, "1077", "presale_deposit")], is_final=True)
    assert result["goods_payment_due"] == "0.00"
    assert result["freight_payment_due"] == "38.00"
    assert result["balances"][0]["remaining_amount"] == "450.00"


def test_multiple_advance_payments_and_final_deposit_have_stable_priority():
    lots = [lot(8, "100"), lot(9, "50", "presale_deposit"), lot(2, "25")]
    result = plan_funding("80", "0", "40", lots, is_final=True)
    assert [(a["receipt_id"], a["component"], a["amount"]) for a in result["applications"]] == [
        (9, "goods", "50.00"), (2, "goods", "25.00"), (8, "goods", "5.00"), (8, "freight", "40.00")]
    assert result == plan_funding("80", "0", "40", reversed(lots), is_final=True)


def test_next_batch_only_uses_unallocated_money_and_reservations_count():
    result = plan_funding("500", "0", "38", [lot(1062, "1077", allocated_amount="665")], is_final=False)
    assert result["applied_amount"] == "412.00"
    assert result["goods_payment_due"] == "88.00"
    assert result["freight_payment_due"] == "38.00"
    assert result["additional_payment_due"] == "126.00"


def test_pending_money_cannot_fund_delivery():
    pending = FundingLot(1, "presale_advance", "100")
    result = plan_funding("1", "0", "1", [pending], is_final=False)
    assert result["applications"] == []
    assert result["additional_payment_due"] == "2.00"
    assert result["balances"][0]["effective"] is False


def test_bank_charge_never_funds_freight_or_goods_principal():
    result = plan_funding("96", "2", "3", [lot(1, "100", bank_charge="4")], is_final=False)
    assert result["applied_amount"] == "98.00"
    assert result["additional_payment_due"] == "3.00"
    assert result["balances"][0]["remaining_amount"] == "2.00"
    assert result["balances"][0]["remaining_principal"] == "0.00"


def test_partial_bank_charge_is_conserved_across_batches():
    result = plan_funding("20", "1", "5", [lot(1, "103", bank_charge="3", allocated_amount="52", allocated_charge="2")], is_final=False)
    assert result["applications"][0]["bank_charge"] == "1.00"
    assert result["balances"][0]["remaining_amount"] == "25.00"
    assert result["balances"][0]["remaining_charge"] == "0.00"


@pytest.mark.parametrize("goods,handling,freight", [("90", "5", "5"), ("0", "5", "0")])
def test_cash_principal_can_pay_batch_handling(goods, handling, freight):
    result = plan_funding(goods, handling, freight, [lot(1, "100")], is_final=False)
    assert result["additional_payment_due"] == "0.00"
    assert result["applied_amount"] == str((Decimal(goods) + Decimal(handling) + Decimal(freight)).quantize(Decimal("0.01")))
    assert all(row["bank_charge"] == "0.00" for row in result["applications"])


def test_later_bank_charge_is_used_before_cash_pays_handling():
    result = plan_funding("5", "5", "10", [lot(1, "10"), lot(2, "10", bank_charge="5")], is_final=False)
    assert result["additional_payment_due"] == "0.00"
    assert result["applied_amount"] == "20.00"
    assert result["applications"] == [
        {"receipt_id": 1, "component": "goods", "purpose": "presale_advance", "amount": "5.00", "bank_charge": "0.00"},
        {"receipt_id": 1, "component": "freight", "purpose": "presale_advance", "amount": "5.00", "bank_charge": "0.00"},
        {"receipt_id": 2, "component": "goods", "purpose": "presale_advance", "amount": "5.00", "bank_charge": "5.00"},
        {"receipt_id": 2, "component": "freight", "purpose": "presale_advance", "amount": "5.00", "bank_charge": "0.00"}]


@pytest.mark.parametrize("values", [
    {"amount": "100", "bank_charge": "101"},
    {"amount": "100", "bank_charge": "100"},
    {"amount": "0"}, {"amount": "100", "allocated_amount": "101"},
    {"amount": "100", "bank_charge": "3", "allocated_amount": "98", "allocated_charge": "0"},
    {"amount": "100", "bank_charge": "3", "allocated_amount": "2", "allocated_charge": "3"},
    {"amount": "100", "bank_charge": "3", "allocated_charge": "4"},
    {"amount": "NaN"}, {"amount": "1.001"}, {"amount": "-1"},
])
def test_invalid_original_or_allocated_money_is_rejected(values):
    with pytest.raises(ValueError):
        plan_funding("1", "0", "1", [lot(1, **values)], is_final=False)


@pytest.mark.parametrize("final", [None, "true", 1, 0])
def test_final_requires_boolean_human_choice(final):
    with pytest.raises(ValueError, match="explicitly"):
        plan_funding("1", "0", "1", [], is_final=final)


def test_duplicate_receipt_is_never_double_spent():
    with pytest.raises(ValueError, match="Duplicate"):
        plan_funding("100", "0", "100", [lot(1, "100"), lot(1, "100")], is_final=False)


@pytest.mark.parametrize("purpose", ["ordinary", "presale_goods", "freight", "", None])
def test_unclassified_or_batch_money_cannot_be_used_as_advance(purpose):
    with pytest.raises(ValueError, match="identity"):
        plan_funding("1", "0", "1", [lot(1, "10", purpose)], is_final=False)


def test_cent_level_money_conservation_for_many_batches():
    lots = [lot(1, "17.23", bank_charge="0.53"), lot(2, "11.43"), lot(3, "6.12", "presale_deposit", bank_charge="0.12")]
    original = sum(Decimal(row.amount) for row in lots)
    spent = Decimal(0)
    for index in range(12):
        result = plan_funding("1.23", "0.05", "0.41", lots, is_final=index == 11)
        spent += Decimal(result["applied_amount"])
        remaining = {row["receipt_id"]: row for row in result["balances"]}
        assert spent + sum(Decimal(row["remaining_amount"]) for row in remaining.values()) == original
        lots = [lot(row.receipt_id, row.amount, row.purpose, bank_charge=row.bank_charge,
            allocated_amount=str(Decimal(row.amount) - Decimal(remaining[row.receipt_id]["remaining_amount"])),
            allocated_charge=str(Decimal(row.bank_charge) - Decimal(remaining[row.receipt_id]["remaining_charge"]))) for row in lots]


def test_funding_matches_independent_capacity_bound_for_248_cent_cases():
    lots = [lot(1, "0.04"), lot(2, "0.04", bank_charge="0.02"),
        lot(3, "0.06", "presale_deposit", bank_charge="0.02")]
    for final in (False, True):
        for goods, handling, freight in product(range(5), repeat=3):
            if goods + handling + freight == 0:
                continue
            # Fee can only pay handling; deposits can never pay freight.
            # These independent capacities give a lower bound on unpaid money.
            eligible_charge = 4 if final else 2
            fee_paid = min(handling, eligible_charge)
            principal = 10 if final else 6
            needed = goods + handling - fee_paid + freight
            expected_unpaid = max(0, needed - principal, freight - 6)
            result = plan_funding(*(f"{value / 100:.2f}" for value in (goods, handling, freight)), lots, is_final=final)
            assert Decimal(result["additional_payment_due"]) == Decimal(expected_unpaid) / 100
