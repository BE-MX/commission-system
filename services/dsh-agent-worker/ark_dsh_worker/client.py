"""Minimal Ark control-plane client; credentials never enter exceptions/logs."""

from __future__ import annotations

from typing import Any

import httpx

from .config import WorkerConfig


class ArkClientError(RuntimeError):
    pass


class AmbiguousSubmissionError(ArkClientError):
    pass


class ArkClient:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self._client = httpx.Client(
            timeout=config.request_timeout_seconds,
            follow_redirects=False,
            verify=True,
            headers={
                "Authorization": f"Bearer {config.worker_token}",
                "X-Agent-Worker-ID": config.worker_id,
                "User-Agent": "Leshine-Ark-DSH-Worker/0.1",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ArkClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        headers: dict | None = None,
        ambiguous_on_network: bool = False,
    ) -> Any:
        url = self.config.worker_api_url + path.lstrip("/")
        try:
            response = self._client.request(method, url, json=json_body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.RequestError as exc:
            error_type = AmbiguousSubmissionError if ambiguous_on_network else ArkClientError
            raise error_type(f"Ark {path} 网络请求失败: {type(exc).__name__}") from exc
        except (httpx.HTTPStatusError, ValueError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "invalid-json"
            raise ArkClientError(f"Ark {path} 返回无效响应: {status}") from exc
        if not isinstance(payload, dict) or payload.get("code") != 200:
            raise ArkClientError(f"Ark {path} 响应信封无效")
        return payload.get("data")

    def claim(self) -> dict | None:
        return self._request("POST", "runs/claim", json_body={
            "worker_id": self.config.worker_id,
            "runtimes": ["dsh"],
        })

    def context(self, run_id: int, lease_token: str) -> dict:
        return self._request("GET", f"runs/{run_id}/context", headers={"X-Agent-Lease-Token": lease_token})

    def heartbeat(self, run_id: int, lease_token: str, runtime_run_id: str | None, steps: int) -> dict:
        return self._request("POST", f"runs/{run_id}/heartbeat", json_body={
            "worker_id": self.config.worker_id,
            "lease_token": lease_token,
            "runtime_run_id": runtime_run_id,
            "steps_used": steps,
        })

    def events(self, run_id: int, lease_token: str, events: list[dict]) -> dict:
        return self._request("POST", f"runs/{run_id}/events", json_body={
            "worker_id": self.config.worker_id,
            "lease_token": lease_token,
            "events": events,
        })

    def complete(self, run_id: int, lease_token: str, payload: dict) -> dict:
        return self._request(
            "POST", f"runs/{run_id}/complete",
            json_body={"worker_id": self.config.worker_id, "lease_token": lease_token, **payload},
            ambiguous_on_network=True,
        )

    def fail(self, run_id: int, lease_token: str, code: str, message: str, *, ambiguous: bool) -> dict:
        return self._request("POST", f"runs/{run_id}/fail", json_body={
            "worker_id": self.config.worker_id,
            "lease_token": lease_token,
            "error_code": code[:64],
            "error_message": message[:1000],
            "ambiguous": ambiguous,
        })

