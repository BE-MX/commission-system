"""Permission-scoped customer overview. Aggregate from the customer grain."""
from datetime import date

from sqlalchemy import and_, case, false, func, literal, or_, select, true
from sqlalchemy.orm import Session, aliased

from app.auth.models import ArkUser
from app.core.time import beijing_today
from app.domestic import constants as order_constants
from app.domestic.models import DomesticCustomer as Customer, DomesticCustomerLedger as Ledger, DomesticOrder as Order
from app.domestic_decision.models import DecisionConfig, DecisionEvent
from app.domestic_followup import collaboration_access, visibility
from app.domestic_followup.collaboration_models import (
    FollowupCollaborator as Collaborator,
    FollowupCustomerProfile as Profile,
    FollowupHandoff as Handoff,
    FollowupResponsibility as Responsibility,
    FollowupScope,
)
from app.domestic_followup.constants import PROSPECT_LIFECYCLE
from app.domestic_followup.models import DomesticFollowup as Followup
from app.system.models import SysDict

MISSING_REGION = "__missing__"


def _has_permission(user, code):
    return "super_admin" in (user.get("roles") or []) or code in (user.get("permissions") or [])


def _access(db, user, scope):
    user_id = visibility.uid(user)
    legacy_member = Customer.id.in_(visibility.scoped_customer_ids(user_id))
    legacy_full = true() if visibility.can_read_all(user) else legacy_member
    legacy_writer = or_(literal(visibility.is_super_admin(user)), Customer.owner_user_id.is_(None), legacy_member)
    live_read = visibility.holds(db, user_id, collaboration_access.READ)
    live_write = live_read and visibility.holds(db, user_id, collaboration_access.WRITE)
    scoped = Customer.id.in_(collaboration_access.scoped_ids(user_id)) if live_read else false()
    managed = Customer.id.in_(collaboration_access.managed_customer_ids())
    owner = Responsibility.owner_user_id == user_id
    member = select(Collaborator.customer_id).where(
        Collaborator.customer_id == Customer.id, Collaborator.user_id == user_id,
    ).exists()
    incoming = Customer.id.in_(collaboration_access.incoming_ids(user_id))
    coordinated = scoped if collaboration_access.can_run_coordination(db, user) else false()
    direct = and_(scoped, or_(owner, member))
    full = or_(legacy_full, direct, coordinated)
    admitted = or_(full, scoped)
    scopes = {
        "mine": or_(and_(scoped, owner), and_(~managed, Customer.owner_user_id == user_id)),
        "authorized": admitted,
        "collaborating": and_(scoped, member),
        "available": and_(scoped, Responsibility.status == "open"),
        "incoming": and_(scoped, incoming),
    }
    can_write = literal(_has_permission(user, "domestic_followup:write"))
    qualified_owner = and_(
        Responsibility.owner_user_id.in_(visibility.holder_ids(collaboration_access.READ)),
        Responsibility.owner_user_id.in_(visibility.holder_ids(collaboration_access.WRITE)),
        select(FollowupScope.id).where(FollowupScope.user_id == Responsibility.owner_user_id,
                                       collaboration_access._scope_matches()).correlate(Customer, Responsibility).exists(),
    )
    writable = and_(
        or_(and_(managed, literal(live_write),
                 Responsibility.status.in_(("following", "handoff")),
                 or_(and_(scoped, owner), and_(qualified_owner, or_(and_(scoped, member), coordinated)))),
            and_(~managed, legacy_writer)),
        can_write,
    )
    editable = or_(writable, and_(coordinated, literal(live_write), can_write))
    claimable = and_(scopes["available"], literal(live_write), can_write)
    return and_(admitted, scopes[scope]), full, writable, managed, and_(scoped, incoming), coordinated, claimable, editable


