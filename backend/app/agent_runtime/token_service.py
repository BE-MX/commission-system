"""Short-lived delegated JWTs for a single Agent Run."""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.agent_runtime.errors import ForbiddenError
from app.agent_runtime.models import AgentProfile, AgentRun
from app.core.config import get_settings


_AUDIENCE = "ark-agent-run"
_ISSUER = "ark-agent-control-plane"


def _secret() -> str:
    settings = get_settings()
    return settings.AGENT_RUNTIME_RUN_TOKEN_SECRET or settings.JWT_SECRET_KEY


def create_run_token(run: AgentRun, profile: AgentProfile, *, ttl_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "sub": str(run.owner_user_id),
        "run_id": run.id,
        "session_id": run.session_id,
        "profile_id": profile.id,
        "profile_key": profile.profile_key,
        "runtime": run.source_runtime,
        "tools": list(profile.tool_allowlist or []),
        "permissions": list((run.context_snapshot or {}).get("permissions") or []),
    }
    settings = get_settings()
    return jwt.encode(payload, _secret(), algorithm=settings.JWT_ALGORITHM)


def decode_run_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            _secret(),
            algorithms=[settings.JWT_ALGORITHM],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except JWTError as exc:
        raise ForbiddenError("Agent Run 委托令牌无效或已过期") from exc

