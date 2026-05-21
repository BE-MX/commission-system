"""方舟洞见 — 行业情报速览报告生成"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.insight.ai_helpers import _safe_json_parse, _try_invoke_ai
from app.insight.models import InsightItem, InsightReport
from app.insight.schemas import IntelligenceReportGenerate

logger = logging.getLogger("insight")

# ── 模板环境 ──────────────────────────────────────────
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# ── 报告 HTML 存储目录 ─────────────────────────────────
REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "insight" / "intelligence_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ── 选材 ──────────────────────────────────────────────
def _select_items(db: Session, config: IntelligenceReportGenerate) -> list[InsightItem]:
    """根据配置选取情报条目。"""
    if config.mode == "manual_select" and config.item_ids:
        items = db.query(InsightItem).filter(InsightItem.id.in_(config.item_ids)).all()
        return items

    # 规则选材
    query = db.query(InsightItem).filter(InsightItem.status == "active")

    # 日期范围
    if config.date_range_start:
        query = query.filter(InsightItem.collected_at >= datetime.combine(config.date_range_start, datetime.min.time()))
    if config.date_range_end:
        query = query.filter(InsightItem.collected_at <= datetime.combine(config.date_range_end, datetime.max.time()))

    # 可信度
    if config.min_credibility_score:
        query = query.filter(InsightItem.credibility_score >= config.min_credibility_score)

    # 信源类型
    if config.source_types:
        query = query.filter(InsightItem.source_type.in_(config.source_types))

    # 条目类型
    if config.item_types:
        query = query.filter(InsightItem.item_type.in_(config.item_types))

    # 仅精选
    if config.include_featured_only:
        query = query.filter(InsightItem.is_featured == True)

    # 竞品过滤
    if config.competitor_filter:
        query = query.filter(InsightItem.related_competitor.in_(config.competitor_filter))

    # 排序: 高可信度 + 高优先级优先
    query = query.order_by(
        desc(InsightItem.credibility_score),
        desc(InsightItem.collected_at),
    )

    if config.max_items_total:
        query = query.limit(config.max_items_total)

    return query.all()


# ── AI 生成 ─────────────────────────────────────────────
def _build_generation_prompt(items: list[InsightItem], config: IntelligenceReportGenerate) -> str:
    """构建 AI 生成 prompt。"""
    # 按信源类型分组
    items_by_source: dict[str, list[dict]] = {}
    for item in items:
        st = item.source_type or "unknown"
        items_by_source.setdefault(st, []).append({
            "id": item.id,
            "title": item.title or "",
            "content": (item.content_md or "")[:300],
            "source_type": item.source_type,
            "credibility": item.credibility_label,
            "url": item.original_url or "",
            "competitor": item.related_competitor or "",
            "tags": item.tags or [],
        })

    items_json = json.dumps(items_by_source, ensure_ascii=False, indent=2)

    focus = config.content_focus or ["竞品动态", "发色趋势", "市场政策"]
    depth_map = {"brief": "500字以内快报", "standard": "1000-1500字标准报告", "deep": "2000字以上深度报告"}
    depth_desc = depth_map.get(config.report_depth, "标准报告")

    prompt = f"""你是一位发制品行业情报分析师，服务于莱莎发制品公司。
请根据以下情报条目，生成一份结构化行业情报速览报告。

## 生成要求

- 报告深度: {depth_desc}
- 内容聚焦: {', '.join(focus)}
- 输出语言: {'中文' if config.output_language == 'zh-CN' else 'English'}

## 情报条目 (按信源类型分组)

{items_json}

## 输出格式 (严格 JSON)

```json
{{
  "tldr": [
    {{"priority": "high", "text": "核心结论1（20字以内）", "from": "来源部分名"}}
  ],
  "market_trends": [
    {{"title": "信号标题", "fact": "事实描述", "source_url": "来源链接", "credibility": "verified/plausible"}}
  ],
  "brand_movements": [
    {{"brand": "品牌名", "title": "动态标题", "fact": "事实描述", "source_url": "来源链接"}}
  ],
  "social_dynamics": [
    {{"account": "账号名", "platform": "平台", "content": "内容摘要", "engagement": "互动数据"}}
  ],
  "competitor_info": [
    {{"competitor": "竞品名", "type": "price_change/new_product/out_of_stock", "detail": "详情"}}
  ],
  "leshine_suggestions": [
    {{
      "scenario": "业务场景",
      "signal_source": "信号来源",
      "strategy": "策略方向",
      "script": "话术示例(英文)",
      "customer_level": "A/B/C/通用"
    }}
  ]
}}
```

## 内容规则

