from datetime import date, datetime
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import inspect
from io import StringIO
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import (
    and_,
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
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.auth.models import ArkUser
from app.auth.dependencies import get_current_user
from app.core.database import Base, get_db
from app.domestic import (
    balance_service,
    constants as domestic_constants,
    customer_service,
    order_service,
    pricing_service,
)
from app.domestic import models as domestic_models
from app.domestic.schemas import (
    CustomerAdjust,
    CustomerCreate,
    CustomerInitialize,
    CustomerRechargeCreate,
    CustomerUpdate,
    DraftSubmitRequest,
    ExpectedQuote,
    ItemExpectedQuote,
    OrderCreate,
    OrderItemAppend,
    OrderItemInput,
    OrderItemUpdate,
    OrderUpdate,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep
from app.system.models import SysDict


D = Decimal


def _expected_quote_payload(**overrides):
    payload = {
        "original_price": "1198.00",
        "base_price_version": 1,
        "discount_price": "1198.00",
        "membership_level": None,
        "pricing_rule": "base_price",
        "pricing_version": "domestic-member-v1",
    }
    payload.update(overrides)
    return payload


def _order_item_payload(**overrides):
    payload = {
        "client_key": "line-1",
        "attrs": _cap_attrs(),
        "order_qty": 1,
        "expected_quote": _expected_quote_payload(),
    }
    payload.update(overrides)
    return payload


def test_order_quote_schemas_require_complete_forbidden_extra_contract():
    quote = ExpectedQuote.model_validate(_expected_quote_payload())
    assert quote.original_price == D("1198.00")

    for field in _expected_quote_payload():
        missing = _expected_quote_payload()
        missing.pop(field)
        with pytest.raises(ValidationError, match=field):
            ExpectedQuote.model_validate(missing)
    with pytest.raises(ValidationError, match="extra"):
        ExpectedQuote.model_validate(
            {**_expected_quote_payload(), "server_may_ignore": True}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("original_price", "0"),
        ("base_price_version", 0),
        ("discount_price", "-0.01"),
        ("membership_level", "gold"),
        ("pricing_rule", "manual"),
    ],
)
def test_expected_quote_rejects_values_outside_versioned_contract(field, value):
    with pytest.raises(ValidationError, match=field):
        ExpectedQuote.model_validate(_expected_quote_payload(**{field: value}))


def test_expected_quote_accepts_and_strips_a_noncurrent_version_for_stale_check():
    quote = ExpectedQuote.model_validate(
        _expected_quote_payload(pricing_version="  domestic-member-v0  ")
    )
    assert quote.pricing_version == "domestic-member-v0"

    for value in ("", "   ", "v" * 33):
        with pytest.raises(ValidationError, match="pricing_version"):
            ExpectedQuote.model_validate(
                _expected_quote_payload(pricing_version=value)
            )


def test_order_item_schema_requires_expected_quote_and_forbids_manual_price():
    assert OrderItemInput.model_validate(_order_item_payload()).client_key == "line-1"
    without_quote = _order_item_payload()
    without_quote.pop("expected_quote")
    with pytest.raises(ValidationError, match="expected_quote"):
        OrderItemInput.model_validate(without_quote)
    # 建单成交价只能走 expected_quote + manual_discount_price 显式契约，
    # 旧版自由 unit_price 字段依然禁止混入
    with pytest.raises(ValidationError, match="unit_price"):
        OrderItemInput.model_validate(
            _order_item_payload(unit_price="1.00")
        )


def test_draft_submit_schema_requires_unique_item_quotes_and_strips_request_id():
    quote = {"client_key": None, "item_id": 7, **_expected_quote_payload()}

    payload = DraftSubmitRequest.model_validate({
        "request_id": "  submit-request-7  ",
        "expected_quotes": [quote],
    })

    assert payload.request_id == "submit-request-7"
    assert payload.expected_quotes == [ItemExpectedQuote.model_validate(quote)]
    with pytest.raises(ValidationError, match="item_id"):
        DraftSubmitRequest.model_validate({
            "request_id": "submit-request-8",
            "expected_quotes": [{**quote, "item_id": 0}],
        })
    with pytest.raises(ValidationError, match="不能重复"):
        DraftSubmitRequest.model_validate({
            "request_id": "submit-request-9",
            "expected_quotes": [quote, quote],
        })
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DraftSubmitRequest.model_validate({
            "request_id": "submit-request-10",
            "expected_quotes": [quote],
            "ignored": True,
        })
    with pytest.raises(ValidationError, match="client_key"):
        DraftSubmitRequest.model_validate({
            "request_id": "submit-request-11",
            "expected_quotes": [{**quote, "client_key": "create-only-key"}],
        })


def test_draft_submit_accepts_only_a_consistent_legacy_snapshot_for_migrated_drafts():
    legacy = {
        "client_key": None,
        "item_id": 7,
        "original_price": "0.00",
        "base_price_version": 0,
        "discount_price": "0.00",
        "membership_level": None,
        "pricing_rule": "legacy_manual",
        "pricing_version": "legacy",
    }

    payload = DraftSubmitRequest.model_validate({
        "request_id": "legacy-draft-submit",
        "expected_quotes": [legacy],
    })

    assert payload.expected_quotes[0].pricing_rule == "legacy_manual"
    for field, value in (
        ("membership_level", "silver"),
        ("base_price_version", 1),
        ("pricing_version", "domestic-member-v1"),
        ("discount_price", "1.00"),
    ):
        with pytest.raises(ValidationError):
            DraftSubmitRequest.model_validate({
                "request_id": f"legacy-invalid-{field}",
                "expected_quotes": [{**legacy, field: value}],
            })


def test_order_update_requires_repricing_contract_only_when_customer_is_explicit():
    quote = {"item_id": 7, **_expected_quote_payload()}

    payload = OrderUpdate.model_validate({
        "customer_id": 9,
        "request_id": "  change-customer-9  ",
        "expected_quotes": [quote],
        "remark": "原子更新",
    })

    assert payload.request_id == "change-customer-9"
    with pytest.raises(ValidationError, match="request_id.*expected_quotes"):
        OrderUpdate.model_validate({"customer_id": 9})
    with pytest.raises(ValidationError, match="只有更换客户"):
        OrderUpdate.model_validate({
            "remark": "普通编辑",
            "request_id": "change-customer-10",
            "expected_quotes": [quote],
        })
    with pytest.raises(ValidationError, match="extra_forbidden"):
        OrderUpdate.model_validate({"remark": "普通编辑", "ignored": True})


def test_order_item_client_key_is_trimmed_bounded_and_append_keeps_request_id():
    item = OrderItemInput.model_validate(
        _order_item_payload(client_key="  browser-line-1  ")
    )
    append = OrderItemAppend.model_validate(
        {
            **_order_item_payload(client_key="  browser-line-2  "),
            "request_id": "  append-request-001  ",
        }
    )
    assert item.client_key == "browser-line-1"
    assert append.client_key == "browser-line-2"
    assert append.request_id == "append-request-001"
    for client_key in ("", "   ", "x" * 65):
        with pytest.raises(ValidationError, match="client_key"):
            OrderItemInput.model_validate(
                _order_item_payload(client_key=client_key)
            )


def test_order_create_rejects_duplicate_trimmed_client_keys():
    with pytest.raises(ValidationError, match="client_key"):
        OrderCreate.model_validate(
            {
                "request_id": "duplicate-lines-request",
                "order_no": "DUP-001",
                "order_date": "2026-09-02",
                "customer_id": 1,
                "order_type": "first_order",
                "order_channel": "wechat",
                "items": [
                    _order_item_payload(client_key=" repeated "),
                    _order_item_payload(client_key="repeated"),
                ],
            }
        )


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
        {"product_type": "cap", "craft": "", "size": None, "length": "15厘米"},
        {"product_type": "cap", "craft": "   ", "size": None, "length": "15厘米"},
        {"product_type": "piece", "craft": "自定义发片", "size": None, "length": ""},
        {"product_type": "piece", "craft": "全递针", "size": "99*99", "length": "25厘米"},
    ],
)
def test_invalid_persistence_price_dimensions_return_none(attrs):
    assert pricing_service.build_persistence_price_key(**attrs) is None


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        (
            {"product_type": "cap", "craft": "特单手织工艺", "length": "47厘米"},
            ("cap", "特单手织工艺", "47厘米"),
        ),
        (
            {"product_type": "piece", "craft": "海报外发片Code", "length": "47厘米"},
            ("piece", "海报外发片Code", "47厘米"),
        ),
    ],
)
def test_custom_persisted_sku_codes_build_exact_price_keys(attrs, expected):
    assert pricing_service.build_persistence_price_key(**attrs) == expected
    assert pricing_service.get_base_price(**attrs) is None


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
FINAL_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "131_domestic_member_pricing_b.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_130_domestic_member_pricing_a", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _final_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_131_domestic_member_pricing_b", FINAL_MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
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


def test_customer_and_order_item_pricing_columns_match_final_contract():
    customer_columns = domestic_models.DomesticCustomer.__table__.columns
    assert customer_columns.membership_level.type.length == 16
    assert customer_columns.membership_level.nullable is True
    assert customer_columns.last_recharge_amount.nullable is True
    assert customer_columns.last_recharged_at.nullable is True

    item_columns = domestic_models.DomesticOrderItem.__table__.columns
    assert item_columns.unit_price.nullable is False
    assert item_columns.unit_price.default is None
    assert item_columns.unit_price.server_default is None
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
        assert column.nullable is (name == "membership_level_snapshot")
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
        original_price=D("100.00"),
        discount_amount=D("0.00"),
        membership_level_snapshot=None,
        pricing_rule="legacy_manual",
        pricing_version="legacy",
        base_price_version_snapshot=0,
    )
    assert legacy_item.unit_price == D("100.00")
    assert legacy_item.pricing_rule == "legacy_manual"


def test_order_item_model_exposes_final_pricing_checks():
    table = domestic_models.DomesticOrderItem.__table__
    assert {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {
        "ck_dom_item_unit_price_nonnegative",
        "ck_dom_item_discount_nonnegative",
        "ck_dom_item_unit_not_above_original",
        "ck_dom_item_original_price_valid",
        "ck_dom_item_base_price_version_nonnegative",
        "ck_dom_item_membership_snapshot",
        "ck_dom_item_pricing_rule",
    }


def _constraint_product(db, suffix):
    product = domestic_models.DomesticProduct(
        attrs_key=f"constraint-{suffix}",
        name=f"约束产品-{suffix}",
        product_type="cap",
        craft="递旋",
        length="20厘米",
    )
    db.add(product)
    db.flush()
    return product


@pytest.mark.parametrize(
    ("overrides", "constraint_name"),
    [
        ({"unit_price": D("-0.01")}, "ck_dom_item_unit_price_nonnegative"),
        ({"discount_amount": D("-0.01")}, "ck_dom_item_discount_nonnegative"),
        ({"unit_price": D("101.00")}, "ck_dom_item_unit_not_above_original"),
        (
            {"original_price": D("0.00"), "pricing_rule": "base_price"},
            "ck_dom_item_original_price_valid",
        ),
        (
            {"base_price_version_snapshot": -1},
            "ck_dom_item_base_price_version_nonnegative",
        ),
        (
            {"membership_level_snapshot": "gold"},
            "ck_dom_item_membership_snapshot",
        ),
        ({"pricing_rule": "manual"}, "ck_dom_item_pricing_rule"),
    ],
)
def test_order_item_database_rejects_invalid_final_price_snapshot(
    db, overrides, constraint_name
):
    _, _, order = _customer_and_order(db, f"final-check-{constraint_name}")
    product = _constraint_product(db, f"final-check-{constraint_name}")
    values = {
        "order_id": order.id,
        "line_no": 1,
        "product_id": product.id,
        "product_name": product.name,
        "order_qty": 1,
        "unit_price": D("100.00"),
        "original_price": D("100.00"),
        "discount_amount": D("0.00"),
        "membership_level_snapshot": None,
        "pricing_rule": "base_price",
        "pricing_version": "domestic-member-v1",
        "base_price_version_snapshot": 1,
    }
    values.update(overrides)
    db.add(domestic_models.DomesticOrderItem(**values))
    with pytest.raises(IntegrityError, match=constraint_name):
        db.flush()


def test_order_item_database_accepts_zero_price_only_for_legacy_snapshot(db):
    _, _, order = _customer_and_order(db, "legacy-zero-final-check")
    product = _constraint_product(db, "legacy-zero-final-check")
    db.add(
        domestic_models.DomesticOrderItem(
            order_id=order.id,
            line_no=1,
            product_id=product.id,
            product_name=product.name,
            order_qty=1,
            unit_price=D("0.00"),
            original_price=D("0.00"),
            discount_amount=D("0.00"),
            membership_level_snapshot=None,
            pricing_rule="legacy_manual",
            pricing_version="legacy",
            base_price_version_snapshot=0,
        )
    )
    db.flush()


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


def _snapshot_validation_table(metadata):
    return Table(
        "ark_domestic_order_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("unit_price", Numeric(14, 2), nullable=False),
        Column("original_price", Numeric(14, 2)),
        Column("discount_amount", Numeric(14, 2)),
        Column("membership_level_snapshot", String(16)),
        Column("pricing_rule", String(24)),
        Column("pricing_version", String(32)),
        Column("base_price_version_snapshot", Integer),
    )


def _valid_snapshot_row(**overrides):
    row = {
        "id": 1,
        "unit_price": D("880.00"),
        "original_price": D("1000.00"),
        "discount_amount": D("120.00"),
        "membership_level_snapshot": "black",
        "pricing_rule": "member_reduction",
        "pricing_version": "domestic-member-v1",
        "base_price_version_snapshot": 1,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "overrides",
    [
        {"original_price": None},
        {"discount_amount": None},
        {"pricing_rule": None},
        {"pricing_version": None},
        {"base_price_version_snapshot": None},
        {"unit_price": D("-0.01")},
        {"discount_amount": D("-0.01")},
        {"unit_price": D("1000.01")},
        {"original_price": D("0.00")},
        {"base_price_version_snapshot": -1},
        {"membership_level_snapshot": "gold"},
        {"pricing_rule": "manual"},
    ],
)
def test_final_migration_blocks_every_invalid_existing_snapshot(overrides):
    migration = _final_migration_module()
    metadata = MetaData()
    items = _snapshot_validation_table(metadata)
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(items.insert(), _valid_snapshot_row(**overrides))
        with pytest.raises(RuntimeError, match="ark_domestic_order_items.*id=1"):
            migration._validate_existing_snapshots(connection)


def test_final_migration_accepts_zero_legacy_snapshot():
    migration = _final_migration_module()
    metadata = MetaData()
    items = _snapshot_validation_table(metadata)
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            items.insert(),
            _valid_snapshot_row(
                unit_price=D("0.00"),
                original_price=D("0.00"),
                discount_amount=D("0.00"),
                membership_level_snapshot=None,
                pricing_rule="legacy_manual",
                pricing_version="legacy",
                base_price_version_snapshot=0,
            ),
        )
        migration._validate_existing_snapshots(connection)


