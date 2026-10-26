"""战队与名单：直接复用 GMV 日报的 sys_dict 战队配置，不重复维护。"""
from sqlalchemy.orm import Session

from app.dingtalk.gmv_daily_config import load_config as load_team_config, okki_user_bindings
from app.perf_goal.models import PerfGoal


def _listed_user_ids(db: Session, period_id: int | None) -> set[int]:
    if period_id is None:
        return set()
    rows = (db.query(PerfGoal.user_id)
            .filter(PerfGoal.period_id == period_id, PerfGoal.granularity == "year")
            .distinct().all())
    return {row[0] for row in rows}


def roster(db: Session, period_id: int | None = None) -> dict:
    """Assemble teams + unassigned from the shared sys_dict team config.

    member.user_id 为方舟账号ID；未绑定 OKKI 的成员为 None（页面按姓名展示）。
    listed = 在该批次内设有任意年度目标。
    """
    config = load_team_config(db)
    bindings = okki_user_bindings(db)
    listed = _listed_user_ids(db, period_id)
    teams = []
    assigned_okki: set[str] = set()
    for team in config["teams"]:
        if not team.get("is_active", True):
            continue
        captain = bindings.get(team["captain_okki_user_id"], {})
        members = []
        for member in team["members"]:
            if not member.get("is_active", True):
                continue
            okki_id = str(member["okki_user_id"])
            assigned_okki.add(okki_id)
            bound = bindings.get(okki_id)
            user_id = bound["ark_user_id"] if bound else None
            members.append({
                "user_id": user_id,
                "okki_user_id": okki_id,
                "name": (bound["name"] if bound else None) or member["name"],
                "is_captain": okki_id == team["captain_okki_user_id"],
                "listed": user_id in listed if user_id is not None else False,
            })
        teams.append({
            "department_id": team["department_id"],
            "name": team["name"],
            "captain_user_id": captain.get("ark_user_id"),
            "captain_name": captain.get("name") or team["captain_okki_user_id"],
            "members": members,
        })
    unassigned = []
    for okki_id, bound in sorted(bindings.items(), key=lambda item: item[1]["name"]):
        if okki_id in assigned_okki:
            continue
        unassigned.append({
            "user_id": bound["ark_user_id"],
            "okki_user_id": okki_id,
            "name": bound["name"],
            "is_captain": False,
            "listed": bound["ark_user_id"] in listed,
        })
    return {"teams": teams, "unassigned": unassigned}


def all_people(roster_data: dict) -> list[dict]:
    """Flat member list: teams first, then unassigned."""
    people = []
    for team in roster_data["teams"]:
        for member in team["members"]:
            people.append({**member, "department_id": team["department_id"], "team_name": team["name"]})
    for member in roster_data["unassigned"]:
        people.append({**member, "department_id": None, "team_name": ""})
    return people


def team_of(roster_data: dict, department_id: int) -> dict | None:
    return next((team for team in roster_data["teams"] if team["department_id"] == department_id), None)


def person_of(roster_data: dict, user_id: int) -> dict | None:
    return next((person for person in all_people(roster_data) if person["user_id"] == user_id), None)
