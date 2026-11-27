"""商品等级与颜色类型：供员工端价格、授权列表按同一口径筛选。"""
import re

from sqlalchemy import select

from app.invoice import price_service
from app.invoice.models import PriceColorType

# 价格矩阵的颜色类型值 → 页面文字；未登记且推断不出的归「其他」
COLOR_TYPE_LABELS = {"solid": "单色", "piano": "P色", "ombre": "T色", "balayage": "TP色"}
COLOR_TYPE_ORDER = [*COLOR_TYPE_LABELS.values(), "其他"]


def product_grade(model):
    """等级取自内部型号开头：B1/B3…，或「50%幅度」；配件等无等级返回 None。"""
    text = str(model or "").strip().upper()
    match = re.match(r"(B\d+)", text) or re.match(r"(\d+%幅度)", text)
    return match.group(1) if match else None


def _key(code):
    return price_service.normalize_color(code).lower()


class ColorTypes:
    """与订单价格同口径：先查价格矩阵登记的颜色类型，未登记再按色号推断。"""

    def __init__(self, db):
        # 登记表只有几十行；按库的大小写不敏感比较在内存里复现
        self.mapped = {_key(code): kind for code, kind in db.execute(
            select(PriceColorType.color_code, PriceColorType.color_type)).all()}

    def label(self, color):
        code = price_service.normalize_color(color)
        kind = self.mapped.get(_key(code)) or (price_service._infer_color_type(code) if code else None)
        return COLOR_TYPE_LABELS.get(kind, "其他")


def traits(row, colors):
    standard = row.standard_json or {}
    return {"grade": product_grade(standard.get("model")),
            "color_type": colors.label(standard.get("color") or row.color_name)}


def _grade_order(grade):
    # B1 < B3 < B10，再排「50%幅度」这类非 B 等级
    match = re.match(r"B(\d+)$", grade)
    return (0, int(match.group(1)), "") if match else (1, 0, grade)


def facets(all_traits):
    """下拉选项只列当前范围内实际出现的等级与颜色类型。"""
    present = {info["color_type"] for info in all_traits}
    return {"grades": sorted({info["grade"] for info in all_traits if info["grade"]}, key=_grade_order),
            "color_types": [kind for kind in COLOR_TYPE_ORDER if kind in present]}


def _weight(value):
    # 克重输入 20 与 20g 视为同一规格
    return re.sub(r"\s+", "", str(value or "")).lower().removesuffix("g")


def matches(row, row_traits, *, color=None, length=None, weight=None, grade=None, color_type=None):
    standard = row.standard_json or {}
    return ((not color or color.strip().lower() in str(row.color_name or "").lower())
            and (not length or str(standard.get("length") or "").strip() == length.strip())
            and (not weight or _weight(standard.get("weight")) == _weight(weight))
            and (not grade or row_traits["grade"] == grade)
            and (not color_type or row_traits["color_type"] == color_type))