def test_final_migration_revision_contract_and_mysql_offline_sql():
    migration = _final_migration_module()
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)
    assert migration.revision == "131_domestic_member_pricing_b"
    assert migration.down_revision == "130_domestic_member_pricing_a"
    assert len(migration.revision) <= 32
    assert upgrade_source.index("_validate_existing_snapshots") < upgrade_source.index(
        "alter_column"
    )
    assert downgrade_source.index("drop_constraint") < downgrade_source.index(
        "alter_column"
    )

    upgrade_output = StringIO()
    migration.op = Operations(
        MigrationContext.configure(
            dialect_name="mysql",
            opts={
                "as_sql": True,
                "literal_binds": True,
                "output_buffer": upgrade_output,
            },
        )
    )
    migration.upgrade()
    upgrade_sql = upgrade_output.getvalue()
    upgrade_statements = [statement.strip() for statement in upgrade_sql.split(";")]
    unit_price_upgrade = next(
        statement
        for statement in upgrade_statements
        if "MODIFY unit_price" in statement
    )
    assert "NOT NULL" in unit_price_upgrade
    assert "DEFAULT" not in unit_price_upgrade.upper()
    for column_name in (
        "original_price",
        "discount_amount",
        "pricing_rule",
        "pricing_version",
        "base_price_version_snapshot",
    ):
        assert f"MODIFY {column_name}" in upgrade_sql
    assert upgrade_sql.count("NOT NULL") >= 5
    for constraint_name in (
        "ck_dom_item_unit_price_nonnegative",
        "ck_dom_item_discount_nonnegative",
        "ck_dom_item_unit_not_above_original",
        "ck_dom_item_original_price_valid",
        "ck_dom_item_base_price_version_nonnegative",
        "ck_dom_item_membership_snapshot",
        "ck_dom_item_pricing_rule",
    ):
        assert constraint_name in upgrade_sql

    downgrade_output = StringIO()
    migration.op = Operations(
        MigrationContext.configure(
            dialect_name="mysql",
            opts={"as_sql": True, "output_buffer": downgrade_output},
        )
    )
    migration.downgrade()
    downgrade_sql = downgrade_output.getvalue()
    downgrade_statements = [statement.strip() for statement in downgrade_sql.split(";")]
    unit_price_downgrade = next(
        statement
        for statement in downgrade_statements
        if "MODIFY unit_price" in statement
    )
    assert "NOT NULL" in unit_price_downgrade
    assert "DEFAULT 0.00" in unit_price_downgrade
    assert downgrade_sql.index("DROP CHECK") < downgrade_sql.index(" NULL")
    assert "MODIFY original_price NUMERIC(14, 2) NULL" in downgrade_sql


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


def test_base_price_lookup_is_byte_exact_and_custom_keys_do_not_gain_seed(db):
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
    ) == ("cap", "未确认工艺", "20厘米")
    assert service.get_base_price(
        product_type="cap", craft="未确认工艺", length="20厘米"
    ) is None


def test_mysql_price_queries_compile_craft_and_length_as_binary_exact():
    from app.domestic import product_service
    from app.domestic import pricing_service as service

    row_predicate = and_(
        *service._base_price_key_predicates(
            "mysql",
            domestic_models.DomesticBasePrice,
            ("cap", "CaseCraft", "20CM"),
        )
    )
    row_sql = str(
        row_predicate.compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    join_sql = str(
        product_service._base_price_join_predicate("mysql").compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "CAST(ark_domestic_base_prices.craft AS BINARY)" in row_sql
    assert "CAST(ark_domestic_base_prices.length AS BINARY)" in row_sql
    assert join_sql.count("CAST(ark_domestic_base_prices.craft AS BINARY)") == 1
    assert join_sql.count("CAST(ark_domestic_products.craft AS BINARY)") == 1
    assert join_sql.count("CAST(ark_domestic_base_prices.length AS BINARY)") == 1
    assert join_sql.count("CAST(ark_domestic_products.length AS BINARY)") == 1


def test_length_case_variants_never_share_price_or_affected_count(db):
    from app.domestic import product_service
    from app.domestic import pricing_service as service
    from app.domestic.schemas import PricingQuoteRequest

    user = _operator(db, "base-price-length-case")
    lower = _persist_product(
        db, _cap_attrs(craft="CaseCraft", length="20cm")
    )
    upper = _persist_product(
        db, _cap_attrs(craft="CaseCraft", length="20CM")
    )
    db.add(
        domestic_models.DomesticBasePrice(
            product_type="cap",
            craft="CaseCraft",
            length="20cm",
            original_price=D("1000.00"),
            version=1,
            updated_by=user.id,
        )
    )
    db.flush()

    configured, configured_total = product_service.list_products(
        db, price_status="configured", page_size=20
    )
    missing, missing_total = product_service.list_products(
        db, price_status="missing", page_size=20
    )
    quote = service.quote_prices(
        db,
        PricingQuoteRequest.model_validate(
            {
                "items": [
                    {"client_key": "lower", "product_id": lower.id},
                    {"client_key": "upper", "product_id": upper.id},
                ]
            }
        ),
    )

    assert configured_total == 1
    assert configured[0]["id"] == lower.id
    assert missing_total == 1
    assert missing[0]["id"] == upper.id
    assert [item["status"] for item in quote["items"]] == [
        "priced",
        "missing_base_price",
    ]
    assert service.affected_sku_count(
        db, ("cap", "CaseCraft", "20cm")
    ) == 1
    assert service.affected_sku_count(
        db, ("cap", "CaseCraft", "20CM")
    ) == 1
    updated = service.upsert_base_price(
        db,
        product_id=lower.id,
        original_price=D("1100.00"),
        user_id=user.id,
    )
    assert updated["affected_sku_count"] == 1

    db.execute(
        text(
            "CREATE UNIQUE INDEX uq_test_dom_base_price_full_nocase "
            "ON ark_domestic_base_prices "
            "(product_type, craft COLLATE NOCASE, length COLLATE NOCASE)"
        )
    )
    db.commit()
    with pytest.raises(ValueError, match="大小写"):
        service.upsert_base_price(
            db,
            product_id=upper.id,
            original_price=D("1200.00"),
            user_id=user.id,
        )
    db.rollback()
    deleted = service.delete_base_price(db, product_id=lower.id)
    assert deleted["affected_sku_count"] == 1
    db.commit()
    all_missing, total_missing = product_service.list_products(
        db, price_status="missing", page_size=20
    )
    assert total_missing == 2
    assert {item["id"] for item in all_missing} == {lower.id, upper.id}


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


def test_base_price_impact_endpoint_previews_shared_key_before_mutation(db):
    user = _operator(db, "base-price-impact")
    attrs = _cap_attrs(craft="递旋", length="20厘米")
    first = _configured_product(db, attrs, "1498.00", version=3)
    sibling_attrs = {**attrs, "net_color": "绿网九分头", "size": "L"}
    _seed_order_dicts(db, sibling_attrs)
    _persist_product(db, sibling_attrs)
    db.commit()
    client = _pricing_api_client(db, user.id, "domestic:admin")

    response = client.get(
        f"/api/domestic/products/{first.id}/base-price-impact"
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "price_key": {
            "product_type": "cap",
            "craft": "递旋",
            "length": "20厘米",
        },
        "affected_sku_count": 2,
        "original_price": 1498.0,
        "version": 3,
    }


@pytest.mark.parametrize(
    (
        "membership_level",
        "last_recharge",
        "expected_price",
        "expected_rule",
        "expected_rule_label",
    ),
    [
        (None, None, "1198.00", "base_price", "非会员原价"),
        ("silver", "10000.00", "1048.00", "member_fixed", "银卡固定会员价"),
        ("black", "30000.00", "998.00", "member_fixed", "黑卡固定会员价"),
        ("supreme", "100000.00", "960.00", "member_fixed", "至尊固定会员价"),
    ],
)
def test_quote_returns_non_member_and_current_member_contracts(
    db,
    membership_level,
    last_recharge,
    expected_price,
    expected_rule,
    expected_rule_label,
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
    assert priced["pricing_rule_label"] == expected_rule_label
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

    assert by_key["fixed"]["pricing_rule_label"] == "银卡固定会员价"
    assert by_key["reduced"]["discount_price"] == D("770.00")
    assert by_key["reduced"]["discount_amount"] == D("70.00")
    assert by_key["reduced"]["pricing_rule_label"] == "银卡立减 ¥70.00"
    assert by_key["capped"]["discount_price"] == D("1600.00")
    assert by_key["capped"]["pricing_rule"] == "member_fixed_capped"
    assert (
        by_key["capped"]["pricing_rule_label"]
        == "命中固定会员价，但原价更低，已按原价"
    )


class _TransactionTestSession:
    def __init__(self, dialect_name):
        self.dialect_name = dialect_name
        self.commit_count = 0
        self.rollback_count = 0

    def get_bind(self):
        return type(
            "Bind", (), {"dialect": type("Dialect", (), {"name": self.dialect_name})()}
        )()

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def _db_operational_error(code):
    return OperationalError("UPDATE base price", {}, Exception(code, "lock error"))


@pytest.mark.parametrize(
    ("dialect_name", "error_code"),
    [("mysql", 1213), ("mariadb", 1205)],
)
def test_mysql_deadlock_retries_whole_base_price_transaction_once(
    dialect_name, error_code
):
    from app.domestic import router as domestic_router

    session = _TransactionTestSession(dialect_name)
    outcomes = iter([_db_operational_error(error_code), {"version": 1}])
    call_count = 0

    def operation():
        nonlocal call_count
        call_count += 1
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    result = domestic_router._run_base_price_transaction(session, operation)

    assert result == {"version": 1}
    assert call_count == 2
    assert session.rollback_count == 1
    assert session.commit_count == 1


@pytest.mark.parametrize(
    ("dialect_name", "codes", "expected_calls", "expected_rollbacks"),
    [
        ("mysql", [1205, 1213], 2, 2),
        ("mysql", [2006], 1, 1),
        ("sqlite", [1213], 1, 1),
    ],
)
def test_base_price_transaction_does_not_over_retry_operational_errors(
    dialect_name, codes, expected_calls, expected_rollbacks
):
    from app.domestic import router as domestic_router

    session = _TransactionTestSession(dialect_name)
    errors = iter(_db_operational_error(code) for code in codes)
    call_count = 0

    def operation():
        nonlocal call_count
        call_count += 1
        raise next(errors)

    with pytest.raises(OperationalError):
        domestic_router._run_base_price_transaction(session, operation)

    assert call_count == expected_calls
    assert session.rollback_count == expected_rollbacks
    assert session.commit_count == 0


def test_quote_api_returns_priced_and_missing_json_contract_with_exact_labels(db):
    user = _operator(db, "quote-mixed-json")
    customer = domestic_models.DomesticCustomer(
        shop_name="黑卡混合报价客户",
        membership_level="black",
        last_recharge_amount=D("30000.00"),
        created_by=user.id,
    )
    db.add(customer)
    priced_product = _configured_product(db, _piece_attrs(), "840.00", version=7)
    client = _pricing_api_client(db, user.id, "domestic:write")

    response = client.post(
        "/api/domestic/pricing/quote",
        json={
            "customer_id": customer.id,
            "items": [
                {"client_key": "priced", "product_id": priced_product.id},
                {
                    "client_key": "missing",
                    "attrs": _cap_attrs(craft="大U型", length="40厘米"),
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["customer"]["membership_level"] == "black"
    priced, missing = payload["items"]
    assert priced == {
        "client_key": "priced",
        "status": "priced",
        "product_id": priced_product.id,
        "original_price": 840.0,
        "base_price_version": 7,
        "discount_price": 720.0,
        "discount_amount": 120.0,
        "pricing_rule": "member_reduction",
        "pricing_rule_label": "黑卡立减 ¥120.00",
        "pricing_version": "domestic-member-v1",
        "expected_quote": {
            "original_price": 840.0,
            "base_price_version": 7,
            "discount_price": 720.0,
            "membership_level": "black",
            "pricing_rule": "member_reduction",
            "pricing_version": "domestic-member-v1",
        },
    }
    assert missing["client_key"] == "missing"
    assert missing["status"] == "missing_base_price"
    assert isinstance(missing["product_id"], int)
    assert "expected_quote" not in missing


@pytest.mark.parametrize(
    "attrs",
    [
        _cap_attrs(craft="特单手织工艺", length="47厘米"),
        _piece_attrs(craft="海报外发片Code", length="47厘米"),
    ],
    ids=["custom-cap", "custom-piece"],
)
def test_custom_sku_can_move_from_missing_to_priced_and_back(db, attrs):
    user = _operator(db, f"custom-price-{attrs['product_type']}")
    customer = domestic_models.DomesticCustomer(
        shop_name=f"特单报价客户-{attrs['product_type']}",
        membership_level="black",
        last_recharge_amount=D("30000.00"),
        created_by=user.id,
    )
    db.add(customer)
    product = _persist_product(db, attrs)
    db.commit()
    writer = _pricing_api_client(db, user.id, "domestic:write")
    admin = _pricing_api_client(db, user.id, "domestic:admin")
    quote_payload = {
        "customer_id": customer.id,
        "items": [{"client_key": "custom", "product_id": product.id}],
    }

    assert pricing_service.get_base_price(
        product_type=product.product_type,
        craft=product.craft,
        length=product.length,
        size=product.size if product.product_type == "piece" else None,
    ) is None
    missing_list = admin.get(
        "/api/domestic/products", params={"price_status": "missing"}
    ).json()["data"]
    assert missing_list["total"] == 1
    assert missing_list["items"][0]["price_key"] == {
        "product_type": product.product_type,
        "craft": product.craft,
        "length": product.length,
    }
    missing_quote = writer.post(
        "/api/domestic/pricing/quote", json=quote_payload
    ).json()["data"]["items"][0]
    assert missing_quote["status"] == "missing_base_price"

    saved = admin.put(
        f"/api/domestic/products/{product.id}/base-price",
        json={"original_price": "1000.00"},
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["affected_sku_count"] == 1
    configured_list = admin.get(
        "/api/domestic/products", params={"price_status": "configured"}
    ).json()["data"]
    assert configured_list["total"] == 1
    priced = writer.post(
        "/api/domestic/pricing/quote", json=quote_payload
    ).json()["data"]["items"][0]
    assert priced["status"] == "priced"
    assert priced["original_price"] == 1000.0
    assert priced["discount_price"] == 880.0
    assert priced["discount_amount"] == 120.0
    assert priced["pricing_rule"] == "member_reduction"
    assert priced["pricing_rule_label"] == "黑卡立减 ¥120.00"

    deleted = admin.delete(f"/api/domestic/products/{product.id}/base-price")
    assert deleted.status_code == 200
    missing_again = writer.post(
        "/api/domestic/pricing/quote", json=quote_payload
    ).json()["data"]["items"][0]
    assert missing_again["status"] == "missing_base_price"


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


# ── 下单时服务端权威锁价 ──────────────────────────────


def _seed_order_dicts(db, attrs):
    from app.system.models import SysDict

    values = {
        domestic_constants.ORDER_TYPE_DICT: "first_order",
        domestic_constants.ORDER_CHANNEL_DICT: "wechat",
    }
    for field, dict_type in domestic_constants.ATTR_DICTS[attrs["product_type"]].items():
        value = attrs.get(field)
        if value is not None:
            values[dict_type] = value
    for dict_type, code in values.items():
        if not db.query(SysDict.id).filter_by(type=dict_type, code=code).first():
            db.add(
                SysDict(
                    type=dict_type,
                    code=code,
                    label=code,
                    sort=1,
                    is_active=True,
                )
            )
    db.flush()


def _order_pricing_context(
    db,
    suffix,
    *,
    attrs=None,
    original_price="1000.00",
    version=1,
    membership_level="black",
    balance="10000.00",
):
    attrs = attrs or _cap_attrs(length="20厘米")
    user = _operator(db, f"order-pricing-{suffix}")
    customer = domestic_models.DomesticCustomer(
        shop_name=f"订单锁价客户-{suffix}",
        membership_level=membership_level,
        balance=D(balance),
        created_by=user.id,
    )
    db.add(customer)
    _seed_order_dicts(db, attrs)
    product = _persist_product(db, attrs)
    key = pricing_service.price_key_for_product(product)
    assert key is not None
    base = domestic_models.DomesticBasePrice(
        product_type=key[0],
        craft=key[1],
        length=key[2],
        original_price=D(original_price),
        version=version,
        updated_by=user.id,
    )
    db.add(base)
    db.flush()
    discount = pricing_service.resolve_discount(
        product_type=product.product_type,
        craft=product.craft,
        size=product.size if product.product_type == "piece" else None,
        length=product.length,
        original_price=base.original_price,
        membership_level=membership_level,
    )
    expected = {
        "original_price": discount.original_price,
        "base_price_version": base.version,
        "discount_price": discount.final_price,
        "membership_level": membership_level,
        "pricing_rule": discount.pricing_rule,
        "pricing_version": pricing_service.PRICING_VERSION,
    }
    db.commit()
    return user, customer, product, base, expected, attrs


def _priced_order_payload(
    customer,
    attrs,
    expected,
    *,
    request_id,
    qty=1,
    is_draft=False,
    client_key="line-1",
    items=None,
):
    return OrderCreate.model_validate(
        {
            "request_id": request_id,
            "order_no": request_id,
            "order_date": "2026-09-02",
            "customer_id": customer.id,
            "order_category": "normal",
            "order_type": "first_order",
            "order_channel": "wechat",
            "is_draft": is_draft,
            "items": items
            or [
                {
                    "client_key": client_key,
                    "attrs": attrs,
                    "order_qty": qty,
                    "expected_quote": expected,
                }
            ],
        }
    )


def _saved_item_expected(item):
    return {
        "item_id": item.id,
        "original_price": item.original_price,
        "base_price_version": item.base_price_version_snapshot,
        "discount_price": item.unit_price,
        "membership_level": item.membership_level_snapshot,
        "pricing_rule": item.pricing_rule,
        "pricing_version": item.pricing_version,
    }


def _current_item_expected(db, item, customer):
    product = db.get(domestic_models.DomesticProduct, item.product_id)
    key = pricing_service.price_key_for_product(product)
    base = db.query(domestic_models.DomesticBasePrice).filter_by(
        product_type=key[0], craft=key[1], length=key[2]
    ).one()
    discount = pricing_service.resolve_discount(
        product_type=product.product_type,
        craft=product.craft,
        length=product.length,
        size=product.size if product.product_type == "piece" else None,
        original_price=base.original_price,
        membership_level=customer.membership_level,
    )
    return {
        "item_id": item.id,
        "original_price": discount.original_price,
        "base_price_version": base.version,
        "discount_price": discount.final_price,
        "membership_level": customer.membership_level,
        "pricing_rule": discount.pricing_rule,
        "pricing_version": pricing_service.PRICING_VERSION,
    }


def _draft_submit_payload(request_id, *items):
    return DraftSubmitRequest.model_validate({
        "request_id": request_id,
        "expected_quotes": [_saved_item_expected(item) for item in items],
    })


def _created_priced_draft(
    db,
    suffix,
    *,
    membership_level=None,
    balance="5000.00",
    original_price="1000.00",
    qty=1,
    attrs=None,
):
    user, customer, product, base, expected, attrs = _order_pricing_context(
        db,
        suffix,
        original_price=original_price,
        membership_level=membership_level,
        balance=balance,
        attrs=attrs,
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer,
            attrs,
            expected,
            request_id=f"{suffix}-create-draft",
            is_draft=True,
            qty=qty,
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).one()
    return user, customer, product, base, order, item


def test_migrated_legacy_draft_detail_can_be_submitted_to_receive_current_quote_409(db):
    user, _customer, _product, _base, order, item = _created_priced_draft(
        db, "migrated-legacy-draft", membership_level="black"
    )
    item.original_price = D("0.00")
    item.unit_price = D("0.00")
    item.discount_amount = D("0.00")
    item.membership_level_snapshot = None
    item.pricing_rule = "legacy_manual"
    item.pricing_version = "legacy"
    item.base_price_version_snapshot = 0
    order.total_amount = D("0.00")
    db.commit()

    detail = order_service.get_order_detail(db, order.id)
    payload = DraftSubmitRequest.model_validate({
        "request_id": "migrated-legacy-submit",
        "expected_quotes": detail["current_expected_quotes"],
    })

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.submit_draft(db, order.id, payload, user.id)

    assert caught.value.detail["changes"][0]["item_id"] == item.id
    assert caught.value.detail["current_expected_quotes"][0]["pricing_rule"] == "member_reduction"
    db.refresh(order)
    assert order.status == domestic_constants.ORDER_DRAFT
    assert order.total_amount == D("0.00")


def test_submit_draft_reprices_membership_atomically_then_charges_confirmed_quote(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db,
        "draft-submit-membership",
        original_price="1000.00",
        membership_level="silver",
        balance="1000.00",
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer,
            attrs,
            expected,
            request_id="draft-submit-membership-create",
            is_draft=True,
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).one()
    stale = _draft_submit_payload("draft-submit-membership-stale", item)
    original_snapshot = _saved_item_expected(item)
    balance_service.recharge_customer(
        db,
        customer_id=customer.id,
        amount=D("30000.00"),
        user_id=user.id,
        request_id="draft-submit-black-recharge",
    )
    balance_before = customer.balance

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.submit_draft(db, order.id, stale, user.id)

    detail = caught.value.detail
    assert detail["changes"] == [{
        "client_key": None,
        "item_id": item.id,
        "reasons": ["membership_changed"],
        "previous_quote": {key: float(value) if isinstance(value, D) else value for key, value in original_snapshot.items() if key != "item_id"},
        "current_quote": detail["changes"][0]["current_quote"],
    }]
    assert detail["current_expected_quotes"][0]["item_id"] == item.id
    assert detail["current_expected_quotes"][0]["client_key"] is None
    assert detail["retry_requires_new_request_id"] is True
    db.refresh(order)
    db.refresh(item)
    db.refresh(customer)
    assert order.status == domestic_constants.ORDER_DRAFT
    assert order.total_amount == original_snapshot["discount_price"]
    assert order.charged_amount == D("0.00")
    assert _saved_item_expected(item) == original_snapshot
    assert customer.balance == balance_before
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 0

    current = DraftSubmitRequest.model_validate({
        "request_id": "draft-submit-membership-confirm",
        "expected_quotes": detail["current_expected_quotes"],
    })
    result = order_service.submit_draft(db, order.id, current, user.id)

    db.refresh(order)
    db.refresh(item)
    db.refresh(customer)
    assert result["replayed"] is False
    assert order.status == domestic_constants.ORDER_PRODUCING
    assert order.total_amount == D("880.00")
    assert order.charged_amount == D("880.00")
    assert item.membership_level_snapshot == "black"
    assert item.unit_price == D("880.00")
    assert customer.balance == balance_before - D("880.00")


def test_submit_draft_price_change_is_all_or_nothing_and_missing_price_is_409(db):
    user, customer, _product, base, expected, attrs = _order_pricing_context(
        db, "draft-submit-base", original_price="1000.00", membership_level=None
    )
    attrs_b = _cap_attrs(craft="草稿第二行工艺", length="21厘米")
    _seed_order_dicts(db, attrs_b)
    product_b = _persist_product(db, attrs_b)
    db.add(domestic_models.DomesticBasePrice(
        product_type="cap", craft=attrs_b["craft"], length=attrs_b["length"],
        original_price=D("1100.00"), version=1, updated_by=user.id,
    ))
    db.commit()
    expected_b = _expected_quote_payload(
        original_price="1100.00", discount_price="1100.00"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer,
            attrs,
            expected,
            request_id="draft-submit-base-create",
            is_draft=True,
            items=[
                {"client_key": "a", "attrs": attrs, "order_qty": 1, "expected_quote": expected},
                {"client_key": "b", "attrs": attrs_b, "order_qty": 1, "expected_quote": expected_b},
            ],
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    items = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).order_by(domestic_models.DomesticOrderItem.id).all()
    snapshots = [_saved_item_expected(item) for item in items]
    payload = _draft_submit_payload("draft-submit-base-stale", *items)
    base.original_price = D("1200.00")
    base.version = 2
    db.commit()

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.submit_draft(db, order.id, payload, user.id)

    assert caught.value.detail["changes"][0]["item_id"] == items[0].id
    assert caught.value.detail["changes"][0]["reasons"] == ["base_price_changed"]
    assert [_saved_item_expected(item) for item in items] == snapshots
    assert order.total_amount == D("2100.00")
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 0

    db.delete(base)
    db.commit()
    with pytest.raises(pricing_service.DomesticQuoteChangedError) as missing:
        order_service.submit_draft(
            db,
            order.id,
            _draft_submit_payload("draft-submit-base-missing", *items),
            user.id,
        )
    change = missing.value.detail["changes"][0]
    assert change["item_id"] == items[0].id
    assert change["client_key"] is None
    assert change["reasons"] == ["price_missing"]
    assert change["current_quote"] is None
    assert change["current_status"] == "missing_base_price"
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 0


def test_submit_draft_insufficient_balance_rolls_back_prices_status_and_request(db):
    user, customer, _product, _base, order, item = _created_priced_draft(
        db,
        "draft-submit-insufficient",
        balance="100.00",
        original_price="1000.00",
    )
    snapshot = _saved_item_expected(item)
    payload = _draft_submit_payload("draft-submit-insufficient-request", item)

    with pytest.raises(ValueError, match="余额不足"):
        order_service.submit_draft(db, order.id, payload, user.id)

    db.refresh(order)
    db.refresh(item)
    db.refresh(customer)
    assert order.status == domestic_constants.ORDER_DRAFT
    assert order.charged_amount == D("0.00")
    assert _saved_item_expected(item) == snapshot
    assert customer.balance == D("100.00")
    assert db.query(domestic_models.DomesticCustomerLedger).count() == 0
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 0


def test_submit_draft_flushes_repriced_items_with_autoflush_disabled(db):
    user, customer, _product, _base, order, item = _created_priced_draft(
        db,
        "draft-submit-no-autoflush",
        membership_level=None,
        balance="5000.00",
        original_price="1000.00",
    )
    customer.membership_level = "black"
    db.commit()
    current = _current_item_expected(db, item, customer)
    NoAutoflushSession = sessionmaker(
        bind=db.get_bind(), autoflush=False, expire_on_commit=False
    )

    with NoAutoflushSession() as session:
        result = order_service.submit_draft(
            session,
            order.id,
            DraftSubmitRequest.model_validate({
                "request_id": "draft-submit-no-autoflush-request",
                "expected_quotes": [current],
            }),
            user.id,
        )

        saved_order = session.get(domestic_models.DomesticOrder, order.id)
        saved_item = session.get(domestic_models.DomesticOrderItem, item.id)
        saved_customer = session.get(domestic_models.DomesticCustomer, customer.id)
        ledger = session.query(domestic_models.DomesticCustomerLedger).filter_by(
            order_id=order.id
        ).one()
        assert result["total_amount"] == 880.0
        assert result["charged_amount"] == 880.0
        assert saved_item.unit_price == D("880.00")
        assert saved_order.total_amount == D("880.00")
        assert saved_order.charged_amount == D("880.00")
        assert ledger.amount == D("-880.00")
        assert saved_customer.balance == D("4120.00")


def test_reprice_customer_flushes_items_with_autoflush_disabled_without_charge(db):
    user, source, _product, _base, order, item = _created_priced_draft(
        db,
        "draft-customer-no-autoflush",
        membership_level=None,
        balance="5000.00",
        original_price="1000.00",
    )
    target = domestic_models.DomesticCustomer(
        shop_name="关闭自动刷新换客目标",
        membership_level="black",
        balance=D("7000.00"),
        created_by=user.id,
    )
    db.add(target)
    db.commit()
    current = _current_item_expected(db, item, target)
    NoAutoflushSession = sessionmaker(
        bind=db.get_bind(), autoflush=False, expire_on_commit=False
    )

    with NoAutoflushSession() as session:
        result = order_service.update_order(
            session,
            order.id,
            _customer_reprice_payload(
                "draft-customer-no-autoflush-request",
                target.id,
                [current],
            ),
        )

        saved_order = session.get(domestic_models.DomesticOrder, order.id)
        saved_item = session.get(domestic_models.DomesticOrderItem, item.id)
        saved_source = session.get(domestic_models.DomesticCustomer, source.id)
        saved_target = session.get(domestic_models.DomesticCustomer, target.id)
        assert result["total_amount"] == 880.0
        assert result["charged_amount"] == 0.0
        assert saved_item.unit_price == D("880.00")
        assert saved_order.total_amount == D("880.00")
        assert saved_order.charged_amount == D("0.00")
        assert saved_source.balance == D("5000.00")
        assert saved_target.balance == D("7000.00")
        assert session.query(domestic_models.DomesticCustomerLedger).count() == 0


def test_submit_draft_success_replays_after_price_change_without_second_charge(db):
    user, customer, _product, base, order, item = _created_priced_draft(
        db, "draft-submit-replay", balance="5000.00"
    )
    payload = _draft_submit_payload("draft-submit-replay-request", item)

    first = order_service.submit_draft(db, order.id, payload, user.id)
    balance_after_first = db.get(
        domestic_models.DomesticCustomer, customer.id
    ).balance
    ledger_count = db.query(domestic_models.DomesticCustomerLedger).count()
    base.original_price = D("1500.00")
    base.version = 2
    customer.membership_level = "supreme"
    db.commit()

    replay = order_service.submit_draft(db, order.id, payload, user.id)

    assert replay == {**first, "replayed": True}
    assert db.get(domestic_models.DomesticCustomer, customer.id).balance == balance_after_first
    assert db.query(domestic_models.DomesticCustomerLedger).count() == ledger_count
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 1


def test_submit_draft_same_request_with_different_hash_is_rejected_before_status(db):
    user, _customer, _product, _base, order, item = _created_priced_draft(
        db, "draft-submit-diff-hash"
    )
    payload = _draft_submit_payload("draft-submit-diff-hash-request", item)
    order_service.submit_draft(db, order.id, payload, user.id)
    changed = payload.model_copy(deep=True)
    changed.expected_quotes[0].pricing_version = "domestic-member-v0"

    with pytest.raises(ValueError, match="不同内容"):
        order_service.submit_draft(db, order.id, changed, user.id)

    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 1


def test_submit_draft_rejects_changed_item_set_without_pricing_request(db):
    user, _customer, _product, _base, order, item = _created_priced_draft(
        db, "draft-submit-item-set"
    )
    quote = _saved_item_expected(item)
    quote["item_id"] = item.id + 999
    payload = DraftSubmitRequest.model_validate({
        "request_id": "draft-submit-item-set-request",
        "expected_quotes": [quote],
    })

    with pytest.raises(ValueError, match="明细已变化.*刷新"):
        order_service.submit_draft(db, order.id, payload, user.id)

    assert order.status == domestic_constants.ORDER_DRAFT
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 0


def _customer_reprice_payload(request_id, customer_id, quotes, **fields):
    return OrderUpdate.model_validate({
        "customer_id": customer_id,
        "request_id": request_id,
        "expected_quotes": quotes,
        **fields,
    })


def test_update_draft_customer_409_is_atomic_then_confirm_updates_all_fields(db):
    user, source, _product, _base, order, item = _created_priced_draft(
        db,
        "draft-customer-atomic",
        membership_level=None,
        original_price="1000.00",
    )
    target = domestic_models.DomesticCustomer(
        shop_name="至尊换客目标",
        membership_level="supreme",
        balance=D("9000.00"),
        created_by=user.id,
    )
    db.add(target)
    db.commit()
    stale = _customer_reprice_payload(
        "draft-customer-atomic-stale",
        target.id,
        [_saved_item_expected(item)],
        order_no="换客后订单号",
        remark="换客后备注",
    )
    original = {
        "customer_id": order.customer_id,
        "order_no": order.order_no,
        "remark": order.remark,
        "total_amount": order.total_amount,
        "snapshot": _saved_item_expected(item),
    }

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.update_order(db, order.id, stale)

    detail = caught.value.detail
    assert detail["changes"][0]["item_id"] == item.id
    assert detail["changes"][0]["client_key"] is None
    assert detail["changes"][0]["reasons"] == ["membership_changed"]
    db.refresh(order)
    db.refresh(item)
    assert {
        "customer_id": order.customer_id,
        "order_no": order.order_no,
        "remark": order.remark,
        "total_amount": order.total_amount,
        "snapshot": _saved_item_expected(item),
    } == original
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 0

    confirmed = _customer_reprice_payload(
        "draft-customer-atomic-confirm",
        target.id,
        detail["current_expected_quotes"],
        order_no="换客后订单号",
        remark="换客后备注",
    )
    result = order_service.update_order(db, order.id, confirmed)

    db.refresh(order)
    db.refresh(item)
    db.refresh(source)
    db.refresh(target)
    assert result["replayed"] is False
    assert order.customer_id == target.id
    assert order.order_no == "换客后订单号"
    assert order.remark == "换客后备注"
    assert item.membership_level_snapshot == "supreme"
    assert order.total_amount == item.unit_price
    assert order.charged_amount == D("0.00")
    assert source.balance == D("5000.00")
    assert target.balance == D("9000.00")
    request = db.query(domestic_models.DomesticOrderPricingRequest).one()
    assert request.operation == "reprice_customer"


def test_update_draft_customer_replay_and_hash_cover_other_header_fields(db):
    user, _source, _product, base, order, item = _created_priced_draft(
        db, "draft-customer-replay", membership_level=None
    )
    payload = _customer_reprice_payload(
        "draft-customer-replay-request",
        order.customer_id,
        [_saved_item_expected(item)],
        remark="第一次成功结果",
    )

    first = order_service.update_order(db, order.id, payload)
    base.original_price = D("1300.00")
    base.version = 2
    db.commit()
    replay = order_service.update_order(db, order.id, payload)

    assert replay == {**first, "replayed": True}
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 1
    changed = payload.model_copy(deep=True)
    changed.remark = "同键不同头字段"
    with pytest.raises(ValueError, match="不同内容"):
        order_service.update_order(db, order.id, changed)
    assert order.remark == "第一次成功结果"


def test_update_customer_rejects_formal_order_and_missing_price_without_record(db):
    user, customer, _product, base, order, item = _created_priced_draft(
        db, "draft-customer-formal-missing"
    )
    submit = _draft_submit_payload("draft-customer-formal-submit", item)
    order_service.submit_draft(db, order.id, submit, user.id)
    formal_payload = _customer_reprice_payload(
        "draft-customer-formal-request",
        customer.id,
        [_saved_item_expected(item)],
    )
    with pytest.raises(ValueError, match="草稿.*更换客户"):
        order_service.update_order(db, order.id, formal_payload)
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 1

    user2, customer2, _product2, base2, order2, item2 = _created_priced_draft(
        db,
        "draft-customer-missing",
        attrs=_cap_attrs(craft="换客缺价工艺", length="22厘米"),
    )
    before = _saved_item_expected(item2)
    db.delete(base2)
    db.commit()
    missing_payload = _customer_reprice_payload(
        "draft-customer-missing-request",
        customer2.id,
        [before],
        remark="不应写入",
    )
    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.update_order(db, order2.id, missing_payload)
    assert caught.value.detail["changes"][0]["current_status"] == "missing_base_price"
    db.refresh(order2)
    db.refresh(item2)
    assert order2.remark is None
    assert _saved_item_expected(item2) == before
    assert db.query(domestic_models.DomesticOrderPricingRequest).filter_by(
        order_id=order2.id
    ).count() == 0


def test_draft_repricing_routes_require_submit_body_and_return_unified_409(db):
    user, customer, _product, _base, order, item = _created_priced_draft(
        db, "draft-repricing-routes", membership_level=None
    )
    stale = _draft_submit_payload("draft-repricing-route-submit", item)
    customer.membership_level = "black"
    db.commit()
    client = _pricing_api_client(
        db,
        user.id,
        "domestic:write",
        raise_server_exceptions=False,
    )

    missing_body = client.post(f"/api/domestic/orders/{order.id}/submit")
    submit_changed = client.post(
        f"/api/domestic/orders/{order.id}/submit",
        json=stale.model_dump(mode="json"),
    )
    update_changed = client.put(
        f"/api/domestic/orders/{order.id}",
        json={
            "customer_id": customer.id,
            "request_id": "draft-repricing-route-update",
            "expected_quotes": [
                quote.model_dump(mode="json") for quote in stale.expected_quotes
            ],
        },
    )

    assert missing_body.status_code == 422
    assert submit_changed.status_code == 409
    assert update_changed.status_code == 409
    for response in (submit_changed, update_changed):
        assert response.json()["detail"]["error_code"] == "DOMESTIC_QUOTE_CHANGED"
        assert response.json()["detail"]["changes"][0]["item_id"] == item.id


def test_submit_draft_mysql_sql_shape_locks_order_customer_items_then_base_prices(db):
    user, _customer, _product, _base, order, item = _created_priced_draft(
        db, "draft-submit-lock-shape"
    )
    statements = []

    def capture(execute_state):
        compiled = str(
            execute_state.statement.compile(dialect=mysql.dialect())
        ).lower()
        if any(table in compiled for table in (
            "ark_domestic_orders",
            "ark_domestic_customers",
            "ark_domestic_order_items",
            "ark_domestic_base_prices",
        )):
            statements.append(compiled)

    event.listen(db, "do_orm_execute", capture)
    try:
        order_service.submit_draft(
            db,
            order.id,
            _draft_submit_payload("draft-submit-lock-shape-request", item),
            user.id,
        )
    finally:
        event.remove(db, "do_orm_execute", capture)

    order_lock = next(i for i, sql in enumerate(statements) if (
        "ark_domestic_orders" in sql and "for update" in sql
    ))
    customer_lock = next(i for i, sql in enumerate(statements) if (
        "ark_domestic_customers" in sql and "for update" in sql
    ))
    item_lock = next(i for i, sql in enumerate(statements) if (
        "ark_domestic_order_items" in sql
        and "for update" in sql
        and "order by ark_domestic_order_items.id asc" in sql
    ))
    base_lock = next(i for i, sql in enumerate(statements) if (
        "ark_domestic_base_prices" in sql
        and "for update" in sql
        and "order by ark_domestic_base_prices.id asc" in sql
    ))
    assert order_lock < customer_lock < item_lock < base_lock


def test_item_update_mysql_sql_shape_locks_order_before_item(db):
    _user, _customer, _product, _base, order, item = _created_priced_draft(
        db, "item-update-lock-shape"
    )
    statements = []

    def capture(execute_state):
        compiled = str(
            execute_state.statement.compile(dialect=mysql.dialect())
        ).lower()
        if "for update" in compiled and any(table in compiled for table in (
            "ark_domestic_orders", "ark_domestic_order_items"
        )):
            statements.append(compiled)

    event.listen(db, "do_orm_execute", capture)
    try:
        order_service.update_item(
            db,
            item.id,
            OrderItemUpdate(remark="锁序测试"),
        )
    finally:
        event.remove(db, "do_orm_execute", capture)

    order_lock = next(i for i, sql in enumerate(statements) if (
        "ark_domestic_orders" in sql
    ))
    item_lock = next(i for i, sql in enumerate(statements) if (
        "ark_domestic_order_items" in sql
    ))
    assert order_lock < item_lock


def test_concurrent_sqlite_duplicate_submit_charges_exactly_once(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'draft-submit-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as seed:
            user, customer, _product, _base, order, item = _created_priced_draft(
                seed, "draft-submit-race", balance="5000.00"
            )
            order_id = order.id
            user_id = user.id
            customer_id = customer.id
            payload_json = _draft_submit_payload(
                "draft-submit-race-request", item
            ).model_dump(mode="json")

        start = threading.Barrier(2, timeout=10)

        def submit_once():
            with Session() as session:
                start.wait()
                return order_service.submit_draft(
                    session,
                    order_id,
                    DraftSubmitRequest.model_validate(payload_json),
                    user_id,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result(timeout=20) for future in (
                executor.submit(submit_once), executor.submit(submit_once)
            )]

        assert {result["replayed"] for result in results} == {False, True}
        with Session() as verify:
            order_row = verify.get(domestic_models.DomesticOrder, order_id)
            customer_row = verify.get(domestic_models.DomesticCustomer, customer_id)
            assert order_row.status == domestic_constants.ORDER_PRODUCING
            assert customer_row.balance == D("4000.00")
            assert verify.query(domestic_models.DomesticCustomerLedger).count() == 1
            assert verify.query(domestic_models.DomesticOrderPricingRequest).count() == 1
    finally:
        engine.dispose()


def test_formal_black_order_charges_discount_and_persists_pricing_snapshot(db):
    user, customer, product, _base, expected, attrs = _order_pricing_context(
        db, "black-reduction", original_price="1000.00", membership_level="black"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="black-reduction-order", qty=2
        ),
        user.id,
    )

    item = db.query(domestic_models.DomesticOrderItem).one()
    order = db.get(domestic_models.DomesticOrder, created["id"])
    db.refresh(customer)
    db.refresh(product)
    detail = order_service.get_order_detail(db, order.id)
    detail_item = detail["items"][0]

    assert customer.balance == D("8240.00")
    assert order.total_amount == D("1760.00")
    assert order.charged_amount == D("1760.00")
    assert item.original_price == D("1000.00")
    assert item.unit_price == D("880.00")
    assert item.discount_amount == D("120.00")
    assert item.membership_level_snapshot == "black"
    assert item.pricing_rule == "member_reduction"
    assert item.pricing_version == "domestic-member-v1"
    assert item.base_price_version_snapshot == 1
    assert product.use_count == 1
    assert detail_item["original_price"] == 1000.0
    assert detail_item["unit_price"] == 880.0
    assert detail_item["discount_amount"] == 120.0
    assert detail_item["membership_level_snapshot"] == "black"
    assert detail_item["pricing_rule"] == "member_reduction"
    assert detail_item["pricing_rule_label"] == "黑卡立减 ¥120.00"
    assert detail_item["pricing_version"] == "domestic-member-v1"
    assert detail_item["base_price_version"] == 1
    assert detail["current_expected_quotes"] == [{
        "client_key": None,
        "item_id": item.id,
        "original_price": 1000.0,
        "base_price_version": 1,
        "discount_price": 880.0,
        "membership_level": "black",
        "pricing_rule": "member_reduction",
        "pricing_version": "domestic-member-v1",
    }]


@pytest.mark.parametrize(
    (
        "suffix",
        "attrs",
        "original",
        "membership",
        "discount",
        "rule",
    ),
    [
        ("nonmember", _cap_attrs(length="20厘米"), "1498", None, "1498", "base_price"),
        ("fixed", _cap_attrs(length="15厘米", density="80%"), "1198", "black", "998", "member_fixed"),
        ("fixed-cap", _cap_attrs(craft="递顶", length="20厘米"), "1600", "silver", "1600", "member_fixed_capped"),
    ],
)
def test_order_uses_server_rule_for_nonmember_fixed_and_capped(
    db, suffix, attrs, original, membership, discount, rule
):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db,
        suffix,
        attrs=attrs,
        original_price=original,
        membership_level=membership,
        balance="2000",
    )
    result = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id=f"{suffix}-priced-order"
        ),
        user.id,
    )
    item = db.query(domestic_models.DomesticOrderItem).one()
    assert item.unit_price == D(discount)
    assert item.pricing_rule == rule
    assert result["total_amount"] == float(D(discount))


def test_discount_balance_threshold_and_draft_charge_contract(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db,
        "discount-balance",
        original_price="1000",
        membership_level="black",
        balance="880",
    )
    formal = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="discount-balance-formal"
        ),
        user.id,
    )
    assert formal["total_amount"] == 880.0
    db.refresh(customer)
    assert customer.balance == D("0.00")

    user2, customer2, _product2, _base2, expected2, attrs2 = _order_pricing_context(
        db,
        "insufficient-discount",
        attrs=_cap_attrs(craft="自定义不足工艺", length="22厘米"),
        original_price="1000",
        membership_level="black",
        balance="879.99",
    )
    with pytest.raises(ValueError, match="余额不足"):
        order_service.create_order(
            db,
            _priced_order_payload(
                customer2,
                attrs2,
                expected2,
                request_id="discount-balance-insufficient",
            ),
            user2.id,
        )
    assert db.query(domestic_models.DomesticOrder).count() == 1

    user3, customer3, _product3, _base3, expected3, attrs3 = _order_pricing_context(
        db,
        "draft-no-charge",
        attrs=_cap_attrs(craft="自定义草稿工艺", length="24厘米"),
        original_price="1000",
        membership_level="black",
        balance="0",
    )
    draft = order_service.create_order(
        db,
        _priced_order_payload(
            customer3,
            attrs3,
            expected3,
            request_id="discount-balance-draft",
            is_draft=True,
        ),
        user3.id,
    )
    db.refresh(customer3)
    draft_order = db.get(domestic_models.DomesticOrder, draft["id"])
    assert customer3.balance == D("0.00")
    assert draft_order.total_amount == D("880.00")
    assert draft_order.charged_amount == D("0.00")


@pytest.mark.parametrize(
    ("field", "stale_value", "reason"),
    [
        ("original_price", D("999.99"), "base_price_changed"),
        ("base_price_version", 99, "base_price_changed"),
        ("discount_price", D("879.99"), "rule_changed"),
        ("membership_level", "silver", "membership_changed"),
        ("pricing_rule", "member_fixed", "rule_changed"),
        ("pricing_version", "domestic-member-v0", "rule_changed"),
    ],
)
def test_create_returns_409_for_each_stale_or_tampered_quote_field(
    db, field, stale_value, reason
):
    user, customer, product, _base, expected, attrs = _order_pricing_context(
        db, f"quote-change-{field}", original_price="1000"
    )
    expected = {**expected, field: stale_value}
    payload = _priced_order_payload(
        customer, attrs, expected, request_id=f"quote-change-{field}-request"
    )
    client = _pricing_api_client(db, user.id, "domestic:write")

    response = client.post(
        "/api/domestic/orders", json=payload.model_dump(mode="json")
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "DOMESTIC_QUOTE_CHANGED"
    assert detail["retry_requires_new_request_id"] is True
    assert detail["changes"][0]["client_key"] == "line-1"
    assert detail["changes"][0]["item_id"] is None
    assert detail["changes"][0]["reasons"] == [reason]
    assert field in detail["changes"][0]["previous_quote"]
    assert len(detail["current_expected_quotes"]) == 1
    assert (
        detail["current_expected_quotes"][0]["pricing_version"]
        == "domestic-member-v1"
    )
    assert db.query(domestic_models.DomesticOrder).count() == 0
    db.refresh(product)
    assert product.use_count == 0


def test_real_membership_change_reports_membership_reason_without_price_noise(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "real-membership-change", original_price="1000", membership_level="black"
    )
    customer.membership_level = "silver"
    db.commit()

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(
            db,
            _priced_order_payload(
                customer,
                attrs,
                expected,
                request_id="real-membership-change-order",
            ),
            user.id,
        )

    change = caught.value.detail["changes"][0]
    assert change["reasons"] == ["membership_changed"]
    assert change["previous_quote"]["discount_price"] == 880.0
    assert change["current_quote"]["discount_price"] == 930.0


def test_membership_loss_reports_only_membership_change_when_rule_also_changes(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "membership-loss", original_price="1000", membership_level="black"
    )
    customer.membership_level = None
    db.commit()

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(
            db,
            _priced_order_payload(
                customer,
                attrs,
                expected,
                request_id="membership-loss-order",
            ),
            user.id,
        )

    change = caught.value.detail["changes"][0]
    assert change["reasons"] == ["membership_changed"]
    assert change["current_quote"]["pricing_rule"] == "base_price"


def test_base_change_reports_only_base_reason_when_fixed_price_becomes_capped(db):
    attrs = _cap_attrs(craft="递顶", length="20厘米")
    user, customer, _product, base, expected, attrs = _order_pricing_context(
        db,
        "fixed-to-capped",
        attrs=attrs,
        original_price="1800",
        membership_level="silver",
    )
    assert expected["pricing_rule"] == "member_fixed"
    base.original_price = D("1600")
    base.version += 1
    db.commit()

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(
            db,
            _priced_order_payload(
                customer,
                attrs,
                expected,
                request_id="fixed-to-capped-order",
            ),
            user.id,
        )

    change = caught.value.detail["changes"][0]
    assert change["reasons"] == ["base_price_changed"]
    assert change["current_quote"]["pricing_rule"] == "member_fixed_capped"


def test_missing_price_and_one_changed_line_roll_back_whole_order(db):
    user, customer, product, base, expected, attrs = _order_pricing_context(
        db, "batch-rollback", original_price="1000"
    )
    missing_attrs = _cap_attrs(craft="未配置批次工艺", length="26厘米")
    _seed_order_dicts(db, missing_attrs)
    missing_product = _persist_product(db, missing_attrs)
    db.commit()
    payload = _priced_order_payload(
        customer,
        attrs,
        expected,
        request_id="batch-price-missing",
        items=[
            {
                "client_key": "priced",
                "attrs": attrs,
                "order_qty": 1,
                "expected_quote": expected,
            },
            {
                "client_key": "missing",
                "attrs": missing_attrs,
                "order_qty": 1,
                "expected_quote": expected,
            },
        ],
    )
    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(db, payload, user.id)
    missing = next(
        row for row in caught.value.detail["changes"] if row["client_key"] == "missing"
    )
    assert missing["reasons"] == ["price_missing"]
    assert missing["current_quote"] is None
    assert missing["current_status"] == "missing_base_price"
    assert [row["client_key"] for row in caught.value.detail["current_expected_quotes"]] == ["priced"]
    assert db.query(domestic_models.DomesticOrder).count() == 0
    db.refresh(product)
    db.refresh(missing_product)
    assert (product.use_count, missing_product.use_count) == (0, 0)

    db.delete(base)
    db.commit()
    with pytest.raises(pricing_service.DomesticQuoteChangedError) as deleted:
        order_service.create_order(
            db,
            _priced_order_payload(
                customer, attrs, expected, request_id="deleted-price-order"
            ),
            user.id,
        )
    assert deleted.value.detail["changes"][0]["reasons"] == ["price_missing"]


def test_one_changed_quote_in_multi_line_order_rolls_back_every_line(db):
    user, customer, product_a, _base_a, expected_a, attrs_a = _order_pricing_context(
        db, "multi-one-stale-a", original_price="1000"
    )
    attrs_b = _cap_attrs(craft="批次变价工艺", length="28厘米")
    _seed_order_dicts(db, attrs_b)
    product_b = _persist_product(db, attrs_b)
    key_b = pricing_service.price_key_for_product(product_b)
    base_b = domestic_models.DomesticBasePrice(
        product_type=key_b[0],
        craft=key_b[1],
        length=key_b[2],
        original_price=D("1100.00"),
        version=1,
    )
    db.add(base_b)
    db.flush()
    discount_b = pricing_service.resolve_discount(
        product_type="cap",
        craft=attrs_b["craft"],
        length=attrs_b["length"],
        original_price=base_b.original_price,
        membership_level="black",
    )
    expected_b = _expected_quote_payload(
        original_price="1100.00",
        discount_price=discount_b.final_price,
        membership_level="black",
        pricing_rule="member_reduction",
    )
    db.commit()
    base_b.version = 2
    db.commit()

    payload = _priced_order_payload(
        customer,
        attrs_a,
        expected_a,
        request_id="multi-one-stale-order",
        items=[
            {
                "client_key": "unchanged",
                "attrs": attrs_a,
                "order_qty": 1,
                "expected_quote": expected_a,
            },
            {
                "client_key": "changed",
                "attrs": attrs_b,
                "order_qty": 1,
                "expected_quote": expected_b,
            },
        ],
    )
    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(db, payload, user.id)

    assert [row["client_key"] for row in caught.value.detail["changes"]] == ["changed"]
    assert [
        row["client_key"] for row in caught.value.detail["current_expected_quotes"]
    ] == ["unchanged", "changed"]
    assert db.query(domestic_models.DomesticOrder).count() == 0
    db.refresh(product_a)
    db.refresh(product_b)
    assert (product_a.use_count, product_b.use_count) == (0, 0)


def test_successful_create_replay_skips_repricing_after_price_change(db):
    user, customer, product, base, expected, attrs = _order_pricing_context(
        db, "create-replay", original_price="1000"
    )
    payload = _priced_order_payload(
        customer, attrs, expected, request_id="priced-create-replay"
    )
    first = order_service.create_order(db, payload, user.id)
    base.original_price = D("1500")
    base.version += 1
    customer.membership_level = "supreme"
    db.commit()

    replay = order_service.create_order(db, payload, user.id)
    db.refresh(product)
    assert replay["id"] == first["id"]
    assert replay["replayed"] is True
    assert product.use_count == 1
    assert db.query(domestic_models.DomesticOrderItem).one().unit_price == D("880")


def test_append_quotes_server_side_replays_and_quantity_uses_frozen_price(db):
    user, customer, product, base, expected, attrs = _order_pricing_context(
        db, "append", original_price="1000", balance="5000"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="append-base-order", qty=1
        ),
        user.id,
    )
    append = OrderItemAppend.model_validate(
        {
            **_order_item_payload(
                client_key="append-line",
                attrs=attrs,
                order_qty=2,
                expected_quote=expected,
            ),
            "request_id": "priced-append-request",
        }
    )
    first = order_service.add_item(db, created["id"], append, user.id)
    base.original_price = D("1500")
    base.version += 1
    db.commit()
    replay = order_service.add_item(db, created["id"], append, user.id)
    assert replay["id"] == first["id"]
    assert replay["replayed"] is True
    db.refresh(product)
    assert product.use_count == 2

    appended = db.get(domestic_models.DomesticOrderItem, first["id"])
    before = customer.balance
    order_service.update_item(
        db, appended.id, OrderItemUpdate(order_qty=3), user.id
    )
    db.refresh(customer)
    assert before - customer.balance == D("880.00")
    assert appended.unit_price == D("880.00")

    order_service.terminate_order(db, created["id"], "客户取消", user.id)
    db.refresh(customer)
    assert customer.balance == D("5000.00")


def test_append_quote_change_is_409_and_leaves_no_side_effects(db):
    user, customer, product, base, expected, attrs = _order_pricing_context(
        db, "append-change", original_price="1000", balance="5000"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="append-change-order"
        ),
        user.id,
    )
    base.version += 1
    db.commit()
    append = OrderItemAppend.model_validate(
        {
            **_order_item_payload(
                client_key="stale-append", attrs=attrs, expected_quote=expected
            ),
            "request_id": "stale-append-request",
        }
    )
    before_balance = customer.balance
    with pytest.raises(pricing_service.DomesticQuoteChangedError):
        order_service.add_item(db, created["id"], append, user.id)
    assert db.query(domestic_models.DomesticOrderItem).count() == 1
    assert db.query(domestic_models.DomesticItemAppendRequest).count() == 0
    db.refresh(customer)
    db.refresh(product)
    assert customer.balance == before_balance
    assert product.use_count == 1


def test_order_router_returns_typed_quote_change_as_409(db):
    user, customer, _product, base, expected, attrs = _order_pricing_context(
        db, "router-409", original_price="1000"
    )
    base.original_price = D("1500.00")
    base.version += 1
    db.commit()
    client = _pricing_api_client(db, user.id, "domestic:write")
    payload = _priced_order_payload(
        customer, attrs, expected, request_id="router-stale-quote"
    )
    response = client.post(
        "/api/domestic/orders", json=payload.model_dump(mode="json")
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "DOMESTIC_QUOTE_CHANGED"
    assert detail["message"] == "价格已更新，请确认后重新提交"
    assert set(detail["changes"][0]) == {
        "client_key", "item_id", "reasons", "previous_quote", "current_quote"
    }
    assert detail["changes"][0]["reasons"] == ["base_price_changed"]
    assert detail["current_expected_quotes"] == [{
        "client_key": "line-1",
        "item_id": None,
        "original_price": 1500.0,
        "base_price_version": 2,
        "discount_price": 1380.0,
        "membership_level": "black",
        "pricing_rule": "member_reduction",
        "pricing_version": "domestic-member-v1",
    }]
    assert db.query(domestic_models.DomesticOrder).count() == 0


def test_order_detects_server_pricing_version_change_as_rule_change(
    db, monkeypatch
):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "pricing-version-change", original_price="1000"
    )
    payload = _priced_order_payload(
        customer, attrs, expected, request_id="pricing-version-change-order"
    )
    monkeypatch.setattr(pricing_service, "PRICING_VERSION", "domestic-member-v2")

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(db, payload, user.id)

    change = caught.value.detail["changes"][0]
    assert change["reasons"] == ["rule_changed"]
    assert change["current_quote"]["pricing_version"] == "domestic-member-v2"
    assert db.query(domestic_models.DomesticOrder).count() == 0


def test_inline_customer_draft_is_quoted_as_nonmember_in_same_transaction(db):
    attrs = _cap_attrs(craft="就地客户工艺", length="23厘米")
    user = _operator(db, "inline-customer-pricing")
    _seed_order_dicts(db, attrs)
    db.add(domestic_models.DomesticBasePrice(
        product_type="cap",
        craft=attrs["craft"],
        length=attrs["length"],
        original_price=D("500.00"),
        version=4,
    ))
    db.commit()
    payload = OrderCreate.model_validate({
        "request_id": "inline-customer-priced-order",
        "order_no": "INLINE-PRICE-001",
        "order_date": "2026-09-02",
        "customer_shop_name": "就地新建非会员客户",
        "order_category": "normal",
        "order_type": "first_order",
        "order_channel": "wechat",
        "is_draft": True,
        "items": [{
            "client_key": "inline-line",
            "attrs": attrs,
            "order_qty": 1,
            "expected_quote": _expected_quote_payload(
                original_price="500.00",
                base_price_version=4,
                discount_price="500.00",
            ),
        }],
    })

    result = order_service.create_order(db, payload, user.id)
    customer = db.query(domestic_models.DomesticCustomer).filter_by(
        shop_name="就地新建非会员客户"
    ).one()
    item = db.query(domestic_models.DomesticOrderItem).one()
    assert customer.membership_level is None
    assert customer.balance == D("0.00")
    assert item.membership_level_snapshot is None
    assert item.unit_price == D("500.00")
    assert result["is_draft"] is True


def test_inline_customer_special_order_quote_409_rolls_back_entire_graph(db):
    attrs = _cap_attrs(craft="回滚特单工艺", length="47厘米")
    user = _operator(db, "inline-special-409-rollback")
    process = Process(name="回滚测试工序", status=1)
    route = ProcessRoute(
        name=domestic_constants.DEFAULT_ROUTE_NAMES["cap"], status=1
    )
    db.add_all([process, route])
    db.flush()
    db.add(
        ProcessRouteStep(
            route_id=route.id,
            process_id=process.id,
            step_order=1,
        )
    )
    seeded_values = {
        domestic_constants.ORDER_TYPE_DICT: "first_order",
        domestic_constants.ORDER_CHANNEL_DICT: "wechat",
        domestic_constants.DICT_CAP_NET_COLOR: attrs["net_color"],
        domestic_constants.DICT_CAP_SIZE: attrs["size"],
        domestic_constants.DICT_CAP_LENGTH: attrs["length"],
        domestic_constants.DICT_CAP_HAIR_STYLE_SERIES: attrs["hair_style_series"],
    }
    db.add_all([
        SysDict(
            type=dict_type,
            code=code,
            label=code,
            sort=1,
            is_active=True,
        )
        for dict_type, code in seeded_values.items()
    ])
    db.add(
        domestic_models.DomesticBasePrice(
            product_type="cap",
            craft=attrs["craft"],
            length=attrs["length"],
            original_price=D("500.00"),
            version=1,
            updated_by=user.id,
        )
    )
    db.commit()
    request_id = "inline-special-stale-quote-request"
    shop_name = "就地特单回滚客户"
    payload = OrderCreate.model_validate({
        "request_id": request_id,
        "order_no": "INLINE-SPECIAL-409",
        "order_date": "2026-09-02",
        "customer_shop_name": shop_name,
        "order_category": "special",
        "order_type": "first_order",
        "order_channel": "wechat",
        "items": [{
            "client_key": "inline-special-line",
            "attrs": attrs,
            "order_qty": 1,
            "expected_quote": _expected_quote_payload(
                original_price="500.00",
                base_price_version=1,
                discount_price="500.00",
                pricing_version="domestic-member-v0",
            ),
        }],
    })

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(db, payload, user.id)

    assert caught.value.detail["changes"][0]["reasons"] == ["rule_changed"]
    assert db.query(domestic_models.DomesticCustomer).filter_by(
        shop_name=shop_name
    ).count() == 0
    assert db.query(domestic_models.DomesticProduct).count() == 0
    assert db.query(SysDict).filter_by(
        type=f"{domestic_constants.DICT_CAP_CRAFT}_special",
        code=attrs["craft"],
    ).count() == 0
    assert db.query(domestic_models.DomesticCraftRoute).filter_by(
        product_type="cap", craft=attrs["craft"]
    ).count() == 0
    assert db.query(domestic_models.DomesticOrder).filter_by(
        request_id=request_id
    ).count() == 0
    assert db.query(domestic_models.DomesticOrderItem).count() == 0
    assert db.query(domestic_models.DomesticCustomerLedger).count() == 0
    assert db.query(domestic_models.DomesticOrderPricingRequest).count() == 0
    assert db.query(domestic_models.DomesticItemAppendRequest).count() == 0


def test_order_pricing_configuration_error_rolls_back_new_product_and_order(db):
    attrs = _cap_attrs(craft="异常低价工艺", length="27厘米")
    user = _operator(db, "order-config-rollback")
    customer = domestic_models.DomesticCustomer(
        shop_name="异常低价客户",
        membership_level="black",
        balance=D("1000.00"),
        created_by=user.id,
    )
    db.add(customer)
    _seed_order_dicts(db, attrs)
    db.add(domestic_models.DomesticBasePrice(
        product_type="cap",
        craft=attrs["craft"],
        length=attrs["length"],
        original_price=D("50.00"),
        version=1,
    ))
    db.commit()
    payload = _priced_order_payload(
        customer,
        attrs,
        _expected_quote_payload(
            original_price="50.00",
            discount_price="0.00",
            membership_level="black",
            pricing_rule="member_reduction",
        ),
        request_id="order-config-error-rollback",
    )

    with pytest.raises(pricing_service.PricingConfigurationError, match="价格"):
        order_service.create_order(db, payload, user.id)

    assert db.query(domestic_models.DomesticOrder).count() == 0
    assert db.query(domestic_models.DomesticProduct).count() == 0


def test_order_price_locks_customer_before_sorted_unique_base_rows(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "lock-order-a", original_price="1000"
    )
    attrs_b = _cap_attrs(craft="锁价工艺B", length="21厘米")
    _seed_order_dicts(db, attrs_b)
    product_b = _persist_product(db, attrs_b)
    key_b = pricing_service.price_key_for_product(product_b)
    db.add(
        domestic_models.DomesticBasePrice(
            product_type=key_b[0],
            craft=key_b[1],
            length=key_b[2],
            original_price=D("1100"),
            version=3,
        )
    )
    db.flush()
    discount_b = pricing_service.resolve_discount(
        product_type=product_b.product_type,
        craft=product_b.craft,
        length=product_b.length,
        size=None,
        original_price=D("1100"),
        membership_level="black",
    )
    expected_b = {
        "original_price": D("1100"),
        "base_price_version": 3,
        "discount_price": discount_b.final_price,
        "membership_level": "black",
        "pricing_rule": discount_b.pricing_rule,
        "pricing_version": "domestic-member-v1",
    }
    db.commit()
    payload = _priced_order_payload(
        customer,
        attrs,
        expected,
        request_id="sorted-price-lock-order",
        items=[
            {
                "client_key": "b",
                "attrs": attrs_b,
                "order_qty": 1,
                "expected_quote": expected_b,
            },
            {
                "client_key": "a1",
                "attrs": attrs,
                "order_qty": 1,
                "expected_quote": expected,
            },
            {
                "client_key": "a2",
                "attrs": attrs,
                "order_qty": 1,
                "expected_quote": expected,
            },
        ],
    )
    statements = []
    orm_statements = []
    customer_orm_statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        lowered = statement.lower()
        if any(table in lowered for table in (
            "ark_domestic_customers",
            "ark_domestic_products",
            "ark_domestic_base_prices",
        )):
            statements.append(lowered)

    def capture_orm(execute_state):
        compiled = str(
            execute_state.statement.compile(dialect=mysql.dialect())
        ).lower()
        if "ark_domestic_base_prices" in compiled:
            orm_statements.append(compiled)
        if "ark_domestic_customers" in compiled:
            customer_orm_statements.append(compiled)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    event.listen(db, "do_orm_execute", capture_orm)
    try:
        order_service.create_order(
            db,
            payload,
            user.id,
        )
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
        event.remove(db, "do_orm_execute", capture_orm)

    customer_select = next(i for i, sql in enumerate(statements) if "select" in sql and "ark_domestic_customers" in sql)
    product_select = next(i for i, sql in enumerate(statements) if "select" in sql and "ark_domestic_products" in sql)
    base_selects = [
        (i, sql)
        for i, sql in enumerate(statements)
        if "select" in sql and "ark_domestic_base_prices" in sql
    ]
    assert len(base_selects) == 2
    assert "for update" in customer_orm_statements[0]
    assert customer_select < product_select
    assert customer_select < base_selects[0][0]
    lookup, locked = orm_statements
    assert "for update" not in lookup
    assert "order by ark_domestic_base_prices.id asc" not in lookup
    assert "where ark_domestic_base_prices.id in" in locked
    assert "order by ark_domestic_base_prices.id asc" in locked
    assert "for update" in locked


def test_missing_order_price_does_not_issue_a_key_range_for_update(db):
    user, customer, _product, base, expected, attrs = _order_pricing_context(
        db, "missing-price-no-gap-lock", original_price="1000"
    )
    db.delete(base)
    db.commit()
    orm_statements = []

    def capture_orm(execute_state):
        compiled = str(
            execute_state.statement.compile(dialect=mysql.dialect())
        ).lower()
        if "ark_domestic_base_prices" in compiled:
            orm_statements.append(compiled)

    event.listen(db, "do_orm_execute", capture_orm)
    try:
        with pytest.raises(pricing_service.DomesticQuoteChangedError):
            order_service.create_order(
                db,
                _priced_order_payload(
                    customer,
                    attrs,
                    expected,
                    request_id="missing-price-no-gap-lock-order",
                ),
                user.id,
            )
    finally:
        event.remove(db, "do_orm_execute", capture_orm)

    assert len(orm_statements) == 1
    assert "for update" not in orm_statements[0]


@pytest.mark.skipif(
    not os.getenv("DOMESTIC_TEST_MYSQL_URL"),
    reason=(
        "set DOMESTIC_TEST_MYSQL_URL only for an explicitly disposable "
        "MySQL schema"
    ),
)
def test_real_mysql_order_quote_locks_avoid_reverse_order_deadlock_and_gap_lock():
    """Optional destructive two-session proof for the production lock contract."""

    engine = create_engine(
        os.environ["DOMESTIC_TEST_MYSQL_URL"], pool_pre_ping=True
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    suffix = str(datetime.now().timestamp()).replace(".", "")
    crafts = [f"mysql-lock-a-{suffix}", f"mysql-lock-b-{suffix}"]
    missing_craft = f"mysql-missing-{suffix}"
    length = "20厘米"

    try:
        with factory() as session:
            user = ArkUser(
                username=f"mysql-order-lock-{suffix}",
                password_hash="x",
                real_name="MySQL订单锁测试",
            )
            session.add(user)
            session.flush()
            customers = [
                domestic_models.DomesticCustomer(
                    shop_name=f"MySQL锁价客户-{index}-{suffix}",
                    membership_level="black",
                    balance=D("10000.00"),
                    created_by=user.id,
                )
                for index in range(3)
            ]
            products = [
                domestic_models.DomesticProduct(
                    attrs_key=f"mysql-lock-product-{index}-{suffix}",
                    name=craft,
                    product_type="cap",
                    craft=craft,
                    length=length,
                    status=1,
                    use_count=0,
                )
                for index, craft in enumerate([*crafts, missing_craft])
            ]
            prices = [
                domestic_models.DomesticBasePrice(
                    product_type="cap",
                    craft=craft,
                    length=length,
                    original_price=D(original),
                    version=1,
                    updated_by=user.id,
                )
                for craft, original in zip(crafts, ("1000.00", "1100.00"))
            ]
            session.add_all([*customers, *products, *prices])
            session.commit()
            customer_ids = [customer.id for customer in customers]
            product_ids = [product.id for product in products]

        expected_quotes = [
            ExpectedQuote.model_validate(_expected_quote_payload(
                original_price=original,
                discount_price=discount,
                membership_level="black",
                pricing_rule="member_reduction",
            ))
            for original, discount in (
                ("1000.00", "880.00"),
                ("1100.00", "980.00"),
            )
        ]
        start = threading.Barrier(2)

        def lock_in_order(customer_id, indexes):
            with factory() as session:
                item_products = [
                    (
                        SimpleNamespace(
                            client_key=f"mysql-line-{index}",
                            expected_quote=expected_quotes[index],
                        ),
                        session.get(
                            domestic_models.DomesticProduct,
                            product_ids[index],
                        ),
                    )
                    for index in indexes
                ]
                start.wait(timeout=10)
                pricing_service.lock_and_validate_order_quotes(
                    session,
                    customer_id=customer_id,
                    item_products=item_products,
                )
                session.commit()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(lock_in_order, customer_ids[0], (0, 1)),
                executor.submit(lock_in_order, customer_ids[1], (1, 0)),
            ]
            for future in futures:
                future.result(timeout=20)

        missing_checked = threading.Event()
        missing_inserted = threading.Event()

        def hold_missing_quote_transaction():
            with factory() as session:
                product = session.get(
                    domestic_models.DomesticProduct, product_ids[2]
                )
                item = SimpleNamespace(
                    client_key="mysql-missing-line",
                    expected_quote=ExpectedQuote.model_validate(
                        _expected_quote_payload(
                            original_price="500.00",
                            discount_price="500.00",
                            membership_level="black",
                        )
                    ),
                )
                with pytest.raises(pricing_service.DomesticQuoteChangedError):
                    pricing_service.lock_and_validate_order_quotes(
                        session,
                        customer_id=customer_ids[2],
                        item_products=[(item, product)],
                    )
                missing_checked.set()
                assert missing_inserted.wait(timeout=10), (
                    "missing price lookup held a MySQL gap lock"
                )
                session.rollback()

        def insert_missing_price_while_reader_is_open():
            assert missing_checked.wait(timeout=10)
            with factory() as session:
                session.add(domestic_models.DomesticBasePrice(
                    product_type="cap",
                    craft=missing_craft,
                    length=length,
                    original_price=D("500.00"),
                    version=1,
                ))
                session.commit()
            missing_inserted.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            holder = executor.submit(hold_missing_quote_transaction)
            inserter = executor.submit(insert_missing_price_while_reader_is_open)
            inserter.result(timeout=20)
            holder.result(timeout=20)
    finally:
        engine.dispose()


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


# ── 手工改价（manual_override）──────────────────────────

MANUAL_PRICE_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "132_domestic_manual_price.py"
)


def _manual_price_migration_module():
    spec = importlib.util.spec_from_file_location(
        "migration_132_domestic_manual_price", MANUAL_PRICE_MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manual_price_migration_revision_contract_and_mysql_offline_sql():
    migration = _manual_price_migration_module()
    assert migration.revision == "132_domestic_manual_price"
    assert migration.down_revision == "131_domestic_member_pricing_b"
    assert len(migration.revision) <= 32

    upgrade_output = StringIO()
    migration.op = Operations(
        MigrationContext.configure(
            dialect_name="mysql",
            opts={
                "as_sql": True,
                "literal_binds": True,
                "output_buffer": upgrade_output,
            },
        )
    )
    migration.upgrade()
    upgrade_sql = upgrade_output.getvalue()
    assert "DROP CHECK" in upgrade_sql.upper()
    assert "ck_dom_item_pricing_rule" in upgrade_sql
    assert "manual_override" in upgrade_sql

    downgrade_output = StringIO()
    migration.op = Operations(
        MigrationContext.configure(
            dialect_name="mysql",
            opts={
                "as_sql": True,
                "literal_binds": True,
                "output_buffer": downgrade_output,
            },
        )
    )
    migration.downgrade()
    downgrade_sql = downgrade_output.getvalue()
    assert "DROP CHECK" in downgrade_sql.upper()
    assert "manual_override" not in downgrade_sql


def test_manual_price_migration_downgrade_blocks_on_manual_rows(db):
    migration = _manual_price_migration_module()
    _, _, order = _customer_and_order(db, "manual-downgrade-guard")
    product = _constraint_product(db, "manual-downgrade-guard")
    db.add(domestic_models.DomesticOrderItem(
        order_id=order.id,
        line_no=1,
        product_id=product.id,
        product_name=product.name,
        order_qty=1,
        unit_price=D("950.00"),
        original_price=D("1000.00"),
        discount_amount=D("50.00"),
        membership_level_snapshot="black",
        pricing_rule="manual_override",
        pricing_version="domestic-member-v1",
        base_price_version_snapshot=1,
    ))
    db.flush()

    def _context():
        return MigrationContext.configure(
            db.get_bind().connect(),
            opts={"as_sql": False},
        )

    migration.op = Operations(_context())
    with pytest.raises(RuntimeError, match="手工改价"):
        migration.downgrade()
    db.rollback()


def test_manual_price_schema_contract():
    item = OrderItemInput.model_validate(_order_item_payload())
    assert item.manual_discount_price is None
    manual = OrderItemInput.model_validate(
        _order_item_payload(manual_discount_price="950.00")
    )
    assert manual.manual_discount_price == D("950.00")
    with pytest.raises(ValidationError):
        OrderItemInput.model_validate(_order_item_payload(manual_discount_price="0"))
    with pytest.raises(ValidationError):
        OrderItemInput.model_validate(_order_item_payload(manual_discount_price="-1"))

    assert OrderItemUpdate.model_validate({"unit_price": "950.00"}).unit_price == D("950.00")
    with pytest.raises(ValidationError):
        OrderItemUpdate.model_validate({"unit_price": "0"})
    with pytest.raises(ValidationError):
        OrderItemUpdate.model_validate({"discount_price": "1.00"})

    quote = {"client_key": None, "item_id": 7, **_expected_quote_payload(
        pricing_rule="manual_override", discount_price="950.00",
    )}
    assert ItemExpectedQuote.model_validate(quote).pricing_rule == "manual_override"


def test_manual_override_pricing_rule_label():
    result = pricing_service.DiscountResult(
        D("1000.00"), D("950.00"), D("50.00"), "manual_override"
    )
    assert pricing_service.pricing_rule_label(result, "black") == "手工改价"
    assert pricing_service.pricing_rule_label(result, None) == "手工改价"


def test_create_order_with_manual_discount_price_charges_manual_amount(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "manual-create", balance="10000.00"
    )
    server_price = expected["discount_price"]  # 黑卡 1000 - 120 = 880
    assert server_price == D("880.00")
    payload = _priced_order_payload(
        customer, attrs, expected, request_id="manual-create-1", qty=2,
        items=[{
            "client_key": "line-1",
            "attrs": attrs,
            "order_qty": 2,
            "expected_quote": expected,
            "manual_discount_price": "950.00",
        }],
    )
    created = order_service.create_order(db, payload, user.id)
    assert created["total_amount"] == 1900.00

    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=created["id"]
    ).one()
    assert item.unit_price == D("950.00")
    assert item.original_price == D("1000.00")
    assert item.discount_amount == D("50.00")
    assert item.pricing_rule == "manual_override"
    assert item.membership_level_snapshot == "black"
    assert item.base_price_version_snapshot == 1

    db.refresh(customer)
    assert customer.balance == D("8100.00")
    order = db.get(domestic_models.DomesticOrder, created["id"])
    assert order.charged_amount == D("1900.00")

    detail = order_service.get_order_detail(db, order.id, include_finance=True)
    view = detail["items"][0]
    assert view["pricing_rule"] == "manual_override"
    assert view["pricing_rule_label"] == "手工改价"
    assert detail["current_expected_quotes"][0]["pricing_rule"] == "manual_override"
    assert detail["current_expected_quotes"][0]["discount_price"] == 950.00


def test_create_order_manual_price_above_original_rejected(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "manual-above", balance="10000.00"
    )
    payload = _priced_order_payload(
        customer, attrs, expected, request_id="manual-above-1",
        items=[{
            "client_key": "line-1",
            "attrs": attrs,
            "order_qty": 1,
            "expected_quote": expected,
            "manual_discount_price": "1000.01",
        }],
    )
    with pytest.raises(ValueError, match="手工优惠价"):
        order_service.create_order(db, payload, user.id)
    assert db.query(domestic_models.DomesticOrder).filter_by(
        request_id="manual-above-1"
    ).first() is None


def test_create_order_manual_price_still_409_on_stale_quote(db):
    user, customer, _product, base, expected, attrs = _order_pricing_context(
        db, "manual-stale", balance="10000.00"
    )

    def _payload(request_id):
        return _priced_order_payload(
            customer, attrs, expected, request_id=request_id,
            items=[{
                "client_key": "line-1",
                "attrs": attrs,
                "order_qty": 1,
                "expected_quote": expected,
                "manual_discount_price": "950.00",
            }],
        )

    base.original_price = D("1100.00")
    base.version += 1
    db.commit()

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.create_order(db, _payload("manual-stale-1"), user.id)
    assert caught.value.detail["changes"][0]["reasons"] == ["base_price_changed"]

    fresh = {
        key: caught.value.detail["current_expected_quotes"][0][key]
        for key in (
            "original_price", "base_price_version", "discount_price",
            "membership_level", "pricing_rule", "pricing_version",
        )
    }
    retry = _priced_order_payload(
        customer, attrs, fresh, request_id="manual-stale-2",
        items=[{
            "client_key": "line-1",
            "attrs": attrs,
            "order_qty": 1,
            "expected_quote": fresh,
            "manual_discount_price": "950.00",
        }],
    )
    created = order_service.create_order(db, retry, user.id)
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=created["id"]
    ).one()
    assert item.unit_price == D("950.00")
    assert item.original_price == D("1100.00")
    assert item.pricing_rule == "manual_override"