def _candidate_customers(db, user, scope, keyword, customer_id=None):
    allowed, full, writable, managed, incoming, coordinated, claimable, editable = _access(db, user, scope)
    assignee_id = case((managed, Responsibility.owner_user_id), else_=Customer.owner_user_id)
    collaboration_status = case(
        (managed, func.coalesce(Responsibility.status, "unassigned")),
        (Customer.owner_user_id.is_not(None), "following"),
        else_="unassigned",
    )
    recipient = (select(Handoff.recipient_user_id).where(Handoff.customer_id == Customer.id, Handoff.status == "pending")
                 .order_by(Handoff.id.desc()).limit(1).correlate(Customer).scalar_subquery())
    query = (
        select(
            Customer.id, Customer.shop_name, Customer.custom_code,
            func.nullif(func.trim(Customer.province), "").label("province"),
            func.nullif(func.trim(Customer.city), "").label("city"),
            case((full, Customer.contact)).label("contact"),
            case((full, Customer.phone)).label("phone"),
            case((full, Profile.wechat)).label("wechat"),
            Customer.lifecycle_status, Customer.owner_user_id, assignee_id.label("assignee_user_id"),
            collaboration_status.label("collaboration_status"), Responsibility.stage,
            Responsibility.version.label("responsibility_version"),
            Responsibility.next_plan_date, managed.label("managed"),
            full.label("can_view_timeline"), writable.label("can_record"), incoming.label("incoming"),
            full.label("can_view_contacts"), editable.label("can_edit_contact"),
            coordinated.label("can_verify_deal"), claimable.label("can_claim"),
            case((managed, recipient)).label("handoff_recipient_user_id"),
            Customer.first_order_date, Customer.last_order_date, Customer.total_order_count,
            Customer.total_sales_amount, Profile.deal_status.label("verified_status"),
            Profile.deal_verified_at, Profile.deal_verified_by_user_id, Profile.deal_evidence,
        )
        .select_from(Customer)
        .outerjoin(Responsibility, Responsibility.customer_id == Customer.id)
        .outerjoin(Profile, Profile.customer_id == Customer.id)
        .where(Customer.status == 1, allowed)
    )
    if customer_id is not None:
        query = query.where(Customer.id == customer_id)
    if keyword.strip():
        like = visibility._like(keyword.strip())
        public_match = or_(*(col.like(like, escape="\\") for col in (Customer.shop_name, Customer.custom_code)))
        contact_match = or_(*(col.like(like, escape="\\") for col in (Customer.contact, Customer.phone, Profile.wechat)))
        query = query.where(or_(public_match, and_(full, contact_match)))
    return query.cte("overview_candidates")


def _order_evidence(db, candidates):
    # Order types are configurable; reuse the decision module's reviewed exclusions.
    configured = db.scalar(select(DecisionConfig.value).where(DecisionConfig.key == "aftersales_order_types"))
    aftersales = {"aftersales", "after_sales", "售后", "售后单"}
    if isinstance(configured, list):
        aftersales.update(value for value in configured if isinstance(value, str) and value)
    aftersales_dict = select(SysDict.code).where(
        SysDict.type == order_constants.ORDER_TYPE_DICT,
        func.trim(SysDict.label).in_(("售后", "售后单", "售后订单", "纯售后")),
    )
    # The normal refund path does not change a completed order's status. A whole-order termination can;
    # preserve completion only when the existing immutable order audit and refund ledger prove both.
    before, after = DecisionEvent.before, DecisionEvent.after
    completion_audit = select(DecisionEvent.id).where(
        DecisionEvent.order_id == Order.id, DecisionEvent.customer_id == Order.customer_id,
        DecisionEvent.entity_type == "order", DecisionEvent.event_type == "changed",
        before["customer_id"].as_integer() == Order.customer_id,
        before["status"].as_integer().in_((order_constants.ORDER_DONE, order_constants.ORDER_SHIPPED)),
        after["status"].as_integer() == order_constants.ORDER_TERMINATED,
    ).exists()
    termination_refund = select(Ledger.id).where(
        Ledger.order_id == Order.id, Ledger.customer_id == Order.customer_id,
        Ledger.transaction_type == "order_refund", Ledger.amount > 0, Ledger.remark.like("% 终止退款：%"),
    ).exists()
    refunded_after_completion = and_(Order.status == order_constants.ORDER_TERMINATED, completion_audit, termination_refund)
    return (
        select(
            Order.customer_id, func.min(Order.order_date).label("system_date"),
            func.max(case((Order.order_type == "sample", 0), else_=1)).label("has_regular"),
        )
        .join(candidates, candidates.c.id == Order.customer_id)
        .where(
            Order.order_kind == "business", Order.deleted_flag == 0, Order.total_amount > 0,
            or_(Order.status.in_((order_constants.ORDER_PRODUCING, order_constants.ORDER_DONE, order_constants.ORDER_SHIPPED)),
                refunded_after_completion),
            or_(Order.order_type.is_(None), and_(Order.order_type.not_in(aftersales), Order.order_type.not_in(aftersales_dict))),
        )
        .group_by(Order.customer_id)
        .cte("overview_orders")
    )


