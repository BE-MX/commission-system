"""内贸条件路线规则与逐件分流的状态机契约。"""

import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from pydantic import ValidationError

from app.auth.models import ArkUser
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic import constants as C
from app.domestic import order_service, progress_service, report_service, routing_service, unit_service
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
from app.domestic.schemas import ManualSkipSubmit, RouteRuleSaveRequest
from app.production import route_service as production_route_service
from app.production.models import (
    Process,
    ProcessRoute,
    ProcessRouteStep,
    UserProcessBinding,
)


def test_domestic_route_migration_is_the_only_head_after_customer_126():
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    revisions = ScriptDirectory.from_config(config)

    assert revisions.get_heads() == ["127_domestic_route_rules"]
    assert revisions.get_revision("127_domestic_route_rules").down_revision == "126"


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


def test_route_rule_model_restricts_deleting_a_configured_route_step():
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
        "RESTRICT",
    ) in composite_fks


def _route_config_payload(process_ids, rules):
    return {
        "steps": [{"process_id": process_id} for process_id in process_ids],
        "rules": rules,
    }


def _route_config_client(db, user_id, permissions):
    from app.domestic.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user_id),
        "roles": [],
        "permissions": permissions,
    }
    return TestClient(app)


def test_production_only_step_save_blocks_changed_conditional_route_atomically(
    db, conditional_route,
):
    initial_rule = {
        "process_id": conditional_route.process_ids[1],
        "rule_type": "optional",
        "config": None,
    }
    route_rule_service.save_rules(db, conditional_route.id, [initial_rule])
    original_ids = list(conditional_route.process_ids)

    with pytest.raises(ValueError, match="需同时具备生产和内贸权限"):
        production_route_service.save_route_steps(
            db,
            conditional_route.id,
            [{"process_id": process_id} for process_id in reversed(original_ids)],
        )

    assert [row["process_id"] for row in production_route_service.get_route_steps(
        db, conditional_route.id,
    )] == original_ids
    assert [row["process_id"] for row in route_rule_service.list_rules(
        db, conditional_route.id,
    )] == [conditional_route.process_ids[1]]


def test_production_only_step_save_allows_routes_without_domestic_rules(
    db, conditional_route,
):
    reordered = list(reversed(conditional_route.process_ids))

    saved = production_route_service.save_route_steps(
        db,
        conditional_route.id,
        [{"process_id": process_id} for process_id in reordered],
    )

    assert [row["process_id"] for row in saved] == reordered


def test_production_only_same_steps_are_noop_for_conditional_route(
    db, conditional_route,
):
    rule = {
        "process_id": conditional_route.process_ids[1],
        "rule_type": "optional",
        "config": None,
    }
    route_rule_service.save_rules(db, conditional_route.id, [rule])
    original_step_ids = [row.id for row in db.query(ProcessRouteStep).filter_by(
        route_id=conditional_route.id,
    ).order_by(ProcessRouteStep.step_order).all()]

    saved = production_route_service.save_route_steps(
        db,
        conditional_route.id,
        [{"process_id": process_id} for process_id in conditional_route.process_ids],
    )

    assert [row["id"] for row in saved] == original_step_ids
    assert route_rule_service.list_rules(db, conditional_route.id)[0]["rule_type"] == "optional"


def test_atomic_route_configuration_requires_both_admin_permissions(
    db, conditional_route,
):
    admin = ArkUser(
        username="route-config-admin", password_hash="x", real_name="路线管理员",
    )
    db.add(admin)
    db.commit()
    payload = _route_config_payload(conditional_route.process_ids, [])

    for permissions in (["production:admin"], ["domestic:admin"]):
        response = _route_config_client(db, admin.id, permissions).put(
            f"/api/domestic/process-routes/{conditional_route.id}/configuration",
            json=payload,
        )
        assert response.status_code == 403


