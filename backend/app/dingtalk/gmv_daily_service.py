"""每日 GMV 计算、Markdown 渲染与可靠钉钉投递。"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.trade.service import formal_projection_enabled as local_mode
from app.core.time import BEIJING_TIMEZONE, beijing_now, beijing_now_aware
from app.dingtalk.gmv_daily_config import admin_users, decorate_config, load_config, okki_user_bindings
from app.dingtalk.models import DingTalkMessageLog
from app.dingtalk.work_notify import get_work_notifier
from app.invoice.order_role import goods_order_sql


logger = logging.getLogger("commission.dingtalk.gmv_daily")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
MESSAGE_TITLE_MAX_LENGTH = 128
VALID_ORDER_SQL = f"""
    (o.status = '13972831656'
     OR (o.status = '13972831654' AND o.status_name = '已结清'))
    AND (o.trail IS NULL OR CAST(o.trail AS CHAR) NOT LIKE '%个人%')
    AND {goods_order_sql('o')}
"""
_LOCAL_REPORT_LOCK = threading.Lock()


def report_date_for_run(now: datetime | None = None) -> date:
    local_now = now.astimezone(BEIJING_TIMEZONE) if now is not None else beijing_now_aware()
    return local_now.date() - timedelta(days=1)


def yesterday_in_beijing() -> date:
    return report_date_for_run()


def _money(value: object, order_no: str) -> tuple[Decimal | None, str | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, f"订单 {order_no} 的 amount_usd 为空，无法计算 GMV"
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        return amount.quantize(CENT, rounding=ROUND_HALF_UP), None
    except (InvalidOperation, TypeError, ValueError):
        return None, f"订单 {order_no} 的 amount_usd={value!s} 不是有效金额"


def _parse_allocations(amount: Decimal, raw: object, order_no: str) -> tuple[list[dict], list[str], list[str]]:
    anomalies: list[str] = []
    fatal_anomalies: list[str] = []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        message = f"订单 {order_no} 的业绩归属部门不是有效 JSON"
        return [], [message], [message]
    entries = parsed if isinstance(parsed, list) else [parsed]
    entries = [entry for entry in entries if isinstance(entry, dict)]
    allocations: list[dict] = []
    for entry in entries:
        department_id = entry.get("department_id", entry.get("id"))
        raw_rate = entry.get("rate", 100 if len(entries) == 1 else None)
        try:
            department_id = int(department_id)
            rate = Decimal(str(raw_rate))
        except (InvalidOperation, TypeError, ValueError):
            message = f"订单 {order_no} 存在无法识别的部门或分摊比例"
            anomalies.append(message)
            fatal_anomalies.append(message)
            continue
        if not rate.is_finite():
            message = f"订单 {order_no} 的部门分摊比例不是有限数值"
            anomalies.append(message)
            fatal_anomalies.append(message)
            continue
        if department_id <= 0:
            message = f"订单 {order_no} 的部门 ID 必须为正整数"
            anomalies.append(message)
            fatal_anomalies.append(message)
            continue
        if rate < 0:
            message = f"订单 {order_no} 的部门分摊比例不能为负数"
            anomalies.append(message)
            fatal_anomalies.append(message)
            continue
        if rate == 0:
            continue
        try:
            allocated_amount = (amount * rate / HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            message = f"订单 {order_no} 的部门分摊金额超出可计算范围"
            anomalies.append(message)
            fatal_anomalies.append(message)
            continue
        allocations.append({
            "department_id": department_id,
            "department_name": str(entry.get("name") or f"部门{department_id}").strip(),
            "rate": rate,
            "amount": allocated_amount,
        })
    if not allocations:
        message = f"订单 {order_no} 没有大于 0 的有效部门分摊"
        anomalies.append(message)
        fatal_anomalies.append(message)
        return [], anomalies, fatal_anomalies
    total_rate = sum((item["rate"] for item in allocations), Decimal("0"))
    if total_rate == HUNDRED:
        # Allocate integer cents by largest remainder. Repeated half-up rounding
        # can otherwise force the last positive department below zero.
        cents = int(abs(amount) / CENT)
        exact = [Decimal(cents) * item["rate"] / HUNDRED for item in allocations]
        floor = [int(value.to_integral_value(rounding=ROUND_DOWN)) for value in exact]
        remaining = cents - sum(floor)
        priority = sorted(range(len(allocations)), key=lambda i: (-(exact[i] - floor[i]), allocations[i]["department_id"], i))
        for index in priority[:remaining]:
            floor[index] += 1
        for item, value in zip(allocations, floor):
            item["amount"] = Decimal(value) * CENT * (-1 if amount < 0 else 1)
    else:
        message = f"订单 {order_no} 的部门分摊合计为 {total_rate.normalize()}%，不是 100%"
        anomalies.append(message)
        fatal_anomalies.append(message)
    return allocations, anomalies, fatal_anomalies


def _new_member(source: dict, *, configured: bool, order_index: int, user_field="okki_user_id") -> dict:
    return {
        user_field: source[user_field],
        "name": source["name"],
        "exclude_from_total": bool(source.get("exclude_from_total")),
        "configured": configured,
        "is_active": bool(source.get("is_active", True)),
        "sort": order_index,
        "gmv": Decimal("0.00"),
    }


def calculate_report(report_date: date, config: dict, orders: list[dict]) -> dict:
    """纯计算：按订单部门 rate 分摊，并仅在配置所属队伍排除指定成员。"""
    user_field = "ark_user_id" if config.get("source") == "local" else "okki_user_id"
    captain_field = "captain_ark_user_id" if config.get("source") == "local" else "captain_okki_user_id"
    team_states: dict[int, dict] = {}
    configured_members: dict[tuple[int, str], dict] = {}
    for team_index, team in enumerate(config["teams"]):
        if not team.get("is_active", True):
            continue
        state = {
            "department_id": int(team["department_id"]),
            "name": team["name"],
            captain_field: team[captain_field],
            "sort": team_index,
            "members": {},
            "raw_gmv": Decimal("0.00"),
        }
        for member_index, member in enumerate(team.get("members", [])):
            key = (state["department_id"], str(member[user_field]))
            configured_members[key] = member
            if member.get("is_active", True):
                state["members"][str(member[user_field])] = _new_member(
                    member, configured=True, order_index=member_index, user_field=user_field,
                )
        team_states[state["department_id"]] = state

    unconfigured: dict[int, dict] = {}
    anomalies: list[str] = []
    fatal_anomalies: list[str] = []
    company_raw = Decimal("0.00")
    company_sales = Decimal("0.00")
    company_returns = Decimal("0.00")
    allocated_total = Decimal("0.00")
    for order in orders:
        order_no = str(order.get("order_no") or order.get("order_id") or "未知订单")
        amount, amount_error = _money(order.get("amount_usd"), order_no)
        if amount_error:
            anomalies.append(amount_error)
            fatal_anomalies.append(amount_error)
            continue
        company_raw += amount
        if order.get("source_type") == "sales_return":
            company_returns += amount
        else:
            company_sales += amount
        allocations, order_anomalies, order_fatal_anomalies = _parse_allocations(
            amount, order.get("departments"), order_no,
        )
        anomalies.extend(order_anomalies)
        fatal_anomalies.extend(order_fatal_anomalies)
        for allocation in allocations:
            allocated_total += allocation["amount"]
            department_id = allocation["department_id"]
            state = team_states.get(department_id)
            if state is None:
                state = unconfigured.setdefault(department_id, {
                    "department_id": department_id,
                    "name": allocation["department_name"],
                    "members": {},
                    "raw_gmv": Decimal("0.00"),
                })
            state["raw_gmv"] += allocation["amount"]
            user_id = str(order.get("user_id") or "未知人员")
            member = state["members"].get(user_id)
            if member is None:
                member_config = configured_members.get((department_id, user_id))
                source = member_config or {
                    user_field: user_id,
                    "name": str(order.get("user_name") or user_id),
                    "exclude_from_total": False,
                    "is_active": False,
                }
                member = _new_member(source, configured=False, order_index=10000 + len(state["members"]), user_field=user_field)
                state["members"][user_id] = member
                anomalies.append(f"{state['name']} 的订单人员 {member['name']} 不在该队在职配置中")
            member["gmv"] += allocation["amount"]

    teams = []
    company_excluded = Decimal("0.00")
    for state in team_states.values():
        members = sorted(state["members"].values(), key=lambda item: (item["sort"], item["name"]))
        excluded = sum((member["gmv"] for member in members if member["exclude_from_total"]), Decimal("0"))
        company_excluded += excluded
        teams.append({
            "department_id": state["department_id"],
            "name": state["name"],
            captain_field: state[captain_field],
            "members": members,
            "raw_gmv": state["raw_gmv"].quantize(CENT),
            "excluded_gmv": excluded.quantize(CENT),
            "total_gmv": (state["raw_gmv"] - excluded).quantize(CENT),
            "sort": state["sort"],
        })
    teams.sort(key=lambda item: item["sort"])
    unconfigured_teams = []
    for state in unconfigured.values():
        unconfigured_teams.append({
            "department_id": state["department_id"],
            "name": state["name"],
            "members": sorted(state["members"].values(), key=lambda item: item["name"]),
            "raw_gmv": state["raw_gmv"].quantize(CENT),
        })
        anomalies.append(f"订单出现未配置日报的队伍：{state['name']}（{state['department_id']}）")
    allocation_gap = (company_raw - allocated_total).quantize(CENT)
    if allocation_gap:
        gap_message = f"公司原始 GMV 与部门分摊合计相差 {_format_money(allocation_gap)}"
        anomalies.append(gap_message)
        fatal_anomalies.append(gap_message)
    return {
        "report_date": report_date,
        "teams": teams,
        "unconfigured_teams": unconfigured_teams,
        "company_raw_gmv": company_raw.quantize(CENT),
        "company_sales_gmv": company_sales.quantize(CENT),
        "company_return_adjustment_gmv": company_returns.quantize(CENT),
        "gmv_basis": "net_sales_and_returns_by_effective_date",
        "company_excluded_gmv": company_excluded.quantize(CENT),
        "company_total_gmv": (company_raw - company_excluded).quantize(CENT),
        "allocated_gmv": allocated_total.quantize(CENT),
        "allocation_gap_gmv": allocation_gap,
        "anomalies": list(dict.fromkeys(anomalies)),
        "fatal_anomalies": list(dict.fromkeys(fatal_anomalies)),
    }


def load_valid_orders(db: Session, report_date: date) -> list[dict]:
    if local_mode(db):
        from app.trade.query_service import load_orders
        from app.trade.return_adjustments import load_return_adjustments
        orders = load_orders(db, date_from=report_date, date_to=report_date)
        returns = load_return_adjustments(db, report_date, report_date)
        # Legacy department IDs are a separate namespace. Without reviewed
        # department mapping, expose the amount but block final publication.
        return [{**row, "departments": []} if row.get("source") == "legacy" or
                row.get("source_type") == "sales_return" else row for row in orders + returns]
    schema = get_settings().BUSINESS_DB_NAME
    rows = db.execute(text(f"""
        SELECT o.order_id, o.order_no, o.amount_usd, o.user_id, o.departments,
               COALESCE(ub.full_name, o.user_id) AS user_name
        FROM `{schema}`.okki_orders o
        LEFT JOIN `{schema}`.user_basic ub ON ub.user_id = o.user_id
        WHERE o.account_date = :report_date AND {VALID_ORDER_SQL}
        ORDER BY o.order_id
    """), {"report_date": report_date}).mappings().all()
    from app.sales_return.gmv import adjustments
    return [dict(row) for row in rows] + adjustments(db, report_date, report_date)


def build_report(db: Session, report_date: date | None = None) -> tuple[dict, dict]:
    effective_date = report_date or yesterday_in_beijing()
    config = decorate_config(db, load_config(db))
    return _report_data(db, effective_date, config), config


def _report_data(db, effective_date, config):
    report = calculate_report(effective_date, config, load_valid_orders(db, effective_date))
    if local_mode(db):
        from app.trade.refresh_service import projection_status
        # Daily company totals include every owner, including unassigned orders.
        report["projection_status"] = projection_status(db, date_from=effective_date, date_to=effective_date)
        if report["projection_status"]["status"] != "current":
            report["fatal_anomalies"].append("本地订单统计更新中")
    return report


def _format_money(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _escape(value: object) -> str:
    text_value = str(value)
    for char in ("\\", "*", "_", "[", "]", "#"):
        text_value = text_value.replace(char, f"\\{char}")
    return text_value


def _message_title(value: str) -> str:
    return value[:MESSAGE_TITLE_MAX_LENGTH]


def render_team_markdown(report: dict, team: dict) -> str:
    day = report["report_date"].isoformat()
    lines = [f"## {day} GMV 日报｜{_escape(team['name'])}", ""]
    for member in team["members"]:
        notes = []
        if member["exclude_from_total"]:
            notes.append("仅展示，不计汇总")
        if not member["configured"]:
            notes.append("非在职配置但有业绩")
        suffix = f"　※{'；'.join(notes)}" if notes else ""
        lines.append(f"- {_escape(member['name'])}：**{_format_money(member['gmv'])}**{suffix}")
    lines.extend([
        "", "---", "",
        f"- 净 GMV（排除前）：**{_format_money(team['raw_gmv'])}**",
        f"- 排除金额：**{_format_money(team['excluded_gmv'])}**",
        f"- 队伍汇总：**{_format_money(team['total_gmv'])}**",
        "", f"> 口径：销售核算日及退货生效日={day}；净 GMV；USD；冻结原部门 rate 分摊。",
    ])
    return "\n".join(lines)


def render_admin_markdown(report: dict) -> str:
    day = report["report_date"].isoformat()
    lines = [
        f"## {day} 全业务 GMV 日报", "",
        f"- 公司净 GMV（排除前）：**{_format_money(report['company_raw_gmv'])}**",
        f"- 排除金额：**{_format_money(report['company_excluded_gmv'])}**",
        f"- 公司考核 GMV：**{_format_money(report['company_total_gmv'])}**",
        "", "### 队伍与个人明细",
    ]
    for team in report["teams"]:
        lines.extend(["", f"**{_escape(team['name'])}｜{_format_money(team['total_gmv'])}**"])
        for member in team["members"]:
            notes = []
            if member["exclude_from_total"]:
                notes.append("不计队伍汇总")
            if not member["configured"]:
                notes.append("配置外人员")
            suffix = f"（{'；'.join(notes)}）" if notes else ""
            lines.append(f"- {_escape(member['name'])}：{_format_money(member['gmv'])}{suffix}")
    for team in report["unconfigured_teams"]:
        lines.extend(["", f"**未配置队伍：{_escape(team['name'])}｜{_format_money(team['raw_gmv'])}**"])
        lines.extend(f"- {_escape(member['name'])}：{_format_money(member['gmv'])}" for member in team["members"])
    if report["anomalies"]:
        lines.extend(["", "### 数据异常"])
        lines.extend(f"- {_escape(item)}" for item in report["anomalies"])
    lines.extend(["", f"> 口径：销售核算日及退货生效日={day}；净 GMV；USD；冻结原部门 rate 分摊。"])
    return "\n".join(lines)


def preview_report(db: Session, report_date: date | None = None) -> dict:
    report, config = build_report(db, report_date)
    return {
        "report": report,
        "team_messages": [
            {"department_id": team["department_id"], "team_name": team["name"], "markdown": render_team_markdown(report, team)}
            for team in report["teams"]
        ],
        "admin_markdown": render_admin_markdown(report),
        "config_persisted": bool(config.get("persisted")),
    }


@contextmanager
def _report_lock(db: Session, report_date: date):
    bind = db.get_bind()
    if bind.dialect.name != "mysql":
        acquired = _LOCAL_REPORT_LOCK.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                _LOCAL_REPORT_LOCK.release()
        return
    lock_name = f"ark_gmv_daily_{report_date:%Y%m%d}"
    with bind.connect() as connection:
        acquired = connection.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar() == 1
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


def _prepare_delivery_logs(db: Session, jobs: list[dict]) -> None:
    """在任何外部调用前一次性冻结整批快照，避免接收人之间出现不同版本。"""
    now = beijing_now()
    for job in jobs:
        existing = (
            db.query(DingTalkMessageLog)
            .filter(
                DingTalkMessageLog.related_type == job["related_type"],
                DingTalkMessageLog.related_id == job["related_id"],
            )
            .order_by(DingTalkMessageLog.id.desc())
            .first()
        )
        if existing and existing.send_status == "success":
            job["prepared_status"] = "skipped"
            continue
        log = existing or DingTalkMessageLog(
            msg_type="markdown",
            title=job["title"],
            content=job["content"],
            related_type=job["related_type"],
            related_id=job["related_id"],
            created_at=now,
        )
        if existing is None:
            db.add(log)
        log.send_status = "pending"
        log.error_msg = None
        job["log"] = log
        job["prepared_status"] = "pending"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


async def _deliver(db: Session, *, job: dict, notifier) -> dict:
    recipient = job["recipient"]
    if job["prepared_status"] == "skipped":
        return {"recipient": recipient["name"], "status": "skipped", "reason": "already_sent"}
    log = job["log"]
    log_id = log.id
    try:
        sent = await notifier.send_to_users(
            user_ids=[recipient["dingtalk_id"]], title=log.title, markdown_text=log.content,
        )
        if not sent:
            raise RuntimeError("钉钉工作通知返回失败")
        log.send_status = "success"
        log.sent_at = beijing_now()
        db.commit()
        return {"recipient": recipient["name"], "status": "success"}
    except Exception as exc:
        db.rollback()
        persisted = db.get(DingTalkMessageLog, log_id)
        if persisted:
            persisted.send_status = "failed"
            persisted.error_msg = str(exc)
            db.commit()
        logger.warning("GMV 日报发送失败 recipient=%s error=%s", recipient["name"], exc)
        print(f"[GMV_DAILY] 发送失败 recipient={recipient['name']} error={exc}", flush=True)
        return {"recipient": recipient["name"], "status": "failed", "reason": str(exc)}


async def send_daily_report(db: Session, report_date: date | None = None, scope: str = "all", notifier=None) -> dict:
    effective_date = report_date or yesterday_in_beijing()
    with _report_lock(db, effective_date) as acquired:
        if not acquired:
            return {"report_date": effective_date, "status": "skipped", "reason": "another_run_active", "deliveries": []}
        raw_config = load_config(db)
        if not raw_config.get("persisted"):
            raise ValueError("请先在 GMV 日报配置页核对名单、选择管理员接收人并保存")
        if scope in {"all", "admins"} and not raw_config.get("admin_recipient_user_ids"):
            raise ValueError("GMV 日报尚未配置管理员接收人")
        config = decorate_config(db, raw_config)
        binding_map = {str(uid): row for uid, row in admin_users(db).items()} if local_mode(db) else okki_user_bindings(db)
        captain_field = "captain_ark_user_id" if local_mode(db) else "captain_okki_user_id"
        delivery_plan: list[dict] = []
        jobs: list[dict] = []
        if scope in {"all", "teams"}:
            for configured in config["teams"]:
                if not configured.get("is_active", True):
                    continue
                recipient = binding_map.get(str(configured[captain_field]))
                if not recipient or not recipient["dingtalk_id"]:
                    delivery_plan.append({"result": {
                        "recipient": configured[captain_field],
                        "status": "failed",
                        "reason": "captain_dingtalk_missing",
                    }})
                    continue
                job = {
                    "recipient": recipient,
                    "title": _message_title(f"{effective_date.isoformat()} GMV 日报｜{configured['name']}"),
                    "related_type": "gmv_daily_team",
                    "related_id": f"{effective_date:%Y%m%d}:{'ark-department:' if local_mode(db) else ''}{configured['department_id']}:{recipient['ark_user_id']}",
                    "department_id": configured["department_id"],
                }
                jobs.append(job)
                delivery_plan.append({"job": job})
        if scope in {"all", "admins"}:
            admins = admin_users(db, config["admin_recipient_user_ids"])
            for user_id in config["admin_recipient_user_ids"]:
                recipient = admins.get(user_id)
                if not recipient or not recipient["dingtalk_id"]:
                    delivery_plan.append({"result": {
                        "recipient": str(user_id),
                        "status": "failed",
                        "reason": "admin_dingtalk_missing",
                    }})
                    continue
                job = {
                    "recipient": recipient,
                    "title": _message_title(f"{effective_date.isoformat()} 全业务 GMV 日报"),
                    "related_type": "gmv_daily_admin",
                    "related_id": f"{effective_date:%Y%m%d}:admin:{user_id}",
                }
                jobs.append(job)
                delivery_plan.append({"job": job})

        # 完整冻结批次的重试只依赖第一次快照；源订单随后变脏也不能阻断补发。
        for job in jobs:
            job["frozen_log"] = (
                db.query(DingTalkMessageLog)
                .filter(
                    DingTalkMessageLog.related_type == job["related_type"],
                    DingTalkMessageLog.related_id == job["related_id"],
                )
                .order_by(DingTalkMessageLog.id.desc())
                .first()
            )
        all_jobs_frozen = bool(jobs) and all(job["frozen_log"] is not None for job in jobs)
        if all_jobs_frozen:
            for job in jobs:
                job["title"] = job["frozen_log"].title
                job["content"] = job["frozen_log"].content
        elif jobs:
            report = _report_data(db, effective_date, config)
            if report["fatal_anomalies"]:
                raise ValueError(f"GMV 数据存在阻断异常，请先预览核查：{report['fatal_anomalies'][0]}")
            teams_by_id = {team["department_id"]: team for team in report["teams"]}
            admin_content = render_admin_markdown(report)
            for job in jobs:
                if job["related_type"] == "gmv_daily_team":
                    job["content"] = render_team_markdown(report, teams_by_id[job["department_id"]])
                else:
                    job["content"] = admin_content

        notifier = notifier or get_work_notifier()
        if jobs:
            _prepare_delivery_logs(db, jobs)
        deliveries = []
        for item in delivery_plan:
            if "result" in item:
                deliveries.append(item["result"])
            else:
                deliveries.append(await _deliver(db, job=item["job"], notifier=notifier))
        has_failure = any(item["status"] == "failed" for item in deliveries)
        return {
            "report_date": effective_date,
            "status": "partial_failure" if has_failure else "completed",
            "deliveries": deliveries,
        }
