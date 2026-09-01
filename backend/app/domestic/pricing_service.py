"""内贸会员等级、原始价格种子与优惠计算纯领域规则。"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterator


MONEY_QUANTUM = Decimal("0.01")

MEMBERSHIP_REDUCTIONS = {
    "silver": Decimal("70.00"),
    "black": Decimal("120.00"),
    "supreme": Decimal("130.00"),
}

MEMBERSHIP_LABELS = {
    None: "非会员",
    "silver": "银卡会员",
    "black": "黑卡会员",
    "supreme": "至尊会员",
}

MEMBER_FIXED_PRICES = {
    ("递旋", "15厘米", "silver"): Decimal("1048.00"),
    ("递旋", "15厘米", "black"): Decimal("998.00"),
    ("递旋", "15厘米", "supreme"): Decimal("960.00"),
    ("递顶", "20厘米", "silver"): Decimal("1698.00"),
    ("递顶", "20厘米", "black"): Decimal("1598.00"),
    ("递顶", "20厘米", "supreme"): Decimal("1548.00"),
    ("递顶", "25厘米", "silver"): Decimal("2098.00"),
    ("递顶", "25厘米", "black"): Decimal("1998.00"),
    ("递顶", "25厘米", "supreme"): Decimal("1948.00"),
}


_FULL_NEEDLE_ROWS = {
    "9*14": (840, 960, 1040, 1290),
    "12*14": (1040, 1140, 1200, 1420),
    "13*15": (1090, 1180, 1350, 1500),
    "14*16": (1160, 1260, 1380, 1630),
    "15*17": (1490, 1580, 1710, 1900),
    "16*18": (1510, 1610, 1760, 1950),
    "18*20": (1760, 1910, 2000, None),
}

_PART_ROWS = {
    "12*14": (980, 1080, 1140, 1360),
    "13*15": (1030, 1120, 1040, 1440),
    "14*16": (1100, 1200, 1320, 1570),
    "15*17": (1430, 1520, 1650, 1840),
    "16*18": (1450, 1550, 1700, 1890),
}

_PIECE_PRICE_ROWS = {
    "全递针": _FULL_NEEDLE_ROWS,
    "递针旋": _FULL_NEEDLE_ROWS,
    "U型递针": {
        "13*15": (1060, 1150, 1320, 1470),
        "14*16": (1130, 1230, 1350, 1600),
        "15*17": (1460, 1550, 1680, 1870),
        "16*18": (1480, 1580, 1730, 1920),
    },
    "递针中分界": _PART_ROWS,
    "递针左分界": _PART_ROWS,
}

_CAP_SPIN_PRICES = (1198, 1498, 1798, 1998, 2050, 2700)
_CAP_PART_PRICES = (None, 1598, 1898, 2198, 2298, 2900)
_CAP_PRICE_ROWS = {
    "递旋": _CAP_SPIN_PRICES,
    "递顶": (None, 1798, 2198, 2498, 2650, 3300),
    "中分界": _CAP_PART_PRICES,
    "左分界": _CAP_PART_PRICES,
}
_CAP_CRAFT_CODES = frozenset({"递旋", "中分界", "左分界", "大U型", "递顶"})


def _build_base_price_seed_matrix():
    matrix = {}
    piece_lengths = ("25厘米", "30厘米", "35厘米", "40厘米")
    for craft, size_rows in _PIECE_PRICE_ROWS.items():
        for size, prices in size_rows.items():
            for length, price in zip(piece_lengths, prices):
                if price is not None:
                    matrix[("piece", craft, size, length)] = Decimal(f"{price}.00")

    cap_lengths = (
        "15厘米", "20厘米", "25厘米", "30厘米", "35厘米", "40厘米"
    )
    for craft, prices in _CAP_PRICE_ROWS.items():
        for length, price in zip(cap_lengths, prices):
            if price is not None:
                matrix[("cap", craft, None, length)] = Decimal(f"{price}.00")
    return matrix


BASE_PRICE_SEED_MATRIX = _build_base_price_seed_matrix()


# 发片产品把工艺和尺寸存成一个 code。只从已确认原价矩阵生成精确 code，
# 查询仍是字典精确匹配，不做前缀、后缀或正则解析。
_PIECE_COMBINED_PREFIXES = {
    "全递针": "全递针",
    "递针旋": "递针旋",
    "U型递针": "U型",
    "递针中分界": "递针中分界",
    "递针左分界": "递针左分界",
}
COMBINED_PIECE_CRAFT_SIZE = {
    f"{_PIECE_COMBINED_PREFIXES[craft]}{size}": (craft, size)
    for craft, size_rows in _PIECE_PRICE_ROWS.items()
    for size in size_rows
}
_COMBINED_PIECE_BY_DIMENSIONS = {
    dimensions: combined
    for combined, dimensions in COMBINED_PIECE_CRAFT_SIZE.items()
}


class PricingConfigurationError(ValueError):
    """定价配置无法生成合法成交价。"""


def membership_label(membership_level: str | None) -> str:
    """返回会员展示文案；未知等级视为配置错误。"""

    try:
        return MEMBERSHIP_LABELS[membership_level]
    except KeyError as exc:
        raise PricingConfigurationError(
            f"未知会员等级：{membership_level!r}"
        ) from exc


@dataclass(frozen=True)
class DiscountResult:
    original_price: Decimal
    final_price: Decimal
    discount_amount: Decimal
    pricing_rule: str


def _money(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _validated_original_price(value: Decimal | int) -> Decimal:
    original = Decimal(value)
    if not original.is_finite() or original <= 0:
        raise PricingConfigurationError("原始价必须是大于 0 的有限金额")
    original = _money(original)
    if original <= 0:
        raise PricingConfigurationError("原始价量化后必须大于 0")
    return original


def resolve_membership(
    last_successful_recharge: Decimal | int | None,
) -> str | None:
    """按最近一次成功充值的单笔金额解析会员等级。"""

    if last_successful_recharge is None:
        return None
    amount = Decimal(last_successful_recharge)
    if amount >= Decimal("100000"):
        return "supreme"
    if amount >= Decimal("30000"):
        return "black"
    if amount >= Decimal("10000"):
        return "silver"
    return None


def _build_matrix_key(
    *, product_type: str, craft: str, length: str, size: str | None = None
) -> tuple[str, str, str | None, str] | None:
    """提取真实定价维度；头套忽略尺码，发片支持独立或合并工艺尺码。"""

    if product_type == "cap":
        return product_type, craft, None, length
    if product_type != "piece":
        return None
    if not size:
        combined = COMBINED_PIECE_CRAFT_SIZE.get(craft)
        if combined is None:
            return None
        craft, size = combined
    return product_type, craft, size, length


def get_base_price(
    *, product_type: str, craft: str, length: str, size: str | None = None
) -> Decimal | None:
    """从已确认种子矩阵按产品定价维度取原始价格。"""

    key = _build_matrix_key(
        product_type=product_type, craft=craft, size=size, length=length
    )
    return BASE_PRICE_SEED_MATRIX.get(key) if key is not None else None


def build_persistence_price_key(
    *, product_type: str, craft: str, length: str, size: str | None = None
) -> tuple[str, str, str] | None:
    """把产品属性转换为数据库使用的合并价格键。"""

    if product_type == "cap":
        if craft not in _CAP_CRAFT_CODES:
            return None
        return product_type, craft, length
    if product_type != "piece":
        return None

    if size:
        combined_craft = _COMBINED_PIECE_BY_DIMENSIONS.get((craft, size))
    else:
        combined_craft = craft if craft in COMBINED_PIECE_CRAFT_SIZE else None
    if combined_craft is None:
        return None
    return product_type, combined_craft, length


def iter_base_price_seeds(
) -> Iterator[tuple[str, str, str, Decimal]]:
    """按实际产品键逐行输出可直接持久化的已确认原始价格。"""

    for (product_type, craft, size, length), price in BASE_PRICE_SEED_MATRIX.items():
        persistence_key = build_persistence_price_key(
            product_type=product_type,
            craft=craft,
            size=size,
            length=length,
        )
        if persistence_key is None:
            raise PricingConfigurationError("原始价格种子无法映射到持久化产品键")
        yield *persistence_key, price


def resolve_discount(
    *,
    product_type: str,
    craft: str,
    length: str,
    original_price: Decimal | int,
    membership_level: str | None,
    size: str | None = None,
) -> DiscountResult:
    """按固定会员价优先、普通立减其次的顺序计算成交价。"""

    if membership_level is not None and membership_level not in MEMBERSHIP_REDUCTIONS:
        raise PricingConfigurationError(f"未知会员等级：{membership_level!r}")
    original = _validated_original_price(original_price)
    reduction = MEMBERSHIP_REDUCTIONS.get(membership_level)
    if reduction is None:
        return DiscountResult(original, original, Decimal("0.00"), "base_price")

    fixed_price = None
    if product_type == "cap":
        fixed_price = MEMBER_FIXED_PRICES.get((craft, length, membership_level))
    if fixed_price is not None:
        if fixed_price > original:
            return DiscountResult(
                original, original, Decimal("0.00"), "member_fixed_capped"
            )
        final_price = fixed_price
        return DiscountResult(
            original,
            final_price,
            _money(original - final_price),
            "member_fixed",
        )

    final_price = _money(original - reduction)
    if final_price < 0:
        raise PricingConfigurationError("会员立减后价格低于 0，请检查原始价或优惠配置")
    return DiscountResult(
        original,
        final_price,
        _money(original - final_price),
        "member_reduction",
    )
