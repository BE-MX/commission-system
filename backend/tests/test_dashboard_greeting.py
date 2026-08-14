"""工作台 AI 问候：AI 成功 / 失败兜底 / 无预设兜底 / 缓存 / refresh 绕过 / HTTP 鉴权"""

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.models import AiPreset, AiProvider
from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.dashboard import greeting_service
from app.dashboard.schemas import GreetingContext, GreetingRequest


def _user(db, username="greeter"):
    user = ArkUser(username=username, password_hash="test-hash", real_name=username)
    db.add(user)
    db.flush()
    return user


def _payload(**ctx_kwargs):
    ctx = {
        "date": "2026-08-13", "weekday": "星期四", "period": "下午",
        "user_name": "小明", "holidays_today": [],
        "upcoming_holidays": ["美国·劳动节(还有18天)"],
        "pending": {"物流异常": 2},
    }
    ctx.update(ctx_kwargs)
    return GreetingRequest(context=GreetingContext(**ctx))


def _preset(db, name="dashboard_greeting"):
    provider = AiProvider(name=f"pv-{name}", api_base="https://example.invalid/v1")
    db.add(provider)
    db.flush()
    preset = AiPreset(preset_name=name, provider_id=provider.id, model="test-model")
    db.add(preset)
    db.flush()
    return preset


def setup_function():
    greeting_service._CACHE.clear()
    greeting_service._REFRESH_TS.clear()


# ---------------- 无预设 → 规则兜底 ----------------

def test_fallback_when_no_preset(db):
    result = greeting_service.get_greeting(db, 1, "小明", _payload())
    assert result["source"] == "fallback"
    assert result["text"]
    assert result["date"] == "2026-08-13"


def test_fallback_uses_holiday_context(db):
    result = greeting_service.get_greeting(
        db, 1, "小明", _payload(holidays_today=["美国·独立日"])
    )
    assert result["source"] == "fallback"
    assert isinstance(result["text"], str) and len(result["text"]) > 0


# ---------------- AI 路径 ----------------

def test_ai_success_sanitizes_and_caches(db, monkeypatch):
    _preset(db)
    calls = []

    def fake_chat(db_, preset_name, messages, **kwargs):
        calls.append(preset_name)
        return {"content": ' "周五了，稳住。\n第二行" ', "tokens_used": 10}

    monkeypatch.setattr(greeting_service, "chat", fake_chat)
    result = greeting_service.get_greeting(db, 1, "小明", _payload())
    assert result["source"] == "ai"
    assert "\n" not in result["text"] and '"' not in result["text"]

    # 同日同人第二次命中缓存，不再调模型
    again = greeting_service.get_greeting(db, 1, "小明", _payload())
    assert again == result
    assert len(calls) == 1

    # refresh 绕过缓存重新生成
    refreshed = greeting_service.get_greeting(
        db, 1, "小明", GreetingRequest(refresh=True, context=_payload().context)
    )
    assert len(calls) == 2
    assert refreshed["source"] == "ai"


def test_ai_failure_falls_back(db, monkeypatch):
    _preset(db)

    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(greeting_service, "chat", boom)
    result = greeting_service.get_greeting(db, 1, "小明", _payload())
    assert result["source"] == "fallback"
    assert result["text"]


def test_ai_retries_next_provider(db, monkeypatch):
    """首个 provider 失败时应重试下一个候选预设，而不是直接兜底。"""
    _preset(db, name="p1")
    _preset(db, name="p2")

    def flaky(db_, preset_name, messages, **kwargs):
        if preset_name == "p1":
            raise RuntimeError("p1 down")
        return {"content": "换一家就好了", "tokens_used": 5}

    monkeypatch.setattr(greeting_service, "chat", flaky)
    result = greeting_service.get_greeting(db, 1, "小明", _payload())
    assert result["source"] == "ai"
    assert result["text"] == "换一家就好了"


def test_refresh_rate_limited(db, monkeypatch):
    """refresh 直达付费模型：冷却期内的重复刷新必须吃缓存，不再调模型。"""
    _preset(db)
    calls = []

    def fake_chat(db_, preset_name, messages, **kwargs):
        calls.append(preset_name)
        return {"content": f"第{len(calls)}句", "tokens_used": 1}

    monkeypatch.setattr(greeting_service, "chat", fake_chat)
    greeting_service.get_greeting(db, 1, "小明", _payload())          # 首次
    greeting_service.get_greeting(db, 1, "小明", GreetingRequest(refresh=True, context=_payload().context))  # 刷新 1：放行
    assert len(calls) == 2
    hit = greeting_service.get_greeting(db, 1, "小明", GreetingRequest(refresh=True, context=_payload().context))  # 冷却内：吃缓存
    assert len(calls) == 2
    assert hit["text"] == "第2句"


def test_accio_work_preset_skipped(db, monkeypatch):
    """accio_work 类型 provider 的预设不可用于 chat，应跳过走兜底。"""
    provider = AiProvider(
        name="accio", api_base="https://example.invalid", provider_type="accio_work"
    )
    db.add(provider)
    db.flush()
    db.add(AiPreset(preset_name="dashboard_greeting", provider_id=provider.id, model="m"))
    db.flush()

    monkeypatch.setattr(
        greeting_service, "chat",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该被调用")),
    )
    result = greeting_service.get_greeting(db, 1, "小明", _payload())
    assert result["source"] == "fallback"


# ---------------- HTTP 层 ----------------

@contextmanager
def _client(db, user=None):
    from app.dashboard.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/dashboard")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    headers = {}
    if user is not None:
        token = create_access_token({
            "sub": str(user.id), "username": user.username,
            "real_name": user.real_name, "roles": [], "permissions": [],
        })
        headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app, headers=headers) as client:
        yield client


def test_http_greeting_requires_token(db):
    with _client(db) as client:
        assert client.post("/api/dashboard/greeting", json={}).status_code in (401, 403)


def test_http_greeting_ok(db):
    user = _user(db, "http_greeter")
    with _client(db, user) as client:
        resp = client.post("/api/dashboard/greeting", json=_payload().model_dump())
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["source"] in ("ai", "fallback")
        assert data["text"]
