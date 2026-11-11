"""钉钉 Stream 消息到方舟入站契约的纯转换。"""


def message_payload(message):
    if str(getattr(message, "conversation_type", "")) != "1":
        return None
    text = ""
    if getattr(message, "text", None) is not None:
        text = message.text.content or ""
    elif hasattr(message, "get_text_list"):
        text = "\n".join(message.get_text_list() or [])
    message_id = getattr(message, "message_id", "")
    sender_id = getattr(message, "sender_staff_id", "")
    if not message_id or not sender_id or not text.strip():
        return None
    return {"message_id": message_id, "dingtalk_id": sender_id, "text": text.strip()}