def _latest_followup(candidates):
    # Order by business occurrence, so late backfills and edits to old rows stay in their historical position.
    ranked = (
        select(
            Followup.customer_id, Followup.followup_date, Followup.author_user_id, Followup.next_date,
            case((candidates.c.can_view_timeline, Followup.summary), else_=Followup.shared_summary).label("summary"),
            case((candidates.c.can_view_timeline, Followup.obstacles)).label("obstacles"),
            func.row_number().over(
                partition_by=Followup.customer_id, order_by=(Followup.followup_date.desc(), Followup.id.desc()),
            ).label("position"),
        )
        .join(candidates, candidates.c.id == Followup.customer_id)
        .where(Followup.status == "confirmed")
        .cte("overview_followups")
    )
    return select(ranked).where(ranked.c.position == 1).cte("overview_latest")


def _deal_evidence(candidates, orders, today):
    c, o = candidates.c, orders.c
    valid_first = c.first_order_date <= today
    valid_last = and_(c.last_order_date >= c.first_order_date, c.last_order_date <= today)
    archive_conflict = or_(
        c.first_order_date > today,
        and_(c.last_order_date.is_not(None), or_(c.last_order_date > today, c.last_order_date < c.first_order_date)),
        c.total_order_count <= 0, c.total_sales_amount < 0,
    )
    archive = and_(
        valid_first, ~func.coalesce(archive_conflict, false()),
        or_(valid_last, c.total_order_count > 0, c.total_sales_amount > 0),
    )
    verified = and_(
        c.deal_verified_at.is_not(None), c.deal_verified_by_user_id.is_not(None),
        func.length(func.trim(c.deal_evidence)) > 0, c.verified_status.in_(("won", "unwon", "unknown")),
    )
    has_system = o.system_date.is_not(None)
    contradictory_archive = and_(archive, verified, c.verified_status != "won")
    status = case((has_system, "won"), (contradictory_archive, "unknown"), (verified, c.verified_status),
                  (archive, "won"), else_="unknown")
    source = case(
        (has_system, "system_order"), (contradictory_archive, "unverified"),
        (verified, "manual_verification"), (archive, "historical_archive"),
        else_="unverified",
    )
    date_from_archive = and_(archive, or_(~verified, c.verified_status == "won"))
    first_date = case(
        (and_(date_from_archive, or_(~has_system, c.first_order_date < o.system_date)), c.first_order_date),
        else_=o.system_date,
    )
    sample_only = and_(
        has_system, o.has_regular == 0, ~func.coalesce(date_from_archive, false()),
        ~func.coalesce(and_(verified, c.verified_status == "won"), false()),
    )
    conflict = or_(
        and_(status == "won", c.lifecycle_status == PROSPECT_LIFECYCLE),
        and_(has_system, verified, c.verified_status != "won"),
        contradictory_archive,
        and_(c.first_order_date.is_not(None), archive_conflict),
    )
    return status, source, first_date, sample_only, func.coalesce(conflict, false())


def _overview_rows(db, candidates, today):
    orders = _order_evidence(db, candidates)
    latest = _latest_followup(candidates)
    c, last = candidates.c, latest.c
    owner, assignee, author, recipient = (aliased(ArkUser, name=role)
                                          for role in ("owner", "assignee", "author", "recipient"))
    deal_status, source, first_date, sample_only, conflict = _deal_evidence(candidates, orders, today)
    return (
        select(
            c.id, c.shop_name, c.custom_code, c.province, c.city, c.contact, c.phone, c.wechat,
            c.lifecycle_status, c.assignee_user_id, c.collaboration_status, c.stage, c.responsibility_version,
            c.can_view_timeline, c.can_record, c.incoming,
            c.can_view_contacts, c.can_edit_contact, c.can_verify_deal, c.can_claim,
            owner.real_name.label("owner_name"), assignee.real_name.label("assignee_name"),
            recipient.real_name.label("handoff_recipient_name"),
            last.followup_date.label("last_followup_date"), author.real_name.label("last_followup_author"),
            last.summary.label("last_followup_summary"),
            last.obstacles,
            case((c.managed, c.next_plan_date), else_=last.next_date).label("next_date"),
            deal_status.label("deal_status"), source.label("deal_source"), first_date.label("first_deal_date"),
            sample_only.label("sample_only"), conflict.label("deal_conflict"),
        )
        .select_from(candidates)
        .outerjoin(orders, orders.c.customer_id == c.id)
        .outerjoin(latest, last.customer_id == c.id)
        .outerjoin(owner, owner.id == c.owner_user_id)
        .outerjoin(assignee, assignee.id == c.assignee_user_id)
        .outerjoin(author, author.id == last.author_user_id)
        .outerjoin(recipient, recipient.id == c.handoff_recipient_user_id)
        .cte("overview_rows")
    )


