"""洞见生成：确定性预聚合、模型结论校验、数字填槽与完整快照替换。"""
import json
import logging
import re
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ai.service import chat
from app.auth.models import ArkUser
from app.core.database import SessionLocal
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup import attachment_service, config_service, dict_service, insight_evidence, insight_queue, stats_service, visibility
from app.domestic_followup.constants import DICT_CATEGORY, DICT_CHANNEL, DICT_OBSTACLE, DICT_RESULT, DICT_STATE_CHANGE
from app.domestic_followup.insight_models import DomesticFollowupInsight, DomesticFollowupInsightSnapshot
from app.domestic_followup.insight_schemas import InsightAIOut, PublicInsightsOut
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem

logger = logging.getLogger("commission")
INSIGHT_PRESET = "domestic_followup_insights"
PERSONAL_CATEGORIES = ("deal", "cold", "rhythm", "method")
COMPANY_CATEGORIES = ("common", "single", "practice", "frequency")
SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def _latest_done(db: Session, scope: str, user_id: int | None) -> DomesticFollowupInsightSnapshot | None:
    query = db.query(DomesticFollowupInsightSnapshot).filter(
        DomesticFollowupInsightSnapshot.scope == scope,
        DomesticFollowupInsightSnapshot.status == "done",
    )
    if user_id is None:
        query = query.filter(DomesticFollowupInsightSnapshot.user_id.is_(None))
    else:
        query = query.filter(DomesticFollowupInsightSnapshot.user_id == user_id)
    return query.order_by(DomesticFollowupInsightSnapshot.id.desc()).first()


def _record_context(db: Session, start: date, end: date, author_id: int | None = None) -> tuple[list, list[dict]]:
    query = (db.query(DomesticFollowup, DomesticCustomer)
             .join(DomesticCustomer, DomesticCustomer.id == DomesticFollowup.customer_id)
             .filter(DomesticFollowup.status == "confirmed", DomesticFollowup.followup_date >= start,
                     DomesticFollowup.followup_date <= end))
    if author_id:
        query = query.filter(DomesticFollowup.author_user_id == author_id)
    rows = query.order_by(DomesticFollowup.followup_date.desc(), DomesticFollowup.id.desc()).limit(500).all()
    followup_ids = [record.id for record, _ in rows]
    items = (db.query(DomesticFollowupItem)
             .filter(DomesticFollowupItem.followup_id.in_(followup_ids),
                     DomesticFollowupItem.status != "withdrawn").all()) if followup_ids else []
    grouped = defaultdict(list)
    for item in items:
        grouped[item.followup_id].append({"kind": item.kind, "text": item.text, "category": item.category,
                                          "severity": item.severity})
    context = [{
        "id": record.id, "version": record.version, "customer_id": customer.id, "shop_name": customer.shop_name,
        "customer_level": customer.customer_level, "author_user_id": record.author_user_id,
        "date": record.followup_date.isoformat(), "channel": record.channel, "summary": record.summary,
        "items": grouped.get(record.id, []), "result_code": record.result_code,
        "obstacles": record.obstacles or [], "state_changes": record.state_changes or [],
        "next_date": record.next_date.isoformat() if record.next_date else None,
        "effective_progress": bool(record.effective_progress),
    } for record, customer in rows]
    return rows, context


def _personal_numbers(db: Session, user_id: int, today: date) -> dict:
    config = config_service.get_config(db)
    entries = stats_service.responsible_customers(db, today, today - timedelta(days=31))
    user = db.get(ArkUser, user_id)
    if user is None:
        raise LookupError("业务员不存在")
    period = {"start": today - timedelta(days=29), "end": today, "today": today,
              "previous_start": today - timedelta(days=59), "previous_end": today - timedelta(days=30)}
    person = stats_service._person(db, user, period, config, entries)
    kpis = person["kpis"]
    numbers = {
        "count": kpis["count"], "reach": kpis["reach"], "overdue": kpis["overdue"],
        "owner_customers": kpis["owner_customers"], "previous_count": kpis["previous_count"],
        "effective_percent": round((kpis["effective_rate"] or 0) * 100),
        "next_step_percent": round((person["quality"]["next_step"]["value"] or 0) * 100),
        "commitment_percent": round((person["quality"]["commitment"]["value"] or 0) * 100),
        "effective_progress_percent": round((person["quality"]["effective_progress"]["value"] or 0) * 100),
        "average_recontact_days": person["average_recontact_days"] or 0,
        "average_snooze": person["average_snooze"],
    }
    for coverage in person["coverage"]:
        key = coverage["level"][0].lower()
        numbers[f"{key}_level_total"] = coverage["total"]
        numbers[f"{key}_level_overdue"] = coverage["total"] - coverage["on_track"]
        numbers[f"{key}_level_frequency"] = coverage["frequency_days"]
    return numbers