def test_atomic_route_configuration_updates_steps_and_rules_together(
    db, conditional_route,
):
    admin = ArkUser(
        username="route-config-success", password_hash="x", real_name="路线管理员",
    )
    db.add(admin)
    db.commit()
    reordered = [
        conditional_route.process_ids[0],
        conditional_route.process_ids[2],
        conditional_route.process_ids[1],
        *conditional_route.process_ids[3:],
    ]
    rule = {
        "process_id": conditional_route.process_ids[2],
        "rule_type": "optional",
        "config": None,
    }

    response = _route_config_client(
        db, admin.id, ["production:admin", "domestic:admin"],
    ).put(
        f"/api/domestic/process-routes/{conditional_route.id}/configuration",
        json=_route_config_payload(reordered, [rule]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [step["process_id"] for step in data["steps"]] == reordered
    assert [saved["process_id"] for saved in data["rules"]] == [
        conditional_route.process_ids[2],
    ]


def test_atomic_route_configuration_invalid_rules_rolls_back_steps_and_rules(
    db, conditional_route,
):
    admin = ArkUser(
        username="route-config-rollback", password_hash="x", real_name="路线管理员",
    )
    db.add(admin)
    original_rule = {
        "process_id": conditional_route.process_ids[1],
        "rule_type": "optional",
        "config": None,
    }
    route_rule_service.save_rules(db, conditional_route.id, [original_rule])
    db.commit()

    response = _route_config_client(
        db, admin.id, ["production:admin", "domestic:admin"],
    ).put(
        f"/api/domestic/process-routes/{conditional_route.id}/configuration",
        json=_route_config_payload(
            list(reversed(conditional_route.process_ids)),
            [{"process_id": 999999, "rule_type": "optional", "config": None}],
        ),
    )

    assert response.status_code == 400
    db.expire_all()
    assert [row["process_id"] for row in production_route_service.get_route_steps(
        db, conditional_route.id,
    )] == conditional_route.process_ids
    saved_rules = route_rule_service.list_rules(db, conditional_route.id)
    assert [(rule["process_id"], rule["rule_type"]) for rule in saved_rules] == [
        (conditional_route.process_ids[1], "optional"),
    ]


def test_atomic_route_configuration_reorder_cannot_move_skip_target_before_trigger(
    db, conditional_route,
):
    admin = ArkUser(
        username="route-config-order", password_hash="x", real_name="路线管理员",
    )
    db.add(admin)
    decision = _decision(conditional_route.process_ids[1], [
        {
            "code": "skip_later",
            "label": "跳过后续",
            "skip_process_ids": [conditional_route.process_ids[3]],
        },
        {"code": "normal", "label": "正常", "skip_process_ids": []},
    ])
    route_rule_service.save_rules(db, conditional_route.id, [decision])
    db.commit()
    invalid_order = [
        conditional_route.process_ids[0],
        conditional_route.process_ids[3],
        conditional_route.process_ids[1],
        conditional_route.process_ids[2],
        *conditional_route.process_ids[4:],
    ]

    response = _route_config_client(
        db, admin.id, ["production:admin", "domestic:admin"],
    ).put(
        f"/api/domestic/process-routes/{conditional_route.id}/configuration",
        json=_route_config_payload(invalid_order, [decision]),
    )

    assert response.status_code == 400
    assert "必须位于触发工序之后" in response.json()["detail"]
    db.expire_all()
    assert [row["process_id"] for row in production_route_service.get_route_steps(
        db, conditional_route.id,
    )] == conditional_route.process_ids
    assert route_rule_service.list_rules(db, conditional_route.id)[0]["config"][
        "options"
    ][0]["skip_process_ids"] == [conditional_route.process_ids[3]]


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


def test_public_tracking_whitelists_steps_and_counts_skips_as_progress(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    _submit(db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8})
    _submit(db, case, 2, 12)
    _submit(db, case, 3, 8)
    _submit(db, case, 5, 20)

    public_item = order_service.get_order_detail(
        db,
        case.item.order_id,
        public_progress_only=True,
        include_finance=False,
    )["items"][0]
    expected_fields = {
        "step_order",
        "process_name",
        "order_qty",
        "completed_qty",
        "skipped_qty",
        "passed_qty",
        "required_qty",
        "reportable_qty",
        "status",
    }
    assert public_item["steps"]
    assert all(set(step) == expected_fields for step in public_item["steps"])
    assert public_item["steps"][4]["completed_qty"] == 0
    assert public_item["steps"][4]["passed_qty"] == 20
    assert public_item["current_process"] == "完成"
    assert public_item["progress_pct"] == 100.0

    internal_item = order_service.get_order_detail(db, case.item.order_id)["items"][0]
    assert "progress_id" in internal_item["steps"][0]
    assert "process_id" in internal_item["steps"][0]
    assert "last_reported_by" in internal_item["steps"][0]
    assert "rule_type" in internal_item["steps"][0]


def test_internal_detail_and_order_list_count_passed_units_as_progress(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    _submit(db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8})
    _submit(db, case, 2, 12)
    _submit(db, case, 3, 8)
    _submit(db, case, 5, 20)

    internal_item = order_service.get_order_detail(db, case.item.order_id)["items"][0]
    optional_step = internal_item["steps"][4]
    assert optional_step["completed_qty"] == 0
    assert optional_step["passed_qty"] == 20
    assert internal_item["current_process"] == "完成"
    assert internal_item["progress_pct"] == 100.0

    order_rows, total = order_service.list_orders(db)
    order_row = next(row for row in order_rows if row["id"] == case.item.order_id)
    assert total == 1
    assert order_row["progress_pct"] == 100.0


def test_order_progress_without_rules_keeps_strict_linear_semantics(db, conditional_order):
    case = conditional_order
    db.query(DomesticRouteRule).filter_by(route_id=case.route.id).delete(
        synchronize_session=False,
    )
    db.flush()

    _submit(db, case, 0, 20)
    _submit(db, case, 1, 20)

    internal_item = order_service.get_order_detail(db, case.item.order_id)["items"][0]
    assert internal_item["current_process"] == case.route.process_names[2]
    assert internal_item["progress_pct"] == 33.3

    order_rows, _ = order_service.list_orders(db)
    order_row = next(row for row in order_rows if row["id"] == case.item.order_id)
    assert order_row["progress_pct"] == 33.3


def test_order_list_preserves_legacy_progress_without_unit_identities(db, conditional_order):
    case = conditional_order
    db.query(DomesticItemUnit).filter_by(item_id=case.item.id).delete(
        synchronize_session=False,
    )
    case.rows[0].completed_qty = 20
    case.rows[1].completed_qty = 10
    db.flush()

    order_rows, _ = order_service.list_orders(db)
    order_row = next(row for row in order_rows if row["id"] == case.item.order_id)
    assert order_row["progress_pct"] == 25.0


def test_order_list_never_falls_back_when_active_units_exist(db, conditional_order):
    case = conditional_order
    case.rows[0].completed_qty = 20
    case.rows[1].completed_qty = 10
    db.flush()

    order_rows, _ = order_service.list_orders(db)
    order_row = next(row for row in order_rows if row["id"] == case.item.order_id)
    assert order_row["progress_pct"] == 0.0


def test_order_list_without_progress_steps_remains_zero(db, conditional_order):
    case = conditional_order
    db.query(DomesticItemProgress).filter_by(item_id=case.item.id).delete(
        synchronize_session=False,
    )
    db.flush()

    order_rows, _ = order_service.list_orders(db)
    order_row = next(row for row in order_rows if row["id"] == case.item.order_id)
    assert order_row["progress_pct"] == 0.0


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


def _finish_parallel_branches(db, case):
    _submit(db, case, 0, 20)
    _submit(db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8})
    _submit(db, case, 2, 12)
    _submit(db, case, 3, 8)


def test_revoke_decision_removes_its_generated_skips(db, conditional_order):
    case = conditional_order
    _submit(db, case, 0, 20)
    decision = _submit(
        db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8},
    )

    result = report_service.revoke_report(
        db, decision["log_id"], case.worker.id,
    )

    assert result["revoked_qty"] == 20
    assert db.query(DomesticSkipLog).filter_by(
        trigger_report_log_id=decision["log_id"], revoked=0,
    ).count() == 0
    assert db.query(DomesticSkipLog).filter_by(
        trigger_report_log_id=decision["log_id"], revoked=1,
    ).count() == 2
    steps = progress_service.build_progress_view(db, case.item)
    assert steps[1]["completed_qty"] == 0
    assert steps[2]["skipped_qty"] == 0
    assert steps[3]["skipped_qty"] == 0


