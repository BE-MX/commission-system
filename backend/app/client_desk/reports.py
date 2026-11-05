"""Daily report reservation and recipient-bound, single-use action redemption."""

import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from sqlalchemy import func

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now
from app.dingtalk.work_notify import get_work_notifier
from .calendar import is_workday
from .models import ClientDeskSuggestion as Row, ClientDeskState as State
from .pack import canonical, digest
from .queue import actor_id, active, today_rows, visible_suggestion
from . import sources
from .rules import R4


def _secret():
    key = get_settings().CLIENT_DESK_REPORT_SECRET
    if len(key.encode()) < 32:
        raise HTTPException(503, "早报签名未配置")
    return key.encode()


def ticket_for(uid, report_key, row_id, action, now):
    nonce = secrets.token_urlsafe(24)
    claims = {
        "u": str(uid),
        "r": report_key,
        "s": str(row_id),
        "a": action,
        "n": nonce,
        "expires": (now + timedelta(hours=12)).isoformat(),
        "v": 1,
    }
    blob = base64.urlsafe_b64encode(canonical(claims).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), blob.encode(), "sha256").hexdigest()
    return blob + "." + sig, hashlib.sha256(nonce.encode()).hexdigest()


def read_ticket(ticket, now):
    try:
        if len(ticket) > 1400:
            raise ValueError
        blob, sig = ticket.split(".")
        expected = hmac.new(_secret(), blob.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError
        claims = json.loads(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)))
        if (
            claims["v"] != 1
            or claims["expires"] <= now.isoformat()
            or claims["a"] not in {"detail", "wa"}
        ):
            raise ValueError
        return claims
    except (KeyError, ValueError, TypeError):
        raise HTTPException(410, "链接已失效，请登录我的私海") from None


def _phone(source, suggestion):
    targets = source.get("wa_targets") or []
    if len(targets) > 1:
        # Multiple chats must be disambiguated by a cited event in this run.
        cited = {
            c["key"] for c in suggestion.get("cites", []) if c["source"] == "whatsapp"
        }
        pairs = {
            (m["account_uid"], m["conversation_uid"])
            for m in source["messages"]
            if m["key"] in cited
        }
        targets = [
            t for t in targets if (t["account_uid"], t["conversation_uid"]) in pairs
        ]
    if len(targets) != 1:
        return None
    phone = re.sub(r"[\s()-]", "", targets[0].get("phone") or "").removeprefix("+")
    return phone if re.fullmatch(r"[1-9][0-9]{6,14}", phone) else None


def _line(value):
    # Strip markdown links/emphasis and control characters from customer-owned text.
    text = re.sub(r"https?://\S+|www\.\S+", "", str(value), flags=re.I)
    return re.sub(r"[\r\n\t*#<>\[\]()!|_\x00-\x1f]", " ", text).strip()[:80]


def _view(db, uid, row, now):
    from .source_policy import restricted_row

    if restricted_row(row):
        return {}, None
    source = sources.build_customer_sources(db, uid, row.company_id, for_ai=False)
    state = db.query(State).filter_by(user_id=uid, company_id=row.company_id).first()
    return source, visible_suggestion(db, row, source, state, now)


def report_rows(rows):
    by_company = {}
    from .source_policy import restricted_row

    for row in rows:
        if not restricted_row(row):
            by_company.setdefault(row.company_id, []).append(row)
    result = {}
    for cid, runs in by_company.items():
        if not any(r.run_seq == 0 for r in runs) or any(r.done_at for r in runs):
            continue
        quality = [r for r in runs if r.quality_feedback]
        if (
            quality
            and max(
                quality, key=lambda r: (r.feedback_at or r.created_at, r.run_seq)
            ).quality_feedback
            == "useless"
        ):
            continue
        result[cid] = max(runs, key=lambda r: r.run_seq)
    return result


