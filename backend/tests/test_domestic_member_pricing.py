from datetime import date, datetime
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import inspect
from pathlib import Path
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    event,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic import balance_service, customer_service, pricing_service
from app.domestic import models as domestic_models
from app.domestic.schemas import CustomerCreate, CustomerRechargeCreate, CustomerUpdate


D = Decimal


@pytest.mark.parametrize(
    ("last_successful_recharge", "expected"),
    [
        (None, None),
        (D("0"), None),
        (D("9999.99"), None),
        (D("10000"), "silver"),
        (D("29999.99"), "silver"),
        (D("30000"), "black"),
        (D("99999.99"), "black"),
        (D("100000"), "supreme"),
        (D("999999"), "supreme"),
    ],
)
def test_membership_uses_only_latest_successful_recharge(
    last_successful_recharge, expected
):
    assert pricing_service.resolve_membership(last_successful_recharge) == expected


@pytest.mark.parametrize(
    ("membership_level", "expected"),
    [
        (None, "非会员"),
        ("silver", "银卡会员"),
        ("black", "黑卡会员"),
        ("supreme", "至尊会员"),
    ],
)
def test_membership_label_is_centralized_and_explicit(membership_level, expected):
    assert pricing_service.membership_label(membership_level) == expected


def test_membership_label_rejects_unknown_values():
    with pytest.raises(pricing_service.PricingConfigurationError, match="会员等级"):
        pricing_service.membership_label("gold")


@pytest.mark.parametrize("schema", [CustomerCreate, CustomerUpdate])
def test_customer_write_schemas_forbid_membership_level(schema):
    payload = {"membership_level": "supreme"}
    if schema is CustomerCreate:
        payload["shop_name"] = "禁止手改会员"
    with pytest.raises(ValidationError, match="membership_level"):
        schema.model_validate(payload)


@pytest.mark.parametrize("request_id", [None, "", "        ", " short "])
def test_recharge_schema_requires_trimmed_request_id(request_id):
    payload = {"amount": "10000.00"}
    if request_id is not None:
        payload["request_id"] = request_id
    with pytest.raises(ValidationError, match="request_id"):
        CustomerRechargeCreate.model_validate(payload)


def test_recharge_schema_strips_request_id():
    payload = CustomerRechargeCreate(
        amount=D("10000.00"), request_id="  recharge-request-001  "
    )
    assert payload.request_id == "recharge-request-001"


def test_recharge_schema_accepts_full_database_money_limit():
    payload = CustomerRechargeCreate(
        amount=D("999999999999.99"), request_id="max-money-request"
    )
    assert payload.amount == D("999999999999.99")


def _membership_customer(db, user, suffix, **overrides):
    values = {
        "shop_name": f"充值会员客户-{suffix}",
        "created_by": user.id,
    }
    values.update(overrides)
    customer = domestic_models.DomesticCustomer(**values)
    db.add(customer)
    db.flush()
    return customer


def _recharge(db, customer, user, amount, request_id):
    return balance_service.recharge_customer(
        db,
        customer_id=customer.id,
        amount=D(amount),
        user_id=user.id,
        request_id=request_id,
    )


@pytest.mark.parametrize(
    ("amount", "expected_level", "expected_label"),
    [
        ("9999.99", None, "非会员"),
        ("10000.00", "silver", "银卡会员"),
        ("29999.99", "silver", "银卡会员"),
        ("30000.00", "black", "黑卡会员"),
        ("99999.99", "black", "黑卡会员"),
        ("100000.00", "supreme", "至尊会员"),
    ],
)
def test_new_recharge_derives_membership_from_that_single_amount(
    db, amount, expected_level, expected_label
):
    user = _operator(db, f"threshold-{amount}")
    customer = _membership_customer(db, user, amount)

    result = _recharge(
        db, customer, user, amount, f"threshold-{amount}-request"
    )
    db.refresh(customer)
    ledger = db.get(domestic_models.DomesticCustomerLedger, result["ledger_id"])

    assert customer.membership_level == expected_level
    assert customer.last_recharge_amount == D(amount)
    assert customer.last_recharged_at == ledger.created_at
    assert result == {
        "ledger_id": ledger.id,
        "amount": float(D(amount)),
        "ledger_balance_after": float(D(amount)),
        "current_balance": float(D(amount)),
        "membership_level": expected_level,
        "membership_label": expected_label,
        "last_recharge_amount": float(D(amount)),
        "last_recharged_at": ledger.created_at,
        "membership_change": (
            {"from": None, "to": expected_level} if expected_level else None
        ),
        "replayed": False,
    }
    assert "balance" not in result


def test_recharge_can_upgrade_downgrade_and_remove_membership(db):
    user = _operator(db, "membership-transitions")
    customer = _membership_customer(db, user, "transitions")

    silver = _recharge(db, customer, user, "10000", "transition-silver")
    supreme = _recharge(db, customer, user, "100000", "transition-supreme")
    black = _recharge(db, customer, user, "30000", "transition-black")
    non_member = _recharge(db, customer, user, "9999.99", "transition-none")

    assert silver["membership_change"] == {"from": None, "to": "silver"}
    assert supreme["membership_change"] == {"from": "silver", "to": "supreme"}
    assert black["membership_change"] == {"from": "supreme", "to": "black"}
    assert non_member["membership_change"] == {"from": "black", "to": None}
    assert non_member["membership_level"] is None
    assert non_member["membership_label"] == "非会员"


def test_membership_ignores_current_balance_and_recharge_history(db):
    user = _operator(db, "single-recharge-only")
    rich_customer = _membership_customer(
        db,
        user,
        "rich",
        balance=D("500000.00"),
        membership_level="supreme",
        last_recharge_amount=D("100000.00"),
    )
    rich_result = _recharge(
        db, rich_customer, user, "9999.99", "rich-small-recharge"
    )
    assert rich_result["current_balance"] == 509999.99
    assert rich_result["membership_level"] is None

    cumulative_customer = _membership_customer(db, user, "cumulative")
    _recharge(db, cumulative_customer, user, "6000", "cumulative-first")
    cumulative_result = _recharge(
        db, cumulative_customer, user, "5000", "cumulative-second"
    )
    assert cumulative_result["current_balance"] == 11000.0
    assert cumulative_result["membership_level"] is None
    assert cumulative_result["last_recharge_amount"] == 5000.0


def test_old_recharge_replay_preserves_current_membership_snapshot(db):
    user = _operator(db, "old-replay")
    customer = _membership_customer(db, user, "old-replay")
    old = _recharge(db, customer, user, "30000", "old-recharge-request")
    latest = _recharge(db, customer, user, "100000", "latest-recharge-request")

    replay = _recharge(db, customer, user, "30000", "old-recharge-request")

    assert replay["ledger_id"] == old["ledger_id"]
    assert replay["amount"] == 30000.0
    assert replay["ledger_balance_after"] == 30000.0
    assert replay["current_balance"] == 130000.0
    assert replay["membership_level"] == "supreme"
    assert replay["membership_label"] == "至尊会员"
    assert replay["last_recharge_amount"] == 100000.0
    assert replay["last_recharged_at"] == latest["last_recharged_at"]
    assert replay["membership_change"] is None
    assert replay["replayed"] is True

    db.refresh(customer)
    assert customer.membership_level == "supreme"
    assert customer.last_recharge_amount == D("100000.00")
    assert customer.last_recharged_at == latest["last_recharged_at"]
    assert db.query(domestic_models.DomesticCustomerLedger).count() == 2


def test_recharge_replay_rejects_same_request_with_different_amount(db):
    user = _operator(db, "replay-mismatch")
    customer = _membership_customer(db, user, "replay-mismatch")
    _recharge(db, customer, user, "10000", "same-request-amount")

    with pytest.raises(ValueError, match="不同金额"):
        _recharge(db, customer, user, "30000", "same-request-amount")