def test_revoke_decision_lists_earliest_downstream_process_and_units(
    db, conditional_order
):
    case = conditional_order
    _submit(db, case, 0, 20)
    decision = _submit(
        db, case, 1, 20, outcomes={"dandong": 12, "lixiaohong": 8},
    )
    _submit(db, case, 2, 1)

    with pytest.raises(ValueError) as exc_info:
        report_service.revoke_report(db, decision["log_id"], case.worker.id)

    message = str(exc_info.value)
    assert "A1-01" in message
    assert case.route.process_names[2] in message


def test_revoke_intake_removes_its_optional_bypass(db, conditional_order):
    case = conditional_order
    _finish_parallel_branches(db, case)
    intake = _submit(db, case, 5, 7)
    bypass = db.query(DomesticSkipLog).filter_by(
        source="optional_bypass",
        trigger_report_log_id=intake["log_id"],
    ).one()

    report_service.revoke_report(db, intake["log_id"], case.worker.id)

    db.refresh(bypass)
    assert bypass.revoked == 1
    steps = progress_service.build_progress_view(db, case.item)
    assert steps[4]["skipped_qty"] == 0
    assert steps[5]["completed_qty"] == 0


def test_manual_skip_is_idempotent_and_excluded_from_workload(db, conditional_order):
    case = conditional_order
    request_id = str(uuid4())
    first = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=3,
        unit_id=None,
        reason="现场主管确认该批无需此工序",
        request_id=request_id,
        user_id=case.worker.id,
    )
    replay = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=3,
        unit_id=None,
        reason=" 现场主管确认该批无需此工序 ",
        request_id=request_id,
        user_id=case.worker.id,
    )

    assert replay["skip_log_id"] == first["skip_log_id"]
    assert replay["replayed"] is True
    assert first["unit_codes"] == ["A1-01", "A1-02", "A1-03"]
    assert db.query(func.sum(DomesticReportLog.report_qty)).scalar() is None
    assert case.rows[0].completed_qty == 0
    step = progress_service.build_progress_view(db, case.item)[0]
    assert (step["completed_qty"], step["skipped_qty"], step["passed_qty"]) == (0, 3, 3)

    with pytest.raises(ValueError, match="请求号已用于另一笔跳过"):
        report_service.submit_manual_skip(
            db,
            item_id=case.item.id,
            progress_id=case.rows[0].id,
            qty=4,
            unit_id=None,
            reason="现场主管确认该批无需此工序",
            request_id=request_id,
            user_id=case.worker.id,
        )


