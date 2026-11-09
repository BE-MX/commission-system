"""Narrow customer contact updates and explicit deal verification."""
import logging
from unicodedata import normalize

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.domestic.models import DomesticCustomer as Customer
from app.domestic_followup import collaboration_access as access, visibility
from app.domestic_followup.collaboration_models import (
    FollowupCollaborationEvent,
    FollowupCustomerProfile as Profile,
)
from app.domestic_followup.models import DomesticFollowupConfig

logger = logging.getLogger("commission")


def normalize_phone(value: str | None) -> str:
    cleaned = "".join(char for char in normalize("NFKC", value or "") if not char.isspace() and char not in "-()")
    domestic = cleaned[3:]
    if (cleaned.startswith("+86") and len(domestic) == 11 and domestic.startswith("1")
            and domestic.isascii() and domestic.isdecimal()):
        return domestic
    return cleaned


def normalize_wechat(value: str | None) -> str:
    return normalize("NFKC", value or "").strip().casefold()


def _has_contact_access(db, user, customer):
    return visibility.in_customer_scope(db, user, customer.id) or access.has_history_access(db, user, customer)


def lock_contact_duplicate_check(db: Session, phone: str | None, wechat: str | None) -> None:
    """Serialize followup contact writes before the transaction's first consistent read."""
    if not normalize_phone(phone) and not normalize_wechat(wechat):
        return
    table = DomesticFollowupConfig.__table__
    values = {"key": "internal_contact_duplicate_mutex", "value": None}
    if db.get_bind().dialect.name == "sqlite":
        statement = sqlite_insert(table).values(**values).on_conflict_do_nothing(index_elements=[table.c.key])
    else:
        insert = mysql_insert(table).values(**values)
        statement = insert.on_duplicate_key_update(key=table.c.key)
    # The atomic insert/update holds the row lock through commit/rollback, including first use.
    db.execute(statement)


def check_contact_duplicates(
    db: Session, user: dict, phone: str | None, wechat: str | None, exclude_customer_id: int | None = None,
    duplicate_confirmed: bool = False,
) -> dict:
    """Check normalized identifiers without revealing contact details or hidden matching customers."""
    target_phone, target_wechat = normalize_phone(phone), normalize_wechat(wechat)
    if not target_phone and not target_wechat:
        return {"matches": [], "requires_review": False, "blocking": False}
    candidate_ids = set()
    if target_phone:
        for customer_id, value in db.execute(select(Customer.id, Customer.phone).where(Customer.phone.is_not(None))):
            if normalize_phone(value) == target_phone:
                candidate_ids.add(customer_id)
    if target_wechat:
        for customer_id, value in db.execute(select(Profile.customer_id, Profile.wechat).where(Profile.wechat.is_not(None))):
            if normalize_wechat(value) == target_wechat:
                candidate_ids.add(customer_id)
    candidate_ids.discard(exclude_customer_id)
    if not candidate_ids:
        return {"matches": [], "requires_review": False, "blocking": False}
    candidates = db.execute(select(Customer.id, Customer.shop_name, Customer.province, Customer.city)
                            .where(Customer.id.in_(candidate_ids)).order_by(Customer.id)).all()
    matches = []
    for row in candidates:
        if not _has_contact_access(db, user, row):
            return {"matches": [], "requires_review": True, "blocking": True}
        matches.append({"id": row.id, "shop_name": row.shop_name, "province": row.province, "city": row.city})
    return {"matches": matches, "requires_review": bool(matches), "blocking": bool(matches) and not duplicate_confirmed}


def _customer_or_raise(customer):
    if customer is None:
        raise LookupError("客户不存在")
    return customer


def _commit(db):
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("customer overview update failed: %s", type(exc).__name__)
        print(f"[domestic_followup] customer overview update failed: {type(exc).__name__}", flush=True)
        raise


def update_contact(db: Session, user: dict, customer_id: int, values: dict, duplicate_confirmed: bool) -> dict:
    values = {key: (value.strip() or None) if value is not None else None for key, value in values.items()}
    lock_contact_duplicate_check(db, values.get("phone"), values.get("wechat"))
    customer = _customer_or_raise(access.lock_customer(db, customer_id))
    if not _has_contact_access(db, user, customer) and not access.has_summary_access(db, user, customer):
        raise LookupError("客户不存在")
    coordinator_edit = (customer.status == 1 and access.can_coordinate(db, user, customer, lock=True)
                        and access.eligible_actor(db, user, customer, lock=True))
    if not coordinator_edit and not visibility.can_write_customer(db, user, customer, lock=True):
        raise PermissionError("无权补充该客户联系方式")
    review = check_contact_duplicates(db, user, values.get("phone"), values.get("wechat"),
                                      customer_id, duplicate_confirmed)
    if review["blocking"]:
        db.rollback()
        return {"updated": False, **review}
    profile = db.get(Profile, customer_id, populate_existing=True, with_for_update=True)
    if "wechat" in values:
        if profile is None:
            profile = Profile(customer_id=customer_id)
            db.add(profile)
        profile.wechat = values.pop("wechat")
    for key, value in values.items():
        setattr(customer, key, value)
    result = {"updated": True, "id": customer.id,
              **{key: getattr(customer, key) for key in ("contact", "phone", "province", "city")},
              "wechat": profile.wechat if profile else None}
    _commit(db)
    return result


def verify_deal(db: Session, user: dict, customer_id: int, status: str, evidence: str) -> dict:
    customer = _customer_or_raise(access.lock_customer(db, customer_id))
    if not access.can_coordinate(db, user, customer, lock=True) or not access.has_summary_access(db, user, customer):
        raise PermissionError("无权核实该客户成交")
    if not evidence.strip():
        raise ValueError("请填写核实依据")
    profile = db.get(Profile, customer_id, populate_existing=True, with_for_update=True)
    if profile is None:
        profile = Profile(customer_id=customer_id)
        db.add(profile)
    actor = access.user_id(user)
    now = beijing_now()
    profile.deal_status = status
    profile.deal_evidence = evidence.strip()
    profile.deal_verified_by_user_id = actor
    profile.deal_verified_at = now
    responsibility = access.responsibility_for(db, customer_id)
    db.add(FollowupCollaborationEvent(
        customer_id=customer_id, actor_user_id=actor, action="deal_verified",
        responsibility_version=responsibility.version if responsibility else 0,
        details={"deal_status": status, "evidence": profile.deal_evidence}, created_at=now,
    ))
    _commit(db)
    return {"id": customer_id, "verified_status": status, "verified_by_user_id": actor, "verified_at": now.isoformat()}
