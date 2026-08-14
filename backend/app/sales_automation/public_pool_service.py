"""OKKI 公海客户只读审计、分档抽样、Agent 背调与机会投影。"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import secrets
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, inspect, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.insight.models import CustomerOpportunity
from app.insight.customer_profile_service import ingest_opportunity_event
from app.sales_automation.identity import normalize_source_url
from app.sales_automation.models import (
    DealAssessment,
    LeadContact,
    PublicPoolBatch,
    PublicPoolTask,
    ResearchFact,
    ResearchRun,
    ResearchSubject,
)
from app.sales_automation.service import ConflictError, NotFoundError, SalesAutomationError


logger = logging.getLogger("commission.sales_public_pool")

TIERS = ("T1", "T2", "T3")
LEASE_MINUTES = 15
DEFAULT_COOLDOWN_DAYS = 180
REACTIVATION_INACTIVE_DAYS = 60
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com",
    "yahoo.com", "ymail.com", "icloud.com", "me.com", "aol.com", "qq.com",
    "163.com", "126.com", "sina.com", "foxmail.com", "mail.ru", "proton.me",
    "protonmail.com", "gmx.com", "gmx.de", "yandex.com", "yandex.ru",
}
WEBSITE_COLUMNS = ("website", "company_website", "web_site", "homepage", "company_url")
ADDRESS_COLUMNS = ("address",)
LOCALITY_COLUMN_GROUPS = {
    "city": ("city", "city_name"),
    "region": ("region", "region_name", "state", "state_name", "province", "province_name"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _data(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    return dict(value)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _snapshot_hash(snapshot: dict) -> str:
    payload = json.dumps(_json_safe(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash(payload)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            return None
    return None


def email_domain_type(value: Any) -> str:
    email = str(value or "").split(",", 1)[0].strip().lower()
    if "@" not in email:
        return "unknown"
    domain = email.rsplit("@", 1)[1].strip(" .")
    if not domain or "." not in domain:
        return "unknown"
    return "free" if domain in FREE_EMAIL_DOMAINS else "corporate"


def address_search_hint(address: Any, city: Any = None, region: Any = None) -> str | None:
    """Use only explicitly structured locality fields; never parse free-text streets."""
    if not str(address or "").strip():
        return None
    structured = {}
    raw = str(address).strip()
    if raw.startswith("{") and len(raw) <= 2000:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                structured = value
        except (json.JSONDecodeError, TypeError):
            pass
    values = [
        city or structured.get("city") or structured.get("city_name"),
        region or structured.get("region") or structured.get("state") or structured.get("province"),
    ]
    safe = []
    for value in values:
        text_value = " ".join(str(value or "").split()).strip(" .,-")
        if not (2 <= len(text_value) <= 80) or any(char.isdigit() for char in text_value):
            continue
        if any(marker in text_value for marker in ("@", "/", "\\", ":", "+")):
            continue
        safe.append(text_value)
    return ", ".join(dict.fromkeys(safe))[:160] or None


def compute_deal_scores(
    components: dict,
    identity_decision: str,
    unique_source_count: int,
    qualification_coverage: float | None = None,
) -> dict:
    positive = sum(float(components.get(key) or 0) for key in (
        "industry_fit", "pain_switch_trigger", "intent_reactivation",
        "buying_capacity", "reachability", "timing",
    ))
    deal_score = max(0.0, min(100.0, positive - float(components.get("risk_penalty") or 0)))
    business_quality = min(100.0, round(
        float(components.get("industry_fit") or 0) / 25 * 45
        + float(components.get("buying_capacity") or 0) / 15 * 35
        + float(components.get("pain_switch_trigger") or 0) / 20 * 20,
        2,
    ))
    confidence_factor = {
        "confirmed": 1.0,
        "candidate": 0.65,
        "unverifiable": 0.25,
        "rejected": 0.0,
    }[identity_decision]
    priority_score = round(deal_score * confidence_factor, 2)
    if identity_decision == "confirmed" and unique_source_count >= 2:
        evidence_confidence = "high"
    elif identity_decision in {"confirmed", "candidate"} and unique_source_count >= 1:
        evidence_confidence = "medium"
    else:
        evidence_confidence = "low"
    if priority_score >= 75:
        grade, likelihood = "A", "high"
    elif priority_score >= 55:
        grade, likelihood = "B", "medium"
    elif priority_score >= 35:
        grade, likelihood = "C", "medium"
    else:
        grade, likelihood = "D", "low"
    # High model scores cannot outrun evidence coverage. A requires both two
    # independent public sources and at least 60% of weighted qualification dimensions.
    if grade == "A" and (evidence_confidence != "high" or (qualification_coverage is not None and qualification_coverage < 60)):
        grade, likelihood = "B", "medium"
    if grade in {"A", "B"} and qualification_coverage is not None and qualification_coverage < 35:
        grade, likelihood = "C", "medium"
    return {
        "grade": grade,
        "deal_likelihood": likelihood,
        "evidence_confidence": evidence_confidence,
        "business_quality_score": business_quality,
        "deal_score": round(deal_score, 2),
        "priority_score": priority_score,
    }


def _enforce_industry_gate(data: dict, components: dict) -> tuple[dict, dict]:
    """Keep an irrelevant lead from receiving invented commercial value downstream."""
    if data.get("industry_relevance") != "irrelevant":
        return data, components
    gated = dict(data)
    gated["contacts"] = []
    gated["outreach_angles"] = []
    gated["risks"] = []
    gated["pain_points"] = []
    gated["product_fit"] = []
    gated["social_profiles"] = []
    gated["supplier_status"] = "unknown"
    gated["opening_message_en"] = None
    gated["outreach_type"] = "no_outreach"
    gated["research_depth"] = "gate_only"
    profile = dict(gated.get("commercial_profile") or {})
    profile.pop("qualification_dimensions", None)
    profile["positive_signals"] = []
    profile["negative_signals"] = []
    profile["next_validation_questions"] = []
    gated["commercial_profile"] = profile
    zeroed = dict(components)
    for key in (
        "industry_fit", "pain_switch_trigger", "intent_reactivation",
        "buying_capacity", "reachability", "timing",
    ):
        zeroed[key] = 0
    return gated, zeroed


def _normalized_research_submission(payload: Any) -> tuple[dict, dict, str]:
    data = _data(payload)
    components = _data(data.get("score_components") or {})
    data, components = _enforce_industry_gate(data, components)
    data["score_components"] = components
    submission = _json_safe({
        key: value for key, value in data.items()
        if key not in {"agent_id", "lease_token", "idempotency_key"}
    })
    return data, components, _snapshot_hash(submission)


def get_idempotent_completed_research(
    db: Session,
    task_id: int,
    payload: Any,
    actor_id: int,
) -> tuple[PublicPoolTask, DealAssessment] | None:
    """Allow an identical retry after response loss, lease expiry, or a knowledge revision change."""
    raw = _data(payload)
    data, _components, submission_hash = _normalized_research_submission(payload)
    task = get_task(db, task_id)
    if task.status != "completed":
        return None
    existing = db.query(DealAssessment).filter(DealAssessment.task_id == task.id).first()
    if existing is None:
        raise ConflictError("已完成任务缺少成交研判")
    if task.claimed_by != _claim_owner(actor_id, raw.get("agent_id")):
        raise ConflictError("已完成任务不属于当前Agent")
    if (existing.evidence_snapshot or {}).get("submission_hash") != submission_hash:
        raise ConflictError("已完成任务不能用不同内容覆盖")
    return task, existing


def submit_industry_gate(
    db: Session,
    task_id: int,
    payload: Any,
    actor_id: int,
) -> tuple[PublicPoolTask, bool]:
    """Persist the low-cost gate and decide whether expensive research may continue."""
    data = _data(payload)
    task = _leased_task(db, task_id, actor_id, data.get("agent_id"), data.get("lease_token"))
    if task.status != "running":
        raise ConflictError("只有执行中的任务可以提交行业门控")
    snapshot = _json_safe({key: value for key, value in data.items() if key != "lease_token"})
    snapshot_hash = _snapshot_hash(snapshot)
    existing = task.gate_snapshot or {}
    if task.gate_status in {"passed", "stopped"}:
        if existing.get("submission_hash") != snapshot_hash:
            raise ConflictError("行业门控已提交，不能用不同内容覆盖")
        return task, task.gate_status == "passed"
    can_deepen = (
        data.get("industry_relevance") != "irrelevant"
        and data.get("identity_decision") != "rejected"
    )
    task.gate_status = "passed" if can_deepen else "stopped"
    task.gate_snapshot = {**snapshot, "submission_hash": snapshot_hash, "deep_research_authorized": can_deepen}
    task.research_summary = data.get("summary")
    task.updated_by = actor_id
    if not can_deepen:
        gated = {
            **data,
            "facts": data.get("facts") or [],
            "contacts": [],
            "outreach_angles": [],
            "risks": [],
            "score_components": {"risk_penalty": 0, "reasons": {"industry_fit": data.get("industry_relevance_reason") or "行业门控停止"}},
            "supplier_status": "unknown",
            "pain_points": [],
            "product_fit": [],
            "research_depth": "gate_only",
            "social_profiles": [],
            "commercial_profile": {"customer_type": "other"},
            "recommended_strategy": "停止销售开发；如后续出现相反证据，再由人工重新评估。",
            "outreach_type": "no_outreach",
            "opening_message_en": None,
            "idempotency_key": f"public-pool-gate-{task.id}",
        }
        complete_task_research(db, task.id, gated, actor_id, allow_stopped_gate=True)
        db.refresh(task)
        return task, False
    db.commit()
    db.refresh(task)
    return task, True


QUALIFICATION_WEIGHTS = {
    "authenticity_maturity": 0.12,
    "purchase_potential": 0.18,
    "demand_readiness": 0.12,
    "industry_professionalism": 0.10,
    "product_market_fit": 0.10,
    "growth_brand_potential": 0.10,
    "decision_authority": 0.08,
    "transaction_compliance": 0.08,
    "engagement_momentum": 0.07,
    "strategic_value": 0.05,
}


def _qualification_summary(commercial_profile: dict) -> dict:
    profile = dict(commercial_profile or {})
    dimensions = profile.get("qualification_dimensions") or {}
    weighted_points = 0.0
    covered_weight = 0.0
    for key, weight in QUALIFICATION_WEIGHTS.items():
        score = (dimensions.get(key) or {}).get("score")
        if score is None:
            continue
        weighted_points += weight * float(score) / 5
        covered_weight += weight
    profile["qualification_score"] = (
        round(weighted_points / covered_weight * 100, 2) if covered_weight else None
    )
    profile["qualification_coverage"] = round(covered_weight * 100, 2)
    return profile


class BusinessPoolGateway:
    """读取 lsordertest 的薄网关；绝不执行写语句。"""

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.schema = self.settings.BUSINESS_DB_NAME
        self.customer_columns = self._customer_columns()
        self.website_column = next((name for name in WEBSITE_COLUMNS if name in self.customer_columns), None)
        self.address_column = next((name for name in ADDRESS_COLUMNS if name in self.customer_columns), None)
        self.locality_columns = {
            key: next((name for name in names if name in self.customer_columns), None)
            for key, names in LOCALITY_COLUMN_GROUPS.items()
        }

    def _customer_columns(self) -> set[str]:
        try:
            return {
                str(item["name"]).lower()
                for item in inspect(self.db.get_bind()).get_columns("customer_info", schema=self.schema)
            }
        except SQLAlchemyError as exc:
            logger.warning("public pool customer capability inspection failed: %s", type(exc).__name__)
            print("public pool customer capability inspection failed", flush=True)
            return set()

    @property
    def _website_expr(self) -> str:
        return f"NULLIF(TRIM(ci.`{self.website_column}`), '')" if self.website_column else "NULL"

    @property
    def _address_expr(self) -> str:
        return f"NULLIF(TRIM(ci.`{self.address_column}`), '')" if self.address_column else "NULL"

    def _locality_expr(self, key: str) -> str:
        column = self.locality_columns.get(key)
        return f"NULLIF(TRIM(ci.`{column}`), '')" if column else "NULL"

    @property
    def _contact_cte(self) -> str:
        free_domains = ",".join(f"'{domain}'" for domain in sorted(FREE_EMAIL_DOMAINS))
        return f"""
        contact_rollup AS (
            SELECT
                cc.company_id,
                MAX(NULLIF(TRIM(cc.email), '')) AS contact_email,
                MAX(NULLIF(TRIM(cc.tel), '')) AS contact_phone,
                MAX(NULLIF(TRIM(cc.name), '')) AS contact_name,
                MAX(CASE
                    WHEN cc.email LIKE '%@%'
                     AND LOWER(SUBSTRING_INDEX(SUBSTRING_INDEX(cc.email, ',', 1), '@', -1)) NOT IN ({free_domains})
                    THEN 1 ELSE 0 END) AS has_corporate_contact_email,
                MAX(CASE WHEN LOWER(COALESCE(ccs.platform, '')) LIKE '%whatsapp%' AND NULLIF(TRIM(ccs.value), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_whatsapp,
                MAX(CASE WHEN LOWER(COALESCE(ccs.platform, '')) NOT LIKE '%whatsapp%' AND NULLIF(TRIM(ccs.value), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_business_social,
                GROUP_CONCAT(DISTINCT CASE WHEN NULLIF(TRIM(ccs.value), '') IS NOT NULL THEN CONCAT(COALESCE(ccs.platform, 'social'), ':', ccs.value) END ORDER BY ccs.id SEPARATOR ' | ') AS social_summary
            FROM `{self.schema}`.customer_contacts cc
            LEFT JOIN `{self.schema}`.customer_contact_socials ccs
              ON BINARY ccs.customer_id = BINARY cc.customer_id
            GROUP BY cc.company_id
        ),
        order_rollup AS (
            SELECT company_id, COUNT(*) AS order_count,
                   COALESCE(SUM(amount_usd), 0) AS order_amount_usd,
                   MAX(account_date) AS last_order_at
            FROM `{self.schema}`.okki_orders
            GROUP BY company_id
        )
        """

    @property
    def _feature_sql(self) -> str:
        free_domains = ",".join(f"'{domain}'" for domain in sorted(FREE_EMAIL_DOMAINS))
        return f"""
            COALESCE(o.order_count, 0) AS order_count,
            COALESCE(o.order_amount_usd, 0) AS order_amount_usd,
            o.last_order_at,
            COALESCE(cr.contact_email, NULLIF(TRIM(ci.email), '')) AS primary_email,
            cr.contact_phone AS primary_phone,
            cr.contact_name,
            cr.social_summary,
            {self._website_expr} AS website,
            {self._address_expr} AS customer_address,
            {self._locality_expr("city")} AS customer_city,
            {self._locality_expr("region")} AS customer_region,
            CASE WHEN (
                (ci.email LIKE '%@%' AND LOWER(SUBSTRING_INDEX(SUBSTRING_INDEX(ci.email, ',', 1), '@', -1)) NOT IN ({free_domains}))
                OR COALESCE(cr.has_corporate_contact_email, 0) = 1
            ) THEN 1 ELSE 0 END AS has_corporate_email,
            COALESCE(cr.has_business_social, 0) AS has_business_social,
            COALESCE(cr.has_whatsapp, 0) AS has_whatsapp,
            CASE WHEN {self._website_expr} IS NOT NULL THEN 1 ELSE 0 END AS has_website
        """

    def audit(self) -> dict:
        sql = text(f"""
        WITH {self._contact_cte}, features AS (
            SELECT ci.company_id,
                   CASE WHEN JSON_LENGTH(COALESCE(ci.owner_user_ids, JSON_ARRAY())) = 0 THEN 1 ELSE 0 END AS is_public,
                   {self._feature_sql}
            FROM `{self.schema}`.customer_info ci
            LEFT JOIN contact_rollup cr ON BINARY cr.company_id = BINARY ci.company_id
            LEFT JOIN order_rollup o ON BINARY o.company_id = BINARY ci.company_id
        )
        SELECT
            COUNT(*) AS total_customers,
            SUM(CASE WHEN is_public = 0 THEN 1 ELSE 0 END) AS private_customers,
            SUM(CASE WHEN is_public = 1 THEN 1 ELSE 0 END) AS public_customers,
            SUM(CASE WHEN is_public = 1 AND order_count > 0
                      AND last_order_at <= DATE_SUB(CURDATE(), INTERVAL {REACTIVATION_INACTIVE_DAYS} DAY)
                     THEN 1 ELSE 0 END) AS tier_t1,
            SUM(CASE WHEN is_public = 1 AND order_count = 0 AND (has_corporate_email = 1 OR has_website = 1 OR has_business_social = 1) THEN 1 ELSE 0 END) AS tier_t2,
            SUM(CASE WHEN is_public = 1 AND order_count = 0 AND has_corporate_email = 0 AND has_website = 0 AND has_business_social = 0
                     AND (primary_email IS NOT NULL OR primary_phone IS NOT NULL OR has_whatsapp = 1) THEN 1 ELSE 0 END) AS tier_t3,
            SUM(CASE WHEN is_public = 1 AND order_count = 0 AND has_corporate_email = 0 AND has_website = 0 AND has_business_social = 0
                     AND primary_email IS NULL AND primary_phone IS NULL AND has_whatsapp = 0 THEN 1 ELSE 0 END) AS cold_storage
        FROM features
        """)
        row = self.db.execute(sql).mappings().one()
        data = {key: int(value or 0) for key, value in row.items()}
        data.update({
            "generated_at": _now().isoformat(),
            "business_schema": self.schema,
            "website_column": self.website_column,
            "public_predicate": "JSON_LENGTH(COALESCE(owner_user_ids, JSON_ARRAY())) = 0",
            "tier_policy_version": "v2",
            "reactivation_inactive_days": REACTIVATION_INACTIVE_DAYS,
        })
        return data

    def fetch_tier_candidates(
        self,
        tier: str,
        limit: int,
        seed: str,
        cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    ) -> list[dict]:
        if tier not in TIERS:
            raise SalesAutomationError("tier 必须是 T1/T2/T3")
        tier_filter = {
            "T1": f"f.order_count > 0 AND f.last_order_at <= DATE_SUB(CURDATE(), INTERVAL {REACTIVATION_INACTIVE_DAYS} DAY)",
            "T2": "f.order_count = 0 AND (f.has_corporate_email = 1 OR f.has_website = 1 OR f.has_business_social = 1)",
            "T3": "f.order_count = 0 AND f.has_corporate_email = 0 AND f.has_website = 0 AND f.has_business_social = 0 AND (f.primary_email IS NOT NULL OR f.primary_phone IS NOT NULL OR f.has_whatsapp = 1)",
        }[tier]
        order_by = {
            "T1": "f.last_order_at DESC, f.order_count DESC, f.order_amount_usd DESC",
            "T2": "(f.has_corporate_email * 35 + f.has_website * 35 + f.has_business_social * 20 + CASE WHEN f.primary_phone IS NOT NULL THEN 10 ELSE 0 END) DESC",
            "T3": "CASE WHEN f.primary_email IS NOT NULL THEN 1 ELSE 0 END DESC",
        }[tier]
        sql = text(f"""
        WITH {self._contact_cte}, features AS (
            SELECT ci.company_id, ci.company_name, ci.country_name, ci.email AS customer_email,
                   {self._feature_sql}
            FROM `{self.schema}`.customer_info ci
            LEFT JOIN contact_rollup cr ON BINARY cr.company_id = BINARY ci.company_id
            LEFT JOIN order_rollup o ON BINARY o.company_id = BINARY ci.company_id
            WHERE JSON_LENGTH(COALESCE(ci.owner_user_ids, JSON_ARRAY())) = 0
        )
        SELECT f.*
        FROM features f
        WHERE {tier_filter}
          AND NOT EXISTS (
              SELECT 1
              FROM ark_sales_research_subjects s
              JOIN ark_sales_public_pool_tasks t ON t.subject_id = s.id
              WHERE s.source_system = 'okki'
                AND BINARY s.source_customer_id = BINARY CAST(f.company_id AS CHAR)
                AND t.created_at >= :cooldown_cutoff
                AND t.status IN ('pending', 'running', 'completed')
          )
        ORDER BY {order_by}, CRC32(CONCAT(CAST(f.company_id AS CHAR), :seed))
        LIMIT :limit
        """)
        rows = self.db.execute(sql, {
            "cooldown_cutoff": _now() - timedelta(days=cooldown_days),
            "seed": seed,
            "limit": max(limit, 1),
        }).mappings().all()
        return [self._candidate(dict(row), tier) for row in rows]

    @staticmethod
    def _candidate(row: dict, tier: str) -> dict:
        email = row.get("primary_email") or row.get("customer_email")
        completeness = min(100, (
            25 * int(bool(row.get("has_corporate_email")))
            + 25 * int(bool(row.get("has_website")))
            + 20 * int(bool(row.get("has_business_social")))
            + 15 * int(bool(email))
            + 10 * int(bool(row.get("primary_phone")))
            + 5 * int(bool(row.get("country_name")))
        ))
        reasons = {
            "T1": [f"当前公海且存在历史订单记录，最近 {REACTIVATION_INACTIVE_DAYS} 天无下单"],
            "T2": ["当前公海、无历史订单且具备企业身份锚点"],
            "T3": ["当前公海、无历史订单且仅有低信息量联系方式"],
        }[tier]
        if row.get("has_corporate_email"):
            reasons.append("存在企业邮箱")
        if row.get("has_website"):
            reasons.append("存在独立站")
        if row.get("has_business_social"):
            reasons.append("存在非WhatsApp社媒")
        snapshot = {
            "company_id": str(row.get("company_id")),
            "company_name": row.get("company_name") or "未命名客户",
            "country_name": row.get("country_name"),
            "customer_email": row.get("customer_email"),
            "contact_name": row.get("contact_name"),
            "contact_email": row.get("primary_email"),
            "contact_phone": row.get("primary_phone"),
            "social_summary": row.get("social_summary"),
            "website": row.get("website"),
            "address_search_hint": address_search_hint(
                row.get("customer_address"), row.get("customer_city"), row.get("customer_region")
            ),
            "order_count": int(row.get("order_count") or 0),
            "order_amount_usd": float(row.get("order_amount_usd") or 0),
            "last_order_at": _json_safe(row.get("last_order_at")),
        }
        return {
            "source_customer_id": str(row.get("company_id")),
            "display_name": row.get("company_name") or "未命名客户",
            "country": row.get("country_name"),
            "primary_email": email,
            "email_domain_type": email_domain_type(email),
            "primary_phone": row.get("primary_phone"),
            "website": row.get("website"),
            "tier": tier,
            "completeness_score": completeness,
            "order_count": int(row.get("order_count") or 0),
            "order_amount_usd": float(row.get("order_amount_usd") or 0),
            "last_order_at": _as_datetime(row.get("last_order_at")),
            "contact_snapshot": {
                "contact_name": row.get("contact_name"),
                "social_summary": row.get("social_summary"),
                "has_whatsapp": bool(row.get("has_whatsapp")),
                "has_business_social": bool(row.get("has_business_social")),
            },
            "source_snapshot": snapshot,
            "selection_reason": reasons,
        }


def latest_audit(db: Session, refresh: bool = False, gateway: BusinessPoolGateway | None = None) -> dict:
    if not refresh:
        batch = db.query(PublicPoolBatch).filter(
            PublicPoolBatch.deleted_at.is_(None),
            PublicPoolBatch.status == "completed",
        ).order_by(PublicPoolBatch.batch_date.desc(), PublicPoolBatch.id.desc()).first()
        if batch and batch.audit_snapshot:
            return {**batch.audit_snapshot, "cache_source": f"batch:{batch.id}"}
    data = (gateway or BusinessPoolGateway(db)).audit()
    data["cache_source"] = "live"
    return data


def _upsert_subject(db: Session, candidate: dict, actor_id: int | None) -> ResearchSubject:
    external_key = f"okki:{candidate['source_customer_id']}"
    subject = db.query(ResearchSubject).filter(ResearchSubject.external_key == external_key).first()
    if subject is None:
        subject = ResearchSubject(
            subject_type="okki_customer",
            external_key=external_key,
            source_system="okki",
            source_customer_id=candidate["source_customer_id"],
            created_by=actor_id,
        )
        db.add(subject)
    for field in (
        "display_name", "country", "primary_email", "email_domain_type", "primary_phone",
        "website", "completeness_score", "order_count", "order_amount_usd", "last_order_at",
        "contact_snapshot", "source_snapshot",
    ):
        setattr(subject, field, candidate.get(field))
    subject.seed_tier = candidate["tier"]
    subject.eligibility_status = "eligible"
    subject.source_snapshot_hash = _snapshot_hash(candidate["source_snapshot"])
    subject.last_selected_at = _now()
    subject.updated_by = actor_id
    db.flush()
    return subject


def prepare_batch(
    db: Session,
    payload: Any,
    actor_id: int | None,
) -> tuple[PublicPoolBatch, bool]:
    """幂等登记批次；未完成批次存在时绝不重复排队。"""
    data = _data(payload)
    batch_date = data.get("batch_date") or date.today()
    quota = int(data.get("quota_per_tier") or 20)
    policy_version = str(data.get("policy_version") or "v1")
    idempotency_key = f"public-pool-{batch_date.isoformat()}-{policy_version}-{quota}"
    existing = db.query(PublicPoolBatch).filter(
        PublicPoolBatch.idempotency_key == idempotency_key,
    ).with_for_update().first()
    if existing is not None and existing.status in {"pending", "running", "completed"}:
        return existing, False
    if existing is not None:
        # 失败批次允许人工重试；生成明细在同一事务中，可安全重建同一幂等批次。
        db.query(PublicPoolTask).filter(PublicPoolTask.batch_id == existing.id).delete(synchronize_session=False)
        batch = existing
        batch.status = "pending"
        batch.audit_snapshot = {}
        batch.result_counts = {}
        batch.error_message = None
        batch.started_at = None
        batch.finished_at = None
        batch.updated_by = actor_id
    else:
        batch = PublicPoolBatch(
            batch_date=batch_date,
            policy_version=policy_version,
            status="pending",
            quota_per_tier=quota,
            quotas={tier: quota for tier in TIERS},
            audit_snapshot={},
            result_counts={},
            idempotency_key=idempotency_key,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        # 两次并发首次提交由唯一幂等键裁决；后到请求返回已登记批次且不再排队。
        db.rollback()
        raced = db.query(PublicPoolBatch).filter(PublicPoolBatch.idempotency_key == idempotency_key).first()
        if raced is None:
            raise
        return raced, False
    db.refresh(batch)
    return batch, True


def execute_batch(
    db: Session,
    batch_id: int,
    gateway: BusinessPoolGateway | None = None,
) -> PublicPoolBatch:
    """领取并执行已登记批次；只有 pending 能进入执行态。"""
    batch = db.query(PublicPoolBatch).filter(PublicPoolBatch.id == batch_id).with_for_update().first()
    if batch is None:
        raise NotFoundError("公海批次不存在")
    if batch.status != "pending":
        return batch
    batch.status = "running"
    batch.started_at = _now()
    db.commit()
    db.refresh(batch)
    quota = batch.quota_per_tier
    actor_id = batch.updated_by
    source = gateway or BusinessPoolGateway(db)
    try:
        batch.audit_snapshot = source.audit()
        result_counts: dict[str, int] = {}
        for tier in TIERS:
            candidates = source.fetch_tier_candidates(
                tier,
                limit=max(quota * 4, quota),
                seed=f"{batch.batch_date.isoformat()}:{tier}:{batch.policy_version}",
            )
            top_count = min(len(candidates), max(0, quota - min(4, quota)))
            selected = candidates[:top_count]
            remaining = candidates[top_count:]
            exploration_count = min(quota - len(selected), len(remaining))
            if exploration_count:
                rng = random.Random(f"{batch.batch_date.isoformat()}:{tier}:{batch.policy_version}")
                selected.extend(rng.sample(remaining, exploration_count))
            for rank, candidate in enumerate(selected[:quota], start=1):
                subject = _upsert_subject(db, candidate, actor_id)
                db.add(PublicPoolTask(
                    batch_id=batch.id,
                    subject_id=subject.id,
                    tier=tier,
                    selection_rank=rank,
                    selection_reason=candidate["selection_reason"],
                    created_by=actor_id,
                    updated_by=actor_id,
                ))
            result_counts[tier] = min(len(selected), quota)
        batch.result_counts = {"selected": result_counts, "total": sum(result_counts.values())}
        batch.status = "completed"
        batch.finished_at = _now()
        db.commit()
        db.refresh(batch)
        return batch
    except Exception as exc:
        db.rollback()
        failed = db.query(PublicPoolBatch).filter(PublicPoolBatch.id == batch.id).first()
        if failed:
            failed.status = "failed"
            failed.error_message = f"{type(exc).__name__}: {str(exc)[:1800]}"
            failed.finished_at = _now()
            db.commit()
        logger.warning("public pool batch generation failed: %s", type(exc).__name__)
        print(f"public pool batch generation failed: {type(exc).__name__}", flush=True)
        raise


def generate_batch(
    db: Session,
    payload: Any,
    actor_id: int | None,
    gateway: BusinessPoolGateway | None = None,
) -> PublicPoolBatch:
    """同步入口，供 scheduler 和测试使用，并接管尚未领取的 pending 批次。"""
    batch, _should_start = prepare_batch(db, payload, actor_id)
    return execute_batch(db, batch.id, gateway) if batch.status == "pending" else batch


def run_batch_in_background(batch_id: int) -> None:
    """FastAPI 后台任务入口，必须使用独立 Session。"""
    with SessionLocal() as db:
        try:
            execute_batch(db, batch_id)
        except Exception as exc:
            logger.exception("public pool background batch failed: id=%s", batch_id)
            print(f"public pool background batch failed: id={batch_id} {type(exc).__name__}", flush=True)


def list_batches(db: Session, page: int, page_size: int) -> tuple[list[PublicPoolBatch], int]:
    query = db.query(PublicPoolBatch).filter(PublicPoolBatch.deleted_at.is_(None))
    total = query.count()
    rows = query.order_by(PublicPoolBatch.batch_date.desc(), PublicPoolBatch.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def get_task(db: Session, task_id: int, *, for_update: bool = False) -> PublicPoolTask:
    query = db.query(PublicPoolTask).filter(PublicPoolTask.id == task_id, PublicPoolTask.deleted_at.is_(None))
    if for_update:
        query = query.with_for_update()
    task = query.first()
    if task is None:
        raise NotFoundError("公海研究任务不存在")
    return task


def list_tasks(
    db: Session,
    page: int,
    page_size: int,
    status: str | None = None,
    tier: str | None = None,
    review_status: str | None = None,
    allocation_status: str | None = None,
    keyword: str | None = None,
) -> tuple[list[tuple[PublicPoolTask, ResearchSubject, DealAssessment | None, CustomerOpportunity | None]], int]:
    query = db.query(PublicPoolTask, ResearchSubject, DealAssessment, CustomerOpportunity).join(
        ResearchSubject, ResearchSubject.id == PublicPoolTask.subject_id,
    ).outerjoin(DealAssessment, DealAssessment.task_id == PublicPoolTask.id).outerjoin(
        CustomerOpportunity, CustomerOpportunity.id == PublicPoolTask.opportunity_id,
    ).filter(
        PublicPoolTask.deleted_at.is_(None), ResearchSubject.deleted_at.is_(None),
    )
    if status:
        query = query.filter(PublicPoolTask.status == status)
    if tier:
        query = query.filter(PublicPoolTask.tier == tier)
    if review_status:
        query = query.filter(PublicPoolTask.review_status == review_status)
    if allocation_status == "claimable":
        query = query.filter(
            PublicPoolTask.review_status == "approved",
            PublicPoolTask.opportunity_id.is_(None),
        )
    elif allocation_status == "claimed":
        query = query.filter(PublicPoolTask.opportunity_id.is_not(None))
    if keyword:
        query = query.filter(or_(
            ResearchSubject.display_name.ilike(f"%{keyword.strip()}%"),
            ResearchSubject.source_customer_id.ilike(f"%{keyword.strip()}%"),
        ))
    total = query.count()
    rows = query.order_by(
        DealAssessment.priority_score.desc(), PublicPoolTask.created_at.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def list_claimable_tasks(db: Session, page: int, page_size: int) -> tuple[list[PublicPoolTask], int]:
    now = _now()
    query = db.query(PublicPoolTask).filter(
        PublicPoolTask.deleted_at.is_(None),
        or_(
            PublicPoolTask.status == "pending",
            and_(PublicPoolTask.status == "running", PublicPoolTask.lease_expires_at <= now),
        ),
    )
    total = query.count()
    rows = query.order_by(PublicPoolTask.created_at.asc(), PublicPoolTask.id.asc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def _claim_owner(actor_id: int, agent_id: str) -> str:
    cleaned = str(agent_id or "").strip()
    if not cleaned or len(cleaned) > 96:
        raise SalesAutomationError("agent_id 必填且不超过96字符")
    return f"{actor_id}:{cleaned}"


def claim_task(db: Session, task_id: int, actor_id: int, agent_id: str) -> tuple[PublicPoolTask, str]:
    task = get_task(db, task_id, for_update=True)
    now = _now()
    reclaimable = task.status == "running" and task.lease_expires_at is not None and task.lease_expires_at <= now
    if task.status != "pending" and not reclaimable:
        raise ConflictError("任务不是等待领取状态，或仍由其他Agent执行")
    token = secrets.token_urlsafe(32)
    task.status = "running"
    task.started_at = task.started_at or now
    task.finished_at = None
    task.error_message = None
    task.claimed_by = _claim_owner(actor_id, agent_id)
    task.lease_token_hash = _hash(token)
    task.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    task.attempt_count += 1
    task.updated_by = actor_id
    db.commit()
    db.refresh(task)
    return task, token


def _leased_task(db: Session, task_id: int, actor_id: int, agent_id: str, lease_token: str) -> PublicPoolTask:
    task = get_task(db, task_id, for_update=True)
    if task.claimed_by != _claim_owner(actor_id, agent_id):
        raise ConflictError("任务租约不属于当前Agent")
    if not lease_token or not secrets.compare_digest(task.lease_token_hash or "", _hash(lease_token)):
        raise ConflictError("任务租约无效")
    if task.lease_expires_at is None or task.lease_expires_at <= _now():
        raise ConflictError("任务租约已过期，请重新领取")
    return task


def heartbeat_task(db: Session, task_id: int, actor_id: int, agent_id: str, lease_token: str) -> PublicPoolTask:
    task = _leased_task(db, task_id, actor_id, agent_id, lease_token)
    if task.status != "running":
        raise ConflictError("只有执行中的任务可以续租")
    task.lease_expires_at = _now() + timedelta(minutes=LEASE_MINUTES)
    db.commit()
    db.refresh(task)
    return task


def fail_task(
    db: Session,
    task_id: int,
    error_message: str,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> PublicPoolTask:
    task = _leased_task(db, task_id, actor_id, agent_id, lease_token)
    if task.status != "running":
        raise ConflictError("只有执行中的任务可以标记失败")
    task.status = "failed"
    task.error_message = str(error_message or "")[:2000]
    task.finished_at = _now()
    task.updated_by = actor_id
    db.commit()
    db.refresh(task)
    return task


def _upsert_subject_contacts(db: Session, subject: ResearchSubject, contacts: list[Any], actor_id: int) -> list[LeadContact]:
    rows: list[LeadContact] = []
    for raw in contacts:
        data = _data(raw)
        email = str(data.get("email") or "").strip()
        email_normalized = email.lower() or None
        name = str(data.get("name") or "").strip() or None
        role = str(data.get("role") or "").strip() or None
        if not email_normalized and not name:
            raise SalesAutomationError("联系人至少需要 email 或 name")
        identity_key = _hash(email_normalized or f"{(name or '').lower()}|{(role or '').lower()}")
        source_url = normalize_source_url(data.get("source_url"))
        row = db.query(LeadContact).filter(
            LeadContact.subject_id == subject.id, LeadContact.identity_key == identity_key,
        ).first()
        if row is None:
            row = LeadContact(subject_id=subject.id, identity_key=identity_key, created_by=actor_id)
            db.add(row)
        row.name = name or row.name
        row.role = role or row.role
        row.email = email or row.email
        row.email_normalized = email_normalized or row.email_normalized
        requested_status = data.get("email_status")
        if requested_status is not None:
            verified_at = data.get("verified_at")
            if requested_status != "unknown" and (not email_normalized or not verified_at):
                raise SalesAutomationError("已验证邮箱状态必须同时提供 email 和 verified_at")
            row.email_status = requested_status
            row.verified_at = None if requested_status == "unknown" else _as_datetime(verified_at)
        row.source_provider = data.get("source_provider") or "agent"
        row.source_url = source_url
        row.captured_at = _as_datetime(data.get("captured_at"))
        if row.captured_at is None:
            raise SalesAutomationError("captured_at 格式无效")
        row.confidence = data.get("confidence")
        row.updated_by = actor_id
        rows.append(row)
    db.flush()
    return rows


def _create_subject_research(
    db: Session,
    subject: ResearchSubject,
    data: dict,
    actor_id: int,
) -> tuple[ResearchRun, list[ResearchFact]]:
    facts = data.get("facts") or []
    if not facts and data.get("identity_decision") not in {"unverifiable", "rejected"}:
        raise SalesAutomationError("主体可用时 facts 至少需要一条公开证据")
    # 每次 task 是研究版本边界；不允许调用方复用另一个 task 的 key 来借用旧证据。
    idem = f"pool-task-{data['task_id']}"
    existing = db.query(ResearchRun).filter(
        ResearchRun.subject_id == subject.id, ResearchRun.idempotency_key == idem,
    ).first()
    if existing:
        existing_facts = db.query(ResearchFact).filter(ResearchFact.run_id == existing.id).all()
        return existing, existing_facts
    run = ResearchRun(
        subject_id=subject.id,
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
    rows: list[ResearchFact] = []
    for position, raw in enumerate(facts):
        fact = _data(raw)
        claim = str(fact.get("claim") or "").strip()
        if not claim:
            raise SalesAutomationError("研究事实 claim 必填")
        source_url = normalize_source_url(fact.get("source_url"))
        captured_at = _as_datetime(fact.get("captured_at"))
        confidence = float(fact.get("confidence"))
        if captured_at is None:
            raise SalesAutomationError("研究事实 captured_at 格式无效")
        if not 0 <= confidence <= 1:
            raise SalesAutomationError("confidence 必须在0到1之间")
        row = ResearchFact(
            run_id=run.id,
            fact_type=fact.get("fact_type") or "general",
            claim=claim,
            fact_hash=_hash(claim.lower()),
            source_url=source_url,
            source_url_hash=_hash(source_url),
            captured_at=captured_at,
            confidence=confidence,
            sort_order=position,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return run, rows


def complete_task_research(
    db: Session,
    task_id: int,
    payload: Any,
    actor_id: int,
    *,
    allow_stopped_gate: bool = False,
) -> tuple[PublicPoolTask, DealAssessment]:
    retried = get_idempotent_completed_research(db, task_id, payload, actor_id)
    if retried is not None:
        return retried
    data, components, submission_hash = _normalized_research_submission(payload)
    task = _leased_task(db, task_id, actor_id, data.get("agent_id"), data.get("lease_token"))
    if task.gate_status != "passed" and not (allow_stopped_gate and task.gate_status == "stopped"):
        raise ConflictError("请先提交行业门控；只有通过后才能执行深入背调")
    if data.get("industry_relevance") == "irrelevant" and not allow_stopped_gate:
        raise ConflictError("行业无关必须在低成本门控阶段停止，不能通过深入背调接口提交")
    if task.status != "running":
        raise ConflictError("只有执行中的任务可以提交研究结果")
    subject = db.query(ResearchSubject).filter(ResearchSubject.id == task.subject_id).with_for_update().first()
    if subject is None:
        raise NotFoundError("研究主体不存在")
    _upsert_subject_contacts(db, subject, data.get("contacts") or [], actor_id)
    research_data = {**data, "task_id": task.id}
    run, facts = _create_subject_research(db, subject, research_data, actor_id)
    unique_sources = len({fact.source_url_hash for fact in facts})
    commercial_profile = _qualification_summary(data.get("commercial_profile") or {})
    scores = compute_deal_scores(
        components,
        data["identity_decision"],
        unique_sources,
        commercial_profile.get("qualification_coverage"),
    )
    evidence_snapshot = {
        "submission_hash": submission_hash,
        "research_run_id": run.id,
        "fact_ids": [fact.id for fact in facts],
        "fact_source_urls": [fact.source_url for fact in facts],
        "source_snapshot_hash": subject.source_snapshot_hash,
        "source_customer_id": subject.source_customer_id,
    }
    assessment = DealAssessment(
        task_id=task.id,
        subject_id=subject.id,
        identity_decision=data["identity_decision"],
        score_factors=components,
        supplier_status=data.get("supplier_status") or "unknown",
        pain_points=data.get("pain_points") or [],
        product_fit=data.get("product_fit") or [],
        industry_relevance=data.get("industry_relevance") or "uncertain",
        industry_relevance_reason=data.get("industry_relevance_reason") or "",
        research_depth=data.get("research_depth") or "focused",
        stop_reason=data.get("stop_reason"),
        social_profiles=_json_safe(data.get("social_profiles") or []),
        knowledge_references=_json_safe(data.get("knowledge_references") or []),
        commercial_profile=_json_safe(commercial_profile),
        recommended_strategy=data.get("recommended_strategy") or "",
        outreach_type=data.get("outreach_type") or ("reactivation" if task.tier == "T1" else "new_development"),
        opening_message_en=data.get("opening_message_en"),
        risks=data.get("risks") or [],
        evidence_snapshot=evidence_snapshot,
        provider=data.get("provider") or "agent",
        model=data.get("model"),
        assessment_version="v2",
        completed_at=_now(),
        created_by=actor_id,
        updated_by=actor_id,
        **scores,
    )
    db.add(assessment)
    task.status = "completed"
    task.research_summary = data.get("summary")
    task.finished_at = _now()
    task.updated_by = actor_id
    db.commit()
    db.refresh(task)
    db.refresh(assessment)
    return task, assessment


def get_task_detail(db: Session, task_id: int) -> dict:
    task = get_task(db, task_id)
    # 同一客户可能跨批次产生多个 task；锁共享 subject，跨 task 抢领也串行化。
    subject = db.query(ResearchSubject).filter(
        ResearchSubject.id == task.subject_id,
    ).with_for_update().first()
    if subject is None:
        raise NotFoundError("研究主体不存在")
    assessment = db.query(DealAssessment).filter(DealAssessment.task_id == task.id).first()
    opportunity = None if task.opportunity_id is None else db.query(CustomerOpportunity).filter(
        CustomerOpportunity.id == task.opportunity_id,
    ).first()
    contacts = db.query(LeadContact).filter(
        LeadContact.subject_id == subject.id, LeadContact.deleted_at.is_(None),
    ).order_by(LeadContact.created_at.asc()).all()
    run = db.query(ResearchRun).filter(
        ResearchRun.subject_id == subject.id, ResearchRun.deleted_at.is_(None),
    ).order_by(ResearchRun.created_at.desc()).first()
    facts = [] if run is None else db.query(ResearchFact).filter(
        ResearchFact.run_id == run.id, ResearchFact.deleted_at.is_(None),
    ).order_by(ResearchFact.sort_order.asc()).all()
    return {
        "task": task,
        "subject": subject,
        "assessment": assessment,
        "opportunity": opportunity,
        "contacts": contacts,
        "research_run": run,
        "facts": facts,
    }


def _opportunity_due_at(grade: str) -> datetime | None:
    now = _now()
    if grade == "A":
        return now + timedelta(hours=2)
    if grade == "B":
        target = now.replace(hour=18, minute=0, second=0, microsecond=0)
        return target if target > now else target + timedelta(days=1)
    if grade == "C":
        return (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    return None


def approve_task(db: Session, task_id: int, actor_id: int) -> PublicPoolTask:
    task = get_task(db, task_id, for_update=True)
    if task.status != "completed":
        raise ConflictError("只有研究完成的客户可以审核")
    if task.review_status == "rejected":
        raise ConflictError("已拒绝任务不能直接确认")
    if task.review_status == "approved":
        return task
    subject = db.query(ResearchSubject).filter(ResearchSubject.id == task.subject_id).first()
    assessment = db.query(DealAssessment).filter(DealAssessment.task_id == task.id).first()
    if subject is None or assessment is None:
        raise ConflictError("任务缺少研究主体或成交研判")
    if (
        assessment.identity_decision == "rejected"
        or assessment.industry_relevance == "irrelevant"
        or assessment.outreach_type == "no_outreach"
    ):
        raise ConflictError("主体不符、行业无关或不建议触达的客户不能审核进入团队公海")
    task.review_status = "approved"
    task.reviewed_by = actor_id
    task.reviewed_at = _now()
    task.updated_by = actor_id
    db.commit()
    db.refresh(task)
    return task


def claim_approved_task(db: Session, task_id: int, actor_id: int) -> CustomerOpportunity:
    """业务员抢领已审核客户；task 行锁保证只有一人成功。"""
    task = get_task(db, task_id, for_update=True)
    if task.status != "completed" or task.review_status != "approved":
        raise ConflictError("只有审核通过的客户可以领取")
    if task.opportunity_id is not None:
        claimed = db.query(CustomerOpportunity).filter(CustomerOpportunity.id == task.opportunity_id).first()
        if claimed is not None and claimed.owner_user_id == actor_id:
            return claimed
        raise ConflictError("该公海客户已被其他业务员领取")
    # 同一客户可能跨批次产生多个 task；锁共享 subject，跨 task 抢领也串行化。
    subject = db.query(ResearchSubject).filter(
        ResearchSubject.id == task.subject_id,
    ).with_for_update().first()
    assessment = db.query(DealAssessment).filter(DealAssessment.task_id == task.id).first()
    if subject is None or assessment is None:
        raise ConflictError("任务缺少研究主体或成交研判")
    if (
        assessment.identity_decision == "rejected"
        or assessment.industry_relevance == "irrelevant"
        or assessment.outreach_type == "no_outreach"
    ):
        raise ConflictError("主体不符、行业无关或不建议触达的客户不能领取")
    source_key = f"okki-public:{subject.source_customer_id}"
    opportunity = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.source_key == source_key,
    ).with_for_update().first()
    if opportunity is not None and opportunity.owner_user_id is not None:
        if opportunity.owner_user_id != actor_id:
            raise ConflictError("该公海客户已被其他业务员领取")
        # 同一业务员重复遇到该客户时沿用历史机会，不重置已流失/已忽略等状态。
        task.opportunity_id = opportunity.id
        task.updated_by = actor_id
        db.commit()
        return opportunity
    confidence_score = {"high": 90, "medium": 65, "low": 35}[assessment.evidence_confidence]
    opportunity_type = "customer_reactivation" if task.tier == "T1" else "public_pool"
    background = {
        "source_snapshot": subject.source_snapshot or {},
        "identity_decision": assessment.identity_decision,
        "business_quality_score": assessment.business_quality_score,
        "deal_score": assessment.deal_score,
        "priority_score": assessment.priority_score,
        "supplier_status": assessment.supplier_status,
        "pain_points": assessment.pain_points or [],
        "product_fit": assessment.product_fit or [],
        "risks": assessment.risks or [],
    }
    signals = list(dict.fromkeys((assessment.product_fit or []) + (assessment.pain_points or [])))[:8]
    if opportunity is None:
        opportunity = CustomerOpportunity(
            opportunity_type=opportunity_type,
            source="okki",
            source_key=source_key,
            source_ref_type="customer",
            source_ref_id=subject.source_customer_id,
            customer_name=subject.display_name,
            customer_region=subject.country,
            customer_external_id=subject.source_customer_id,
            status="pending",
        )
        db.add(opportunity)
    opportunity.source = "okki"
    opportunity.source_ref_type = "customer"
    opportunity.source_ref_id = subject.source_customer_id
    opportunity.customer_name = subject.display_name
    opportunity.customer_region = subject.country
    opportunity.customer_external_id = subject.source_customer_id
    opportunity.status = "pending"
    opportunity.opportunity_type = opportunity_type
    opportunity.owner_user_id = actor_id
    opportunity.owner_resolve_status = "resolved"
    opportunity.priority_level = assessment.grade
    opportunity.confidence_score = confidence_score
    opportunity.urgency = "high" if assessment.grade == "A" else "normal" if assessment.grade in {"B", "C"} else "low"
    opportunity.title = f"{subject.display_name} · {'老客再激活' if task.tier == 'T1' else '公海开发'}"
    opportunity.summary = task.research_summary
    opportunity.key_signals_json = signals
    opportunity.background_check_json = background
    opportunity.background_summary_json = {
        "recommended_strategy": assessment.recommended_strategy,
        "deal_likelihood": assessment.deal_likelihood,
        "evidence_confidence": assessment.evidence_confidence,
    }
    opportunity.customer_profile_json = subject.source_snapshot or {}
    opportunity.recommended_strategy = assessment.recommended_strategy
    opportunity.opening_message_en = assessment.opening_message_en
    opportunity.evidence_json = assessment.evidence_snapshot or {}
    opportunity.due_at = _opportunity_due_at(assessment.grade)
    task.updated_by = actor_id
    db.flush()
    task.opportunity_id = opportunity.id
    db.commit()
    db.refresh(opportunity)
    event = ingest_opportunity_event(
        db,
        opportunity,
        event_type="reactivation" if task.tier == "T1" else "public_pool",
    )
    if event is None:
        logger.warning(
            "public pool opportunity claimed but radar sync failed: task=%s opp=%s",
            task.id,
            opportunity.id,
        )
        print(
            f"public pool opportunity claimed but radar sync failed: task={task.id} opp={opportunity.id}",
            flush=True,
        )
    return opportunity


def reject_task(db: Session, task_id: int, actor_id: int, reason: str) -> PublicPoolTask:
    task = get_task(db, task_id, for_update=True)
    if task.status != "completed":
        raise ConflictError("只有研究完成的客户可以审核")
    if task.review_status == "approved":
        raise ConflictError("已进入开发队列的任务不能拒绝")
    task.review_status = "rejected"
    task.reviewed_by = actor_id
    task.reviewed_at = _now()
    task.error_message = f"人工拒绝：{reason[:900]}"
    task.updated_by = actor_id
    db.commit()
    db.refresh(task)
    return task
