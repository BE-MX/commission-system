"""智能获客联系人完善与企业研究服务。"""

from typing import Any

from sqlalchemy.orm import Session

from app.sales_automation.identity import normalize_source_url
from app.sales_automation.models import LeadContact, ResearchFact, ResearchRun
from app.sales_automation.service import SalesAutomationError, _data, _datetime, _hash, _now, get_lead


def upsert_contacts(db: Session, company_id: int, contacts: list[Any], actor_id: int | None = None) -> list[LeadContact]:
    get_lead(db, company_id, for_update=True)
    rows: list[LeadContact] = []
    for raw in contacts:
        data = _data(raw)
        email = (data.get("email") or "").strip()
        email_normalized = email.lower() or None
        name = (data.get("name") or "").strip() or None
        role = (data.get("role") or "").strip() or None
        if not email_normalized and not name:
            raise SalesAutomationError("联系人至少需要 email 或 name")
        identity = email_normalized or f"{(name or '').lower()}|{(role or '').lower()}"
        identity_key = _hash(identity)
        source_url = normalize_source_url(data.get("source_url"))
        row = db.query(LeadContact).filter(
            LeadContact.company_id == company_id,
            LeadContact.identity_key == identity_key,
        ).first()
        is_new = row is None
        if row is None:
            row = LeadContact(company_id=company_id, identity_key=identity_key, created_by=actor_id)
            db.add(row)
        row.name = name or row.name
        row.role = role or row.role
        row.email = email or row.email
        row.email_normalized = email_normalized or row.email_normalized
        if "email_status" in data:
            requested_status = data.get("email_status")
            if requested_status is None:
                raise SalesAutomationError("email_status 不能为null")
            if requested_status != "unknown" and (not email_normalized or not data.get("verified_at")):
                raise SalesAutomationError("已验证邮箱状态必须同时提供 email 和 verified_at")
            row.email_status = requested_status
            row.verified_at = (
                None if requested_status == "unknown"
                else _datetime(data["verified_at"], "verified_at")
            )
        row.source_provider = data.get("source_provider") or "agent"
        row.source_url = source_url
        row.captured_at = _datetime(data.get("captured_at"), "captured_at")
        row.confidence = data.get("confidence")
        row.updated_by = actor_id
        if is_new:
            db.flush()
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def upsert_research(db: Session, company_id: int, payload: Any, actor_id: int | None = None) -> ResearchRun:
    get_lead(db, company_id, for_update=True)
    data = _data(payload)
    facts = data.get("facts") or []
    if not facts:
        raise SalesAutomationError("facts 至少需要一条证据")
    for fact in facts:
        fact_data = _data(fact)
        for field in ("claim", "source_url", "captured_at", "confidence"):
            if fact_data.get(field) is None or fact_data.get(field) == "":
                raise SalesAutomationError(f"研究事实 {field} 必填")
        confidence = float(fact_data["confidence"])
        if not 0 <= confidence <= 1:
            raise SalesAutomationError("confidence 必须在0到1之间")

    idem = data.get("idempotency_key")
    if idem:
        existing = db.query(ResearchRun).filter(
            ResearchRun.company_id == company_id,
            ResearchRun.idempotency_key == idem,
        ).first()
        if existing:
            return existing
    run = ResearchRun(
        company_id=company_id,
        status="completed",
        summary=data.get("summary") or "",
        outreach_angles=data.get("outreach_angles") or [],
        risks=data.get("risks") or [],
        provider=data.get("provider") or "agent",
        model=data.get("model"),
        idempotency_key=idem,
        started_at=_now(),
        finished_at=_now(),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(run)
    db.flush()
    for position, raw_fact in enumerate(facts):
        fact = _data(raw_fact)
        claim = fact["claim"].strip()
        source_url = normalize_source_url(fact["source_url"])
        db.add(ResearchFact(
            run_id=run.id,
            fact_type=fact.get("fact_type") or "general",
            claim=claim,
            fact_hash=_hash(claim.lower()),
            source_url=source_url,
            source_url_hash=_hash(source_url),
            captured_at=_datetime(fact["captured_at"], "captured_at"),
            confidence=float(fact["confidence"]),
            sort_order=position,
            created_by=actor_id,
            updated_by=actor_id,
        ))
    db.commit()
    db.refresh(run)
    return run


def get_latest_research(db: Session, company_id: int) -> tuple[ResearchRun | None, list[ResearchFact]]:
    run = db.query(ResearchRun).filter(
        ResearchRun.company_id == company_id,
        ResearchRun.deleted_at.is_(None),
    ).order_by(ResearchRun.created_at.desc()).first()
    if run is None:
        return None, []
    facts = db.query(ResearchFact).filter(
        ResearchFact.run_id == run.id,
        ResearchFact.deleted_at.is_(None),
    ).order_by(ResearchFact.sort_order.asc()).all()
    return run, facts
