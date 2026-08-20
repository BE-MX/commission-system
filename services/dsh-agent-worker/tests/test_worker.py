import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from ark_dsh_worker.adapter import AdapterResult, DshSdkAdapter, DshUnavailableError
from ark_dsh_worker import adapter as adapter_module
from ark_dsh_worker.config import ConfigError, WorkerConfig
from ark_dsh_worker.events import EventNormalizer
from ark_dsh_worker.runner import Worker
from ark_dsh_worker.retention import prune_expired_session_logs


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
                "turn": 1, "step": 1, "message": {
                    "source": {"kind": "tool", "callId": "c1"},
                    "content": [{
                        "type": "tool-result", "toolCallId": "c1", "isError": False,
                        "content": [{
                            "type": "text",
                            "text": '{"ok":true,"data":{"answer":"private"}}',
                        }],
                    }],
                },
            }},
        ]
        for event in events:
            on_notification(SimpleNamespace(
                method="session.event", payload={"sessionId": "s1", "event": event},
            ))
        content = {
            "summary": "结论", "key_findings": [{"text": "事实", "evidence_call_ids": ["c1"]}], "risks": [],
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
    assert "private" not in serialized
    assert "arguments_sha256" in serialized
    assert "result_sha256" in serialized


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


@pytest.mark.parametrize("content", [
    '{"ok":false,"error":"权限不足"}',
    [{"type": "text", "text": '{"ok":false,"error":"抓取失败"}'}],
    "not-an-ark-envelope",
])
def test_event_normalizer_never_marks_business_failure_as_successful_evidence(content):
    normalizer = EventNormalizer(1, 1)
    notification = SimpleNamespace(method="session.event", payload={
        "sessionId": "s", "event": {"type": "tool/result", "seq": 1, "data": {
            "message": {"toolCallId": "c-denied", "content": content},
        }},
    })
    result = normalizer.normalize(notification)
    assert result["event_type"] == "tool.failed"
    assert result["payload"]["call_id"] == "c-denied"
    assert result["payload"]["error_code"] in {"ARK_TOOL_ERROR", "INVALID_TOOL_RESULT"}
    assert "权限不足" not in json.dumps(result, ensure_ascii=False)
    assert "抓取失败" not in json.dumps(result, ensure_ascii=False)


def test_event_normalizer_reads_official_nested_result_and_call_id():
    normalizer = EventNormalizer(1, 1)
    notification = SimpleNamespace(method="session.event", payload={
        "sessionId": "s", "event": {"type": "tool/result", "seq": 1, "data": {
            "message": {
                "source": {"kind": "tool", "callId": "c-ok"},
                "content": [{
                    "type": "tool-result", "toolCallId": "c-ok", "isError": False,
                    "content": [{"type": "text", "text": '{"ok":true,"data":{"secret":"x"}}'}],
                }],
            },
        }},
    })
    result = normalizer.normalize(notification)
    assert result["event_type"] == "tool.succeeded"
    assert result["payload"]["call_id"] == "c-ok"
    assert "secret" not in json.dumps(result)


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


def test_release_builder_pins_the_reviewed_rc8_commit():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "build_dsh_release.sh").read_text()
    assert 'DSH_TAG="dsh-v0.1.0-rc.8"' in script
    assert 'DSH_COMMIT="141eb6fef83422698aef7a981029e843e8161534"' in script
    assert "--frozen-lockfile" in script
    assert "SHA256SUMS" in script
    assert "ARK_DSH_MANYLINUX_2_28_CONFIRMED" in script
    assert "SOURCE_DATE_EPOCH" in script
    assert "BUILD_PROVENANCE.json" in script
    assert "THIRD_PARTY_NOTICES.md" in script
    assert "release output directory must be empty" in script
    assert "ARK_DSH_PKG_BIN" in script
    assert "pnpm_release_wrapper.sh" in script
    assert "PNPM_CONFIG_OFFLINE=true" in script