def _themes(context: list[dict]) -> dict[str, dict]:
    themes = {}
    def touch(key, label, row):
        theme = themes.setdefault(key, {"theme_key": key, "label": label, "customer_ids": set(), "record_ids": []})
        theme["customer_ids"].add(row["customer_id"])
        if row["id"] not in theme["record_ids"]:
            theme["record_ids"].append(row["id"])
    for row in context:
        for value in row["obstacles"]:
            touch(f"obstacle:{value}", f"障碍：{value}", row)
        for value in row["state_changes"]:
            touch(f"state:{value}", f"状态变化：{value}", row)
        for item in row["items"]:
            if item.get("kind") in ("issue", "suggestion") and item.get("category"):
                touch(f"category:{item['category']}", f"异常意见：{item['category']}", row)
    evidence = {row["id"]: row for row in context}
    for theme in themes.values():
        theme["customer_count"] = len(theme.pop("customer_ids"))
        theme["evidence"] = [evidence[record_id] for record_id in theme["record_ids"][:5]]
    return themes


def _fill(text: str | None, numbers: dict) -> str | None:
    if text is None:
        return None
    literal = SLOT.sub("", text)
    if re.search(r"[0-9一二三四五六七八九十百千万两]+(?:[.,][0-9]+)?\s*(?:[%％]|家|次|天|条|位|人|日)", literal):
        raise ValueError("统计数字必须使用后端槽位")
    def replace(match):
        key = match.group(1)
        if key not in numbers:
            raise ValueError(f"未知数字槽位：{key}")
        return str(numbers[key])
    return SLOT.sub(replace, text).strip()


def _public_summaries(db, themes, context, won_ids):
    """A separate prompt containing aggregates only; raw company prose is never 'redacted' for sales."""
    values = dict_service.load_values(db)
    known = {f"{prefix}:{value}" for prefix, dictionary in (
        ("obstacle", DICT_OBSTACLE), ("state", DICT_STATE_CHANGE), ("category", DICT_CATEGORY),
    ) for value in values[dictionary]}
    aggregates = [{"theme_key": key, "label": theme["label"], "customer_count": theme["customer_count"]}
                  for key, theme in themes.items() if theme["customer_count"] >= 3 and key in known]
    if len(won_ids) >= 10:
        won_records = [row for row in context if row["customer_id"] in won_ids]
        aggregates.append({"theme_key": "practice", "label": "成交客户跟进样本", "customer_count": len(won_ids),
                           "record_count": len(won_records),
                           "next_step_count": sum(bool(row["next_date"]) for row in won_records)})
    if not aggregates:
        return {}
    result = chat(db=db, preset_name=INSIGHT_PRESET, caller_module="domestic_followup_insights_public",
                  snapshot_mode="metadata", timeout_sec=180, enforce_total_timeout=True,
                  messages=[{"role": "user", "content": json.dumps({
                      "aggregates": aggregates,
                      "rules": "只根据匿名聚合给公司建议，不猜客户身份，不引用原话，不推断因果。统计数字只用 {customer_count} 等输入字段槽位。只返回 JSON {items:[{theme_key,title,body,suggested_action}]}，没有依据可返回空数组。",
                  }, ensure_ascii=False)}])
    parsed = PublicInsightsOut.model_validate(attachment_service.parse_json(result.get("content", "")))
    allowed = {row["theme_key"]: row for row in aggregates}
    summaries = {}
    for item in parsed.items:
        if item.theme_key not in allowed:
            continue
        numbers = {key: value for key, value in allowed[item.theme_key].items() if isinstance(value, int)}
        summaries[item.theme_key] = {key: _fill(getattr(item, key), numbers)
                                     for key in ("title", "body", "suggested_action")}
    return summaries


