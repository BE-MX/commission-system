"""Guarded cutover tests for domestic conditional routes."""

from datetime import date
from decimal import Decimal

import pytest

from app.auth.models import ArkUser
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticCustomer,
    DomesticItemProgress,
    DomesticItemUnit,
    DomesticOrder,
    DomesticOrderItem,
    DomesticProduct,
    DomesticReportLog,
    DomesticReportUnit,
    DomesticRouteRule,
    DomesticSkipLog,
    DomesticSkipUnit,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding
from scripts import domestic_route_cutover as cutover


@pytest.fixture
def cutover_case(db):
    operator = ArkUser(
        username="cutover-operator", password_hash="x", real_name="切换操作员",
        is_active=True,
    )
    db.add(operator)
    db.flush()

    old_route = ProcessRoute(name="旧内贸路线", status=1)
    target_route = ProcessRoute(name="头套网帽（递针）", status=1)
    db.add_all([old_route, target_route])
    db.flush()

    processes = [Process(name=f"切换工序{i}", status=1) for i in range(1, 5)]
    db.add_all(processes)
    db.flush()
    for order, process in enumerate(processes[:2], start=1):
        db.add(ProcessRouteStep(
            route_id=old_route.id, process_id=process.id, step_order=order,
        ))
    for order, process in enumerate(processes[2:], start=1):
        db.add(ProcessRouteStep(
            route_id=target_route.id, process_id=process.id, step_order=order,
        ))
        db.add(UserProcessBinding(user_id=operator.id, process_id=process.id))
    db.add(DomesticRouteRule(
        route_id=target_route.id,
        process_id=processes[3].id,
        rule_type="optional",
        config_json=None,
    ))

    mapping = DomesticCraftRoute(
        product_type="cap", craft="needle_cap", route_id=old_route.id,
        updated_by=operator.id,
    )
    product = DomesticProduct(
        attrs_key="cutover-product", name="切换产品", product_type="cap",
        craft="needle_cap", size="M", length="16", density="120",
        route_id=old_route.id, status=1,
    )
    customer = DomesticCustomer(
        shop_name="切换客户", balance=Decimal("1000"), status=1,
        created_by=operator.id,
    )
    db.add_all([mapping, product, customer])
    db.flush()
    order = DomesticOrder(
        domestic_no="DO20260831-901", order_no="CUTOVER-1", order_date=date(2026, 8, 31),
        customer_id=customer.id, status=1, total_amount=0, charged_amount=0,
        next_line_no=3, item_count=2, total_unit_qty=3, created_by=operator.id,
    )
    db.add(order)
    db.flush()

    clean_item = DomesticOrderItem(
        order_id=order.id, line_no=1, product_id=product.id,
        product_name=product.name, route_id=old_route.id, order_qty=2,
        unit_price=0, status=0,
    )
    reported_item = DomesticOrderItem(
        order_id=order.id, line_no=2, product_id=product.id,
        product_name=product.name, route_id=old_route.id, order_qty=1,
        unit_price=0, status=0,
    )
    db.add_all([clean_item, reported_item])
    db.flush()
    for item in (clean_item, reported_item):
        for unit_no in range(1, item.order_qty + 1):
            db.add(DomesticItemUnit(item_id=item.id, unit_no=unit_no, status=1))
        for step_order, process in enumerate(processes[:2], start=1):
            db.add(DomesticItemProgress(
                item_id=item.id, route_id=old_route.id, process_id=process.id,
                step_order=step_order, completed_qty=0, status=0,
            ))
    db.flush()

    reported_progress = db.query(DomesticItemProgress).filter_by(
        item_id=reported_item.id, step_order=1,
    ).one()
    reported_unit = db.query(DomesticItemUnit).filter_by(
        item_id=reported_item.id, unit_no=1,
    ).one()
    reported_progress.completed_qty = 1
    log = DomesticReportLog(
        item_id=reported_item.id, progress_id=reported_progress.id,
        process_id=reported_progress.process_id, step_order=1, report_qty=1,
        reported_by_user_id=operator.id, reported_by_name=operator.real_name,
        source="web", report_mode="quantity", request_id="cutover-report-1",
        reported_at=cutover.beijing_now(), revoked=0,
    )
    db.add(log)
    db.flush()
    db.add(DomesticReportUnit(
        log_id=log.id, unit_id=reported_unit.id,
        progress_id=reported_progress.id, completed_at=log.reported_at,
    ))
    db.commit()
    return {
        "operator": operator,
        "old_route": old_route,
        "target_route": target_route,
        "processes": processes,
        "mapping": mapping,
        "product": product,
        "clean_item": clean_item,
        "reported_item": reported_item,
    }