def test_manual_skip_history_blocks_route_rebuild_and_item_delete(db, conditional_order):
    case = conditional_order
    report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=1,
        unit_id=None,
        reason="主管确认无需首道工序",
        request_id=str(uuid4()),
        user_id=case.worker.id,
    )

    with pytest.raises(ValueError, match="已有 1 条跳过记录"):
        progress_service.init_item_progress(db, case.item, route_id=case.route.id)

    with pytest.raises(ValueError, match="已有 1 条跳过记录"):
        order_service.delete_item(db, case.item.id, case.worker.id)


def test_attach_route_only_accepts_items_without_an_existing_route(db, conditional_order):
    case = conditional_order

    with pytest.raises(ValueError, match="已配置工艺路线"):
        order_service.attach_route(db, case.item.id, case.route.id)


def test_consecutive_optional_steps_keep_their_shared_upstream():
    rows = [
        SimpleNamespace(id=1, process_id=11),
        SimpleNamespace(id=2, process_id=12),
        SimpleNamespace(id=3, process_id=13),
        SimpleNamespace(id=4, process_id=14),
    ]
    unit_id = 101
    state = routing_service.PassageState(
        reported_by_progress={1: {unit_id}, 3: {unit_id}},
        skipped_by_progress={},
    )
    rules = {
        12: {"rule_type": route_rule_service.RULE_OPTIONAL},
        13: {"rule_type": route_rule_service.RULE_OPTIONAL},
    }

    upstream, _skipped, passed = routing_service.effective_passage_maps(
        rows, state, {unit_id}, rules,
    )

    assert upstream[4] == {unit_id}
    assert passed[4] == set()


