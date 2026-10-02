"""排程侧车 HTTP 客户端：POST /schedule/preview，失败可降级为手动指定时间。

排程算法唯一实现位于 Node 侧车（outreach-schedule.mjs），这里只做薄封装；
HTTP 客户端用项目已有的 httpx（requirements.txt 已声明）。
"""

import httpx

from app.core.config import get_settings
from app.mail_outreach import policies
from app.mail_outreach.errors import unavailable


def preview_schedule(payload: dict) -> dict:
    """调用排程侧车预览候选发送时间；侧车不可达/拒绝一律抛域错误。"""
    settings = get_settings()
    base_url = (settings.MAIL_OUTREACH_SCHEDULE_SERVICE_URL or "").strip()
    if not base_url:
        raise unavailable(
            "排程服务未配置，可改用手动指定时间",
            error_code="schedule_service_unavailable",
        )
    headers = {}
    if settings.MAIL_OUTREACH_SCHEDULE_TOKEN:
        headers["Authorization"] = f"Bearer {settings.MAIL_OUTREACH_SCHEDULE_TOKEN}"
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/schedule/preview",
            json={
                {"language_source": "languageSource", "language_basis": "languageBasis", "office_start": "officeStart"}.get(key, key): value
                for key, value in payload.items() if value is not None
            },
            headers=headers,
            timeout=policies.SCHEDULE_SERVICE_TIMEOUT_SEC,
        )
    except httpx.HTTPError as exc:
        raise unavailable(
            f"排程服务不可达：{type(exc).__name__}",
            error_code="schedule_service_unavailable",
        ) from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise unavailable("排程服务返回非 JSON", error_code="schedule_service_error") from exc
    if response.status_code != 200 or not isinstance(data, dict) or not data.get("ok"):
        sidecar_message = ((data.get("error") or {}).get("message") or data.get("message")) if isinstance(data, dict) else None
        raise unavailable(
            f"排程预览被拒绝：{sidecar_message or '未知原因'}",
            error_code="schedule_preview_rejected" if response.status_code < 500 else "schedule_service_error",
        )
    result = data.get("data", data)
    if not isinstance(result, dict):
        raise unavailable("排程返回结构不正确", error_code="schedule_service_error")
    keys = {"scheduledAtUtc": "scheduled_at_utc", "scheduledAtLocal": "scheduled_at_local", "officeStart": "office_start", "localDate": "local_date"}
    normalized = {keys.get(key, key): value for key, value in result.items()}
    if not normalized.get("scheduled_at_utc"):
        raise unavailable("排程缺少发送时间", error_code="schedule_service_error")
    return {**normalized, "ok": True}


__all__ = ["preview_schedule"]
