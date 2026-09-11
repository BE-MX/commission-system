"""Opt-in pytest plugin: real reply facade, synthetic data, memory-only writes.

Usage (only after explicit paid-test approval), from backend:
python -m pytest -p scripts.whatsapp_reply_evaluation
tests/test_whatsapp_reply_model_evaluation.py --reply-eval-paid
--reply-eval-env PATH_TO_EXISTING_ENV -s -q

At most 30 scenarios / 60 text calls per invocation. No automatic retry.
Printed results contain only case IDs, statuses, latency and token counts.
This is a technical baseline, not a substitute for business-owner blind review.
"""

import json
import time
import math
import statistics
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.bootstrap.seed_whatsapp_reply import reply_parameters
from app.core.config import Settings
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.reply_service import suggest_reply
from scripts.whatsapp_reply_cases import generate_cases


def pytest_addoption(parser):
    parser.addoption("--reply-eval-paid", action="store_true", help="Explicitly allow at most 60 paid synthetic text calls")
    parser.addoption("--reply-eval-env", type=Path, help="Existing provider configuration; database is opened read-only")
    parser.addoption("--reply-eval-case", action="append", default=[], help="Run only a named synthetic case; repeat for a bounded diagnostic subset")


def load_provider_configuration(path):
    settings = Settings(_env_file=path)
    engine = create_engine(settings.commission_db_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
            connection.commit()
            with Session(bind=connection) as db:
                row = db.query(AiPreset, AiProvider).join(AiProvider, AiPreset.provider_id == AiProvider.id).filter(
                    AiPreset.preset_name == settings.WHATSAPP_TRANSLATION_PRESET_NAME,
                    AiPreset.deleted_at.is_(None), AiPreset.is_enabled.is_(True),
                    AiProvider.deleted_at.is_(None), AiProvider.is_enabled.is_(True),
                    AiProvider.provider_type == "direct",
                ).one()
                preset, provider = row
                # Encrypted credential stays in process memory; never print or
                # serialize this mapping or the Settings object.
                result = {
                    "provider": {key: getattr(provider, key) for key in (
                        "api_base", "api_key", "api_type", "extra_headers", "timeout_sec",
                    )},
                    "model": preset.model,
                    "parameters": {key: value for key, value in (preset.parameters or {}).items()
                                   if key in {"temperature", "top_p", "thinking", "reasoning_effort", "response_format"}},
                    "encryption_key": settings.ARK_AI_ENCRYPTION_KEY,
                }
                db.rollback()
                return result
    finally:
        engine.dispose()


def install_memory_provider(db, configuration, settings, monkeypatch):
    if db.get_bind().url.drivername != "sqlite" or db.get_bind().url.database != ":memory:":
        raise ValueError("evaluation writes require in-memory SQLite")
    from app.ai import keyring
    provider = db.query(AiProvider).filter_by(name="synthetic-reply").one()
    for key, value in configuration["provider"].items():
        setattr(provider, key, value)
    for name, cap in ((settings.WHATSAPP_REPLY_GENERATOR_PRESET, 3200),):
        preset = db.query(AiPreset).filter_by(preset_name=name).one()
        preset.model = configuration["model"]
        preset.parameters = reply_parameters(configuration["parameters"], cap, configuration["provider"]["api_type"])
    db.commit()
    monkeypatch.setattr(settings, "ARK_AI_ENCRYPTION_KEY", configuration["encryption_key"])
    monkeypatch.setattr(keyring, "_ARK_AI_ENCRYPTION_KEY", None)
    # Only the isolated test account's rate allowance changes, never production.
    monkeypatch.setattr(settings, "WHATSAPP_REPLY_RATE_PER_MINUTE", 30)


def install_metadata_diagnostics(monkeypatch):
    from app.whatsapp_translation import reply_direct
    original = reply_direct._object
    def parse(content):
        try:
            return original(content)
        except WhatsAppTranslationError:
            print(json.dumps({"reply_diagnostic": {"kind": "invalid_json_object", "chars": len(content) if isinstance(content, str) else 0}}), flush=True)
            raise
    monkeypatch.setattr(reply_direct, "_object", parse)


def evaluate_cases(db, identity, make_request, case_ids=None):
    if db.get_bind().url.drivername != "sqlite" or db.get_bind().url.database != ":memory:":
        raise ValueError("evaluation requires in-memory SQLite")
    rows = []
    cases = generate_cases()
    if case_ids:
        if set(case_ids) - {case.case_id for case in cases}:
            raise ValueError("unknown synthetic case")
        cases = [case for case in cases if case.case_id in case_ids]
    for case in cases:
        request = make_request(
            messages=[{"role": role, "text": text} for role, text in case.messages],
            target_language=case.language, style=case.style,
            context_scope={"requested_limit": 20, "latest_visible": False, "omitted_media": case.omitted_media},
        )
        started = time.monotonic()
        try:
            response = suggest_reply(db, identity, request)
            status = response.status
        except WhatsAppTranslationError as exc:
            status = exc.error_code
        rows.append({"case_id": case.case_id, "status": status, "duration_ms": round((time.monotonic() - started) * 1000)})
    logs = db.query(AiCallLog).all()
    durations = sorted(row["duration_ms"] for row in rows)
    summary = {
        "cases": rows, "calls": len(logs), "tokens": sum(log.tokens_used or 0 for log in logs),
        "median_ms": statistics.median(durations), "p95_ms": durations[math.ceil(len(durations) * .95) - 1],
        "semantic_review": "pending_business_owner_blind_review",
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary
