"""Battle-report lifecycle and goal writes with optimistic versions and audit trails."""
import logging
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import update

from app.battle_report.access import actor_id, bound_accounts, is_admin, load_report, visible_members
from app.battle_report.models import BattleReport, BattleReportAudit, BattleReportMember
from app.battle_report.statistics import money
from app.core.time import beijing_now

logger = logging.getLogger(__name__)


@contextmanager
def write_transaction(db):
    try:
        yield
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.warning("Battle report write failed", exc_info=True)
        print("Battle report write failed; transaction rolled back", flush=True)
        raise


def require_admin(user):
    if not is_admin(user):
        raise HTTPException(403, "需要战报管理权限")


def report_payload(report, now=None):
    now = now or beijing_now()
    stage = report.status
    if stage == "published":
        stage = "upcoming" if now.date() < report.start_date else "ended" if now.date() > report.end_date else "running"
    return {"id": report.id, "name": report.name, "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(), "target_deadline": report.target_deadline.isoformat(),
            "status": report.status, "stage": stage, "visibility": report.visibility,
            "version": report.version, "currency": report.currency, "basis_version": report.basis_version}


def audit(db, report, user, action, before=None, after=None, reason=""):
    db.add(BattleReportAudit(report_id=report.id, actor_id=actor_id(user), action=action,
                            before=before, after=after, reason=reason, created_at=beijing_now()))


def validate_roster(db, inputs, existing=()):
    available = {item["ark_user_id"]: item for item in bound_accounts(db)}
    old = {m.ark_user_id: m for m in existing}
    resolved = []
    for item in inputs:
        account = available.get(item.ark_user_id)
        if account is None:
            if item.ark_user_id in old:
                member = old[item.ark_user_id]
                account = {"ark_user_id": member.ark_user_id, "okki_user_id": member.okki_user_id,
                           "user_name": member.user_name}
            else:
                raise HTTPException(422, "所选业务员须有唯一有效的 OKKI 绑定，请在系统管理 → 外部账号绑定中配置")
        if item.ark_user_id in old:
            # Existing reports retain the external identity even after HR/organization edits.
            member = old[item.ark_user_id]
            account = {**account, "okki_user_id": member.okki_user_id, "user_name": member.user_name}
        resolved.append({**account, "team": item.team, "is_captain": item.is_captain})
    if len({r["okki_user_id"] for r in resolved}) != len(resolved):
        raise HTTPException(422, "不同参与人不能共用同一个 OKKI 账号")
    return resolved


def list_reports(db, user, archived=False):
    query = db.query(BattleReport)
    if not is_admin(user):
        query = query.join(BattleReportMember).filter(BattleReportMember.ark_user_id == actor_id(user),
                                                      BattleReport.status != "draft")
    query = query.filter(BattleReport.status == "archived" if archived else BattleReport.status != "archived")
    return {"items": [report_payload(r) for r in query.order_by(BattleReport.id.desc()).all()],
            "can_admin": is_admin(user)}


def create_report(db, user, payload):
    require_admin(user)
    with write_transaction(db):
        roster = validate_roster(db, payload.members)
        report = BattleReport(**payload.model_dump(exclude={"members"}), created_by=actor_id(user))
        db.add(report)
        db.flush()
        for item in roster:
            db.add(BattleReportMember(report_id=report.id, **item))
        audit(db, report, user, "create", after={**report_payload(report), "members": roster})
    return report_payload(report)


def member_payload(member, report, own, user):
    can_edit = report.status != "archived" and (is_admin(user) or (
        "battle_report:write" in user.get("permissions", []) and report.status == "published"
        and own and own.id == member.id and beijing_now() <= report.target_deadline))
    return {"id": member.id, "ark_user_id": member.ark_user_id, "okki_user_id": member.okki_user_id,
            "user_name": member.user_name, "team": member.team, "is_captain": member.is_captain,
            "target_usd": money(member.target_usd) if member.target_usd is not None else None,
            "version": member.version, "can_edit": bool(can_edit)}


def get_report(db, report_id, user):
    report, members, own = load_report(db, report_id, user)
    visible = visible_members(report, members, own, user)
    details = visible_members(report, members, own, user, details=True)
    return {**report_payload(report), "members": [member_payload(m, report, own, user) for m in visible],
            "detail_member_ids": [m.id for m in details], "can_admin": is_admin(user),
            "own_member_id": own.id if own else None}


