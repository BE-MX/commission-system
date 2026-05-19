"""素材管理 — 下载统计服务"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.asset.models import Asset, DownloadLog


def get_top_downloaded(db: Session, limit: int = 20) -> list[dict]:
    """下载量 Top N 素材。"""
    rows = (
        db.query(
            Asset.id,
            Asset.file_name,
            Asset.file_type,
            Asset.download_count,
        )
        .filter(Asset.status != "offline")
        .order_by(desc(Asset.download_count))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "file_name": r.file_name,
            "file_type": r.file_type,
            "download_count": r.download_count,
        }
        for r in rows
    ]


def get_download_trend(db: Session, days: int = 30) -> list[dict]:
    """最近 N 天每日下载量趋势。"""
    start_date = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            func.date(DownloadLog.created_at).label("date"),
            func.count(DownloadLog.id).label("count"),
        )
        .filter(DownloadLog.created_at >= start_date)
        .group_by(func.date(DownloadLog.created_at))
        .order_by(func.date(DownloadLog.created_at))
        .all()
    )
    return [{"date": str(r.date), "count": r.count} for r in rows]


def get_download_stats(db: Session) -> dict:
    """下载统计概览。"""
    total_downloads = db.query(func.count(DownloadLog.id)).scalar() or 0
    total_assets = db.query(func.count(Asset.id)).filter(Asset.status != "offline").scalar() or 0
    today = datetime.utcnow().date()
    today_downloads = (
        db.query(func.count(DownloadLog.id))
        .filter(func.date(DownloadLog.created_at) == today)
        .scalar()
        or 0
    )
    return {
        "total_downloads": total_downloads,
        "total_assets": total_assets,
        "today_downloads": today_downloads,
        "top_assets": get_top_downloaded(db, limit=10),
        "trend": get_download_trend(db, days=14),
    }