def _region_filter(columns, province, city):
    conditions = []
    if province == MISSING_REGION:
        conditions.append(or_(columns.province.is_(None), columns.city.is_(None)))
    elif province is not None:
        conditions.append(columns.province == province)
    if city == MISSING_REGION:
        conditions.append(columns.city.is_(None))
    elif city is not None:
        conditions.append(columns.city == city)
    return conditions


def _regions(db, candidates):
    c = candidates.c
    values = db.execute(select(c.province, c.city).distinct().order_by(c.province, c.city))
    groups = {}
    for province, city in values:
        groups.setdefault(province, []).append(city)
    return [{"province": province, "cities": cities} for province, cities in groups.items()]


def _assignees(db, candidates):
    ids = select(candidates.c.assignee_user_id).distinct()
    rows = db.execute(select(ArkUser.id, ArkUser.real_name).where(ArkUser.id.in_(ids))
                      .order_by(ArkUser.real_name, ArkUser.id))
    return [{"id": user_id, "name": name} for user_id, name in rows]


def _serialize_row(row):
    data = dict(row)
    for key in ("first_deal_date", "last_followup_date", "next_date"):
        if data[key] is not None:
            data[key] = data[key].isoformat()
    for key in ("can_view_timeline", "can_record", "incoming", "sample_only", "deal_conflict", "can_view_contacts",
                "can_edit_contact", "can_verify_deal", "can_claim"):
        data[key] = bool(data[key])
    return data


def get_customer_overview(db: Session, user: dict, customer_id: int) -> dict | None:
    candidates = _candidate_customers(db, user, "authorized", "", customer_id=customer_id)
    overview = _overview_rows(db, candidates, beijing_today())
    row = db.execute(select(overview)).mappings().one_or_none()
    return _serialize_row(row) if row is not None else None


def list_customer_overview(
    db: Session, user: dict, *, keyword: str = "", province: str | None = None,
    city: str | None = None, deal_status: str = "all", scope: str | None = None,
    page: int = 1, page_size: int = 20, sort_field: str = "last_followup_date", sort_order: str = "desc",
    assignee_user_id: int | None = None, collaboration_status: str | None = None,
    date_from: date | None = None, date_to: date | None = None, never_contacted: bool = False,
    overdue: bool = False, lifecycle_status: str | None = None,
):
    scope = scope or ("authorized" if visibility.can_read_all(user) or
                      _has_permission(user, collaboration_access.COORDINATE) else "mine")
    today = beijing_today()
    candidates = _candidate_customers(db, user, scope, keyword)
    overview = _overview_rows(db, candidates, today)
    o = overview.c
    conditions = _region_filter(o, province, city)
    for value, column in (
        (assignee_user_id, o.assignee_user_id), (collaboration_status, o.collaboration_status),
        (lifecycle_status, o.lifecycle_status),
    ):
        if value is not None:
            conditions.append(column == value)
    if date_from:
        conditions.append(o.last_followup_date >= date_from)
    if date_to:
        conditions.append(o.last_followup_date <= date_to)
    if never_contacted:
        conditions.append(o.last_followup_date.is_(None))
    if overdue:
        conditions.append(o.next_date < today)

    counts = dict(db.execute(
        select(
            func.count().label("total"),
            *(func.count(case((o.deal_status == key, 1))).label(key) for key in ("won", "unwon", "unknown")),
            func.count(case((o.sample_only, 1))).label("sample_only"),
        ).select_from(overview).where(*conditions)
    ).mappings().one())
    if deal_status == "sample_only":
        conditions.append(o.sample_only)
    elif deal_status != "all":
        conditions.append(o.deal_status == deal_status)
    sort_column = o[sort_field]
    page_query = (
        select(overview).where(*conditions)
        .order_by(sort_column.is_(None), sort_column.asc() if sort_order == "asc" else sort_column.desc(), o.id.asc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [_serialize_row(row) for row in db.execute(page_query).mappings()],
        "total": counts["total"] if deal_status == "all" else counts[deal_status],
        "page": page, "page_size": page_size, "counts": counts,
        "regions": _regions(db, candidates), "assignees": _assignees(db, candidates),
    }