def bump_report(db, report, version, **values):
    changed = db.execute(update(BattleReport).where(BattleReport.id == report.id, BattleReport.version == version)
                         .values(**values, version=version + 1, updated_at=beijing_now())
                         .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, "战报已被他人修改，请重新载入")
    db.refresh(report)


def update_report(db, report_id, user, payload):
    require_admin(user)
    with write_transaction(db):
        report, members, own = load_report(db, report_id, user, lock=True)
        if report.status == "archived":
            raise HTTPException(409, "请先恢复归档战报")
        if report.status == "published" and report.start_date <= beijing_now().date() and not payload.reason:
            raise HTTPException(422, "进行中或已结束战报更正必须填写原因；更正将重算整个周期")
        before = {**report_payload(report), "members": [member_payload(m, report, own, user) for m in members]}
        roster = validate_roster(db, payload.members, members)
        bump_report(db, report, payload.version, **payload.model_dump(exclude={"members", "reason", "version"}))
        keep = {r["ark_user_id"] for r in roster}
        old = {m.ark_user_id: m for m in members}
        for m in members:
            if m.ark_user_id not in keep:
                db.delete(m)
        db.flush()  # Release roster unique keys before replacing a transferred external identity.
        for item in roster:
            if item["ark_user_id"] in old:
                m = old[item["ark_user_id"]]
                m.team, m.is_captain = item["team"], item["is_captain"]
                m.version += 1  # Invalidate goal forms opened against the previous activity configuration.
            else:
                db.add(BattleReportMember(report_id=report.id, **item))
        audit(db, report, user, "configure", before, {**report_payload(report), "members": roster}, payload.reason)
    return get_report(db, report_id, user)


def change_state(db, report_id, user, payload):
    require_admin(user)
    with write_transaction(db):
        report, members, _ = load_report(db, report_id, user, lock=True)
        allowed = {("draft", "publish"): "published", ("published", "archive"): "archived",
                   ("archived", "restore"): "published"}
        status = allowed.get((report.status, payload.action))
        if status is None:
            raise HTTPException(409, "当前状态不支持此操作")
        if payload.action == "publish":
            if not members:
                raise HTTPException(422, "请先配置参与人")
            current = {r["ark_user_id"]: r["okki_user_id"] for r in bound_accounts(db)}
            if any(current.get(m.ark_user_id) != m.okki_user_id for m in members):
                raise HTTPException(422, "发布前请核对参与人的 OKKI 绑定")
        before = report_payload(report)
        bump_report(db, report, payload.version, status=status)
        audit(db, report, user, payload.action, before, report_payload(report))
    return report_payload(report)


def save_targets(db, report_id, user, payload):
    with write_transaction(db):
        report, members, own = load_report(db, report_id, user, lock=True)
        if report.status == "archived":
            raise HTTPException(409, "归档战报不可修改目标")
        admin = is_admin(user)
        if not admin and (report.status != "published" or beijing_now() > report.target_deadline):
            raise HTTPException(403, "目标填报已截止或战报尚未发布，请联系管理员")
        if admin and beijing_now() > report.target_deadline and not payload.reason:
            raise HTTPException(422, "截止后更正目标必须填写原因")
        by_id = {m.id: m for m in members}
        before, after = [], []
        for target in payload.targets:
            member = by_id.get(target.member_id)
            if member is None or (not admin and member.id != own.id):
                raise HTTPException(403, "只能修改本人在该战报中的目标")
            before.append({"member_id": member.id, "target_usd": money(member.target_usd) if member.target_usd else None})
            changed = db.execute(update(BattleReportMember).where(
                BattleReportMember.id == member.id, BattleReportMember.version == target.version)
                .values(target_usd=target.target_usd, version=target.version + 1, target_updated_at=beijing_now())
                .execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                raise HTTPException(409, "目标已被他人修改，请重新载入后填写")
            after.append({"member_id": member.id, "target_usd": money(target.target_usd)})
        audit(db, report, user, "targets", before, after, payload.reason)
    db.expire_all()
    return get_report(db, report_id, user)