def test_mini_submit_marks_concurrent_idempotency_result_as_retryable(monkeypatch, db):
    from app.mini import router as mini_router
    from app.mini.schemas import DomesticSubmitRequest

    worker = ArkUser(username="retryable-worker", password_hash="x", real_name="重试工")
    db.add(worker)
    db.flush()
    monkeypatch.setattr(mini_router, "_domestic_report_mode", lambda _user: "quantity")
    monkeypatch.setattr(
        mini_router.domestic_report_service,
        "submit_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("该报工请求正在并发处理，请使用同一请求号重试")
        ),
    )
    body = DomesticSubmitRequest(
        item_id=1,
        progress_id=1,
        qty=1,
        request_id="stable-request-id",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(mini_router.domestic_submit(body, current_user=worker, db=db))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "SUBMIT_PENDING",
        "message": "该报工请求正在并发处理，请使用同一请求号重试",
    }


def test_manual_skip_exact_unit_and_revoke_blocked_by_downstream_actual_work(
    db, conditional_order
):
    case = conditional_order
    unit = db.query(DomesticItemUnit).filter_by(item_id=case.item.id, unit_no=7).one()
    skipped = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=None,
        unit_id=unit.id,
        reason="现场主管确认该件无需此工序",
        request_id=str(uuid4()),
        user_id=case.worker.id,
    )
    _submit(
        db,
        case,
        1,
        1,
        unit_id=unit.id,
        outcomes={"dandong": 1},
    )

    with pytest.raises(ValueError) as exc_info:
        report_service.revoke_manual_skip(
            db, skipped["skip_log_id"], case.worker.id,
        )
    message = str(exc_info.value)
    assert "A1-07" in message
    assert case.route.process_names[1] in message


def test_two_sessions_cannot_double_allocate_same_item_manual_skip(
    db, engine, conditional_order
):
    case = conditional_order
    db.commit()
    Session = sessionmaker(bind=engine)
    first_db = Session()
    second_db = Session()
    try:
        first = report_service.submit_manual_skip(
            first_db,
            item_id=case.item.id,
            progress_id=case.rows[0].id,
            qty=12,
            unit_id=None,
            reason="第一位主管放行十二件产品",
            request_id=str(uuid4()),
            user_id=case.worker.id,
        )
        with pytest.raises(ValueError, match="最多只能跳过 8 件"):
            report_service.submit_manual_skip(
                second_db,
                item_id=case.item.id,
                progress_id=case.rows[0].id,
                qty=12,
                unit_id=None,
                reason="第二位主管尝试重复放行产品",
                request_id=str(uuid4()),
                user_id=case.worker.id,
            )
        assert len(first["unit_ids"]) == 12
        assert second_db.query(DomesticSkipUnit.unit_id).distinct().count() == 12
    finally:
        first_db.close()
        second_db.close()


