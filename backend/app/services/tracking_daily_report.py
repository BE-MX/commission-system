"""物流跟踪 — 日报生成服务

每天 08:30 为每个有运单的用户生成 HTML 日报并推送钉钉。
"""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.tracking import ShipmentTracking, ShippingDailyReport
from app.utils.tracking_status import get_status_label
from app.utils.shortlink import generate_short_link

logger = logging.getLogger("tracking.daily_report")

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "tracking" / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _format_est_date(dt) -> str:
    """格式化预计送达日期"""
    if not dt:
        return "-"
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d")


def _format_dt(dt) -> str:
    """格式化日期时间"""
    if not dt:
        return "-"
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d %H:%M")


def _shipment_to_dict(s: ShipmentTracking) -> dict:
    """将 ShipmentTracking 转为模板可用字典"""
    return {
        "waybill_no": s.waybill_no,
        "carrier": s.carrier,
        "carrier_name": s.carrier_name,
        "receiver_name": s.receiver_name or "-",
        "receiver_country": s.receiver_country or "-",
        "unified_status": s.unified_status or "pending",
        "status_label": get_status_label(s.unified_status),
        "estimated_delivery_date": _format_est_date(s.estimated_delivery_date),
        "delivered_at": _format_dt(s.delivered_at),
        "current_status_text": s.current_status_text or "",
    }


