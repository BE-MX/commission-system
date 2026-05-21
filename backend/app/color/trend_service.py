"""色彩趋势数据服务"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.color.models import ColorPalette, ColorTrendData

logger = logging.getLogger("color.trend")

COLOR_FAMILIES = ["black", "brown", "blonde", "red", "silver", "vibrant"]


def get_trend_overview(db: Session) -> list[dict]:
    """获取各色族当前热度概览"""
    # 取最近一周的各数据源平均值
    week_ago = date.today() - timedelta(days=7)

    results = []
    for family in COLOR_FAMILIES:
        # 最近一周各数据源的平均归一化分数
        rows = (
            db.query(ColorTrendData.data_source, func.avg(ColorTrendData.normalized_score))
            .filter(
                ColorTrendData.color_family == family,
                ColorTrendData.period_date >= week_ago,
            )
            .group_by(ColorTrendData.data_source)
            .all()
        )

        if rows:
            avg_score = sum(float(r[1] or 0) for r in rows) / len(rows)
            # 简单趋势判断：与上一周比较
            prev_week = week_ago - timedelta(days=7)
            prev_rows = (
                db.query(func.avg(ColorTrendData.normalized_score))
                .filter(
                    ColorTrendData.color_family == family,
                    ColorTrendData.period_date >= prev_week,
                    ColorTrendData.period_date < week_ago,
                )
                .scalar()
            )
            prev_score = float(prev_rows or 0)
            change = avg_score - prev_score
            trend = "rising" if change > 5 else "falling" if change < -5 else "stable"
        else:
            avg_score = 0
            change = 0
            trend = "stable"

        results.append({
            "color_family": family,
            "current_score": round(avg_score, 2),
            "trend": trend,
            "change_pct": round(change, 2),
        })

    # 按分数排序
    results.sort(key=lambda x: -x["current_score"])
    return results


def get_trend_history(
    db: Session,
    color_family: Optional[str] = None,
    data_source: Optional[str] = None,
    period_type: str = "weekly",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict]:
    """历史趋势数据查询"""
    q = db.query(ColorTrendData).filter(ColorTrendData.period_type == period_type)

    if color_family:
        q = q.filter(ColorTrendData.color_family == color_family)
    if data_source:
        q = q.filter(ColorTrendData.data_source == data_source)
    if start_date:
        q = q.filter(ColorTrendData.period_date >= start_date)
    if end_date:
        q = q.filter(ColorTrendData.period_date <= end_date)

    items = q.order_by(ColorTrendData.period_date.desc()).limit(365).all()
    return [
        {
            "color_family": item.color_family,
            "data_source": item.data_source,
            "period_date": item.period_date.isoformat() if item.period_date else None,
            "period_type": item.period_type,
            "raw_value": float(item.raw_value) if item.raw_value else 0,
            "normalized_score": float(item.normalized_score) if item.normalized_score else None,
        }
        for item in items
    ]


def get_trend_prediction(
    db: Session,
    horizon: int = 30,
    top_n: int = 5,
) -> list[dict]:
    """30天趋势预测（P4 接入 TFT 服务）"""
    # TODO: P4 接入 TFT 预测服务
    # 目前返回基于历史趋势的简单移动平均预测
    overview = get_trend_overview(db)
    return [
        {
            "color_family": item["color_family"],
            "score": round(item["current_score"] * (1.1 if item["trend"] == "rising" else 0.9 if item["trend"] == "falling" else 1.0), 2),
            "trend": item["trend"],
            "method": "sma_placeholder",  # 标记为占位算法
        }
        for item in overview[:top_n]
    ]


def write_trend_data(
    db: Session,
    color_family: str,
    data_source: str,
    period_date: date,
    raw_value: float,
    normalized_score: Optional[float] = None,
    period_type: str = "weekly",
) -> ColorTrendData:
    """写入趋势数据（幂等：同一天同一维度覆盖）"""
    existing = (
        db.query(ColorTrendData)
        .filter(
            ColorTrendData.color_family == color_family,
            ColorTrendData.data_source == data_source,
            ColorTrendData.period_date == period_date,
            ColorTrendData.period_type == period_type,
        )
        .first()
    )

    if existing:
        existing.raw_value = raw_value
        existing.normalized_score = normalized_score
    else:
        existing = ColorTrendData(
            color_family=color_family,
            data_source=data_source,
            period_date=period_date,
            period_type=period_type,
            raw_value=raw_value,
            normalized_score=normalized_score,
        )
        db.add(existing)

    db.commit()
    return existing


def normalize_scores(db: Session, period_date: date, data_source: str, period_type: str = "weekly"):
    """对某天的原始值做 Min-Max 归一化到 0-100"""
    rows = (
        db.query(ColorTrendData)
        .filter(
            ColorTrendData.period_date == period_date,
            ColorTrendData.data_source == data_source,
            ColorTrendData.period_type == period_type,
        )
        .all()
    )

    if not rows:
        return

    values = [float(r.raw_value) for r in rows]
    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val if max_val > min_val else 1

    for row in rows:
        score = (float(row.raw_value) - min_val) / range_val * 100
        row.normalized_score = round(score, 2)

    db.commit()