1. **结论先行**: TL;DR 不超过5条，按业务影响排序
2. **事实优先**: 每条信号必须有对应的情报条目支撑
3. **莱莎建议**: 结合 B2B 跨境贸易场景，输出可执行话术
4. **禁止编造**: 不在情报条目中的信息不得出现在报告中
5. **推断标注**: 推断性内容用「建议」「可考虑」等措辞
"""
    return prompt


def _generate_with_ai(db: Session, items: list[InsightItem], config: IntelligenceReportGenerate) -> dict:
    """调用 AI 生成报告内容。"""
    if not items:
        logger.warning("No items selected for intelligence report")
        return _empty_report_data()

    prompt = _build_generation_prompt(items, config)
    text = _try_invoke_ai(db, "insight_intelligence_generate", prompt)
    parsed = _safe_json_parse(text or "") if text else None

    if not parsed or not isinstance(parsed, dict):
        logger.warning("AI intelligence generation failed, using fallback")
        return _fallback_report_data(items)

    return parsed


def _empty_report_data() -> dict:
    return {
        "tldr": [],
        "market_trends": [],
        "brand_movements": [],
        "social_dynamics": [],
        "competitor_info": [],
        "leshine_suggestions": [],
    }


def _fallback_report_data(items: list[InsightItem]) -> dict:
    """AI 失败时的降级输出：直接列出条目要点。"""
    tldr = []
    for item in items[:5]:
        tldr.append({
            "priority": "medium",
            "text": (item.title or "")[:30],
            "from": item.source_type or "未知",
        })

    return {
        "tldr": tldr,
        "market_trends": [],
        "brand_movements": [],
        "social_dynamics": [],
        "competitor_info": [],
        "leshine_suggestions": [],
    }


# ── HTML 渲染 ───────────────────────────────────────────
def _render_html(report_date: date, data: dict, config: IntelligenceReportGenerate, item_count: int) -> str:
    """渲染完整 HTML 报告。"""
    template = _jinja_env.get_template("intelligence_overview.html")
    return template.render(
        report_date=report_date,
        data=data,
        config=config.model_dump(),
        item_count=item_count,
        generated_at=datetime.utcnow().isoformat(),
    )


# ── 报告管理 ────────────────────────────────────────────
def generate_intelligence_report(
    db: Session,
    config: IntelligenceReportGenerate,
    user_id: Optional[int] = None,
) -> InsightReport:
    """生成行业情报速览报告 — 核心入口。"""
    report_date = date.today()
    report_title = config.report_title or f"行业情报速览 {report_date}"

    # 创建 pending 记录
    report = InsightReport(
        report_type="intelligence_overview",
        report_date=report_date,
        title=report_title,
        status="generating",
        date_range_start=config.date_range_start,
        date_range_end=config.date_range_end,
        config_snapshot=config.model_dump(),
        trigger_type="manual",
        created_by=user_id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    try:
        # 选材
        items = _select_items(db, config)
        report.item_ids = [item.id for item in items]
        item_count = len(items)

        # AI 生成
        data = _generate_with_ai(db, items, config)

        # 渲染 HTML
        html_content = _render_html(report_date, data, config, item_count)

        # 保存 HTML 文件
        file_name = f"intelligence_{report.id}_{report_date.isoformat()}.html"
        file_path = REPORT_DIR / file_name
        file_path.write_text(html_content, encoding="utf-8")

        # 更新报告记录
        report.status = "completed"
        report.file_path = str(file_path)
        report.html_content = html_content[:50000]  # 数据库存前 50KB
        report.source_data = data
        report.item_count = item_count
        db.commit()
        db.refresh(report)

        logger.info("Intelligence report generated id=%s items=%s", report.id, item_count)
        return report

    except Exception as e:
        logger.exception("Intelligence report generation failed")
        report.status = "failed"
        report.error_msg = str(e)[:500]
        db.commit()
        raise


def list_intelligence_reports(
    db: Session,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """速览报告卡片列表。"""
    query = db.query(InsightReport).filter(InsightReport.report_type == "intelligence_overview")
    if status:
        query = query.filter(InsightReport.status == status)

    total = query.count()
    rows = (
        query.order_by(desc(InsightReport.is_pinned), desc(InsightReport.report_date), desc(InsightReport.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "report_title": r.title,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "date_range_start": r.date_range_start.isoformat() if r.date_range_start else None,
            "date_range_end": r.date_range_end.isoformat() if r.date_range_end else None,
            "item_count": r.item_count or 0,
            "trigger_type": r.trigger_type,
            "status": r.status,
            "is_pinned": bool(r.is_pinned),
            "file_path": r.file_path,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"total": total, "items": items, "page": page, "page_size": page_size}


def get_intelligence_report_html(db: Session, report_id: int) -> str:
    """获取报告 HTML 内容。"""
    report = db.query(InsightReport).filter(
        InsightReport.id == report_id,
        InsightReport.report_type == "intelligence_overview",
    ).first()
    if not report:
        raise ValueError("报告不存在")

    # 优先从文件读取
    if report.file_path:
        p = Path(report.file_path)
        if p.is_file():
            return p.read_text(encoding="utf-8")

    # 其次从数据库读取
    if report.html_content:
        return report.html_content

    raise ValueError("报告内容为空")


def delete_intelligence_report(db: Session, report_id: int) -> None:
    report = db.query(InsightReport).filter(
        InsightReport.id == report_id,
        InsightReport.report_type == "intelligence_overview",
    ).first()
    if not report:
        raise ValueError("报告不存在")

    # 删除文件
    if report.file_path:
        p = Path(report.file_path)
        if p.is_file():
            p.unlink()

    db.delete(report)
    db.commit()


def pin_report(db: Session, report_id: int, is_pinned: bool) -> InsightReport:
    report = db.query(InsightReport).filter(
        InsightReport.id == report_id,
        InsightReport.report_type == "intelligence_overview",
    ).first()
    if not report:
        raise ValueError("报告不存在")
    report.is_pinned = is_pinned
    db.commit()
    db.refresh(report)
    return report
