"""Native GMV configuration is isolated from legacy external account IDs."""
import json
import logging
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from app.auth.models import ArkUser
from app.dingtalk.gmv_daily_schemas import GmvNativeConfigUpdate
from app.system.models import SysDict
from app.system.reserved_dict_types import LOCAL_GMV_DICT_TYPES
from app.trade.department_service import department_options

logger = logging.getLogger(__name__)
TEAM, MEMBER, ADMIN = LOCAL_GMV_DICT_TYPES


def load_native_config(db):
    rows = db.scalars(select(SysDict).where(SysDict.type.in_(LOCAL_GMV_DICT_TYPES)).order_by(SysDict.sort, SysDict.id)).all()
    if not rows:
        return {"source": "local", "teams": [], "admin_recipient_user_ids": [], "persisted": False}
    try:
        teams = []
        for row in rows:
            if row.type != TEAM:
                continue
            members = []
            for member in rows:
                if member.type != MEMBER:
                    continue
                meta = json.loads(member.remark)
                if int(meta["department_id"]) == int(row.code):
                    members.append({"ark_user_id": int(member.code), "name": member.label,
                        "exclude_from_total": meta["exclude_from_total"], "is_active": member.is_active})
            teams.append({"department_id": int(row.code), "name": row.label, "captain_ark_user_id": int(row.remark),
                "is_active": row.is_active, "members": members})
        result = GmvNativeConfigUpdate(source="local", teams=teams,
            admin_recipient_user_ids=[int(row.code) for row in rows if row.type == ADMIN and row.is_active])
        member_count = sum(len(team.members) for team in result.teams)
        if member_count != sum(row.type == MEMBER for row in rows):
            raise ValueError("orphan members")
        return {**result.model_dump(), "persisted": True}
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("本地 GMV 配置损坏，请在专用配置页重新核对保存") from exc


def decorate_native_config(db, config):
    from app.dingtalk.gmv_daily_config import admin_users, _public_recipient
    users = admin_users(db)
    for team in config["teams"]:
        captain = users.get(team["captain_ark_user_id"], {})
        team.update(captain_name=captain.get("name") or str(team["captain_ark_user_id"]),
                    captain_has_dingtalk=bool(captain.get("has_dingtalk")))
    config["admin_recipients"] = [_public_recipient(users.get(uid, {"ark_user_id": uid, "name": str(uid), "has_dingtalk": False}))
        for uid in config["admin_recipient_user_ids"]]
    return config


def native_options(db):
    from app.dingtalk.gmv_daily_config import admin_users, _public_recipient
    people = [_public_recipient(row) for row in admin_users(db).values()]
    return {"source": "local", "departments": department_options(db), "captains": people,
            "members": people, "admin_recipients": people}


def save_native_config(db, request):
    from app.dingtalk.gmv_daily_config import admin_users
    users = {row.id: row for row in db.scalars(select(ArkUser).options(lazyload(ArkUser.roles)))}
    recipients = admin_users(db)
    departments = {item["id"] for item in department_options(db)}
    team_ids, member_ids = set(), set()
    for team in request.teams:
        if team.department_id in team_ids or (team.is_active and team.department_id not in departments):
            raise ValueError("本地日报部门重复、不存在或已停用")
        team_ids.add(team.department_id)
        if team.is_active and not recipients.get(team.captain_ark_user_id, {}).get("has_dingtalk"):
            raise ValueError("队长须为启用且有钉钉账号的方舟员工")
        for member in team.members:
            employee = users.get(member.ark_user_id)
            if member.ark_user_id in member_ids or employee is None or (team.is_active and member.is_active and (
                    not employee.is_active or employee.deleted_at is not None)):
                raise ValueError("本地日报人员重复、不存在或已停用")
            member_ids.add(member.ark_user_id)
            member.name = employee.real_name or employee.username
    admin_ids = request.admin_recipient_user_ids
    if len(set(admin_ids)) != len(admin_ids) or any(not recipients.get(uid, {}).get("has_dingtalk") for uid in admin_ids):
        raise ValueError("管理员接收人重复、已停用或未绑定钉钉")
    try:
        db.query(SysDict).filter(SysDict.type.in_(LOCAL_GMV_DICT_TYPES)).delete(synchronize_session=False)
        for index, team in enumerate(request.teams):
            db.add(SysDict(type=TEAM, code=str(team.department_id), label=team.name,
                remark=str(team.captain_ark_user_id), sort=index, is_active=team.is_active))
            for position, member in enumerate(team.members):
                db.add(SysDict(type=MEMBER, code=str(member.ark_user_id), label=member.name,
                    remark=json.dumps({"department_id": team.department_id, "exclude_from_total": member.exclude_from_total}),
                    sort=index * 1000 + position, is_active=member.is_active))
        for index, uid in enumerate(admin_ids):
            db.add(SysDict(type=ADMIN, code=str(uid), label=recipients[uid]["name"], sort=index, is_active=True))
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Native GMV config save failed", exc_info=True)
        print("Native GMV config save failed; transaction rolled back", flush=True)
        raise
    return decorate_native_config(db, load_native_config(db))
