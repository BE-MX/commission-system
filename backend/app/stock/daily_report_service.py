"""备货管理 — 安全库存日报 (写入 / 查询 / 推送标记 / 接收人列表)"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.stock.models import StockDailyReport


def upsert_daily_report(
    db: Session,
    report_date_value: date,
    shortage_skus: list[dict],
    warning_skus: list[dict],
    summary: dict,
) -> StockDailyReport:
    """写入或更新当日日报。"""
    existing = (
        db.query(StockDailyReport)
        .filter(StockDailyReport.report_date == report_date_value)
        .first()
    )
    if existing:
        existing.shortage_count = summary.get("shortage_count", 0)
        existing.warning_count = summary.get("warning_count", 0)
        existing.sufficient_count = summary.get("sufficient_count", 0)
        existing.shortage_skus = _serialize_skus(shortage_skus)
        existing.warning_skus = _serialize_skus(warning_skus)
        db.commit()
        return existing

    rec = StockDailyReport(
        report_date=report_date_value,
        shortage_count=summary.get("shortage_count", 0),
        warning_count=summary.get("warning_count", 0),
        sufficient_count=summary.get("sufficient_count", 0),
        shortage_skus=_serialize_skus(shortage_skus),
        warning_skus=_serialize_skus(warning_skus),
        dingtalk_sent=0,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _serialize_skus(skus: list[dict]) -> list[dict]:
    """提取日报需要的字段精简存库"""
    keep = ["product_id", "product_name", "model", "enable_count",
            "safety_stock", "avg_daily_sales_30d", "suggested_qty"]
    return [{k: it.get(k) for k in keep if k in it} for it in skus]


def get_daily_report(db: Session, report_date_value: Optional[date] = None) -> Optional[dict]:
    """
    获取日报。report_date=None 时取最新一条。
    返回 dict 或 None。
    """
    q = db.query(StockDailyReport)
    if report_date_value:
        rec = q.filter(StockDailyReport.report_date == report_date_value).first()
    else:
        rec = q.order_by(StockDailyReport.report_date.desc()).first()

    if not rec:
        return None

    return {
        "id": rec.id,
        "report_date": rec.report_date.isoformat(),
        "shortage_count": rec.shortage_count,
        "warning_count": rec.warning_count,
        "sufficient_count": rec.sufficient_count,
        "shortage_skus": rec.shortage_skus or [],
        "warning_skus": rec.warning_skus or [],
        "dingtalk_sent": bool(rec.dingtalk_sent),
        "sent_at": rec.sent_at.isoformat() if rec.sent_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def mark_daily_report_pushed(db: Session, report_date_value: date) -> None:
    """标记钉钉已推送"""
    rec = (
        db.query(StockDailyReport)
        .filter(StockDailyReport.report_date == report_date_value)
        .first()
    )
    if rec:
        rec.dingtalk_sent = 1
        rec.sent_at = datetime.utcnow()
        db.commit()


def get_stock_recipients(db: Session) -> list[str]:
    """
    返回需要接收库存日报的钉钉 user_id 列表。
    口径: 拥有 stock:read 或 stock:admin 权限的活跃用户(含 super_admin)。
    """
    sql = """
        SELECT DISTINCT u.dingtalk_id
        FROM ark_users u
        LEFT JOIN ark_user_roles ur ON ur.user_id = u.id
        LEFT JOIN ark_roles r       ON r.id = ur.role_id
        LEFT JOIN ark_role_permissions rp ON rp.role_id = r.id
        LEFT JOIN ark_permissions p ON p.id = rp.permission_id
        WHERE u.is_active = 1
          AND u.dingtalk_id IS NOT NULL
          AND u.dingtalk_id <> ''
          AND (
              r.name = 'super_admin'
              OR p.code IN ('stock:read', 'stock:admin')
          )
    """
    rows = db.execute(text(sql)).all()
    return [str(r[0]) for r in rows if r[0]]
