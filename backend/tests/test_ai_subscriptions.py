"""AI 订阅管理、统一单价、全链路计费与预设功能归属回归测试。"""

from datetime import date, datetime, timedelta
from decimal import Decimal
import os
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai import billing_service, preset_service, subscription_service
from app.ai.call_service import chat
from app.ai.image_service import generate_image
from app.ai.logo_storage import detect_logo_type
from app.ai.models import (
    AiBalanceCheckpoint,
    AiCallLog,
    AiModelPrice,
    AiPreset,
    AiProvider,
    AiProviderBilling,
)
from app.ai.router import router as ai_router
from app.api.deps import get_db
from app.auth.dependencies import get_current_user
from app.core.time import beijing_now


def _make_provider(db, name="TestProvider", *, provider_type="direct", api_type="openai", is_enabled=True):
    p = AiProvider(
        name=name,
        provider_type=provider_type,
        api_base="https://api.example.test/v1",
        api_key="encrypted-secret",
        api_type=api_type,
        is_enabled=is_enabled,
        timeout_sec=60,
    )
    db.add(p)
    db.flush()
    return p


def _make_preset(db, provider, name="waybill_ocr", *, model="deepseek-chat", feature_key="tracking", parameters=None):
    pr = AiPreset(
        preset_name=name,
        provider_id=provider.id,
        model=model,
        feature_key=feature_key,
        parameters=parameters or {},
        is_enabled=True,
    )
    db.add(pr)
    db.flush()
    return pr


# ── 1. 计费异常绝对不污染成功调用 ─────────────────────────────────

def test_chat_billing_exception_never_breaks_successful_call(db, monkeypatch):
    provider = _make_provider(db, "IsolatedChatProvider")
    _make_preset(db, provider, "iso_chat", model="deepseek-chat")
    db.commit()

    monkeypatch.setattr("app.ai.call_service.decrypt_key", lambda k: "plain-key")
    monkeypatch.setattr(
        "app.ai.call_service.post_json",
        lambda *a, **kw: {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        },
    )

    def boom(*a, **kw):
        raise RuntimeError("billing db exploded")

    monkeypatch.setattr(billing_service, "_resolve_cost", boom)

    res = chat(db, "iso_chat", [{"role": "user", "content": "hi"}], caller_module="logistics")
    assert res["content"] == "hello"

    log = db.query(AiCallLog).filter(AiCallLog.id == res["log_id"]).one()
    assert log.status == "success"
    assert log.provider_id == provider.id
    assert log.finished_at is not None
    assert log.cost_status == "unpriced"
    assert log.usage_detail == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}


