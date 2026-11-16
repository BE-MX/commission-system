"""Private management metadata for publishing text presets to the workspace."""


def validate_chat_options(value) -> None:
    if not isinstance(value, dict):
        raise ValueError("chat 必须是 JSON 对象")
    unknown = set(value) - {"enabled", "label", "vision", "allowed_roles", "pricing"}
    if unknown:
        raise ValueError("未知的聊天配置字段：" + ", ".join(sorted(unknown)))
    from app.ai_chat.billing import pricing_options
    pricing_options(value.get('pricing'))
    for key in ("enabled", "vision"):
        if key in value and type(value[key]) is not bool:
            raise ValueError(f"chat.{key} 必须是布尔值")
    if "label" in value and (not isinstance(value["label"], str) or len(value["label"]) > 128):
        raise ValueError("聊天显示名称最长 128 字")
    roles = value.get("allowed_roles", [])
    if (not isinstance(roles, list) or len(roles) > 100
            or any(not isinstance(role, str) or not role.strip() or len(role) > 50 for role in roles)
            or len(set(roles)) != len(roles)):
        raise ValueError("聊天可用角色必须是不重复的角色标识数组")


def chat_options(preset) -> dict:
    from app.ai_chat.billing import pricing_options
    value = (preset.parameters or {}).get("chat", {})
    validate_chat_options(value)
    legacy = preset.preset_name == "customer_ai_chat"
    return {
        "enabled": value.get("enabled", legacy),
        "label": value.get("label", "").strip() or preset.model,
        "vision": value.get("vision", legacy),
        "allowed_roles": value.get("allowed_roles", []),
        "pricing": pricing_options(value.get('pricing')),
    }