@pytest.mark.parametrize("request_id", [None, "", "       "])
def test_recharge_service_defensively_requires_request_id(db, request_id):
    user = _operator(db, f"missing-request-{request_id!r}")
    customer = _membership_customer(db, user, f"missing-{request_id!r}")
    with pytest.raises(ValueError, match="幂等键"):
        balance_service.recharge_customer(
            db,
            customer_id=customer.id,
            amount=D("10000"),
            user_id=user.id,
            request_id=request_id,
        )


def test_customer_service_never_writes_membership_level(db):
    user = _operator(db, "customer-service-membership")
    created = customer_service.create_customer(
        db,
        CustomerCreate(shop_name="服务层新客户", province="山东省"),
        user.id,
    )
    assert created.membership_level is None

    created.membership_level = "black"
    created.last_recharge_amount = D("30000.00")
    db.commit()
    customer_service.update_customer(
        db, created.id, CustomerUpdate(province="河南省")
    )
    db.refresh(created)
    assert created.membership_level == "black"
    assert created.last_recharge_amount == D("30000.00")


def _customer_api_client(db, user_id, *, raise_server_exceptions=True):
    from app.domestic.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user_id),
        "roles": [],
        "permissions": [
            "domestic:read",
            "domestic:write",
            "domestic:recharge",
        ],
    }
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_customer_api_rejects_manual_membership_and_missing_request_id(db):
    user = _operator(db, "customer-api-validation")
    customer = _membership_customer(db, user, "api-validation")
    client = _customer_api_client(db, user.id)

    create_response = client.post(
        "/api/domestic/customers",
        json={"shop_name": "接口手改会员", "membership_level": "supreme"},
    )
    update_response = client.put(
        f"/api/domestic/customers/{customer.id}",
        json={"membership_level": "supreme"},
    )
    missing_response = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        json={"amount": 10000},
    )
    blank_response = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        json={"amount": 10000, "request_id": "        "},
    )

    assert create_response.status_code == 422
    assert update_response.status_code == 422
    assert missing_response.status_code == 422
    assert blank_response.status_code == 422


def test_customer_api_returns_recharge_and_list_membership_contract(db):
    user = _operator(db, "customer-api-contract")
    customer = _membership_customer(db, user, "api-contract")
    client = _customer_api_client(db, user.id)

    recharge_response = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        json={"amount": 30000, "request_id": "api-contract-recharge"},
    )
    replay_response = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        json={"amount": 30000, "request_id": "api-contract-recharge"},
    )
    list_response = client.get("/api/domestic/customers")

    assert recharge_response.status_code == 200
    assert recharge_response.json()["message"] == "充值成功"
    assert "balance" not in recharge_response.json()["data"]
    assert replay_response.status_code == 200
    assert replay_response.json()["message"] == "该笔充值已经处理过，当前会员状态以返回结果为准"
    item = list_response.json()["data"]["items"][0]
    assert item["membership_level"] == "black"
    assert item["membership_label"] == "黑卡会员"
    assert item["last_recharge_amount"] == 30000.0
    assert item["last_recharged_at"] == recharge_response.json()["data"]["last_recharged_at"]


def test_recharge_api_rolls_back_before_returning_business_error(db, monkeypatch):
    user = _operator(db, "customer-api-rollback")
    customer = _membership_customer(db, user, "api-rollback", remark="原备注")
    db.commit()
    client = _customer_api_client(db, user.id)

    def fail_after_write(session, **_kwargs):
        stored = session.get(domestic_models.DomesticCustomer, customer.id)
        stored.remark = "不应提交"
        session.flush()
        raise ValueError("模拟充值失败")

    monkeypatch.setattr(balance_service, "recharge_customer", fail_after_write)
    response = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        json={"amount": 30000, "request_id": "api-rollback-request"},
    )

    assert response.status_code == 400
    db.refresh(customer)
    assert customer.remark == "原备注"


def test_recharge_api_rolls_back_unexpected_errors(db, monkeypatch):
    user = _operator(db, "customer-api-unexpected-rollback")
    customer = _membership_customer(
        db, user, "api-unexpected-rollback", remark="原备注"
    )
    db.commit()
    client = _customer_api_client(
        db, user.id, raise_server_exceptions=False
    )

    def fail_after_write(session, **_kwargs):
        stored = session.get(domestic_models.DomesticCustomer, customer.id)
        stored.remark = "不应提交"
        session.flush()
        raise RuntimeError("模拟数据库提交失败")

    monkeypatch.setattr(balance_service, "recharge_customer", fail_after_write)
    response = client.post(
        f"/api/domestic/customers/{customer.id}/recharges",
        json={"amount": 30000, "request_id": "unexpected-rollback-request"},
    )

    assert response.status_code == 500
    db.refresh(customer)
    assert customer.remark == "原备注"


def test_member_reductions_are_explicit():
    assert pricing_service.MEMBERSHIP_REDUCTIONS == {
        "silver": D("70.00"),
        "black": D("120.00"),
        "supreme": D("130.00"),
    }


PIECE_SOURCE_ROWS = {
    "全递针": {
        "9*14": (840, 960, 1040, 1290),
        "12*14": (1040, 1140, 1200, 1420),
        "13*15": (1090, 1180, 1350, 1500),
        "14*16": (1160, 1260, 1380, 1630),
        "15*17": (1490, 1580, 1710, 1900),
        "16*18": (1510, 1610, 1760, 1950),
        "18*20": (1760, 1910, 2000, None),
    },
    "递针旋": {
        "9*14": (840, 960, 1040, 1290),
        "12*14": (1040, 1140, 1200, 1420),
        "13*15": (1090, 1180, 1350, 1500),
        "14*16": (1160, 1260, 1380, 1630),
        "15*17": (1490, 1580, 1710, 1900),
        "16*18": (1510, 1610, 1760, 1950),
        "18*20": (1760, 1910, 2000, None),
    },
    "U型递针": {
        "13*15": (1060, 1150, 1320, 1470),
        "14*16": (1130, 1230, 1350, 1600),
        "15*17": (1460, 1550, 1680, 1870),
        "16*18": (1480, 1580, 1730, 1920),
    },
    "递针中分界": {
        "12*14": (980, 1080, 1140, 1360),
        "13*15": (1030, 1120, 1040, 1440),
        "14*16": (1100, 1200, 1320, 1570),
        "15*17": (1430, 1520, 1650, 1840),
        "16*18": (1450, 1550, 1700, 1890),
    },
    "递针左分界": {
        "12*14": (980, 1080, 1140, 1360),
        "13*15": (1030, 1120, 1040, 1440),
        "14*16": (1100, 1200, 1320, 1570),
        "15*17": (1430, 1520, 1650, 1840),
        "16*18": (1450, 1550, 1700, 1890),
    },
}

CAP_SOURCE_ROWS = {
    "递旋": (1198, 1498, 1798, 1998, 2050, 2700),
    "递顶": (None, 1798, 2198, 2498, 2650, 3300),
    "中分界": (None, 1598, 1898, 2198, 2298, 2900),
    "左分界": (None, 1598, 1898, 2198, 2298, 2900),
}

EXPECTED_COMBINED_PIECE_CODES = {
    f"{prefix}{size}": (craft, size)
    for craft, prefix in {
        "全递针": "全递针",
        "递针旋": "递针旋",
        "U型递针": "U型",
        "递针中分界": "递针中分界",
        "递针左分界": "递针左分界",
    }.items()
    for size in PIECE_SOURCE_ROWS[craft]
}


def _expected_seed_matrix():
    expected = {}
    piece_lengths = ("25厘米", "30厘米", "35厘米", "40厘米")
    for craft, sizes in PIECE_SOURCE_ROWS.items():
        for size, prices in sizes.items():
            for length, price in zip(piece_lengths, prices):
                if price is not None:
                    expected[("piece", craft, size, length)] = D(f"{price}.00")

    cap_lengths = (
        "15厘米", "20厘米", "25厘米", "30厘米", "35厘米", "40厘米"
    )
    for craft, prices in CAP_SOURCE_ROWS.items():
        for length, price in zip(cap_lengths, prices):
            if price is not None:
                expected[("cap", craft, None, length)] = D(f"{price}.00")
    return expected


