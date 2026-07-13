"""OKKI 推单字段映射与状态机测试（管钱逻辑，必须有测试）。

真实推单无沙箱，okki_client.push_order 一律 monkeypatch，不打真实接口。
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.invoice import okki_client, product_service, service, xiaoman_service
from app.invoice.models import CustomProduct, Invoice, InvoiceItem, InvoiceSyncLog, XiaomanSettings
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload, InvoiceUpdate


# ── 数据工厂 ──────────────────────────────────────────────


def _seed_settings(db, **overrides):
    row = XiaomanSettings(
        id=1,
        generic_product_no="GENERIC-PROD",
        generic_product_id=888,
        generic_sku_id=999,
        default_order_status="13972831654",
        default_currency="USD",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    return row


def _seed_binding(db, ark_user_id=1, external_account_id="777001", department_id=24925, **overrides):
    # 推单前置校验需要业务员用户行（部门归属挂在 ark_users 上）
    if db.get(ArkUser, ark_user_id) is None:
        db.add(ArkUser(
            id=ark_user_id, username=f"sales{ark_user_id}", password_hash="x", real_name="张三",
            okki_department_id=department_id,
            okki_department_name="多财多亿" if department_id is not None else None,
        ))
    row = ArkUserExternalBinding(
        ark_user_id=ark_user_id,
        provider="okki",
        external_account_id=external_account_id,
        binding_status="active",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    return row


def _make_invoice(db, **overrides):
    invoice = Invoice(
        invoice_no=overrides.pop("invoice_no", "INV20260713-001"),
        order_type="production",
        customer_id="123456",
        customer_name="Customer A",
        sales_user_id=1,
        sales_user_name="张三",
        invoice_date=date(2026, 7, 13),
        currency="USD",
        shipping_fee=Decimal("10"),
        surcharge_name="Paypal Surcharge",
        surcharge_amount=Decimal("5"),
        payment_term="30% deposit",
        remark="hello",
    )
    for key, value in overrides.items():
        setattr(invoice, key, value)
    db.add(invoice)
    db.flush()
    return invoice


def _stock_item(**overrides):
    item = InvoiceItem(
        sort_order=1,
        item_type="stock",
        product_id=1,
        sku_id=9001,
        product_name="Raw Hair/18/#1/100g",
        product_display="Raw Hair",
        net_weight_grams="100g",
        color="#1",
        length="18",
        quantity=3,
        price_per_piece=Decimal("12.50"),
        total_price=Decimal("37.50"),
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


def _custom_item(custom_product_id, **overrides):
    item = InvoiceItem(
        sort_order=2,
        item_type="custom",
        custom_product_id=custom_product_id,
        product_name="Genius Weft/18/#1/20g",
        product_display="Genius Weft",
        net_weight_grams="20g",
        model="B1",
        color="#1",
        length="18",
        quantity=2,
        price_per_piece=Decimal("8.00"),
        total_price=Decimal("16.00"),
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


def _make_custom_product(db, match_key, **overrides):
    row = CustomProduct(
        match_key=match_key,
        product_display="Genius Weft",
        product_name="Genius Weft/18/#1/20g",
        color="#1",
        size="18",
        unit="20g",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def no_reconcile(monkeypatch):
    """跳过推单前对账（测试库无 okki_products 投影表）"""
    monkeypatch.setattr(product_service, "reconcile_custom_products", lambda db: {"checked": 0, "linked": 0})


# ── payload 映射 ──────────────────────────────────────────


def test_build_push_payload_stock_custom_and_backfilled(db):
    _seed_settings(db)
    _seed_binding(db)
    cp_pending = _make_custom_product(db, "key-pending")
    cp_backfilled = _make_custom_product(db, "key-backfilled", okki_product_id=555, okki_sku_id=556)

    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    invoice.items.append(_custom_item(cp_pending.id))
    invoice.items.append(_custom_item(cp_backfilled.id, sort_order=3, quantity=1, total_price=Decimal("8.00")))
    db.flush()

    payload, line_binding, issues = xiaoman_service.build_push_payload(db, invoice)

    assert issues == []
    assert payload["company_id"] == 123456
    assert payload["status"] == 13972831654
    assert payload["currency"] == "USD"
    assert payload["name"].startswith("INV20260713-001")
    assert payload["account_date"] == "2026-07-13"
    # 人员：绑定的 OKKI 用户做创建人/处理人/业绩归属，不传 user_id（避开权限 404）
    assert payload["create_user"] == 777001
    assert payload["handler"] == [777001]
    assert payload["users"] == [{"user_id": 777001, "rate": 100}]
    assert "user_id" not in payload
    # 企业必填：部门（挂业务员用户设置）+ 4 个自定义字段
    assert payload["departments"] == [{"department_id": 24925, "rate": 100}]
    assert payload[xiaoman_service.FIELD_ORDER_TYPE] == "定制品"  # production 自动映射
    assert payload[xiaoman_service.FIELD_NEW_DEAL] == "是"        # okki_orders 无该客户历史
    assert payload[xiaoman_service.FIELD_FREE_SHIPPING] == "否"   # 运费 10 > 0
    assert payload[xiaoman_service.FIELD_FIRST_RETURN] == "否"    # 默认否
    # 新建：不带 order_id / unique_id
    assert "order_id" not in payload

    rows = payload["product_list"]
    assert len(rows) == 3
    # 库存行：真实 ID，小计必传（OKKI 不自动算）
    assert rows[0]["product_id"] == 1 and rows[0]["sku_id"] == 9001
    assert rows[0]["count"] == 3 and rows[0]["unit_price"] == 12.5 and rows[0]["cost_amount"] == 37.5
    assert "product_name" not in rows[0]
    # 已回填 custom 行：转正走真实 ID，逐行推、不参与合并
    assert rows[1]["product_id"] == 555 and rows[1]["sku_id"] == 556
    assert "product_name" not in rows[1]
    # 未回填 custom 行 → 合并为单条通用产品行：数量 1，单价=总价=非标合计
    assert rows[2]["product_id"] == 888 and rows[2]["sku_id"] == 999
    assert rows[2]["count"] == 1
    assert rows[2]["unit_price"] == 16.0 and rows[2]["cost_amount"] == 16.0
    assert rows[2]["product_name"].startswith("非标合计1项")
    assert "Genius Weft/18/#1/20g x2" in rows[2]["product_name"]
    assert "product_model" not in rows[2] and "unit" not in rows[2]

    # 费用：运费+附加费各一条绝对值
    costs = payload["cost_list"]
    assert len(costs) == 2
    assert all(c["percent_type"] == 0 for c in costs)
    assert costs[0]["cost"] == 10.0 and costs[1]["cost"] == 5.0
    assert costs[1]["cost_name"] == "Paypal Surcharge"
    # 付款条款并入备注
    assert "hello" in payload["remark"] and "30% deposit" in payload["remark"]
    # 订单级金额不传，OKKI 自算
    for field in ("amount", "amount_usd", "product_total_amount", "exchange_rate"):
        assert field not in payload
    # line_binding 与真实行一一对应
    assert len(line_binding) == 3


def test_build_push_payload_blockers(db):
    # 无 settings、无绑定、客户 ID 非数字、custom 行无通用产品 → 全部前置拦截
    cp = _make_custom_product(db, "key-blocker")
    invoice = _make_invoice(db, customer_id="CUST001")
    invoice.items.append(_custom_item(cp.id))
    db.flush()

    payload, line_binding, issues = xiaoman_service.build_push_payload(db, invoice)

    assert payload is None and line_binding == []
    fields = {issue["field"] for issue in issues}
    assert "customer_id" in fields
    assert "default_order_status" in fields
    assert "sales_user_id" in fields
    assert "okki_department" in fields
    assert "items[1]" in fields


def test_push_flags_explicit_and_stock_order_type(db):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, order_type="stock",
                            okki_new_deal=0, okki_free_shipping=1, okki_first_return=1)
    invoice.items.append(_stock_item())
    db.flush()

    payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)
    assert issues == []
    assert payload[xiaoman_service.FIELD_ORDER_TYPE] == "规格品"  # stock 自动映射
    # 发票存值优先，不走兜底（运费 10>0 但显式标了包邮=是）
    assert payload[xiaoman_service.FIELD_NEW_DEAL] == "否"
    assert payload[xiaoman_service.FIELD_FREE_SHIPPING] == "是"
    assert payload[xiaoman_service.FIELD_FIRST_RETURN] == "是"


def test_push_blocked_without_department(db):
    _seed_settings(db)
    _seed_binding(db, ark_user_id=2, external_account_id="777002", department_id=None)
    invoice = _make_invoice(db, sales_user_id=2)
    invoice.items.append(_stock_item())
    db.flush()

    _payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)
    assert any(issue["field"] == "okki_department" for issue in issues)


def test_resolve_okki_flags_history_fallback(db):
    from sqlalchemy import text as sa_text
    # 该客户在 OKKI 已有历史订单 → 新成交兜底为否；运费 0 → 包邮兜底为是
    db.execute(sa_text(
        "INSERT INTO lsordertest.okki_orders (order_id, company_id) VALUES ('H1', '123456')"
    ))
    invoice = _make_invoice(db, shipping_fee=Decimal("0"))
    db.flush()

    flags = service.resolve_okki_flags(db, invoice)
    assert flags == {"okki_new_deal": 0, "okki_free_shipping": 1, "okki_first_return": 0}


def test_okki_department_options_aggregation(db):
    from sqlalchemy import text as sa_text

    from app.auth.service import list_okki_department_options

    db.execute(sa_text(
        "INSERT INTO lsordertest.okki_orders (order_id, company_id, departments) VALUES "
        "('D1','C1','[{\"name\": \"多财多亿\", \"rate\": 100, \"department_id\": 24925}]'),"
        "('D2','C1','[{\"name\": \"多财多亿\", \"rate\": 100, \"department_id\": 24925}]'),"
        "('D3','C2','{\"id\": 24926, \"name\": \"稻乐偲\"}'),"      # dict 格式 + id 键兼容
        "('D4','C3','not-json'),"                                    # 坏 JSON 只跳过
        "('D5','C4','[{\"name\": \"我的企业\", \"rate\": 100, \"department_id\": 0}]'),"
        "('D6','C5','[{\"department_id\": \"abc\"}]')"               # 脏 id 只跳过
    ))
    options = list_okki_department_options(db)
    by_id = {option["department_id"]: option for option in options}
    assert by_id[24925]["order_count"] == 2 and by_id[24925]["name"] == "多财多亿"
    assert by_id[24926]["name"] == "稻乐偲"
    assert 0 in by_id  # 我的企业（id=0）是合法部门
    assert options[0]["department_id"] == 24925  # 按用量倒序
    assert "abc" not in str([o["department_id"] for o in options])


def test_build_push_payload_inactive_binding_rejected(db):
    _seed_settings(db)
    _seed_binding(db, binding_status="inactive")
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()

    _payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)
    assert any(issue["field"] == "sales_user_id" for issue in issues)


# ── 推单状态机 ────────────────────────────────────────────


def test_sync_invoice_success_state_and_unique_id_writeback(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    cp1 = _make_custom_product(db, "key-a")
    cp2 = _make_custom_product(db, "key-b")

    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    # 两条 custom 行合并为一条通用产品行推送（16.00 + 16.00 = 32.00）
    invoice.items.append(_custom_item(cp1.id))
    invoice.items.append(_custom_item(cp2.id, sort_order=3))
    db.flush()

    captured = {}

    def fake_push(db_, payload):
        captured["payload"] = payload
        return {
            "order_id": 424242,
            "product_list": [
                {"unique_id": 111, "product_id": "1", "sku_id": "9001"},
                {"unique_id": 222, "product_id": "888", "sku_id": "999"},
            ],
        }

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = xiaoman_service.sync_invoice(db, invoice, operator_id=7)

    assert result["ok"] is True
    assert invoice.sync_status == "synced"
    assert invoice.status == "synced"
    assert invoice.xiaoman_order_id == "424242"
    assert invoice.sync_error is None
    assert invoice.synced_at is not None
    assert invoice.xiaoman_removed_lines is None
    # 合并行金额 = 非标合计，数量恒 1
    merged = captured["payload"]["product_list"][1]
    assert merged["count"] == 1 and merged["unit_price"] == 32.0 and merged["cost_amount"] == 32.0
    # unique_id 回写：库存行精确匹配；合并行的 uid 写到每一条成员上
    assert invoice.items[0].xiaoman_unique_id == "111"
    assert invoice.items[1].xiaoman_unique_id == "222"
    assert invoice.items[2].xiaoman_unique_id == "222"

    log = db.query(InvoiceSyncLog).filter(InvoiceSyncLog.invoice_id == invoice.id).one()
    assert log.action == "create" and log.success == 1 and log.operator_id == 7
    assert json.loads(log.request_digest)["company_id"] == 123456


def test_sync_invoice_failure_state_and_log(db, monkeypatch, no_reconcile):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()

    def fake_push(db_, payload):
        raise okki_client.OkkiApiError("OKKI 订单推送失败：boom")

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = xiaoman_service.sync_invoice(db, invoice, operator_id=7)

    assert result["ok"] is False
    assert invoice.sync_status == "sync_failed"
    assert invoice.status == "sync_failed"
    assert "boom" in invoice.sync_error
    assert invoice.xiaoman_order_id is None

    log = db.query(InvoiceSyncLog).filter(InvoiceSyncLog.invoice_id == invoice.id).one()
    assert log.success == 0 and "boom" in log.error_message


def test_sync_invoice_preflight_issues_do_not_mark_failed(db, no_reconcile):
    # 前置校验失败：未发起推送，不落 sync_failed、不写日志
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()

    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is False and result["issues"]
    assert invoice.sync_status == "not_synced"
    assert db.query(InvoiceSyncLog).filter(InvoiceSyncLog.invoice_id == invoice.id).count() == 0


def test_sync_create_without_order_id_marks_failed(db, monkeypatch, no_reconcile):
    # 响应异常（无 order_id）不能标成功：本地记不住单号，重推必然重复建单
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    db.flush()

    monkeypatch.setattr(okki_client, "push_order", lambda db_, payload: {})
    result = xiaoman_service.sync_invoice(db, invoice)

    assert result["ok"] is False and "order_id" in result["message"]
    assert invoice.sync_status == "sync_failed"
    assert invoice.xiaoman_order_id is None


def test_sync_partial_response_fails_but_keeps_order_id(db, monkeypatch, no_reconcile):
    # OKKI 静默丢行：订单已建（order_id 固化）但同步标失败，用户可见可重推
    _seed_settings(db)
    _seed_binding(db)
    cp = _make_custom_product(db, "key-partial")
    invoice = _make_invoice(db)
    invoice.items.append(_stock_item())
    invoice.items.append(_custom_item(cp.id))
    db.flush()

    def fake_push(db_, payload):
        return {
            "order_id": 424242,
            # custom 行被 OKKI 静默忽略，响应只有库存行
            "product_list": [{"unique_id": 111, "product_id": "1", "sku_id": "9001"}],
        }

    monkeypatch.setattr(okki_client, "push_order", fake_push)
    result = xiaoman_service.sync_invoice(db, invoice, operator_id=7)

    assert result["ok"] is False and "1 行" in result["message"]
    assert invoice.xiaoman_order_id == "424242"  # 单号已固化，重推走编辑语义
    assert invoice.sync_status == "sync_failed"
    assert invoice.items[0].xiaoman_unique_id == "111"  # 成功的行照常回写
    logs = db.query(InvoiceSyncLog).filter(InvoiceSyncLog.invoice_id == invoice.id).all()
    assert [log.success for log in logs] == [1, 0]  # 受理日志 + 缺行告警日志


def test_edit_push_generic_rows_merge_and_stock_duplicates_blocked(db):
    _seed_settings(db)
    _seed_binding(db)
    cp1 = _make_custom_product(db, "key-f1")
    cp2 = _make_custom_product(db, "key-f2")
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_custom_item(cp1.id))
    invoice.items.append(_custom_item(cp2.id, sort_order=3))
    db.flush()

    # 多条新非标行合并为一条通用行 → 编辑推单不再触发去重拦截
    payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)
    assert issues == []
    generic_rows = [r for r in payload["product_list"] if r.get("product_id") == 888]
    assert len(generic_rows) == 1
    assert generic_rows[0]["count"] == 1 and generic_rows[0]["cost_amount"] == 32.0

    # 编辑时一次新增两条相同库存品（无 unique_id）仍会被 OKKI 去重 → 前置拦截
    invoice.items.append(_stock_item(sort_order=4))
    invoice.items.append(_stock_item(sort_order=5))
    db.flush()
    _payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)
    assert any(issue["field"] == "items" for issue in issues)


def test_edit_push_merged_line_uid_carry_supersede_and_snapshot_filter(db):
    _seed_settings(db)
    _seed_binding(db)
    cp1 = _make_custom_product(db, "key-m1")
    cp2 = _make_custom_product(db, "key-m2")
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    # 历史上曾逐行推送：两条非标行各有 uid；快照里还有一条已删成员的 uid=555
    invoice.items.append(_custom_item(cp1.id, xiaoman_unique_id="555"))
    invoice.items.append(_custom_item(cp2.id, sort_order=3, xiaoman_unique_id="556"))
    invoice.xiaoman_removed_lines = json.dumps([
        {"unique_id": 555, "item_type": "custom", "product_id": None, "sku_id": None, "custom_product_id": None},
    ])
    db.flush()

    payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)
    assert issues == []
    rows = payload["product_list"]
    merged = [r for r in rows if not r.get("remove")]
    assert len(merged) == 1
    # 合并行沿用首个成员 uid 锚定 OKKI 侧既有行，金额=两条合计
    assert merged[0]["unique_id"] == 555
    assert merged[0]["cost_amount"] == 32.0
    remove_rows = [r for r in rows if r.get("remove") == 1]
    # 快照里的 555 被过滤（合并行还在用）；556 被合并取代 → 发 remove 收掉
    assert [r["unique_id"] for r in remove_rows] == [556]
    assert remove_rows[0]["product_id"] == 888 and remove_rows[0]["sku_id"] == 999


def test_edit_push_sends_empty_remark_and_cost_list(db):
    # 编辑语义下空值也要发：字段缺省可能被 OKKI 当"不修改"，运费改 0 永远同步不过去
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(
        db, xiaoman_order_id="424242",
        shipping_fee=Decimal("0"), surcharge_amount=Decimal("0"),
        remark=None, payment_term=None,
    )
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    db.flush()

    payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)
    assert issues == []
    assert payload["remark"] == "" and payload["cost_list"] == []

    # 新建时空字段不发
    invoice.xiaoman_order_id = None
    invoice.items[0].xiaoman_unique_id = None
    payload, _binding, _issues = xiaoman_service.build_push_payload(db, invoice)
    assert "remark" not in payload and "cost_list" not in payload


def test_delete_invoice_blocked_by_okki_order_id(db):
    # 编辑会把 synced 翻回 not_synced，删除守卫必须看 xiaoman_order_id 而非同步状态
    invoice = _make_invoice(db, xiaoman_order_id="424242", sync_status="not_synced")
    db.flush()
    with pytest.raises(ValueError):
        service.delete_invoice(db, invoice)


# ── 编辑语义：order_id / unique_id / 删行 ─────────────────


def test_build_push_payload_edit_carries_order_id_and_remove_rows(db):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_stock_item(xiaoman_unique_id="111"))
    invoice.xiaoman_removed_lines = json.dumps([
        {"unique_id": 333, "item_type": "stock", "product_id": 2, "sku_id": 9002},
        {"unique_id": 444, "item_type": "custom", "product_id": None, "sku_id": None, "custom_product_id": None},
    ])
    db.flush()

    payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)

    assert issues == []
    assert payload["order_id"] == 424242
    rows = payload["product_list"]
    assert rows[0]["unique_id"] == 111
    remove_rows = [r for r in rows if r.get("remove") == 1]
    assert {r["unique_id"] for r in remove_rows} == {333, 444}
    by_uid = {r["unique_id"]: r for r in remove_rows}
    # 快照带 ID 的原样回传；custom 快照无 ID 时回落通用产品
    assert by_uid[333]["product_id"] == 2 and by_uid[333]["sku_id"] == 9002
    assert by_uid[444]["product_id"] == 888 and by_uid[444]["sku_id"] == 999


def test_merged_uid_not_duplicated_when_member_backfilled(db):
    # 合并推过的成员（共享 uid）之后被回填转正：转正行必须放弃共享 uid 按新行推，
    # 合并行继续锚定该 uid——否则 payload 两行同 uid，OKKI 互相覆盖金额无声出错
    _seed_settings(db)
    _seed_binding(db)
    cp_promoted = _make_custom_product(db, "key-promoted", okki_product_id=555, okki_sku_id=556)
    cp_pending = _make_custom_product(db, "key-still-pending")
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_custom_item(cp_promoted.id, xiaoman_unique_id="222"))
    invoice.items.append(_custom_item(cp_pending.id, sort_order=3, xiaoman_unique_id="222"))
    db.flush()

    payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)

    assert issues == []
    rows = payload["product_list"]
    promoted = [r for r in rows if r.get("product_id") == 555]
    merged = [r for r in rows if r.get("product_id") == 888 and not r.get("remove")]
    assert len(promoted) == 1 and "unique_id" not in promoted[0]
    assert len(merged) == 1 and merged[0]["unique_id"] == 222
    # uid 已被合并行认领，不产生 remove
    assert [r for r in rows if r.get("remove") == 1] == []
    uids = [r["unique_id"] for r in rows if r.get("unique_id")]
    assert len(uids) == len(set(uids))


def test_merged_uid_removed_when_all_members_backfilled(db):
    # 共享 uid 的成员全部转正：旧通用行没人认领 → 发 remove 收掉，转正行全部按新行推
    _seed_settings(db)
    _seed_binding(db)
    cp1 = _make_custom_product(db, "key-all-p1", okki_product_id=555, okki_sku_id=556)
    cp2 = _make_custom_product(db, "key-all-p2", okki_product_id=655, okki_sku_id=656)
    invoice = _make_invoice(db, xiaoman_order_id="424242")
    invoice.items.append(_custom_item(cp1.id, xiaoman_unique_id="222"))
    invoice.items.append(_custom_item(cp2.id, sort_order=3, xiaoman_unique_id="222"))
    db.flush()

    payload, _binding, issues = xiaoman_service.build_push_payload(db, invoice)

    assert issues == []
    rows = payload["product_list"]
    real_rows = [r for r in rows if not r.get("remove")]
    assert {r["product_id"] for r in real_rows} == {555, 655}
    assert all("unique_id" not in r for r in real_rows)
    remove_rows = [r for r in rows if r.get("remove") == 1]
    assert [r["unique_id"] for r in remove_rows] == [222]
    assert remove_rows[0]["product_id"] == 888 and remove_rows[0]["sku_id"] == 999


def test_replace_items_carries_unique_id_and_accumulates_removed(db):
    create_payload = InvoiceCreate(
        customer_id="123456",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 13),
        items=[
            InvoiceItemPayload(
                product_id=1, sku_id=9001, product_name="Raw Hair/18/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="18", quantity=3, price_per_piece=Decimal("12.50"),
            ),
            InvoiceItemPayload(
                product_id=2, sku_id=9002, product_name="Raw Hair/20/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="20", quantity=1, price_per_piece=Decimal("15.00"),
            ),
        ],
    )
    invoice = service.create_invoice(db, create_payload, user_id=1)
    db.flush()

    # 模拟已成功推单
    kept_id, dropped_id = invoice.items[0].id, invoice.items[1].id
    invoice.items[0].xiaoman_unique_id = "111"
    invoice.items[1].xiaoman_unique_id = "222"
    invoice.xiaoman_order_id = "424242"
    invoice.xiaoman_order_no = "SO-424242"
    invoice.sync_status = "synced"
    invoice.status = "synced"
    db.flush()

    update_payload = InvoiceUpdate(
        customer_id="123456",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 13),
        items=[
            # 回传 id → 传承 unique_id（数量已改）
            InvoiceItemPayload(
                id=kept_id,
                product_id=1, sku_id=9001, product_name="Raw Hair/18/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="18", quantity=5, price_per_piece=Decimal("12.50"),
            ),
            # 新行无 id
            InvoiceItemPayload(
                product_id=3, sku_id=9003, product_name="Raw Hair/22/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="22", quantity=2, price_per_piece=Decimal("18.00"),
            ),
            # 第二条原有行未回传 → 视为删除
        ],
    )
    invoice = service.update_invoice(db, invoice, update_payload, user_id=1)
    db.flush()

    # 编辑保留 OKKI 关联（幂等编辑），同步状态回未同步；
    # 明细完整时 _refresh_invoice_totals 直接回 ready（可再次同步）
    assert invoice.xiaoman_order_id == "424242"
    assert invoice.xiaoman_order_no == "SO-424242"
    assert invoice.sync_status == "not_synced"
    assert invoice.status == "ready"
    # unique_id 传承与删行快照
    assert invoice.items[0].xiaoman_unique_id == "111"
    assert invoice.items[1].xiaoman_unique_id is None
    removed = json.loads(invoice.xiaoman_removed_lines)
    assert [entry["unique_id"] for entry in removed] == ["222"]
    assert removed[0]["product_id"] == 2 and removed[0]["sku_id"] == 9002
    assert dropped_id != kept_id

    # 再编辑一次（回传当前行 id，不再删行）：快照不丢、unique_id 继续传承
    second_payload = InvoiceUpdate(
        customer_id="123456",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 13),
        items=[
            InvoiceItemPayload(
                id=invoice.items[0].id,
                product_id=1, sku_id=9001, product_name="Raw Hair/18/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="18", quantity=6, price_per_piece=Decimal("12.50"),
            ),
            InvoiceItemPayload(
                id=invoice.items[1].id,
                product_id=3, sku_id=9003, product_name="Raw Hair/22/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="22", quantity=2, price_per_piece=Decimal("18.00"),
            ),
        ],
    )
    invoice = service.update_invoice(db, invoice, second_payload, user_id=1)
    db.flush()
    assert invoice.items[0].xiaoman_unique_id == "111"
    assert [entry["unique_id"] for entry in json.loads(invoice.xiaoman_removed_lines)] == ["222"]


def test_replace_items_duplicate_echoed_id_only_first_carries(db):
    # 前端复制行若带上旧 id（或恶意请求），同一 unique_id 绝不能落到两行——
    # OKKI 编辑推单按 unique_id 锚定，两行同 ID 会互相覆盖且金额无声出错
    create_payload = InvoiceCreate(
        customer_id="123456",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 13),
        items=[
            InvoiceItemPayload(
                product_id=1, sku_id=9001, product_name="Raw Hair/18/#1/100g",
                product_display="Raw Hair", net_weight_grams="100g",
                color="#1", length="18", quantity=3, price_per_piece=Decimal("12.50"),
            ),
        ],
    )
    invoice = service.create_invoice(db, create_payload, user_id=1)
    db.flush()
    line_id = invoice.items[0].id
    invoice.items[0].xiaoman_unique_id = "111"
    invoice.xiaoman_order_id = "424242"
    invoice.sync_status = "synced"
    db.flush()

    dup_line = dict(
        id=line_id,
        product_id=1, sku_id=9001, product_name="Raw Hair/18/#1/100g",
        product_display="Raw Hair", net_weight_grams="100g",
        color="#1", length="18", quantity=3, price_per_piece=Decimal("12.50"),
    )
    update_payload = InvoiceUpdate(
        customer_id="123456",
        customer_name="Customer A",
        invoice_date=date(2026, 7, 13),
        items=[InvoiceItemPayload(**dup_line), InvoiceItemPayload(**dup_line)],
    )
    invoice = service.update_invoice(db, invoice, update_payload, user_id=1)
    db.flush()

    assert invoice.items[0].xiaoman_unique_id == "111"
    assert invoice.items[1].xiaoman_unique_id is None
    # id 被回传（即使重复）不算删除，快照不应记录
    assert invoice.xiaoman_removed_lines is None