def test_revoke_searches_all_later_steps_and_ignores_intermediate_skips(
    db, conditional_order
):
    case = conditional_order
    first = _submit(db, case, 0, 1)
    unit_id = first["unit_ids"][0]
    for step_index in (1, 2):
        report_service.submit_manual_skip(
            db,
            item_id=case.item.id,
            progress_id=case.rows[step_index].id,
            qty=None,
            unit_id=unit_id,
            reason="主管确认该件跨过中间工序",
            request_id=str(uuid4()),
            user_id=case.worker.id,
        )
    _submit(db, case, 3, 1, unit_id=unit_id)

    with pytest.raises(ValueError) as exc_info:
        report_service.revoke_report(db, first["log_id"], case.worker.id)
    message = str(exc_info.value)
    assert case.route.process_names[3] in message
    assert "A1-01" in message


def test_manual_skip_can_be_revoked_without_downstream_actual_work(
    db, conditional_order
):
    case = conditional_order
    skipped = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=2,
        unit_id=None,
        reason="主管确认两件无需首道工序",
        request_id=str(uuid4()),
        user_id=case.worker.id,
    )

    result = report_service.revoke_manual_skip(
        db, skipped["skip_log_id"], case.worker.id,
    )

    assert result["revoked_qty"] == 2
    audit = db.query(DomesticSkipLog).get(skipped["skip_log_id"])
    assert audit.revoked == 1
    assert progress_service.build_progress_view(db, case.item)[0]["passed_qty"] == 0