def test_image_generation_billing_exception_never_marks_error(db, monkeypatch):
    provider = _make_provider(db, "IsolatedImageProvider")
    _make_preset(db, provider, "design_image_generation", model="gpt-image-2")
    db.commit()

    monkeypatch.setattr("app.ai.image_service.decrypt_key", lambda k: "plain-key")
    monkeypatch.setattr(
        "app.ai.image_service._send_with_retry",
        lambda *a, **kw: SimpleNamespace(
            json={
                "data": [{"b64_json": "AAAA"}],
                "usage": {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
            },
            attempts=1,
            request_id="req-1",
            output_format="png",
        ),
    )
    monkeypatch.setattr(billing_service, "_resolve_cost", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    res = generate_image(db, "design_image_generation", "draw a wig", caller_module="design_image")
    assert res["content"].startswith("data:image/")
    log = db.query(AiCallLog).filter(AiCallLog.id == res["log_id"]).one()
    assert log.status == "success"
    assert log.provider_id == provider.id
    assert log.cost_status == "unpriced"


# ── 2. 统一单价模式、兼容回退、不回溯历史与 Agent 预扣隔离 ──────────

def test_pricing_modes_fallback_and_no_retroactive_change(db):
    p = _make_provider(db, "PriceProvider")
    subscription_service.replace_model_prices(
        db,
        p.id,
        [
            {"model": "m-token", "pricing_mode": "token", "input_per_million": Decimal("2.500000"), "output_per_million": Decimal("10.000000"), "currency": "CNY"},
            {"model": "m-call", "pricing_mode": "per_call", "per_call_amount": Decimal("0.350000"), "currency": "USD"},
            {"model": "m-rate", "pricing_mode": "image_rate_card", "currency": "USD"},
        ],
    )

    # token 模式：10000 input * 2.5/1M + 5000 output * 10/1M = 0.025 + 0.05 = 0.075000 CNY
    log1 = AiCallLog(caller_module="logistics", preset_name="p1", provider_id=p.id, provider_type="direct", model="m-token", status="success")
    db.add(log1)
    db.commit()
    billing_service.settle_call_log_cost(
        db, log1.id, provider_id=p.id, provider_type="direct", model="m-token",
        preset_name="p1", caller_module="logistics", status="success",
        tokens_prompt=10000, tokens_completion=5000,
    )
    db.refresh(log1)
    assert log1.cost_status == "priced"
    assert log1.cost_amount == Decimal("0.075000")
    assert log1.cost_currency == "CNY"

    # 单价变更不回溯历史日志
    subscription_service.replace_model_prices(
        db,
        p.id,
        [{"model": "m-token", "pricing_mode": "token", "input_per_million": Decimal("20"), "output_per_million": Decimal("40"), "currency": "CNY"}],
    )
    db.refresh(log1)
    assert log1.cost_amount == Decimal("0.075000")

    # per_call 模式（无需 token）
    subscription_service.replace_model_prices(
        db, p.id,
        [
            {"model": "m-call", "pricing_mode": "per_call", "per_call_amount": Decimal("0.350000"), "currency": "USD"},
            {"model": "m-rate", "pricing_mode": "image_rate_card", "currency": "USD"},
        ],
    )
    log2 = AiCallLog(caller_module="expo", preset_name="p2", provider_id=p.id, provider_type="direct", model="m-call", status="success")
    db.add(log2)
    db.commit()
    billing_service.settle_call_log_cost(
        db, log2.id, provider_id=p.id, provider_type="direct", model="m-call",
        preset_name="p2", caller_module="expo", status="success",
    )
    db.refresh(log2)
    assert log2.cost_status == "priced"
    assert log2.cost_amount == Decimal("0.350000")
    assert log2.cost_currency == "USD"

    # image_rate_card 模式
    rate_card = {"input_text_microusd_per_token": 5, "output_image_microusd_per_token": 40}
    usage_detail = {"input_tokens_details": {"text_tokens": 1000}, "output_tokens_details": {"image_tokens": 2000}}
    log3 = AiCallLog(caller_module="design_image", preset_name="p3", provider_id=p.id, provider_type="direct", model="m-rate", status="success")
    db.add(log3)
    db.commit()
    billing_service.settle_call_log_cost(
        db, log3.id, provider_id=p.id, provider_type="direct", model="m-rate",
        preset_name="p3", caller_module="design_image", status="success",
        usage_detail=usage_detail, preset_parameters={"rate_card": rate_card},
    )
    db.refresh(log3)
    assert log3.cost_status == "priced"
    assert log3.cost_amount == Decimal("0.085000")  # (5000 + 80000) / 1_000_000
    assert log3.cost_currency == "USD"

    # 兼容回退 parameters.chat.pricing
    log4 = AiCallLog(caller_module="ai_chat", preset_name="customer_ai_chat", provider_id=p.id, provider_type="direct", model="unregistered-model", status="success")
    db.add(log4)
    db.commit()
    billing_service.settle_call_log_cost(
        db, log4.id, provider_id=p.id, provider_type="direct", model="unregistered-model",
        preset_name="customer_ai_chat", caller_module="ai_chat", status="success",
        tokens_prompt=100000, tokens_completion=50000,
        preset_parameters={"chat": {"pricing": {"currency": "USD", "input_per_million": "3", "output_per_million": "15"}}},
    )
    db.refresh(log4)
    assert log4.cost_status == "priced"
    assert log4.cost_amount == Decimal("1.050000")
    assert log4.price_snapshot["source"] == "fallback_chat_pricing"

    # Agent Runtime 保守预扣（accounting_source='reservation'）严禁算作真实消费
    log5 = AiCallLog(caller_module="agent_runtime", preset_name="agent_runtime_copilot", provider_id=p.id, provider_type="direct", model="m-call", status="success")
    db.add(log5)
    db.commit()
    billing_service.settle_call_log_cost(
        db, log5.id, provider_id=p.id, provider_type="direct", model="m-call",
        preset_name="agent_runtime_copilot", caller_module="agent_runtime", status="success",
        tokens_prompt=99999, tokens_completion=4000, accounting_source="reservation",
    )
    db.refresh(log5)
    assert log5.cost_status == "no_usage"
    assert log5.cost_amount is None

    # 测试调用单列 test，不计入消费
    log6 = AiCallLog(caller_module="ai_preset_test", preset_name="p1", provider_id=p.id, provider_type="direct", model="m-call", status="success")
    db.add(log6)
    db.commit()
    billing_service.settle_call_log_cost(
        db, log6.id, provider_id=p.id, provider_type="direct", model="m-call",
        preset_name="p1", caller_module="ai_preset_test", status="success",
    )
    db.refresh(log6)
    assert log6.cost_status == "test"
    assert log6.cost_amount is None


# ── 3. 多维度告警不遮蔽、续费顺延、余额精确截点、异币种、总账守恒 ──

def test_multidim_alerts_balance_cutoff_and_ledger_conservation(db, monkeypatch):
    fixed_today = date(2026, 11, 27)
    fixed_now = datetime(2026, 11, 27, 15, 0, 0)
    monkeypatch.setattr(subscription_service, "beijing_today", lambda: fixed_today)
    monkeypatch.setattr(subscription_service, "beijing_now", lambda: fixed_now)

    # Provider A: 同时待确认续费(2026-11-24) AND 余额不足(0 USD)
    pa = _make_provider(db, "AnthropicOfficial", api_type="anthropic")
    subscription_service.upsert_provider_billing(
        db, pa.id,
        {
            "service_kind": "official",
            "plan_name": "Team",
            "billing_mode": "monthly",
            "is_balance_deducted_by_usage": True,
            "price_amount": Decimal("180.00"),
            "price_currency": "USD",
            "subscribed_at": date(2026, 10, 24),
            "renew_at": date(2026, 11, 24),
            "low_balance_threshold": Decimal("10"),
        },
    )
    subscription_service.create_balance_checkpoint(
        db, pa.id,
        {"checkpoint_kind": "reconcile", "balance_amount": Decimal("0"), "balance_currency": "USD", "recorded_at": datetime(2026, 11, 24, 10, 0, 0)},
    )

    # Provider B: 当天 15:00 登记余额 100 CNY；上午 10:00 的 30 CNY 调用不应被重复扣减，16:00 的 20 CNY 才扣减
    pb = _make_provider(db, "DeepSeek")
    subscription_service.upsert_provider_billing(
        db, pb.id,
        {
            "service_kind": "official",
            "billing_mode": "pay_as_you_go",
            "is_balance_deducted_by_usage": True,
            "low_balance_threshold": Decimal("50"),
        },
    )
    subscription_service.create_balance_checkpoint(
        db, pb.id,
        {"checkpoint_kind": "reconcile", "balance_amount": Decimal("100"), "balance_currency": "CNY", "recorded_at": datetime(2026, 11, 27, 15, 0, 0)},
    )
    db.add_all([
        AiCallLog(
            caller_module="logistics", preset_name="p", provider_id=pb.id, provider_type="direct",
            status="success", finished_at=datetime(2026, 11, 27, 10, 0, 0),
            cost_status="priced", cost_amount=Decimal("30.000000"), cost_currency="CNY",
        ),
        AiCallLog(
            caller_module="logistics", preset_name="p", provider_id=pb.id, provider_type="direct",
            status="success", finished_at=datetime(2026, 11, 27, 16, 0, 0),
            cost_status="priced", cost_amount=Decimal("20.000000"), cost_currency="CNY",
        ),
        # 在途 pending 调用不扣减余额但计入 inflight_count
        AiCallLog(
            caller_module="logistics", preset_name="p", provider_id=pb.id, provider_type="direct",
            status="pending",
        ),
        # 存量 legacy 与 test 不入汇总
        AiCallLog(
            caller_module="logistics", preset_name="p", provider_id=pb.id, provider_type="direct",
            status="success", finished_at=datetime(2026, 11, 27, 16, 5, 0),
            cost_status="legacy", cost_amount=Decimal("999.000000"), cost_currency="CNY",
        ),
        AiCallLog(
            caller_module="ai_preset_test", preset_name="p", provider_id=pb.id, provider_type="direct",
            status="success", finished_at=datetime(2026, 11, 27, 16, 6, 0),
            cost_status="test", cost_amount=Decimal("88.000000"), cost_currency="CNY",
        ),
    ])

    # Provider C: 异币种消费导致余额不可用
    pc = _make_provider(db, "MixedCurRelay")
    subscription_service.upsert_provider_billing(
        db, pc.id, {"service_kind": "relay", "billing_mode": "pay_as_you_go", "is_balance_deducted_by_usage": True},
    )
    subscription_service.create_balance_checkpoint(
        db, pc.id,
        {"checkpoint_kind": "reconcile", "balance_amount": Decimal("100"), "balance_currency": "CNY", "recorded_at": datetime(2026, 11, 20, 0, 0, 0)},
    )
    db.add(AiCallLog(
        caller_module="expo", preset_name="img", provider_id=pc.id, provider_type="direct",
        status="success", finished_at=datetime(2026, 11, 21, 10, 0, 0),
        cost_status="priced", cost_amount=Decimal("5.000000"), cost_currency="USD",
    ))

    # Provider D: 已软删提供商的本月日志仍须计入全平台总账
    pd = _make_provider(db, "DeletedOldRelay")
    pd.deleted_at = datetime(2026, 11, 20, 12, 0, 0)
    db.add(AiCallLog(
        caller_module="insight", preset_name="old", provider_id=pd.id, provider_type="direct",
        status="success", finished_at=datetime(2026, 11, 10, 10, 0, 0),
        cost_status="priced", cost_amount=Decimal("15.500000"), cost_currency="CNY",
    ))
    db.commit()

    res = subscription_service.list_subscriptions(db)
    summary = res["summary"]
    by_id = {item["id"]: item for item in res["items"]}

    # Provider A 主标签 renew_pending + 副标签 balance_empty，同时计入两个预警维度
    assert by_id[pa.id]["status"] == "renew_pending"
    assert by_id[pa.id]["secondary_flags"] == ["balance_empty"]
    assert summary["renew_alert_count"] == 1
    assert summary["balance_alert_count"] == 1

    # Provider B 仅扣 16:00 的 20 CNY => 100 - 20 = 80.0000，且 inflight=1
    assert by_id[pb.id]["balance"]["estimated_amount"] == "80.0000"
    assert by_id[pb.id]["balance"]["remaining_pct"] == 80
    assert by_id[pb.id]["balance"]["inflight_count"] == 1

    # Provider C 异币种不可估算
    assert by_id[pc.id]["balance"]["currency_mismatch"] is True
    assert by_id[pc.id]["balance"]["estimated_amount"] is None

    # 总账守恒：CNY = 30 + 20 + 15.5(软删) = 65.50；USD = 5.00；固定订阅单列 180.00 USD
    month_map = {x["currency"]: x["amount"] for x in summary["month_spend"]}
    assert month_map == {"CNY": "65.50", "USD": "5.00"}
    assert summary["fixed_subscriptions_monthly"] == [{"currency": "USD", "amount": "180.00"}]

    # 确认续费：2026-11-24 -> 2026-12-24
    renewed = subscription_service.confirm_provider_renew(db, pa.id)
    assert renewed["renew_at"] == "2026-12-24"
    # 月末日期顺延边界：2026-01-31 + 1 month -> 2026-02-28
    assert subscription_service.add_billing_cycle(date(2026, 1, 31), "monthly") == date(2026, 2, 28)

    # 再次登记余额记录漂移快照 estimated_before_amount（同时验证倒填历史截点与截点上限）
    cp_backdated = subscription_service.create_balance_checkpoint(
        db, pb.id,
        {"checkpoint_kind": "reconcile", "balance_amount": Decimal("120"), "balance_currency": "CNY", "recorded_at": datetime(2026, 11, 26, 10, 0, 0)},
    )
    assert cp_backdated["estimated_before_amount"] is None

    cp2 = subscription_service.create_balance_checkpoint(
        db, pb.id,
        {"checkpoint_kind": "reconcile", "balance_amount": Decimal("76"), "balance_currency": "CNY", "recorded_at": datetime(2026, 11, 27, 17, 0, 0)},
    )
    assert cp2["estimated_before_amount"] == "80.0000"
    assert cp2["drift_amount"] == "-4.0000"


# ── 4. 安全校验（https、LOGO 禁 SVG、403 权限）与预设归属 ──────────

def test_security_logo_https_and_preset_feature_validation(db):
    p = _make_provider(db, "SecProvider")
    db.commit()

    with pytest.raises(ValueError, match="https"):
        subscription_service.upsert_provider_billing(db, p.id, {"console_url": "http://insecure.example"})
    with pytest.raises(ValueError, match="https"):
        subscription_service.upsert_provider_billing(db, p.id, {"console_url": "https://:443"})

    # 校验真实运行时预设名都能映射到 feature_catalog
    from app.ai.feature_catalog import default_feature_for_preset
    assert default_feature_for_preset("whatsapp_message_assistant") == "whatsapp"
    assert default_feature_for_preset("factory_delivery_ocr") == "stock"
    assert default_feature_for_preset("client_desk_daily") == "client_desk"
    assert default_feature_for_preset("client_desk_unlinked") == "client_desk"
    assert default_feature_for_preset("pcw_conversation_summary") == "client_desk"
    assert default_feature_for_preset("pm_diff") == "pm_hub"

    # LOGO magic bytes 校验：PNG 通过，SVG / 伪造文本拒绝
    assert detect_logo_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32) == ("image/png", "png")
    with pytest.raises(ValueError, match="SVG"):
        detect_logo_type(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    with pytest.raises(ValueError, match="PNG"):
        detect_logo_type(b"not-an-image-at-all")
    with pytest.raises(ValueError, match="512KB"):
        detect_logo_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * (513 * 1024))

    # 新建预设无 feature_key 拒绝
    with pytest.raises(ValueError, match="所属功能"):
        preset_service.create_preset(db, {"preset_name": "no_feat_preset", "provider_id": p.id, "model": "m"})

    created = preset_service.create_preset(
        db, {"preset_name": "valid_feat_preset", "provider_id": p.id, "model": "m", "feature_key": "tracking"},
    )
    assert created.feature_key == "tracking"
    listed = preset_service.list_presets(db, feature_keys=["tracking"])
    assert len(listed) == 1 and listed[0]["feature_label"] == "物流跟踪"


def test_subscription_endpoint_requires_ai_admin_permission_and_admin_writes(db, tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(ai_router, prefix="/api/ai")

    def override_db():
        yield db

    # 1. 模拟普通业务用户（无 ai:admin 权限）应返回 403
    sales_user = {"sub": "99", "username": "sales", "roles": ["sales"], "permissions": []}
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: sales_user

    client = TestClient(app)
    assert client.get("/api/ai/subscriptions").status_code == 403

    # 2. 模拟 ai:admin 管理员完成订阅配置、余额登记、单价维护、续费确认、LOGO 上传与预设功能校验
    admin_user = {"sub": "1", "username": "admin", "roles": ["admin"], "permissions": ["ai:admin"]}
    app.dependency_overrides[get_current_user] = lambda: admin_user

    p = _make_provider(db, "HttpAdminProvider")
    db.commit()

    monkeypatch.setattr("app.ai.logo_storage.ROOT", tmp_path)

    r_billing = client.put(
        f"/api/ai/providers/{p.id}/billing",
        json={
            "service_kind": "official",
            "plan_name": "Pro",
            "billing_mode": "monthly",
            "is_balance_deducted_by_usage": True,
            "price_amount": "20.00",
            "price_currency": "USD",
            "renew_at": "2026-12-01",
            "console_url": "https://console.example.test",
            "docs_url": "https://docs.example.test",
        },
    )
    assert r_billing.status_code == 200, r_billing.text

    r_cp = client.post(
        f"/api/ai/providers/{p.id}/balance-checkpoints",
        json={
            "checkpoint_kind": "reconcile",
            "balance_amount": "50.00",
            "balance_currency": "USD",
            "remark": "初始盘点",
        },
    )
    assert r_cp.status_code == 200, r_cp.text
    assert r_cp.json()["data"]["balance_amount"] == "50.0000"
    assert r_cp.json()["data"]["remark"] == "初始盘点"

    r_prices = client.put(
        f"/api/ai/providers/{p.id}/model-prices",
        json={
            "items": [
                {
                    "model": "claude-sonnet-4",
                    "pricing_mode": "token",
                    "input_per_million": "3.00",
                    "output_per_million": "15.00",
                    "currency": "USD",
                }
            ]
        },
    )
    assert r_prices.status_code == 200, r_prices.text
    assert len(r_prices.json()["data"]["items"]) == 1

    r_renew = client.post(f"/api/ai/providers/{p.id}/renew-confirm")
    assert r_renew.status_code == 200, r_renew.text
    assert r_renew.json()["data"]["renew_at"] == "2027-01-01"

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    r_logo_up = client.put(
        f"/api/ai/providers/{p.id}/logo",
        files={"file": ("logo.png", png_bytes, "image/png")},
    )
    assert r_logo_up.status_code == 200, r_logo_up.text
    r_logo_get = client.get(f"/api/ai/providers/{p.id}/logo")
    assert r_logo_get.status_code == 200
    assert r_logo_get.headers["content-type"].startswith("image/png")
    assert r_logo_get.headers["cache-control"] == "private, no-cache"
    assert r_logo_get.headers.get("etag")

    r_subs = client.get("/api/ai/subscriptions")
    assert r_subs.status_code == 200
    sub_item = next(item for item in r_subs.json()["data"]["items"] if item["id"] == p.id)
    assert sub_item["billing"]["has_logo"] is True
    assert sub_item["billing"]["logo_url"] == f"/api/ai/providers/{p.id}/logo"

    r_cat = client.get("/api/ai/feature-catalog")
    assert r_cat.status_code == 200
    assert len(r_cat.json()["data"]["items"]) >= 10


# ── 5. 北京时间跨日/跨月测试（服务器非东八区） ──────────────────────

def test_beijing_month_boundary_under_utc_server_timezone(db, monkeypatch):
    # 模拟服务器在 UTC 时区，且当前为 UTC 2026-11-30 16:30（即北京时间 2026-12-01 00:30）
    prev_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        bj_today = date(2026, 12, 1)
        monkeypatch.setattr(subscription_service, "beijing_today", lambda: bj_today)

        p = _make_provider(db, "TzProvider")
        db.add_all([
            # 北京时间 11 月 30 日 23:59 -> 属上月，不计入 12 月本月消费，计入累计
            AiCallLog(
                caller_module="logistics", preset_name="p", provider_id=p.id, provider_type="direct",
                status="success", finished_at=datetime(2026, 11, 30, 23, 59, 0),
                cost_status="priced", cost_amount=Decimal("10.000000"), cost_currency="CNY",
            ),
            # 北京时间 12 月 1 日 00:01 -> 属本月
            AiCallLog(
                caller_module="logistics", preset_name="p", provider_id=p.id, provider_type="direct",
                status="success", finished_at=datetime(2026, 12, 1, 0, 1, 0),
                cost_status="priced", cost_amount=Decimal("4.500000"), cost_currency="CNY",
            ),
        ])
        db.commit()

        summary = subscription_service.list_subscriptions(db)["summary"]
        assert summary["month_spend"] == [{"currency": "CNY", "amount": "4.50"}]
        assert summary["total_spend"] == [{"currency": "CNY", "amount": "14.50"}]
    finally:
        if prev_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = prev_tz
        if hasattr(time, "tzset"):
            time.tzset()