def test_exact_target_route_refuses_missing_and_ambiguous():
    with pytest.raises(cutover.CutoverError, match="不存在"):
        cutover.require_exact_route([], "头套网帽（递针）")
    with pytest.raises(cutover.CutoverError, match="多条"):
        cutover.require_exact_route(
            [ProcessRoute(id=31, name="头套网帽（递针）"),
             ProcessRoute(id=87, name="头套网帽（递针）")],
            "头套网帽（递针）",
        )


def test_preflight_discovers_by_name_and_reports_scope_without_writes(db, cutover_case):
    before = cutover.capture_database_fingerprint(db)

    first = cutover.preflight(
        db,
        target_route_name="头套网帽（递针）",
        craft_names=["needle_cap"],
    )
    second = cutover.preflight(
        db,
        target_route_name="头套网帽（递针）",
        craft_names=["needle_cap"],
    )
    same_exact_pair = cutover.preflight(
        db,
        target_route_name="头套网帽（递针）",
        craft_keys=["cap::needle_cap"],
    )

    assert first["target_route"]["id"] == cutover_case["target_route"].id
    assert first["target_route"]["rule_valid"] is True
    assert first["worker_coverage"]["missing"] == []
    assert first["craft_mappings"][0]["craft"] == "needle_cap"
    assert first["products"][0]["current_route_id"] == cutover_case["old_route"].id
    assert first["products"][0]["will_change"] is True
    assert [row["id"] for row in first["items"]["no_report"]] == [
        cutover_case["clean_item"].id,
    ]
    assert [row["id"] for row in first["items"]["reported"]] == [
        cutover_case["reported_item"].id,
    ]
    assert first["before_totals"] == {
        "items": 2,
        "report_logs": 1,
        "report_units": 1,
        "completed_qty": 1,
        "workload_qty": 1,
    }
    assert first["preflight_token"] == second["preflight_token"]
    assert first["preflight_token"] == same_exact_pair["preflight_token"]
    assert cutover.capture_database_fingerprint(db) == before


def test_preflight_rejects_invalid_rules_and_missing_worker_coverage(db, cutover_case):
    target = cutover_case["target_route"]
    last_process = cutover_case["processes"][3]
    db.query(UserProcessBinding).filter_by(process_id=last_process.id).delete()
    db.commit()
    with pytest.raises(cutover.CutoverError, match="未绑定在职人员"):
        cutover.preflight(
            db, target_route_name=target.name, craft_names=["needle_cap"],
        )

    db.add(UserProcessBinding(
        user_id=cutover_case["operator"].id, process_id=last_process.id,
    ))
    rule = db.query(DomesticRouteRule).filter_by(route_id=target.id).one()
    rule.rule_type = "unsupported"
    db.commit()
    with pytest.raises(cutover.CutoverError, match="规则校验失败"):
        cutover.preflight(
            db, target_route_name=target.name, craft_names=["needle_cap"],
        )

    db.delete(rule)
    db.commit()
    with pytest.raises(cutover.CutoverError, match="没有配置条件规则"):
        cutover.preflight(
            db, target_route_name=target.name, craft_names=["needle_cap"],
        )


def test_apply_requires_token_crafts_and_reviewed_reconciliation(db, cutover_case):
    target_name = cutover_case["target_route"].name
    with pytest.raises(cutover.CutoverError, match="至少一个工艺选择器"):
        cutover.apply_cutover(
            db, target_route_name=target_name, craft_names=[],
            writes_stopped=True,
            preflight_token="x", reconciliation={"reported_items": []},
        )
    with pytest.raises(cutover.CutoverError, match="预检令牌"):
        cutover.apply_cutover(
            db, target_route_name=target_name, craft_names=["needle_cap"],
            writes_stopped=True,
            preflight_token="wrong", reconciliation={"reported_items": []},
        )

    plan = cutover.preflight(
        db, target_route_name=target_name, craft_names=["needle_cap"],
    )
    with pytest.raises(cutover.CutoverError, match="逐项覆盖"):
        cutover.apply_cutover(
            db, target_route_name=target_name, craft_names=["needle_cap"],
            writes_stopped=True,
            preflight_token=plan["preflight_token"],
            reconciliation={"reported_items": []},
        )
    assert db.get(DomesticCraftRoute, cutover_case["mapping"].id).route_id == cutover_case["old_route"].id