def _highlights(scope: str, numbers: dict, themes: dict) -> list[dict]:
    if scope == "personal":
        return [
            {"key": "overdue", "label": "客户覆盖", "title": f"{numbers['overdue']} 家客户应跟未跟",
             "body": "先到个人数据查看名单，再安排下一次跟进。"},
            {"key": "count", "label": "跟进节奏", "title": f"近 30 天记录 {numbers['count']} 次",
             "body": f"有效沟通率 {numbers['effective_percent']}%，约定兑现 {numbers['commitment_percent']}%。"},
            {"key": "next_step", "label": "跟进方式", "title": f"留下一步 {numbers['next_step_percent']}%",
             "body": "有效沟通结束前，明确下一次联系时间与动作。"},
        ]
    common = sorted(themes.values(), key=lambda row: row["customer_count"], reverse=True)
    return [
        {"key": "common", "label": "共性问题", "title": f"{common[0]['customer_count']} 家客户：{common[0]['label']}",
         "body": "主题家数由后端按记录聚合，可进入公司层建议核对。"} if common else
        {"key": "common", "label": "共性问题", "title": "本周期没有突出共性", "body": "证据不足时不凑建议。"},
        {"key": "practice", "label": "成交样本", "title": f"{numbers['won_customer_count']} 家成交客户可复盘",
         "body": "少于 10 家时不生成因果式经验结论。"},
        {"key": "evidence", "label": "证据边界", "title": "每条建议均可回查原始记录",
         "body": "记录失效或超出权限后，对应证据和建议自动隐藏。"},
    ]


def _copy_carried_items(db: Session, snapshot: DomesticFollowupInsightSnapshot, categories: tuple[str, ...]) -> None:
    previous = db.query(DomesticFollowupInsightSnapshot).filter(
        DomesticFollowupInsightSnapshot.scope == snapshot.scope,
        DomesticFollowupInsightSnapshot.user_id == snapshot.user_id,
        DomesticFollowupInsightSnapshot.status == "done", DomesticFollowupInsightSnapshot.id < snapshot.id,
    ).order_by(DomesticFollowupInsightSnapshot.id.desc()).first()
    if previous is None:
        return
    rows = db.query(DomesticFollowupInsight).filter(
        DomesticFollowupInsight.snapshot_id == previous.id,
        DomesticFollowupInsight.category.not_in(categories)).all()
    for row in rows:
        db.add(DomesticFollowupInsight(
            snapshot_id=snapshot.id, category=row.category, customer_id=row.customer_id, theme_key=row.theme_key,
            title=row.title, body=row.body, suggested_action=row.suggested_action, suggested_date=row.suggested_date,
            signals=row.signals, evidence_followup_ids=row.evidence_followup_ids, numeric_values=row.numeric_values,
            sample_size=row.sample_size, evidence_versions=row.evidence_versions,
            public_summary=row.public_summary, sample_customer_ids=row.sample_customer_ids,
            source_insight_id=row.source_insight_id or row.id, feedbacks={},
            created_at=row.created_at,
        ))


