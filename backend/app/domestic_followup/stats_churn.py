"""客户流失态势（方舟甲板）数据：释放倒计时、跟进频率、按大区聚合、近 30 天落海。

释放口径只来自 app.domestic.public_sea；频率口径复用 stats_coverage。
规格：docs/requirements/2026-11-13-followup-churn-ship/README.md 第三、七节。
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic import public_sea
from app.domestic.models import DomesticCustomer
from app.domestic_decision.ownership_events import latest_releases
from app.domestic_followup import config_service, stats_coverage, visibility
from app.domestic_followup.collaboration_models import FollowupResponsibility

REGIONS = ("华东", "华南", "华北", "华中", "西南", "东北", "西北")
UNKNOWN_REGION = "未填地区"
_PROVINCE_REGION = {
    **dict.fromkeys(("上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "台湾"), "华东"),
    **dict.fromkeys(("广东", "广西", "海南", "香港", "澳门"), "华南"),
    **dict.fromkeys(("北京", "天津", "河北", "山西", "内蒙古"), "华北"),
    **dict.fromkeys(("河南", "湖北", "湖南"), "华中"),
    **dict.fromkeys(("重庆", "四川", "贵州", "云南", "西藏"), "西南"),
    **dict.fromkeys(("辽宁", "吉林", "黑龙江"), "东北"),
    **dict.fromkeys(("陕西", "甘肃", "青海", "宁夏", "新疆"), "西北"),
}
_SUFFIXES = ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区", "自治区", "省", "市")
CRITICAL_DAYS, WARNING_DAYS, FALLEN_WINDOW_DAYS = 3, 14, 30
INDIVIDUAL_LEVELS = ("S级", "A级")


def region_of(province: str | None) -> str:
    """自由文本省份 → 大区；「广东」「广东省」算同一个，无法识别归入未填地区。"""
    text = (province or "").strip()
    for suffix in _SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return _PROVINCE_REGION.get(text, UNKNOWN_REGION)


def _tier(remaining: int) -> str:
    return "critical" if remaining <= CRITICAL_DAYS else "warning" if remaining <= WARNING_DAYS else "stable"


def _target_user(db: Session, current_user: dict, user_id: int | None) -> int | None:
    """None = 全部（仅 read_all）；业务员只能看自己。"""
    actor = visibility.uid(current_user)
    if not visibility.can_read_all(current_user):
        if user_id and user_id != actor:
            raise PermissionError("只能查看自己的客户流失态势")
        return actor
    if user_id and db.get(ArkUser, user_id) is None:
        raise LookupError("用户不存在")
    return user_id


def _straps(db: Session, today: date, frequencies: dict) -> tuple[dict[int, int], set[int], dict[int, int]]:
    """频率超期天数、有跟进安排的客户、跟进责任人。口径与看板「应跟未跟」一致。"""
    entries = stats_coverage.responsible_customers(db, today, today)
    overdue, arranged, followup_owner = {}, set(), {}
    for owner_id in {entry["owner_id"] for entry in entries}:
        for row in stats_coverage.coverage_for(entries, owner_id, frequencies, today)["overdue_customers"]:
            overdue[row["customer_id"]] = row["overdue_days"]
    for entry in entries:
        followup_owner[entry["customer"].id] = entry["owner_id"]
        if entry["customer"].customer_level in frequencies:
            arranged.add(entry["customer"].id)
    return overdue, arranged, followup_owner


def churn_map(db: Session, current_user: dict, *, user_id: int | None = None) -> dict:
    today = beijing_today()
    target = _target_user(db, current_user, user_id)
    read_all = visibility.can_read_all(current_user)
    config = config_service.get_config(db)
    frequencies = config.get("frequency_days") or {}

    query = db.query(DomesticCustomer).filter(DomesticCustomer.status == 1, DomesticCustomer.owner_user_id.isnot(None))
    if target is not None:  # 我归属的 + 我负责跟进的
        query = query.filter(or_(
            DomesticCustomer.owner_user_id == target,
            DomesticCustomer.id.in_(select(FollowupResponsibility.customer_id).where(
                FollowupResponsibility.owner_user_id == target)),
        ))
    owned = query.order_by(DomesticCustomer.id).all()
    launch = public_sea.launch_date(db)
    clocks = public_sea.compute_clocks(db, owned, today, launch=launch, launch_known=True)
    overdue, arranged, followup_owner = _straps(db, today, frequencies)

    regions = {key: {"key": key, "owned": 0, "stable": 0, "critical": 0, "warning": 0,
                     "public_total": 0, "fallen_recent": 0} for key in (*REGIONS, UNKNOWN_REGION)}
    names: dict[int, str] = {}
    customers = []
    for customer in owned:
        due, reason = clocks[customer.id].display()
        remaining = (due - today).days
        tier = _tier(remaining)
        region = regions[region_of(customer.province)]
        region["owned"] += 1
        region[tier] += 1
        if tier == "stable" and customer.customer_level not in INDIVIDUAL_LEVELS:
            continue
        follow_owner = followup_owner.get(customer.id)
        customers.append({
            "id": customer.id, "shop_name": customer.shop_name, "level": customer.customer_level or "",
            "province": customer.province or "", "region": region["key"], "tier": tier,
            "release_date": due.isoformat(), "remaining_days": remaining, "clock": reason,
            "last_followup_date": _iso(clocks[customer.id].last_followup_date),
            "last_order_date": _iso(clocks[customer.id].last_order_date),
            "frequency_overdue_days": overdue.get(customer.id, 0),
            "strap": "none" if customer.id not in arranged else "loose" if overdue.get(customer.id) else "tight",
            "owner_user_id": customer.owner_user_id if read_all else None,
            "followup_user_id": follow_owner if read_all else None,
            "mine_as_owner": customer.owner_user_id == visibility.uid(current_user),
            "mine_as_followup": follow_owner == visibility.uid(current_user),
        })
        if read_all:
            names.update(dict.fromkeys(filter(None, (customer.owner_user_id, follow_owner))))
    customers.sort(key=lambda row: (row["remaining_days"], row["shop_name"]))

    fallen = _fallen(db, regions, today, read_all, names, target)
    if names:
        resolved = dict(db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.id.in_(names)).all())
        name_fields = {"owner_user_id": "owner_name", "followup_user_id": "followup_name",
                       "previous_owner_id": "previous_owner_name"}
        for row in (*customers, *fallen):
            for key, field in name_fields.items():
                if row.get(key):
                    row[field] = resolved.get(row[key])
    owner_options = []
    if read_all:
        owner_ids = {row[0] for row in db.query(DomesticCustomer.owner_user_id).filter(
            DomesticCustomer.status == 1, DomesticCustomer.owner_user_id.isnot(None)).distinct()}
        owner_options = [{"value": uid, "label": name} for uid, name in db.query(ArkUser.id, ArkUser.real_name)
                         .filter(ArkUser.id.in_(owner_ids or {0})).order_by(ArkUser.real_name, ArkUser.id)]
    return {
        "generated_at": beijing_now().isoformat(timespec="minutes"),
        "today": today.isoformat(),
        "rule": {"launch_date": _iso(launch), "follow_enforced": bool(launch and today >= launch),
                 "order_months": public_sea.ORDER_MONTHS, "follow_months": public_sea.FOLLOW_MONTHS},
        "kpis": {
            "critical": sum(region["critical"] for region in regions.values()),
            "within_14": sum(region["critical"] + region["warning"] for region in regions.values()),
            "fallen_30": sum(region["fallen_recent"] for region in regions.values()),
        },
        "regions": [region for region in regions.values() if region["owned"] or region["public_total"]],
        "customers": customers,
        "fallen": fallen,
        "owners": owner_options,
        "scope": "all" if target is None else "user",
        "user_id": target,
    }


def _fallen(db: Session, regions: dict, today: date, read_all: bool, names: dict, target: int | None) -> list[dict]:
    """公海：各区总数（全公司）；近 30 天落海按查看范围计数并给明细。

    查看某人（业务员本人或管理者筛选）时只算、只列原归属是这个人的——业务员只看得到自己掉下去的客户，
    看不到同事的公海客户明细（同事的客户计入各区公海总数）。
    """
    for province, count in (db.query(DomesticCustomer.province, func.count(DomesticCustomer.id))
                            .filter(DomesticCustomer.status == 1, DomesticCustomer.owner_user_id.is_(None))
                            .group_by(DomesticCustomer.province)):
        regions[region_of(province)]["public_total"] += count
    since = datetime.combine(today - timedelta(days=FALLEN_WINDOW_DAYS), time.min)
    # 归属变化会刷新 updated_at：先用它把候选缩到近 30 天动过的公海客户，再按客户 ID 查事件（事件表无时间索引）
    candidates = [row[0] for row in db.query(DomesticCustomer.id).filter(
        DomesticCustomer.status == 1, DomesticCustomer.owner_user_id.is_(None), DomesticCustomer.updated_at >= since)]
    releases = latest_releases(db, candidates, since)
    if target is not None:
        releases = {cid: event for cid, event in releases.items() if event["previous_owner_id"] == target}
    if not releases:
        return []
    rows = []
    for customer in db.query(DomesticCustomer).filter(DomesticCustomer.id.in_(releases)).order_by(DomesticCustomer.id):
        event = releases[customer.id]
        region = regions[region_of(customer.province)]
        region["fallen_recent"] += 1
        row = {"id": customer.id, "shop_name": customer.shop_name, "level": customer.customer_level or "",
               "province": customer.province or "", "region": region["key"],
               "fallen_at": event["at"].isoformat(timespec="minutes"),
               "fallen_days_ago": (today - event["at"].date()).days,
               "previous_owner_id": event["previous_owner_id"] if read_all else None}
        if read_all:
            names[event["previous_owner_id"]] = None
        rows.append(row)
    rows.sort(key=lambda row: (row["fallen_days_ago"], row["shop_name"]))
    return rows


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