def test_manual_skip_audit_api_lists_active_and_revoked_only_for_admin(
    db, conditional_order
):
    case = conditional_order
    active = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=2,
        unit_id=None,
        reason="主管确认两件无需首道工序",
        request_id="manual-audit-active",
        user_id=case.worker.id,
    )
    revoked = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=1,
        unit_id=None,
        reason="主管确认一件无需首道工序",
        request_id="manual-audit-revoked",
        user_id=case.worker.id,
    )
    report_service.revoke_manual_skip(db, revoked["skip_log_id"], case.worker.id)

    automatic = DomesticSkipLog(
        item_id=case.item.id,
        progress_id=case.rows[1].id,
        skip_qty=1,
        source="decision",
        reason="分流自动跳过",
        trigger_report_log_id=None,
        created_by_user_id=case.worker.id,
    )
    optional = DomesticSkipLog(
        item_id=case.item.id,
        progress_id=case.rows[2].id,
        skip_qty=1,
        source="optional_bypass",
        reason="可选工序自动跳过",
        trigger_report_log_id=None,
        created_by_user_id=case.worker.id,
    )
    db.add_all([automatic, optional])
    db.commit()

    # 钉死 created_at 相同情况下仍按 id 倒序，避免翻页/审计顺序漂移。
    same_time = datetime(2026, 8, 31, 10, 0, 0)
    db.query(DomesticSkipLog).filter(
        DomesticSkipLog.id.in_([active["skip_log_id"], revoked["skip_log_id"]])
    ).update({DomesticSkipLog.created_at: same_time}, synchronize_session=False)
    db.commit()

    from app.domestic.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db

    def claims(permission):
        return {
            "sub": str(case.worker.id),
            "roles": [],
            "permissions": [permission],
        }

    app.dependency_overrides[get_current_user] = lambda: claims("domestic:read")
    client = TestClient(app)
    denied = client.get(
        "/api/domestic/reports/skips", params={"item_id": case.item.id}
    )
    assert denied.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: claims("domestic:admin")
    response = client.get(
        "/api/domestic/reports/skips", params={"item_id": case.item.id}
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200
    rows = response.json()["data"]
    assert [row["skip_log_id"] for row in rows] == [
        revoked["skip_log_id"], active["skip_log_id"],
    ]
    assert {row["skip_log_id"] for row in rows}.isdisjoint({automatic.id, optional.id})
    assert rows[0] == {
        "skip_log_id": revoked["skip_log_id"],
        "item_id": case.item.id,
        "progress_id": case.rows[0].id,
        "process_id": case.route.process_ids[0],
        "process_name": case.route.process_names[0],
        "skip_mode": "quantity",
        "skipped_qty": 1,
        "reason": "主管确认一件无需首道工序",
        "request_id": "manual-audit-revoked",
        "operator_id": case.worker.id,
        "operator_name": "分流工",
        "unit_ids": revoked["unit_ids"],
        "unit_codes": revoked["unit_codes"],
        "created_at": "2026-08-31T10:00:00",
        "revoked": True,
        "revoked_at": rows[0]["revoked_at"],
    }
    assert rows[0]["revoked_at"] is not None
    assert rows[1]["revoked"] is False
    assert rows[1]["revoked_at"] is None


def test_manual_skip_audit_api_returns_stable_error_for_missing_item(
    db, conditional_order
):
    from app.domestic.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(conditional_order.worker.id),
        "roles": [],
        "permissions": ["domestic:admin"],
    }
    response = TestClient(app).get(
        "/api/domestic/reports/skips", params={"item_id": 999999}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "订单明细不存在"


@pytest.mark.parametrize("reason", ["abcd", " " * 8, "x" * 501])
def test_manual_skip_schema_rejects_reason_after_stripping(reason):
    with pytest.raises(ValidationError):
        ManualSkipSubmit.model_validate({
            "item_id": 1,
            "progress_id": 1,
            "qty": 1,
            "reason": reason,
            "request_id": "stable-request-id",
        })


def test_manual_skip_schema_requires_exactly_one_selection_mode():
    base = {
        "item_id": 1,
        "progress_id": 1,
        "reason": "主管确认无需此工序",
        "request_id": "stable-request-id",
    }
    for selection in ({}, {"qty": 1, "unit_id": 2}):
        with pytest.raises(ValidationError):
            ManualSkipSubmit.model_validate({**base, **selection})


def test_manual_skip_request_id_distinguishes_quantity_and_unit_modes(
    db, conditional_order
):
    case = conditional_order
    request_id = str(uuid4())
    first = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=1,
        unit_id=None,
        reason="主管确认该件无需首道工序",
        request_id=request_id,
        user_id=case.worker.id,
    )

    with pytest.raises(ValueError, match="请求号已用于另一笔跳过"):
        report_service.submit_manual_skip(
            db,
            item_id=case.item.id,
            progress_id=case.rows[0].id,
            qty=None,
            unit_id=first["unit_ids"][0],
            reason="主管确认该件无需首道工序",
            request_id=request_id,
            user_id=case.worker.id,
        )


def test_manual_skip_replay_survives_item_shipping(db, conditional_order):
    case = conditional_order
    request_id = str(uuid4())
    first = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=2,
        unit_id=None,
        reason="主管确认两件无需首道工序",
        request_id=request_id,
        user_id=case.worker.id,
    )
    item = db.query(DomesticOrderItem).get(case.item.id)
    item.status = C.ITEM_SHIPPED
    db.commit()

    replay = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=2,
        unit_id=None,
        reason="主管确认两件无需首道工序",
        request_id=request_id,
        user_id=case.worker.id,
    )

    assert replay["skip_log_id"] == first["skip_log_id"]
    assert replay["replayed"] is True


