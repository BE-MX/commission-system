"""expo 模块共享工具函数。"""


def user_id_from_current_user(current_user) -> int | None:
    """从当前用户依赖中提取用户 ID。

    同时兼容 JWT payload dict（优先用 "id"，回退 "sub" 并转 int）
    与 ArkUser 对象（取 .id）。
    """
    if isinstance(current_user, dict):
        user_id = current_user.get("id") or current_user.get("sub")
        return int(user_id) if user_id is not None else None
    return getattr(current_user, "id", None)