def test_manylinux_release_workflow_is_pinned_and_runs_real_smoke():
    workflow = (
        Path(__file__).resolve().parents[3]
        / ".github" / "workflows" / "dsh-manylinux-release.yml"
    ).read_text()
    assert "quay.io/pypa/manylinux_2_28_x86_64@sha256:443eabd" in workflow
    assert "docker.io/library/rockylinux@sha256:c584db6" in workflow
    assert "node-v24.4.1-linux-x64.tar.xz" in workflow
    assert "pnpm-11.7.0.tgz" in workflow
    assert "uv-0.8.12.tar.gz" in workflow
    assert "--frozen-lockfile --ignore-scripts" in workflow
    assert "verify_dsh_release.py" in workflow
    assert "RUN_REAL_DSH_SMOKE=1" in workflow
    assert "--require-hashes" in workflow
    assert "chmod -R a-w" in workflow
    assert "needs: smoke" in workflow
    assert "actions/attest-build-provenance@96b4a1ef7235a096b17240c259729fdd70c83d45" in workflow
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in workflow


def test_release_toolchain_locks_pkg_and_all_transitive_integrities():
    root = Path(__file__).resolve().parents[1] / "release-toolchain"
    package = json.loads((root / "package.json").read_text())
    lock = (root / "pnpm-lock.yaml").read_text()
    assert package["dependencies"] == {"@yao-pkg/pkg": "6.21.0"}
    assert "'@yao-pkg/pkg@6.21.0':" in lock
    assert lock.count("integrity: sha512-") > 100


def test_sdk_preflight_fails_before_worker_can_claim(tmp_path, monkeypatch):
    def missing(_name):
        raise adapter_module.metadata.PackageNotFoundError

    monkeypatch.setattr(adapter_module.metadata, "version", missing)
    with pytest.raises(DshUnavailableError, match="尚未安装"):
        DshSdkAdapter(_config(tmp_path)).ensure_available()


def test_sdk_preflight_rejects_mixed_sdk_and_runtime_versions(tmp_path, monkeypatch):
    actual_version = adapter_module.metadata.version

    def mixed(name):
        if name == "deepseek-harness-sdk":
            return "0.1.0rc8"
        if name == "deepseek-harness-runtime-bin":
            return "0.1.0rc7"
        return actual_version(name)

    monkeypatch.setattr(adapter_module.metadata, "version", mixed)
    monkeypatch.setitem(sys.modules, "deepseek_harness", SimpleNamespace(DeepSeekHarness=object))
    with pytest.raises(DshUnavailableError, match="SDK/Runtime 版本不匹配"):
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


def test_worker_does_not_expose_arbitrary_runtime_exception_text(tmp_path):
    class LeakyAdapter:
        def run(self, _context, _token, _on_notification):
            raise ValueError("upstream leaked secret=/private/runtime/token")

    client = FakeClient()
    worker = Worker(_config(tmp_path), client, LeakyAdapter())
    assert worker.run_once() is True
    assert client.failed["message"] == "DSH Worker 执行失败 (ValueError)"
    assert "secret" not in client.failed["message"]


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


def test_session_retention_only_removes_old_regular_jsonl(tmp_path):
    old = tmp_path / "project" / "session-old" / "session.jsonl"
    fresh = tmp_path / "project" / "session-fresh" / "session.jsonl"
    old.parent.mkdir(parents=True)
    fresh.parent.mkdir(parents=True)
    old.write_text("old raw event")
    fresh.write_text("fresh raw event")
    cutoff_age = time.time() - 91 * 86_400
    os.utime(old, (cutoff_age, cutoff_age))
    link = tmp_path / "linked" / "session.jsonl"
    link.parent.mkdir()
    link.symlink_to(fresh)

    assert prune_expired_session_logs(tmp_path, retention_days=90) == 1
    assert not old.exists()
    assert fresh.read_text() == "fresh raw event"
    assert link.is_symlink()