def test_manual_price_is_part_of_create_replay_hash(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "manual-replay", balance="10000.00"
    )

    def _payload(manual):
        return _priced_order_payload(
            customer, attrs, expected, request_id="manual-replay-1",
            items=[{
                "client_key": "line-1",
                "attrs": attrs,
                "order_qty": 1,
                "expected_quote": expected,
                "manual_discount_price": manual,
            }],
        )

    created = order_service.create_order(db, _payload("950.00"), user.id)
    replayed = order_service.create_order(db, _payload("950.00"), user.id)
    assert replayed["replayed"] is True
    assert replayed["id"] == created["id"]
    with pytest.raises(ValueError, match="已用于不同订单内容"):
        order_service.create_order(db, _payload("900.00"), user.id)
    db.refresh(customer)
    assert customer.balance == D("9050.00")


def test_draft_with_manual_price_submits_without_409_and_charges_manual(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "manual-draft", balance="10000.00"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="manual-draft-create",
            is_draft=True, qty=2,
            items=[{
                "client_key": "line-1",
                "attrs": attrs,
                "order_qty": 2,
                "expected_quote": expected,
                "manual_discount_price": "950.00",
            }],
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).one()
    assert item.pricing_rule == "manual_override"
    assert order.charged_amount == D("0.00")

    result = order_service.submit_draft(
        db, order.id, _draft_submit_payload("manual-draft-submit", item), user.id
    )
    assert result["charged_amount"] == 1900.00
    db.refresh(order)
    db.refresh(item)
    db.refresh(customer)
    assert order.status == domestic_constants.ORDER_PRODUCING
    assert item.unit_price == D("950.00")
    assert item.pricing_rule == "manual_override"
    assert customer.balance == D("8100.00")

    replayed = order_service.submit_draft(
        db, order.id, _draft_submit_payload("manual-draft-submit", item), user.id
    )
    assert replayed["replayed"] is True
    db.refresh(customer)
    assert customer.balance == D("8100.00")