def test_base_price_seed_matrix_matches_all_confirmed_source_values_only():
    expected = _expected_seed_matrix()
    assert pricing_service.BASE_PRICE_SEED_MATRIX == expected


def test_persistence_seed_rows_use_unique_three_column_product_keys():
    rows = list(pricing_service.iter_base_price_seeds())
    keys = [(product_type, craft, length) for product_type, craft, length, _ in rows]
    expected = {}
    combined_by_pair = {
        pair: combined for combined, pair in EXPECTED_COMBINED_PIECE_CODES.items()
    }
    for (product_type, craft, size, length), price in _expected_seed_matrix().items():
        persisted_craft = (
            combined_by_pair[(craft, size)] if product_type == "piece" else craft
        )
        expected[(product_type, persisted_craft, length)] = price

    assert len(keys) == len(set(keys))
    assert dict((key, row[-1]) for key, row in zip(keys, rows)) == expected


def test_matrix_key_builder_is_private_and_persistence_builder_is_public():
    assert not hasattr(pricing_service, "build_price_key")
    assert callable(pricing_service.build_persistence_price_key)


def test_unseeded_current_cap_craft_builds_persistence_key():
    assert pricing_service.build_persistence_price_key(
        product_type="cap", craft="大U型", size="59", length="25厘米"
    ) == ("cap", "大U型", "25厘米")


@pytest.mark.parametrize(
    "attrs",
    [
        {"product_type": "unknown", "craft": "递旋", "size": None, "length": "15厘米"},
        {"product_type": "cap", "craft": "递针旋全头套", "size": None, "length": "15厘米"},
        {"product_type": "piece", "craft": "全递针", "size": None, "length": "25厘米"},
        {"product_type": "piece", "craft": "全递针未知", "size": None, "length": "25厘米"},
        {"product_type": "piece", "craft": "全递针", "size": "99*99", "length": "25厘米"},
    ],
)
def test_unknown_persistence_price_dimensions_return_none(attrs):
    assert pricing_service.build_persistence_price_key(**attrs) is None


def test_all_seed_rows_round_trip_through_public_persistence_builder():
    persisted_rows = list(pricing_service.iter_base_price_seeds())
    persisted_by_key = {
        (product_type, craft, length): price
        for product_type, craft, length, price in persisted_rows
    }
    combined_by_pair = {
        pair: combined for combined, pair in EXPECTED_COMBINED_PIECE_CODES.items()
    }

    for product_type, craft, length, price in persisted_rows:
        assert pricing_service.build_persistence_price_key(
            product_type=product_type,
            craft=craft,
            size=None,
            length=length,
        ) == (product_type, craft, length)

    for (product_type, craft, size, length), price in _expected_seed_matrix().items():
        canonical_key = pricing_service.build_persistence_price_key(
            product_type=product_type,
            craft=craft,
            size=size,
            length=length,
        )
        assert persisted_by_key[canonical_key] == price
        if product_type == "piece":
            combined_key = pricing_service.build_persistence_price_key(
                product_type="piece",
                craft=combined_by_pair[(craft, size)],
                size=None,
                length=length,
            )
            assert combined_key == canonical_key


@pytest.mark.parametrize(
    ("size", "length"),
    [
        (size, length)
        for size, prices in PIECE_SOURCE_ROWS["全递针"].items()
        for length, price in zip(
            ("25厘米", "30厘米", "35厘米", "40厘米"), prices
        )
        if price is not None
    ],
)
def test_piece_full_needle_and_needle_spin_have_identical_matrices(size, length):
    assert pricing_service.get_base_price(
        product_type="piece", craft="全递针", size=size, length=length
    ) == pricing_service.get_base_price(
        product_type="piece", craft="递针旋", size=size, length=length
    )


@pytest.mark.parametrize(
    ("size", "length"),
    [
        (size, length)
        for size in PIECE_SOURCE_ROWS["递针中分界"]
        for length in ("25厘米", "30厘米", "35厘米", "40厘米")
    ],
)
def test_piece_middle_and_left_part_have_identical_matrices(size, length):
    assert pricing_service.get_base_price(
        product_type="piece", craft="递针中分界", size=size, length=length
    ) == pricing_service.get_base_price(
        product_type="piece", craft="递针左分界", size=size, length=length
    )


@pytest.mark.parametrize(
    ("craft", "length", "expected"),
    [
        (craft, length, price)
        for craft, prices in CAP_SOURCE_ROWS.items()
        for length, price in zip(
            ("15厘米", "20厘米", "25厘米", "30厘米", "35厘米", "40厘米"),
            prices,
        )
        if price is not None
    ],
)
def test_current_cap_craft_codes_resolve_confirmed_prices(craft, length, expected):
    assert pricing_service.get_base_price(
        product_type="cap", craft=craft, size="59", length=length
    ) == D(f"{expected}.00")


def test_confirmed_boundary_price_is_not_smoothed():
    assert pricing_service.get_base_price(
        product_type="piece", craft="递针中分界", size="13*15", length="35厘米"
    ) == D("1040.00")


@pytest.mark.parametrize(
    "attrs",
    [
        {"product_type": "piece", "craft": "全递针", "size": "18*20", "length": "40厘米"},
        {"product_type": "piece", "craft": "U型递针", "size": "9*14", "length": "25厘米"},
        {"product_type": "cap", "craft": "递顶", "size": None, "length": "15厘米"},
        {"product_type": "cap", "craft": "大U型", "size": None, "length": "25厘米"},
    ],
)
def test_unconfirmed_combinations_remain_without_price(attrs):
    assert pricing_service.get_base_price(**attrs) is None


@pytest.mark.parametrize(
    ("craft", "length", "expected"),
    [
        ("全递针18*20", "25厘米", "1760.00"),
        ("递针旋9*14", "25厘米", "840.00"),
        ("U型15*17", "35厘米", "1680.00"),
        ("递针中分界13*15", "35厘米", "1040.00"),
        ("递针左分界13*15", "35厘米", "1040.00"),
    ],
)
def test_all_confirmed_piece_craft_families_accept_exact_combined_codes(
    craft, length, expected
):
    assert pricing_service.get_base_price(
        product_type="piece", craft=craft, size=None, length=length
    ) == D(expected)


def test_all_confirmed_combined_piece_codes_map_one_to_one_to_internal_matrix():
    assert pricing_service.COMBINED_PIECE_CRAFT_SIZE == EXPECTED_COMBINED_PIECE_CODES
    assert len(set(pricing_service.COMBINED_PIECE_CRAFT_SIZE.values())) == len(
        EXPECTED_COMBINED_PIECE_CODES
    )
    combined_by_pair = {
        pair: combined for combined, pair in EXPECTED_COMBINED_PIECE_CODES.items()
    }
    for (product_type, craft, size, length), expected in _expected_seed_matrix().items():
        if product_type != "piece":
            continue
        assert pricing_service.get_base_price(
            product_type="piece",
            craft=combined_by_pair[(craft, size)],
            size=None,
            length=length,
        ) == expected


@pytest.mark.parametrize("craft", ["全递针", "全递针未知尺寸", "U型", "特单发片"])
def test_unknown_or_incomplete_combined_piece_craft_has_no_price(craft):
    assert pricing_service.get_base_price(
        product_type="piece", craft=craft, size=None, length="25厘米"
    ) is None


def test_cap_price_ignores_size():
    assert pricing_service.get_base_price(
        product_type="cap", craft="递顶", size=None, length="35厘米"
    ) == pricing_service.get_base_price(
        product_type="cap", craft="递顶", size="59", length="35厘米"
    ) == D("2650.00")


@pytest.mark.parametrize(
    "craft", ["递针旋全头套", "递针旋九分头", "递针顶", "递针中分界", "递针左分界"]
)
def test_legacy_cap_craft_codes_are_not_supported(craft):
    assert pricing_service.get_base_price(
        product_type="cap", craft=craft, size=None, length="25厘米"
    ) is None


