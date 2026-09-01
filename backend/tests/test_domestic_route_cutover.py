"""Direct domestic route switch tests."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Query

from app.auth.models import ArkUser
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticCustomer,
    DomesticItemProgress,
    DomesticOrder,
    DomesticOrderItem,
    DomesticProduct,
    DomesticRouteRule,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding
from app.system.models import SysDict
from scripts import domestic_route_cutover as cutover


@pytest.fixture
def direct_switch_case(db):
    operator = ArkUser(
        username="direct-switch-operator",
        password_hash="x",
        real_name="切换操作员",
        is_active=True,
    )
    db.add(operator)
    db.flush()

    old_route = ProcessRoute(name="旧内贸通用路线", status=1)
    cap_route = ProcessRoute(name="头套网帽（递针）", status=1)
    piece_route = ProcessRoute(name="发片网底（递针）", status=1)
    db.add_all([old_route, cap_route, piece_route])
    db.flush()

    processes = [
        Process(name="旧路线工序", status=1),
        Process(name="发加工点", status=1),
        Process(name="丹东收货", status=1),
        Process(name="丹东发货", status=1),
        Process(name="李晓宏手钩", status=1),
        Process(name="李晓宏递针", status=1),
        Process(name="毛坯质检", status=1),
        Process(name="毛坯维修", status=1),
        Process(name="后处理定型", status=1),
        Process(name="发片路线工序", status=1),
    ]
    db.add_all(processes)
    db.flush()
    db.add(ProcessRouteStep(route_id=old_route.id, process_id=processes[0].id, step_order=1))
    for route in (cap_route, piece_route):
        for step_order, process in enumerate(processes[1:9], start=1):
            db.add(ProcessRouteStep(
                route_id=route.id,
                process_id=process.id,
                step_order=step_order,
            ))
    for process in processes:
        db.add(UserProcessBinding(user_id=operator.id, process_id=process.id))
    decisions = {
        processes[1].id: [
            {"code": "dandong", "label": "丹东", "skip_process_ids": [processes[4].id, processes[5].id]},
            {"code": "lixiaohong", "label": "李晓宏", "skip_process_ids": [processes[2].id, processes[3].id]},
        ],
        processes[4].id: [
            {"code": "needle", "label": "需要递针", "skip_process_ids": []},
            {"code": "no_needle", "label": "不需要递针", "skip_process_ids": [processes[5].id]},
        ],
        processes[6].id: [
            {"code": "qualified", "label": "合格", "skip_process_ids": [processes[7].id]},
            {"code": "repair", "label": "需要维修", "skip_process_ids": []},
        ],
    }
    for route in (cap_route, piece_route):
        for process_id, options in decisions.items():
            db.add(DomesticRouteRule(
                route_id=route.id,
                process_id=process_id,
                rule_type="decision",
                config_json={"options": options},
            ))
        db.add(DomesticRouteRule(
            route_id=route.id,
            process_id=processes[8].id,
            rule_type="optional",
            config_json=None,
        ))
    db.add_all([
        SysDict(
            type="domestic_cap_craft",
            code="递旋",
            label="递旋",
            sort=1,
            is_active=True,
        ),
        SysDict(
            type="domestic_cap_craft",
            code="中分界",
            label="中分界",
            sort=2,
            is_active=True,
        ),
        SysDict(
            type="domestic_piece_craft_size",
            code="U型13*15",
            label="U型13*15",
            sort=1,
            is_active=True,
        ),
    ])

    cap_mapping = DomesticCraftRoute(
        product_type="cap",
        craft="递旋",
        route_id=old_route.id,
        updated_by=operator.id,
    )
    piece_mapping = DomesticCraftRoute(
        product_type="piece",
        craft="U型13*15",
        route_id=old_route.id,
        updated_by=operator.id,
    )
    cap_product = DomesticProduct(
        attrs_key="direct-cap",
        name="头套产品",
        product_type="cap",
        craft="递旋",
        size="M",
        length="15厘米",
        density="65%",
        hair_style_series="直发",
        route_id=old_route.id,
        status=1,
    )
    piece_product = DomesticProduct(
        attrs_key="direct-piece",
        name="发片产品",
        product_type="piece",
        craft="U型13*15",
        size=None,
        length="20厘米",
        density=None,
        route_id=None,
        status=1,
    )
    customer = DomesticCustomer(
        shop_name="直接切换客户",
        balance=Decimal("1000"),
        status=1,
        created_by=operator.id,
    )
    db.add_all([cap_mapping, piece_mapping, cap_product, piece_product, customer])
    db.flush()

    order = DomesticOrder(
        domestic_no="DO20260901-901",
        order_no="DIRECT-1",
        order_date=date(2026, 9, 1),
        customer_id=customer.id,
        status=1,
        total_amount=0,
        charged_amount=0,
        next_line_no=2,
        item_count=1,
        total_unit_qty=1,
        created_by=operator.id,
    )
    db.add(order)
    db.flush()
    old_item = DomesticOrderItem(
        order_id=order.id,
        line_no=1,
        product_id=cap_product.id,
        product_name=cap_product.name,
        route_id=old_route.id,
        order_qty=1,
        unit_price=0,
        original_price=0,
        discount_amount=0,
        membership_level_snapshot=None,
        pricing_rule="legacy_manual",
        pricing_version="legacy",
        base_price_version_snapshot=0,
        status=0,
    )
    db.add(old_item)
    db.flush()
    old_progress = DomesticItemProgress(
        item_id=old_item.id,
        route_id=old_route.id,
        process_id=processes[0].id,
        step_order=1,
        completed_qty=0,
        status=0,
    )
    db.add(old_progress)
    db.commit()
    return {
        "old_route": old_route,
        "cap_route": cap_route,
        "piece_route": piece_route,
        "cap_mapping": cap_mapping,
        "piece_mapping": piece_mapping,
        "cap_product": cap_product,
        "piece_product": piece_product,
        "old_item": old_item,
        "old_progress": old_progress,
    }


def test_dry_run_reports_two_routes_without_writes(db, direct_switch_case):
    plan = cutover.build_plan(db)

    assert plan["mode"] == "dry-run"
    assert plan["routes"]["cap"]["name"] == "头套网帽（递针）"
    assert plan["routes"]["piece"]["name"] == "发片网底（递针）"
    assert plan["mapping_counts"] == {"cap": 1, "piece": 1}
    assert plan["missing_mappings_to_create"] == {
        "cap": ["中分界"],
        "piece": [],
    }
    assert plan["product_counts"] == {"cap": 1, "piece": 1}
    assert plan["existing_order_items_unchanged"] == {"cap": 1, "piece": 0}
    db.refresh(direct_switch_case["cap_product"])
    assert direct_switch_case["cap_product"].route_id == direct_switch_case["old_route"].id


def test_apply_switches_mappings_and_products_but_not_existing_items(db, direct_switch_case):
    result = cutover.apply_cutover(db, writes_stopped=True)

    assert result["mode"] == "applied"
    assert result["created_mapping_counts"] == {"cap": 1, "piece": 0}
    assert result["updated_mapping_counts"] == {"cap": 2, "piece": 1}
    assert result["updated_product_counts"] == {"cap": 1, "piece": 1}
    for key in ("cap_mapping", "piece_mapping", "cap_product", "piece_product", "old_item", "old_progress"):
        db.refresh(direct_switch_case[key])
    assert direct_switch_case["cap_mapping"].route_id == direct_switch_case["cap_route"].id
    assert direct_switch_case["cap_product"].route_id == direct_switch_case["cap_route"].id
    assert direct_switch_case["piece_mapping"].route_id == direct_switch_case["piece_route"].id
    assert direct_switch_case["piece_product"].route_id == direct_switch_case["piece_route"].id
    assert direct_switch_case["old_item"].route_id == direct_switch_case["old_route"].id
    assert direct_switch_case["old_progress"].route_id == direct_switch_case["old_route"].id
    created_mapping = db.query(DomesticCraftRoute).filter_by(
        product_type="cap",
        craft="中分界",
    ).one()
    assert created_mapping.route_id == direct_switch_case["cap_route"].id
    assert created_mapping.updated_by is None


def test_apply_requires_write_freeze(db, direct_switch_case):
    with pytest.raises(cutover.CutoverError, match="停止内贸写入"):
        cutover.apply_cutover(db, writes_stopped=False)


def test_missing_target_route_refuses_switch(db, direct_switch_case):
    db.delete(direct_switch_case["piece_route"])
    db.commit()

    with pytest.raises(cutover.CutoverError, match="发片网底.*不存在"):
        cutover.build_plan(db)


def test_route_without_active_worker_refuses_switch(db, direct_switch_case):
    worker = db.query(ArkUser).filter_by(username="direct-switch-operator").one()
    worker.is_active = False
    db.commit()

    with pytest.raises(cutover.CutoverError, match="未绑定在职人员"):
        cutover.build_plan(db)


def test_cap_route_without_required_rules_refuses_switch(db, direct_switch_case):
    db.query(DomesticRouteRule).filter_by(
        route_id=direct_switch_case["cap_route"].id,
    ).delete(synchronize_session=False)
    db.commit()

    with pytest.raises(cutover.CutoverError, match="条件规则不符合业务契约"):
        cutover.build_plan(db)


def test_piece_route_without_required_rules_refuses_switch(db, direct_switch_case):
    db.query(DomesticRouteRule).filter_by(
        route_id=direct_switch_case["piece_route"].id,
    ).delete(synchronize_session=False)
    db.commit()

    with pytest.raises(cutover.CutoverError, match="条件规则不符合业务契约"):
        cutover.build_plan(db)


def test_cap_route_with_wrong_branch_targets_refuses_switch(db, direct_switch_case):
    rule = db.query(DomesticRouteRule).filter_by(
        route_id=direct_switch_case["cap_route"].id,
    ).order_by(DomesticRouteRule.id.asc()).first()
    options = [dict(option) for option in rule.config_json["options"]]
    options[0]["code"], options[1]["code"] = options[1]["code"], options[0]["code"]
    rule.config_json = {"options": options}
    db.commit()

    with pytest.raises(cutover.CutoverError, match="结果编码或跳过目标与业务路线不一致"):
        cutover.build_plan(db)


def test_cap_route_with_extra_conditional_rule_refuses_switch(db, direct_switch_case):
    dandong_receipt = db.query(Process).filter_by(name="丹东收货").one()
    db.add(DomesticRouteRule(
        route_id=direct_switch_case["cap_route"].id,
        process_id=dandong_receipt.id,
        rule_type="optional",
        config_json=None,
    ))
    db.commit()

    with pytest.raises(cutover.CutoverError, match="未批准的额外条件规则"):
        cutover.build_plan(db)


def test_second_phase_failure_rolls_back_first_phase(db, direct_switch_case, monkeypatch):
    original_update = Query.update

    def fail_product_update(query, *args, **kwargs):
        entity = query.column_descriptions[0].get("entity")
        if entity is DomesticProduct:
            raise RuntimeError("injected product update failure")
        return original_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "update", fail_product_update)
    with pytest.raises(RuntimeError, match="injected product update failure"):
        cutover.apply_cutover(db, writes_stopped=True)

    db.expire_all()
    db.refresh(direct_switch_case["cap_mapping"])
    assert direct_switch_case["cap_mapping"].route_id == direct_switch_case["old_route"].id
    assert db.query(DomesticCraftRoute).filter_by(
        product_type="cap",
        craft="中分界",
    ).count() == 0


def test_cli_confirmation_must_be_exact():
    with pytest.raises(cutover.CutoverError, match="DOMESTIC_WRITES_STOPPED"):
        cutover.confirm_writes_stopped("yes")
    cutover.confirm_writes_stopped("DOMESTIC_WRITES_STOPPED")
