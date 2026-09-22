"""Roster-scoped access shared by summaries, daily cells and order details."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.battle_report.models import BattleReport, BattleReportMember


def is_admin(user: dict) -> bool:
    return "super_admin" in user.get("roles", []) or "battle_report:admin" in user.get("permissions", [])


def actor_id(user: dict) -> int:
    try:
        return int(user["sub"])
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "登录信息无效") from None


def bound_accounts(db: Session) -> list[dict]:
    records = (db.query(ArkUser, ArkUserExternalBinding)
               .join(ArkUserExternalBinding, ArkUserExternalBinding.ark_user_id == ArkUser.id)
               .filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
                       ArkUserExternalBinding.provider == "okki",
                       ArkUserExternalBinding.binding_status == "active",
                       ArkUserExternalBinding.deleted_at.is_(None)).all())
    by_user, by_external = {}, {}
    for user, binding in records:
        by_user.setdefault(user.id, []).append((user, binding))
        by_external.setdefault(binding.external_account_id, set()).add(user.id)
    result = []
    for items in by_user.values():
        primary = [item for item in items if item[1].is_primary]
        choices = primary or items
        if len(choices) != 1:
            continue  # Ambiguous bindings must be fixed in account administration.
        user, binding = choices[0]
        if not binding.external_account_id.strip() or len(by_external[binding.external_account_id]) != 1:
            continue
        result.append({"ark_user_id": user.id, "okki_user_id": binding.external_account_id,
                       "user_name": user.real_name, "team": user.okki_department_name or ""})
    return sorted(result, key=lambda row: (row["user_name"], row["ark_user_id"]))


def load_report(db, report_id, user, *, lock=False):
    query = db.query(BattleReport).filter(BattleReport.id == report_id)
    if lock:
        query = query.with_for_update().populate_existing()
    report = query.first()
    if report is None:
        raise HTTPException(404, "战报不存在")
    members = db.query(BattleReportMember).filter_by(report_id=report_id).order_by(BattleReportMember.id).all()
    own = next((m for m in members if m.ark_user_id == actor_id(user)), None)
    if not is_admin(user):
        if report.status == "draft" or own is None:
            raise HTTPException(403, "无权访问该战报")
        # An external account reassignment must never silently expose the new owner's orders.
        current = {item["ark_user_id"]: item["okki_user_id"] for item in bound_accounts(db)}
        if current.get(own.ark_user_id) != own.okki_user_id:
            raise HTTPException(422, "当前账号的 OKKI 绑定已失效，请联系管理员在外部账号绑定中核对")
    return report, members, own


def visible_members(report, members, own, user, *, details=False):
    if is_admin(user):
        return members
    if details:
        return [m for m in members if m.team == own.team] if own.is_captain else [own]
    if report.visibility == "self":
        return [own]
    if report.visibility == "team":
        return [m for m in members if m.team == own.team]
    return members


def select_members(members, *, team=None, member_id=None):
    if team is not None and team not in {m.team for m in members}:
        raise HTTPException(403, "无权查看所选业务组")
    if member_id is not None and member_id not in {m.id for m in members}:
        raise HTTPException(403, "无权查看所选业务员")
    return [m for m in members if (team is None or m.team == team)
            and (member_id is None or m.id == member_id)]
