"""内贸条件路线规则的持久化与校验契约。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.domestic import route_rule_service
from app.domestic.models import DomesticRouteRule
from app.domestic.schemas import RouteRuleSaveRequest
from app.production.models import Process, ProcessRoute, ProcessRouteStep


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
