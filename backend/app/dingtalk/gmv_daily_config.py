"""GMV 日报配置，复用 sys_dict，不创建专用业务表。"""

from __future__ import annotations

import json
from copy import deepcopy

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.auth.service import list_okki_department_options
from app.core.config import get_settings
from app.core.time import beijing_now
from app.dingtalk.gmv_daily_schemas import GmvDailyConfigUpdate
from app.system.models import SysDict
from app.system.reserved_dict_types import (
    ADMIN_DICT_TYPE,
    MEMBER_DICT_TYPE,
    RESERVED_DICT_TYPES,
    TEAM_DICT_TYPE,
)


# 首次上线默认值来自 2026-08-26 已确认的八队、队长及在职名单；保存后台配置后
# 完全以 sys_dict 为准，后续调队不需要改代码。
DEFAULT_TEAMS = [
    {"department_id": 25198, "name": "专治不服", "captain_okki_user_id": "55278718", "members": [
        ("55278718", "毕晓珍", False), ("55278725", "代晴玉", False),
        ("55497300", "刘源", False), ("56158751", "张砚斐", False),
    ]},
    {"department_id": 24925, "name": "多财多亿", "captain_okki_user_id": "55278720", "members": [
        ("55278720", "刘琳琳", False), ("55411216", "翟佳盟", False),
        ("57010933", "胡宁宁", False), ("56786146", "高瑞杰", False),
    ]},
    {"department_id": 24926, "name": "稻乐偲", "captain_okki_user_id": "55278716", "members": [
        ("55278716", "夏新月", False), ("55303520", "宋化通", False),
        ("55296478", "潘康衡", False),
    ]},
    {"department_id": 258940, "name": "行则将至", "captain_okki_user_id": "55298611", "members": [
        ("55298611", "宋皓月", False), ("56646975", "张笑", False),
        ("56843323", "罗馨瑜", True),
    ]},
    {"department_id": 258941, "name": "星星之火", "captain_okki_user_id": "55369626", "members": [
        ("55369626", "李宝珠", False), ("56506160", "刘行行", False),
        ("57125949", "刘也", False),
    ]},
    {"department_id": 258938, "name": "乘风", "captain_okki_user_id": "55531178", "members": [
        ("55531178", "田雯", False), ("56653054", "曲冉", False),
        ("57130855", "凯丽比努尔·阿伍提", True),
    ]},
    {"department_id": 258942, "name": "无名", "captain_okki_user_id": "56046345", "members": [
        ("56046345", "尹德魁", False), ("57180994", "张心茹", False),
    ]},
    {"department_id": 309932, "name": "嘉树", "captain_okki_user_id": "55951723", "members": [
        ("55951723", "周露露", False),
    ]},
]


def _default_config() -> dict:
    teams = []
    for source in DEFAULT_TEAMS:
        team = {key: deepcopy(value) for key, value in source.items() if key != "members"}
        team["is_active"] = True
        team["members"] = [
            {"okki_user_id": user_id, "name": name, "exclude_from_total": excluded, "is_active": True}
            for user_id, name, excluded in source["members"]
        ]
        teams.append(team)
    return {"teams": teams, "admin_recipient_user_ids": [], "persisted": False}


