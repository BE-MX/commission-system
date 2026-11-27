"""Customer dedup: does this social account / email already belong to a customer, and whose?

Reads the OKKI mirror (``lsordertest``) only; the single write is the audit row in
``commission_db``.  Stored social values come in many shapes, so candidates are fetched
with a coarse SQL substring filter and then compared exactly on the normalised key.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

from sqlalchemy import bindparam, func, text
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now
from app.customer_dedup.models import CustomerDedupCheck
from app.customer_dedup.normalize import (
    EMAIL,
    PLATFORM_LABELS,
    PLATFORM_STORED,
    Lookup,
    key_for,
    phones_match,
)

logger = logging.getLogger("commission.customer_dedup")

PER_MINUTE_LIMIT = 30
PER_DAY_LIMIT = 600
MAX_CANDIDATES = 5000
MAX_CUSTOMERS = 10
_EMAIL_LIST_CAP = 200

STATUS_PRIVATE = "private"
STATUS_PUBLIC = "public"
STATUS_NOT_FOUND = "not_found"
STATUS_PENDING = "pending"
STATUS_INCONCLUSIVE = "inconclusive"


class RateLimited(Exception):
    pass


class AuditUnavailable(Exception):
    pass


class Inconclusive(Exception):
    """The lookup could not be answered reliably; never report it as "not found"."""


def _schema() -> str:
    return get_settings().BUSINESS_DB_NAME


_PHONE_DIGITS_SQL = "ccs.value"
for _sep in (" ", "-", "(", ")", ".", "+", "/"):
    _PHONE_DIGITS_SQL = f"REPLACE({_PHONE_DIGITS_SQL}, '{_sep}', '')"


def _like_escape(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _commit_or_fail_closed(db: Session, user_id: int) -> None:
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed: no audit row, no answer
        db.rollback()
        logger.warning("customer dedup audit write failed user=%s err=%s", user_id, exc)
        print(f"[customer_dedup] audit write failed user={user_id} err={exc}", flush=True)
        raise AuditUnavailable("查重服务暂不可用，请稍后再试") from exc


def reserve(db: Session, user_id: int, auth_channel: str, lookup: Lookup) -> CustomerDedupCheck:
    """Count and claim one quota slot atomically per user, before any lookup runs.

    The user-row lock serialises parallel requests from the same caller, so a burst
    cannot all read the same count; the pending audit row is committed before the
    lookup, so every answered query is already on record.

    The commit first ends any transaction opened by authentication reads: under
    InnoDB REPEATABLE READ an older snapshot would make the counts below miss rows
    committed by requests that held the lock before us.
    """
    db.commit()
    db.query(ArkUser.id).filter(ArkUser.id == user_id).with_for_update().first()
    now = beijing_now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    base = db.query(func.count(CustomerDedupCheck.id)).filter(CustomerDedupCheck.user_id == user_id)
    if base.filter(CustomerDedupCheck.created_at >= now - timedelta(minutes=1)).scalar() >= PER_MINUTE_LIMIT:
        db.rollback()
        raise RateLimited(f"查重太频繁：每人每分钟最多 {PER_MINUTE_LIMIT} 次，请稍后再试")
    if base.filter(CustomerDedupCheck.created_at >= day_start).scalar() >= PER_DAY_LIMIT:
        db.rollback()
        raise RateLimited(f"今天的查重次数已达上限（{PER_DAY_LIMIT} 次），明天再试或联系管理员")
    audit = CustomerDedupCheck(
        user_id=user_id,
        auth_channel=auth_channel,
        platform=lookup.platform,
        normalized_value=lookup.key[:500],
        result_status=STATUS_PENDING,
        matched_count=0,
        created_at=now,
    )
    db.add(audit)
    _commit_or_fail_closed(db, user_id)
    return audit


def _social_company_ids(db: Session, lookup: Lookup) -> set[str]:
    schema = _schema()
    sql = (
        f"SELECT ccs.value AS value, cc.company_id AS company_id "
        f"FROM `{schema}`.customer_contact_socials ccs "
        f"JOIN `{schema}`.customer_contacts cc ON cc.customer_id = ccs.customer_id "
        f"WHERE LOWER(ccs.platform) IN :platforms AND {_PHONE_DIGITS_SQL if lookup.is_phone else 'LOWER(ccs.value)'} "
        f"LIKE :like ESCAPE '!' LIMIT :limit"
    )
    # Phone numbers are stored with arbitrary punctuation ("+1 (202) 555-0123",
    # "+33 6 12 34 56 78"), so strip it in SQL and filter on the last seven digits.
    needle = lookup.needle[-7:] if lookup.is_phone else lookup.needle
    params = {
        "platforms": list(PLATFORM_STORED[lookup.platform]),
        "like": f"%{_like_escape(needle)}%",
        "limit": MAX_CANDIDATES,
    }
    statement = text(sql).bindparams(bindparam("platforms", expanding=True))
    rows = db.execute(statement, params).mappings().all()
    if len(rows) >= MAX_CANDIDATES:
        logger.warning("customer dedup candidate cap reached platform=%s", lookup.platform)
        print(f"[customer_dedup] candidate cap reached platform={lookup.platform}", flush=True)
        raise Inconclusive("这个账号太短、匹配范围过大，无法可靠查重，请提交完整账号或主页链接")

    wanted = set(lookup.match_keys)
    matched: set[str] = set()
    for row in rows:
        stored = key_for(lookup.platform, row["value"] or "")
        if not stored:
            continue
        same = (
            phones_match(lookup.key[4:], stored[4:], query_is_international=lookup.phone_intl)
            if lookup.is_phone and stored.startswith("tel:")
            else stored in wanted
        )
        if same and row["company_id"] is not None:
            matched.add(str(row["company_id"]))
    return matched


def _email_company_ids(db: Session, email: str) -> set[str]:
    schema = _schema()
    rows = db.execute(text(
        f"SELECT company_id FROM `{schema}`.customer_contacts WHERE email = :email "
        f"UNION SELECT company_id FROM `{schema}`.customer_info WHERE email = :email"
    ), {"email": email}).all()
    matched = {str(r[0]) for r in rows if r[0] is not None}
    # customer_info.email can hold a separated list or stray whitespace synced from OKKI.
    # (customer_contacts.email was verified clean on 2026-11-27: no lists, case or
    # whitespace drift across 163k rows, so it keeps the indexed equality lookup.)
    listed = db.execute(text(
        f"SELECT company_id, email FROM `{schema}`.customer_info "
        f"WHERE (email LIKE '%,%' OR email LIKE '%;%' OR email LIKE '% %' OR email <> TRIM(email)) "
        f"AND LOWER(email) LIKE :like ESCAPE '!' LIMIT :limit"
    ), {"like": f"%{_like_escape(email)}%", "limit": _EMAIL_LIST_CAP}).all()
    if len(listed) >= _EMAIL_LIST_CAP:
        raise Inconclusive("这个邮箱匹配范围过大，暂时无法可靠查重，请联系管理员")
    for company_id, value in listed:
        if email in {part.lower() for part in re.split(r"[,;\s]+", str(value or "")) if part}:
            matched.add(str(company_id))
    return matched


def _owner_ids(raw) -> list[str]:
    if raw is None:
        return []
    value = raw
    if isinstance(raw, (bytes, str)):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("customer dedup unparsable owner_user_ids=%r", raw)
            print(f"[customer_dedup] unparsable owner_user_ids={raw!r}", flush=True)
            return []
    if not isinstance(value, list):
        return []
    # Same rule as customer_image: OKKI user ids are numeric; skip null/bool/garbage.
    ids = [str(v).strip() for v in value if not isinstance(v, bool) and v is not None]
    return [v for v in ids if v.isdigit() and v != "0"]


def _customers(db: Session, company_ids: set[str], my_okki_id: str | None) -> list[dict]:
    if not company_ids:
        return []
    schema = _schema()
    rows = db.execute(
        text(
            f"SELECT company_id, company_name, owner_user_ids FROM `{schema}`.customer_info "
            f"WHERE company_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": sorted(company_ids)},
    ).mappings().all()

    owners_by_company = {str(r["company_id"]): _owner_ids(r["owner_user_ids"]) for r in rows}
    if len(owners_by_company) < len(company_ids):
        # Contact matched but its customer record is not mirrored yet: ownership unknown.
        missing = sorted(company_ids - set(owners_by_company))[:10]
        logger.warning("customer dedup contact without customer_info company_ids=%s", missing)
        print(f"[customer_dedup] contact without customer_info company_ids={missing}", flush=True)
        raise Inconclusive("该账号已在系统中，但客户资料正在同步，暂时无法判断归属，请稍后再查")
    all_owner_ids = sorted({o for ids in owners_by_company.values() for o in ids})
    names: dict[str, str] = {}
    if all_owner_ids:
        for user_id, full_name, nickname in db.execute(
            text(
                f"SELECT user_id, full_name, nickname FROM `{schema}`.user_basic WHERE user_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": all_owner_ids},
        ).all():
            name = (full_name or "").strip() or (nickname or "").strip()
            if name:
                names[str(user_id)] = name

    customers = []
    for r in rows:
        owner_ids = owners_by_company[str(r["company_id"])]
        customers.append({
            "company_name": (r["company_name"] or "").strip() or "（未命名客户）",
            "status": STATUS_PRIVATE if owner_ids else STATUS_PUBLIC,
            "owners": [names.get(o, f"OKKI 用户 {o}") for o in owner_ids],
            "is_mine": bool(my_okki_id) and my_okki_id in owner_ids,
        })
    # Private first, then by name, so the most relevant match leads.
    customers.sort(key=lambda c: (c["status"] != STATUS_PRIVATE, c["company_name"]))
    return customers


def _message(status: str, customers: list[dict]) -> str:
    if status == STATUS_NOT_FOUND:
        return "当前系统尚未收录此客户"
    if status == STATUS_PUBLIC:
        names = "、".join(c["company_name"] for c in customers[:3])
        return f"当前客户已进入公海，未绑定业务员：{names}"
    private = [c for c in customers if c["status"] == STATUS_PRIVATE]
    if all(c["is_mine"] for c in private) and all(len(c["owners"]) == 1 for c in private):
        return "该客户已在你自己的私海：" + "、".join(c["company_name"] for c in private[:3])
    parts = [f"{c['company_name']}（负责人：{'、'.join(c['owners'])}）" for c in private[:3]]
    return "该客户已进入同事私海：" + "；".join(parts)


def check(db: Session, lookup: Lookup, *, user_id: int, auth_channel: str, my_okki_id: str | None) -> dict:
    audit = reserve(db, user_id, auth_channel, lookup)
    try:
        company_ids = (
            _email_company_ids(db, lookup.key) if lookup.platform == EMAIL else _social_company_ids(db, lookup)
        )
        customers = _customers(db, company_ids, my_okki_id)
    except Inconclusive:
        audit.result_status = STATUS_INCONCLUSIVE
        _commit_or_fail_closed(db, user_id)
        raise
    if not customers:
        status = STATUS_NOT_FOUND
    elif any(c["status"] == STATUS_PRIVATE for c in customers):
        status = STATUS_PRIVATE
    else:
        status = STATUS_PUBLIC

    audit.result_status = status
    audit.matched_count = min(len(customers), 32767)
    _commit_or_fail_closed(db, user_id)

    return {
        "status": status,
        "message": _message(status, customers),
        "platform": lookup.platform,
        "platform_label": PLATFORM_LABELS[lookup.platform],
        "normalized_account": lookup.key,
        "matched_count": len(customers),
        "customers": customers[:MAX_CUSTOMERS],
    }
