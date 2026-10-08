"""Decision facts: independently seeded SQLite data, no shared database writes."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.domestic.models import DomesticCustomer, DomesticProduct, DomesticOrder, DomesticOrderItem
from app.domestic_decision.models import DecisionConfig, DecisionMapping
from app.domestic_decision.schemas import AnalysisRequest
from app.domestic_decision.scope import live_actor
from app.domestic_decision.analytics import build_analysis, filter_options
from app.domestic_decision.profiles import customer_profile, salesperson_profile


@pytest.fixture
def dd_seed(db):
    users = [ArkUser(username=f"dd_{i}", real_name=f"Owner {i}", password_hash="unused", is_active=True) for i in (1, 2)]
    db.add_all(users)
    db.flush()
    role = ArkRole(name="dd_sales", label="Sales")
    db.add(role)
    db.flush()
    db.add_all([ArkUserRole(user_id=r.id, role_id=role.id) for r in users])
    permission_ids = {}
    def grant(code):
        if code not in permission_ids:
            permission = ArkPermission(code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
            db.add(permission)
            db.flush()
            db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
            permission_ids[code] = permission.id
            db.flush()
    grant("domestic_decision:read")
    customers = [DomesticCustomer(shop_name=f"DD Store {i}", owner_user_id=users[i - 1].id, created_by=users[i - 1].id, balance=0, settle_mode="prepay", total_sales_amount=100000 if i == 1 else None) for i in (1, 2)]
    db.add_all(customers)
    product = DomesticProduct(attrs_key="dd_lace", name="Current changed product", product_type="cap", craft="CURRENT_ONLY", length="35厘米")
    db.add(product)
    db.flush()
    sequence = [0]
    def order(day=date(2026, 9, 10), total=4400, customer=None, status=1, deleted=0, order_type=None, kind="business", channel="online"):
        sequence[0] += 1
        customer = customer or customers[0]
        row = DomesticOrder(domestic_no=f"DD{sequence[0]}", order_no=f"DD{sequence[0]}", order_kind=kind, customer_id=customer.id, order_date=day, order_category="normal" if kind == "business" else None, status=status, total_amount=total if kind == "business" else 0, deleted_flag=deleted, order_type=order_type, order_channel=channel if kind == "business" else None, created_by=users[1].id)
        db.add(row)
        db.flush()
        return row
    def item(order, qty=1, price=1000, color="black", attrs=None, original=None):
        count = db.query(DomesticOrderItem).filter_by(order_id=order.id).count()
        row = DomesticOrderItem(order_id=order.id, line_no=count + 1, product_id=product.id, product_name="Historical lace", attrs_snapshot=attrs if attrs is not None else {"product_type": "cap", "craft": "lace", "length": "15厘米", "density": "120", "size": "M", "net_color": "brown", "hair_style_series": "straight"}, order_qty=qty, unit_price=price, original_price=original if original is not None else max(price, 1000), discount_amount=0, labor_fee=100, pricing_rule="legacy_manual", pricing_version="legacy-v1", base_price_version_snapshot=0, color=color)
        db.add(row)
        db.flush()
        return row
    def request(**kwargs):
        values = {"start_date": "2026-09-01", "end_date": "2026-09-30", "comparison_mode": "previous"}
        values.update(kwargs)
        return AnalysisRequest(**values)
    return SimpleNamespace(users=users, customers=customers, actor={"id": users[0].id}, grant=grant, role=role, permissions=permission_ids, product=product, order=order, item=item, request=request)


def test_a01_a02_grains_labor_and_snapshot(db, dd_seed):
    s = dd_seed
    order = s.order()
    s.item(order, qty=2, price=1000)
    s.item(order, qty=3, price=800)
    result = build_analysis(db, s.actor, s.request())
    assert result["summary"]["amount"] == 4400
    assert result["summary"]["quantity"] == 5
    assert result["summary"]["order_count"] == 1
    assert result["summary"]["weighted_unit_price"] == 880
    assert result["dimensions"]["craft"][0]["key"] == "lace"
    assert result["customers"][0]["history"]["archival_amount"] == 100000
    assert result["customers"][0]["history"]["system_amount"] == 4400
    assert "finance" not in result
    assert "balance" not in json.dumps(result)
    assert "province" in result["dimensions"] and "order_channel" in result["dimensions"]
    assert "settle_mode" not in result["dimensions"] and "membership_level" not in result["dimensions"]


@pytest.mark.parametrize("status,deleted,kind,expected", [(0, 0, "business", 0), (1, 0, "business", 1), (2, 0, "business", 1), (3, 0, "business", 1), (4, 0, "business", 0), (5, 0, "business", 0), (6, 0, "business", 0), (1, 1, "business", 0), (1, 0, "production", 0)])
def test_a03_valid_commercial_statuses(db, dd_seed, status, deleted, kind, expected):
    row = dd_seed.order(total=1000, status=status, deleted=deleted, kind=kind)
    dd_seed.item(row)
    result = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert result["summary"]["order_count"] == expected


def test_a04_filters_must_match_same_line_and_whole_order_separate(db, dd_seed):
    s = dd_seed
    order = s.order(total=3000)
    s.item(order, price=1000, color="red", attrs={"product_type": "cap", "craft": "lace", "length": "15厘米"})
    s.item(order, price=2000, color="black", attrs={"product_type": "cap", "craft": "silk", "length": "25厘米"})
    result = build_analysis(db, s.actor, s.request(filters={"color": ["red"]}))
    assert result["summary"]["matched_amount"] == 1000
    assert result["summary"]["related_order_amount"] == 3000
    assert build_analysis(db, s.actor, s.request(filters={"color": ["red"], "length": ["25厘米"]}))["summary"]["order_count"] == 0


def test_quantity_bins_keep_matching_lines_and_whole_order_grains(db, dd_seed):
    s = dd_seed
    order = s.order(total=12000)
    red = s.item(order, qty=2, price=1000, color="red")
    s.item(order, qty=10, price=1000, color="black")
    result = build_analysis(db, s.actor, s.request(filters={"color": ["red"]}))
    item_bin = result["quantity_structure"]["item_bands"][0]
    order_bin = result["quantity_structure"]["order_bands"][0]
    assert item_bin["band"] == "2-3" and item_bin["quantity"] == 2 and item_bin["amount"] == 2000
    assert item_bin["evidence_refs"] == [{"type": "items", "id": red.id}]
    assert order_bin["band"] == "11+" and order_bin["whole_quantity"] == 12 and order_bin["matched_quantity"] == 2
    assert order_bin["order_count"] == 1 and order_bin["related_order_amount"] == 12000


def test_a10_a11_not_applicable_unknown_color_mapping(db, dd_seed):
    s = dd_seed
    order = s.order(total=3000)
    s.item(order, attrs={"product_type": "piece", "craft": "U型13*15", "length": "15厘米"}, color="1# + 4#")
    s.item(order, attrs={"product_type": "cap", "craft": "lace", "length": "25厘米"}, color=None)
    s.item(order, attrs={"product_type": "cap", "craft": "lace", "length": "15厘米", "density": "120"}, color="1# + 4#")
    result = build_analysis(db, s.actor, s.request())
    coverage = result["quality"]["dimension_coverage"]["density"]
    assert coverage["applicable_count"] == coverage["known_count"] == 1
    assert coverage["not_applicable_count"] == 2
    assert coverage["quantity_coverage"] == coverage["amount_coverage"] == coverage["rate"] == 1
    assert coverage["strong_advice_enabled"]
    assert any(r["key"] == "未归类：1# + 4#" for r in result["dimensions"]["color"])
    db.add(DecisionMapping(property="color", product_type="", raw_value="1# + 4#", standard_value="混色 1+4", updated_by=s.users[0].id))
    db.flush()
    changed = build_analysis(db, s.actor, s.request())
    assert changed["meta"]["data_version"] != result["meta"]["data_version"]
    assert any(r["key"] == "混色 1+4" for r in changed["dimensions"]["color"])


def test_a13_a14_full_history_dormant_and_filters_do_not_fake_cycle(db, dd_seed):
    s = dd_seed
    for day in [date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 11), date(2026, 6, 21), date(2026, 7, 1)]:
        row = s.order(day, total=1000)
        s.item(row)
    result = build_analysis(db, s.actor, s.request(filters={"color": ["black"]}))
    customer = result["customers"][0]
    assert customer["order_count"] == 0
    assert customer["history"]["purchase_days"] == 4
    assert customer["history"]["commercial_order_count"] == 6
    assert customer["history"]["cycle_days"] == 10
    assert any(r["rule_key"] == "repurchase_due" for r in result["insights"])


def test_a13_insufficient_distinct_dates_never_zero_cycle(db, dd_seed):
    for _ in range(3):
        dd_seed.order(total=1000)
    result = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert result["customers"][0]["history"]["cycle_days"] is None
    assert result["customers"][0]["history"]["purchase_days"] == 1


def test_a15_mature_cohort_only(db, dd_seed):
    dd_seed.order(date(2026, 9, 20), total=1000)
    result = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert result["cohorts"][0]["mature_30d_count"] == 0
    assert result["cohorts"][0]["second_purchase_30d_rate"] is None


def test_a16_a17_live_owner_and_forged_ids(db, dd_seed):
    s = dd_seed
    row = s.order(total=1000)
    s.item(row)
    with pytest.raises(HTTPException) as error:
        build_analysis(db, s.actor, s.request(customer_ids=[s.customers[1].id]))
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        build_analysis(db, s.actor, s.request(owner_ids=[s.users[1].id]))
    with pytest.raises(HTTPException):
        build_analysis(db, {**s.actor, "permissions": ["domestic_decision:read_all"], "roles": ["super_admin"]}, s.request(scope="all"))
    s.customers[0].owner_user_id = s.users[1].id
    db.flush()
    assert build_analysis(db, s.actor, s.request())["meta"]["customer_ids"] == []
    with pytest.raises(HTTPException):
        customer_profile(db, s.actor, s.customers[0].id, s.request())


def test_permission_revocation_and_inactive_actor_are_live(db, dd_seed):
    s = dd_seed
    db.query(ArkRolePermission).filter_by(role_id=s.role.id).delete(synchronize_session=False)
    db.flush()
    with pytest.raises(HTTPException) as error:
        live_actor(db, {**s.actor, "permissions": ["domestic_decision:read"]})
    assert error.value.status_code == 403
    s.users[0].is_active = False
    db.flush()
    with pytest.raises(HTTPException) as error:
        live_actor(db, s.actor)
    assert error.value.status_code == 401


def test_a19_zero_base_no_infinity_unknown_history_no_fake_zero(db, dd_seed):
    row = dd_seed.order(total=1000)
    dd_seed.item(row)
    result = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert result["comparison"]["changes"]["amount"]["rate"] is None
    assert result["trend"][0]["amount"] is None
    assert result["trend"][0]["coverage"] == "unconfirmed"


def test_a20_a29_data_version_detects_edits_and_reconciliation(db, dd_seed):
    row = dd_seed.order(total=1000)
    line = dd_seed.item(row)
    first = build_analysis(db, dd_seed.actor, dd_seed.request())
    line.unit_price = 900
    db.flush()
    second = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert first["meta"]["data_version"] != second["meta"]["data_version"]
    assert second["quality"]["order_reconciliation"][0]["difference"] == 100
    assert second["summary"]["amount"] == 1000
    assert second["summary"]["matched_amount"] == 900


def test_a27_current_membership_separate_historical_line(db, dd_seed):
    dd_seed.grant("domestic_decision_finance:read")
    row = dd_seed.order(total=1000)
    line = dd_seed.item(row)
    line.membership_level_snapshot = "silver"
    dd_seed.customers[0].membership_level = "supreme"
    db.flush()
    result = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert result["customers"][0]["membership_level"] == "supreme"
    assert result["evidence"]["items"][0]["membership_level_snapshot"] == "silver"
    assert result["evidence"]["items"][0]["unit_price"] == 1000


def test_filters_scope_and_profile_current_portfolio(db, dd_seed):
    s = dd_seed
    own_order = s.order(total=1000)
    s.item(own_order)
    s.item(s.order(total=1000, customer=s.customers[1]))
    options = filter_options(db, s.actor)
    assert [r["value"] for r in options["customers"]] == [s.customers[0].id]
    assert not options["permissions"]["finance"]
    with pytest.raises(HTTPException):
        salesperson_profile(db, s.actor, s.users[1].id, s.request())
    result = salesperson_profile(db, s.actor, s.users[0].id, s.request())
    assert result["attribution_mode"] == "current_owner"
    assert "finance" not in result
    assert [row["id"] for row in result["evidence"]["orders"]] == [own_order.id]
    assert all(row["customer_id"] == s.customers[0].id for row in result["evidence"]["items"])
    assert "charged_amount" not in result["evidence"]["orders"][0]


@pytest.mark.parametrize("changes", [{"team_id": 1}, {"filters": {"balance": ["100"]}}, {"dimensions": ["sql"]}, {"dimensions": ["craft", "craft"]}, {"end_date": "2026-08-01"}, {"start_date": "2020-01-01"}])
def test_query_contract_rejects_arbitrary_or_unbounded_input(dd_seed, changes):
    with pytest.raises(ValidationError):
        dd_seed.request(**changes)


def test_commercial_history_excludes_zero_and_configured_aftersales(db, dd_seed):
    dd_seed.order(total=0)
    dd_seed.order(total=1000, order_type="remake")
    dd_seed.order(total=2000)
    db.add(DecisionConfig(key="aftersales_order_types", value=["remake"]))
    db.flush()
    result = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert result["summary"]["amount"] == 3000
    assert result["summary"]["commercial_amount"] == 2000
    assert result["customers"][0]["history"]["commercial_order_count"] == 1


def test_piece_size_uses_explicit_compound_craft_mapping_only(db, dd_seed):
    s = dd_seed
    order = s.order(total=1000)
    s.item(order, attrs={"product_type": "piece", "craft": "U型13*15", "length": "15厘米", "size": "UNTRUSTED_SIZE"})
    first = build_analysis(db, s.actor, s.request(dimensions=["size", "length"]))
    assert first["dimensions"]["size"][0]["key"] == "待映射：U型13*15"
    assert first["quality"]["dimension_coverage"]["size"]["rate"] == 0
    db.add(DecisionMapping(property="size", product_type="piece", raw_value="U型13*15", standard_value="13*15", updated_by=s.users[0].id))
    db.flush()
    second = build_analysis(db, s.actor, s.request(dimensions=["size", "length"]))
    assert second["dimensions"]["size"][0]["key"] == "13*15"
    assert second["quality"]["dimension_coverage"]["size"]["rate"] == 1


def test_disabled_customer_contact_rules_suppressed(db, dd_seed):
    s = dd_seed
    s.customers[0].status = 0
    for day in (date(2026, 5, 1), date(2026, 5, 11), date(2026, 5, 21), date(2026, 6, 1)):
        s.order(day, total=1000)
    result = build_analysis(db, s.actor, s.request())
    assert not any(r["rule_key"] == "repurchase_due" for r in result["insights"])


def test_a28_matrix_distinct_counts_not_additive(db, dd_seed):
    s = dd_seed
    order = s.order(total=2000)
    s.item(order, attrs={"product_type": "cap", "craft": "lace", "length": "15厘米"})
    s.item(order, attrs={"product_type": "cap", "craft": "silk", "length": "25厘米"})
    result = build_analysis(db, s.actor, s.request())
    assert len(result["matrix"]) == 2
    assert sum(r["order_count"] for r in result["matrix"]) == 2
    assert result["summary"]["order_count"] == 1
    assert not result["quality"]["group_counts_additive"]


def test_a29_decomposition_balances_and_zero_quantity_base(db, dd_seed):
    s = dd_seed
    old = s.order(date(2026, 8, 10), total=2000)
    s.item(old, qty=2, price=1000)
    new = s.order(total=2800)
    s.item(new, qty=3, price=900)
    result = build_analysis(db, s.actor, s.request())
    decomposition = result["amount_decomposition"]
    assert decomposition["quantity_contribution"] == 1000
    assert decomposition["weighted_price_contribution"] == -300
    assert decomposition["method"] == "base_period_price_quantity_first"
    assert decomposition["matched_amount_change"] == 700
    assert decomposition["header_item_difference_change"] == 100
    db.delete(old)
    db.flush()
    assert build_analysis(db, s.actor, s.request())["amount_decomposition"]["status"] == "new_or_zero_base"


def test_archive_before_coverage_not_real_new_customer_or_complete_history(db, dd_seed):
    s = dd_seed
    s.customers[0].first_order_date = date(2020, 1, 1)
    s.order(total=1000)
    db.add(DecisionConfig(key="coverage_start", value="2025-01-01"))
    db.flush()
    result = build_analysis(db, s.actor, s.request())
    assert not result["customers"][0]["history"]["history_complete"]
    assert result["customers"][0]["history"]["first_purchase_status"] == "historical_customer_entered_system"
    assert result["cohorts"][0]["historical_customer_count"] == 1
    assert result["cohorts"][0]["verified_new_customer_count"] == 0


def test_unknown_original_price_excluded_from_price_reference(db, dd_seed):
    s = dd_seed
    row = s.order(total=50)
    s.item(row, price=50, original=0)
    result = build_analysis(db, s.actor, s.request())
    assert result["price_structure"]["known_standard_item_count"] == 0
    assert result["price_structure"]["unknown_standard_item_count"] == 1
    assert result["price_structure"]["discount_rate"] is None


def test_historical_product_risk_pool_retains_dormant_excludes_never_bought(db, dd_seed):
    s = dd_seed
    other = DomesticCustomer(shop_name="DD other own", owner_user_id=s.users[0].id, created_by=s.users[0].id)
    db.add(other)
    db.flush()
    for day in (date(2026, 5, 1), date(2026, 5, 11), date(2026, 5, 21), date(2026, 6, 1)):
        s.item(s.order(day, total=1000), color="black")
        s.item(s.order(day, total=1000, customer=other), color="red")
    result = build_analysis(db, s.actor, s.request(filters={"color": ["black"]}))
    assert result["meta"]["risk_customer_ids"] == [s.customers[0].id]
    assert [row["customer_id"] for row in result["customers"]] == [s.customers[0].id]
    assert result["customers"][0]["order_count"] == 0
    assert result["customers"][0]["history"]["purchase_days"] == 4
    assert all(insight["customer_id"] != other.id for insight in result["insights"])


def test_profile_preserves_full_authorized_rfm_peers_no_other_fact_leak(db, dd_seed):
    s = dd_seed
    all_customers = [s.customers[0]]
    for index in range(29):
        customer = DomesticCustomer(shop_name=f"DD peer {index}", owner_user_id=s.users[0].id, created_by=s.users[0].id)
        db.add(customer)
        db.flush()
        all_customers.append(customer)
    for index, customer in enumerate(all_customers):
        s.item(s.order(date(2026, 9, 1) + timedelta(days=index), total=1000 + index, customer=customer), price=1000 + index)
    aggregate = build_analysis(db, s.actor, s.request())
    expected = next(row for row in aggregate["customers"] if row["customer_id"] == s.customers[0].id)["history"]["rfm"]
    profile = customer_profile(db, s.actor, s.customers[0].id, s.request())
    assert expected["peer_count"] == 30
    assert profile["customer"]["history"]["rfm"] == expected
    assert profile["meta"]["customer_ids"] == [s.customers[0].id]
    assert all(order["customer_id"] == s.customers[0].id for order in profile["evidence"]["orders"])
    assert all(line["customer_id"] == s.customers[0].id for line in profile["evidence"]["items"])


def test_own_purchase_recommendations_sparse_co_purchase_degrades(db, dd_seed):
    s = dd_seed
    s.item(s.order(total=1000))
    result = build_analysis(db, s.actor, s.request())
    customer = result["customers"][0]
    assert customer["preferences"]["status"] == "observed_purchases"
    assert customer["preferences"]["co_purchase"] == []
    assert customer["recommendations"][0]["inventory_delivery"] == "unknown"
    assert customer["recommendations"][0]["rule_key"] == "own_repeat_combination"


def test_co_purchase_requires_twenty_customers_and_five_support(db, dd_seed):
    s = dd_seed
    customers = [s.customers[0]]
    for index in range(19):
        row = DomesticCustomer(shop_name=f"DD combination {index}", owner_user_id=s.users[0].id, created_by=s.users[0].id)
        db.add(row)
        db.flush()
        customers.append(row)
    for index, customer in enumerate(customers):
        order = s.order(total=2000 if index < 5 else 1000, customer=customer)
        s.item(order, attrs={"product_type": "cap", "craft": "lace", "length": "15厘米"})
        if index < 5:
            s.item(order, attrs={"product_type": "cap", "craft": "silk", "length": "25厘米"})
    result = build_analysis(db, s.actor, s.request())
    target = next(row for row in result["customers"] if row["customer_id"] == s.customers[0].id)
    assert target["preferences"]["co_purchase"][0]["support_customer_count"] == 5
    assert target["preferences"]["co_purchase"][0]["peer_customer_count"] == 20
    assert "evidence_refs" not in target["preferences"]["co_purchase"][0]


def test_sparse_customer_uses_twenty_valid_peer_cycles_and_profile_keeps_reference(db, dd_seed):
    s = dd_seed
    s.item(s.order(total=1000))
    for index in range(20):
        customer = DomesticCustomer(shop_name=f"DD cycle peer {index}", owner_user_id=s.users[0].id, created_by=s.users[0].id)
        db.add(customer)
        db.flush()
        for day in (date(2026, 5, 1), date(2026, 5, 11), date(2026, 5, 21), date(2026, 5, 31)):
            s.item(s.order(day, total=1000, customer=customer))
    result = customer_profile(db, s.actor, s.customers[0].id, s.request())
    history = result["customer"]["history"]
    assert history["cycle_days"] == 10
    assert history["cycle_peer_count"] == 20
    assert history["cycle_basis"] == "peer_reference"
    assert all(row["customer_id"] == s.customers[0].id for row in result["evidence"]["orders"])


def test_dimension_quality_uses_lower_weighted_coverage_not_record_count(db, dd_seed):
    s = dd_seed
    order = s.order(total=5095000)
    for _ in range(95):
        s.item(order, qty=1, price=1000)
    for _ in range(5):
        s.item(order, qty=1000, price=1000, attrs={"product_type": "cap", "length": "15厘米"})
    result = build_analysis(db, s.actor, s.request(metric="quantity"))
    coverage = result["quality"]["dimension_coverage"]["craft"]
    assert coverage["record_coverage"] == .95
    assert coverage["quantity_coverage"] == 95 / 5095
    assert coverage["amount_coverage"] == 95 / 5095
    assert coverage["effective_coverage"] == 95 / 5095
    assert not coverage["strong_advice_enabled"]
    assert result["meta"]["coverage_method"] == "minimum_of_record_and_display_metric_weighted_coverage"
