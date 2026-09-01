from decimal import Decimal

import pytest

from app.domestic import pricing_service


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
    "递针旋全头套": (1198, 1498, 1798, 1998, 2050, 2700),
    "递针旋九分头": (1198, 1498, 1798, 1998, 2050, 2700),
    "递针顶": (None, 1798, 2198, 2498, 2650, 3300),
    "递针中分界": (None, 1598, 1898, 2198, 2298, 2900),
    "递针左分界": (None, 1598, 1898, 2198, 2298, 2900),
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
    assert dict(
        ((product_type, craft, size, length), price)
        for product_type, craft, size, length, price
        in pricing_service.iter_base_price_seeds()
    ) == expected


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
    "length", ("15厘米", "20厘米", "25厘米", "30厘米", "35厘米", "40厘米")
)
def test_cap_full_and_nine_part_have_identical_six_length_matrices(length):
    assert pricing_service.get_base_price(
        product_type="cap", craft="递针旋全头套", size="S", length=length
    ) == pricing_service.get_base_price(
        product_type="cap", craft="递针旋九分头", size="XL", length=length
    )


def test_confirmed_boundary_price_is_not_smoothed():
    assert pricing_service.get_base_price(
        product_type="piece", craft="递针中分界", size="13*15", length="35厘米"
    ) == D("1040.00")


@pytest.mark.parametrize(
    "attrs",
    [
        {"product_type": "piece", "craft": "全递针", "size": "18*20", "length": "40厘米"},
        {"product_type": "piece", "craft": "U型递针", "size": "9*14", "length": "25厘米"},
        {"product_type": "cap", "craft": "递针顶", "size": None, "length": "15厘米"},
    ],
)
def test_unconfirmed_combinations_remain_without_price(attrs):
    assert pricing_service.get_base_price(**attrs) is None


def test_current_combined_piece_craft_value_is_resolved_exactly():
    assert pricing_service.get_base_price(
        product_type="piece", craft="全递针9*14", size=None, length="25厘米"
    ) == D("840.00")
    assert pricing_service.get_base_price(
        product_type="piece", craft="U型13*15", size=None, length="35厘米"
    ) == D("1320.00")


@pytest.mark.parametrize("craft", ["全递针", "全递针未知尺寸", "U型", "特单发片"])
def test_unknown_or_incomplete_combined_piece_craft_has_no_price(craft):
    assert pricing_service.get_base_price(
        product_type="piece", craft=craft, size=None, length="25厘米"
    ) is None


def test_cap_price_ignores_size():
    assert pricing_service.get_base_price(
        product_type="cap", craft="递针顶", size=None, length="35厘米"
    ) == pricing_service.get_base_price(
        product_type="cap", craft="递针顶", size="59", length="35厘米"
    ) == D("2650.00")


@pytest.mark.parametrize(
    ("craft", "length", "level", "expected"),
    [
        (craft, "15厘米", level, expected)
        for craft in ("递针旋全头套", "递针旋九分头")
        for level, expected in (
            ("silver", "1048.00"),
            ("black", "998.00"),
            ("supreme", "960.00"),
        )
    ]
    + [
        ("递针顶", length, level, expected)
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
def test_nine_part_non_fixed_lengths_use_member_reductions(
    length, original, level, expected
):
    base_price = pricing_service.get_base_price(
        product_type="cap",
        craft="递针旋九分头",
        size=None,
        length=length,
    )
    result = pricing_service.resolve_discount(
        product_type="cap",
        craft="递针旋九分头",
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
        craft="递针顶",
        size=None,
        length="35厘米",
        original_price=D("2650.005"),
        membership_level=None,
    )
    assert result.final_price == D("2650.01")
    assert result.discount_amount == D("0.00")
    assert result.pricing_rule == "base_price"


def test_reduction_never_produces_a_negative_price():
    result = pricing_service.resolve_discount(
        product_type="piece",
        craft="全递针",
        size="9*14",
        length="25厘米",
        original_price=D("50"),
        membership_level="silver",
    )
    assert result.final_price == D("0.00")
    assert result.discount_amount == D("50.00")
    assert result.pricing_rule == "member_reduction"


def test_fixed_price_above_original_is_capped_and_marked():
    result = pricing_service.resolve_discount(
        product_type="cap",
        craft="递针旋全头套",
        size=None,
        length="15厘米",
        original_price=D("900"),
        membership_level="silver",
    )
    assert result.final_price == D("900.00")
    assert result.discount_amount == D("0.00")
    assert result.pricing_rule == "member_fixed_capped"