def test_manual_draft_survives_base_price_and_membership_drift(db):
    user, customer, _product, base, expected, attrs = _order_pricing_context(
        db, "manual-drift", membership_level="black", balance="10000.00"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="manual-drift-create",
            is_draft=True,
            items=[{
                "client_key": "line-1",
                "attrs": attrs,
                "order_qty": 1,
                "expected_quote": expected,
                "manual_discount_price": "950.00",
            }],
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).one()

    # 原价上调、会员降级：手工价是用户确认过的绝对金额，不漂移也不 409
    base.original_price = D("1200.00")
    base.version += 1
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=D("100.00"),
        user_id=user.id, request_id="manual-drift-recharge",
    )
    db.refresh(customer)
    assert customer.membership_level is None

    result = order_service.submit_draft(
        db, order.id, _draft_submit_payload("manual-drift-submit", item), user.id
    )
    assert result["charged_amount"] == 950.00
    db.refresh(item)
    assert item.unit_price == D("950.00")
    assert item.pricing_rule == "manual_override"
    assert item.original_price == D("1200.00")
    assert item.discount_amount == D("250.00")


def test_manual_echo_above_current_original_is_rejected(db):
    user, customer, _product, base, expected, attrs = _order_pricing_context(
        db, "manual-over-Original", balance="10000.00"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="manual-over-create",
            is_draft=True,
            items=[{
                "client_key": "line-1",
                "attrs": attrs,
                "order_qty": 1,
                "expected_quote": expected,
                "manual_discount_price": "950.00",
            }],
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).one()

    # 管理员把原价调到手工价之下：绝不许成交价高于原价，提交被拦下
    base.original_price = D("900.00")
    base.version += 1
    db.commit()

    with pytest.raises(ValueError, match="手工优惠价"):
        order_service.submit_draft(
            db, order.id, _draft_submit_payload("manual-over-submit", item), user.id
        )
    db.refresh(order)
    db.refresh(customer)
    assert order.status == domestic_constants.ORDER_DRAFT
    assert order.charged_amount == D("0.00")
    assert customer.balance == D("10000.00")


