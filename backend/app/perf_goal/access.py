"""数据范围：管理层看全部，队长看本队，业务员看自己。"""
from fastapi import HTTPException

MANAGEMENT_ROLES = {"super_admin", "admin", "supervisor"}


def is_admin(user: dict) -> bool:
    return "super_admin" in user.get("roles", []) or "perf_goal:admin" in user.get("permissions", [])


def can_read_all(user: dict) -> bool:
    return is_admin(user) or bool(MANAGEMENT_ROLES & set(user.get("roles", [])))


def actor_id(user: dict) -> int:
    try:
        return int(user["sub"])
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "登录信息无效") from None


def captain_department(roster_data: dict, user_id: int) -> int | None:
    for team in roster_data["teams"]:
        if team["captain_user_id"] == user_id:
            return team["department_id"]
    return None


def visible_scope(user: dict, roster_data: dict) -> tuple[str, int | None]:
    """('all', None) 管理层；('team', department_id) 队长；('self', user_id) 业务员。"""
    uid = actor_id(user)
    if can_read_all(user):
        return "all", None
    department_id = captain_department(roster_data, uid)
    if department_id is not None:
        return "team", department_id
    return "self", uid


def require_person_visible(user: dict, roster_data: dict, user_id: int) -> None:
    kind, scope_id = visible_scope(user, roster_data)
    if kind == "all":
        return
    if kind == "team":
        team = next((t for t in roster_data["teams"] if t["department_id"] == scope_id), None)
        if team and any(m["user_id"] == user_id for m in team["members"]):
            return
    if user_id != actor_id(user):
        raise HTTPException(403, "无权查看该业务员")


def require_team_visible(user: dict, roster_data: dict, department_id: int) -> None:
    kind, scope_id = visible_scope(user, roster_data)
    if kind == "all" or (kind == "team" and scope_id == department_id):
        return
    raise HTTPException(403, "无权查看该战队")


def require_company_visible(user: dict, roster_data: dict) -> None:
    if visible_scope(user, roster_data)[0] != "all":
        raise HTTPException(403, "无权查看公司整体数据")


def require_board_visible(user: dict, roster_data: dict) -> None:
    """战队榜与排名表：管理层看全部，队长看本队，业务员不可见。"""
    if visible_scope(user, roster_data)[0] == "self":
        raise HTTPException(403, "业务员仅可查看本人数据")
