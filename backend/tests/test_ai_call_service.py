"""带图 chat 的超时下限逻辑（2026-07-08 expo 面容分析超时→kiosk 弹回首页修复）。"""

from types import SimpleNamespace

from app.ai.call_service import (
    MIN_MULTIMODAL_CHAT_TIMEOUT_SEC,
    _effective_chat_timeout,
    _has_image_message,
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