def test_mixed_draft_quote_change_retry_preserves_manual_line(db):
    user, customer, product_a, base_a, expected_a, attrs_a = _order_pricing_context(
        db, "manual-mixed", balance="10000.00"
    )
    attrs_b = _cap_attrs(length="25厘米")
    _seed_order_dicts(db, attrs_b)
    product_b = _persist_product(db, attrs_b)
    key_b = pricing_service.price_key_for_product(product_b)
    base_b = domestic_models.DomesticBasePrice(
        product_type=key_b[0], craft=key_b[1], length=key_b[2],
        original_price=D("2000.00"), version=1, updated_by=user.id,
    )
    db.add(base_b)
    db.flush()
    discount_b = pricing_service.resolve_discount(
        product_type="piece" if product_b.product_type == "piece" else "cap",
        craft=product_b.craft,
        length=product_b.length,
        size=product_b.size if product_b.product_type == "piece" else None,
        original_price=base_b.original_price,
        membership_level="black",
    )
    expected_b = {
        "original_price": discount_b.original_price,
        "base_price_version": base_b.version,
        "discount_price": discount_b.final_price,
        "membership_level": "black",
        "pricing_rule": discount_b.pricing_rule,
        "pricing_version": pricing_service.PRICING_VERSION,
    }
    db.commit()

    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs_a, expected_a, request_id="manual-mixed-create",
            is_draft=True,
            items=[
                {
                    "client_key": "line-a",
                    "attrs": attrs_a,
                    "order_qty": 1,
                    "expected_quote": expected_a,
                    "manual_discount_price": "950.00",
                },
                {
                    "client_key": "line-b",
                    "attrs": attrs_b,
                    "order_qty": 1,
                    "expected_quote": expected_b,
                },
            ],
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    items = {
        item.product_id: item
        for item in db.query(domestic_models.DomesticOrderItem).filter_by(
            order_id=order.id
        ).all()
    }
    item_a = items[product_a.id]
    item_b = items[product_b.id]

    base_b.original_price = D("2100.00")
    base_b.version += 1
    db.commit()

    with pytest.raises(pricing_service.DomesticQuoteChangedError) as caught:
        order_service.submit_draft(
            db, order.id,
            _draft_submit_payload("manual-mixed-submit", item_a, item_b),
            user.id,
        )
    detail = caught.value.detail
    assert [change["item_id"] for change in detail["changes"]] == [item_b.id]
    # 手工行在重试快照里保持手工价，不被系统报价覆盖
    quotes_by_item = {
        quote["item_id"]: quote for quote in detail["current_expected_quotes"]
    }
    assert quotes_by_item[item_a.id]["pricing_rule"] == "manual_override"
    assert quotes_by_item[item_a.id]["discount_price"] == 950.00
    assert quotes_by_item[item_b.id]["original_price"] == 2100.00

    retry = DraftSubmitRequest.model_validate({
        "request_id": "manual-mixed-retry",
        "expected_quotes": detail["current_expected_quotes"],
    })
    result = order_service.submit_draft(db, order.id, retry, user.id)
    assert result["total_amount"] == pytest.approx(950.00 + 1980.00)
    db.refresh(item_a)
    db.refresh(item_b)
    assert item_a.unit_price == D("950.00")
    assert item_a.pricing_rule == "manual_override"
    assert item_b.unit_price == D("1980.00")
    assert item_b.pricing_rule == "member_reduction"


