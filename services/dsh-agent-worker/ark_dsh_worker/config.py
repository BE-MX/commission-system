"""Environment-only worker configuration with origin and secret checks."""

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse


class ConfigError(ValueError):
    pass


def _positive_int(env: dict[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数") from exc
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0")
    return value


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


@dataclass(frozen=True)
class WorkerConfig:
    ark_base_url: str
    ark_mcp_url: str
    worker_id: str
    worker_token: str
    session_root: Path
    poll_seconds: int = 5
    heartbeat_seconds: int = 45
    request_timeout_seconds: int = 30
    session_retention_days: int = 90
    dsh_expected_version: str = "0.1.0rc8"

    @property
    def worker_api_url(self) -> str:
        return urljoin(self.ark_base_url + "/", "api/agent-runtime/worker/")

    @property
    def model_base_url(self) -> str:
        return urljoin(self.ark_base_url + "/", "api/agent-runtime/model/v1")

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "WorkerConfig":
        env = dict(os.environ if environ is None else environ)
        base = str(env.get("ARK_BASE_URL") or "").strip().rstrip("/")
        worker_id = str(env.get("ARK_AGENT_WORKER_ID") or "").strip()
        token = str(env.get("ARK_AGENT_WORKER_TOKEN") or "").strip()
        if not base or not worker_id or len(token) < 24:
            raise ConfigError("ARK_BASE_URL、ARK_AGENT_WORKER_ID 和至少 24 字符的 Worker Token 必填")
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
            raise ConfigError("ARK_BASE_URL 必须是无 query/fragment 的 HTTP(S) origin 或基础路径")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ConfigError("非本机 ARK_BASE_URL 必须使用 HTTPS")
        mcp = str(env.get("ARK_MCP_URL") or urljoin(base + "/", "mcp")).strip()
        if _origin(mcp) != _origin(base):
            raise ConfigError("ARK_MCP_URL 必须与 ARK_BASE_URL 同源，防止委托令牌被转发")
        root = Path(env.get("ARK_DSH_SESSION_ROOT") or ".ark-dsh-sessions").expanduser().resolve()
        return cls(
            ark_base_url=base,
            ark_mcp_url=mcp,
            worker_id=worker_id,
            worker_token=token,
            session_root=root,
            poll_seconds=_positive_int(env, "ARK_AGENT_POLL_SECONDS", 5),
            heartbeat_seconds=_positive_int(env, "ARK_AGENT_HEARTBEAT_SECONDS", 45),
            request_timeout_seconds=_positive_int(env, "ARK_AGENT_HTTP_TIMEOUT_SECONDS", 30),
            session_retention_days=_positive_int(env, "ARK_DSH_SESSION_RETENTION_DAYS", 90),
            dsh_expected_version=str(env.get("DSH_SDK_EXPECTED_VERSION") or "0.1.0rc8"),
        )

    def ensure_runtime_dirs(self) -> None:
        self.session_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.session_root, 0o700)