async def send_report(db, user, now=None):
    uid = actor_id(user)
    now = now or beijing_now()
    cfg = active(db, uid)
    if uid not in cfg.CLIENT_DESK_NONWORKDAY_USER_IDS and not is_workday(
        now.date(), cfg.CLIENT_DESK_CALENDAR
    ):
        return
    origin = cfg.CLIENT_DESK_ORIGIN.rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        raise HTTPException(503, "早报入口未配置")
    _secret()
    key = f"{uid}:{now.date().isoformat()}"
    if db.query(Row.id).filter_by(report_key=key).first():
        return
    rows = today_rows(db, uid, now.date()).order_by(Row.run_seq, Row.id).all()
    ranking = []
    for row in report_rows(rows).values():
        try:
            source, view = _view(db, uid, row, now)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        if not view or not (set(view["rule_codes"]) - {R4}):
            continue
        priority = {"high": 0, "medium": 1, "low": 2}.get(view.get("priority"), 3)
        ranking.append(
            (priority, -view["rank_score"], row.company_id, row, source, view)
        )
    ranking.sort(key=lambda r: r[:3])
    if not ranking:
        return
    # Authorize and serialize the daily send intent after source reads, before transport.
    recipient = (
        db.query(ArkUser.dingtalk_id)
        .filter_by(id=uid, is_active=True, deleted_at=None)
        .with_for_update()
        .one()
    )
    if not recipient.dingtalk_id:
        return
    if db.query(Row.id).filter_by(report_key=key).with_for_update().first():
        return
    active(db, uid)
    anchor = db.query(Row).filter_by(id=rows[0].id).with_for_update().one()
    nonces, items, lines = {}, [], []
    for _, _, _, row, source, view in ranking[:10]:
        links = []
        actions = ["detail"]
        if view.get("draft_message") and _phone(source, view):
            actions.append("wa")
        for action in actions:
            ticket, hashed = ticket_for(uid, key, row.id, action, now)
            nonces[hashed] = None
            label = "查看档案" if action == "detail" else "在 WhatsApp 打开"
            links.append(f"[{label}]({origin}/client-desk/handoff#ticket={ticket})")
        items.append(
            {
                "id": str(row.id),
                "actions": actions,
                "dependencies": digest(
                    source.get("ai_source_dependencies", source["source_dependencies"])
                ),
                "view_hash": digest(view),
            }
        )
        lines.extend(
            [
                f'{len(items)}. **{_line(source["card"]["name"])}** {_line(view["reason"])}',
                " · ".join(links),
            ]
        )
    from .link_service import conversations

    waiting = conversations(db, uid, keyword="", page=1, page_size=1)
    pending = waiting.get("unreplied_count")
    if pending is not None:
        lines.append(f"另有 {int(pending)} 个未关联会话待回复。")
    title = f"我的私海 · 今天建议跟进 {len(items)} 位"
    if all(entry[5]["status"] != "succeeded" for entry in ranking[:10]):
        lines.insert(0, "本次按规则提醒，暂无可用 AI 草稿。")
    body = "\n\n".join(lines)
    anchor.report_key, anchor.report_recipient, anchor.report_items = (
        key,
        recipient.dingtalk_id,
        items,
    )
    anchor.report_nonces, anchor.report_hash = nonces, digest(body)
    anchor.send_status, anchor.reserved_at = "sending", now
    recipient_id, anchor_id = recipient.dingtalk_id, anchor.id
    db.commit()
    # The reservation is durable. Re-read source grants and personal feedback in
    # a new transaction. A changed frozen item cancels this report, never resends.
    active(db, uid)
    current_reports = report_rows(
        today_rows(db, uid, now.date()).populate_existing().all()
    )
    for item in items:
        current_row = (
            db.query(Row)
            .filter_by(id=int(item["id"]), user_id=uid)
            .populate_existing()
            .one()
        )
        current_source, current_view = _view(db, uid, current_row, beijing_now())
        if not current_view:
            db.query(Row).filter_by(id=anchor_id, send_status="sending").update(
                {Row.send_status: "cancelled"}
            )
            db.commit()
            return "cancelled"
        fingerprint = digest(
            current_source.get(
                "ai_source_dependencies", current_source["source_dependencies"]
            )
        )
        if (
            not current_view
            or current_reports.get(current_row.company_id) is not current_row
            or current_row.done_at
            or fingerprint != item["dependencies"]
            or digest(current_view) != item["view_hash"]
        ):
            db.query(Row).filter_by(id=anchor_id, send_status="sending").update(
                {Row.send_status: "cancelled"}
            )
            db.commit()
            return "cancelled"
    current_recipient = (
        db.query(ArkUser.dingtalk_id)
        .filter_by(id=uid, is_active=True, deleted_at=None)
        .scalar()
    )
    if current_recipient != recipient_id:
        db.query(Row).filter_by(id=anchor_id, send_status="sending").update(
            {Row.send_status: "cancelled"}
        )
        db.commit()
        return "cancelled"
    db.commit()
    status, receipt = await get_work_notifier().send_with_receipt(
        recipient_id, title, body
    )
    anchor = (
        db.query(Row)
        .filter_by(id=anchor_id, send_status="sending")
        .with_for_update()
        .one()
    )
    anchor.send_status, anchor.provider_receipt = status, receipt
    if status == "accepted":
        anchor.accepted_at = beijing_now()
        db.query(Row).filter(
            Row.id.in_([int(i["id"]) for i in items]), Row.shown_at.is_(None)
        ).update(
            {Row.shown_at: anchor.accepted_at, Row.shown_channel: "report"},
            synchronize_session=False,
        )
    db.commit()
    return status


