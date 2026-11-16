"""公海释放口径（唯一来源）：订单钟 3 个自然月 + 跟进钟 1 个自然月，先到期者释放。

释放任务、客户流失态势图、看板都只调这里，避免「图上还剩 5 天、今天却被释放」。
规格：docs/requirements/2026-11-13-followup-churn-ship/README.md 第二节（Q1~Q6）。
"""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domestic import constants as C
from app.domestic.models import DomesticCustomer, DomesticOrder

ORDER_MONTHS = 3
FOLLOW_MONTHS = 1
LAUNCH_CONFIG_KEY = "public_sea_follow_launch_date"
REASON_ORDER = "order"
REASON_FOLLOW = "follow"


def months_ago(today: date, months: int) -> date:
    """往前推 N 个自然月；目标月没有这一天时取目标月最后一天（5-31 往前 1 个月 = 4-30）。

    2026-11-13 前的旧实现回退到了目标月的上一个月底（5-31 → 3-31），让判定在月末倒退一天。
    """
    month_index = today.month - 1 - months
    year = today.year + month_index // 12
    month = month_index % 12 + 1
    try:
        return today.replace(year=year, month=month)
    except ValueError:
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        return date(next_year, next_month, 1) - timedelta(days=1)


def release_day(effective: date, months: int) -> date:
    """释放日 = 最早满足 months_ago(D, months) >= effective 的 D。

    与释放判定 `effective <= months_ago(today, months)` 严格等价（months_ago 单调不减），
    所以图上的倒计时与任务逐日一致，月末也不会差一天。
    """
    day = effective + timedelta(days=27 * months)
    while months_ago(day, months) < effective:
        day += timedelta(days=1)
    return day


@dataclass(frozen=True)
class Clock:
    customer_id: int
    order_due: date | None          # 订单钟释放日；None = 没有任何基准日，永不按订单钟释放
    follow_due: date | None         # 跟进钟释放日（按当前是否生效计算）；None = 规则未生效
    follow_preview_due: date        # 不含生效日锚点的跟进钟，供生效前预演
    follow_enforced: bool
    last_followup_date: date | None
    last_order_date: date | None

    @property
    def due(self) -> date | None:
        dues = [d for d in (self.order_due, self.follow_due) if d is not None]
        return min(dues) if dues else None

    @property
    def reason(self) -> str | None:
        """先到期的钟；同一天到期按订单钟算（保留 11-09 D07 的跟进责任）。"""
        if self.follow_due is not None and (self.order_due is None or self.follow_due < self.order_due):
            return REASON_FOLLOW
        return REASON_ORDER if self.order_due is not None else None

    def display(self) -> tuple[date | None, str | None]:
        """图上展示的释放日与原因：生效前用预演跟进钟。"""
        follow = self.follow_due if self.follow_enforced else self.follow_preview_due
        if self.order_due is None or follow < self.order_due:
            return follow, REASON_FOLLOW
        return self.order_due, REASON_ORDER


def launch_date(db: Session) -> date | None:
    from app.domestic_followup.config_service import get_config  # 延迟导入：followup 依赖 domestic

    raw = get_config(db).get(LAUNCH_CONFIG_KEY)
    return date.fromisoformat(raw) if raw else None


def _shared(query, locking: bool):
    """locking=True 时用共享锁读：读到最新提交的版本，而不是本事务第一次读时的快照。"""
    return query.with_for_update(read=True) if locking else query


def _latest_orders(db: Session, ids: list[int], locking: bool = False) -> dict[int, date]:
    query = (db.query(DomesticOrder.customer_id, func.max(DomesticOrder.order_date))
             .filter(DomesticOrder.customer_id.in_(ids), DomesticOrder.deleted_flag == 0,
                     DomesticOrder.status.notin_(C.ORDER_INACTIVE_STATUSES),
                     DomesticOrder.order_kind == "business")
             .group_by(DomesticOrder.customer_id))
    return dict(_shared(query, locking).all())


def compute_clocks(db: Session, customers: list[DomesticCustomer], today: date,
                   *, launch: date | None = None, launch_known: bool = False, locking: bool = False) -> dict[int, Clock]:
    """批量计算两个钟。launch 不传时从跟进设置读取。"""
    from app.domestic_followup.collaboration_models import FollowupResponsibility
    from app.domestic_followup.models import DomesticFollowup

    ids = [customer.id for customer in customers]
    if not ids:
        return {}
    if not launch_known:
        launch = launch_date(db)
    enforced = launch is not None and today >= launch
    orders = _latest_orders(db, ids, locking)
    followups = dict(_shared(
        db.query(DomesticFollowup.customer_id, func.max(DomesticFollowup.followup_date))
        .filter(DomesticFollowup.customer_id.in_(ids), DomesticFollowup.status == "confirmed",
                DomesticFollowup.followup_date <= today)
        .group_by(DomesticFollowup.customer_id), locking).all())
    paused = dict(
        db.query(FollowupResponsibility.customer_id, FollowupResponsibility.next_plan_date)
        .filter(FollowupResponsibility.customer_id.in_(ids), FollowupResponsibility.stage == "paused",
                FollowupResponsibility.next_plan_date.isnot(None),
                FollowupResponsibility.next_plan_date >= today)  # 约定日当天也算暂缓
        .all()
    )
    result = {}
    for customer in customers:
        created = customer.created_at.date() if customer.created_at else None
        claimed = customer.owner_claimed_at.date() if customer.owner_claimed_at else None
        order_dates = [d for d in (orders.get(customer.id), customer.last_order_date,
                                   customer.first_contact_date, created) if d is not None]
        # 订单钟不认认领日（2026-11-13 亮哥定）：否则放掉再认领回来就能无限续期
        order_due = release_day(min(max(order_dates), today), ORDER_MONTHS) if order_dates else None
        # 跟进钟：已确认跟进、已生效正式订单（下单也算跟进）、认领日、建档日
        # 没有任何日期（只有 created_at 为空的历史数据）时从今天算，等于不按跟进钟释放
        follow_dates = [d for d in (followups.get(customer.id), orders.get(customer.id), claimed, created)
                        if d is not None] or [today]
        raw = min(max(follow_dates), today)
        # 预演：已配置生效日就从生效日起算（与将来真实释放一致）；完全没配置时按历史数据预演
        preview_due = release_day(max(raw, launch) if launch else raw, FOLLOW_MONTHS)
        follow_due = release_day(max(raw, launch), FOLLOW_MONTHS) if enforced else None
        pause_until = paused.get(customer.id)
        if pause_until is not None:  # Q4 暂缓：约定日当天还没跟进，次日才到期
            floor = pause_until + timedelta(days=1)
            preview_due = max(preview_due, floor)
            follow_due = max(follow_due, floor) if follow_due else None
        result[customer.id] = Clock(
            customer_id=customer.id, order_due=order_due, follow_due=follow_due,
            follow_preview_due=preview_due, follow_enforced=enforced,
            last_followup_date=followups.get(customer.id), last_order_date=orders.get(customer.id),
        )
    return result
