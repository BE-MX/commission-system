"""Guarded domestic attribute dictionary and route cutover tests."""

import subprocess
import sys
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.auth.models import ArkUser
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticCustomer,
    DomesticOrder,
    DomesticOrderItem,
    DomesticProduct,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep
from app.system.models import SysDict
from scripts import domestic_attribute_cutover as cutover


EXPECTED_STANDARD_VALUES = {
    "domestic_cap_craft": ["递旋", "中分界", "左分界", "大U型", "递顶"],
    "domestic_cap_net_color": [
        "紫网全头套",
        "绿网全头套",
        "红网全头套",
        "绿网九分头",
        "黑网九分头",
        "特单网帽",
    ],
    "domestic_cap_size": ["SS", "S", "M", "L", "XL", "51", "53", "57", "59", "取模定制"],
    "domestic_cap_length": [f"{length}厘米" for length in range(15, 61, 5)],
    "domestic_cap_density": ["65%", "80%", "90%"],
    "domestic_cap_hair_style_series": [
        "直发",
        "纹理",
        "卷发",
        "毛坯",
        "来图直发",
        "来图纹理",
        "来图卷发",
    ],
    "domestic_piece_craft_size": [
        "U型13*15",
        "U型14*16",
        "U型16*18",
        "全递针9*14",
        "全递针12*14",
        "全递针13*15",
        "全递针14*16",
        "全递针15*17",
        "特单发片",
    ],
    "domestic_piece_length": [f"{length}厘米" for length in range(20, 41, 5)],
    "domestic_order_type": [
        ("first_order", "首单"),
        ("repurchase", "复购"),
        ("return_order", "返单"),
        ("supplementary", "补单"),
        ("after_sales_remake", "售后重做"),
    ],
    "domestic_order_channel": [
        ("wechat", "微信"),
        ("phone", "电话"),
        ("exhibition", "展会"),
        ("offline_visit", "线下拜访"),
        ("other", "其他"),
    ],
}


def test_standalone_cli_import_registers_foreign_key_targets():
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from scripts import domestic_attribute_cutover; "
                "from app.core.database import Base; "
                "assert 'ark_users' in Base.metadata.tables"
            ),
        ],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _dict_rows(db, dict_type):
    return (
        db.query(SysDict)
        .filter(SysDict.type == dict_type)
        .order_by(SysDict.sort.asc(), SysDict.id.asc())
        .all()
    )


def _codes_and_labels(db, dict_type):
    return [(row.code, row.label) for row in _dict_rows(db, dict_type)]