def redeem(db, user, ticket, now=None):
    uid = actor_id(user)
    now = now or beijing_now()
    active(db, uid)
    claims = read_ticket(ticket, now)
    if claims["u"] != str(uid):
        raise HTTPException(403, "仅限早报收件人")
    row = db.query(Row).filter_by(id=int(claims["s"]), user_id=uid).first()
    if not row:
        raise HTTPException(410, "入口已失效")
    source, view = _view(db, uid, row, now)
    if not view:
        raise HTTPException(410, "来源策略或授权已变更")
    anchor = (
        db.query(Row)
        .filter_by(user_id=uid, report_key=claims["r"])
        .populate_existing()
        .with_for_update()
        .first()
    )
    recipient = (
        db.query(ArkUser.dingtalk_id)
        .filter_by(id=uid, is_active=True, deleted_at=None)
        .first()
    )
    if not anchor or not recipient or recipient.dingtalk_id != anchor.report_recipient:
        raise HTTPException(403, "收件人映射已变更")
    if anchor.send_status not in {"accepted", "unknown", "sending"}:
        raise HTTPException(410, "入口已失效")
    item = next(
        (
            i
            for i in anchor.report_items
            if i["id"] == str(row.id) and claims["a"] in i["actions"]
        ),
        None,
    )
    hashed = hashlib.sha256(claims["n"].encode()).hexdigest()
    if (
        not item
        or hashed not in anchor.report_nonces
        or anchor.report_nonces[hashed] is not None
    ):
        raise HTTPException(410, "链接已使用或已失效")
    deps = source.get("ai_source_dependencies", source["source_dependencies"])
    if item["dependencies"] != digest(deps):
        raise HTTPException(410, "客户资料已变更，请重新打开档案")
    url = f"/client-desk?company_id={row.company_id}"
    if claims["a"] == "wa":
        phone = _phone(source, view or {})
        if not view or not view.get("draft_message") or not phone:
            raise HTTPException(410, "草稿或会话已变更")
        url = f'https://wa.me/{phone}?text={quote(view["draft_message"],safe="")}'
    anchor.report_nonces = anchor.report_nonces | {hashed: now.isoformat()}
    anchor.opened_at = anchor.opened_at or now
    db.commit()
    return {"url": url}
