from datetime import date
from decimal import Decimal
import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.domestic import pricing_service
from app.domestic import models as domestic_models


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


def test_member_pricing_migration_is_self_contained_and_backfills_compatibly(
    monkeypatch,
):
    migration = _migration_module()
    module_source = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_source = inspect.getsource(migration.upgrade)
    downgrade_source = inspect.getsource(migration.downgrade)

    added_columns = []
    monkeypatch.setattr(migration.op, "create_table", lambda *_args, **_kwargs: None)
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

    assert "transaction_type = 'recharge'" in module_source
    assert "MAX(id)" in module_source
    assert "last_recharge_amount = latest.amount" in module_source
    assert "last_recharged_at = latest.created_at" in module_source
    assert "original_price = unit_price" in module_source
    assert "discount_amount = 0" in module_source
    assert "membership_level_snapshot = NULL" in module_source
    assert "pricing_rule = 'legacy_manual'" in module_source
    assert "pricing_version = 'legacy'" in module_source
    assert "base_price_version_snapshot = 0" in module_source
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