def _generate(db: Session, snapshot: DomesticFollowupInsightSnapshot, token: str) -> bool:
    categories = PERSONAL_CATEGORIES if snapshot.scope == "personal" else COMPANY_CATEGORIES
    if snapshot.trigger == "daily":
        categories = ("deal", "cold")
    rows, context = _record_context(db, snapshot.period_start, snapshot.period_end, snapshot.user_id)
    themes = _themes(context) if snapshot.scope == "company" else {}
    won_ids = insight_evidence.won_customer_ids(db, {row["customer_id"] for row in context}, snapshot.period_end)
    numbers = (_personal_numbers(db, snapshot.user_id, snapshot.period_end)
               if snapshot.scope == "personal" else {"won_customer_count": len(won_ids)})
    values = dict_service.load_values(db)
    dictionaries = {key: values[key] for key in (DICT_RESULT, DICT_OBSTACLE, DICT_STATE_CHANGE, DICT_CATEGORY, DICT_CHANNEL)}
    instructions = {
        "personal": "只输出 deal/cold/rhythm/method 四类。deal/cold 必须给 customer_id、suggested_action、suggested_date；rhythm/method 针对本人行为，不评分、不排名。",
        "company": "只输出 common/single/practice/frequency。common 必须使用输入主题的 theme_key，数字用 {customer_count}；practice/frequency 数字用 {won_customer_count}，样本不足时省略。",
    }
    payload = {
        "categories": list(categories), "dictionaries": dictionaries, "numbers": numbers,
        "themes": list(themes.values()), "records": context,
        "won_customer_ids": sorted(won_ids) if snapshot.scope == "company" else [],
        "rules": [
            "只根据输入记录输出 JSON，不要输出 Markdown。每条必须有 1~5 个 evidence_followup_ids。",
            "次数、天数、占比和家数只能写输入 numbers 里已有的 {槽位}；不要编造数字。证据不足就省略该条。",
            instructions[snapshot.scope],
            "输出结构：{items:[{category,customer_id,theme_key,title,body,suggested_action,suggested_date,signals,evidence_followup_ids}]}",
        ],
    }
    result = chat(db=db, preset_name=INSIGHT_PRESET,
                  messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                  caller_module="domestic_followup_insights", caller_user_id=snapshot.user_id,
                  snapshot_mode="metadata", timeout_sec=180, enforce_total_timeout=True)
    parsed = InsightAIOut.model_validate(attachment_service.parse_json(result.get("content", "")))
    allowed = {row["id"]: row for row in context}
    public_summaries = _public_summaries(db, themes, context, won_ids) if snapshot.scope == "company" else {}
    created = []
    for item in parsed.items:
        if item.category not in categories:
            continue
        evidence_ids = [record_id for record_id in dict.fromkeys(item.evidence_followup_ids) if record_id in allowed]
        if not evidence_ids:
            continue
        evidence_rows = [allowed[record_id] for record_id in evidence_ids]
        if snapshot.scope == "personal" and any(row["author_user_id"] != snapshot.user_id for row in evidence_rows):
            continue
        if item.category in ("deal", "cold", "single"):
            if not item.customer_id or any(row["customer_id"] != item.customer_id for row in evidence_rows):
                continue
        if item.category in ("deal", "cold") and (
                not item.suggested_action or not item.suggested_action.strip() or not item.suggested_date):
            continue
        item_numbers = dict(numbers)
        sample_size = len({row["customer_id"] for row in evidence_rows})
        if item.category == "common":
            theme = themes.get(item.theme_key or "")
            if theme is None or any(record_id not in theme["record_ids"] for record_id in evidence_ids):
                continue
            item_numbers["customer_count"] = theme["customer_count"]
            sample_size = theme["customer_count"]
        elif item.category in ("practice", "frequency"):
            sample_size = numbers["won_customer_count"]
            if sample_size < 10 or any(row["customer_id"] not in won_ids for row in evidence_rows):
                continue
        try:
            title = _fill(item.title, item_numbers)
            body = _fill(item.body, item_numbers)
            action = _fill(item.suggested_action, item_numbers)
            signals = [_fill(signal, item_numbers) for signal in item.signals]
        except ValueError:
            logger.warning("followup insight skipped: invalid numeric slot")
            print("[domestic_followup] insight skipped: invalid numeric slot", flush=True)
            continue
        used_numbers = {key for text in (item.title, item.body, item.suggested_action)
                        for key in SLOT.findall(text or "")}
        created.append(DomesticFollowupInsight(
            snapshot_id=snapshot.id, category=item.category,
            customer_id=item.customer_id if item.category in ("deal", "cold", "single") else None,
            theme_key=item.theme_key if item.category == "common" else None, title=title, body=body, suggested_action=action,
            suggested_date=item.suggested_date if item.category in ("deal", "cold") else None,
            signals=signals, evidence_followup_ids=evidence_ids,
            evidence_versions={str(record_id): allowed[record_id]["version"] for record_id in evidence_ids},
            public_summary=public_summaries.get("practice" if item.category == "practice" else item.theme_key)
                           if item.category in ("common", "practice") else None,
            sample_customer_ids=sorted(won_ids) if item.category in ("practice", "frequency") else None,
            numeric_values={key: item_numbers[key] for key in used_numbers},
            sample_size=sample_size,
        ))
    updated = db.execute(update(DomesticFollowupInsightSnapshot).where(
        DomesticFollowupInsightSnapshot.id == snapshot.id, DomesticFollowupInsightSnapshot.status == "running",
        DomesticFollowupInsightSnapshot.run_token == token,
    ).values(status="done", generated_at=beijing_now(), error=None, record_count=len(context), payload={
        "highlights": _highlights(snapshot.scope, numbers, themes),
        "empty_sections": [key for key in categories if not any(row.category == key for row in created)],
    }).execution_options(synchronize_session=False))
    if not updated.rowcount:
        db.rollback()
        return False
    db.query(DomesticFollowupInsight).filter(DomesticFollowupInsight.snapshot_id == snapshot.id).delete()
    db.add_all(created)
    if snapshot.trigger == "daily":
        _copy_carried_items(db, snapshot, categories)
    db.commit()
    return True


