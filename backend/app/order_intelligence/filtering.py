"""订单经营分析的统一多维筛选口径。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MAX_FILTER_VALUES = 100
SOURCE_CODES = frozenset({
    "alibaba_inquiry",
    "alibaba_ecosystem",
    "social_owned",
    "social_assigned",
    "referral",
    "website",
    "other",
    "unknown",
})

# 展示层按大洲分组；只对实际出现的国家做归类，未命中的新值进入“其他”。
CONTINENT_COUNTRIES = {
    "北美洲": frozenset({
        "美国", "加拿大", "墨西哥", "波多黎各", "多米尼加共和国", "洪都拉斯",
        "牙买加", "危地马拉", "特立尼达和多巴哥", "巴巴多斯", "古巴", "巴拿马",
        "哥斯达黎加", "萨尔瓦多", "尼加拉瓜", "海地", "巴哈马", "伯利兹",
    }),
    "南美洲": frozenset({
        "巴西", "智利", "哥伦比亚", "委内瑞拉", "阿根廷", "苏里南", "圭亚那",
        "秘鲁", "厄瓜多尔", "玻利维亚", "巴拉圭", "乌拉圭",
    }),
    "欧洲": frozenset({
        "英国", "荷兰", "德国", "瑞典", "比利时", "爱尔兰", "瑞士", "丹麦",
        "捷克", "波兰", "塞浦路斯", "法国", "罗马尼亚", "保加利亚", "克罗地亚",
        "挪威", "芬兰", "意大利", "斯洛伐克", "摩尔多瓦", "奥地利", "西班牙",
        "马耳他", "希腊", "乌克兰", "葡萄牙", "俄罗斯", "冰岛", "匈牙利",
        "梵蒂冈", "卢森堡", "立陶宛", "拉脱维亚", "爱沙尼亚", "斯洛文尼亚",
        "塞尔维亚", "黑山", "阿尔巴尼亚", "北马其顿", "波黑", "白俄罗斯",
    }),
    "亚洲": frozenset({
        "阿联酋", "以色列", "科威特", "沙特阿拉伯", "印尼", "印度尼西亚", "尼泊尔",
        "缅甸", "菲律宾", "新加坡", "约旦", "中国", "马来西亚", "韩国", "中国台湾",
        "印度", "土耳其", "日本", "泰国", "越南", "柬埔寨", "老挝", "巴基斯坦",
        "孟加拉国", "斯里兰卡", "卡塔尔", "巴林", "阿曼", "伊拉克", "伊朗",
    }),
    "非洲": frozenset({
        "南非", "科特迪瓦", "尼日利亚", "博茨瓦纳", "赞比亚", "贝宁", "毛里求斯",
        "喀麦隆", "塞舌尔", "多哥", "摩洛哥", "埃及", "肯尼亚", "坦桑尼亚",
        "埃塞俄比亚", "加纳", "乌干达", "塞内加尔", "突尼斯", "阿尔及利亚",
    }),
    "大洋洲": frozenset({
        "澳大利亚", "新西兰", "关岛", "斐济", "巴布亚新几内亚", "萨摩亚",
    }),
}
CONTINENT_ORDER = (*CONTINENT_COUNTRIES.keys(), "其他")


def _clean(values: Iterable[str] | None, field: str) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(
        str(value).strip() for value in (values or ())
        if value is not None and str(value).strip()
    ))
    if len(result) > MAX_FILTER_VALUES:
        raise ValueError(f"{field}最多选择 {MAX_FILTER_VALUES} 项")
    if any(len(value) > 200 for value in result):
        raise ValueError(f"{field}包含过长选项")
    return result


@dataclass(frozen=True)
class AnalysisFilters:
    countries: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    colors: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        countries: Iterable[str] | None = None,
        models: Iterable[str] | None = None,
        colors: Iterable[str] | None = None,
        sources: Iterable[str] | None = None,
    ) -> "AnalysisFilters":
        clean_sources = _clean(sources, "订单来源")
        invalid_sources = set(clean_sources) - SOURCE_CODES
        if invalid_sources:
            raise ValueError("订单来源包含无效选项")
        return cls(
            countries=_clean(countries, "国家"),
            models=_clean(models, "产品型号"),
            colors=_clean(colors, "颜色"),
            sources=clean_sources,
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "countries": list(self.countries),
            "models": list(self.models),
            "colors": list(self.colors),
            "sources": list(self.sources),
        }

    def is_empty(self) -> bool:
        return not (self.countries or self.models or self.colors or self.sources)


def _bind_list(params: dict, prefix: str, values: tuple[str, ...]) -> str:
    names = []
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        params[key] = value
        names.append(f":{key}")
    return ", ".join(names)


def model_expression(item_alias: str, product_alias: str, fallback_name: bool = True) -> str:
    fallback = (
        f", NULLIF(TRIM(SUBSTRING_INDEX({item_alias}.product_name, '/', 1)), '')"
        if fallback_name else ""
    )
    return (
        f"COALESCE(NULLIF(TRIM({product_alias}.model), ''), "
        f"NULLIF(TRIM({item_alias}.product_model), ''){fallback}, '未知')"
    )


def color_expression(item_alias: str, product_alias: str) -> str:
    return (
        f"COALESCE(NULLIF(TRIM({product_alias}.color), ''), "
        f"CASE WHEN LENGTH(COALESCE({item_alias}.product_name, '')) "
        f"- LENGTH(REPLACE(COALESCE({item_alias}.product_name, ''), '/', '')) >= 2 "
        f"THEN NULLIF(TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX({item_alias}.product_name, '/', -2), '/', 1)), '') END, "
        "'未知')"
    )


def _country_expression(customer_alias: str) -> str:
    return (
        f"COALESCE(NULLIF(NULLIF(TRIM({customer_alias}.country_name), ''), '0'), '未知')"
    )


def order_sql(
    filters: AnalysisFilters,
    params: dict,
    schema: str,
    order_alias: str = "o",
    customer_alias: str = "ci",
) -> str:
    clauses = []
    if filters.countries:
        values = _bind_list(params, "filter_country", filters.countries)
        clauses.append(f"{_country_expression(customer_alias)} IN ({values})")
    if filters.models or filters.colors:
        detail_clauses = [f"filter_oi.order_id = {order_alias}.order_id"]
        if filters.models:
            values = _bind_list(params, "filter_model", filters.models)
            detail_clauses.append(f"{model_expression('filter_oi', 'filter_p', False)} IN ({values})")
        if filters.colors:
            values = _bind_list(params, "filter_color", filters.colors)
            detail_clauses.append(f"{color_expression('filter_oi', 'filter_p')} IN ({values})")
        clauses.append(
            f"EXISTS (SELECT 1 FROM `{schema}`.okki_order_items filter_oi "
            f"LEFT JOIN `{schema}`.okki_products filter_p ON filter_p.product_id = filter_oi.product_id "
            f"WHERE {' AND '.join(detail_clauses)})"
        )
    return " AND " + " AND ".join(clauses) if clauses else ""


def product_sql(filters: AnalysisFilters, params: dict, item_alias: str = "oi", product_alias: str = "p") -> str:
    clauses = []
    if filters.models:
        values = _bind_list(params, "product_model", filters.models)
        clauses.append(f"{model_expression(item_alias, product_alias, False)} IN ({values})")
    if filters.colors:
        values = _bind_list(params, "product_color", filters.colors)
        clauses.append(f"{color_expression(item_alias, product_alias)} IN ({values})")
    return " AND " + " AND ".join(clauses) if clauses else ""


def group_countries(countries: Iterable[str]) -> list[dict]:
    grouped = {continent: [] for continent in CONTINENT_ORDER}
    for country in sorted(set(countries)):
        continent = next(
            (name for name, members in CONTINENT_COUNTRIES.items() if country in members),
            "其他",
        )
        grouped[continent].append(country)
    return [
        {
            "label": continent,
            "value": continent,
            "children": [{"label": country, "value": country} for country in grouped[continent]],
        }
        for continent in CONTINENT_ORDER
        if grouped[continent]
    ]