def test_report_request_unique_race_recovers_as_idempotent_replay(
    db, conditional_order, monkeypatch
):
    case = conditional_order
    request_id = str(uuid4())
    first = _submit(db, case, 0, 1, request_id=request_id)
    original = report_service._report_replay_if_exists
    calls = 0

    def hide_winner_until_recovery(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return None
        return original(*args, **kwargs)

    monkeypatch.setattr(
        report_service, "_report_replay_if_exists", hide_winner_until_recovery,
    )
    replay = _submit(db, case, 0, 1, request_id=request_id)

    assert replay["log_id"] == first["log_id"]
    assert replay["replayed"] is True


def test_manual_skip_request_unique_race_recovers_as_idempotent_replay(
    db, conditional_order, monkeypatch
):
    case = conditional_order
    request_id = str(uuid4())
    first = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=1,
        unit_id=None,
        reason="主管确认该件无需首道工序",
        request_id=request_id,
        user_id=case.worker.id,
    )
    original = report_service._manual_skip_replay_if_exists
    calls = 0

    def hide_winner_until_recovery(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original(*args, **kwargs)

    monkeypatch.setattr(
        report_service, "_manual_skip_replay_if_exists", hide_winner_until_recovery,
    )
    replay = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=1,
        unit_id=None,
        reason="主管确认该件无需首道工序",
        request_id=request_id,
        user_id=case.worker.id,
    )

    assert replay["skip_log_id"] == first["skip_log_id"]
    assert replay["replayed"] is True


def test_request_unique_race_with_different_payload_returns_stable_error(
    db, conditional_order, monkeypatch
):
    case = conditional_order
    request_id = str(uuid4())
    _submit(db, case, 0, 1, request_id=request_id)
    original = report_service._report_replay_if_exists
    calls = 0

    def hide_winner_until_recovery(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return None
        return original(*args, **kwargs)

    monkeypatch.setattr(
        report_service, "_report_replay_if_exists", hide_winner_until_recovery,
    )
    with pytest.raises(ValueError, match="请求号已用于另一笔报工"):
        _submit(db, case, 0, 2, request_id=request_id)


def test_request_deadlock_recovers_or_returns_retryable_business_error(
    db, conditional_order, monkeypatch
):
    case = conditional_order
    request_id = str(uuid4())
    first = _submit(db, case, 0, 1, request_id=request_id)

    def deadlock_once(*args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception(1213, "deadlock"))

    monkeypatch.setattr(report_service, "_submit_report_once", deadlock_once)
    replay = _submit(db, case, 0, 1, request_id=request_id)
    assert replay["log_id"] == first["log_id"]
    assert replay["replayed"] is True


def test_non_request_unique_integrity_error_is_not_swallowed(
    db, conditional_order, monkeypatch
):
    case = conditional_order

    def unrelated_unique(*args, **kwargs):
        raise IntegrityError(
            "INSERT", {}, Exception("UNIQUE constraint failed: some_other_table.code"),
        )

    monkeypatch.setattr(report_service, "_submit_report_once", unrelated_unique)
    with pytest.raises(IntegrityError):
        _submit(db, case, 0, 1, request_id=str(uuid4()))


def test_deadlock_without_visible_winner_returns_retryable_business_error(
    db, conditional_order, monkeypatch
):
    case = conditional_order

    def deadlock_once(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception(1213, "deadlock"))

    monkeypatch.setattr(report_service, "_submit_report_once", deadlock_once)
    with pytest.raises(ValueError, match="正在并发处理.*同一请求号重试"):
        _submit(db, case, 0, 1, request_id=str(uuid4()))


def test_manual_skip_deadlock_recovers_existing_winner(
    db, conditional_order, monkeypatch
):
    case = conditional_order
    request_id = str(uuid4())
    first = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=1,
        unit_id=None,
        reason="主管确认该件无需首道工序",
        request_id=request_id,
        user_id=case.worker.id,
    )

    def deadlock_once(*args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception(1213, "deadlock"))

    monkeypatch.setattr(report_service, "_submit_manual_skip_once", deadlock_once)
    replay = report_service.submit_manual_skip(
        db,
        item_id=case.item.id,
        progress_id=case.rows[0].id,
        qty=1,
        unit_id=None,
        reason="主管确认该件无需首道工序",
        request_id=request_id,
        user_id=case.worker.id,
    )
    assert replay["skip_log_id"] == first["skip_log_id"]
    assert replay["replayed"] is True
