"""Board projection: deterministic stage, dictionary-backed tags and research report.

Fixed tags come from synced fields; AI tags are stored by successful analysis
runs and take effect automatically, minus codes the salesperson removed. Tag
vocabularies live in sys_dict so prompts and validators read them at runtime.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import bindparam, text

from app.core.time import beijing_now, beijing_today

TAG_TYPES = {
    "ai": "client_desk_ai_tag",
    "risk": "client_desk_risk_tag",
    "type": "client_desk_customer_type",
}
DEFAULT_TAGS = {
    "ai": [
        ("high_repurchase", "高复购潜力"),
        ("custom_need", "有定制需求"),
        ("price_sensitive", "价格敏感"),
        ("sample_stage", "样品阶段"),
        ("decision_maker", "决策人直联"),
        ("large_order", "大单潜力"),
        ("repurchase_window", "复购窗口将至"),
        ("quality_focus", "重视品质"),
    ],
    "risk": [
        ("complaint", "有投诉记录"),
        ("slow_payment", "回款偏慢"),
        ("long_silent", "长期沉默"),
        ("churn_risk", "流失风险"),
        ("comparing_suppliers", "正在比价"),
    ],
    "type": [
        ("wholesaler", "批发商"),
        ("salon", "沙龙/发型师"),
        ("brand", "品牌商"),
        ("ecommerce", "电商卖家"),
        ("distributor", "经销商"),
        ("retailer", "零售店"),
    ],
}
STAGES = [
    ("active", "活跃洽谈"),
    ("repeat", "稳定复购"),
    ("nurture", "新客培育"),
    ("dormant", "待唤醒"),
    ("churn", "流失风险"),
]
STAGE_LABELS = dict(STAGES)
SECTIONS = [
    ("identity", "客户主体"),
    ("business_quality", "经营情况"),
    ("product_fit", "产品适配"),
    ("supplier_status", "供应商现状"),
    ("risk", "风险与缺口"),
    ("strategy", "建议动作"),
]
PROFILE_BLOCKS = [
    ("identity", "客户是谁"),
    ("needs", "采购需求"),
    ("decision", "决策方式"),
    ("relationship", "合作现状"),
    ("opportunity", "机会与风险"),
]


def seed_tag_dictionary(db):
    from app.system.models import SysDict
    from app.client_desk.service import atomic_insert

    for kind, items in DEFAULT_TAGS.items():
        for sort, (code, label) in enumerate(items):
            atomic_insert(
                db,
                SysDict,
                {
                    "type": TAG_TYPES[kind],
                    "code": code,
                    "label": label,
                    "sort": sort,
                    "is_active": True,
                },
                ["type", "code"],
            )


def tag_vocabulary(db):
    """Active vocabulary per kind; codes are unique across kinds."""
    from app.system.models import SysDict

    kinds = {v: k for k, v in TAG_TYPES.items()}
    result = {kind: [] for kind in TAG_TYPES}
    seen = set()
    for row in (
        db.query(SysDict)
        .filter(SysDict.type.in_(list(kinds)), SysDict.is_active.is_(True))
        .order_by(SysDict.type, SysDict.sort, SysDict.id)
    ):
        if row.code in seen:
            continue
        seen.add(row.code)
        result[kinds[row.type]].append({"code": row.code, "label": row.label})
    return result


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def compute_stage(order_count, last_order, last_touch, created_at, today=None):
    """Deterministic and explainable; no model output participates."""
    today = today or beijing_today()
    last_order, last_touch, created = (
        _as_date(last_order),
        _as_date(last_touch),
        _as_date(created_at),
    )
    order_age = (today - last_order).days if last_order else None
    touch_age = (today - last_touch).days if last_touch else None
    if order_count >= 2 and order_age is not None and order_age <= 180:
        return "repeat"
    if touch_age is not None and touch_age <= 14:
        return "active"
    if order_count and order_age is not None and order_age > 270 and (
        touch_age is None or touch_age > 90
    ):
        return "churn"
    if not order_count and (
        (created and (today - created).days <= 90)
        or (touch_age is not None and touch_age <= 60)
    ):
        return "nurture"
    return "dormant"


def research_report(research):
    """Only reviewed customer_research_v1 claims reach salespeople.

    Gap results, raw JSON and process fields are never exposed; an empty report
    is a plain ``none`` status that the UI renders as "无背调结果".
    """
    for row in research or []:
        result = row.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("schema_version") != "customer_research_v1":
            continue
        claims = [
            c
            for c in result.get("claims") or []
            if isinstance(c, dict) and isinstance(c.get("statement"), str)
        ]
        if not claims:
            continue
        sections = []
        for key, label in SECTIONS:
            statements = [
                c["statement"].strip()
                for c in claims
                if c.get("section") == key and c["statement"].strip()
            ]
            if statements:
                sections.append({"key": key, "label": label, "statements": statements})
        if not sections:
            continue
        verdict_source = next(
            (s for s in sections if s["key"] == "strategy"), sections[0]
        )
        return {
            "status": "ready",
            "verdict": verdict_source["statements"][0][:160],
            "sections": sections,
            "generated_at": row.get("updated_at"),
            "source_count": len(result.get("citations") or []),
            "event_key": row.get("event_key"),
            "reviewed": True,
        }
    return {"status": "none"}


def model_research(report):
    """Compact statements for the model; never the raw research document."""
    if not report or report.get("status") != "ready":
        return None
    return {
        "verdict": report["verdict"],
        "sections": [
            {"section": s["key"], "statements": s["statements"][:6]}
            for s in report["sections"]
        ],
    }


def linkage_of(dependencies):
    """Binding identity of a run, cheap enough to revalidate for a whole board."""
    deps = dependencies or {}
    wa = sorted(
        [d["account"], str(d["link"]), d["version"], d["generation"]]
        for d in deps.get("wa") or []
        if d.get("ai")
    )
    feed = deps.get("alibaba_feed") or {}
    items = feed.get("items") if isinstance(feed, dict) else None
    feed_links = sorted(
        [str(i.get("link_id")), i.get("link_version")] for i in items or []
    )
    return {"wa": wa, "feed": feed_links}


def _current_linkage(db, actor, ids, wanted_feed_links):
    from sqlalchemy import exists
    from app.client_desk.models import ClientDeskWaLink
    from app.client_desk.sources import visible_wa_query
    from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage

    wa = defaultdict(list)
    if ids:
        # Mirrors visible_wa(): conversations without a timed message carry no dependency.
        has_message = exists().where(
            WhatsAppMessage.account_uid == WhatsAppConversation.account_uid,
            WhatsAppMessage.conversation_uid == WhatsAppConversation.conversation_uid,
            WhatsAppMessage.deleted_at.is_(None),
            (WhatsAppMessage.sent_at.isnot(None)) | (WhatsAppMessage.received_at.isnot(None)),
        )
        for cid, account, link, version, generation, ai in visible_wa_query(
            db, actor, company_ids=ids, for_ai=True
        ).filter(has_message).with_entities(
            ClientDeskWaLink.company_id,
            WhatsAppAccount.account_uid,
            ClientDeskWaLink.id,
            WhatsAppAccount.consent_version,
            WhatsAppAccount.session_generation,
            WhatsAppAccount.ai_egress_allowed,
        ):
            if ai:
                wa[str(cid)].append([account, str(link), version, generation])
    live_feed = set()
    if wanted_feed_links:
        from app.alibaba_feed.models import AlibabaFeedLink

        for link_id, version in db.query(
            AlibabaFeedLink.id, AlibabaFeedLink.version
        ).filter(
            AlibabaFeedLink.id.in_([int(i) for i in wanted_feed_links]),
            AlibabaFeedLink.deleted_at.is_(None),
        ):
            live_feed.add((str(link_id), version))
    return wa, live_feed


def stored_linkage_valid(db, actor, company_id, state, source=None):
    """AI tags/profile stay visible only while every WhatsApp/inquiry grant they used is live.

    With a full source bundle (detail view) the reviewed research it cited must
    also remain readable; the board omits that per-customer ACL read for speed.
    """
    if not state or not state.profile_dependencies:
        return False
    deps = state.profile_dependencies.get("deps") or {}
    if source is not None:
        current = {r["id"] for r in (source.get("source_dependencies") or {}).get("research") or []}
        if not {r.get("id") for r in deps.get("research") or []} <= current:
            return False
    linkage = linkage_of(deps)
    live_wa, live_feed = _current_linkage(
        db, actor, [str(company_id)], {link for link, _ in linkage["feed"]}
    )
    return sorted(live_wa.get(str(company_id), [])) == linkage["wa"] and all(
        (link, version) in live_feed for link, version in linkage["feed"]
    )


def effective_tags(state, vocabulary, valid=True):
    """AI tags that are still authorized, active in the dictionary and not removed."""
    if not state or not valid:
        return []
    labels = {
        item["code"]: (kind, item["label"])
        for kind, items in vocabulary.items()
        for item in items
    }
    removed = set(state.tag_overrides or [])
    tags = []
    for tag in state.ai_tags or []:
        code = tag.get("code")
        if code in removed or code not in labels:
            continue
        kind, label = labels[code]
        tags.append(
            {
                "code": code,
                "label": label,
                "kind": kind,
                "reason": tag.get("reason"),
                "cites": tag.get("cites") or [],
                "applied_at": tag.get("applied_at"),
            }
        )
    return tags


def removed_tags(state, vocabulary):
    labels = {i["code"]: i["label"] for items in vocabulary.values() for i in items}
    return [
        {"code": code, "label": labels[code]}
        for code in (state.tag_overrides or [] if state else [])
        if code in labels
    ]


def fixed_tags(grade, stage, origin):
    tags = [
        {"code": "grade:" + (grade or "none"), "label": grade or "未分级", "kind": "grade"},
        {"code": "stage:" + stage, "label": STAGE_LABELS[stage], "kind": "stage"},
    ]
    if origin:
        tags.append({"code": "channel:" + origin, "label": origin, "kind": "channel"})
    return tags


def profile_view(state, valid):
    if not state or not valid or not isinstance(state.profile_json, dict):
        return None
    profile = state.profile_json
    blocks = profile.get("blocks") or {}
    return {
        "blocks": [
            {
                "key": key,
                "label": label,
                "text": (blocks.get(key) or {}).get("text"),
                "cites": (blocks.get(key) or {}).get("cites") or [],
            }
            for key, label in PROFILE_BLOCKS
            if (blocks.get(key) or {}).get("text")
        ],
        "coverage": profile.get("coverage") or {},
        "generated_at": profile.get("generated_at"),
    }


def _mirror(db, sql, ids):
    return db.execute(
        text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": ids}
    ).mappings()


def board(db, user, keyword=""):
    """All private customers as cards; lane grouping happens client-side."""
    from app.client_desk.access import require_enabled
    from app.client_desk.models import ClientDeskState, ClientDeskSuggestion
    from app.client_desk.private_scope import list_private_companies, user_id
    from app.client_desk.rules import REASONS, R4
    from app.client_desk.source_context import list_last_touches
    from app.client_desk.sources import grade_options
    from app.invoice.models import CustomerProfile
    from app.invoice.product_service import _parse_ts, _schema
    from app.order_intelligence.service import VALID_ORDER_SQL

    actor = require_enabled(db, user)
    folded = (keyword or "").casefold()
    cards = [
        c
        for c in list_private_companies(db, actor)
        if folded in (c["name"] or "").casefold()
        or folded in (c["country"] or "").casefold()
        or keyword in c["company_id"]
    ]
    ids = [c["company_id"] for c in cards]
    vocabulary = tag_vocabulary(db)
    base = {
        "tag_vocabulary": vocabulary,
        "stages": [{"code": c, "label": l} for c, l in STAGES],
        "grade_options": grade_options(db),
        "biz_date": beijing_today(),
    }
    if not ids:
        return {**base, "items": [], "total": 0}
    schema = _schema()
    raw = {
        str(r["company_id"]): dict(r)
        for r in _mirror(
            db, f"SELECT * FROM `{schema}`.customer_info WHERE company_id IN :ids", ids
        )
    }
    contact = {}
    for r in _mirror(
        db,
        f"SELECT id,company_id,name FROM `{schema}`.customer_contacts WHERE company_id IN :ids ORDER BY id",
        ids,
    ):
        contact.setdefault(str(r["company_id"]), r["name"])
    orders = {}
    for r in _mirror(
        db,
        f"SELECT o.company_id, COUNT(*) AS n, SUM(o.amount_usd) AS amount, "
        f"SUM(CASE WHEN o.amount_usd IS NULL THEN 1 ELSE 0 END) AS unknown, "
        f"MAX(o.account_date) AS last_date FROM `{schema}`.okki_orders o "
        f'WHERE o.company_id IN :ids AND {VALID_ORDER_SQL.format(a="o")} '
        f"GROUP BY o.company_id",
        ids,
    ):
        orders[str(r["company_id"])] = {
            "count": int(r["n"] or 0),
            "amount_usd": float(r["amount"]) if r["amount"] is not None else None,
            "unknown_amount_count": int(r["unknown"] or 0),
            "last_order_date": _as_date(r["last_date"]),
        }
    grades = {
        cid: g
        for cid, g in db.query(
            CustomerProfile.customer_id, CustomerProfile.customer_grade
        ).filter(CustomerProfile.customer_id.in_(ids))
    }
    uid = user_id(actor)
    states = {
        str(s.company_id): s
        for s in db.query(ClientDeskState).filter(
            ClientDeskState.user_id == uid,
            ClientDeskState.company_id.in_([int(i) for i in ids]),
        )
    }
    touches = list_last_touches(db, actor, ids)
    feed_wanted = {
        link
        for s in states.values()
        for link, _ in linkage_of(
            (s.profile_dependencies or {}).get("deps")
        )["feed"]
    }
    live_wa, live_feed = _current_linkage(db, actor, ids, feed_wanted)
    today = beijing_today()
    pending = {}
    for row in db.query(ClientDeskSuggestion).filter(
        ClientDeskSuggestion.user_id == uid,
        ClientDeskSuggestion.biz_date == today,
        ClientDeskSuggestion.company_id.in_([int(i) for i in ids]),
    ).order_by(ClientDeskSuggestion.run_seq):
        open_ = (
            row.display_eligible
            and row.done_at is None
            and row.quality_feedback is None
            and not (row.snoozed_until and row.snoozed_until > today)
            and row.priority != "skip"
            and set(row.rule_codes or []) - {R4}
        )
        pending[str(row.company_id)] = {
            "open": bool(open_) or pending.get(str(row.company_id), {}).get("open", False),
            "reasons": [REASONS[c] for c in row.rule_codes or [] if c in REASONS and c != R4],
            "analysis_state": row.status if row.run_seq else None,
        }
    items = []
    for card in cards:
        cid = card["company_id"]
        info = raw.get(cid, {})
        summary = orders.get(
            cid,
            {"count": 0, "amount_usd": None, "unknown_amount_count": 0, "last_order_date": None},
        )
        touch_at, channel = touches.get(cid, (None, None))
        stage = compute_stage(
            summary["count"],
            summary["last_order_date"],
            touch_at,
            _parse_ts(info.get("create_time") or info.get("created_at")),
            today,
        )
        state = states.get(cid)
        linkage = linkage_of(((state.profile_dependencies or {}) if state else {}).get("deps"))
        valid = bool(state and state.profile_dependencies) and sorted(
            live_wa.get(cid, [])
        ) == linkage["wa"] and all(
            (link, version) in live_feed for link, version in linkage["feed"]
        )
        ai = effective_tags(state, vocabulary, valid)
        hint = pending.get(cid, {})
        items.append(
            {
                **card,
                "contact_name": contact.get(cid),
                "grade": grades.get(cid),
                "stage": stage,
                "origin": info.get("origin_name"),
                "okki_stage": info.get("trail_status_name"),
                "tags": fixed_tags(grades.get(cid), stage, info.get("origin_name"))
                + [{k: t[k] for k in ("code", "label", "kind")} for t in ai],
                "orders": summary,
                "last_touch_at": touch_at,
                "channel": channel,
                "todo": hint.get("open", False),
                "todo_reasons": hint.get("reasons", []),
                "analysis_state": hint.get("analysis_state"),
            }
        )
    items.sort(key=lambda i: (not i["todo"], -(i["orders"]["amount_usd"] or 0), int(i["company_id"])))
    return {**base, "items": items, "total": len(items), "generated_at": beijing_now()}
