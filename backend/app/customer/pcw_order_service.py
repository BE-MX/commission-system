"""私海客户工作台（PCW）：订单只读视图、确定性订单统计与可解释复购窗口。

设计依据 docs/requirements/private-customer-workbench-prototype/：
- development-spec.md PCW-04 与 product-plan.md 第 7 节：统计口径与复购算法；
- api-contracts.md 第 3 节 orders/order-analytics/reorder-windows 行、第 5 节读模型必备键；
- schema-migrations.md 第 1 节：OrderAnalysisBatchMap / ReorderWindow 语义。

口径要点（全部为确定性规则，不使用语言模型）：
- 有效订单：CustomerOrder.is_valid_business_order（投影层按小满 status/status_name/
  trail 的确定性口径写入）；excluded_reasons 中 invalid 且 order_status 为小满
  “已终止”状态码的计为 cancelled，其余无效计为 invalid；
- 订单类型由明细 item_type 派生：全 sample→sample、全 bulk→bulk、
  sample+bulk→mixed、其余（无明细或含 unknown 行）→unknown；
- 金额按 (维度值, 币种) 分桶，Decimal 求和后转字符串，绝不跨币种相加；
  缺金额/缺币种的明细不计入并计入 unknown_count，不置零；
- 数量按 (维度值, 单位) 分桶，pcs/kg/bundles 不混加；unit 参数做行级过滤；
- order_coverage 桶=含该维度值的有效订单数，分母 eligible_order_count 写进响应，
  可交叉、合计允许超过 100%；
- 维度值未知（未映射）进入“（未知）”桶并计入 unknown_count；
- 复购窗口：有效商业订单按 (客户, 产品族, 业务日期) 同日归并为低置信近似批次
  （purchase_batch_key="day:<iso-date>"，provenance="same_day_merge"），
  ≥4 批次（≥3 间隔）才开窗；间隔中位数为基准，极差/中位数>0.6 降级 irregular；
  窗口=末批日期+中位数±7 天；新批次落在旧 open 窗口内→旧窗口 covered 并取消
  其 pending 行动与事项，新批次在窗口外但有更新批次→旧窗口 superseded；
  以最新批次为 anchor  upsert 新窗口（occurrence_key 幂等）。

写操作只flush不commit，事务边界由调用方（测试/未来的投影层或调度入口）控制；
批量处理逐客户 savepoint 隔离，单客户失败记 failures 并继续，不无声吞异常。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable, Mapping, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import get_live_user_authorization
from app.core.time import beijing_now, beijing_now_aware, to_beijing_time
from app.customer import pcw_errors
from app.customer.access_service import (
    CustomerAccessDenied,
    require_customer_access,
)
from app.customer.logical_customer_service import (
    logical_root_predicate,
    resolve_canonical_customer_id,
)
from app.customer.models import (
    CustomerAction,
    CustomerOrder,
    CustomerOrderItem,
    CustomerSyncCursor,
)
from app.customer.pcw_models import (
    CustomerWorkItem,
    OrderAnalysisBatchMap,
    ReorderWindow,
)
from app.order_intelligence.service import ORDER_STATUS_TERMINATED

logger = logging.getLogger(__name__)

METRIC_VERSION = "order_analytics_v1"
DEFAULT_MAPPING_VERSION = "commercial_cycle_v1"

DIMENSIONS = frozenset({"product_family", "model", "color", "length"})
MEASURES = frozenset({"amount", "quantity", "order_coverage"})

UNKNOWN_BUCKET = "（未知）"
AMOUNT_BASIS_ORIGINAL = "original_currency"

# 复购窗口试点阈值（development-spec PCW-04 / product-plan §7.3，待业务确认）
MIN_BATCHES_FOR_WINDOW = 4
IRREGULAR_RANGE_RATIO = Decimal("0.6")
WINDOW_MARGIN_DAYS = 7

_READ_PERMISSIONS = frozenset({"customer:read", "customer:read_all", "customer:admin"})
_MANAGE_PERMISSIONS = frozenset({"customer:read_all", "customer:admin"})

# 与 pcw_overview_service 同一水位口径：>48h 未推进视为 stale
_WATERMARK_STALE_AFTER = timedelta(hours=48)

_OPEN_ITEM_STATES = ("open", "awaiting_reply")

_BATCH_KEY_PREFIX = "day:"


def _iso_bj(value) -> str | None:
    if value is None:
        return None
    return to_beijing_time(value).isoformat(timespec="seconds")


def _dec_str(value) -> str | None:
    """Decimal 转字符串（固定小数点，不用科学计数法）；None 保持 None。"""
    if value is None:
        return None
    return format(Decimal(str(value)), "f")


def _parse_date_param(value, field: str) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise pcw_errors.bad_request(
                f"{field} 必须是 ISO 日期", error_code="DATE_FILTER_INVALID"
            ) from exc
    raise pcw_errors.bad_request(
        f"{field} 必须是 ISO 日期", error_code="DATE_FILTER_INVALID"
    )


def _access_customer(
    db: Session, *, customer_id: int, actor_user_id: int
) -> int:
    """鉴权 + 合并客户解析，返回当前逻辑（canonical）客户ID；失权/不存在一律 404。"""
    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise pcw_errors.customer_not_found()
    roles, permissions = get_live_user_authorization(db, actor_user_id)
    user = {"sub": actor_user_id, "roles": roles, "permissions": permissions}
    try:
        access = require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions=_READ_PERMISSIONS,
            manage_permissions=_MANAGE_PERMISSIONS,
        )
    except CustomerAccessDenied:
        raise pcw_errors.customer_not_found() from None
    return int(access.customer_id)


def _logical_orders(db: Session, customer_id: int) -> list[CustomerOrder]:
    """当前逻辑客户名下的全部订单（含合并带入），按业务日期/ID 稳定排序。"""
    return (
        db.query(CustomerOrder)
        .filter(logical_root_predicate(CustomerOrder, "order", customer_id))
        .order_by(CustomerOrder.account_date.asc(), CustomerOrder.id.asc())
        .all()
    )


def _items_by_order(
    db: Session, order_ids: Sequence[int]
) -> dict[int, list[CustomerOrderItem]]:
    if not order_ids:
        return {}
    rows = (
        db.query(CustomerOrderItem)
        .filter(CustomerOrderItem.order_id.in_(order_ids))
        .order_by(CustomerOrderItem.id.asc())
        .all()
    )
    grouped: dict[int, list[CustomerOrderItem]] = {}
    for row in rows:
        grouped.setdefault(int(row.order_id), []).append(row)
    return grouped


def derive_order_type(items: Iterable[CustomerOrderItem]) -> str:
    """按投影明细口径派生订单类型：sample/bulk/mixed/unknown。"""
    types = {item.item_type for item in items}
    if types == {"sample"}:
        return "sample"
    if types == {"bulk"}:
        return "bulk"
    if types == {"sample", "bulk"}:
        return "mixed"
    return "unknown"


def _order_summary(
    order: CustomerOrder, items: list[CustomerOrderItem]
) -> dict:
    """列表行：金额未知为 None 加 reason，不置零；standard_amount_usd 带质量标记。"""
    if order.amount_original is not None and order.currency:
        amount = _dec_str(order.amount_original)
        amount_reason = None
    else:
        amount = None
        amount_reason = "missing_original_amount"
    # amount_usd 列非空但投影在缺原币时落默认值 0：无原币金额时美元值不可验证，按未知处理
    if order.amount_original is not None:
        standard_amount_usd = _dec_str(order.amount_usd)
        usd_quality = "projected"
    else:
        standard_amount_usd = None
        usd_quality = "unavailable"
    return {
        "id": int(order.id),
        "order_no": order.order_no,
        "effective_date": order.account_date.isoformat() if order.account_date else None,
        "status": order.order_status,
        "order_type": derive_order_type(items),
        "amount": amount,
        "amount_reason": amount_reason,
        "currency": order.currency,
        "standard_amount_usd": standard_amount_usd,
        "standard_amount_quality": usd_quality,
        "item_count": len(items),
        "is_valid_business_order": bool(order.is_valid_business_order),
        "source": order.source_system,
        "synced_at": _iso_bj(order.synced_at),
    }


def list_customer_orders(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    date_from=None,
    date_to=None,
    order_type: str | None = None,
    status: str | None = None,
    product_family: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """客户订单只读列表（api-contracts §3 orders 行）。逻辑客户解析合并客户。

    只读，无写操作。order_type/product_family 为明细派生筛选，在 SQL 日期/状态
    过滤后于内存中分类过滤再分页；单客户订单量级下无 N+1（明细一次 IN 查询）。
    """
    canonical_id = _access_customer(
        db, customer_id=customer_id, actor_user_id=actor_user_id
    )
    date_from = _parse_date_param(date_from, "date_from")
    date_to = _parse_date_param(date_to, "date_to")
    if order_type is not None and order_type not in {"sample", "bulk", "mixed", "unknown"}:
        raise pcw_errors.bad_request(
            "order_type 不合法",
            error_code="ORDER_TYPE_INVALID",
            details={"allowed": ["sample", "bulk", "mixed", "unknown"]},
        )
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), 100)

    orders = _logical_orders(db, canonical_id)
    if date_from is not None:
        orders = [o for o in orders if o.account_date is not None and o.account_date >= date_from]
    if date_to is not None:
        orders = [o for o in orders if o.account_date is not None and o.account_date <= date_to]
    if status is not None:
        orders = [o for o in orders if o.order_status == status]

    items_map = _items_by_order(db, [int(o.id) for o in orders])
    rows: list[dict] = []
    for order in orders:
        items = items_map.get(int(order.id), [])
        summary = _order_summary(order, items)
        if order_type is not None and summary["order_type"] != order_type:
            continue
        if product_family is not None and not any(
            item.product_family == product_family for item in items
        ):
            continue
        rows.append(summary)

    # 列表按业务日期倒序（最新在前），同日期按 ID 倒序保证稳定
    rows.sort(
        key=lambda row: (row["effective_date"] or "", row["id"]), reverse=True
    )
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_order_detail(
    db: Session, *, customer_id: int, order_id: int, actor_user_id: int
) -> dict:
    """订单明细只读视图；订单不属于当前逻辑客户时 404（不泄漏存在性）。"""
    canonical_id = _access_customer(
        db, customer_id=customer_id, actor_user_id=actor_user_id
    )
    order = (
        db.query(CustomerOrder)
        .filter(
            CustomerOrder.id == order_id,
            logical_root_predicate(CustomerOrder, "order", canonical_id),
        )
        .one_or_none()
    )
    if order is None:
        raise pcw_errors.customer_not_found()
    items = _items_by_order(db, [int(order.id)]).get(int(order.id), [])
    return {
        **_order_summary(order, items),
        "order_name": order.order_name,
        "external_order_id": order.external_order_id,
        "source_account_key": order.source_account_key,
        "invalid_reason": order.invalid_reason,
        "items": [
            {
                "id": int(item.id),
                "product_name": item.product_name,
                "product_family": item.product_family,
                "model": item.model,
                "color": item.color,
                "length": item.length,
                "quantity": _dec_str(item.quantity),
                "quantity_unit": item.quantity_unit,
                "unit_price": _dec_str(item.unit_price),
                "line_amount": _dec_str(item.line_amount),
                "currency": order.currency,
                "item_type": item.item_type,
            }
            for item in items
        ],
    }


def _classify_population(
    orders: list[CustomerOrder], items_map: Mapping[int, list[CustomerOrderItem]]
) -> tuple[list[tuple[CustomerOrder, list[CustomerOrderItem]]], dict]:
    """把（已按日期/产品族过滤的）订单总体分为有效商业单与排除集。

    返回 (eligible[(order, items)], excluded_reasons)。样品单与未知类型单分列，
    不与商业单混算；无效单按投影字段拆分 cancelled（终止未结清）/invalid。
    """
    eligible: list[tuple[CustomerOrder, list[CustomerOrderItem]]] = []
    excluded = {"cancelled": 0, "invalid": 0, "sample": 0, "unknown_type": 0}
    for order in orders:
        items = items_map.get(int(order.id), [])
        if not order.is_valid_business_order:
            if order.order_status == ORDER_STATUS_TERMINATED:
                excluded["cancelled"] += 1
            else:
                excluded["invalid"] += 1
            continue
        order_type = derive_order_type(items)
        if order_type == "sample":
            excluded["sample"] += 1
        elif order_type == "unknown":
            excluded["unknown_type"] += 1
        else:
            eligible.append((order, items))
    return eligible, excluded


def _dimension_value(item: CustomerOrderItem, dimension: str) -> str | None:
    value = getattr(item, dimension)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bucket_amount(eligible, dimension, currency_filter):
    """金额按 (维度值, 币种) 分桶；缺金额/币种计入 unknown_count，不跨币种相加。"""
    buckets: dict[tuple[str, str], dict] = {}
    unknown_count = 0
    included_order_ids: set[int] = set()
    for order, items in eligible:
        for item in items:
            if item.item_type != "bulk":
                continue  # 混合订单的样品行不进商业金额桶
            currency = order.currency
            value = _dimension_value(item, dimension)
            if (
                value is None
                or item.line_amount is None
                or not currency
            ):
                unknown_count += 1
                if item.line_amount is None or not currency:
                    continue  # 无金额/币种无法入账，直接跳过
            if currency_filter is not None and currency != currency_filter:
                continue
            key = (value or UNKNOWN_BUCKET, currency)
            bucket = buckets.setdefault(
                key, {"value": key[0], "currency": currency, "amount": Decimal("0"), "order_ids": set()}
            )
            bucket["amount"] += Decimal(str(item.line_amount))
            bucket["order_ids"].add(int(order.id))
            included_order_ids.add(int(order.id))
    rows = [
        {
            "value": bucket["value"],
            "currency": bucket["currency"],
            "amount": format(bucket["amount"], "f"),
            "order_count": len(bucket["order_ids"]),
        }
        for _, bucket in sorted(buckets.items())
    ]
    return rows, unknown_count, len(included_order_ids)


def _bucket_quantity(eligible, dimension, unit_filter):
    """数量按 (维度值, 单位) 分桶；pcs/kg/bundles 不混加；缺数量/单位计 unknown。"""
    buckets: dict[tuple[str, str], dict] = {}
    unknown_count = 0
    included_order_ids: set[int] = set()
    for order, items in eligible:
        for item in items:
            if item.item_type != "bulk":
                continue
            value = _dimension_value(item, dimension)
            unit = (item.quantity_unit or "").strip() or None
            if value is None or item.quantity is None or unit is None:
                unknown_count += 1
                if item.quantity is None or unit is None:
                    continue
            if unit_filter is not None and unit != unit_filter:
                continue
            key = (value or UNKNOWN_BUCKET, unit)
            bucket = buckets.setdefault(
                key, {"value": key[0], "unit": unit, "quantity": Decimal("0"), "order_ids": set()}
            )
            bucket["quantity"] += Decimal(str(item.quantity))
            bucket["order_ids"].add(int(order.id))
            included_order_ids.add(int(order.id))
    rows = [
        {
            "value": bucket["value"],
            "unit": bucket["unit"],
            "quantity": format(bucket["quantity"], "f"),
            "order_count": len(bucket["order_ids"]),
        }
        for _, bucket in sorted(buckets.items())
    ]
    return rows, unknown_count, len(included_order_ids)


def _bucket_order_coverage(eligible, dimension, eligible_order_count):
    """覆盖率：桶=含该维度值的有效订单数；可交叉，合计允许超过 100%。

    无任何已知维度值的订单进“（未知）”桶并计入 unknown_count；每个有效订单
    都会落入某个桶，故 included_count == eligible_order_count。
    """
    counts: dict[str, int] = {}
    unknown_count = 0
    for order, items in eligible:
        values = {
            value
            for item in items
            if item.item_type == "bulk"
            for value in [_dimension_value(item, dimension)]
            if value is not None
        }
        if not values:
            counts[UNKNOWN_BUCKET] = counts.get(UNKNOWN_BUCKET, 0) + 1
            unknown_count += 1
            continue
        for value in sorted(values):
            counts[value] = counts.get(value, 0) + 1
    rows = []
    for value in sorted(counts):
        order_count = counts[value]
        pct = None
        if eligible_order_count:
            pct = format(
                (Decimal(order_count) * 100 / Decimal(eligible_order_count)).quantize(
                    Decimal("0.01")
                ),
                "f",
            )
        rows.append(
            {"value": value, "order_count": order_count, "coverage_pct": pct}
        )
    return rows, unknown_count, len(eligible)


def _commercial_batch_dates(
    eligible: Iterable[tuple[CustomerOrder, list[CustomerOrderItem]]]
) -> dict[str, list[date]]:
    """有效商业订单按 (产品族, 业务日期) 归并批次日期（同日去重，升序）。

    仅 bulk 行参与；无业务日期或无产品族的行无法归批，跳过。
    """
    dates_by_family: dict[str, set[date]] = {}
    for order, items in eligible:
        if order.account_date is None:
            continue
        families = {
            item.product_family.strip()
            for item in items
            if item.item_type == "bulk"
            and item.product_family
            and item.product_family.strip()
        }
        for family in families:
            dates_by_family.setdefault(family, set()).add(order.account_date)
    return {family: sorted(days) for family, days in dates_by_family.items()}


def _cycle_samples(
    dates_by_family: Mapping[str, list[date]]
) -> list[dict]:
    """各产品族商业采购间隔样本与中位数；不足 2 批次（无间隔）的族不列出。"""
    samples = []
    for family in sorted(dates_by_family):
        days = dates_by_family[family]
        if len(days) < 2:
            continue
        intervals = [
            (later - earlier).days for earlier, later in zip(days, days[1:])
        ]
        samples.append(
            {
                "product_family": family,
                "batch_count": len(days),
                "interval_days": intervals,
                "median_interval_days": _median_days(intervals),
            }
        )
    return samples


def _median_days(intervals: Sequence[int]) -> int:
    """间隔中位数（天）；偶数样本取两中值平均后四舍五入到天。"""
    value = median(intervals)
    return int(value) if float(value).is_integer() else int(round(float(value)))


def _source_watermarks(db: Session, customer_id: int, now) -> list[dict]:
    """订单投影来源水位：优先小满 orders 同步游标，叠加本客户订单最近投影时间。"""
    entries: list[dict] = []
    cursors = (
        db.query(CustomerSyncCursor)
        .filter(
            CustomerSyncCursor.source_system == "okki",
            CustomerSyncCursor.resource_type == "orders",
        )
        .all()
    )
    synced = max(
        (c.last_success_at for c in cursors if c.last_success_at is not None),
        default=None,
    )
    if cursors:
        entries.append(
            {
                "source": "okki",
                "resource": "orders",
                "synced_through": _iso_bj(synced),
                "status": (
                    "unknown"
                    if synced is None
                    else "stale" if now - synced > _WATERMARK_STALE_AFTER else "fresh"
                ),
                "basis": "customer_sync_cursor",
            }
        )
    projection_synced = max(
        (
            order.synced_at
            for order in db.query(CustomerOrder.synced_at)
            .filter(logical_root_predicate(CustomerOrder, "order", customer_id))
            .all()
            if order.synced_at is not None
        ),
        default=None,
    )
    entries.append(
        {
            "source": "okki",
            "resource": "orders",
            "synced_through": _iso_bj(projection_synced),
            "status": (
                "unknown"
                if projection_synced is None
                else "stale"
                if now - projection_synced > _WATERMARK_STALE_AFTER
                else "fresh"
            ),
            "basis": "customer_order_projection",
        }
    )
    if not cursors and projection_synced is None:
        entries[0]["note"] = "无订单同步游标且无本客户订单投影记录，同步水位未知"
    return entries


def get_order_analytics(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    dimension: str,
    measure: str,
    currency: str | None = None,
    unit: str | None = None,
    product_family: str | None = None,
    date_from=None,
    date_to=None,
) -> dict:
    """订单结构统计（api-contracts §3 order-analytics 行、§5 必备键）。只读。

    - measure=amount：按 (维度值, 币种) 分桶，amount_basis="original_currency"；
    - measure=quantity：按 (维度值, 单位) 分桶，unit 参数行级过滤；
    - measure=order_coverage：含该维度值的有效订单数 / eligible_order_count；
    - 统一美元指标暂不返回：amount_usd 投影口径（缺失落 0）当前不可逐单验证，
      待金额质量可核验后再提供，不伪造。
    """
    canonical_id = _access_customer(
        db, customer_id=customer_id, actor_user_id=actor_user_id
    )
    if dimension not in DIMENSIONS:
        raise pcw_errors.bad_request(
            "dimension 不合法",
            error_code="ANALYTICS_DIMENSION_INVALID",
            details={"allowed": sorted(DIMENSIONS)},
        )
    if measure not in MEASURES:
        raise pcw_errors.bad_request(
            "measure 不合法",
            error_code="ANALYTICS_MEASURE_INVALID",
            details={"allowed": sorted(MEASURES)},
        )
    date_from = _parse_date_param(date_from, "date_from")
    date_to = _parse_date_param(date_to, "date_to")

    all_orders = _logical_orders(db, canonical_id)
    all_items_map = _items_by_order(db, [int(o.id) for o in all_orders])
    # 周期样本基于客户全量有效商业订单史（不受本次筛选影响），无则空
    full_eligible, _full_excluded = _classify_population(all_orders, all_items_map)
    cycle_samples = _cycle_samples(_commercial_batch_dates(full_eligible))

    orders = all_orders
    items_map = all_items_map
    if date_from is not None:
        orders = [o for o in orders if o.account_date is not None and o.account_date >= date_from]
    if date_to is not None:
        orders = [o for o in orders if o.account_date is not None and o.account_date <= date_to]
    if product_family is not None:
        orders = [
            o
            for o in orders
            if any(
                item.product_family == product_family
                for item in items_map.get(int(o.id), [])
            )
        ]

    eligible, excluded_reasons = _classify_population(orders, items_map)
    eligible_order_count = len(eligible)

    if measure == "amount":
        buckets, unknown_count, included_count = _bucket_amount(
            eligible, dimension, currency
        )
        amount_basis = AMOUNT_BASIS_ORIGINAL
        quantity_unit = None
    elif measure == "quantity":
        buckets, unknown_count, included_count = _bucket_quantity(
            eligible, dimension, unit
        )
        amount_basis = None
        quantity_unit = unit
    else:
        buckets, unknown_count, included_count = _bucket_order_coverage(
            eligible, dimension, eligible_order_count
        )
        amount_basis = None
        quantity_unit = None

    now = beijing_now()
    return {
        "metric_version": METRIC_VERSION,
        "generated_at": beijing_now_aware().isoformat(timespec="seconds"),
        "filters": {
            "dimension": dimension,
            "measure": measure,
            "currency": currency,
            "unit": unit,
            "product_family": product_family,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "amount_basis": amount_basis,
        "quantity_unit": quantity_unit,
        "eligible_order_count": eligible_order_count,
        "included_count": included_count,
        "unknown_count": unknown_count,
        "excluded_reasons": excluded_reasons,
        "buckets": buckets,
        "cycle_samples": cycle_samples,
        "source_watermarks": _source_watermarks(db, canonical_id, now),
    }


def _batch_key(day: date) -> str:
    return f"{_BATCH_KEY_PREFIX}{day.isoformat()}"


def _batch_key_date(key: str) -> date | None:
    if not isinstance(key, str) or not key.startswith(_BATCH_KEY_PREFIX):
        return None
    try:
        return date.fromisoformat(key[len(_BATCH_KEY_PREFIX) :])
    except ValueError:
        return None


def _ensure_batch_maps(
    db: Session,
    *,
    eligible: Iterable[tuple[CustomerOrder, list[CustomerOrderItem]]],
    mapping_version: str,
) -> int:
    """按明细写 OrderAnalysisBatchMap；(order_item_id, mapping_version) 唯一保证幂等。"""
    written = 0
    for order, items in eligible:
        if order.account_date is None:
            continue
        for item in items:
            if item.item_type != "bulk":
                continue
            family = (item.product_family or "").strip()
            if not family:
                continue
            exists = (
                db.query(OrderAnalysisBatchMap.id)
                .filter(
                    OrderAnalysisBatchMap.order_item_id == item.id,
                    OrderAnalysisBatchMap.mapping_version == mapping_version,
                )
                .first()
            )
            if exists is not None:
                continue
            row = OrderAnalysisBatchMap(
                order_id=int(order.id),
                order_item_id=int(item.id),
                purchase_batch_key=_batch_key(order.account_date),
                product_family=family,
                mapping_version=mapping_version,
                provenance="same_day_merge",
                quality_status="low_confidence",
            )
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                written += 1
            except IntegrityError:
                # 并发重放：唯一键兜底，已存在即幂等
                winner = (
                    db.query(OrderAnalysisBatchMap.id)
                    .filter(
                        OrderAnalysisBatchMap.order_item_id == item.id,
                        OrderAnalysisBatchMap.mapping_version == mapping_version,
                    )
                    .first()
                )
                if winner is None:
                    raise
    return written


def _cancel_window_action_and_item(
    db: Session, window: ReorderWindow, now
) -> None:
    """新单覆盖窗口：取消其 pending 行动并关闭关联事项（直接操作模型，同事务）。"""
    if window.action_id is not None:
        action = db.get(CustomerAction, int(window.action_id))
        if action is not None and action.status == "pending":
            action.status = "cancelled"
            action.dismissal_reason = "covered_by_new_order"
            action.row_version = int(action.row_version) + 1
            action.updated_at = now
    if window.work_item_id is not None:
        item = db.get(CustomerWorkItem, int(window.work_item_id))
        if item is not None and item.state in _OPEN_ITEM_STATES:
            item.state = "cancelled"
            item.row_version = int(item.row_version) + 1
            item.updated_at = now


def _sample_refs(days: list[date]) -> list[dict]:
    refs = []
    for index, day in enumerate(days):
        refs.append(
            {
                "batch_key": _batch_key(day),
                "business_date": day.isoformat(),
                "interval_from_previous_days": (
                    (day - days[index - 1]).days if index else None
                ),
            }
        )
    return refs


def _upsert_window(
    db: Session,
    *,
    customer_id: int,
    family: str,
    days: list[date],
    mapping_version: str,
    now,
) -> tuple[ReorderWindow, bool]:
    """以末批次为 anchor upsert 窗口；返回 (窗口, 是否新建)。已有窗口保持 open。"""
    intervals = [(later - earlier).days for earlier, later in zip(days, days[1:])]
    median_days = _median_days(intervals)
    exact_median = Decimal(str(median(intervals)))
    spread = Decimal(max(intervals) - min(intervals))
    confidence = (
        "irregular"
        if exact_median > 0 and spread / exact_median > IRREGULAR_RANGE_RATIO
        else "regular"
    )
    anchor_date = days[-1]
    anchor_key = _batch_key(anchor_date)
    occurrence_key = f"reorder:{customer_id}:{family}:{anchor_key}"
    window_from = anchor_date + timedelta(days=median_days - WINDOW_MARGIN_DAYS)
    window_to = anchor_date + timedelta(days=median_days + WINDOW_MARGIN_DAYS)
    sample_refs = _sample_refs(days)

    window = (
        db.query(ReorderWindow)
        .filter(ReorderWindow.occurrence_key == occurrence_key)
        .one_or_none()
    )
    if window is None:
        window = ReorderWindow(
            customer_id=customer_id,
            product_family=family,
            anchor_batch_key=anchor_key,
            occurrence_key=occurrence_key,
            metric_version=mapping_version,
            sample_refs_json=sample_refs,
            median_interval_days=median_days,
            window_from=window_from,
            window_to=window_to,
            confidence=confidence,
            state="open",
        )
        db.add(window)
        db.flush()
        return window, True
    window.sample_refs_json = sample_refs
    window.median_interval_days = median_days
    window.window_from = window_from
    window.window_to = window_to
    window.confidence = confidence
    window.metric_version = mapping_version
    window.updated_at = now
    # covered/superseded/closed 是终态：同锚点重算只更新口径字段，不复活窗口
    db.flush()
    return window, False


def _compute_customer_windows(
    db: Session, *, customer_id: int, mapping_version: str, now
) -> dict:
    """单客户复购窗口计算；调用方负责 savepoint 与异常隔离。"""
    counters = {"windows_opened": 0, "windows_covered": 0, "windows_superseded": 0, "skipped": 0}
    orders = _logical_orders(db, customer_id)
    items_map = _items_by_order(db, [int(o.id) for o in orders])
    eligible, _excluded = _classify_population(orders, items_map)
    _ensure_batch_maps(db, eligible=eligible, mapping_version=mapping_version)
    dates_by_family = _commercial_batch_dates(eligible)

    open_windows = (
        db.query(ReorderWindow)
        .filter(
            ReorderWindow.customer_id == customer_id,
            ReorderWindow.state == "open",
        )
        .order_by(ReorderWindow.id.asc())
        .all()
    )
    open_by_family: dict[str, list[ReorderWindow]] = {}
    for window in open_windows:
        open_by_family.setdefault(window.product_family, []).append(window)

    for family in sorted(set(dates_by_family) | set(open_by_family)):
        days = dates_by_family.get(family, [])
        anchor_key = _batch_key(days[-1]) if days else None
        for window in open_by_family.get(family, []):
            if anchor_key is not None and window.anchor_batch_key == anchor_key:
                continue  # 同一锚点：走 upsert 更新，不是覆盖
            window_anchor_date = _batch_key_date(window.anchor_batch_key)
            newer = [
                day
                for day in days
                if window_anchor_date is None or day > window_anchor_date
            ]
            if not newer:
                continue
            if any(window.window_from <= day <= window.window_to for day in newer):
                # 新批次落在窗口内：被新单覆盖，取消旧窗口行动与事项
                window.state = "covered"
                window.updated_at = now
                _cancel_window_action_and_item(db, window, now)
                counters["windows_covered"] += 1
            else:
                # 新批次在窗口外（迟到/提前）：旧锚点被替代，行动清理由日评估统一处理
                window.state = "superseded"
                window.updated_at = now
                counters["windows_superseded"] += 1
        if len(days) >= MIN_BATCHES_FOR_WINDOW:
            _window, created = _upsert_window(
                db,
                customer_id=customer_id,
                family=family,
                days=days,
                mapping_version=mapping_version,
                now=now,
            )
            if created:
                counters["windows_opened"] += 1
        elif days:
            counters["skipped"] += 1  # 样本不足：不开窗
    return counters


def compute_reorder_windows(
    db: Session, *, customer_id: int | None = None, mapping_version: str = DEFAULT_MAPPING_VERSION
) -> dict:
    """计算/重放商业采购批次映射与复购窗口（确定性，可重复执行）。

    customer_id 为空时处理全部有订单的客户（按逻辑客户归并）；逐客户 savepoint
    隔离，单客户失败计入 failures 并继续，异常不无声吞。
    """
    if not mapping_version or not str(mapping_version).strip():
        raise pcw_errors.bad_request(
            "mapping_version 必填", error_code="MAPPING_VERSION_INVALID"
        )
    mapping_version = str(mapping_version).strip()
    now = beijing_now()

    if customer_id is not None:
        canonical = resolve_canonical_customer_id(db, customer_id)
        if canonical is None:
            raise pcw_errors.customer_not_found()
        customer_ids = [canonical]
    else:
        storage_ids = [
            int(row.customer_id)
            for row in db.query(CustomerOrder.customer_id).distinct().all()
        ]
        seen: set[int] = set()
        customer_ids = []
        for storage_id in sorted(storage_ids):
            canonical = resolve_canonical_customer_id(db, storage_id)
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            customer_ids.append(canonical)

    totals = {
        "customers_processed": 0,
        "windows_opened": 0,
        "windows_covered": 0,
        "windows_superseded": 0,
        "skipped": 0,
        "mapping_version": mapping_version,
        "failures": [],
    }
    for cid in customer_ids:
        try:
            with db.begin_nested():
                counters = _compute_customer_windows(
                    db, customer_id=cid, mapping_version=mapping_version, now=now
                )
        except Exception as exc:  # savepoint 已回滚本客户写入；记录并继续
            logger.warning(
                "compute_reorder_windows 客户 %s 失败: %s", cid, exc, exc_info=True
            )
            print(
                f"compute_reorder_windows customer {cid} failed: {exc!r}", flush=True
            )
            totals["failures"].append(
                {"customer_id": cid, "error": exc.__class__.__name__}
            )
            continue
        totals["customers_processed"] += 1
        for key in ("windows_opened", "windows_covered", "windows_superseded", "skipped"):
            totals[key] += counters[key]
    return totals


def get_reorder_windows(
    db: Session,
    *,
    customer_id: int,
    actor_user_id: int,
    state: str | None = None,
) -> dict:
    """客户复购窗口只读列表；不得借 GET 生成任务，本函数无任何写操作。"""
    canonical_id = _access_customer(
        db, customer_id=customer_id, actor_user_id=actor_user_id
    )
    if state is not None and state not in {"open", "covered", "superseded", "closed"}:
        raise pcw_errors.bad_request(
            "state 不合法",
            error_code="WINDOW_STATE_INVALID",
            details={"allowed": ["open", "covered", "superseded", "closed"]},
        )
    query = db.query(ReorderWindow).filter(
        ReorderWindow.customer_id == canonical_id
    )
    if state is not None:
        query = query.filter(ReorderWindow.state == state)
    windows = query.order_by(ReorderWindow.id.asc()).all()
    return {
        "items": [
            {
                "id": int(window.id),
                "product_family": window.product_family,
                "anchor_batch_key": window.anchor_batch_key,
                "occurrence_key": window.occurrence_key,
                "sample_refs": list(window.sample_refs_json or []),
                "median_interval_days": window.median_interval_days,
                "window_from": window.window_from.isoformat() if window.window_from else None,
                "window_to": window.window_to.isoformat() if window.window_to else None,
                "confidence": window.confidence,
                "state": window.state,
                "action_id": int(window.action_id) if window.action_id is not None else None,
                "work_item_id": (
                    int(window.work_item_id) if window.work_item_id is not None else None
                ),
                "metric_version": window.metric_version,
                "created_at": _iso_bj(window.created_at),
                "updated_at": _iso_bj(window.updated_at),
            }
            for window in windows
        ],
        "total": len(windows),
    }


def on_order_projected(db: Session, order_id: int) -> None:
    """订单投影后的重算入口：供 projection_okki_order / 测试在同事务调用。

    解析订单当前逻辑客户后重算该客户窗口。接线建议：在
    projection_okki_order._project_okki_order 成功返回 ProjectionReceipt 后
    调用 ``on_order_projected(db, receipt.order_id)``（本任务按边界要求未改动
    投影层，避免与其他代理的并行修改冲突）。
    """
    order = db.get(CustomerOrder, order_id)
    if order is None:
        raise pcw_errors.not_found("订单不存在", error_code="ORDER_NOT_FOUND")
    canonical = resolve_canonical_customer_id(db, int(order.customer_id))
    if canonical is None:
        logger.warning(
            "on_order_projected: 订单 %s 的存储客户 %s 无法解析为有效逻辑客户，跳过窗口重算",
            order_id,
            order.customer_id,
        )
        print(
            f"on_order_projected: order {order_id} customer {order.customer_id} "
            "not resolvable, window recompute skipped",
            flush=True,
        )
        return
    compute_reorder_windows(db, customer_id=canonical)


__all__ = [
    "DEFAULT_MAPPING_VERSION",
    "METRIC_VERSION",
    "UNKNOWN_BUCKET",
    "compute_reorder_windows",
    "derive_order_type",
    "get_order_analytics",
    "get_order_detail",
    "get_reorder_windows",
    "list_customer_orders",
    "on_order_projected",
]