def test_update_item_unit_price_settles_balance_delta(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "manual-edit", balance="10000.00"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="manual-edit-create", qty=2,
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).one()
    assert item.unit_price == D("880.00")
    db.refresh(customer)
    assert customer.balance == D("8240.00")

    # 往低改：差额退回客户余额
    order_service.update_item(
        db, item.id, OrderItemUpdate(unit_price=D("800.00")), user.id
    )
    db.refresh(item)
    db.refresh(order)
    db.refresh(customer)
    assert item.unit_price == D("800.00")
    assert item.pricing_rule == "manual_override"
    assert item.discount_amount == D("200.00")
    assert order.total_amount == D("1600.00")
    assert order.charged_amount == D("1600.00")
    assert customer.balance == D("8400.00")

    # 往高改（不超过原价）：从余额补扣差额
    order_service.update_item(
        db, item.id, OrderItemUpdate(unit_price=D("1000.00")), user.id
    )
    db.refresh(item)
    db.refresh(customer)
    assert item.unit_price == D("1000.00")
    assert customer.balance == D("8000.00")

    with pytest.raises(ValueError, match="不能高于原价"):
        order_service.update_item(
            db, item.id, OrderItemUpdate(unit_price=D("1000.01")), user.id
        )
    db.refresh(customer)
    assert customer.balance == D("8000.00")

    ledgers = balance_service.list_customer_ledger(
        db, customer_id=customer.id
    )[0]
    adjustments = [
        row for row in ledgers if row["transaction_type"] == "order_adjustment"
    ]
    assert [row["amount"] for row in adjustments] == [-400.00, 160.00]