def test_apply_is_atomic_rebuilds_only_clean_items_and_conserves_history(db, cutover_case):
    target = cutover_case["target_route"]
    clean_item = cutover_case["clean_item"]
    reported_item = cutover_case["reported_item"]
    old_unit_ids = [row[0] for row in db.query(DomesticItemUnit.id).filter_by(
        item_id=clean_item.id,
    ).order_by(DomesticItemUnit.id).all()]
    plan = cutover.preflight(
        db, target_route_name=target.name, craft_names=["needle_cap"],
    )

    result = cutover.apply_cutover(
        db,
        target_route_name=target.name,
        craft_names=["needle_cap"],
        writes_stopped=True,
        preflight_token=plan["preflight_token"],
        reconciliation={
            "reported_items": [
                {"item_id": reported_item.id, "action": "keep_current"},
            ],
        },
    )

    assert db.get(DomesticCraftRoute, cutover_case["mapping"].id).route_id == target.id
    assert db.get(DomesticProduct, cutover_case["product"].id).route_id == target.id
    assert db.get(DomesticOrderItem, clean_item.id).route_id == target.id
    assert db.get(DomesticOrderItem, reported_item.id).route_id == cutover_case["old_route"].id
    assert [row[0] for row in db.query(DomesticItemProgress.process_id).filter_by(
        item_id=clean_item.id,
    ).order_by(DomesticItemProgress.step_order).all()] == [
        process.id for process in cutover_case["processes"][2:]
    ]
    assert [row[0] for row in db.query(DomesticItemUnit.id).filter_by(
        item_id=clean_item.id,
    ).order_by(DomesticItemUnit.id).all()] == old_unit_ids
    assert result["before_totals"] == result["after_totals"]
    assert result["write_freeze_confirmation"] == "DOMESTIC_WRITES_STOPPED"


def test_apply_rolls_back_every_write_on_unsupported_reconciliation(db, cutover_case):
    plan = cutover.preflight(
        db,
        target_route_name=cutover_case["target_route"].name,
        craft_names=["needle_cap"],
    )
    before = cutover.capture_database_fingerprint(db)
    with pytest.raises(cutover.CutoverError, match="不支持的处置动作"):
        cutover.apply_cutover(
            db,
            target_route_name=cutover_case["target_route"].name,
            craft_names=["needle_cap"],
            writes_stopped=True,
            preflight_token=plan["preflight_token"],
            reconciliation={"reported_items": [{
                "item_id": cutover_case["reported_item"].id,
                "action": "move_history",
            }]},
        )
    assert cutover.capture_database_fingerprint(db) == before


def test_preflight_token_detects_change_after_review(db, cutover_case):
    plan = cutover.preflight(
        db,
        target_route_name=cutover_case["target_route"].name,
        craft_names=["needle_cap"],
    )
    cutover_case["product"].name = "预检后被修改"
    db.commit()

    with pytest.raises(cutover.CutoverError, match="预检后数据已变化"):
        cutover.apply_cutover(
            db,
            target_route_name=cutover_case["target_route"].name,
            craft_names=["needle_cap"],
            writes_stopped=True,
            preflight_token=plan["preflight_token"],
            reconciliation={"reported_items": [{
                "item_id": cutover_case["reported_item"].id,
                "action": "keep_current",
            }]},
        )


def test_skip_audit_history_is_never_rebuilt_as_a_clean_item(db, cutover_case):
    clean_item = cutover_case["clean_item"]
    progress = db.query(DomesticItemProgress).filter_by(
        item_id=clean_item.id, step_order=1,
    ).one()
    unit = db.query(DomesticItemUnit).filter_by(
        item_id=clean_item.id, unit_no=1,
    ).one()
    skip = DomesticSkipLog(
        item_id=clean_item.id, progress_id=progress.id, skip_qty=1,
        source="manual", skip_mode="unit", reason="历史异常放行记录",
        request_id="cutover-existing-skip", created_by_user_id=cutover_case["operator"].id,
        revoked=1, revoked_at=cutover.beijing_now(),
    )
    db.add(skip)
    db.flush()
    db.add(DomesticSkipUnit(
        skip_log_id=skip.id, unit_id=unit.id, progress_id=progress.id,
    ))
    db.commit()

    plan = cutover.preflight(
        db,
        target_route_name=cutover_case["target_route"].name,
        craft_names=["needle_cap"],
    )

    assert clean_item.id not in [row["id"] for row in plan["items"]["no_report"]]
    audited = next(row for row in plan["items"]["reported"] if row["id"] == clean_item.id)
    assert audited["report_log_count"] == 0
    assert audited["skip_log_count"] == 1


