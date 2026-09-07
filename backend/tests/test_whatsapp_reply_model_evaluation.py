"""Skipped in ordinary tests; never interprets passing structure as sales quality."""

import pytest

from scripts.whatsapp_reply_evaluation import evaluate_cases, install_memory_provider, load_provider_configuration
from tests.reply_support import request, seed_reply


def test_opt_in_real_reply_baseline(db, monkeypatch, pytestconfig):
    if not pytestconfig.getoption("--reply-eval-paid", default=False):
        pytest.skip("paid model baseline requires explicit opt-in")
    path = pytestconfig.getoption("--reply-eval-env", default=None)
    if path is None or not path.is_file():
        pytest.fail("an existing provider environment file is required", pytrace=False)
    identity, _, _, _, _, settings = seed_reply(db, monkeypatch)
    configuration = load_provider_configuration(path)
    install_memory_provider(db, configuration, settings, monkeypatch)
    summary = evaluate_cases(db, identity, request)
    assert summary["calls"] <= 60
    assert len(summary["cases"]) == 30
    assert all(row["status"] in {"ready", "needs_confirmation", "insufficient_context"} for row in summary["cases"]), "technical failures present; inspect metadata summary"
