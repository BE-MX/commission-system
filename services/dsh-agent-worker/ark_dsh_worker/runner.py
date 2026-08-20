"""One-at-a-time leased worker loop with heartbeat and terminal-state safety."""

from __future__ import annotations

import json
import logging
import re
import threading
import time

from .adapter import AdapterResult, HarnessAdapter
from .client import AmbiguousSubmissionError, ArkClient, ArkClientError
from .config import WorkerConfig
from .events import EventNormalizer


logger = logging.getLogger("ark_dsh_worker")
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)
_ARTIFACT_TYPES = {
    "customer_order_copilot": "copilot_answer",
    "repurchase_risk_analyst": "repurchase_action_card",
    "sales_discovery_shadow": "sales_discovery_shadow_result",
}


class RunCancelled(RuntimeError):
    pass


def _parse_artifact(text: str) -> dict:
    match = _FENCE_RE.match(text or "")
    raw = match.group(1) if match else (text or "").strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("DSH 最终响应不是合法 JSON 成果") from exc
    if not isinstance(value, dict):
        raise ValueError("DSH 最终成果必须是 JSON 对象")
    return value


def _evidence(content: dict) -> list[dict]:
    direct = content.get("evidence")
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, dict)]
    candidates = content.get("candidates")
    if isinstance(candidates, list):
        return [
            {
                "source_url": item.get("source_url"),
                "source": item.get("source") or "fetch_public_page",
                "tool_call_id": item.get("tool_call_id"),
            }
            for item in candidates
            if isinstance(item, dict) and item.get("source_url")
        ]
    return []


class Worker:
    def __init__(self, config: WorkerConfig, client: ArkClient, adapter: HarnessAdapter):
        self.config = config
        self.client = client
        self.adapter = adapter

    def run_once(self) -> bool:
        claim = self.client.claim()
        if claim is None:
            return False
        run_id = int(claim["run_id"])
        lease_token = claim["lease_token"]
        try:
            self._execute(claim)
        except AmbiguousSubmissionError:
            self._safe_fail(run_id, lease_token, "COMPLETE_SUBMISSION_AMBIGUOUS", "成果提交结果不确定，禁止自动重试", True)
        except RunCancelled:
            self._safe_fail(run_id, lease_token, "CANCEL_REQUESTED", "任务已由用户取消", False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DSH run %s failed: %s", run_id, type(exc).__name__)
            self._safe_fail(run_id, lease_token, "DSH_EXECUTION_FAILED", _safe_message(exc), False)
        return True

    def _execute(self, claim: dict) -> None:
        run_id = int(claim["run_id"])
        lease_token = claim["lease_token"]
        context = self.client.context(run_id, lease_token)
        normalizer = EventNormalizer(run_id, int(claim["next_sequence_no"]))
        limits = context["profile"].get("limits") or {}
        max_steps = int(limits.get("max_steps") or 1)
        timeout_seconds = int(limits.get("timeout_seconds") or 300)
        deadline = time.monotonic() + timeout_seconds
        start_event = {
            "sequence_no": normalizer.next_sequence,
            "event_id": f"dsh-{run_id}-{normalizer.next_sequence}",
            "event_type": "run.started",
            "schema_version": 1,
            "actor_type": "runtime",
            "visibility": "user",
            "payload": {"runtime": "dsh", "profile_version": claim["profile_version"]},
            "source_event_ids": [],
        }
        response = self.client.events(run_id, lease_token, [start_event])
        normalizer.next_sequence = int(response["next_sequence_no"])

        cancelled = threading.Event()
        finished = threading.Event()
        runtime_id = f"dsh-run-{run_id}-attempt"
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(run_id, lease_token, runtime_id, normalizer, cancelled, finished),
            daemon=True,
        )
        heartbeat.start()

        def on_notification(notification) -> None:
            if cancelled.is_set():
                raise RunCancelled("任务已请求取消")
            if time.monotonic() > deadline:
                raise ValueError("DSH 执行时间超过 Profile 限制")
            event = normalizer.normalize(notification)
            if event is not None:
                if normalizer.steps > max_steps:
                    raise ValueError("DSH 步骤数超过 Profile 限制")
                response = self.client.events(run_id, lease_token, [event])
                normalizer.next_sequence = int(response["next_sequence_no"])

        try:
            result = self.adapter.run(context, claim["run_token"], on_notification)
        finally:
            finished.set()
            heartbeat.join(timeout=min(self.config.heartbeat_seconds, 5))
        if cancelled.is_set():
            raise RunCancelled("任务已请求取消")
        if time.monotonic() > deadline:
            raise ValueError("DSH 执行时间超过 Profile 限制")
        if result.finish_reason != "completed":
            raise ValueError(f"DSH 未正常完成: {result.finish_reason or 'unknown'}")
        content = _parse_artifact(result.final_response)
        profile_key = context["profile"]["profile_key"]
        artifact_type = _ARTIFACT_TYPES.get(profile_key)
        if artifact_type is None:
            raise ValueError(f"未配置成果类型的 Profile: {profile_key}")
        self.client.complete(run_id, lease_token, {
            "runtime_run_id": result.runtime_run_id,
            "artifacts": [{
                "artifact_type": artifact_type,
                "schema_version": 1,
                "title": context["profile"].get("name") or context["profile"].get("profile_key"),
                "content": content,
                "evidence": _evidence(content),
            }],
            "steps_used": normalizer.steps,
            "prompt_tokens": normalizer.prompt_tokens,
            "completion_tokens": normalizer.completion_tokens,
            "cost_usd": "0",
        })

    def _heartbeat_loop(self, run_id, lease_token, runtime_id, normalizer, cancelled, finished) -> None:
        while not finished.wait(self.config.heartbeat_seconds):
            try:
                result = self.client.heartbeat(run_id, lease_token, runtime_id, normalizer.steps)
                if result.get("cancel_requested"):
                    cancelled.set()
                    return
            except ArkClientError as exc:
                logger.warning("DSH heartbeat failed for run %s: %s", run_id, type(exc).__name__)
                cancelled.set()
                return

    def _safe_fail(self, run_id: int, lease_token: str, code: str, message: str, ambiguous: bool) -> None:
        try:
            self.client.fail(run_id, lease_token, code, message, ambiguous=ambiguous)
        except ArkClientError as exc:
            logger.error("Could not submit terminal failure for run %s: %s", run_id, type(exc).__name__)

    def serve_forever(self) -> None:
        while True:
            worked = self.run_once()
            if not worked:
                time.sleep(self.config.poll_seconds)


def _safe_message(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        return str(exc)[:1000]
    return f"DSH Worker 执行失败 ({type(exc).__name__})"