def test_ambiguous_craft_name_refuses_and_exact_key_changes_only_one_mapping(db, cutover_case):
    piece_mapping = DomesticCraftRoute(
        product_type="piece", craft="needle_cap",
        route_id=cutover_case["old_route"].id,
        updated_by=cutover_case["operator"].id,
    )
    db.add(piece_mapping)
    db.commit()

    with pytest.raises(cutover.CutoverError, match=r"needle_cap.*cap.*piece"):
        cutover.preflight(
            db,
            target_route_name=cutover_case["target_route"].name,
            craft_names=["needle_cap"],
        )

    plan = cutover.preflight(
        db,
        target_route_name=cutover_case["target_route"].name,
        craft_keys=["cap::needle_cap"],
    )
    assert plan["selected_craft_pairs"] == [
        {"product_type": "cap", "craft": "needle_cap"},
    ]
    assert [row["id"] for row in plan["craft_mappings"]] == [
        cutover_case["mapping"].id,
    ]

    cutover.apply_cutover(
        db,
        target_route_name=cutover_case["target_route"].name,
        craft_names=[],
        craft_keys=["cap::needle_cap"],
        writes_stopped=True,
        preflight_token=plan["preflight_token"],
        reconciliation={"reported_items": [{
            "item_id": cutover_case["reported_item"].id,
            "action": "keep_current",
        }]},
    )
    assert db.get(DomesticCraftRoute, cutover_case["mapping"].id).route_id == cutover_case["target_route"].id
    assert db.get(DomesticCraftRoute, piece_mapping.id).route_id == cutover_case["old_route"].id


@pytest.mark.parametrize(
    ("craft_names", "craft_keys", "message"),
    [
        ([], ["bad-key"], "格式"),
        ([], ["unknown::needle_cap"], "产品类型"),
        ([], ["cap::needle_cap", "cap::needle_cap"], "重复"),
        (["needle_cap", "needle_cap"], [], "重复"),
        ([], ["cap::missing"], "不存在"),
        (["needle_cap"], ["cap::needle_cap"], "重叠"),
    ],
)
def test_craft_selectors_are_strict(db, cutover_case, craft_names, craft_keys, message):
    with pytest.raises(cutover.CutoverError, match=message):
        cutover.preflight(
            db,
            target_route_name=cutover_case["target_route"].name,
            craft_names=craft_names,
            craft_keys=craft_keys,
        )


def test_preflight_token_covers_worker_and_full_report_audit_fields(db, cutover_case):
    first = cutover.preflight(
        db,
        target_route_name=cutover_case["target_route"].name,
        craft_keys=["cap::needle_cap"],
    )
    log = db.query(DomesticReportLog).filter_by(
        item_id=cutover_case["reported_item"].id,
    ).one()
    log.reported_by_user_id = cutover_case["operator"].id + 1000
    log.reported_by_name = "审计字段已变化"
    log.source = "mini"
    db.commit()

    second = cutover.preflight(
        db,
        target_route_name=cutover_case["target_route"].name,
        craft_keys=["cap::needle_cap"],
    )
    assert second["preflight_token"] != first["preflight_token"]


def test_apply_requires_write_freeze_before_rollback_or_any_write(
    db, cutover_case, monkeypatch,
):
    product = cutover_case["product"]
    db.refresh(product)
    product.name = "尚未提交的调用方改动"
    assert product in db.dirty
    rollback_calls = []
    monkeypatch.setattr(db, "rollback", lambda: rollback_calls.append(True))

    with pytest.raises(cutover.CutoverError, match="停止内贸写入"):
        cutover.apply_cutover(
            db,
            target_route_name=cutover_case["target_route"].name,
            craft_keys=["cap::needle_cap"],
            preflight_token="0" * 64,
            reconciliation={"reported_items": []},
        )

    assert product.name == "尚未提交的调用方改动"
    assert rollback_calls == []


@pytest.mark.parametrize("value", [None, "", "yes", "domestic_writes_stopped"])
def test_cli_write_freeze_confirmation_must_match_exact_constant(value):
    with pytest.raises(cutover.CutoverError, match="DOMESTIC_WRITES_STOPPED"):
        cutover.confirm_writes_stopped(value)
    assert cutover.confirm_writes_stopped("DOMESTIC_WRITES_STOPPED") is True