def test_update_item_unit_price_on_draft_moves_no_money(db):
    user, customer, _product, _base, order, item = _created_priced_draft(
        db, "manual-edit-draft", membership_level="black", balance="5000.00"
    )
    order_service.update_item(
        db, item.id, OrderItemUpdate(unit_price=D("700.00")), user.id
    )
    db.refresh(item)
    db.refresh(order)
    db.refresh(customer)
    assert item.unit_price == D("700.00")
    assert item.pricing_rule == "manual_override"
    assert order.total_amount == D("700.00")
    assert order.charged_amount == D("0.00")
    assert customer.balance == D("5000.00")


def test_update_item_unit_price_rejects_shipped_and_terminated(db):
    user, customer, _product, _base, expected, attrs = _order_pricing_context(
        db, "manual-edit-closed", balance="10000.00"
    )
    created = order_service.create_order(
        db,
        _priced_order_payload(
            customer, attrs, expected, request_id="manual-edit-closed-1",
        ),
        user.id,
    )
    order = db.get(domestic_models.DomesticOrder, created["id"])
    item = db.query(domestic_models.DomesticOrderItem).filter_by(
        order_id=order.id
    ).one()

    order.status = domestic_constants.ORDER_TERMINATED
    db.commit()
    with pytest.raises(ValueError, match="不能修改明细"):
        order_service.update_item(
            db, item.id, OrderItemUpdate(unit_price=D("800.00")), user.id
        )
    db.refresh(item)
    assert item.unit_price == D("880.00")


# ── 客户余额/等级的初始化与临时调整 ──────────────────────


def test_initialize_customer_sets_opening_balance_and_level_once(db):
    user = _operator(db, "init-customer")
    customer = _membership_customer(db, user, "init")
    payload = CustomerInitialize(
        balance=D("5000.00"), membership_level="black", remark="老客户期初",
    )
    result = customer_service.initialize_customer(db, customer.id, payload, user.id)
    assert result["replayed"] is False
    assert result["current_balance"] == 5000.00
    assert result["membership_level"] == "black"
    assert result["membership_label"] == "黑卡会员"

    db.refresh(customer)
    assert customer.balance == D("5000.00")
    # 初始化不是充值：派生依据保持为空，等级是显式约定
    assert customer.last_recharge_amount is None
    rows = db.query(domestic_models.DomesticCustomerLedger).filter_by(
        customer_id=customer.id
    ).all()
    assert len(rows) == 1
    assert rows[0].transaction_type == "init"
    assert rows[0].business_key == f"init:{customer.id}"

    replayed = customer_service.initialize_customer(db, customer.id, payload, user.id)
    assert replayed["replayed"] is True
    db.refresh(customer)
    assert customer.balance == D("5000.00")

    with pytest.raises(ValueError, match="不能重复初始化"):
        customer_service.initialize_customer(
            db, customer.id,
            CustomerInitialize(balance=D("6000.00")), user.id,
        )
    db.rollback()


def test_initialize_rejected_once_customer_has_any_ledger(db):
    user = _operator(db, "init-late")
    customer = _membership_customer(db, user, "late")
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=D("10000.00"),
        user_id=user.id, request_id="init-late-recharge",
    )
    with pytest.raises(ValueError, match="临时调整"):
        customer_service.initialize_customer(
            db, customer.id, CustomerInitialize(balance=D("5000.00")), user.id,
        )
    db.refresh(customer)
    assert customer.balance == D("10000.00")


def test_adjust_customer_balance_signed_and_idempotent(db):
    user = _operator(db, "adjust-money")
    customer = _membership_customer(db, user, "money", balance=D("1000.00"))
    db.commit()

    payload = CustomerAdjust(
        amount=D("200.00"), remark="补录线下收款", request_id="adjust-money-1",
    )
    result = customer_service.adjust_customer(db, customer.id, payload, user.id)
    assert result["current_balance"] == 1200.00
    replayed = customer_service.adjust_customer(db, customer.id, payload, user.id)
    assert replayed["replayed"] is True
    assert replayed["current_balance"] == 1200.00

    down = CustomerAdjust(
        amount=D("-1200.00"), remark="多录退回", request_id="adjust-money-2",
    )
    result = customer_service.adjust_customer(db, customer.id, down, user.id)
    assert result["current_balance"] == 0.00

    with pytest.raises(ValueError, match="不同金额"):
        customer_service.adjust_customer(
            db, customer.id,
            CustomerAdjust(amount=D("5.00"), remark="改内容", request_id="adjust-money-2"),
            user.id,
        )
    db.rollback()
    with pytest.raises(ValueError, match="余额不足"):
        customer_service.adjust_customer(
            db, customer.id,
            CustomerAdjust(amount=D("-0.01"), remark="扣穿", request_id="adjust-money-3"),
            user.id,
        )
    db.rollback()


def test_adjust_customer_level_only_is_temporary_and_audited(db):
    user = _operator(db, "adjust-level")
    customer = _membership_customer(db, user, "level", balance=D("100.00"))
    db.commit()

    payload = CustomerAdjust(
        membership_level="supreme", remark="大客临时升舱", request_id="adjust-level-1",
    )
    result = customer_service.adjust_customer(db, customer.id, payload, user.id)
    assert result["membership_level"] == "supreme"
    db.refresh(customer)
    assert customer.balance == D("100.00")
    assert customer.last_recharge_amount is None

    rows = db.query(domestic_models.DomesticCustomerLedger).filter_by(
        customer_id=customer.id, transaction_type="level_adjust"
    ).all()
    assert len(rows) == 1
    assert rows[0].amount == D("0")
    assert "非会员 → 至尊会员" in rows[0].remark

    replayed = customer_service.adjust_customer(db, customer.id, payload, user.id)
    assert replayed["replayed"] is True
    assert db.query(domestic_models.DomesticCustomerLedger).filter_by(
        customer_id=customer.id, transaction_type="level_adjust"
    ).count() == 1

    # 临时等级不碰派生依据：下一次充值仍按当次金额重新核定
    balance_service.recharge_customer(
        db, customer_id=customer.id, amount=D("10000.00"),
        user_id=user.id, request_id="adjust-level-recharge",
    )
    db.refresh(customer)
    assert customer.membership_level == "silver"

    # 取消会员：显式传 null
    result = customer_service.adjust_customer(
        db, customer.id,
        CustomerAdjust(membership_level=None, remark="取消资格", request_id="adjust-level-2"),
        user.id,
    )
    assert result["membership_level"] is None
    assert result["membership_label"] == "非会员"


def test_adjust_customer_requires_content(db):
    user = _operator(db, "adjust-empty")
    customer = _membership_customer(db, user, "empty")
    with pytest.raises(ValueError, match="没有需要调整的内容"):
        customer_service.adjust_customer(
            db, customer.id,
            CustomerAdjust(amount=D("0"), remark="空调用", request_id="adjust-empty-1"),
            user.id,
        )
    with pytest.raises(ValidationError):
        CustomerAdjust(amount=D("1.00"), remark=" ", request_id="adjust-empty-2")
    with pytest.raises(ValidationError):
        CustomerAdjust(amount=D("1.00"), remark="x" * 2)


def test_initialize_and_adjust_api_require_admin(db):
    user = _operator(db, "init-adjust-api")
    customer = _membership_customer(db, user, "api")
    client = _customer_api_client(db, user.id)  # read/write/recharge，无 admin

    init_denied = client.post(
        f"/api/domestic/customers/{customer.id}/initialize",
        json={"balance": "100.00"},
    )
    adjust_denied = client.post(
        f"/api/domestic/customers/{customer.id}/adjust",
        json={"amount": "1.00", "remark": "越权", "request_id": "deny-adjust-1"},
    )
    assert init_denied.status_code == 403
    assert adjust_denied.status_code == 403

    from app.domestic.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user.id), "roles": [], "permissions": ["domestic:admin"],
    }
    admin_client = TestClient(app)

    created = admin_client.post(
        f"/api/domestic/customers/{customer.id}/initialize",
        json={"balance": "300.00", "membership_level": "silver"},
    )
    assert created.status_code == 200
    assert created.json()["data"]["current_balance"] == 300.00
    assert created.json()["data"]["membership_label"] == "银卡会员"

    adjusted = admin_client.post(
        f"/api/domestic/customers/{customer.id}/adjust",
        json={
            "amount": "-50.00", "membership_level": None,
            "remark": "扣错退回", "request_id": "api-adjust-1",
        },
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["data"]["current_balance"] == 250.00
    assert adjusted.json()["data"]["membership_level"] is None
