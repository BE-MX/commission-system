"""内贸报工：数量流转 / 拆批 / 守恒 / 撤销 / 状态联动

管货管数量的核心，DoD 第 2 条要求必须有测试。
重点考的是「上游累计 − 本道累计 = 可报数量」这条守恒关系在各种操作序列后是否还成立。
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.auth.models import ArkUser
from app.domestic import order_service, product_service, progress_service, report_service
from app.domestic import constants as C
from app.domestic.models import (
    DomesticCraftRoute,
    DomesticItemProgress,
    DomesticOrderItem,
    DomesticReportLog,
)
from app.domestic.schemas import (
    ItemShipRequest,
    OrderCreate,
    OrderItemInput,
    OrderItemUpdate,
    ProductAttrs,
)
from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding
from app.system.models import SysDict

PROCESS_NAMES = ["制网", "钩织", "定型"]


# ── fixtures ─────────────────────────────────────────


def _user(db, username, real_name=None):
    user = ArkUser(username=username, password_hash="x", real_name=real_name or username)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def route(db):
    """三道工序的工艺路线：制网 → 钩织 → 定型"""
    route = ProcessRoute(name="头套标准路线", status=1)
    db.add(route)
    db.flush()
    for idx, name in enumerate(PROCESS_NAMES, start=1):
        process = Process(name=name, sort_order=idx, status=1)
        db.add(process)
        db.flush()
        db.add(ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=idx))
    db.flush()
    return route


@pytest.fixture
def workers(db, route):
    """每道工序一个工人，全部绑定好各自工序"""
    steps = product_service.get_route_steps(db, route.id)
    result = []
    for idx, step in enumerate(steps):
        worker = _user(db, f"worker{idx + 1}", PROCESS_NAMES[idx] + "工")
        db.add(UserProcessBinding(user_id=worker.id, process_id=step.process_id))
        result.append(worker)
    db.flush()
    return result


@pytest.fixture
def craft_mapping(db, route):
    db.add(DomesticCraftRoute(product_type="cap", craft="递针旋全头套", route_id=route.id))
    _seed_order_values(db, _attrs())
    db.flush()
    return route


def _attrs(craft="递针旋全头套"):
    return ProductAttrs(
        product_type="cap", craft=craft, net_color="呼吸红",
        size="s", length="15厘米", density="65%",
        hair_style_series="直发",
    )


def _seed_order_values(db, attrs):
    values = {
        C.ORDER_TYPE_DICT: "first_order",
        C.ORDER_CHANNEL_DICT: "wechat",
    }
    for field, dict_type in C.ATTR_DICTS[attrs.product_type].items():
        value = getattr(attrs, field)
        if value is not None:
            values[dict_type] = value
    for dict_type, code in values.items():
        if not db.query(SysDict.id).filter_by(type=dict_type, code=code).first():
            db.add(SysDict(type=dict_type, code=code, label=code, sort=1, is_active=True))
    db.flush()


def _create_order(db, user, qty=20, craft="递针旋全头套"):
    attrs = _attrs(craft)
    _seed_order_values(db, attrs)
    payload = OrderCreate(
        request_id=str(uuid4()),
        order_no="710",
        order_date=date(2026, 7, 27),
        customer_shop_name="马姐假发",
        order_category="normal",
        order_type="first_order",
        order_channel="wechat",
        items=[OrderItemInput(attrs=attrs, order_qty=qty)],
    )
    return order_service.create_order(db, payload, user.id)


def _item_of(db, order_id):
    return db.query(DomesticOrderItem).filter(DomesticOrderItem.order_id == order_id).first()


def _steps(db, item):
    return progress_service.build_progress_view(db, item)


def _report(db, item, step_idx, worker, qty):
    steps = _steps(db, item)
    return report_service.submit_report(
        db, item_id=item.id, progress_id=steps[step_idx]["progress_id"],
        qty=qty, user_id=worker.id, source="web",
    )


# ── 下单与展开 ────────────────────────────────────────


def test_order_expands_route_into_progress_rows(db, craft_mapping, workers):
    creator = _user(db, "planner")
    result = _create_order(db, creator, qty=20)

    assert result["warnings"] == []
    detail = order_service.get_order_detail(db, result["id"])
    assert detail["created_by_name"] == "planner"
    item = _item_of(db, result["id"])
    steps = _steps(db, item)
    assert [s["process_name"] for s in steps] == PROCESS_NAMES
    # 首道可报全部数量，后面各道上游为 0
    assert steps[0]["reportable_qty"] == 20
    assert steps[1]["reportable_qty"] == 0
    assert steps[2]["reportable_qty"] == 0


def test_order_without_craft_mapping_warns_and_cannot_start(db, route):
    creator = _user(db, "planner")
    result = _create_order(db, creator, qty=5, craft="没配过的工艺")

    assert len(result["warnings"]) == 1
    assert "还没配工艺路线" in result["warnings"][0]
    item = _item_of(db, result["id"])
    assert _steps(db, item) == []
    assert item.route_id is None


def test_attach_route_recovers_item_missing_mapping(db, route):
    creator = _user(db, "planner")
    result = _create_order(db, creator, qty=5, craft="没配过的工艺")
    item = _item_of(db, result["id"])

    order_service.attach_route(db, item.id, route.id)

    db.refresh(item)
    assert item.route_id == route.id
    assert len(_steps(db, item)) == 3


# ── 整批报工（多数场景）────────────────────────────────


def test_full_batch_report_moves_whole_quantity_downstream(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])

    result = _report(db, item, 0, workers[0], 20)

    assert result["step_completed_qty"] == 20
    assert result["step_finished"] is True
    assert result["item_finished"] is False
    steps = _steps(db, item)
    assert steps[0]["reportable_qty"] == 0
    assert steps[1]["reportable_qty"] == 20  # 全部数量流到了下一道


def test_finishing_last_step_completes_item_and_order(db, craft_mapping, workers):
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=20)["id"]
    item = _item_of(db, order_id)

    for idx, worker in enumerate(workers):
        _report(db, item, idx, worker, 20)

    db.refresh(item)
    assert item.status == C.ITEM_DONE
    detail = order_service.get_order_detail(db, order_id)
    assert detail["status"] == C.ORDER_DONE
    assert detail["items"][0]["progress_pct"] == 100.0


# ── 拆批报工（工序交接拆数量）──────────────────────────


def test_split_batch_leaves_remainder_upstream(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])

    _report(db, item, 0, workers[0], 12)

    steps = _steps(db, item)
    assert steps[0]["completed_qty"] == 12
    assert steps[0]["reportable_qty"] == 8   # 首道还剩 8 件没做
    assert steps[0]["status"] == 0           # 没做满，本道未完成
    assert steps[1]["reportable_qty"] == 12  # 下一道只能接已交付的 12 件


def test_split_batches_accumulate_to_full_quantity(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])

    _report(db, item, 0, workers[0], 12)
    _report(db, item, 1, workers[1], 12)   # 下游先把第一批做完
    _report(db, item, 0, workers[0], 8)    # 上游补齐剩余 8 件（同一张码继续报）
    _report(db, item, 1, workers[1], 8)

    steps = _steps(db, item)
    assert [s["completed_qty"] for s in steps] == [20, 20, 0]
    assert steps[2]["reportable_qty"] == 20
    logs = db.query(DomesticReportLog).filter(DomesticReportLog.item_id == item.id).count()
    assert logs == 4  # 每次报工都留痕


def test_cannot_report_more_than_upstream_delivered(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    _report(db, item, 0, workers[0], 12)

    with pytest.raises(ValueError, match="最多还能报 12 件"):
        _report(db, item, 1, workers[1], 13)


def test_cannot_report_when_upstream_has_nothing(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])

    with pytest.raises(ValueError, match="上一道工序还没做出可接的数量"):
        _report(db, item, 1, workers[1], 1)


def test_cannot_over_report_first_step_beyond_order_qty(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])

    with pytest.raises(ValueError, match="最多还能报 20 件"):
        _report(db, item, 0, workers[0], 21)


def test_quantity_conservation_holds_after_random_splits(db, craft_mapping, workers):
    """任意拆批序列后，每道累计都不能超过上一道累计。"""
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=30)["id"])

    for qty in (7, 13, 10):
        _report(db, item, 0, workers[0], qty)
    for qty in (5, 15):
        _report(db, item, 1, workers[1], qty)
    _report(db, item, 2, workers[2], 20)

    completed = [s["completed_qty"] for s in _steps(db, item)]
    assert completed == [30, 20, 20]
    assert all(completed[i] >= completed[i + 1] for i in range(len(completed) - 1))


# ── 工序分工 ──────────────────────────────────────────


def test_worker_cannot_report_process_not_assigned(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])

    with pytest.raises(ValueError, match="没有被分配到这道工序"):
        _report(db, item, 0, workers[1], 5)


def test_scan_targets_workers_own_step_with_default_quantity(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    _report(db, item, 0, workers[0], 12)

    view = report_service.scan_item(db, item.id, workers[1].id)

    assert view["can_submit"] is True
    assert view["next_step"]["process_name"] == PROCESS_NAMES[1]
    assert view["next_step"]["reportable_qty"] == 12  # 默认带出可报全量，工人零思考


def test_scan_blocks_when_nothing_reportable(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])

    view = report_service.scan_item(db, item.id, workers[1].id)

    assert view["can_submit"] is False
    assert view["block_reason"] == report_service.BLOCK_NOTHING_REPORTABLE


def test_scan_blocks_unassigned_worker(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    outsider = _user(db, "outsider")

    view = report_service.scan_item(db, item.id, outsider.id)

    assert view["block_reason"] == report_service.BLOCK_NOT_ASSIGNED


# ── 二维码 ────────────────────────────────────────────


def test_qr_roundtrip_and_rejects_foreign_prefix(db):
    qr = report_service.generate_qr_data(42)
    assert qr.startswith("ARK-D:42:")

    valid, item_id = report_service.verify_qr_data(qr)
    assert (valid, item_id) == (True, 42)

    # 外贸的 ARK-P 码在内贸这边一律无效（前缀分流）
    assert report_service.verify_qr_data("ARK-P:42:deadbeef") == (False, 0)
    assert report_service.verify_qr_data("ARK-D:42:00000000")[0] is False


# ── 撤销 ──────────────────────────────────────────────


def test_revoke_rolls_quantity_back(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    result = _report(db, item, 0, workers[0], 12)

    report_service.revoke_report(db, result["log_id"], workers[0].id)

    steps = _steps(db, item)
    assert steps[0]["completed_qty"] == 0
    assert steps[0]["reportable_qty"] == 20
    log = db.query(DomesticReportLog).get(result["log_id"])
    assert log.revoked == 1 and log.revoked_at is not None


def test_revoke_blocked_when_downstream_already_consumed(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    first = _report(db, item, 0, workers[0], 12)
    _report(db, item, 1, workers[1], 12)

    with pytest.raises(ValueError, match="请先撤销下一道的报工"):
        report_service.revoke_report(db, first["log_id"], workers[0].id)

    assert _steps(db, item)[0]["completed_qty"] == 12  # 数量未被改动


def test_partial_revoke_allowed_when_downstream_took_less(db, craft_mapping, workers):
    """上道报 20、下道只接了 12 时，撤掉上道最后一笔 8 件仍然守恒。"""
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    _report(db, item, 0, workers[0], 12)
    second = _report(db, item, 0, workers[0], 8)
    _report(db, item, 1, workers[1], 12)

    report_service.revoke_report(db, second["log_id"], workers[0].id)

    completed = [s["completed_qty"] for s in _steps(db, item)]
    assert completed == [12, 12, 0]


def test_cannot_revoke_others_report_without_admin(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    result = _report(db, item, 0, workers[0], 5)

    with pytest.raises(ValueError, match="只能撤销自己的报工记录"):
        report_service.revoke_report(db, result["log_id"], workers[1].id)

    report_service.revoke_report(db, result["log_id"], workers[1].id, is_admin=True)
    assert _steps(db, item)[0]["completed_qty"] == 0


def test_cannot_revoke_twice(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    result = _report(db, item, 0, workers[0], 5)
    report_service.revoke_report(db, result["log_id"], workers[0].id)

    with pytest.raises(ValueError, match="已经撤销过了"):
        report_service.revoke_report(db, result["log_id"], workers[0].id)


def test_revoke_reopens_completed_item(db, craft_mapping, workers):
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=5)["id"]
    item = _item_of(db, order_id)
    logs = [_report(db, item, idx, worker, 5) for idx, worker in enumerate(workers)]
    db.refresh(item)
    assert item.status == C.ITEM_DONE

    report_service.revoke_report(db, logs[-1]["log_id"], workers[-1].id)

    db.refresh(item)
    assert item.status == C.ITEM_PRODUCING
    assert order_service.get_order_detail(db, order_id)["status"] == C.ORDER_PRODUCING


# ── 发货与数量修改 ────────────────────────────────────


def test_ship_requires_completion_then_flips_order_status(db, craft_mapping, workers):
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=5)["id"]
    item = _item_of(db, order_id)
    ship = ItemShipRequest(ship_time=datetime(2026, 7, 28, 9, 0), ship_weight=Decimal("38.00"))

    with pytest.raises(ValueError, match="还没做完"):
        order_service.ship_item(db, item.id, ship)

    for idx, worker in enumerate(workers):
        _report(db, item, idx, worker, 5)
    order_service.ship_item(db, item.id, ship)

    db.refresh(item)
    assert item.status == C.ITEM_SHIPPED
    assert float(item.ship_weight) == 38.0
    assert order_service.get_order_detail(db, order_id)["status"] == C.ORDER_SHIPPED


def test_shipped_item_rejects_revoke(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=5)["id"])
    logs = [_report(db, item, idx, worker, 5) for idx, worker in enumerate(workers)]
    order_service.ship_item(
        db, item.id, ItemShipRequest(ship_time=datetime(2026, 7, 28, 9, 0), ship_weight=Decimal("38"))
    )

    with pytest.raises(ValueError, match="已发货"):
        report_service.revoke_report(db, logs[-1]["log_id"], workers[-1].id)


def test_cannot_shrink_quantity_below_reported(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    _report(db, item, 0, workers[0], 12)

    with pytest.raises(ValueError, match="已有工序完成 12 件"):
        order_service.update_item(db, item.id, OrderItemUpdate(order_qty=10))

    order_service.update_item(db, item.id, OrderItemUpdate(order_qty=12))
    db.refresh(item)
    assert item.status == C.ITEM_PRODUCING  # 首道做满但后面两道还没做
    assert _steps(db, item)[0]["status"] == 1


def test_terminated_order_rejects_reporting(db, craft_mapping, workers):
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=20)["id"]
    item = _item_of(db, order_id)
    order_service.terminate_order(db, order_id, "客户取消")

    with pytest.raises(ValueError, match="订单已终止"):
        _report(db, item, 0, workers[0], 5)

    assert report_service.scan_item(db, item.id, workers[0].id)["block_reason"] == \
        report_service.BLOCK_ORDER_TERMINATED


def test_item_with_reports_cannot_be_deleted(db, craft_mapping, workers):
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=20)["id"]
    item = _item_of(db, order_id)
    _report(db, item, 0, workers[0], 5)

    with pytest.raises(ValueError, match="已有 1 条报工记录"):
        order_service.delete_item(db, item.id)
    with pytest.raises(ValueError, match="不能删除"):
        order_service.delete_order(db, order_id)


# ── 产品沉淀 ──────────────────────────────────────────


def test_same_attrs_reuse_one_product(db, craft_mapping, workers):
    creator = _user(db, "planner")
    first = _item_of(db, _create_order(db, creator, qty=5)["id"])
    second_order = _create_order(db, creator, qty=8)["id"]
    second = _item_of(db, second_order)

    assert first.product_id == second.product_id
    product = db.query(product_service.DomesticProduct).get(first.product_id)
    assert product.use_count == 2
    assert product.name == "头套/递针旋全头套/呼吸红/s/15厘米/65%/直发"


def test_report_history_returns_all_order_dimensions(db, craft_mapping, workers):
    creator = _user(db, "report-dimension-planner")
    item = _item_of(db, _create_order(db, creator, qty=2)["id"])
    _report(db, item, 0, workers[0], 1)

    rows = report_service.list_today_reports(db, workers[0].id)

    assert rows[0]["order_category"] == "normal"
    assert rows[0]["order_category_label"] == "普货"
    assert rows[0]["order_type"] == "first_order"
    assert rows[0]["order_type_label"] == "first_order"
    assert rows[0]["order_channel"] == "wechat"
    assert rows[0]["order_channel_label"] == "wechat"


def test_piece_ignores_net_color_in_identity(db):
    """发片没有网底：带上网底值不该让同一产品分裂成两个。"""
    with_color = ProductAttrs(
        product_type="piece", craft="全递针", net_color="呼吸红",
        size="13*15", length="30厘米", density="80%",
    )
    without = ProductAttrs(
        product_type="piece", craft="全递针", net_color=None,
        size="13*15", length="30厘米", density="80%",
    )
    assert product_service.build_attrs_key(with_color) == product_service.build_attrs_key(without)


# ── 对抗性审查补测（2026-07-27）────────────────────────


def test_deleted_order_blocks_scanning_and_reporting(db, craft_mapping, workers):
    """卡片还贴在车间墙上：软删订单后那张码必须失效，否则工时挂在查不到的单上。"""
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=20)["id"]
    item = _item_of(db, order_id)
    order_service.delete_order(db, order_id)

    view = report_service.scan_item(db, item.id, workers[0].id)
    assert view["block_reason"] == report_service.BLOCK_ORDER_TERMINATED

    with pytest.raises(ValueError, match="订单已删除"):
        _report(db, item, 0, workers[0], 5)


def test_terminated_order_blocks_shipping(db, craft_mapping, workers):
    """否则会出现「订单已终止但货已发出」的自相矛盾状态。"""
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=5)["id"]
    item = _item_of(db, order_id)
    for idx, worker in enumerate(workers):
        _report(db, item, idx, worker, 5)
    order_service.terminate_order(db, order_id, "客户取消")

    with pytest.raises(ValueError, match="订单已终止"):
        order_service.ship_item(
            db, item.id,
            ItemShipRequest(ship_time=datetime(2026, 7, 28, 9, 0), ship_weight=Decimal("38")),
        )


def test_request_id_makes_submit_idempotent(db, craft_mapping, workers):
    """弱网重试：同一个 request_id 再提交一次不能变成报两次。"""
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    steps = _steps(db, item)
    kwargs = dict(
        item_id=item.id, progress_id=steps[0]["progress_id"],
        qty=5, user_id=workers[0].id, source="mini", request_id="req-abc",
    )

    first = report_service.submit_report(db, **kwargs)
    replay = report_service.submit_report(db, **kwargs)

    assert replay["log_id"] == first["log_id"]
    assert replay.get("replayed") is True
    assert _steps(db, item)[0]["completed_qty"] == 5
    assert db.query(DomesticReportLog).filter(DomesticReportLog.item_id == item.id).count() == 1


def test_different_request_ids_still_accumulate(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    steps = _steps(db, item)
    for req in ("r1", "r2"):
        report_service.submit_report(
            db, item_id=item.id, progress_id=steps[0]["progress_id"],
            qty=5, user_id=workers[0].id, source="mini", request_id=req,
        )
    assert _steps(db, item)[0]["completed_qty"] == 10


def test_on_behalf_report_credits_the_actual_worker(db, craft_mapping, workers):
    """代报工：件数必须记在做活的工人名下，不是记在操作电脑的跟单名下。"""
    planner = _user(db, "planner")
    item = _item_of(db, _create_order(db, planner, qty=20)["id"])
    steps = _steps(db, item)

    # 跟单自己没绑工序，不指定工人时应当被拒
    with pytest.raises(ValueError, match="你没有被分配到这道工序"):
        report_service.submit_report(
            db, item_id=item.id, progress_id=steps[0]["progress_id"],
            qty=5, user_id=planner.id, source="web",
        )

    report_service.submit_report(
        db, item_id=item.id, progress_id=steps[0]["progress_id"],
        qty=5, user_id=planner.id, source="web", on_behalf_user_id=workers[0].id,
    )
    log = db.query(DomesticReportLog).filter(DomesticReportLog.item_id == item.id).first()
    assert log.reported_by_user_id == workers[0].id
    assert log.source == "web"


def test_on_behalf_rejects_worker_without_that_process(db, craft_mapping, workers):
    planner = _user(db, "planner")
    item = _item_of(db, _create_order(db, planner, qty=20)["id"])
    steps = _steps(db, item)

    with pytest.raises(ValueError, match="该工人没有被分配到这道工序"):
        report_service.submit_report(
            db, item_id=item.id, progress_id=steps[0]["progress_id"],
            qty=5, user_id=planner.id, source="web", on_behalf_user_id=workers[1].id,
        )


def test_attach_route_refuses_when_report_logs_exist(db, craft_mapping, workers, route):
    """重建进度会级联删掉流水（含已撤销的），审计不能断档。"""
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    result = _report(db, item, 0, workers[0], 5)
    report_service.revoke_report(db, result["log_id"], workers[0].id)

    # 数量已归零，但流水还在 —— 仍不允许重建
    assert _steps(db, item)[0]["completed_qty"] == 0
    with pytest.raises(ValueError, match="已有 1 条报工记录"):
        order_service.attach_route(db, item.id, route.id)


def test_progress_steps_renumbered_from_one(db, route):
    """路线侧序号跳号也不能影响上下游口径 —— 展开时自己按位置重排。"""
    steps = product_service.get_route_steps(db, route.id)
    steps[-1].step_order = 9
    db.flush()

    creator = _user(db, "planner")
    db.add(DomesticCraftRoute(product_type="cap", craft="递针顶", route_id=route.id))
    db.flush()
    item = _item_of(db, _create_order(db, creator, qty=6, craft="递针顶")["id"])

    assert [s["step_order"] for s in _steps(db, item)] == [1, 2, 3]


def test_workload_summary_excludes_revoked(db, craft_mapping, workers):
    """计件工资的唯一口径：撤销掉的件数不能算钱。"""
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    _report(db, item, 0, workers[0], 12)
    latest = _report(db, item, 0, workers[0], 8)
    report_service.revoke_report(db, latest["log_id"], workers[0].id)

    rows = report_service.get_workload_summary(
        db, date_start=datetime(2026, 1, 1), date_end=datetime(2099, 1, 1)
    )
    mine = [r for r in rows if r["user_id"] == workers[0].id]
    assert len(mine) == 1
    assert mine[0]["total_qty"] == 12
    assert mine[0]["report_count"] == 1


def test_multi_item_order_status_rolls_up_partially(db, craft_mapping, workers):
    """一单多品：一行做完不等于整单做完，一行发货不等于整单发货。"""
    creator = _user(db, "planner")
    payload = OrderCreate(
        request_id=str(uuid4()),
        order_no="712", order_date=date(2026, 7, 27), customer_shop_name="马姐假发",
        order_category="normal", order_type="first_order", order_channel="wechat",
        items=[
            OrderItemInput(attrs=_attrs(), order_qty=3),
            OrderItemInput(attrs=_attrs(), order_qty=5),
        ],
    )
    order_id = order_service.create_order(db, payload, creator.id)["id"]
    items = db.query(DomesticOrderItem).filter(DomesticOrderItem.order_id == order_id).all()
    assert len(items) == 2

    for idx, worker in enumerate(workers):
        _report(db, items[0], idx, worker, 3)

    assert order_service.get_order_detail(db, order_id)["status"] == C.ORDER_PRODUCING

    ship = ItemShipRequest(ship_time=datetime(2026, 7, 28, 9, 0), ship_weight=Decimal("38"))
    order_service.ship_item(db, items[0].id, ship)
    assert order_service.get_order_detail(db, order_id)["status"] == C.ORDER_PRODUCING

    for idx, worker in enumerate(workers):
        _report(db, items[1], idx, worker, 5)
    assert order_service.get_order_detail(db, order_id)["status"] == C.ORDER_DONE

    order_service.ship_item(db, items[1].id, ship)
    assert order_service.get_order_detail(db, order_id)["status"] == C.ORDER_SHIPPED


def test_enlarging_quantity_reopens_completed_item(db, craft_mapping, workers):
    creator = _user(db, "planner")
    order_id = _create_order(db, creator, qty=5)["id"]
    item = _item_of(db, order_id)
    for idx, worker in enumerate(workers):
        _report(db, item, idx, worker, 5)

    order_service.update_item(db, item.id, OrderItemUpdate(order_qty=9))

    db.refresh(item)
    assert item.status == C.ITEM_PRODUCING
    assert _steps(db, item)[0]["reportable_qty"] == 4
    assert order_service.get_order_detail(db, order_id)["status"] == C.ORDER_PRODUCING


def test_scan_blocks_when_no_route_and_when_all_done(db, route, craft_mapping, workers):
    creator = _user(db, "planner")
    unrouted = _item_of(db, _create_order(db, creator, qty=2, craft="没配过的工艺")["id"])
    assert report_service.scan_item(db, unrouted.id, workers[0].id)["block_reason"] == \
        report_service.BLOCK_NO_ROUTE

    done = _item_of(db, _create_order(db, creator, qty=2)["id"])
    for idx, worker in enumerate(workers):
        _report(db, done, idx, worker, 2)
    assert report_service.scan_item(db, done.id, workers[0].id)["block_reason"] == \
        report_service.BLOCK_ALL_DONE


def test_oversized_attrs_rejected_as_validation_error(db):
    attrs = ProductAttrs(
        product_type="cap", craft="工" * 64, net_color="色" * 64,
        size="码" * 64, length="长" * 32, density="量" * 32,
        hair_style_series="发" * 64,
    )
    with pytest.raises(ValueError, match="属性值太长"):
        product_service.build_attrs_key(attrs)


def test_configuring_mapping_backfills_products_missing_route(db, route):
    creator = _user(db, "planner")
    result = _create_order(db, creator, qty=5, craft="递针顶")
    assert result["warnings"]

    product_service.upsert_craft_route(
        db, product_type="cap", craft="递针顶", route_id=route.id, user_id=creator.id
    )

    product = db.query(product_service.DomesticProduct).filter(
        product_service.DomesticProduct.craft == "递针顶"
    ).first()
    assert product.route_id == route.id


def test_progress_view_carries_last_reporter(db, craft_mapping, workers):
    """车间查进度最想知道的两件事：这道工序最近是谁报的、报了多少。"""
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    _report(db, item, 0, workers[0], 12)
    _report(db, item, 0, workers[0], 8)

    first = _steps(db, item)[0]
    assert first["last_reported_by"] == workers[0].real_name
    assert first["last_report_qty"] == 8          # 最近一次，不是首次也不是合计
    assert _steps(db, item)[1]["last_reported_by"] is None


def test_revoked_report_not_shown_as_last_reporter(db, craft_mapping, workers):
    creator = _user(db, "planner")
    item = _item_of(db, _create_order(db, creator, qty=20)["id"])
    result = _report(db, item, 0, workers[0], 5)
    report_service.revoke_report(db, result["log_id"], workers[0].id)

    assert _steps(db, item)[0]["last_reported_by"] is None


def test_lookup_by_system_no_customer_no_and_qr(db, craft_mapping, workers):
    """速查一个输入框吃三种东西，车间不用先选按什么查。"""
    creator = _user(db, "planner")
    created = _create_order(db, creator, qty=20)
    item = _item_of(db, created["id"])

    by_sys = order_service.lookup_order(db, created["domestic_no"])
    by_cust = order_service.lookup_order(db, "710")
    by_qr = order_service.lookup_order(db, report_service.generate_qr_data(item.id))

    assert by_sys["id"] == by_cust["id"] == by_qr["id"] == created["id"]
    assert by_qr["items"][0]["steps"][0]["process_name"] == PROCESS_NAMES[0]


def test_lookup_rejects_unknown_and_bad_qr(db, craft_mapping):
    with pytest.raises(ValueError, match="没找到订单"):
        order_service.lookup_order(db, "不存在的单号")
    with pytest.raises(ValueError, match="二维码无效"):
        order_service.lookup_order(db, "ARK-D:999:deadbeef")
    with pytest.raises(ValueError, match="请输入订单号"):
        order_service.lookup_order(db, "  ")


def test_lookup_skips_deleted_orders(db, craft_mapping, workers):
    creator = _user(db, "planner")
    created = _create_order(db, creator, qty=20)
    order_service.delete_order(db, created["id"])

    with pytest.raises(ValueError, match="没找到订单"):
        order_service.lookup_order(db, created["domestic_no"])