def generate_user_report(db: Session, user_id: int, dingtalk_user_id: str, report_date: date, username: str = None) -> ShippingDailyReport | None:
    """为指定用户生成指定日期的日报。

    user_id: 系统用户ID（用于存日报表）
    dingtalk_user_id: 钉钉用户ID（用于查运单）
    username: 系统用户名（用于 fallback 匹配 dingtalk_user_id 为空的运单）
    """
    from app.auth.models import ArkUser

    seven_days_ago = report_date - timedelta(days=7)

    # 查询该用户的所有活跃/近期运单
    # 主匹配：dingtalk_user_id == 用户钉钉ID
    # 兜底匹配：dingtalk_user_name == 用户名（处理 dingtalk_user_id 缺失的情况）
    from sqlalchemy import or_

    conditions = [ShipmentTracking.dingtalk_user_id == dingtalk_user_id]
    if username:
        conditions.append(
            (ShipmentTracking.dingtalk_user_name == username)
            & (ShipmentTracking.dingtalk_user_id.in_(["", None]))
        )

    shipments = (
        db.query(ShipmentTracking)
        .filter(or_(*conditions))
        .filter(
            (ShipmentTracking.is_active == True)
            | (ShipmentTracking.delivered_at >= seven_days_ago)
        )
        .all()
    )

    if not shipments:
        logger.info("用户 %s 在 %s 无运单，跳过日报生成", user_id, report_date)
        return None

    # 按状态分组
    alert_shipments = []        # exception + customs_hold
    delivering_shipments = []   # out_for_delivery
    transit_shipments = []      # in_transit + picked_up
    recent_delivered = []       # delivered (近7天)

    for s in shipments:
        unified = s.unified_status or "pending"
        s_dict = _shipment_to_dict(s)

        if unified in ("exception", "customs_hold"):
            alert_shipments.append(s_dict)
        elif unified == "out_for_delivery":
            delivering_shipments.append(s_dict)
        elif unified in ("in_transit", "picked_up"):
            transit_shipments.append(s_dict)
        elif unified == "delivered" and s.delivered_at and s.delivered_at.date() >= seven_days_ago:
            recent_delivered.append(s_dict)

    total_count = len(shipments)
    alert_count = len(alert_shipments)
    delivering_count = len(delivering_shipments)
    in_transit_count = len(transit_shipments) + delivering_count + alert_count

    # 若已存在则删除旧记录（覆盖生成）
    existing = (
        db.query(ShippingDailyReport)
        .filter(ShippingDailyReport.user_id == user_id)
        .filter(ShippingDailyReport.report_date == report_date)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()

    # 渲染模板
    template = _jinja_env.get_template("daily_report.html")
    html = template.render(
        report_date=report_date.strftime("%Y年%m月%d日"),
        total_count=total_count,
        alert_count=alert_count,
        delivering_count=delivering_count,
        in_transit_count=in_transit_count,
        alert_shipments=alert_shipments,
        delivering_shipments=delivering_shipments,
        transit_shipments=transit_shipments,
        recent_delivered=recent_delivered,
    )

    # 存入数据库
    report = ShippingDailyReport(
        user_id=user_id,
        report_date=report_date,
        html_content=html,
        is_pushed=False,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    logger.info("用户 %s 日报已生成: %s", user_id, report_date)
    return report


async def push_daily_report(db: Session, report: ShippingDailyReport) -> bool:
    """推送日报到用户钉钉，生成短链。"""
    from app.dingtalk.work_notify import get_work_notifier
    from app.auth.models import ArkUser

    user = db.query(ArkUser).filter(ArkUser.id == report.user_id).first()
    if not user or not user.dingtalk_id:
        logger.info("用户 %s 未绑定钉钉ID，跳过日报推送", report.user_id)
        return False

    # 生成日报查看短链
    report_url = f"https://leshine.work/tracking/daily-report?date={report.report_date.strftime('%Y-%m-%d')}"
    try:
        short_url = generate_short_link(report_url)
    except Exception as e:
        logger.warning("日报短链生成失败: %s", e)
        short_url = report_url

    report.short_url = short_url
    db.commit()

    md = (
        f"### 📦 物流日报 · {report.report_date.strftime('%Y年%m月%d日')}\n\n"
        f"您名下运单最新状态汇总已生成，点击查看详情。\n\n"
        f"[查看日报]({short_url})"
    )

    notifier = get_work_notifier()
    try:
        await notifier.send_to_users(
            user_ids=[user.dingtalk_id],
            title=f"物流日报 · {report.report_date.strftime('%m月%d日')}",
            markdown_text=md,
        )
        report.is_pushed = True
        db.commit()
        logger.info("日报已推送给用户 %s", report.user_id)
        return True
    except Exception as e:
        logger.warning("日报推送失败 %s: %s", report.user_id, e)
        return False


async def generate_daily_reports() -> dict:
    """生成所有用户的日报并推送。APScheduler 定时任务入口。"""
    db = SessionLocal()
    today = date.today()

    try:
        from app.auth.models import ArkUser

        # 收集所有需要生成日报的系统用户（去重）
        user_ids = set()

        # 方式1：通过 dingtalk_user_id 关联
        dingtalk_ids = [
            row[0] for row in
            db.query(ShipmentTracking.dingtalk_user_id)
            .filter(ShipmentTracking.is_active == True)
            .filter(ShipmentTracking.dingtalk_user_id.isnot(None))
            .filter(ShipmentTracking.dingtalk_user_id != "")
            .distinct()
            .all()
        ]
        for dingtalk_id in dingtalk_ids:
            user = db.query(ArkUser).filter(ArkUser.dingtalk_id == dingtalk_id).first()
            if user:
                user_ids.add(user.id)

        # 方式2：通过 dingtalk_user_name 匹配（dingtalk_user_id 为空的运单）
        usernames = [
            row[0] for row in
            db.query(ShipmentTracking.dingtalk_user_name)
            .filter(ShipmentTracking.is_active == True)
            .filter(
                (ShipmentTracking.dingtalk_user_id.is_(None))
                | (ShipmentTracking.dingtalk_user_id == "")
            )
            .filter(ShipmentTracking.dingtalk_user_name.isnot(None))
            .filter(ShipmentTracking.dingtalk_user_name != "")
            .distinct()
            .all()
        ]
        for username in usernames:
            user = db.query(ArkUser).filter(ArkUser.username == username).first()
            if user:
                user_ids.add(user.id)

        if not user_ids:
            logger.info("今日无需要生成日报的用户")
            return {"total": 0, "generated": 0, "pushed": 0}

        generated = 0
        pushed = 0

        for uid in user_ids:
            user = db.query(ArkUser).filter(ArkUser.id == uid).first()
            if not user:
                continue

            # 检查今天是否已生成
            existing = (
                db.query(ShippingDailyReport)
                .filter(ShippingDailyReport.user_id == user.id)
                .filter(ShippingDailyReport.report_date == today)
                .first()
            )
            if existing:
                logger.info("用户 %s 今日日报已存在，跳过", user.id)
                continue

            report = generate_user_report(db, user.id, user.dingtalk_id or "", today, username=user.username)
            if report:
                generated += 1
                ok = await push_daily_report(db, report)
                if ok:
                    pushed += 1

        return {"total": len(user_ids), "generated": generated, "pushed": pushed}
    except Exception as e:
        logger.exception("日报生成任务异常: %s", e)
        return {"total": 0, "generated": 0, "pushed": 0, "error": str(e)}
    finally:
        db.close()


def get_user_daily_report(db: Session, user_id: int, report_date: date) -> ShippingDailyReport | None:
    """获取用户指定日期的日报。"""
    return (
        db.query(ShippingDailyReport)
        .filter(ShippingDailyReport.user_id == user_id)
        .filter(ShippingDailyReport.report_date == report_date)
        .first()
    )