@pytest.mark.parametrize(
    ("craft", "length", "level", "expected"),
    [
        ("递旋", "15厘米", level, expected)
        for level, expected in (
            ("silver", "1048.00"),
            ("black", "998.00"),
            ("supreme", "960.00"),
        )
    ]
    + [
        ("递顶", length, level, expected)
        for length, prices in (
            ("20厘米", ("1698.00", "1598.00", "1548.00")),
            ("25厘米", ("2098.00", "1998.00", "1948.00")),
        )
        for level, expected in zip(("silver", "black", "supreme"), prices)
    ],
)
def test_fixed_member_prices_take_priority(craft, length, level, expected):
    original = pricing_service.get_base_price(
        product_type="cap", craft=craft, size=None, length=length
    )
    result = pricing_service.resolve_discount(
        product_type="cap",
        craft=craft,
        size=None,
        length=length,
        original_price=original,
        membership_level=level,
    )
    assert result.final_price == D(expected)
    assert result.discount_amount == original - D(expected)
    assert result.pricing_rule == "member_fixed"


@pytest.mark.parametrize(
    ("length", "original", "level", "expected"),
    [
        (length, original, level, expected)
        for length, original, prices in (
            ("20厘米", "1498.00", ("1428.00", "1378.00", "1368.00")),
            ("25厘米", "1798.00", ("1728.00", "1678.00", "1668.00")),
            ("30厘米", "1998.00", ("1928.00", "1878.00", "1868.00")),
            ("35厘米", "2050.00", ("1980.00", "1930.00", "1920.00")),
            ("40厘米", "2700.00", ("2630.00", "2580.00", "2570.00")),
        )
        for level, expected in zip(("silver", "black", "supreme"), prices)
    ],
)
def test_cap_spin_non_fixed_lengths_use_member_reductions(
    length, original, level, expected
):
    base_price = pricing_service.get_base_price(
        product_type="cap",
        craft="递旋",
        size=None,
        length=length,
    )
    result = pricing_service.resolve_discount(
        product_type="cap",
        craft="递旋",
        size=None,
        length=length,
        original_price=base_price,
        membership_level=level,
    )

    assert base_price == D(original)
    assert result.final_price == D(expected)
    assert result.discount_amount == pricing_service.MEMBERSHIP_REDUCTIONS[level]
    assert result.pricing_rule == "member_reduction"


@pytest.mark.parametrize(
    ("level", "expected"),
    [("silver", "930.00"), ("black", "880.00"), ("supreme", "870.00")],
)
def test_non_fixed_member_price_uses_reduction(level, expected):
    result = pricing_service.resolve_discount(
        product_type="piece",
        craft="全递针",
        size="9*14",
        length="30厘米",
        original_price=D("1000"),
        membership_level=level,
    )
    assert result.final_price == D(expected)
    assert result.pricing_rule == "member_reduction"


def test_non_member_uses_quantized_base_price():
    result = pricing_service.resolve_discount(
        product_type="cap",
        craft="递顶",
        size=None,
        length="35厘米",
        original_price=D("2650.005"),
        membership_level=None,
    )
    assert result.final_price == D("2650.01")
    assert result.discount_amount == D("0.00")
    assert result.pricing_rule == "base_price"


def test_reduction_below_zero_raises_configuration_error():
    with pytest.raises(pricing_service.PricingConfigurationError, match="立减"):
        pricing_service.resolve_discount(
            product_type="piece",
            craft="全递针",
            size="9*14",
            length="25厘米",
            original_price=D("50"),
            membership_level="silver",
        )


@pytest.mark.parametrize("original", [D("0"), D("-1"), D("NaN"), D("Infinity"), D("-Infinity")])
def test_original_price_must_be_finite_and_positive(original):
    with pytest.raises(pricing_service.PricingConfigurationError, match="原始价"):
        pricing_service.resolve_discount(
            product_type="cap",
            craft="递旋",
            size=None,
            length="20厘米",
            original_price=original,
            membership_level=None,
        )


@pytest.mark.parametrize("membership_level", ["gold", "", "SILVER"])
def test_unknown_membership_level_raises_configuration_error(membership_level):
    with pytest.raises(pricing_service.PricingConfigurationError, match="会员等级"):
        pricing_service.resolve_discount(
            product_type="cap",
            craft="递旋",
            size=None,
            length="20厘米",
            original_price=D("1498"),
            membership_level=membership_level,
        )


def test_fixed_price_above_original_is_capped_and_marked():
    result = pricing_service.resolve_discount(
        product_type="cap",
        craft="递旋",
        size=None,
        length="15厘米",
        original_price=D("900"),
        membership_level="silver",
    )
    assert result.final_price == D("900.00")
    assert result.discount_amount == D("0.00")
    assert result.pricing_rule == "member_fixed_capped"


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "130_domestic_member_pricing_a.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_130_domestic_member_pricing_a", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _operator(db, suffix):
    user = ArkUser(
        username=f"member-pricing-{suffix}",
        password_hash="x",
        real_name=f"member-pricing-{suffix}",
    )
    db.add(user)
    db.flush()
    return user


def _customer_and_order(db, suffix):
    user = _operator(db, suffix)
    customer = domestic_models.DomesticCustomer(
        shop_name=f"会员定价客户-{suffix}",
        membership_level=None,
        created_by=user.id,
    )
    db.add(customer)
    db.flush()
    order = domestic_models.DomesticOrder(
        domestic_no=f"DOP-{suffix}",
        order_no=f"CUSTOMER-{suffix}",
        order_date=date(2026, 9, 1),
        customer_id=customer.id,
        created_by=user.id,
    )
    db.add(order)
    db.flush()
    return user, customer, order


def test_base_price_model_persists_without_size_and_rejects_duplicate_key(db):
    model = getattr(domestic_models, "DomesticBasePrice")
    assert "size" not in model.__table__.columns

    db.add(
        model(
            product_type="piece",
            craft="全递针9*14",
            length="25厘米",
            original_price=D("840.00"),
            version=1,
        )
    )
    db.flush()
    db.add(
        model(
            product_type="piece",
            craft="全递针9*14",
            length="25厘米",
            original_price=D("999.00"),
            version=2,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"product_type": "unknown"},
        {"original_price": D("0.00")},
        {"original_price": D("-0.01")},
        {"version": 0},
    ],
)
def test_base_price_database_checks_reject_invalid_rows(db, overrides):
    model = getattr(domestic_models, "DomesticBasePrice")
    values = {
        "product_type": "cap",
        "craft": "递旋",
        "length": "15厘米",
        "original_price": D("1198.00"),
        "version": 1,
    }
    values.update(overrides)
    db.add(model(**values))
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize("membership_level", [None, "silver", "black", "supreme"])
def test_customer_membership_snapshot_accepts_only_current_levels(
    db, membership_level
):
    user = _operator(db, membership_level or "none")
    customer = domestic_models.DomesticCustomer(
        shop_name=f"会员等级-{membership_level}",
        membership_level=membership_level,
        last_recharge_amount=D("10000.00") if membership_level else None,
        created_by=user.id,
    )
    db.add(customer)
    db.flush()
    assert customer.last_recharged_at is None


