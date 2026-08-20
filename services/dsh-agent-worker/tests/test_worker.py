import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ark_dsh_worker.adapter import AdapterResult, DshSdkAdapter, DshUnavailableError
from ark_dsh_worker import adapter as adapter_module
from ark_dsh_worker.config import ConfigError, WorkerConfig
from ark_dsh_worker.events import EventNormalizer
from ark_dsh_worker.runner import Worker


def _config(tmp_path):
    return WorkerConfig.from_env({
        "ARK_BASE_URL": "http://localhost:8001",
        "ARK_AGENT_WORKER_ID": "test-worker",
        "ARK_AGENT_WORKER_TOKEN": "x" * 32,
        "ARK_DSH_SESSION_ROOT": str(tmp_path),
        "ARK_AGENT_HEARTBEAT_SECONDS": "60",
    })


class FakeClient:
    def __init__(self):
        self.next_seq = 3
        self.event_rows = []
        self.completed = None
        self.failed = None

    def claim(self):
        return {
            "run_id": 9, "session_id": 4, "profile_version": 1,
            "lease_token": "l" * 32, "run_token": "run.jwt.token",
            "next_sequence_no": 3,
        }

    def context(self, *_args):
        return {
            "run": {"id": 9, "input": {"question": "why"}, "business_ref_type": "customer", "business_ref_id": "12"},
            "session": {"id": 4},
            "profile": {
                "profile_key": "customer_order_copilot", "model": "deepseek-chat",
                "system_prompt": "facts only", "limits": {},
                "output_schema": {"type": "object"},
            },
        }

    def events(self, _run_id, _lease, events):
        self.event_rows.extend(events)
        self.next_seq = events[-1]["sequence_no"] + 1
        return {"next_sequence_no": self.next_seq}

    def complete(self, _run_id, _lease, payload):
        self.completed = payload
        return payload

    def fail(self, _run_id, _lease, code, message, *, ambiguous):
        self.failed = {"code": code, "message": message, "ambiguous": ambiguous}

    def heartbeat(self, *_args):
        return {"cancel_requested": False}


class FakeAdapter:
    def run(self, _context, _token, on_notification):
        events = [
            {"type": "step/start", "seq": 1, "data": {"turn": 1, "step": 1}},
            {"type": "tool/call", "seq": 2, "data": {
                "turn": 1, "step": 1, "callId": "c1", "name": "mcp__ark__search_knowledge",
                "arguments": '{"q":"secret customer"}',
            }},
            {"type": "tool/result", "seq": 3, "data": {
                "turn": 1, "step": 1, "message": {"toolCallId": "c1", "content": "private"},
            }},
        ]
        for event in events:
            on_notification(SimpleNamespace(
                method="session.event", payload={"sessionId": "s1", "event": event},
            ))
        content = {
            "summary": "结论", "key_findings": [], "risks": [],
            "recommended_actions": [],
            "evidence": [{"source": "search_knowledge", "tool_call_id": "c1"}],
            "open_questions": [],
        }
        return AdapterResult("dsh-9", json.dumps(content, ensure_ascii=False), "completed")


def test_worker_completes_structured_artifact_and_redacts_tool_arguments(tmp_path):
    client = FakeClient()
    worker = Worker(_config(tmp_path), client, FakeAdapter())
    assert worker.run_once() is True
    assert client.failed is None
    assert client.completed["artifacts"][0]["artifact_type"] == "copilot_answer"
    assert client.completed["steps_used"] == 1
    serialized = json.dumps(client.event_rows, ensure_ascii=False)
    assert "secret customer" not in serialized
    assert "arguments_sha256" in serialized


def test_event_normalizer_ignores_stream_chunks_and_keeps_usage_metadata():
    normalizer = EventNormalizer(1, 7)
    chunk = SimpleNamespace(method="session.event", payload={
        "sessionId": "s", "event": {"type": "assistant/chunk", "seq": 1, "data": {"text": "private"}},
    })
    assert normalizer.normalize(chunk) is None
    message = SimpleNamespace(method="session.event", payload={
        "sessionId": "s", "event": {"type": "assistant/message", "seq": 2, "data": {
            "turn": 1, "step": 1, "message": {"content": "private"},
            "usage": {"inputTokens": 10, "outputTokens": 4},
        }},
    })
    result = normalizer.normalize(message)
    assert result["event_type"] == "model.responded"
    assert result["payload"]["prompt_tokens"] == 10
    assert "private" not in json.dumps(result)


def test_config_rejects_cross_origin_mcp_token_forwarding(tmp_path):
    with pytest.raises(ConfigError, match="同源"):
        WorkerConfig.from_env({
            "ARK_BASE_URL": "https://ark.example",
            "ARK_MCP_URL": "https://evil.example/mcp",
            "ARK_AGENT_WORKER_ID": "worker",
            "ARK_AGENT_WORKER_TOKEN": "x" * 32,
            "ARK_DSH_SESSION_ROOT": str(tmp_path),
        })


def test_cordis_composition_has_no_local_execution_tools():
    text = (Path(__file__).resolve().parents[1] / "cordis.safe.yml").read_text()
    forbidden = ("tool-bash", "tool-jobs", "fs-local", "str-replace-editor", "agent-team")
    assert all(name not in text for name in forbidden)
    assert "dsh-mcp-client" in text


def test_sdk_preflight_fails_before_worker_can_claim(tmp_path, monkeypatch):
    def missing(_name):
        raise adapter_module.metadata.PackageNotFoundError

    monkeypatch.setattr(adapter_module.metadata, "version", missing)
    with pytest.raises(DshUnavailableError, match="尚未安装"):
        DshSdkAdapter(_config(tmp_path)).ensure_available()


def test_worker_stops_when_profile_step_limit_is_exceeded(tmp_path):
    class TooManyStepsAdapter:
        def run(self, _context, _token, on_notification):
            for seq in (1, 2):
                on_notification(SimpleNamespace(
                    method="session.event",
                    payload={"sessionId": "s1", "event": {
                        "type": "step/start", "seq": seq, "data": {"turn": 1, "step": seq},
                    }},
                ))
            return AdapterResult("never", "{}", "completed")

    client = FakeClient()
    worker = Worker(_config(tmp_path), client, TooManyStepsAdapter())
    assert worker.run_once() is True
    assert client.completed is None
    assert client.failed["code"] == "DSH_EXECUTION_FAILED"


def test_adapter_exports_the_validated_session_root(tmp_path, monkeypatch):
    captured = {}

    class FakeHarness:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def run(self, *_args, **_kwargs):
            return SimpleNamespace(final_response="{}", finish_reason="completed")

    adapter = DshSdkAdapter(_config(tmp_path))
    monkeypatch.setattr(adapter, "_sdk", lambda: FakeHarness)
    adapter.run({
        "run": {"id": 1, "input": {}, "business_ref_type": "customer", "business_ref_id": "1"},
        "session": {"id": 1},
        "profile": {"model": "deepseek-chat", "system_prompt": "facts", "limits": {}, "output_schema": {}},
    }, "run.jwt.token", lambda _event: None)
    assert captured["env"]["DSH_SESSION_ROOT"] == str(tmp_path)