def generate_snapshot(db: Session, snapshot_id: int) -> bool:
    if not config_service.get_config(db)["insight_generation_enabled"]:
        return False
    token = insight_queue.claim(db, snapshot_id)
    if not token:
        return False
    snapshot = db.get(DomesticFollowupInsightSnapshot, snapshot_id)
    if snapshot is None or snapshot.status != "running":
        return False
    try:
        return _generate(db, snapshot, token)
    except Exception as exc:  # noqa: BLE001 — 保留上一份 done，当前只标记失败
        db.rollback()
        logger.warning("followup insight generation failed snapshot=%s: %s", snapshot_id, type(exc).__name__)
        print(f"[domestic_followup] insight generation failed snapshot={snapshot_id}: {type(exc).__name__}", flush=True)
        db.execute(update(DomesticFollowupInsightSnapshot).where(
            DomesticFollowupInsightSnapshot.id == snapshot_id, DomesticFollowupInsightSnapshot.status == "running",
            DomesticFollowupInsightSnapshot.run_token == token,
        ).values(status="failed", error=type(exc).__name__[:255]).execution_options(synchronize_session=False))
        db.commit()
        return False


def run_snapshots(snapshot_ids: list[int]) -> None:
    with SessionLocal() as db:
        for snapshot_id in snapshot_ids:
            generate_snapshot(db, snapshot_id)


def generate_scheduled(weekly: bool = False) -> dict:
    today = beijing_today()
    with SessionLocal() as db:
        config = config_service.get_config(db)
        if not config["insight_generation_enabled"]:
            return {"generated": 0, "disabled": True}
        entries = stats_service.responsible_customers(db, today, today - timedelta(days=1))
        roster = stats_service._roster(db, config, entries)
        insight_queue.lock_admission(db)
        insight_queue.recover_stale(db)
        snapshots = []
        trigger = "weekly" if weekly else "daily"
        end = today - timedelta(days=1) if weekly else today
        def already_generated(scope, user_id):
            return db.query(DomesticFollowupInsightSnapshot.id).filter(
                DomesticFollowupInsightSnapshot.scope == scope, DomesticFollowupInsightSnapshot.user_id == user_id,
                DomesticFollowupInsightSnapshot.trigger == trigger, DomesticFollowupInsightSnapshot.period_end == end,
                DomesticFollowupInsightSnapshot.status == "done",
            ).with_for_update().first() is not None
        for user in roster:
            if insight_queue.active(db, "personal", user.id) or already_generated("personal", user.id):
                continue
            snapshots.append(DomesticFollowupInsightSnapshot(
                scope="personal", user_id=user.id, status="queued", trigger=trigger,
                period_start=end - timedelta(days=59), period_end=end,
            ))
        if weekly and not insight_queue.active(db, "company", None) and not already_generated("company", None):
            snapshots.append(DomesticFollowupInsightSnapshot(
                scope="company", user_id=None, status="queued", trigger=trigger,
                period_start=end - timedelta(days=59), period_end=end,
            ))
        db.add_all(snapshots)
        db.commit()
        ids = [snapshot.id for snapshot in snapshots]
    from app.domestic_followup import insight_jobs
    insight_jobs.submit_snapshots(ids)
    return {"queued": len(ids), "disabled": False}


def pending_snapshots() -> list[int]:
    with SessionLocal() as db:
        insight_queue.recover_stale(db)
        if not config_service.get_config(db)["insight_generation_enabled"]:
            db.commit()
            return []
        ids = [row[0] for row in db.query(DomesticFollowupInsightSnapshot.id).filter(
            DomesticFollowupInsightSnapshot.status == "queued",
        ).order_by(DomesticFollowupInsightSnapshot.id).limit(2).all()]
        db.commit()
        return ids