def test_customer_membership_database_check_rejects_unknown_level(db):
    user = _operator(db, "invalid-level")
    db.add(
        domestic_models.DomesticCustomer(
            shop_name="无效会员等级",
            membership_level="gold",
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_customer_and_order_item_pricing_columns_match_compatibility_contract():
    customer_columns = domestic_models.DomesticCustomer.__table__.columns
    assert customer_columns.membership_level.type.length == 16
    assert customer_columns.membership_level.nullable is True
    assert customer_columns.last_recharge_amount.nullable is True
    assert customer_columns.last_recharged_at.nullable is True

    item_columns = domestic_models.DomesticOrderItem.__table__.columns
    expected = {
        "original_price": 14,
        "discount_amount": 14,
        "membership_level_snapshot": 16,
        "pricing_rule": 24,
        "pricing_version": 32,
        "base_price_version_snapshot": None,
    }
    for name, length_or_precision in expected.items():
        column = item_columns[name]
        assert column.nullable is True
        assert column.default is None
        assert column.server_default is None
        if length_or_precision is not None:
            assert (
                getattr(column.type, "length", None) or column.type.precision
            ) == length_or_precision

    legacy_item = domestic_models.DomesticOrderItem(
        order_id=1,
        line_no=1,
        product_id=1,
        product_name="旧写路径",
        order_qty=1,
        unit_price=D("100.00"),
    )
    assert legacy_item.original_price is None
    assert legacy_item.pricing_rule is None


def test_pricing_request_persists_and_rejects_duplicate_order_request(db):
    model = getattr(domestic_models, "DomesticOrderPricingRequest")
    _, _, order = _customer_and_order(db, "request-unique")
    payload = {
        "order_id": order.id,
        "request_id": "same-request",
        "operation": "submit",
        "request_hash": "a" * 64,
        "result_json": {"total": "840.00"},
    }
    db.add(model(**payload))
    db.flush()
    db.add(model(**payload))
    with pytest.raises(IntegrityError):
        db.flush()


def test_pricing_request_operation_database_check(db):
    model = getattr(domestic_models, "DomesticOrderPricingRequest")
    _, _, order = _customer_and_order(db, "request-operation")
    db.add(
        model(
            order_id=order.id,
            request_id="bad-operation",
            operation="edit",
            request_hash="b" * 64,
            result_json={},
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_member_pricing_tables_expose_named_database_constraints():
    base_price = getattr(domestic_models, "DomesticBasePrice").__table__
    pricing_request = getattr(
        domestic_models, "DomesticOrderPricingRequest"
    ).__table__
    customer = domestic_models.DomesticCustomer.__table__

    assert {
        constraint.name
        for constraint in base_price.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_dom_base_price_product_type",
        "ck_dom_base_price_positive",
        "ck_dom_base_price_version",
    }
    assert {
        constraint.name
        for constraint in pricing_request.constraints
        if isinstance(constraint, CheckConstraint)
    } == {"ck_dom_pricing_request_operation"}
    assert {
        constraint.name
        for constraint in customer.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {"ck_dom_customer_membership_level"}


def test_member_pricing_migration_revision_and_frozen_seed_contract():
    migration = _migration_module()
    expected = tuple(pricing_service.iter_base_price_seeds())

    assert migration.revision == "130_domestic_member_pricing_a"
    assert migration.down_revision == "129_domestic_order_attributes"
    assert len(migration.revision) <= 32
    assert migration.BASE_PRICE_SEEDS == expected
    assert len(migration.BASE_PRICE_SEEDS) == 131
    assert len({row[:3] for row in migration.BASE_PRICE_SEEDS}) == 131
    assert (
        "piece",
        "递针中分界13*15",
        "35厘米",
        D("1040.00"),
    ) in migration.BASE_PRICE_SEEDS

    full_needle = {
        (craft.removeprefix("全递针"), length): price
        for product_type, craft, length, price in migration.BASE_PRICE_SEEDS
        if product_type == "piece" and craft.startswith("全递针")
    }
    needle_spin = {
        (craft.removeprefix("递针旋"), length): price
        for product_type, craft, length, price in migration.BASE_PRICE_SEEDS
        if product_type == "piece" and craft.startswith("递针旋")
    }
    assert needle_spin == full_needle


def test_customer_migration_backfill_uses_latest_recharge_id_and_preserves_money():
    migration = _migration_module()
    backfill = getattr(migration, "_backfill_customer_membership")
    metadata = MetaData()
    customers = Table(
        "ark_domestic_customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("membership_level", String(16)),
        Column("last_recharge_amount", Numeric(14, 2)),
        Column("last_recharged_at", DateTime),
        Column("balance", Numeric(14, 2), nullable=False),
    )
    ledger = Table(
        "ark_domestic_customer_ledger",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, nullable=False),
        Column("transaction_type", String(32), nullable=False),
        Column("amount", Numeric(14, 2), nullable=False),
        Column("balance_after", Numeric(14, 2), nullable=False),
        Column("created_at", DateTime, nullable=False),
    )
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    same_second = datetime(2026, 9, 1, 10, 0, 0)
    later = datetime(2026, 9, 1, 10, 1, 0)
    customer_rows = [
        {
            "id": customer_id,
            "membership_level": "silver",
            "last_recharge_amount": D("1.00"),
            "last_recharged_at": later,
            "balance": D(f"{customer_id}00.00"),
        }
        for customer_id in range(1, 7)
    ]
    ledger_rows = [
        # Same timestamp: id=2 must win, not created_at or accumulated amount.
        {"id": 1, "customer_id": 1, "transaction_type": "recharge", "amount": D("10000.00"), "balance_after": D("10100.00"), "created_at": same_second},
        {"id": 2, "customer_id": 1, "transaction_type": "recharge", "amount": D("30000.00"), "balance_after": D("40100.00"), "created_at": same_second},
        # A later non-recharge ledger entry must never become the membership source.
        {"id": 20, "customer_id": 1, "transaction_type": "order_refund", "amount": D("500.00"), "balance_after": D("40600.00"), "created_at": later},
        {"id": 21, "customer_id": 2, "transaction_type": "order_charge", "amount": D("-10.00"), "balance_after": D("190.00"), "created_at": later},
        {"id": 3, "customer_id": 3, "transaction_type": "recharge", "amount": D("9999.99"), "balance_after": D("10299.99"), "created_at": same_second},
        {"id": 4, "customer_id": 4, "transaction_type": "recharge", "amount": D("10000.00"), "balance_after": D("10400.00"), "created_at": same_second},
        {"id": 5, "customer_id": 5, "transaction_type": "recharge", "amount": D("30000.00"), "balance_after": D("30500.00"), "created_at": same_second},
        {"id": 6, "customer_id": 6, "transaction_type": "recharge", "amount": D("100000.00"), "balance_after": D("100600.00"), "created_at": same_second},
    ]

    with engine.begin() as connection:
        connection.execute(customers.insert(), customer_rows)
        connection.execute(ledger.insert(), ledger_rows)
        balances_before = {
            row.id: row.balance
            for row in connection.execute(
                select(customers.c.id, customers.c.balance)
            )
        }
        ledger_before = connection.execute(select(ledger).order_by(ledger.c.id)).all()

        backfill(connection)

        actual = {
            row.id: row
            for row in connection.execute(select(customers).order_by(customers.c.id))
        }
        assert actual[1].membership_level == "black"
        assert actual[1].last_recharge_amount == D("30000.00")
        assert actual[1].last_recharged_at == same_second
        assert (
            actual[2].membership_level,
            actual[2].last_recharge_amount,
            actual[2].last_recharged_at,
        ) == (None, None, None)
        assert actual[3].membership_level is None
        assert actual[3].last_recharge_amount == D("9999.99")
        assert actual[4].membership_level == "silver"
        assert actual[5].membership_level == "black"
        assert actual[6].membership_level == "supreme"
        assert {row.id: row.balance for row in actual.values()} == balances_before
        assert connection.execute(select(ledger).order_by(ledger.c.id)).all() == ledger_before


def test_order_item_migration_backfill_only_populates_legacy_pricing_snapshots():
    migration = _migration_module()
    backfill = getattr(migration, "_backfill_legacy_order_pricing")
    metadata = MetaData()
    orders = Table(
        "ark_domestic_orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("total_amount", Numeric(14, 2), nullable=False),
    )
    items = Table(
        "ark_domestic_order_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("order_id", Integer, nullable=False),
        Column("unit_price", Numeric(14, 2), nullable=False),
        Column("original_price", Numeric(14, 2)),
        Column("discount_amount", Numeric(14, 2)),
        Column("membership_level_snapshot", String(16)),
        Column("pricing_rule", String(24)),
        Column("pricing_version", String(32)),
        Column("base_price_version_snapshot", Integer),
    )
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(orders.insert(), [{"id": 1, "total_amount": D("24.68")}])
        connection.execute(
            items.insert(),
            [
                {"id": 1, "order_id": 1, "unit_price": D("0.00")},
                {"id": 2, "order_id": 1, "unit_price": D("12.34")},
            ],
        )

        backfill(connection)

        actual = connection.execute(select(items).order_by(items.c.id)).all()
        assert [row.unit_price for row in actual] == [D("0.00"), D("12.34")]
        assert [row.original_price for row in actual] == [D("0.00"), D("12.34")]
        for row in actual:
            assert row.discount_amount == D("0.00")
            assert row.membership_level_snapshot is None
            assert row.pricing_rule == "legacy_manual"
            assert row.pricing_version == "legacy"
            assert row.base_price_version_snapshot == 0
        assert connection.execute(select(orders.c.total_amount)).scalar_one() == D("24.68")


def test_member_pricing_migration_is_self_contained_and_backfills_compatibly(
    monkeypatch,
):
    migration = _migration_module()
    module_source = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)

    added_columns = []
    created_tables = {}
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *columns, **kwargs: created_tables.update(
            {name: (columns, kwargs)}
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table_name, column: added_columns.append((table_name, column)),
    )
    monkeypatch.setattr(migration.op, "execute", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "alter_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration.op, "create_check_constraint", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(migration.op, "bulk_insert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration,
        "_backfill_customer_membership",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        migration,
        "_backfill_legacy_order_pricing",
        lambda _connection: None,
    )
    migration.upgrade()

    assert "app.domestic.pricing_service" not in module_source
    for table_name in (
        "ark_domestic_base_prices",
        "ark_domestic_order_pricing_requests",
    ):
        assert table_name in upgrade_source
        assert table_name in downgrade_source
    for column_name in (
        "last_recharge_amount",
        "last_recharged_at",
        "original_price",
        "discount_amount",
        "membership_level_snapshot",
        "pricing_rule",
        "pricing_version",
        "base_price_version_snapshot",
    ):
        assert column_name in upgrade_source
        assert column_name in downgrade_source

    assert "_backfill_customer_membership(connection)" in upgrade_source
    assert "_backfill_legacy_order_pricing(connection)" in upgrade_source
    compatibility_column_names = {
        "original_price",
        "discount_amount",
        "membership_level_snapshot",
        "pricing_rule",
        "pricing_version",
        "base_price_version_snapshot",
    }
    compatibility_columns = {
        column.name: column
        for table_name, column in added_columns
        if table_name == "ark_domestic_order_items"
    }
    assert set(compatibility_columns) == compatibility_column_names
    for column in compatibility_columns.values():
        assert column.nullable is True
        assert column.server_default is None
        assert column.comment
    customer_columns = {
        column.name: column
        for table_name, column in added_columns
        if table_name == "ark_domestic_customers"
    }
    assert customer_columns["last_recharge_amount"].comment == "最近一次成功充值金额（人民币）"
    assert customer_columns["last_recharged_at"].comment == "最近一次成功充值时间（北京时）"
    for table_name in (
        "ark_domestic_base_prices",
        "ark_domestic_order_pricing_requests",
    ):
        columns, table_kwargs = created_tables[table_name]
        assert table_kwargs["comment"]
        assert all(column.comment for column in columns if isinstance(column, Column))


# ── 原价维护与批量会员报价 API ─────────────────────────


def _cap_attrs(**overrides):
    values = {
        "product_type": "cap",
        "craft": "递旋",
        "net_color": "自然色",
        "size": "12*14",
        "length": "20厘米",
        "hair_style_series": "标准款",
    }
    values.update(overrides)
    return values


def _piece_attrs(**overrides):
    values = {
        "product_type": "piece",
        "craft": "全递针9*14",
        "length": "25厘米",
    }
    values.update(overrides)
    return values


def test_pricing_write_schemas_enforce_money_item_identity_and_unique_keys():
    from app.domestic import schemas

    BasePriceUpdate = getattr(schemas, "BasePriceUpdate")
    PricingQuoteRequest = getattr(schemas, "PricingQuoteRequest")

    assert BasePriceUpdate(original_price="999999999999.99").original_price == D(
        "999999999999.99"
    )
    for invalid in ("0", "1000000000000", "1.001"):
        with pytest.raises(ValidationError):
            BasePriceUpdate(original_price=invalid)
    with pytest.raises(ValidationError, match="extra"):
        BasePriceUpdate(original_price="1.00", extra="forbidden")

    valid = PricingQuoteRequest.model_validate(
        {
            "customer_id": None,
            "items": [
                {"client_key": "  first  ", "product_id": 1},
                {"client_key": "second", "attrs": _cap_attrs()},
            ],
        }
    )
    assert [item.client_key for item in valid.items] == ["first", "second"]

    invalid_items = [
        {"client_key": "x"},
        {"client_key": "x", "product_id": 1, "attrs": _cap_attrs()},
    ]
    for item in invalid_items:
        with pytest.raises(ValidationError, match="product_id|attrs"):
            PricingQuoteRequest(customer_id=None, items=[item])
    with pytest.raises(ValidationError, match="client_key"):
        PricingQuoteRequest(
            customer_id=None,
            items=[
                {"client_key": " duplicate ", "product_id": 1},
                {"client_key": "duplicate", "product_id": 2},
            ],
        )
    with pytest.raises(ValidationError):
        PricingQuoteRequest(customer_id=None, items=[])
    with pytest.raises(ValidationError):
        PricingQuoteRequest(
            customer_id=None,
            items=[{"client_key": str(i), "product_id": i + 1} for i in range(51)],
        )
    with pytest.raises(ValidationError, match="extra"):
        PricingQuoteRequest(
            customer_id=None,
            items=[{"client_key": "x", "product_id": 1}],
            extra="forbidden",
        )


def _persist_product(db, attrs):
    from app.domestic.product_service import find_or_create_product
    from app.domestic.schemas import ProductAttrs

    return find_or_create_product(db, ProductAttrs.model_validate(attrs))


def test_product_price_join_shares_cap_key_and_filters_before_pagination(db):
    from app.domestic import product_service

    configured_a = _persist_product(db, _cap_attrs(net_color="自然色", size="12*14"))
    configured_b = _persist_product(
        db,
        _cap_attrs(
            net_color="深棕色", size="14*16", hair_style_series="蓬松款"
        ),
    )
    missing_cap = _persist_product(
        db, _cap_attrs(craft="递顶", length="20厘米")
    )
    missing_piece = _persist_product(db, _piece_attrs(craft="全递针12*14"))
    db.add(
        domestic_models.DomesticBasePrice(
            product_type="cap",
            craft="递旋",
            length="20厘米",
            original_price=D("1498.00"),
            version=3,
        )
    )
    db.flush()

    first_page, configured_total = product_service.list_products(
        db,
        price_status="configured",
        page=1,
        page_size=1,
        sort_field="name",
        sort_order="asc",
    )
    missing_rows, missing_total = product_service.list_products(
        db, price_status="missing", page=1, page_size=20
    )

    assert configured_total == 2
    assert len(first_page) == 1
    assert first_page[0]["id"] in {configured_a.id, configured_b.id}
    assert first_page[0]["original_price"] == D("1498.00")
    assert first_page[0]["base_price_version"] == 3
    assert first_page[0]["price_status"] == "configured"
    assert first_page[0]["price_key"] == {
        "product_type": "cap",
        "craft": "递旋",
        "length": "20厘米",
    }
    assert missing_total == 2
    assert {row["id"] for row in missing_rows} == {
        missing_cap.id,
        missing_piece.id,
    }
    assert all(row["price_status"] == "missing" for row in missing_rows)
    assert all(row["original_price"] is None for row in missing_rows)


def test_piece_prices_are_isolated_by_combined_craft_and_length(db):
    from app.domestic import product_service

    priced = _persist_product(db, _piece_attrs(craft="全递针9*14"))
    missing = _persist_product(db, _piece_attrs(craft="全递针12*14"))
    db.add(
        domestic_models.DomesticBasePrice(
            product_type="piece",
            craft="全递针9*14",
            length="25厘米",
            original_price=D("840.00"),
            version=1,
        )
    )
    db.flush()

    rows, total = product_service.list_products(db, page_size=20)
    by_id = {row["id"]: row for row in rows}

    assert total == 2
    assert by_id[priced.id]["price_status"] == "configured"
    assert by_id[missing.id]["price_status"] == "missing"
    assert by_id[priced.id]["price_key"] == {
        "product_type": "piece",
        "craft": "全递针9*14",
        "length": "25厘米",
    }


def test_base_price_upsert_versions_shared_skus_and_delete_returns_to_missing(db):
    from app.domestic import pricing_service as service
    from app.domestic import product_service

    user = _operator(db, "base-price-admin")
    first = _persist_product(db, _cap_attrs(net_color="自然色", size="12*14"))
    second = _persist_product(
        db,
        _cap_attrs(
            net_color="深棕色", size="14*16", hair_style_series="蓬松款"
        ),
    )

    created = service.upsert_base_price(
        db,
        product_id=first.id,
        original_price=D("1498.00"),
        user_id=user.id,
    )
    updated = service.upsert_base_price(
        db,
        product_id=first.id,
        original_price=D("1598.00"),
        user_id=user.id,
    )

    assert created == {
        "original_price": D("1498.00"),
        "version": 1,
        "price_key": {
            "product_type": "cap",
            "craft": "递旋",
            "length": "20厘米",
        },
        "affected_sku_count": 2,
    }
    assert updated["version"] == 2
    assert updated["original_price"] == D("1598.00")
    assert updated["affected_sku_count"] == 2
    assert db.query(domestic_models.DomesticBasePrice).count() == 1
    stored = db.query(domestic_models.DomesticBasePrice).one()
    assert stored.updated_by == user.id

    deleted = service.delete_base_price(db, product_id=first.id)
    assert deleted["affected_sku_count"] == 2
    assert deleted["price_key"] == created["price_key"]
    assert db.query(domestic_models.DomesticBasePrice).count() == 0
    rows, total = product_service.list_products(
        db, price_status="missing", page_size=20
    )
    assert total == 2
    assert {row["id"] for row in rows} == {first.id, second.id}


def test_base_price_lookup_is_byte_exact_and_invalid_matrix_keys_stay_missing(db):
    from app.domestic import pricing_service as service

    db.add_all(
        [
            domestic_models.DomesticBasePrice(
                product_type="cap",
                craft="CaseCraft",
                length="20cm",
                original_price=D("100.00"),
                version=1,
            ),
            domestic_models.DomesticBasePrice(
                product_type="cap",
                craft="casecraft",
                length="20cm",
                original_price=D("200.00"),
                version=1,
            ),
        ]
    )
    db.flush()

    upper = service.get_base_price_row(
        db, ("cap", "CaseCraft", "20cm"), for_update=True
    )
    lower = service.get_base_price_row(db, ("cap", "casecraft", "20cm"))

    assert upper.original_price == D("100.00")
    assert lower.original_price == D("200.00")
    assert service.price_key_for_attrs(
        product_type="cap", craft="未确认工艺", length="20厘米"
    ) is None


def test_base_price_upsert_rejects_case_insensitive_unique_conflict(db):
    """SQLite NOCASE 唯一索引复现 MySQL CI 唯一键，不能复用错大小写行。"""
    from app.domestic import pricing_service as service

    user = _operator(db, "base-price-case-conflict")
    product = _persist_product(
        db, _piece_attrs(craft="U型13*15", length="25厘米")
    )
    db.add(
        domestic_models.DomesticBasePrice(
            product_type="piece",
            craft="u型13*15",
            length="25厘米",
            original_price=D("1060.00"),
            version=1,
            updated_by=user.id,
        )
    )
    db.flush()
    db.execute(
        text(
            "CREATE UNIQUE INDEX uq_test_dom_base_price_nocase "
            "ON ark_domestic_base_prices "
            "(product_type, craft COLLATE NOCASE, length)"
        )
    )
    db.commit()

    with pytest.raises(ValueError, match="大小写"):
        service.upsert_base_price(
            db,
            product_id=product.id,
            original_price=D("1200.00"),
            user_id=user.id,
        )


def test_concurrent_sqlite_admin_sessions_recover_exact_unique_conflict(tmp_path):
    """两个线程均先读到缺价，再由真实唯一约束裁决同键插入。"""
    from sqlalchemy.orm import sessionmaker

    from app.domestic import pricing_service as service

    race_engine = create_engine(
        f"sqlite:///{tmp_path / 'base-price-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    domestic_models.DomesticProduct.__table__.create(race_engine)
    domestic_models.DomesticBasePrice.__table__.create(race_engine)
    Session = sessionmaker(bind=race_engine)
    with Session() as seed_session:
        product = domestic_models.DomesticProduct(
            attrs_key='["cap","递旋","自然色","12*14","20厘米","","标准款"]',
            name="头套/递旋/自然色/12*14/20厘米/标准款",
            product_type="cap",
            craft="递旋",
            net_color="自然色",
            size="12*14",
            length="20厘米",
            hair_style_series="标准款",
            status=1,
            use_count=0,
        )
        seed_session.add(product)
        seed_session.commit()
        product_id = product.id

    first_flush_barrier = threading.Barrier(2, timeout=10)

    def save_price(price, user_id):
        session = Session()
        transaction_open = None

        def align_first_base_price_flush(current_session, _context, _instances):
            if any(
                isinstance(row, domestic_models.DomesticBasePrice)
                for row in current_session.new
            ):
                first_flush_barrier.wait()

        event.listen(session, "before_flush", align_first_base_price_flush)
        try:
            result = service.upsert_base_price(
                session,
                product_id=product_id,
                original_price=D(price),
                user_id=user_id,
            )
            session.commit()
            transaction_open = session.in_transaction()
            return result, transaction_open
        except Exception:
            session.rollback()
            transaction_open = session.in_transaction()
            raise
        finally:
            event.remove(session, "before_flush", align_first_base_price_flush)
            assert transaction_open is False
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(save_price, "1498.00", 101),
            executor.submit(save_price, "1598.00", 102),
        ]
        results = [future.result(timeout=20)[0] for future in futures]

    assert {result["version"] for result in results} == {1, 2}
    winner = next(result for result in results if result["version"] == 2)
    with Session() as verify_session:
        rows = verify_session.query(domestic_models.DomesticBasePrice).all()
        assert len(rows) == 1
        assert rows[0].version == winner["version"]
        assert rows[0].original_price == winner["original_price"]
        assert verify_session.in_transaction() is True
        verify_session.rollback()
        assert verify_session.in_transaction() is False


def _pricing_api_client(db, user_id, *permissions, raise_server_exceptions=True):
    from app.domestic.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user_id),
        "roles": [],
        "permissions": list(permissions),
    }
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _configured_product(db, attrs, price, version=1):
    product = _persist_product(db, attrs)
    from app.domestic import pricing_service as service

    key = service.price_key_for_product(product)
    assert key is not None
    db.add(
        domestic_models.DomesticBasePrice(
            product_type=key[0],
            craft=key[1],
            length=key[2],
            original_price=D(price),
            version=version,
        )
    )
    db.flush()
    return product


@pytest.mark.parametrize(
    ("membership_level", "last_recharge", "expected_price", "expected_rule"),
    [
        (None, None, "1198.00", "base_price"),
        ("silver", "10000.00", "1048.00", "member_fixed"),
        ("black", "30000.00", "998.00", "member_fixed"),
        ("supreme", "100000.00", "960.00", "member_fixed"),
    ],
)
def test_quote_returns_non_member_and_current_member_contracts(
    db, membership_level, last_recharge, expected_price, expected_rule
):
    from app.domestic import pricing_service as service
    from app.domestic.schemas import PricingQuoteRequest

    user = _operator(db, f"quote-{membership_level or 'none'}")
    customer = None
    if membership_level:
        customer = domestic_models.DomesticCustomer(
            shop_name=f"报价客户-{membership_level}",
            membership_level=membership_level,
            last_recharge_amount=D(last_recharge),
            balance=D("76543.21"),
            created_by=user.id,
        )
        db.add(customer)
        db.flush()
    product = _configured_product(
        db, _cap_attrs(length="15厘米", density="100%"), "1198.00", version=4
    )
    original_use_count = product.use_count

    result = service.quote_prices(
        db,
        PricingQuoteRequest.model_validate(
            {
                "customer_id": customer.id if customer else None,
                "items": [{"client_key": "line-1", "product_id": product.id}],
            }
        ),
    )

    priced = result["items"][0]
    assert result["customer"] == {
        "id": customer.id if customer else None,
        "membership_level": membership_level,
        "membership_label": {
            None: "非会员",
            "silver": "银卡会员",
            "black": "黑卡会员",
            "supreme": "至尊会员",
        }[membership_level],
        "last_recharge_amount": D(last_recharge) if last_recharge else None,
    }
    assert priced["status"] == "priced"
    assert priced["discount_price"] == D(expected_price)
    assert priced["pricing_rule"] == expected_rule
    assert priced["pricing_version"] == "domestic-member-v1"
    assert priced["expected_quote"] == {
        "original_price": D("1198.00"),
        "base_price_version": 4,
        "discount_price": D(expected_price),
        "membership_level": membership_level,
        "pricing_rule": expected_rule,
        "pricing_version": "domestic-member-v1",
    }
    assert "会员" in priced["pricing_rule_label"] or membership_level is None
    assert product.use_count == original_use_count
    if customer:
        assert customer.balance == D("76543.21")
        assert customer.membership_level == membership_level


def test_quote_batch_labels_reduction_fixed_and_fixed_price_cap(db):
    from app.domestic import pricing_service as service
    from app.domestic.schemas import PricingQuoteRequest

    user = _operator(db, "quote-rule-labels")
    customer = domestic_models.DomesticCustomer(
        shop_name="银卡报价客户",
        membership_level="silver",
        last_recharge_amount=D("10000.00"),
        created_by=user.id,
    )
    db.add(customer)
    fixed = _configured_product(
        db, _cap_attrs(length="15厘米", density="100%"), "1198.00"
    )
    reduced = _configured_product(db, _piece_attrs(), "840.00")
    capped = _configured_product(
        db, _cap_attrs(craft="递顶", length="20厘米"), "1600.00"
    )

    result = service.quote_prices(
        db,
        PricingQuoteRequest.model_validate(
            {
                "customer_id": customer.id,
                "items": [
                    {"client_key": "fixed", "product_id": fixed.id},
                    {"client_key": "reduced", "product_id": reduced.id},
                    {"client_key": "capped", "product_id": capped.id},
                ],
            }
        ),
    )
    by_key = {item["client_key"]: item for item in result["items"]}

    assert by_key["fixed"]["pricing_rule_label"] == "银卡会员固定会员价"
    assert by_key["reduced"]["discount_price"] == D("770.00")
    assert by_key["reduced"]["discount_amount"] == D("70.00")
    assert by_key["reduced"]["pricing_rule_label"] == "银卡会员立减70.00元"
    assert by_key["capped"]["discount_price"] == D("1600.00")
    assert by_key["capped"]["pricing_rule"] == "member_fixed_capped"
    assert (
        by_key["capped"]["pricing_rule_label"]
        == "银卡会员固定价高于原价，按原价封顶"
    )


def test_quote_api_commits_new_missing_sku_without_incrementing_use_count(db):
    user = _operator(db, "quote-new-missing")
    client = _pricing_api_client(db, user.id, "domestic:write")

    response = client.post(
        "/api/domestic/pricing/quote",
        json={
            "customer_id": None,
            "items": [
                {
                    "client_key": "new-missing",
                    "attrs": _cap_attrs(craft="大U型", length="40厘米"),
                }
            ],
        },
    )

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["client_key"] == "new-missing"
    assert item["status"] == "missing_base_price"
    assert item["message"] == "该产品尚未配置原始价格"
    assert "expected_quote" not in item
    stored = db.get(domestic_models.DomesticProduct, item["product_id"])
    assert stored is not None
    assert stored.use_count == 0


def test_quote_invalid_customer_does_not_persist_attrs_product(db):
    user = _operator(db, "quote-invalid-customer")
    client = _pricing_api_client(db, user.id, "domestic:write")

    response = client.post(
        "/api/domestic/pricing/quote",
        json={
            "customer_id": 999999,
            "items": [
                {"client_key": "must-not-create", "attrs": _piece_attrs()}
            ],
        },
    )

    assert response.status_code == 400
    assert "客户不存在" in response.json()["detail"]
    assert db.query(domestic_models.DomesticProduct).count() == 0


def test_quote_configuration_error_rolls_back_products_created_earlier_in_batch(db):
    user = _operator(db, "quote-config-error")
    customer = domestic_models.DomesticCustomer(
        shop_name="异常配置报价客户",
        membership_level="silver",
        last_recharge_amount=D("10000.00"),
        created_by=user.id,
    )
    db.add(customer)
    db.flush()
    bad_product = _configured_product(db, _piece_attrs(), "50.00")
    db.commit()
    initial_count = db.query(domestic_models.DomesticProduct).count()
    client = _pricing_api_client(db, user.id, "domestic:write")

    response = client.post(
        "/api/domestic/pricing/quote",
        json={
            "customer_id": customer.id,
            "items": [
                {
                    "client_key": "new-first",
                    "attrs": _cap_attrs(craft="大U型", length="40厘米"),
                },
                {"client_key": "bad-price", "product_id": bad_product.id},
            ],
        },
    )

    assert response.status_code == 400
    assert "价格" in response.json()["detail"]
    assert db.query(domestic_models.DomesticProduct).count() == initial_count


def test_pricing_routes_enforce_write_and_admin_permissions_and_admin_contract(db):
    user = _operator(db, "pricing-route-permissions")
    product = _persist_product(db, _cap_attrs())
    db.commit()
    read_client = _pricing_api_client(db, user.id, "domestic:read")
    admin_client = _pricing_api_client(db, user.id, "domestic:admin")

    denied_quote = read_client.post(
        "/api/domestic/pricing/quote",
        json={"items": [{"client_key": "x", "product_id": product.id}]},
    )
    denied_price = read_client.put(
        f"/api/domestic/products/{product.id}/base-price",
        json={"original_price": "1498.00"},
    )
    saved = admin_client.put(
        f"/api/domestic/products/{product.id}/base-price",
        json={"original_price": "1498.00"},
    )
    configured = admin_client.get(
        "/api/domestic/products", params={"price_status": "configured"}
    )
    deleted = admin_client.delete(
        f"/api/domestic/products/{product.id}/base-price"
    )
    missing = admin_client.get(
        "/api/domestic/products", params={"price_status": "missing"}
    )
    deleted_again = admin_client.delete(
        f"/api/domestic/products/{product.id}/base-price"
    )

    assert denied_quote.status_code == 403
    assert denied_price.status_code == 403
    assert saved.status_code == 200
    assert saved.json()["data"]["version"] == 1
    assert saved.json()["data"]["affected_sku_count"] == 1
    assert configured.json()["data"]["total"] == 1
    assert configured.json()["data"]["items"][0]["price_status"] == "configured"
    assert deleted.status_code == 200
    assert deleted.json()["data"]["affected_sku_count"] == 1
    assert missing.json()["data"]["total"] == 1
    assert missing.json()["data"]["items"][0]["price_status"] == "missing"
    assert deleted_again.status_code == 400
    assert "尚未配置" in deleted_again.json()["detail"]