def _parse_member(row: SysDict) -> dict | None:
    try:
        meta = json.loads(row.remark or "{}")
        department_id = int(meta["department_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    user_id = (row.code or "").strip()
    name = (row.label or "").strip()
    if department_id <= 0 or not user_id or not name:
        return None
    return {
        "department_id": department_id,
        "okki_user_id": user_id,
        "name": name,
        "exclude_from_total": bool(meta.get("exclude_from_total")),
        "is_active": bool(row.is_active),
        "sort": int(row.sort or 0),
    }


def load_config(db: Session) -> dict:
    rows = (
        db.query(SysDict)
        .filter(SysDict.type.in_(RESERVED_DICT_TYPES))
        .order_by(SysDict.sort, SysDict.id)
        .all()
    )
    team_rows = [row for row in rows if row.type == TEAM_DICT_TYPE]
    if not team_rows:
        if rows:
            raise ValueError("GMV 日报配置不完整：缺少队伍配置，请在专用配置页重新保存")
        return _default_config()

    members_by_team: dict[int, list[dict]] = {}
    for row in rows:
        if row.type != MEMBER_DICT_TYPE:
            continue
        member = _parse_member(row)
        if not member:
            raise ValueError(f"GMV 日报成员配置损坏：字典项 {row.id}")
        members_by_team.setdefault(member.pop("department_id"), []).append(member)

    teams = []
    for row in team_rows:
        try:
            department_id = int(row.code)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"GMV 日报队伍配置损坏：字典项 {row.id}") from exc
        if department_id <= 0 or department_id in {team["department_id"] for team in teams}:
            raise ValueError(f"GMV 日报队伍部门无效或重复：{row.code}")
        team_name = (row.label or "").strip()
        if not team_name:
            raise ValueError(f"GMV 日报队伍 {row.code} 缺少名称")
        captain_user_id = (row.remark or "").strip()
        if not captain_user_id:
            raise ValueError(f"GMV 日报队伍 {team_name} 缺少队长")
        members = sorted(members_by_team.get(department_id, []), key=lambda item: item["sort"])
        if not members:
            raise ValueError(f"GMV 日报队伍 {team_name} 没有成员配置")
        for member in members:
            member.pop("sort", None)
        teams.append({
            "department_id": department_id,
            "name": team_name,
            "captain_okki_user_id": captain_user_id,
            "is_active": bool(row.is_active),
            "members": members,
        })
    configured_team_ids = {team["department_id"] for team in teams}
    orphan_team_ids = set(members_by_team) - configured_team_ids
    if orphan_team_ids:
        raise ValueError(f"GMV 日报存在无所属队伍的成员配置：{sorted(orphan_team_ids)}")

    admin_rows = [row for row in rows if row.type == ADMIN_DICT_TYPE and row.is_active]
    if any(not row.code.isdigit() or int(row.code) <= 0 for row in admin_rows):
        raise ValueError("GMV 日报管理员接收人配置损坏")
    admin_ids = [int(row.code) for row in admin_rows]
    if len(set(admin_ids)) != len(admin_ids):
        raise ValueError("GMV 日报管理员接收人配置重复")
    return {"teams": teams, "admin_recipient_user_ids": admin_ids, "persisted": True}


def okki_user_bindings(db: Session) -> dict[str, dict]:
    rows = (
        db.query(ArkUserExternalBinding, ArkUser)
        .join(ArkUser, ArkUser.id == ArkUserExternalBinding.ark_user_id)
        .filter(
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
            ArkUser.deleted_at.is_(None),
            ArkUser.is_active.is_(True),
        )
        .order_by(ArkUserExternalBinding.is_primary.desc(), ArkUserExternalBinding.id)
        .all()
    )
    result: dict[str, dict] = {}
    for binding, user in rows:
        result.setdefault(str(binding.external_account_id), {
            "ark_user_id": user.id,
            "name": user.real_name,
            "has_dingtalk": bool((user.dingtalk_id or "").strip()),
            "dingtalk_id": (user.dingtalk_id or "").strip(),
        })
    return result


def admin_users(db: Session, user_ids: list[int] | None = None) -> dict[int, dict]:
    query = db.query(ArkUser).filter(ArkUser.deleted_at.is_(None), ArkUser.is_active.is_(True))
    if user_ids is not None:
        query = query.filter(ArkUser.id.in_(user_ids or [-1]))
    return {
        user.id: {
            "ark_user_id": user.id,
            "name": user.real_name,
            "has_dingtalk": bool((user.dingtalk_id or "").strip()),
            "dingtalk_id": (user.dingtalk_id or "").strip(),
        }
        for user in query.order_by(ArkUser.real_name).all()
    }


def _public_recipient(source: dict) -> dict:
    return {key: value for key, value in source.items() if key != "dingtalk_id"}


def decorate_config(db: Session, config: dict | None = None) -> dict:
    config = deepcopy(config or load_config(db))
    bindings = okki_user_bindings(db)
    for team in config["teams"]:
        captain = bindings.get(team["captain_okki_user_id"], {})
        team.update({
            "captain_ark_user_id": captain.get("ark_user_id"),
            "captain_name": captain.get("name") or team["captain_okki_user_id"],
            "captain_has_dingtalk": bool(captain.get("has_dingtalk")),
        })
    admins = admin_users(db, config["admin_recipient_user_ids"])
    config["admin_recipients"] = [
        _public_recipient(admins.get(
            user_id,
            {"ark_user_id": user_id, "name": f"用户{user_id}", "has_dingtalk": False},
        ))
        for user_id in config["admin_recipient_user_ids"]
    ]
    return config


def config_options(db: Session) -> dict:
    bindings = okki_user_bindings(db)
    recipients = [_public_recipient(value) for value in admin_users(db).values()]
    captain_options = [dict(_public_recipient(value), okki_user_id=key) for key, value in bindings.items()]
    captain_options.sort(key=lambda item: item["name"])
    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(text(f"""
        SELECT DISTINCT ub.user_id, ub.full_name, ub.nickname
        FROM `{schema}`.user_basic ub
        JOIN supervisor_relation_history sr ON sr.salesperson_id = ub.user_id AND sr.is_current = 1
        ORDER BY ub.full_name
    """)).mappings().all()
    member_options = [
        {
            "okki_user_id": str(row["user_id"]),
            "name": row["full_name"] or row["nickname"] or str(row["user_id"]),
            "has_dingtalk": bool(bindings.get(str(row["user_id"]), {}).get("has_dingtalk")),
        }
        for row in rows
    ]
    return {
        "departments": list_okki_department_options(db),
        "captains": captain_options,
        "members": member_options,
        "admin_recipients": recipients,
    }


def save_config(db: Session, request: GmvDailyConfigUpdate) -> dict:
    department_ids: set[int] = set()
    member_ids: set[str] = set()
    bindings = okki_user_bindings(db)
    for team in request.teams:
        if team.department_id in department_ids:
            raise ValueError(f"队伍部门重复：{team.department_id}")
        department_ids.add(team.department_id)
        captain = bindings.get(team.captain_okki_user_id)
        if team.is_active and (not captain or not captain["has_dingtalk"]):
            raise ValueError(f"队长 {team.captain_okki_user_id} 未绑定有效钉钉账号")
        for member in team.members:
            if member.okki_user_id in member_ids:
                raise ValueError(f"成员 {member.name} 重复归属多个队伍")
            member_ids.add(member.okki_user_id)

    admins = admin_users(db, request.admin_recipient_user_ids)
    invalid_admins = [user_id for user_id in request.admin_recipient_user_ids if not admins.get(user_id, {}).get("has_dingtalk")]
    if invalid_admins:
        raise ValueError(f"管理员接收人未绑定有效钉钉：{invalid_admins}")

    now = beijing_now()
    try:
        db.query(SysDict).filter(SysDict.type.in_(RESERVED_DICT_TYPES)).delete(synchronize_session=False)
        for team_index, team in enumerate(request.teams):
            db.add(SysDict(
                type=TEAM_DICT_TYPE, code=str(team.department_id), label=team.name,
                remark=team.captain_okki_user_id, sort=team_index,
                is_active=team.is_active, created_at=now, updated_at=now,
            ))
            for member_index, member in enumerate(team.members):
                db.add(SysDict(
                    type=MEMBER_DICT_TYPE,
                    code=member.okki_user_id,
                    label=member.name,
                    remark=json.dumps({
                        "department_id": team.department_id,
                        "exclude_from_total": member.exclude_from_total,
                    }, ensure_ascii=False, separators=(",", ":")),
                    sort=team_index * 1000 + member_index,
                    is_active=member.is_active,
                    created_at=now,
                    updated_at=now,
                ))
        for index, user_id in enumerate(request.admin_recipient_user_ids):
            db.add(SysDict(
                type=ADMIN_DICT_TYPE, code=str(user_id), label=admins[user_id]["name"],
                sort=index, is_active=True, created_at=now, updated_at=now,
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return decorate_config(db)
