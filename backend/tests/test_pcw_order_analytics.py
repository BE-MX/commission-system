"""PCW-04 订单统计与可解释复购窗口契约测试。

口径见 backend/app/customer/pcw_order_service.py 模块 docstring；
设计依据 docs/requirements/private-customer-workbench-prototype/ 的
development-spec.md PCW-04、api-contracts.md §3/§5、product-plan.md §7。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.models import (
    CustomerAction,
    CustomerAssignment,
    CustomerOrder,
    CustomerOrderItem,
)
from app.customer.pcw_models import (
    CustomerWorkItem,
    OrderAnalysisBatchMap,
    ReorderWindow,
)
from app.customer.pcw_order_service import (
    UNKNOWN_BUCKET,
    compute_reorder_windows,
    get_order_analytics,
    get_order_detail,
    get_reorder_windows,
    list_customer_orders,
    on_order_projected,
)
from app.customer.pcw_workitem_service import create_pcw_action, ensure_work_item
from tests.test_customer_workflow import (
    _account,
    _grant_permission,
    _source_record,
    _user,
)

NOW = beijing_now().replace(microsecond=0)

STATUS_ENDED = "13972831656"  # 小满已结束：有效商业订单
STATUS_TERMINATED = "13972831654"  # 小满已终止（未结清）：按 cancelled 归类
STATUS_IN_PROGRESS = "999"  # 其他状态：无效单

FAMILY = "hair_bundle"


def _actor(db, account, user_id: int):
    """有 customer:read 权限且为客户当前主负责人的业务员。"""
    user = _user(db, user_id)
    _grant_permission(db, user_id, "customer:read")
    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=user.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=user.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    return user


def _item(db, order, source, *, seq, family=FAMILY, model="M1", color="1B",
          length="20inch", quantity=Decimal("10"), unit="pcs",
          price=Decimal("10.0000"), line_amount=Decimal("100.00"),
          item_type="bulk"):
    row = CustomerOrderItem(
        order_id=order.id,
        external_item_id=f"IT-{seq}",
        product_name=f"Product {seq}",
        product_family=family,
        model=model,
        color=color,
        length=length,
        quantity=quantity,
        quantity_unit=unit,
        unit_price=price,
        line_amount=line_amount,
        item_type=item_type,
        source_record_id=source.id,
        item_fingerprint=f"{seq:064x}",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _order(db, account, *, seq, order_date, status=STATUS_ENDED, valid=True,
           currency="USD", amount=Decimal("100.00"), usd=Decimal("100.00"),
           items=()):
    source = _source_record(db, account, record_id=seq)
    order = CustomerOrder(
        customer_id=account.id,
        source_system="okki",
        source_account_key="tenant-a",
        external_order_id=f"ORD-{seq}",
        order_no=f"NO-{seq}",
        order_name=f"Order {seq}",
        order_status=status,
        account_date=order_date,
        currency=currency,
        amount_original=amount,
        amount_usd=usd,
        is_valid_business_order=valid,
        invalid_reason=None if valid else "not_effective_business_order",
        source_record_id=source.id,
        source_hash=f"{seq + 7:064x}",
        synced_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(order)
    db.flush()
    for index, item_kwargs in enumerate(items):
        _item(db, order, source, seq=seq * 100 + index, **item_kwargs)
    return order


def _buckets_by(result, *keys):
    return {
        tuple(bucket[key] for key in ("value", *keys)): bucket
        for bucket in result["buckets"]
    }


# ---------------------------------------------------------------------------
# A/B. 订单列表与明细
# ---------------------------------------------------------------------------


def test_list_orders_classification_filters_and_amount_quality(db):
    account, _version = _account(db, code="C-PCW-O1")
    actor = _actor(db, account, 9701)
    bulk = _order(db, account, seq=101, order_date=date(2026, 8, 1),
                  items=[{"color": "1B"}])
    sample = _order(db, account, seq=102, order_date=date(2026, 8, 5),
                    items=[{"item_type": "sample", "color": "2"}])
    mixed = _order(db, account, seq=103, order_date=date(2026, 8, 10),
                   items=[{"color": "1B"}, {"item_type": "sample", "color": "4"}])
    unknown = _order(db, account, seq=104, order_date=date(2026, 8, 15),
                     items=[{"item_type": "unknown"}])
    no_amount = _order(db, account, seq=105, order_date=date(2026, 8, 20),
                       amount=None, usd=Decimal("0"), items=[{"color": "6"}])

    result = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id,
    )
    assert result["total"] == 5
    assert result["page"] == 1 and result["page_size"] == 20
    by_no = {row["order_no"]: row for row in result["items"]}
    assert by_no["NO-101"]["order_type"] == "bulk"
    assert by_no["NO-102"]["order_type"] == "sample"
    assert by_no["NO-103"]["order_type"] == "mixed"
    assert by_no["NO-104"]["order_type"] == "unknown"
    # 默认按业务日期倒序
    assert [row["order_no"] for row in result["items"]] == [
        "NO-105", "NO-104", "NO-103", "NO-102", "NO-101",
    ]
    row = by_no["NO-101"]
    assert row["effective_date"] == "2026-08-01"
    assert row["amount"] == "100.00"
    assert row["amount_reason"] is None
    assert row["currency"] == "USD"
    assert row["standard_amount_usd"] == "100.00"
    assert row["standard_amount_quality"] == "projected"
    assert row["item_count"] == 1
    assert row["source"] == "okki"
    assert row["synced_at"].endswith("+08:00")
    # 金额未知：None + reason，不置零；美元值不可验证
    unknown_amount = by_no["NO-105"]
    assert unknown_amount["amount"] is None
    assert unknown_amount["amount_reason"] == "missing_original_amount"
    assert unknown_amount["standard_amount_usd"] is None
    assert unknown_amount["standard_amount_quality"] == "unavailable"

    only_sample = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id, order_type="sample",
    )
    assert [row["id"] for row in only_sample["items"]] == [sample.id]

    by_status = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id, status=STATUS_ENDED,
    )
    assert by_status["total"] == 5

    by_family = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id, product_family=FAMILY,
    )
    assert by_family["total"] == 5  # 全部订单的明细都属于该产品族
    other_family = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id, product_family="hair_wig",
    )
    assert other_family["total"] == 0

    by_date = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id,
        date_from="2026-08-05", date_to=date(2026, 8, 15),
    )
    assert by_date["total"] == 3

    page1 = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id, page=1, page_size=2,
    )
    page3 = list_customer_orders(
        db, customer_id=account.id, actor_user_id=actor.id, page=3, page_size=2,
    )
    assert page1["total"] == 5 and len(page1["items"]) == 2
    assert len(page3["items"]) == 1
    assert bulk.id != mixed.id  # 静默引用检查，防误用夹具


def test_order_detail_items_and_cross_customer_404(db):
    account, _version = _account(db, code="C-PCW-O2")
    other, _v2 = _account(db, code="C-PCW-O3")
    actor = _actor(db, account, 9702)
    other_actor = _actor(db, other, 9703)
    order = _order(db, account, seq=201, order_date=date(2026, 8, 1),
                   items=[
                       {"color": "1B", "quantity": Decimal("10"), "unit": "pcs"},
                       {"color": "4", "quantity": Decimal("2.5000"), "unit": "kg",
                        "line_amount": Decimal("55.50"), "length": "14inch"},
                   ])
    detail = get_order_detail(
        db, customer_id=account.id, order_id=order.id, actor_user_id=actor.id,
    )
    assert detail["order_no"] == "NO-201"
    assert len(detail["items"]) == 2
    second = detail["items"][1]
    assert second["product_family"] == FAMILY
    assert second["color"] == "4"
    assert second["length"] == "14inch"
    assert second["quantity"] == "2.5000"
    assert second["quantity_unit"] == "kg"
    assert second["line_amount"] == "55.50"
    assert second["currency"] == "USD"
    assert detail["source_account_key"] == "tenant-a"
    assert detail["synced_at"].endswith("+08:00")

    # 跨客户：订单不属于该逻辑客户 → 404，不泄漏存在性
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        get_order_detail(
            db, customer_id=other.id, order_id=order.id, actor_user_id=other_actor.id,
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.error_code == "CUSTOMER_NOT_FOUND_OR_FORBIDDEN"


def test_orders_require_customer_access(db):
    account, _version = _account(db, code="C-PCW-O4")
    order = _order(db, account, seq=301, order_date=date(2026, 8, 1),
                   items=[{}])
    # 无读权限
    no_perm = _user(db, 9704)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        list_customer_orders(db, customer_id=account.id, actor_user_id=no_perm.id)
    assert excinfo.value.error_code == "CUSTOMER_NOT_FOUND_OR_FORBIDDEN"
    # 有读权限但不在客户归属范围
    outsider = _user(db, 9705)
    _grant_permission(db, 9705, "customer:read")
    with pytest.raises(pcw_errors.PcwError):
        list_customer_orders(db, customer_id=account.id, actor_user_id=outsider.id)
    with pytest.raises(pcw_errors.PcwError):
        get_order_analytics(
            db, customer_id=account.id, actor_user_id=outsider.id,
            dimension="color", measure="amount",
        )
    with pytest.raises(pcw_errors.PcwError):
        get_reorder_windows(db, customer_id=account.id, actor_user_id=outsider.id)
    # 客户不存在
    actor_owner = _actor(db, account, 9706)
    with pytest.raises(pcw_errors.PcwError):
        list_customer_orders(db, customer_id=999999, actor_user_id=actor_owner.id)
    assert order.id is not None


# ---------------------------------------------------------------------------
# C. 订单统计口径
# ---------------------------------------------------------------------------

ANALYTICS_KEYS = {
    "metric_version", "filters", "amount_basis", "quantity_unit",
    "eligible_order_count", "included_count", "unknown_count",
    "excluded_reasons", "buckets", "cycle_samples", "source_watermarks",
}


def test_amount_buckets_never_mix_currencies(db):
    account, _version = _account(db, code="C-PCW-A1")
    actor = _actor(db, account, 9711)
    _order(db, account, seq=401, order_date=date(2026, 8, 1),
           currency="USD", items=[{"color": "1B", "line_amount": Decimal("100.00")}])
    _order(db, account, seq=402, order_date=date(2026, 8, 10),
           currency="EUR", amount=Decimal("50.00"), usd=Decimal("55.00"),
           items=[{"color": "1B", "line_amount": Decimal("50.00")}])

    result = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="color", measure="amount",
    )
    assert ANALYTICS_KEYS <= set(result)
    assert result["metric_version"] == "order_analytics_v1"
    assert result["amount_basis"] == "original_currency"
    assert result["quantity_unit"] is None
    assert result["eligible_order_count"] == 2
    assert result["included_count"] == 2
    assert result["unknown_count"] == 0
    buckets = _buckets_by(result, "currency")
    assert buckets[("1B", "USD")]["amount"] == "100.00"
    assert buckets[("1B", "EUR")]["amount"] == "50.00"
    assert len(buckets) == 2  # 绝不跨币种相加

    usd_only = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="color", measure="amount", currency="USD",
    )
    buckets = _buckets_by(usd_only, "currency")
    assert list(buckets) == [("1B", "USD")]
    assert usd_only["filters"]["currency"] == "USD"
    assert usd_only["filters"]["dimension"] == "color"
    # 统一美元指标在数据不可逐单验证时不返回该键
    assert "standard_amount_usd" not in result
    assert "total_usd" not in result


def test_quantity_buckets_never_mix_units(db):
    account, _version = _account(db, code="C-PCW-A2")
    actor = _actor(db, account, 9712)
    _order(db, account, seq=411, order_date=date(2026, 8, 1),
           items=[{"color": "1B", "quantity": Decimal("10"), "unit": "pcs"}])
    _order(db, account, seq=412, order_date=date(2026, 8, 10),
           items=[{"color": "1B", "quantity": Decimal("2.5000"), "unit": "kg"}])

    result = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="color", measure="quantity",
    )
    assert result["amount_basis"] is None
    assert result["quantity_unit"] is None
    buckets = _buckets_by(result, "unit")
    assert buckets[("1B", "pcs")]["quantity"] == "10.0000"
    assert buckets[("1B", "kg")]["quantity"] == "2.5000"
    assert len(buckets) == 2  # pcs 与 kg 不混加

    pcs_only = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="color", measure="quantity", unit="pcs",
    )
    assert pcs_only["quantity_unit"] == "pcs"
    assert list(_buckets_by(pcs_only, "unit")) == [("1B", "pcs")]


def test_unknown_color_bucketed_and_counted(db):
    account, _version = _account(db, code="C-PCW-A3")
    actor = _actor(db, account, 9713)
    _order(db, account, seq=421, order_date=date(2026, 8, 1),
           items=[
               {"color": None, "line_amount": Decimal("80.00")},  # 未知颜色入（未知）桶
               {"color": "1B", "line_amount": None},  # 缺金额：不入桶但计 unknown
           ])

    result = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="color", measure="amount",
    )
    assert result["unknown_count"] == 2
    buckets = _buckets_by(result, "currency")
    assert buckets[(UNKNOWN_BUCKET, "USD")]["amount"] == "80.00"
    assert len(buckets) == 1
    # 缺金额行不计入 included
    assert result["included_count"] == 1


def test_order_coverage_crosses_and_denominator(db):
    account, _version = _account(db, code="C-PCW-A4")
    actor = _actor(db, account, 9714)
    _order(db, account, seq=431, order_date=date(2026, 8, 1),
           items=[{"color": "1B"}, {"color": "4"}])  # 一单含两色
    _order(db, account, seq=432, order_date=date(2026, 8, 10),
           items=[{"color": "1B"}])
    _order(db, account, seq=433, order_date=date(2026, 8, 20),
           items=[{"color": None}])  # 无已知颜色 →（未知）桶
    _order(db, account, seq=434, order_date=date(2026, 8, 25),
           items=[{"item_type": "sample", "color": "1B"}])  # 样品单不进有效分母

    result = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="color", measure="order_coverage",
    )
    assert result["eligible_order_count"] == 3
    assert result["included_count"] == 3
    assert result["unknown_count"] == 1
    assert result["excluded_reasons"]["sample"] == 1
    buckets = {bucket["value"]: bucket for bucket in result["buckets"]}
    assert buckets["1B"]["order_count"] == 2
    assert buckets["1B"]["coverage_pct"] == "66.67"
    assert buckets["4"]["coverage_pct"] == "33.33"
    assert buckets[UNKNOWN_BUCKET]["order_count"] == 1
    # 可交叉：合计允许超过 100%
    total_pct = sum(Decimal(b["coverage_pct"]) for b in result["buckets"])
    assert total_pct > Decimal("100")


def test_excluded_reasons_classification(db):
    account, _version = _account(db, code="C-PCW-A5")
    actor = _actor(db, account, 9715)
    _order(db, account, seq=441, order_date=date(2026, 8, 1),
           items=[{"color": "1B", "line_amount": Decimal("5.00")}])
    _order(db, account, seq=442, order_date=date(2026, 8, 2),
           status=STATUS_TERMINATED, valid=False, items=[{"color": "1B"}])
    _order(db, account, seq=443, order_date=date(2026, 8, 3),
           status=STATUS_IN_PROGRESS, valid=False, items=[{"color": "1B"}])
    _order(db, account, seq=444, order_date=date(2026, 8, 4),
           items=[{"item_type": "sample", "color": "1B"}])
    _order(db, account, seq=445, order_date=date(2026, 8, 5), items=[])  # 无明细→unknown
    # 混合单：商业行计入，样品行不混算
    _order(db, account, seq=446, order_date=date(2026, 8, 6),
           items=[
               {"color": "1B", "line_amount": Decimal("10.00")},
               {"item_type": "sample", "color": "4", "line_amount": Decimal("999.00")},
           ])

    result = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="color", measure="amount",
    )
    assert result["excluded_reasons"] == {
        "cancelled": 1, "invalid": 1, "sample": 1, "unknown_type": 1,
    }
    assert result["eligible_order_count"] == 2  # bulk + mixed
    buckets = _buckets_by(result, "currency")
    assert buckets[("1B", "USD")]["amount"] == "15.00"  # 5.00 + 混合单商业行 10.00
    assert len(buckets) == 1  # 样品行 999.00 不混算


def test_analytics_cycle_samples_and_watermark_unknown(db):
    account, _version = _account(db, code="C-PCW-A6")
    actor = _actor(db, account, 9716)
    for index, day in enumerate(
        [date(2026, 6, 1), date(2026, 6, 29), date(2026, 7, 31), date(2026, 8, 30)]
    ):
        _order(db, account, seq=451 + index, order_date=day, items=[{}])

    result = get_order_analytics(
        db, customer_id=account.id, actor_user_id=actor.id,
        dimension="product_family", measure="amount",
    )
    samples = {row["product_family"]: row for row in result["cycle_samples"]}
    assert samples[FAMILY]["interval_days"] == [28, 32, 30]
    assert samples[FAMILY]["median_interval_days"] == 30
    assert samples[FAMILY]["batch_count"] == 4
    # 有订单投影记录 → 水位取订单最近同步时间
    watermark = result["source_watermarks"][-1]
    assert watermark["basis"] == "customer_order_projection"
    assert watermark["status"] == "fresh"
    assert watermark["synced_through"].endswith("+08:00")

    # 无订单客户：水位 unknown 并注明，不伪造
    empty, _ve = _account(db, code="C-PCW-A7")
    empty_actor = _actor(db, empty, 9717)
    empty_result = get_order_analytics(
        db, customer_id=empty.id, actor_user_id=empty_actor.id,
        dimension="color", measure="amount",
    )
    assert empty_result["eligible_order_count"] == 0
    assert empty_result["buckets"] == []
    assert empty_result["cycle_samples"] == []
    assert empty_result["source_watermarks"][-1]["status"] == "unknown"
    assert "note" in empty_result["source_watermarks"][-1]


# ---------------------------------------------------------------------------
# D/E. 复购窗口
# ---------------------------------------------------------------------------

def _four_batch_customer(db, code, user_id, *, split_last_day=False):
    """[28,32,30] 间隔的四批次客户；split_last_day 追加同日拆单验证归并去重。"""
    account, _version = _account(db, code=code)
    actor = _actor(db, account, user_id)
    days = [date(2026, 6, 1), date(2026, 6, 29), date(2026, 7, 31), date(2026, 8, 30)]
    for index, day in enumerate(days):
        _order(db, account, seq=500 + index, order_date=day, items=[{}])
    if split_last_day:
        _order(db, account, seq=599, order_date=days[-1], items=[{}])
    return account, actor, days


def test_reorder_window_regular_median_and_same_day_merge(db):
    account, actor, days = _four_batch_customer(
        db, "C-PCW-R1", 9721, split_last_day=True,
    )
    result = compute_reorder_windows(db, customer_id=account.id)
    assert result["customers_processed"] == 1
    assert result["windows_opened"] == 1
    assert result["windows_covered"] == 0
    assert result["skipped"] == 0
    assert result["failures"] == []

    # 同日拆单归并：5 张单 → 4 个批次、5 条明细映射（低置信同日归并口径）
    maps = db.query(OrderAnalysisBatchMap).all()
    assert len(maps) == 5
    assert {row.purchase_batch_key for row in maps} == {
        f"day:{day.isoformat()}" for day in days
    }
    assert all(row.provenance == "same_day_merge" for row in maps)
    assert all(row.quality_status == "low_confidence" for row in maps)
    assert all(row.mapping_version == "commercial_cycle_v1" for row in maps)

    window = db.query(ReorderWindow).one()
    assert window.product_family == FAMILY
    assert window.anchor_batch_key == "day:2026-08-30"
    assert window.occurrence_key == f"reorder:{account.id}:{FAMILY}:day:2026-08-30"
    assert window.median_interval_days == 30
    assert window.confidence == "regular"  # 极差 4 / 中位 30 ≤ 0.6
    assert window.state == "open"
    assert window.window_from == date(2026, 9, 22)  # 末批 + 30 - 7
    assert window.window_to == date(2026, 10, 6)  # 末批 + 30 + 7
    refs = window.sample_refs_json
    assert [ref["interval_from_previous_days"] for ref in refs] == [None, 28, 32, 30]
    assert window.metric_version == "commercial_cycle_v1"

    windows = get_reorder_windows(
        db, customer_id=account.id, actor_user_id=actor.id,
    )
    assert windows["total"] == 1
    entry = windows["items"][0]
    assert entry["window_from"] == "2026-09-22"
    assert entry["window_to"] == "2026-10-06"
    assert entry["confidence"] == "regular"
    assert entry["metric_version"] == "commercial_cycle_v1"
    assert len(entry["sample_refs"]) == 4
    open_only = get_reorder_windows(
        db, customer_id=account.id, actor_user_id=actor.id, state="open",
    )
    assert open_only["total"] == 1
    covered = get_reorder_windows(
        db, customer_id=account.id, actor_user_id=actor.id, state="covered",
    )
    assert covered["total"] == 0


def test_reorder_window_irregular_when_spread_exceeds_ratio(db):
    account, _version = _account(db, code="C-PCW-R2")
    _actor(db, account, 9722)
    days = [date(2026, 1, 1)]
    for interval in [10, 40, 15, 50]:
        days.append(days[-1] + timedelta(days=interval))
    for index, day in enumerate(days):
        _order(db, account, seq=510 + index, order_date=day, items=[{}])

    result = compute_reorder_windows(db, customer_id=account.id)
    assert result["windows_opened"] == 1
    window = db.query(ReorderWindow).one()
    # 间隔 [10,40,15,50]，极差 40 / 中位 27.5 > 0.6 → irregular（降级提示核验）
    assert window.confidence == "irregular"
    assert window.median_interval_days == 28  # 27.5 四舍五入到天
    assert window.state == "open"


def test_insufficient_batches_do_not_open_window(db):
    account, _version = _account(db, code="C-PCW-R3")
    _actor(db, account, 9723)
    for index, day in enumerate(
        [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
    ):
        _order(db, account, seq=520 + index, order_date=day, items=[{}])

    result = compute_reorder_windows(db, customer_id=account.id)
    assert result["customers_processed"] == 1
    assert result["windows_opened"] == 0
    assert result["skipped"] == 1  # 3 批次（2 间隔）样本不足：不开窗
    assert db.query(ReorderWindow).count() == 0
    # 批次映射仍然落库（口径留痕），只是不开窗
    assert db.query(OrderAnalysisBatchMap).count() == 3


def test_new_order_in_window_covers_old_and_cancels_action(db):
    account, actor, _days = _four_batch_customer(db, "C-PCW-R4", 9724)
    compute_reorder_windows(db, customer_id=account.id)
    window = db.query(ReorderWindow).one()

    # 模拟日评估已生成窗口行动与事项
    item = ensure_work_item(
        db, customer_id=account.id,
        business_key=f"reorder:{account.id}:{FAMILY}",
        business_cycle=window.occurrence_key,
        work_type="reorder", title="复购窗口跟进",
    )
    action = create_pcw_action(
        db, work_item=item, owner_user_id=actor.id,
        action_type="message", thread_group="reorder", priority="high",
        reason="复购窗口开启", next_action="询问采购计划",
    )
    window.work_item_id = item.id
    window.action_id = action.id
    db.flush()

    # 新商业订单落入窗口（2026-10-01 ∈ [09-22, 10-06]）：经投影钩子重算
    covering = _order(db, account, seq=530, order_date=date(2026, 10, 1), items=[{}])
    result = on_order_projected(db, covering.id)
    assert result is None

    db.flush()
    old_window = db.query(ReorderWindow).filter(
        ReorderWindow.id == window.id
    ).one()
    assert old_window.state == "covered"
    assert db.get(CustomerAction, action.id).status == "cancelled"
    assert db.get(CustomerAction, action.id).dismissal_reason == "covered_by_new_order"
    assert db.get(CustomerWorkItem, item.id).state == "cancelled"

    new_window = db.query(ReorderWindow).filter(
        ReorderWindow.state == "open"
    ).one()
    assert new_window.id != old_window.id
    assert new_window.anchor_batch_key == "day:2026-10-01"
    # 新间隔样本 [28,32,30,32]，中位 31
    assert new_window.median_interval_days == 31
    assert new_window.window_from == date(2026, 10, 25)
    assert new_window.window_to == date(2026, 11, 8)

    windows = get_reorder_windows(
        db, customer_id=account.id, actor_user_id=actor.id, state="covered",
    )
    assert windows["total"] == 1
    assert windows["items"][0]["action_id"] == action.id


def test_sample_cancelled_and_unrelated_orders_do_not_close_window(db):
    account, actor, _days = _four_batch_customer(db, "C-PCW-R5", 9725)
    compute_reorder_windows(db, customer_id=account.id)
    window = db.query(ReorderWindow).one()

    # 样单 / 取消单 / 无关产品族新单（均落在窗口期内）不得关闭旧窗口
    _order(db, account, seq=540, order_date=date(2026, 9, 25),
           items=[{"item_type": "sample"}])
    _order(db, account, seq=541, order_date=date(2026, 9, 26),
           status=STATUS_TERMINATED, valid=False, items=[{}])
    _order(db, account, seq=542, order_date=date(2026, 9, 27),
           items=[{"family": "hair_wig"}])
    result = compute_reorder_windows(db, customer_id=account.id)

    db.flush()
    assert db.get(ReorderWindow, window.id).state == "open"
    assert result["windows_covered"] == 0
    # 新产品族只有 1 批次：样本不足计入 skipped，不开窗
    assert result["skipped"] == 1
    assert db.query(ReorderWindow).count() == 1


def test_compute_reorder_windows_replay_is_idempotent(db):
    account, _actor, _days = _four_batch_customer(db, "C-PCW-R6", 9726)
    first = compute_reorder_windows(db, customer_id=account.id)
    assert first["windows_opened"] == 1
    map_count = db.query(OrderAnalysisBatchMap).count()
    window_count = db.query(ReorderWindow).count()

    second = compute_reorder_windows(db, customer_id=account.id)
    assert second["customers_processed"] == 1
    assert second["windows_opened"] == 0  # 同 occurrence_key 更新，不重复建
    assert second["windows_covered"] == 0
    assert db.query(OrderAnalysisBatchMap).count() == map_count
    assert db.query(ReorderWindow).count() == window_count
    window = db.query(ReorderWindow).one()
    assert window.state == "open"
    assert window.median_interval_days == 30

    # 全量入口（customer_id=None）同样幂等且按逻辑客户归并
    third = compute_reorder_windows(db)
    assert third["windows_opened"] == 0
    assert db.query(ReorderWindow).count() == window_count
