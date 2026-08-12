"""Contracts for the least-privilege cron/systemd heartbeat reporter."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "runtime_heartbeat.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("runtime_heartbeat_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_one_shot_cron_requires_stable_started_at(monkeypatch):
    module = _load_script()
    monkeypatch.setenv("ARK_OPERATIONS_BASE_URL", "https://leshine.work")
    monkeypatch.setenv("ARK_HEARTBEAT_TOKEN", "x" * 32)
    monkeypatch.setenv("ARK_RUNTIME_SERVICE_ID", "shopify-sync")
    monkeypatch.setenv("ARK_RUNTIME_SERVICE_NAME", "Shopify 定时同步")
    monkeypatch.delenv("ARK_RUNTIME_STARTED_AT", raising=False)

    with pytest.raises(ValueError, match="ARK_RUNTIME_STARTED_AT"):
        module.send_once(require_stable_started_at=True)
