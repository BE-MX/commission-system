"""Award calculations from OKKI facts; never use attachment current-year values."""
import json
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import bindparam, text

from app.core.config import get_settings
from app.core.time import to_beijing_naive
from app.invoice.order_role import goods_order_sql
from app.battle_report.statistics import money
from app.battle_report.order_decisions import decision_index, resolve_order_role

NEW_DEAL_FIELD = "22595163468"
ZERO = Decimal(0)
logger = logging.getLogger(__name__)


def source_facts(db, report, members, now):
    """Read year/cohort facts including repeat orders now owned by another salesperson."""
    now = to_beijing_naive(now)
    if now.date() < report.start_date:
        return [], None
    schema = get_settings().BUSINESS_DB_NAME
    query = text(f"""
        SELECT o.order_id, o.order_no, o.user_id, o.company_id, o.account_date, o.amount_usd,
               o.custom_fields, o.synced_at, {goods_order_sql('o')} AS is_goods
        FROM `{schema}`.okki_orders o
        WHERE (o.status = '13972831656' OR (o.status = '13972831654' AND o.status_name = '已结清'))
          AND (o.trail IS NULL OR CAST(o.trail AS CHAR) NOT LIKE '%个人%')
          AND (o.account_date BETWEEN :start AND :end OR o.account_date IS NULL)
          AND (o.user_id IN :users OR o.company_id IN (
              SELECT s.company_id FROM `{schema}`.okki_orders s
              WHERE s.user_id IN :users AND s.account_date BETWEEN :start AND :end
          ))
        ORDER BY o.account_date, o.order_id
    """).bindparams(bindparam("users", expanding=True))
    rows = db.execute(query, {"start": report.start_date, "end": min(report.end_date, now.date()),
                              "users": [m.okki_user_id for m in members]}).mappings().all()
    synced = db.execute(text(f"SELECT MAX(synced_at) FROM `{schema}`.okki_orders")).scalar()
    return rows, synced.isoformat() if hasattr(synced, "isoformat") else str(synced) if synced else None


def calculate(report, members, raw, now, synced_at=None):
    now = to_beijing_naive(now)
    issues, orders, seen = [], [], {}
    try:
        decisions = decision_index(report.award_rules)
    except (ValueError, TypeError):
        logger.warning("Invalid persisted battle-report order decisions", exc_info=True)
        print("Invalid battle-report order decisions; award ranking suspended", flush=True)
        decisions = {}
        issues.append("人工订单裁定配置无效；GMV保留，排名待管理员核对")
    applied_decisions = set()
    gmv_issues = set()
    for source in raw:
        row = dict(source)
        if not row.get("is_goods", True):
            continue  # Independent freight may inherit the goods order's new-deal flag.
        try:
            oid, uid, cid = (str(row.get(k) or "") for k in ("order_id", "user_id", "company_id"))
            day = row["account_date"]
            day = day.date() if isinstance(day, datetime) else day if isinstance(day, date) else date.fromisoformat(day)
            if not report.start_date <= day <= min(report.end_date, now.date()):
                continue
            amount = Decimal(str(row.get("amount_usd")))
            fields = row["custom_fields"]
            fields = json.loads(fields) if isinstance(fields, str) else fields
            mark = fields.get(NEW_DEAL_FIELD) if isinstance(fields, dict) else None
            if not oid or not uid or not cid or not amount.is_finite() or amount < 0:
                raise ValueError
            role, issue = resolve_order_role({**row, "account_date": day}, mark, decisions)
            if issue:
                issues.append(issue)
            elif oid in decisions:
                applied_decisions.add(oid)
            fact = (uid, cid, day, amount, mark, bool(row.get("is_goods", True)))
            if oid in seen:
                if seen[oid] != fact:
                    issues.append(f"订单 {oid} 重复且事实冲突")
                    gmv_issues.update((uid, seen[oid][0]))
                continue
            seen[oid] = fact
            orders.append({"id": oid, "uid": uid, "cid": cid, "day": day,
                           "amount": amount, "new": True if role == "new_sign" else False if role == "repeat" else None, "goods": fact[-1]})
        except (ValueError, TypeError, KeyError, InvalidOperation):
            issues.append(f"订单 {row.get('order_id', '未知')} 缺少有效客户、日期、美元金额或新成交标记")
            gmv_issues.add(str(row.get("user_id") or ""))
    # Earliest new-sign fact determines ownership; later owner transfers cannot steal the cohort.
    def order_key(o):
        return (o["day"], int(o["id"]) if o["id"].isdigit() else 0, o["id"])
    cohorts = {}
    for o in sorted(orders, key=order_key):
        if o["new"]:
            cohorts.setdefault(o["cid"], o)
    rows = []
    for m in members:
        owned = [o for o in orders if o["uid"] == str(m.okki_user_id) and o["goods"]]
        new = {cid: o for cid, o in cohorts.items() if o["uid"] == str(m.okki_user_id)}
        repeats = [o for o in orders if o["cid"] in new and o["new"] is False and o["goods"]
                   and order_key(o) > order_key(new[o["cid"]])]
        row = {"member_id": m.id, "ark_user_id": m.ark_user_id, "user_name": m.user_name,
               "team": m.team, "is_captain": bool(m.is_captain),
               "gmv_complete": str(m.okki_user_id) not in gmv_issues,
               "gmv": format(sum((o["amount"] for o in owned), ZERO), "f"),
               "new_count": len(new), "new_amount": format(sum((o["amount"] for o in owned if o["new"]), ZERO), "f"),
               "repeat_count": len({o["cid"] for o in repeats}), "repeat_orders": len(repeats),
               "repeat_amount": format(sum((o["amount"] for o in repeats), ZERO), "f")}
        rows.append(row)
    data = {"award_kind": report.award_kind, "people": rows, "issues": issues,
            "data_complete": not issues, "calculated_at": now.isoformat(), "source_synced_at": synced_at,
            "source_label": "OKKI订单镜像 · 每次刷新重新查询 · 非直连实时接口", "currency": "USD",
            "period_state": "upcoming" if now.date() < report.start_date else "ended" if now.date() > report.end_date else "running",
            "workday_progress": None, "order_decision_count": len(decisions),
            "applied_order_decision_count": len(applied_decisions)}
    if report.award_kind == "annual_repurchase":
        annual(data, report)
    else:
        pk(data)
    return data


