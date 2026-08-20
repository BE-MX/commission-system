"""Opt-in smoke against the official bundled DeepSeek Harness runtime.

Run with::

    RUN_REAL_DSH_SMOKE=1 pytest -q \
      services/dsh-agent-worker/tests/test_real_runtime_integration.py

The fixture is entirely local: it exposes an OpenAI-compatible SSE route and
a stateless MCP tool on one origin, then drives Ark's production adapter and
Cordis composition through the official SDK/runtime binary.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import multiprocessing
import os
from pathlib import Path
import socket
import time

import pytest
from starlette.requests import Request


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_DSH_SMOKE") != "1",
    reason="set RUN_REAL_DSH_SMOKE=1 after installing official DSH wheels",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve_ark_fixture(port: int, capture_path: str) -> None:
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    import uvicorn

    mcp = FastMCP(
        "ark-dsh-smoke",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(name="search_knowledge")
    def search_knowledge(query: str) -> str:
        return json.dumps({
            "ok": True,
            "data": {"query": query, "answer": "verified smoke evidence"},
        })

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    @app.post("/api/agent-runtime/model/v1/chat/completions")
    async def completions(request: Request):
        body = await request.json()
        snapshot = {
            "authorization": request.headers.get("authorization"),
            "body": body,
        }
        with Path(capture_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        has_tool_result = any(item.get("role") == "tool" for item in body.get("messages") or [])

        async def chunks():
            if not has_tool_result:
                payloads = [
                    {"choices": [{"delta": {
                        "role": "assistant",
                        "content": None,
                        "reasoning_content": "",
                        "tool_calls": [{
                            "index": 0,
                            "id": "smoke-call-1",
                            "type": "function",
                            "function": {
                                "name": "mcp__ark__search_knowledge",
                                "arguments": '{"query":"runtime smoke"}',
                            },
                        }],
                    }, "finish_reason": None}]},
                    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {
                        "prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14,
                    }},
                ]
            else:
                result = json.dumps({
                    "summary": "真实 DSH Runtime 已完成受控工具调用",
                    "key_findings": [{
                        "text": "MCP 返回 verified smoke evidence",
                        "evidence_call_ids": ["smoke-call-1"],
                    }],
                    "risks": [],
                    "recommended_actions": [{
                        "text": "继续灰度业务验收",
                        "evidence_call_ids": ["smoke-call-1"],
                    }],
                    "evidence": [{
                        "source": "search_knowledge",
                        "tool_call_id": "smoke-call-1",
                    }],
                    "open_questions": [],
                }, ensure_ascii=False)
                payloads = [
                    {"choices": [{"delta": {
                        "role": "assistant", "content": result, "reasoning_content": "",
                    }, "finish_reason": None}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {
                        "prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26,
                    }},
                ]
            for payload in payloads:
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    app.mount("/mcp", mcp_app)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _wait_for_port(port: int, process, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process.is_alive():
            raise RuntimeError("Ark smoke fixture exited during startup")
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError("Ark smoke fixture did not start")


def test_official_runtime_executes_ark_cordis_model_and_mcp_contract(tmp_path):
    from importlib import metadata

    from ark_dsh_worker.adapter import DshSdkAdapter
    from ark_dsh_worker.config import WorkerConfig
    from ark_dsh_worker.events import EventNormalizer

    assert metadata.version("deepseek-harness-sdk") == "0.1.0rc8"
    assert metadata.version("deepseek-harness-runtime-bin") == "0.1.0rc8"
    port = _free_port()
    capture = tmp_path / "model-requests.jsonl"
    method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    process = multiprocessing.get_context(method).Process(
        target=_serve_ark_fixture,
        args=(port, str(capture)),
        daemon=True,
    )
    process.start()
    try:
        _wait_for_port(port, process)
        config = WorkerConfig.from_env({
            "ARK_BASE_URL": f"http://127.0.0.1:{port}",
            "ARK_MCP_URL": f"http://127.0.0.1:{port}/mcp",
            "ARK_AGENT_WORKER_ID": "real-dsh-smoke",
            "ARK_AGENT_WORKER_TOKEN": "w" * 32,
            "ARK_DSH_SESSION_ROOT": str(tmp_path / "sessions"),
            "DSH_SDK_EXPECTED_VERSION": "0.1.0rc8",
        })
        context = {
            "run": {
                "id": 901,
                "input": {"question": "验证真实 DSH Runtime"},
                "business_ref_type": "customer_profile",
                "business_ref_id": "1",
            },
            "session": {"id": 902},
            "profile": {
                "profile_key": "customer_order_copilot",
                "model": "ark-smoke-model",
                "system_prompt": "只能使用授权工具，并输出符合 schema 的 JSON。",
                "limits": {"max_output_tokens": 2000, "timeout_seconds": 60},
                "output_schema": {"type": "object"},
            },
        }
        notifications = []
        result = DshSdkAdapter(config).run(
            context,
            "header.payload.signature",
            notifications.append,
        )
    finally:
        process.terminate()
        process.join(timeout=5)

    if result.finish_reason != "completed":
        print("RESULT", result)
        print("REQUESTS", capture.read_text() if capture.exists() else None)
        for notification in notifications:
            print("NOTIFICATION", notification)
    assert result.finish_reason == "completed", {
        "result": result,
        "notifications": notifications,
        "requests": capture.read_text() if capture.exists() else None,
        "sessions": [str(path) for path in (tmp_path / "sessions").rglob("*")],
    }
    parsed = json.loads(result.final_response)
    assert parsed["evidence"] == [{
        "source": "search_knowledge",
        "tool_call_id": "smoke-call-1",
    }]
    requests = [json.loads(line) for line in capture.read_text().splitlines()]
    assert len(requests) == 2
    assert all(item["authorization"] == "Bearer header.payload.signature" for item in requests)
    assert requests[0]["body"]["model"] == "ark-smoke-model"
    assert [item["role"] for item in requests[1]["body"]["messages"]][-2:] == ["assistant", "tool"]

    normalizer = EventNormalizer(901, 1)
    events = [normalizer.normalize(item) for item in notifications]
    events = [item for item in events if item is not None]
    event_types = {item["event_type"] for item in events}
    assert {"model.requested", "model.responded", "tool.requested", "tool.succeeded"} <= event_types, {
        "events": events,
        "notifications": notifications,
    }
    assert "verified smoke evidence" not in json.dumps(events, ensure_ascii=False)
    assert list((tmp_path / "sessions").rglob("*.jsonl"))
