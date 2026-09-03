"""带图 chat 的超时下限逻辑（2026-07-08 expo 面容分析超时→kiosk 弹回首页修复）。"""

import pytest
from types import SimpleNamespace

from app.ai.call_service import (
    MIN_MULTIMODAL_CHAT_TIMEOUT_SEC,
    _effective_chat_timeout,
    _has_image_message,
    _snapshot_messages,
)


def _img_msgs():
    return [{"role": "user", "content": [
        {"type": "text", "text": "分析"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ]}]


def _text_msgs():
    return [{"role": "user", "content": "纯文字"}]


def test_has_image_true_for_image_url_block():
    assert _has_image_message(_img_msgs()) is True


def test_has_image_false_for_text_only():
    assert _has_image_message(_text_msgs()) is False
    assert _has_image_message([{"role": "user", "content": [{"type": "text", "text": "x"}]}]) is False


def test_timeout_floor_applied_when_image_and_provider_below_floor():
    prov = SimpleNamespace(timeout_sec=60)
    assert _effective_chat_timeout(prov, has_image=True) == MIN_MULTIMODAL_CHAT_TIMEOUT_SEC
    assert MIN_MULTIMODAL_CHAT_TIMEOUT_SEC >= 120


def test_timeout_keeps_higher_provider_value_when_image():
    prov = SimpleNamespace(timeout_sec=300)
    assert _effective_chat_timeout(prov, has_image=True) == 300  # 不下调已够大的配置


def test_timeout_unchanged_for_text_only():
    prov = SimpleNamespace(timeout_sec=60)
    assert _effective_chat_timeout(prov, has_image=False) == 60  # 纯文字不加码


def test_timeout_handles_none_provider_timeout():
    prov = SimpleNamespace(timeout_sec=None)
    assert _effective_chat_timeout(prov, has_image=True) == MIN_MULTIMODAL_CHAT_TIMEOUT_SEC
    assert _effective_chat_timeout(prov, has_image=False) == 0


def test_metadata_snapshot_never_persists_knowledge_plaintext():
    secret = "内部定价与客户名单"
    snapshot = _snapshot_messages([{"role": "user", "content": secret}], "metadata")

    assert secret not in snapshot
    assert '"snapshot_mode": "metadata"' in snapshot
    assert "content_sha256" in snapshot


def test_full_snapshot_remains_backward_compatible():
    assert "旧调用正文" in _snapshot_messages(
        [{"role": "user", "content": "旧调用正文"}], "full"
    )

def test_metadata_mode_never_logs_plaintext_on_provider_exception(db, monkeypatch):
    from app.ai.call_service import chat
    from app.ai.models import AiCallLog, AiPreset, AiProvider

    provider = AiProvider(
        name="translation-test-provider",
        provider_type="direct",
        api_base="https://example.invalid",
        api_type="openai",
        is_enabled=True,
        timeout_sec=15,
    )
    db.add(provider)
    db.flush()
    db.add(AiPreset(
        preset_name="test",
        provider_id=provider.id,
        model="test-model",
        is_enabled=True,
    ))
    db.commit()

    def raise_sensitive(*args, **kwargs):
        raise RuntimeError("PRIVATE-WHATSAPP-TEXT")

    monkeypatch.setattr("app.ai.call_service.post_json", raise_sensitive)
    with pytest.raises(RuntimeError, match="PRIVATE-WHATSAPP-TEXT"):
        chat(
            db,
            preset_name="test",
            messages=[{"role": "user", "content": "PRIVATE-WHATSAPP-TEXT"}],
            caller_module="whatsapp_translation",
            snapshot_mode="metadata",
            timeout_sec=15,
        )

    log = db.query(AiCallLog).order_by(AiCallLog.id.desc()).first()
    assert log.error_message == "RuntimeError"
    assert "PRIVATE-WHATSAPP-TEXT" not in log.prompt_snapshot
    assert "PRIVATE-WHATSAPP-TEXT" not in log.error_message


def test_metadata_mode_never_logs_full_provider_response(db, monkeypatch, caplog):
    from app.ai.call_service import chat
    from app.ai.models import AiCallLog, AiPreset, AiProvider

    provider = AiProvider(
        name="metadata-diagnostic-provider",
        provider_type="direct",
        api_base="https://example.invalid",
        api_type="openai",
        is_enabled=True,
        timeout_sec=15,
    )
    db.add(provider)
    db.flush()
    db.add(AiPreset(
        preset_name="metadata-diagnostic",
        provider_id=provider.id,
        model="test-model",
        is_enabled=True,
    ))
    db.commit()
    monkeypatch.setattr("app.ai.call_service.post_json", lambda *args, **kwargs: {
        "choices": [{"message": {"content": ""}}],
        "diagnostic": "PRIVATE-WHATSAPP-TEXT",
        "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
    })
    caplog.clear()

    with caplog.at_level("WARNING"):
        chat(
            db,
            preset_name="metadata-diagnostic",
            messages=[{"role": "user", "content": "PRIVATE-WHATSAPP-TEXT"}],
            caller_module="whatsapp_translation",
            snapshot_mode="metadata",
            timeout_sec=15,
        )

    assert "PRIVATE-WHATSAPP-TEXT" not in caplog.text
    assert "full_result=" not in caplog.text
    log = db.query(AiCallLog).order_by(AiCallLog.id.desc()).first()
    assert log.response_snapshot.startswith('{"snapshot_mode": "metadata"')
    assert "PRIVATE-WHATSAPP-TEXT" not in log.response_snapshot


def test_chat_returns_prompt_and_completion_tokens(db, monkeypatch):
    from app.ai.call_service import chat
    from app.ai.models import AiPreset, AiProvider

    provider = AiProvider(
        name="token-test-provider",
        provider_type="direct",
        api_base="https://example.invalid",
        api_type="openai",
        is_enabled=True,
        timeout_sec=15,
    )
    db.add(provider)
    db.flush()
    db.add(AiPreset(
        preset_name="token-test",
        provider_id=provider.id,
        model="test-model",
        is_enabled=True,
    ))
    db.commit()
    monkeypatch.setattr("app.ai.call_service.post_json", lambda *args, **kwargs: {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
    })
    result = chat(
        db,
        preset_name="token-test",
        messages=[{"role": "user", "content": "text"}],
        caller_module="test",
        timeout_sec=15,
    )
    assert result["tokens_prompt"] == 3
    assert result["tokens_completion"] == 5
    assert result["tokens_used"] == 8