def annual_order_key(row):
    """Display by score only; equal scores retain roster order."""
    return -Decimal(row["score"])


def annual(data, report):
    baselines = {b["ark_user_id"]: b for b in report.award_rules["baselines"]}
    data["target_source"] = "附件I2:I18 · 评比需满足最低门槛（USD）"
    for row in data["people"]:
        baseline = Decimal(str(baselines[row["ark_user_id"]]["gmv_2025_usd"]))
        target = Decimal(str(baselines[row["ark_user_id"]]["target_gmv_usd"]))
        row.update(baseline=format(baseline, "f"), target=format(target, "f"),
                   progress_percent=float(Decimal(row["gmv"]) / target * 100),
                   qualified=row["gmv_complete"] and Decimal(row["gmv"]) >= target,
                   score=format(Decimal(row["new_count"]) * Decimal("0.2") + Decimal(row["repeat_count"]) * Decimal("0.2")
                                + Decimal(row["repeat_amount"]) / 5000 * Decimal("0.6"), "f"),
                   rank=None, overall_rank=None, top_five=False)
    data["people"].sort(key=annual_order_key)
    data["ranking_rule"] = "score_desc_roster_ties_v3"
    qualified = [r for r in data["people"] if r["qualified"]]
    cutoff_tie = data["data_complete"] and len(qualified) > 5 and Decimal(qualified[4]["score"]) == Decimal(qualified[5]["score"])
    for index, row in enumerate(data["people"], 1):
        if data["data_complete"]:
            row["overall_rank"] = index
    for row in qualified:
        if not data["data_complete"]:
            continue
        row["rank"] = 1 + sum(Decimal(r["score"]) > Decimal(row["score"]) for r in qualified)
        row["top_five"] = row["rank"] <= 5 and (not cutoff_tie or Decimal(row["score"]) > Decimal(qualified[4]["score"]))
    data.update(qualified=qualified, unqualified=[r for r in data["people"] if not r["qualified"]],
                cutoff_tie=cutoff_tie, teams=[], pending=[r for r in data["people"] if not r["gmv_complete"]])
    data["unqualified"] = [r for r in data["unqualified"] if r["gmv_complete"]]


def pk(data):
    teams = []
    for team in dict.fromkeys(r["team"] for r in data["people"]):
        people = [r for r in data["people"] if r["team"] == team]
        count, total = len(people), sum(r["new_count"] for r in people)
        target, base = count * 6, count * 100
        complete = data["data_complete"] and total >= target
        teams.append({"team": team, "captain": next((r["user_name"] for r in people if r["is_captain"]), "未配置"),
                      "member_count": count, "new_count": total, "target": target,
                      "new_amount": format(sum((Decimal(r["new_amount"]) for r in people), ZERO), "f"),
                      "gmv": format(sum((Decimal(r["gmv"]) for r in people), ZERO), "f"),
                      "progress_percent": total / target * 100, "completed": complete,
                      "target_bonus": money(Decimal(base) * (Decimal("1.1") if total * 10 >= target * 11 else 1)) if complete else "0.00",
                      "pk_bonus": "0.00", "inquiries": 0, "leading": False, "people": people})
    def metric(t):
        return (Decimal(t["new_count"]) / t["member_count"], Decimal(t["new_amount"]) / t["member_count"],
                Decimal(t["gmv"]) / t["member_count"])
    winner = None
    if len(teams) == 2 and data["data_complete"] and metric(teams[0]) != metric(teams[1]):
        lead = max(teams, key=metric)
        lead["leading"] = True
        if all(t["completed"] for t in teams):
            winner = lead["team"]
            lead["pk_bonus"], lead["inquiries"] = "500.00", 10
    gate = len(teams) == 2 and all(t["completed"] for t in teams)
    data.update(teams=teams, pk_eligible=gate, winner=winner,
                pk_status="数据待核对" if not data["data_complete"] else ("当前胜出，奖金与询盘尚未发放" if data["period_state"] == "ended" else "暂领先，奖金待活动结束确认") if winner else "双方达标，PK持平" if gate else "双方均须达标后评选PK胜利奖",
                rewards_provisional=data["period_state"] != "ended")


def build_snapshot(db, report, members, now):
    raw, synced = source_facts(db, report, members, now)
    return calculate(report, members, raw, now, synced)
