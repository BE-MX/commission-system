"""钉钉机器人身份、命令与单人对话上下文。"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.project_radar.ingest import create_job, select_candidates, supplement_target, _clear_dialog
from app.project_radar.models import RadarDialog, RadarIngestJob, RadarSubscription, RadarTarget
from app.project_radar.service import list_subscriptions, update_subscription
from app.project_radar.urls import parse_input

_HELP = "发链接即收录，可一次多条；链接后写笔记，#词 变标签。\n「最近」查看最近收录；「搜 关键词」查找；「静默 2」「重点 2」「放弃 2」调整第2项；「深度看 2」为二期能力。"


def _permissions(user: ArkUser) -> tuple[set[str], set[str]]:
    roles = {role.name for role in user.roles}
    permissions = {permission.code for role in user.roles for permission in role.permissions}
    return roles, permissions


def _recent_text(rows) -> str:
    if not rows:
        return "你的雷达还没有项目，直接发链接即可收录。"
    labels = {"inbox": "待看", "trying": "试用中", "adopted": "已采用", "dropped": "已放弃"}
    return "\n".join(f"{index}. {row['title']}（{labels.get(row['status'], row['status'])}）" for index, row in enumerate(rows, 1))


def _card_subscription(db: Session, user_id: int, number: int):
    dialog = db.query(RadarDialog).filter(RadarDialog.user_id == user_id, RadarDialog.kind == "card").one_or_none()
    ids = (dialog.payload or {}).get("subscription_ids") if dialog and dialog.expires_at >= beijing_now() else None
    if not ids or number < 1 or number > len(ids):
        raise ValueError("找不到这个编号，请使用上一张卡片里的编号")
    subscription = db.query(RadarSubscription).filter_by(
        id=ids[number - 1], user_id=user_id, removed_at=None,
    ).one_or_none()
    if subscription is None:
        raise ValueError("该项目已不在你的雷达里")
    return subscription


def handle_inbound(db: Session, *, message_id: str, dingtalk_id: str, text: str) -> dict:
    if message_id:
        existing = db.query(RadarIngestJob).filter(RadarIngestJob.request_key == f"dingtalk:{message_id}").one_or_none()
        if existing:
            return {"reply": "这条消息已收到，无需重复发送", "job_id": existing.id}
    user = db.query(ArkUser).filter(
        ArkUser.dingtalk_id == dingtalk_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
    ).one_or_none()
    if user is None:
        return {"reply": "尚未匹配到你的方舟账号，请联系管理员在用户管理中同步钉钉 ID"}
    roles, permissions = _permissions(user)
    if "super_admin" not in roles and "project_radar:write" not in permissions:
        return {"reply": "你的账号没有项目雷达收录权限，请联系管理员分配 project_radar:write"}

    parsed = parse_input(text)
    if parsed["urls"]:
        had_context = db.query(RadarDialog).filter(RadarDialog.user_id == user.id).first() is not None
        _clear_dialog(db, user.id)
        job = create_job(
            db, user.id, text, channel="dingtalk", request_key=f"dingtalk:{message_id}",
            dingtalk_id=dingtalk_id,
        )
        db.commit()
        prefix = "上一个选择已取消。" if had_context else ""
        return {"reply": f"{prefix}收到 {len(parsed['urls'])} 个链接，正在读取…", "job_id": job.id}

    stripped = text.strip()
    dialog = db.query(RadarDialog).filter(RadarDialog.user_id == user.id).one_or_none()
    if dialog and dialog.kind in {"choose", "supplement"} and dialog.expires_at < beijing_now():
        kind = dialog.kind
        db.delete(dialog)
        db.commit()
        if re.fullmatch(r"[\d\s]+|全部", stripped):
            return {"reply": "上下文已失效，请重新发送链接"}
        dialog = None
    if dialog and dialog.kind == "choose" and re.fullmatch(r"[\d\s]+|全部", stripped):
        result = select_candidates(db, user.id, stripped)
        return {"reply": result["message"], "deliver": result["ok"]}
    if dialog and dialog.kind == "supplement":
        result = supplement_target(db, user.id, stripped)
        return {"reply": result["message"], "deliver": result["ok"]}

    if stripped == "帮助":
        return {"reply": _HELP}
    if stripped == "最近":
        result = list_subscriptions(db, user.id, page=1, page_size=5)
        return {"reply": _recent_text(result["items"])}
    if stripped.startswith("搜 "):
        result = list_subscriptions(db, user.id, keyword=stripped[2:].strip(), page=1, page_size=5)
        return {"reply": _recent_text(result["items"])}
    if re.fullmatch(r"深度看\s+\d+", stripped):
        return {"reply": "agent 深度看属于二期能力，本期请使用程序扫描和详情页重新分析"}

    command = re.fullmatch(r"(静默|重点|普通|已采用|放弃|试用中|待看)\s*(\d+)", stripped)
    if command:
        try:
            subscription = _card_subscription(db, user.id, int(command.group(2)))
            action = command.group(1)
            if action in {"放弃", "试用中", "待看"}:
                status = {"放弃": "dropped", "试用中": "trying", "待看": "inbox"}[action]
                update_subscription(db, user.id, subscription.id, {"status": status})
            else:
                level = {"静默": "silent", "重点": "key", "普通": "normal", "已采用": "adopted"}[action]
                update_subscription(db, user.id, subscription.id, {"watch_level": level})
            db.commit()
            target = db.get(RadarTarget, subscription.target_id)
            return {"reply": f"已更新「{target.title}」：{action}"}
        except ValueError as exc:
            return {"reply": str(exc)}
    return {"reply": "没有找到链接或可用指令。发送「帮助」查看用法。"}
