"""Lease-bound controlled agent loop. No retry after an uncertain external call."""

import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from sqlalchemy import case
from fastapi import HTTPException
from .source_policy import manual_only

from app.ai.service import chat
from app.ai.text_snapshot import prepare_text_chat
from app.core.config import get_settings
from app.core.time import beijing_now
from .access import enrolled_user_ids
from .models import ClientDeskSuggestion as Row, ClientDeskState as State
from . import agent_tools, sources
from .board import tag_vocabulary
from .pack import build_pack, digest, PROTOCOL_HASH, PROTOCOL_VERSION
from .queue import active, auto_done, effective_snooze, state_data
from .rules import R1, R3, R6, R7, evaluate
from .validator import validate

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=4)
CORRECTION = "上次结果未通过结构、证据或安全检查。请不要再调用工具，直接严格按协议输出最终结果 JSON。"


def recover_expired(db, now):
    query = db.query(Row).filter(Row.status == "running", Row.lease_expires_at <= now)
    return query.update(
        {
            Row.status: case(
                (Row.call_started_at.is_(None), "queued"), else_="ambiguous"
            ),
            Row.error_code: "lease_expired",
            Row.lease_token: None,
            Row.lease_expires_at: None,
        },
        synchronize_session=False,
    )


def claim(db, now):
    cfg = get_settings()
    if not cfg.CLIENT_DESK_ENABLED:
        return None
    row = (
        db.query(Row)
        .filter(
            Row.status == "queued",
            Row.queue_eligible.is_(True),
            Row.user_id.in_(enrolled_user_ids(cfg)),
            Row.biz_date == now.date(),
        )
        .order_by(Row.run_seq.desc(), Row.rank_score.desc(), Row.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if row is None:
        return None
    token = secrets.token_hex(24)
    row.status, row.lease_token, row.lease_expires_at = "running", token, now + LEASE
    job = (row.id, token, row.user_id, row.company_id)
    db.commit()
    return job


def guarded(db, job, now):
    return db.query(Row).filter(
        Row.id == job[0],
        Row.lease_token == job[1],
        Row.status == "running",
        Row.lease_expires_at > now,
    )


def _stop(db, job, status, code):
    db.rollback()
    guarded(db, job, beijing_now()).update(
        {
            Row.status: status,
            Row.error_code: code,
            Row.lease_token: None,
            Row.lease_expires_at: None,
        },
        synchronize_session=False,
    )
    db.commit()


def run_job(db, job):
    from .service import lock_state

    _, _, uid, cid = job
    called = False
    answered = False
    usage = {"input": 0, "output": 0}
    selection = None
    initial_dependencies = None
    try:
        conversation, refs, steps_left, corrections, calls = None, None, 0, 0, 0
        trace, result, work = [], None, None
        while result is None:
            now = beijing_now()
            cfg = active(db, uid)
            row = guarded(db, job, now).populate_existing().first()
            if not row:
                db.rollback()
                return
            selected = sorted(row.selected_feed_item_ids or [])
            if selection is not None and selected != selection:
                _stop(db, job, "rule_only", "source_changed")
                return
            selection = selected
            if selection and row.run_seq <= 0:
                _stop(db, job, "rule_only", "manual_selection_required")
                return
            source = sources.analysis_input(
                db, uid, cid, now, **({"feed_item_ids": selection} if selection else {})
            )
            if selection and (row.source_dependencies or {}).get(
                "alibaba_feed"
            ) != source["source_dependencies"].get("alibaba_feed"):
                _stop(db, job, "rule_only", "source_changed")
                return
            if (
                initial_dependencies is not None
                and initial_dependencies != source["source_dependencies"]
            ):
                _stop(db, job, "rule_only", "source_changed")
                return
            initial_dependencies = source["source_dependencies"]
            day, codes = row.biz_date, list(row.rule_codes or [])
            state = db.query(State).filter_by(user_id=uid, company_id=cid).first()
            personal = state_data(state)
            allowed = evaluate(
                source,
                personal,
                now,
                uid,
                cfg.CLIENT_DESK_RULES,
                cfg.CLIENT_DESK_CALENDAR,
            )
            allowed_codes = set(allowed.codes) if allowed else set()
            if any(c in {R1, R6, R7} and c not in allowed_codes for c in codes):
                _stop(db, job, "rule_only", "source_changed")
                return
            if (
                row.quality_feedback
                or row.done_at
                or effective_snooze(db, uid, cid, now.date())
            ):
                _stop(db, job, "rule_only", "feedback_recorded")
                return
            if conversation is None:
                removed = set(personal.get("tag_overrides") or [])
                vocabulary = [
                    {**item, "kind": kind}
                    for kind, items in tag_vocabulary(db).items()
                    for item in items
                    if item["code"] not in removed
                ]
                base = build_pack(source, personal, codes, day, tags=vocabulary)
                conversation, refs = list(base.messages), dict(base.refs)
                steps_left = agent_tools.max_steps(cfg.CLIENT_DESK_RULES, row.run_seq)
            work = replace(
                base, messages=list(conversation), refs=dict(refs), hash=digest(conversation)
            )
            snapshot = prepare_text_chat(db, cfg.CLIENT_DESK_PRESET_NAME, 1800)
            if (
                snapshot.provider.id not in cfg.CLIENT_DESK_ALLOWED_PROVIDER_IDS
                or snapshot.preset.system_prompt
            ):
                raise ValueError("unapproved_preset")
            intent = {
                Row.call_started_at: beijing_now(),
                Row.attempts: Row.attempts + 1,
                Row.pack_hash: work.hash,
                Row.protocol_version: PROTOCOL_VERSION,
                Row.protocol_hash: PROTOCOL_HASH,
                Row.agent_trace: trace,
                Row.lease_expires_at: beijing_now() + LEASE,
            }
            if not guarded(db, job, beijing_now()).update(
                intent, synchronize_session=False
            ):
                db.rollback()
                return
            db.commit()
            called, answered = True, False
            calls += 1
            response = chat(
                db,
                preset_name=cfg.CLIENT_DESK_PRESET_NAME,
                messages=work.messages,
                caller_module="client_desk",
                caller_user_id=uid,
                snapshot_mode="metadata",
                timeout_sec=85,
                enforce_total_timeout=True,
                trusted_text_snapshot=snapshot,
            )
            answered = True
            usage["input"] += response.get("tokens_prompt") or 0
            usage["output"] += response.get("tokens_completion") or 0
            content = response.get("content")
            action = agent_tools.parse_action(content)
            if action and steps_left > 0:
                name, args = action
                payload, new_refs, status = agent_tools.run_tool(
                    db, source, refs, name, args
                )
                steps_left -= 1
                reply = agent_tools.tool_message(name, payload, steps_left)
                if (
                    agent_tools.context_size(conversation)
                    + len(content)
                    + len(reply["content"])
                    > agent_tools.CONTEXT_LIMIT
                ):
                    # Keep the bounded context; the next turn must conclude.
                    status, steps_left, new_refs = "limit", 0, {}
                    reply = agent_tools.tool_message(
                        name, {"error": "资料已达上限，请据现有资料输出"}, 0
                    )
                refs.update(new_refs)
                conversation += [{"role": "assistant", "content": content}, reply]
                trace.append(
                    agent_tools.trace_step(name, status, beijing_now(), args)
                )
                guarded(db, job, beijing_now()).update(
                    {Row.token_usage: usage, Row.agent_trace: trace},
                    synchronize_session=False,
                )
                db.commit()
                continue
            try:
                result = validate(content, work, day)
            except ValueError:
                guarded(db, job, beijing_now()).update(
                    {Row.token_usage: usage}, synchronize_session=False
                )
                db.commit()
                if corrections == 0:
                    corrections = 1
                    conversation += [
                        {"role": "assistant", "content": str(content or "")[:4000]},
                        {"role": "user", "content": CORRECTION},
                    ]
                    continue
                _stop(db, job, "rule_only", "validation_failed")
                return
        pack = work
        trace.append(agent_tools.trace_step("final", "ok", beijing_now()))
        db.rollback()
        active(db, uid)
        current_row = guarded(db, job, beijing_now()).populate_existing().first()
        if not current_row:
            db.rollback()
            return
        if sorted(current_row.selected_feed_item_ids or []) != selection:
            _stop(db, job, "rule_only", "source_changed")
            return
        fresh = sources.analysis_input(
            db,
            uid,
            cid,
            beijing_now(),
            **({"feed_item_ids": selection} if selection else {}),
        )
        if fresh["source_dependencies"] != pack.dependencies:
            _stop(db, job, "rule_only", "source_changed")
            return
        state = lock_state(db, uid, cid)
        if state.manual_version != (personal.get("manual_version") or 0):
            _stop(db, job, "rule_only", "personal_state_changed")
            return
        row = (
            guarded(db, job, beijing_now())
            .populate_existing()
            .with_for_update()
            .first()
        )
        if not row:
            db.rollback()
            return
        if any(
            (
                row.quality_feedback,
                row.done_at,
                effective_snooze(db, uid, cid, beijing_now().date()),
            )
        ):
            _stop(db, job, "rule_only", "feedback_recorded")
            return
        finished = beijing_now()
        row.status, row.lease_token, row.lease_expires_at, row.error_code = (
            "succeeded",
            None,
            None,
            None,
        )
        row.source_dependencies, row.token_usage = pack.dependencies, usage
        row.agent_trace = trace
        row.grade_hint = result["grade_hint"]
        for key, value in result["suggestion"].items():
            setattr(row, key, value)
        version = [day.isoformat(), row.run_seq]
        if not state.last_applied_run or state.last_applied_run < version:
            state.brief_prev_md, state.brief_prev_dependencies = (
                state.brief_md,
                state.brief_dependencies,
            )
            state.brief_prev_fingerprint, state.brief_prev_at = (
                state.brief_fingerprint,
                state.brief_at,
            )
            state.brief_md, state.brief_dependencies, state.brief_fingerprint = (
                result["brief_md"],
                pack.dependencies,
                digest(pack.dependencies),
            )
            state.brief_at, state.last_applied_run = finished, version
            # AI tags take effect immediately; codes the salesperson removed stay removed.
            removed = set(state.tag_overrides or [])
            state.ai_tags = [
                tag | {"run": version, "applied_at": finished.isoformat()}
                for tag in result["tags"]
                if tag["code"] not in removed
            ]
            state.profile_json = {
                "blocks": result["profile"],
                "coverage": {
                    "orders": len(source.get("orders") or []),
                    "messages": sum(1 for k in pack.refs if k.startswith("M-")),
                    "inquiries": sum(1 for k in pack.refs if k.startswith("AF-")),
                    "research": (source.get("research_report") or {}).get("status") == "ready",
                    "followups": sum(1 for k in pack.refs if k.startswith("F-")),
                },
                "generated_at": finished.isoformat(),
            }
            state.profile_dependencies = {"deps": pack.dependencies, "run": version}
            # Historical v1 output may update the manual profile only. It cannot
            # schedule rechecks, suppress future automatic analysis, or cool rules.
            if manual_only(pack.dependencies):
                db.commit()
                return
            if manual_only(personal.get("brief_dependencies")):
                # Old persisted state may predate the write-side policy guard.
                # Rebuild automatic state from this clean run, never its counters.
                state.recheck_count = 0
                state.activity_watermark = None
                state.rule_cooldowns = {}
            state.last_analyzed_at = finished
            watermark = source.get("activity_watermark")
            if state.activity_watermark != watermark:
                state.recheck_count = 0
            elif R3 in codes:
                state.recheck_count = (state.recheck_count or 0) + 1
            state.activity_watermark = watermark
            recheck = result["recheck"] if (state.recheck_count or 0) < 2 else None
            state.recheck_date = (
                date.fromisoformat(recheck["date"]) if recheck else None
            )
            state.recheck_condition = recheck["condition"] if recheck else None
            if row.priority == "skip":
                until = min(
                    finished.date() + timedelta(days=14),
                    date.fromisoformat(result["recheck"]["date"]),
                ).isoformat()
                state.rule_cooldowns = (state.rule_cooldowns or {}) | {
                    c: until for c in codes
                }
        db.commit()
    except HTTPException as exc:
        changed = exc.status_code in (403, 404, 409, 503)
        logger.warning(
            "private desk source access %s: HTTP %s", job[0], exc.status_code
        )
        print(
            f"[CLIENT_DESK] source access {job[0]}: HTTP {exc.status_code}", flush=True
        )
        _stop(
            db,
            job,
            "rule_only" if changed else "failed",
            "source_changed" if changed else "execution_failed",
        )
    except Exception as exc:
        status = "ambiguous" if called and not answered else "failed"
        logger.warning("private desk execution %s: %s", job[0], type(exc).__name__)
        print(f"[CLIENT_DESK] execution {job[0]}: {type(exc).__name__}", flush=True)
        _stop(
            db,
            job,
            status,
            "call_uncertain" if status == "ambiguous" else "execution_failed",
        )


def drain_queue(session_factory, limit=40):
    cfg = get_settings()
    if not cfg.CLIENT_DESK_ENABLED:
        return
    with session_factory() as db:
        recover_expired(db, beijing_now())
        user_ids = db.scalars(enrolled_user_ids(cfg)).all()
        db.commit()

    def worker(budget):
        with session_factory() as db:
            for _ in range(budget):
                job = claim(db, beijing_now())
                if not job:
                    break
                run_job(db, job)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(worker, [len(range(slot, limit, 3)) for slot in range(3)]))
    for uid in user_ids:
        with session_factory() as db:
            try:
                auto_done(db, uid)
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("private desk follow-up check: %s", type(exc).__name__)
                print(
                    f"[CLIENT_DESK] follow-up check: {type(exc).__name__}", flush=True
                )
