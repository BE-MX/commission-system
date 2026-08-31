"""内贸条件路线规则与逐件分流的状态机契约。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func
from pydantic import ValidationError

from app.auth.models import ArkUser
from app.domestic import progress_service, report_service, unit_service
from app.domestic import route_rule_service
from app.domestic.models import (
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
from app.domestic.schemas import RouteRuleSaveRequest
from app.production.models import (
    Process,
    ProcessRoute,
    ProcessRouteStep,
    UserProcessBinding,
)


@pytest.fixture
def conditional_route(db):
    route = ProcessRoute(name="内贸条件路线", status=1)
    processes = [Process(name=f"条件工序{i}", status=1) for i in range(1, 7)]
    db.add_all([route, *processes])
    db.flush()
    for step_order, process in enumerate(processes, start=1):
        db.add(ProcessRouteStep(
            route_id=route.id,
            process_id=process.id,
            step_order=step_order,
        ))
    db.flush()
    return SimpleNamespace(
        id=route.id,
        process_ids=[process.id for process in processes],
        process_names=[process.name for process in processes],
    )


@pytest.fixture
def conditional_order(db, conditional_route):
    worker = ArkUser(username="conditional-worker", password_hash="x", real_name="分流工")
    db.add(worker)
    db.flush()
    for process_id in conditional_route.process_ids:
        db.add(UserProcessBinding(user_id=worker.id, process_id=process_id))

    customer = DomesticCustomer(
        shop_name="条件路线客户",
        created_by=worker.id,
    )
    product = DomesticProduct(
        attrs_key="conditional-routing-product",
        name="条件路线产品",
        product_type="cap",
        craft="条件工艺",
        size="S",
        length="15厘米",
        density="100%",
        route_id=conditional_route.id,
    )
    db.add_all([customer, product])
    db.flush()
    order = DomesticOrder(
        domestic_no="DO20260831-999",
        order_no="CONDITIONAL-001",
        order_date=date(2026, 8, 31),
        customer_id=customer.id,
        order_type="normal",
        status=1,
        total_amount=Decimal("0"),
        charged_amount=Decimal("0"),
        next_line_no=2,
        item_count=1,
        total_unit_qty=20,
        created_by=worker.id,
    )
    db.add(order)
    db.flush()
    item = DomesticOrderItem(
        order_id=order.id,
        line_no=1,
        product_id=product.id,
        product_name=product.name,
        attrs_snapshot={},
        route_id=conditional_route.id,
        order_qty=20,
        unit_price=Decimal("0"),
        status=0,
    )
    db.add(item)
    db.flush()
    progress_service.init_item_progress(db, item)
    unit_service.ensure_item_units(db, item)
    route_rule_service.save_rules(db, conditional_route.id, [
        _decision(conditional_route.process_ids[1], [
            {
                "code": "dandong",
                "label": "丹东",
                "skip_process_ids": [conditional_route.process_ids[3]],
            },
            {
                "code": "lixiaohong",
                "label": "李晓宏",
                "skip_process_ids": [conditional_route.process_ids[2]],
            },
        ]),
        {
            "process_id": conditional_route.process_ids[4],
            "rule_type": "optional",
            "config": None,
        },
    ])
    db.flush()
    rows = db.query(DomesticItemProgress).filter_by(item_id=item.id).order_by(
        DomesticItemProgress.step_order
    ).all()
    return SimpleNamespace(
        item=item,
        worker=worker,
        rows=rows,
        route=conditional_route,
    )


def _decision(process_id, options=None):
    return {
        "process_id": process_id,
        "rule_type": "decision",
        "config": {
            "options": options or [
                {"code": "left", "label": "左线", "skip_process_ids": []},
                {"code": "right", "label": "右线", "skip_process_ids": []},
            ],
        },
    }


def test_route_rule_rejects_skip_target_before_trigger(db, conditional_route):
    with pytest.raises(ValueError, match="必须位于触发工序之后"):
        route_rule_service.save_rules(db, conditional_route.id, [_decision(
            conditional_route.process_ids[3],
            [
                {
                    "code": "bad",
                    "label": "错误",
                    "skip_process_ids": [conditional_route.process_ids[1]],
                },
                {"code": "ok", "label": "正确", "skip_process_ids": []},
            ],
        )])


def test_route_rules_roundtrip_decision_and_optional(db, conditional_route):
    saved = route_rule_service.save_rules(db, conditional_route.id, [
        _decision(conditional_route.process_ids[1], [
            {
                "code": "left",
                "label": "左线",
                "skip_process_ids": [conditional_route.process_ids[3]],
            },
            {
                "code": "right",
                "label": "右线",
                "skip_process_ids": [conditional_route.process_ids[2]],
            },
        ]),
        {
            "process_id": conditional_route.process_ids[4],
            "rule_type": "optional",
            "config": None,
        },
    ])

    assert [rule["rule_type"] for rule in saved] == ["decision", "optional"]
    assert saved[0]["config"]["options"][0]["skip_processes"] == [{
        "id": conditional_route.process_ids[3],
        "name": conditional_route.process_names[3],
    }]
    assert route_rule_service.list_rules(db, conditional_route.id) == saved
    assert route_rule_service.rule_map(db, conditional_route.id) == {
        rule["process_id"]: rule for rule in saved
    }


def test_save_rules_fully_replaces_existing_rules(db, conditional_route):
    route_rule_service.save_rules(db, conditional_route.id, [
        {"process_id": conditional_route.process_ids[1], "rule_type": "optional", "config": None},
    ])

    saved = route_rule_service.save_rules(db, conditional_route.id, [
        {"process_id": conditional_route.process_ids[4], "rule_type": "optional", "config": None},
    ])

    assert [rule["process_id"] for rule in saved] == [conditional_route.process_ids[4]]
    assert db.query(DomesticRouteRule).filter_by(route_id=conditional_route.id).count() == 1


def test_list_rules_ignores_rule_whose_trigger_step_was_removed(db, conditional_route):
    trigger_id = conditional_route.process_ids[1]
    route_rule_service.save_rules(db, conditional_route.id, [
        {"process_id": trigger_id, "rule_type": "optional", "config": None},
    ])
    db.query(ProcessRouteStep).filter_by(
        route_id=conditional_route.id,
        process_id=trigger_id,
    ).delete(synchronize_session=False)
    db.flush()

    assert route_rule_service.list_rules(db, conditional_route.id) == []


def test_list_rules_filters_skip_target_step_that_was_removed(db, conditional_route):
    trigger_id = conditional_route.process_ids[1]
    removed_target_id = conditional_route.process_ids[3]
    route_rule_service.save_rules(db, conditional_route.id, [_decision(trigger_id, [
        {
            "code": "removed",
            "label": "已移除目标",
            "skip_process_ids": [removed_target_id],
        },
        {"code": "kept", "label": "保留", "skip_process_ids": []},
    ])])
    db.query(ProcessRouteStep).filter_by(
        route_id=conditional_route.id,
        process_id=removed_target_id,
    ).delete(synchronize_session=False)
    db.flush()

    option = route_rule_service.list_rules(db, conditional_route.id)[0]["config"]["options"][0]
    assert option["skip_process_ids"] == []
    assert option["skip_processes"] == []


def test_route_rule_model_cascades_with_route_step_identity():
    composite_fks = {
        (
            tuple(column.name for column in constraint.columns),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in DomesticRouteRule.__table__.foreign_key_constraints
    }
    assert (
        ("route_id", "process_id"),
        ("process_route_step.route_id", "process_route_step.process_id"),
        "CASCADE",
    ) in composite_fks


def test_route_rules_reject_unknown_and_disabled_routes(db, conditional_route):
    disabled = ProcessRoute(name="停用内贸路线", status=0)
    db.add(disabled)
    db.flush()

    with pytest.raises(ValueError, match="路线不存在或已停用"):
        route_rule_service.validate_rules(db, 999999, [])
    with pytest.raises(ValueError, match="路线不存在或已停用"):
        route_rule_service.validate_rules(db, disabled.id, [])


def test_route_rules_reject_duplicate_process(db, conditional_route):
    rule = {"process_id": conditional_route.process_ids[1], "rule_type": "optional", "config": None}
    with pytest.raises(ValueError, match="同一工序只能配置一条规则"):
        route_rule_service.validate_rules(db, conditional_route.id, [rule, rule.copy()])


def test_route_rules_reject_process_outside_route(db, conditional_route):
    outside = Process(name="路线外工序", status=1)
    db.add(outside)
    db.flush()

    with pytest.raises(ValueError, match="工序不属于该路线"):
        route_rule_service.validate_rules(db, conditional_route.id, [
            {"process_id": outside.id, "rule_type": "optional", "config": None},
        ])


def test_route_rules_reject_disabled_process(db, conditional_route):
    disabled = Process(name="路线内停用工序", status=0)
    db.add(disabled)
    db.flush()
    db.add(ProcessRouteStep(
        route_id=conditional_route.id,
        process_id=disabled.id,
        step_order=7,
    ))
    db.flush()

    with pytest.raises(ValueError, match="工序不存在或已停用"):
        route_rule_service.validate_rules(db, conditional_route.id, [
            {"process_id": disabled.id, "rule_type": "optional", "config": None},
        ])


def test_route_rules_reject_unknown_rule_type(db, conditional_route):
    with pytest.raises(ValueError, match="不支持的规则类型"):
        route_rule_service.validate_rules(db, conditional_route.id, [{
            "process_id": conditional_route.process_ids[1],
            "rule_type": "sometimes",
            "config": None,
        }])


def test_route_rules_reject_decision_with_fewer_than_two_options(db, conditional_route):
    with pytest.raises(ValueError, match="至少需要两个结果选项"):
        route_rule_service.validate_rules(db, conditional_route.id, [_decision(
            conditional_route.process_ids[1],
            [{"code": "only", "label": "唯一", "skip_process_ids": []}],
        )])


@pytest.mark.parametrize("code", ["Bad", "1bad", "has-dash", "a" * 33, ""])
def test_route_rules_reject_invalid_decision_code(db, conditional_route, code):
    with pytest.raises(ValueError, match="结果编码格式不合法"):
        route_rule_service.validate_rules(db, conditional_route.id, [_decision(
            conditional_route.process_ids[1],
            [
                {"code": code, "label": "选项一", "skip_process_ids": []},
                {"code": "valid", "label": "选项二", "skip_process_ids": []},
            ],
        )])


def test_route_rules_reject_duplicate_decision_code(db, conditional_route):
    with pytest.raises(ValueError, match="结果编码不能重复"):
        route_rule_service.validate_rules(db, conditional_route.id, [_decision(
            conditional_route.process_ids[1],
            [
                {"code": "same", "label": "选项一", "skip_process_ids": []},
                {"code": "same", "label": "选项二", "skip_process_ids": []},
            ],
        )])


def test_route_rules_reject_empty_decision_label(db, conditional_route):
    with pytest.raises(ValueError, match="结果名称不能为空"):
        route_rule_service.validate_rules(db, conditional_route.id, [_decision(
            conditional_route.process_ids[1],
            [
                {"code": "empty", "label": "  ", "skip_process_ids": []},
                {"code": "valid", "label": "选项二", "skip_process_ids": []},
            ],
        )])


def test_route_rules_reject_target_outside_route(db, conditional_route):
    outside = Process(name="跳过目标路线外工序", status=1)
    db.add(outside)
    db.flush()

    with pytest.raises(ValueError, match="跳过目标不属于该路线"):
        route_rule_service.validate_rules(db, conditional_route.id, [_decision(
            conditional_route.process_ids[1],
            [
                {"code": "outside", "label": "路线外", "skip_process_ids": [outside.id]},
                {"code": "valid", "label": "路线内", "skip_process_ids": []},
            ],
        )])


def test_route_rules_reject_disabled_skip_target(db, conditional_route):
    target_id = conditional_route.process_ids[3]
    db.query(Process).filter(Process.id == target_id).update({"status": 0})
    db.flush()

    with pytest.raises(ValueError, match="跳过目标工序不存在或已停用"):
        route_rule_service.validate_rules(db, conditional_route.id, [_decision(
            conditional_route.process_ids[1],
            [
                {"code": "disabled", "label": "停用", "skip_process_ids": [target_id]},
                {"code": "valid", "label": "正常", "skip_process_ids": []},
            ],
        )])


def test_route_rules_reject_target_equal_to_trigger(db, conditional_route):
    trigger_id = conditional_route.process_ids[1]
    with pytest.raises(ValueError, match="必须位于触发工序之后"):
        route_rule_service.validate_rules(db, conditional_route.id, [_decision(
            trigger_id,
            [
                {"code": "self", "label": "自身", "skip_process_ids": [trigger_id]},
                {"code": "valid", "label": "其他", "skip_process_ids": []},
            ],
        )])


@pytest.mark.parametrize("config", [
    {"options": []},
    {"options": [{"code": "unused", "label": "不应存在", "skip_process_ids": []}]},
])
def test_route_rules_reject_optional_options(db, conditional_route, config):
    with pytest.raises(ValueError, match="可选工序不能配置结果选项"):
        route_rule_service.validate_rules(db, conditional_route.id, [{
            "process_id": conditional_route.process_ids[1],
            "rule_type": "optional",
            "config": config,
        }])


def test_route_rule_pydantic_input_is_strict():
    valid = RouteRuleSaveRequest.model_validate({
        "rules": [{
            "process_id": 1,
            "rule_type": "decision",
            "config": {"options": [
                {"code": "left", "label": "左线", "skip_process_ids": [2]},
                {"code": "right", "label": "右线", "skip_process_ids": []},
            ]},
        }],
    })
    assert valid.rules[0].config.options[0].code == "left"

    invalid_payloads = [
        {"rules": [{"process_id": 0, "rule_type": "optional", "config": None}]},
        {"rules": [{"process_id": 1, "rule_type": "unknown", "config": None}]},
        {"rules": [{
            "process_id": 1,
            "rule_type": "decision",
            "config": {"options": [
                {"code": "Bad-Code", "label": "非法", "skip_process_ids": []},
                {"code": "valid", "label": "合法", "skip_process_ids": []},
            ]},
        }]},
        {"rules": [{
            "process_id": 1,
            "rule_type": "decision",
            "config": {"options": [
                {
                    "code": "left",
                    "label": "左线",
                    "skip_process_ids": [2],
                    "skip_processes": [{"id": 999, "name": "不可信客户端名称"}],
                },
                {"code": "right", "label": "右线", "skip_process_ids": []},
            ]},
        }]},
        {"rules": [{"process_id": 1, "rule_type": "optional", "config": None, "extra": True}]},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            RouteRuleSaveRequest.model_validate(payload)


def _submit(db, case, step_index, qty, *, outcomes=None, unit_id=None, request_id=None):
    return report_service.submit_report(
        db,
        item_id=case.item.id,
        progress_id=case.rows[step_index].id,
        qty=qty,
        user_id=case.worker.id,
        source="web",
        outcomes=outcomes,
        unit_id=unit_id,
        request_id=request_id,
    )


def test_decision_split_routes_exact_units_and_excludes_skips_from_workload(
    db, conditional_order
):
    case = conditional_order
    _submit(db, case, 0, 20)
    dispatch = _submit(
        db,
        case,
        1,
        20,
        outcomes={"dandong": 12, "lixiaohong": 8},
    )

    assert dispatch["outcomes"] == {"dandong": 12, "lixiaohong": 8}
    allocation = {
        code: {
            unit_id
            for unit_id, outcome_code in db.query(
                DomesticReportUnit.unit_id,
                DomesticReportUnit.outcome_code,
            ).filter(DomesticReportUnit.log_id == dispatch["log_id"])
            if outcome_code == code
        }
        for code in ("dandong", "lixiaohong")
    }
    assert len(allocation["dandong"]) == 12
    assert len(allocation["lixiaohong"]) == 8
    assert allocation["dandong"].isdisjoint(allocation["lixiaohong"])
    assert allocation["dandong"] | allocation["lixiaohong"] == set(dispatch["unit_ids"])

    steps = {step["process_id"]: step for step in progress_service.build_progress_view(db, case.item)}
    dandong = steps[case.route.process_ids[2]]
    lixiaohong = steps[case.route.process_ids[3]]
    assert (dandong["reportable_qty"], dandong["skipped_qty"]) == (12, 8)
    assert (lixiaohong["reportable_qty"], lixiaohong["skipped_qty"]) == (8, 0)

    _submit(db, case, 2, 12)
    lixiaohong = progress_service.build_progress_view(db, case.item)[3]
    assert (lixiaohong["reportable_qty"], lixiaohong["skipped_qty"]) == (8, 12)

    workload = db.query(func.sum(DomesticReportLog.report_qty)).filter(
        DomesticReportLog.reported_by_user_id == case.worker.id,
        DomesticReportLog.process_id == case.route.process_ids[1],
        DomesticReportLog.revoked == 0,
    ).scalar()
    assert workload == 20
    assert db.query(func.sum(DomesticSkipLog.skip_qty)).scalar() == 20


def test_decision_quantity_allocation_follows_option_and_unit_order(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    result = _submit(
        db,
        case,
        1,
        20,
        outcomes={"dandong": 12, "lixiaohong": 8},
    )
    rows = db.query(
        DomesticItemUnit.unit_no,
        DomesticReportUnit.outcome_code,
    ).join(
        DomesticReportUnit, DomesticReportUnit.unit_id == DomesticItemUnit.id,
    ).filter(
        DomesticReportUnit.log_id == result["log_id"],
    ).order_by(DomesticItemUnit.unit_no).all()
    assert rows == [
        *[(number, "dandong") for number in range(1, 13)],
        *[(number, "lixiaohong") for number in range(13, 21)],
    ]


def test_future_skip_does_not_let_unit_leap_over_unfinished_branch(db, conditional_order):
    case = conditional_order
    route_rule_service.save_rules(db, case.route.id, [
        _decision(case.route.process_ids[1], [
            {
                "code": "dandong",
                "label": "丹东",
                "skip_process_ids": [case.route.process_ids[3], case.route.process_ids[4]],
            },
            {
                "code": "lixiaohong",
                "label": "李晓宏",
                "skip_process_ids": [case.route.process_ids[2]],
            },
        ]),
        {"process_id": case.route.process_ids[4], "rule_type": "optional", "config": None},
    ])
    _submit(db, case, 0, 20)
    _submit(db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8})

    before_branch = progress_service.build_progress_view(db, case.item)
    assert before_branch[4]["skipped_qty"] == 0
    intake = before_branch[5]
    assert intake["reportable_qty"] == 0
    with pytest.raises(ValueError, match="上一道工序还没做出"):
        _submit(db, case, 5, 1)

    _submit(db, case, 2, 12)
    after_branch = progress_service.build_progress_view(db, case.item)
    assert after_branch[4]["skipped_qty"] == 12


def test_decision_validates_outcome_shape_for_quantity_and_unit_modes(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    with pytest.raises(ValueError, match="必须包含全部结果选项"):
        _submit(db, case, 1, 1, outcomes={"dandong": 1})
    with pytest.raises(ValueError, match="合计必须等于报工数量"):
        _submit(db, case, 1, 2, outcomes={"dandong": 1, "lixiaohong": 0})

    unit = db.query(DomesticItemUnit).filter_by(item_id=case.item.id, unit_no=1).one()
    normalized = _submit(
        db,
        case,
        1,
        1,
        unit_id=unit.id,
        outcomes={"dandong": 1, "lixiaohong": 0},
    )
    assert normalized["outcomes"] == {"dandong": 1}

    second_unit = db.query(DomesticItemUnit).filter_by(item_id=case.item.id, unit_no=2).one()
    result = _submit(
        db, case, 1, 1, unit_id=second_unit.id, outcomes={"lixiaohong": 1},
    )
    assert result["outcomes"] == {"lixiaohong": 1}


def test_required_and_optional_steps_reject_outcomes(db, conditional_order):
    case = conditional_order
    with pytest.raises(ValueError, match="不是分流判定工序"):
        _submit(db, case, 0, 1, outcomes={"unexpected": 1})


def test_optional_predecessor_is_bypassed_by_downstream_report(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    _submit(db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8})
    _submit(db, case, 2, 12)
    _submit(db, case, 3, 8)

    # 先对5件实际定型，再入库12件；入库应优先使用已定型5件，再自动绕过7件。
    optional = _submit(db, case, 4, 5)
    intake = _submit(db, case, 5, 12)
    assert intake["unit_ids"][:5] == optional["unit_ids"]
    bypass = db.query(DomesticSkipLog).filter_by(
        source="optional_bypass",
        trigger_report_log_id=intake["log_id"],
        revoked=0,
    ).one()
    assert bypass.skip_qty == 7
    assert {
        row.unit_id for row in db.query(DomesticSkipUnit).filter_by(skip_log_id=bypass.id)
    } == set(intake["unit_ids"][5:])

    steps = progress_service.build_progress_view(db, case.item)
    assert (steps[4]["completed_qty"], steps[4]["skipped_qty"], steps[4]["passed_qty"]) == (5, 7, 12)
    assert steps[5]["completed_qty"] == 12

    _submit(db, case, 5, 8)
    db.refresh(case.item)
    order = db.query(DomesticOrder).get(case.item.order_id)
    finished = progress_service.build_progress_view(db, case.item)
    assert (finished[4]["completed_qty"], finished[4]["skipped_qty"], finished[4]["passed_qty"]) == (5, 15, 20)
    assert finished[5]["passed_qty"] == 20
    assert case.item.status == 1
    assert order.status == 2


def test_optional_bypass_unit_mode_only_uses_scanned_unit(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    _submit(db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8})
    _submit(db, case, 2, 12)
    _submit(db, case, 3, 8)
    unit = db.query(DomesticItemUnit).filter_by(item_id=case.item.id, unit_no=9).one()

    result = _submit(db, case, 5, 1, unit_id=unit.id)
    bypass = db.query(DomesticSkipLog).filter_by(
        source="optional_bypass", trigger_report_log_id=result["log_id"], revoked=0
    ).one()
    assert bypass.skip_qty == 1
    assert db.query(DomesticSkipUnit.unit_id).filter_by(skip_log_id=bypass.id).scalar() == unit.id


def test_optional_bypass_rejects_unit_before_pre_optional_step(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 1)
    unit = db.query(DomesticItemUnit).filter_by(item_id=case.item.id, unit_no=1).one()
    with pytest.raises(ValueError, match="上一道工序还没做出"):
        _submit(db, case, 5, 1, unit_id=unit.id)


def test_decision_request_replay_compares_normalized_outcomes(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    request_id = str(uuid4())
    first = _submit(
        db,
        case,
        1,
        20,
        outcomes={"dandong": 12, "lixiaohong": 8},
        request_id=request_id,
    )
    route_rule_service.save_rules(db, case.route.id, [
        _decision(case.route.process_ids[1], [
            {"code": "new_left", "label": "新左线", "skip_process_ids": []},
            {"code": "new_right", "label": "新右线", "skip_process_ids": []},
        ]),
        {"process_id": case.route.process_ids[4], "rule_type": "optional", "config": None},
    ])
    replay = _submit(
        db,
        case,
        1,
        20,
        outcomes={"lixiaohong": 8, "dandong": 12},
        request_id=request_id,
    )
    assert replay["log_id"] == first["log_id"]
    assert replay["replayed"] is True
    assert replay["outcomes"] == first["outcomes"]
    assert replay["unit_outcomes"] == first["unit_outcomes"]

    with pytest.raises(ValueError, match="请求号已用于另一笔报工"):
        _submit(
            db,
            case,
            1,
            20,
            outcomes={"dandong": 11, "lixiaohong": 9},
            request_id=request_id,
        )
