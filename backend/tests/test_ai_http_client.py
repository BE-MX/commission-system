"""build_anthropic_body 的 OpenAI→Anthropic 多模态转换测试。

背景：expo 面容分析按 OpenAI image_url 格式组装消息，发到 anthropic 类 Provider
时若不转格式，网关静默丢图 → 模型「未收到照片」（2026-07-08 session=28/29/30 实case）。
"""

from app.ai.http_client import build_anthropic_body


def _user_image_msg(url):
    return [
        {"role": "user", "content": [
            {"type": "text", "text": "请分析照片"},
            {"type": "image_url", "image_url": {"url": url}},
        ]},
    ]


def test_data_url_image_converted_to_anthropic_source():
    body = build_anthropic_body("claude", _user_image_msg("data:image/jpeg;base64,/9j/ABCD"))
    blocks = body["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "请分析照片"}
    assert blocks[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "/9j/ABCD"},
    }
    assert "image_url" not in blocks[1]  # 旧格式必须消失


def test_png_media_type_preserved():
    body = build_anthropic_body("claude", _user_image_msg("data:image/png;base64,iVBORw0KGgo"))
    assert body["messages"][0]["content"][1]["source"]["media_type"] == "image/png"


def test_http_url_image_converted_to_url_source():
    body = build_anthropic_body("claude", _user_image_msg("https://cdn.example.com/a.jpg"))
    assert body["messages"][0]["content"][1] == {
        "type": "image", "source": {"type": "url", "url": "https://cdn.example.com/a.jpg"},
    }


def test_text_only_string_content_unchanged():
    body = build_anthropic_body("claude", [{"role": "user", "content": "只有文字"}])
    assert body["messages"][0]["content"] == "只有文字"


def test_text_blocks_untouched():
    body = build_anthropic_body("claude", [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    ])
    assert body["messages"][0]["content"] == [{"type": "text", "text": "hi"}]


def test_malformed_data_url_kept_as_is():
    """非 base64 的 data URL 不猜，保持原块（不伪造 source）。"""
    body = build_anthropic_body("claude", _user_image_msg("data:image/jpeg,rawbytes"))
    block = body["messages"][0]["content"][1]
    assert block["type"] == "image_url"  # 未转换


def test_system_message_lifted_and_stripped():
    """既有行为不回归：system 提到顶层，不留在 messages 里。"""
    msgs = [
        {"role": "system", "content": "你是分析师"},
        *_user_image_msg("data:image/jpeg;base64,/9j/AAAA"),
    ]
    body = build_anthropic_body("claude", msgs, system_prompt="你是分析师")
    assert body["system"] == "你是分析师"
    assert all(m["role"] != "system" for m in body["messages"])
    assert body["messages"][0]["content"][1]["type"] == "image"  # 图仍被转换


def test_assistant_string_content_preserved_in_multiturn():
    """_chat_json 重试会追加 assistant 字符串消息，不能被转换逻辑破坏。"""
    msgs = [
        *_user_image_msg("data:image/jpeg;base64,/9j/BBBB"),
        {"role": "assistant", "content": "上一轮非法 JSON"},
        {"role": "user", "content": "请重新输出合法 JSON"},
    ]
    body = build_anthropic_body("claude", msgs)
    assert body["messages"][1]["content"] == "上一轮非法 JSON"
    assert body["messages"][0]["content"][1]["type"] == "image"