@pytest.fixture
def cutover_case(db):
    operator = ArkUser(
        username="attribute-cutover-operator",
        password_hash="x",
        real_name="属性切换操作员",
        is_active=True,
    )
    db.add(operator)
    db.flush()

    old_route = ProcessRoute(name="旧内贸路线", status=1)
    cap_route = ProcessRoute(name="头套网帽（递针）", status=1)
    piece_route = ProcessRoute(name="发片网底（递针）", status=1)
    db.add_all([old_route, cap_route, piece_route])
    db.flush()
    old_process = Process(name="旧内贸工序", status=1)
    cap_process = Process(name="头套有效工序", status=1)
    piece_process = Process(name="发片有效工序", status=1)
    db.add_all([old_process, cap_process, piece_process])
    db.flush()
    db.add_all([
        ProcessRouteStep(route_id=old_route.id, process_id=old_process.id, step_order=1),
        ProcessRouteStep(route_id=cap_route.id, process_id=cap_process.id, step_order=1),
        ProcessRouteStep(route_id=piece_route.id, process_id=piece_process.id, step_order=1),
    ])

    db.add_all([
        SysDict(type="domestic_cap_craft", code="旧头套工艺", label="旧头套工艺", sort=1),
        SysDict(type="domestic_cap_size", code="old-size", label="旧尺码", sort=1),
        SysDict(type="domestic_piece_craft_size", code="旧合并工艺", label="旧合并工艺", sort=1),
        SysDict(type="domestic_net_color", code="旧网色", label="旧网色", sort=1),
        SysDict(type="domestic_piece_craft", code="旧发片工艺", label="旧发片工艺", sort=1),
        SysDict(type="domestic_piece_size", code="旧发片尺码", label="旧发片尺码", sort=1),
        SysDict(type="domestic_length", code="旧长度", label="旧长度", sort=1),
        SysDict(type="domestic_density", code="旧发量", label="旧发量", sort=1),
        SysDict(
            type="domestic_cap_craft_special",
            code="特制头套工艺",
            label="特制头套工艺",
            sort=0,
        ),
        SysDict(
            type="domestic_piece_craft_size_special",
            code="特制发片工艺",
            label="特制发片工艺",
            sort=0,
        ),
        SysDict(
            type="domestic_net_color_special",
            code="历史特单网色",
            label="历史特单网色",
            sort=0,
        ),
    ])
    db.add_all([
        DomesticCraftRoute(
            product_type="cap",
            craft="旧头套工艺",
            route_id=old_route.id,
            updated_by=operator.id,
        ),
        DomesticCraftRoute(
            product_type="piece",
            craft="旧发片工艺",
            route_id=old_route.id,
            updated_by=operator.id,
        ),
        DomesticCraftRoute(
            product_type="cap",
            craft="特制头套工艺",
            route_id=old_route.id,
            updated_by=operator.id,
        ),
        DomesticCraftRoute(
            product_type="piece",
            craft="特制发片工艺",
            route_id=old_route.id,
            updated_by=operator.id,
        ),
    ])

    cap_product = DomesticProduct(
        attrs_key="history-cap",
        name="历史头套产品",
        product_type="cap",
        craft="旧头套工艺",
        size="M",
        length="20厘米",
        density=None,
        route_id=old_route.id,
        status=1,
    )
    piece_product = DomesticProduct(
        attrs_key="history-piece",
        name="历史发片产品",
        product_type="piece",
        craft="旧发片工艺",
        size=None,
        length="20厘米",
        density=None,
        route_id=old_route.id,
        status=1,
    )
    customer = DomesticCustomer(
        shop_name="属性切换历史客户",
        balance=Decimal("1000"),
        status=1,
        created_by=operator.id,
    )
    db.add_all([cap_product, piece_product, customer])
    db.flush()
    order = DomesticOrder(
        domestic_no="DO20260901-902",
        order_no="ATTR-HISTORY-1",
        order_date=date(2026, 9, 1),
        customer_id=customer.id,
        order_category="normal",
        order_type=None,
        order_channel=None,
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
    attrs_snapshot = {"craft": "旧头套工艺", "length": "20厘米"}
    item = DomesticOrderItem(
        order_id=order.id,
        line_no=1,
        product_id=cap_product.id,
        product_name=cap_product.name,
        attrs_snapshot=deepcopy(attrs_snapshot),
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
    db.add(item)
    db.commit()
    return {
        "old_route": old_route,
        "cap_route": cap_route,
        "piece_route": piece_route,
        "cap_process": cap_process,
        "piece_process": piece_process,
        "cap_product": cap_product,
        "piece_product": piece_product,
        "order": order,
        "item": item,
        "attrs_snapshot": attrs_snapshot,
    }


def test_preflight_reports_exact_values_deterministically_without_writes(db, cutover_case):
    before = _codes_and_labels(db, "domestic_cap_craft")

    first = cutover.build_plan(db)
    second = cutover.build_plan(db)

    assert first == second
    assert first["mode"] == "preflight"
    assert first["routes"] == {
        "cap": {
            "id": cutover_case["cap_route"].id,
            "name": "头套网帽（递针）",
            "enabled_step_count": 1,
        },
        "piece": {
            "id": cutover_case["piece_route"].id,
            "name": "发片网底（递针）",
            "enabled_step_count": 1,
        },
    }
    assert first["history_unchanged"] == {
        "products": 2,
        "orders": 1,
        "order_items": 1,
        "product_route_id": True,
        "order_item_attrs_snapshot": True,
        "order_item_route_id": True,
        "orders_deleted": False,
    }
    additions = first["dictionary_changes"]["add"]
    actual = {}
    for row in additions:
        actual.setdefault(row["type"], []).append((row["code"], row["label"]))
    expected = {
        dict_type: [
            value if isinstance(value, tuple) else (value, value)
            for value in values
        ]
        for dict_type, values in EXPECTED_STANDARD_VALUES.items()
    }
    assert actual == expected
    assert _codes_and_labels(db, "domestic_cap_craft") == before


@pytest.mark.parametrize("failure", ["missing", "disabled", "empty", "disabled_process"])
def test_invalid_target_route_blocks_preflight_and_apply(db, cutover_case, failure):
    route = cutover_case["piece_route"]
    if failure == "missing":
        db.delete(route)
    elif failure == "disabled":
        route.status = 0
    elif failure == "empty":
        db.query(ProcessRouteStep).filter_by(route_id=route.id).delete()
    else:
        cutover_case["piece_process"].status = 0
    db.commit()

    match = {
        "missing": "不存在",
        "disabled": "已停用",
        "empty": "没有启用工序",
        "disabled_process": "没有启用工序",
    }[failure]
    with pytest.raises(cutover.CutoverError, match=match):
        cutover.build_plan(db)
    with pytest.raises(cutover.CutoverError, match=match):
        cutover.apply_cutover(db, writes_stopped=True)
    assert _codes_and_labels(db, "domestic_cap_craft") == [("旧头套工艺", "旧头套工艺")]


def test_apply_replaces_standard_data_and_preserves_special_and_history(db, cutover_case):
    special_before = {
        row.type: (row.code, row.label, row.sort, row.is_active)
        for row in db.query(SysDict).filter(SysDict.type.like("%_special")).all()
    }
    history_before = {
        "product_routes": [cutover_case["cap_product"].route_id, cutover_case["piece_product"].route_id],
        "order_id": cutover_case["order"].id,
        "item_route": cutover_case["item"].route_id,
        "attrs": deepcopy(cutover_case["item"].attrs_snapshot),
    }

    result = cutover.apply_cutover(db, writes_stopped=True)

    assert result["mode"] == "applied"
    for dict_type, values in EXPECTED_STANDARD_VALUES.items():
        expected = [value if isinstance(value, tuple) else (value, value) for value in values]
        assert _codes_and_labels(db, dict_type) == expected
    for obsolete_type in cutover.OBSOLETE_DICT_TYPES:
        assert _dict_rows(db, obsolete_type) == []
    special_after = {
        row.type: (row.code, row.label, row.sort, row.is_active)
        for row in db.query(SysDict).filter(SysDict.type.like("%_special")).all()
    }
    assert special_after == special_before

    mappings = {
        (row.product_type, row.craft): (row.route_id, row.updated_by)
        for row in db.query(DomesticCraftRoute).all()
    }
    for craft in EXPECTED_STANDARD_VALUES["domestic_cap_craft"]:
        assert mappings[("cap", craft)] == (cutover_case["cap_route"].id, None)
    for craft in EXPECTED_STANDARD_VALUES["domestic_piece_craft_size"]:
        assert mappings[("piece", craft)] == (cutover_case["piece_route"].id, None)
    assert mappings[("cap", "特制头套工艺")][0] == cutover_case["old_route"].id
    assert mappings[("piece", "特制发片工艺")][0] == cutover_case["old_route"].id
    assert ("cap", "旧头套工艺") not in mappings
    assert ("piece", "旧发片工艺") not in mappings

    for key in ("cap_product", "piece_product", "order", "item"):
        db.refresh(cutover_case[key])
    assert [cutover_case["cap_product"].route_id, cutover_case["piece_product"].route_id] == history_before["product_routes"]
    assert cutover_case["order"].id == history_before["order_id"]
    assert cutover_case["item"].route_id == history_before["item_route"]
    assert cutover_case["item"].attrs_snapshot == history_before["attrs"]
    assert db.query(DomesticOrder).count() == 1


def test_second_apply_is_idempotent(db, cutover_case):
    cutover.apply_cutover(db, writes_stopped=True)
    first_dict_rows = [
        (row.id, row.type, row.code, row.label, row.sort, row.is_active)
        for row in db.query(SysDict).order_by(SysDict.id.asc()).all()
    ]
    first_mappings = [
        (row.id, row.product_type, row.craft, row.route_id, row.updated_by)
        for row in db.query(DomesticCraftRoute).order_by(DomesticCraftRoute.id.asc()).all()
    ]

    result = cutover.apply_cutover(db, writes_stopped=True)

    second_dict_rows = [
        (row.id, row.type, row.code, row.label, row.sort, row.is_active)
        for row in db.query(SysDict).order_by(SysDict.id.asc()).all()
    ]
    second_mappings = [
        (row.id, row.product_type, row.craft, row.route_id, row.updated_by)
        for row in db.query(DomesticCraftRoute).order_by(DomesticCraftRoute.id.asc()).all()
    ]
    assert result["mode"] == "applied"
    assert second_dict_rows == first_dict_rows
    assert second_mappings == first_mappings


def test_apply_rolls_back_if_mapping_replacement_fails(db, cutover_case, monkeypatch):
    before = _codes_and_labels(db, "domestic_cap_craft")

    def fail_mapping_replacement(*_args, **_kwargs):
        raise RuntimeError("injected mapping failure")

    monkeypatch.setattr(cutover, "_replace_standard_mappings", fail_mapping_replacement)
    with pytest.raises(RuntimeError, match="injected mapping failure"):
        cutover.apply_cutover(db, writes_stopped=True)

    assert _codes_and_labels(db, "domestic_cap_craft") == before


def test_apply_requires_explicit_writes_stopped_confirmation(db, cutover_case):
    with pytest.raises(cutover.CutoverError, match="DOMESTIC_WRITES_STOPPED"):
        cutover.apply_cutover(db, writes_stopped=False)


def test_cli_defaults_to_preflight_and_apply_requires_explicit_flag(monkeypatch, capsys):
    calls = []

    class FakeSession:
        def rollback(self):
            calls.append("rollback")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(cutover, "SessionLocal", FakeSession)
    monkeypatch.setattr(cutover, "build_plan", lambda _db: {"mode": "preflight"})
    monkeypatch.setattr(
        cutover,
        "apply_cutover",
        lambda _db, *, writes_stopped: calls.append(("apply", writes_stopped))
        or {"mode": "applied"},
    )

    assert cutover.main([]) == 0
    assert '"mode": "preflight"' in capsys.readouterr().out
    assert "apply" not in calls
    assert cutover.main(["--apply"]) == 2
    assert "DOMESTIC_WRITES_STOPPED" in capsys.readouterr().err
    assert cutover.main([
        "--apply",
        "--confirm-writes-stopped",
        "WRITES_NOT_ACTUALLY_STOPPED",
    ]) == 2
    assert "DOMESTIC_WRITES_STOPPED" in capsys.readouterr().err
    assert cutover.main([
        "--apply",
        "--confirm-writes-stopped",
        "DOMESTIC_WRITES_STOPPED",
    ]) == 0
    assert '"mode": "applied"' in capsys.readouterr().out
    assert calls.count(("apply", True)) == 1
