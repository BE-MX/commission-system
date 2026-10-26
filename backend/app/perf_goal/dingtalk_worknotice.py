"""绩效报告专用钉钉工作通知客户端（独立应用凭据，同步调用，供 APScheduler 工作线程使用）。

ENABLED=false 或发送失败时由调用方降级到群 webhook @，本模块不做降级决策。
"""
import logging
import time

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://oapi.dingtalk.com"


class WorknoticeError(RuntimeError):
    """钉钉返回的业务错误；系统繁忙可能发生在服务端已经投递之后。"""

    def __init__(self, errcode: int | str | None, errmsg: str | None):
        self.errcode = errcode
        self.errmsg = str(errmsg or "unknown")
        self.delivery_uncertain = (
            str(self.errcode) in {"130101", "-1"} and self.errmsg.strip() == "系统繁忙"
        )
        super().__init__(f"钉钉工作通知发送失败: {self.errmsg}")


def worknotice_configured(settings=None) -> bool:
    settings = settings or get_settings()
    return bool(settings.PERF_REPORT_WORKNOTICE_ENABLED
                and settings.PERF_REPORT_DINGTALK_APP_KEY
                and settings.PERF_REPORT_DINGTALK_APP_SECRET
                and settings.PERF_REPORT_DINGTALK_AGENT_ID)


class PerfWorknoticeClient:
    """企业内部应用工作通知（gettoken → asyncsend_v2），token 自动缓存。"""

    def __init__(self, app_key: str, app_secret: str, agent_id: str, timeout_sec: float = 10.0):
        self._app_key = app_key
        self._app_secret = app_secret
        self._agent_id = agent_id
        self._timeout = timeout_sec
        self._token: str | None = None
        self._token_expires: float = 0

    def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        try:
            with httpx.Client() as client:
                resp = client.get(f"{BASE_URL}/gettoken",
                                  params={"appkey": self._app_key, "appsecret": self._app_secret},
                                  timeout=self._timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            raise
        except httpx.HTTPError as exc:
            raise WorknoticeError(-1, type(exc).__name__) from None
        try:
            data = resp.json()
        except ValueError:
            raise WorknoticeError(-1, f"gettoken 返回非 JSON（HTTP {resp.status_code}）") from None
        if data.get("errcode") != 0:
            raise WorknoticeError(data.get("errcode", -1), data.get("errmsg", "获取token失败"))
        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 7200)
        return self._token

    def send_markdown(self, user_ids: list[str], title: str, markdown_text: str) -> dict:
        """向指定钉钉 userId 列表发送 markdown 工作通知。"""
        if not user_ids:
            raise WorknoticeError(-1, "缺少接收人")
        token = self.get_access_token()
        try:
            with httpx.Client() as client:
                resp = client.post(
                    f"{BASE_URL}/topapi/message/corpconversation/asyncsend_v2",
                    params={"access_token": token},
                    json={"agent_id": int(self._agent_id), "userid_list": ",".join(user_ids),
                          "msg": {"msgtype": "markdown",
                                  "markdown": {"title": title[:128], "text": markdown_text}}},
                    timeout=self._timeout + 5)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            raise
        except httpx.HTTPError as exc:
            raise WorknoticeError(-1, type(exc).__name__) from None
        try:
            data = resp.json()
        except ValueError:
            raise WorknoticeError(-1, f"工作通知返回非 JSON（HTTP {resp.status_code}）") from None
        if data.get("errcode", 0) != 0:
            logger.warning("perf worknotice rejected: errcode=%s", data.get("errcode"))
            raise WorknoticeError(data.get("errcode"), data.get("errmsg"))
        return data


def build_client(settings=None) -> PerfWorknoticeClient:
    settings = settings or get_settings()
    if not worknotice_configured(settings):
        raise RuntimeError("绩效报告工作通知未配置或未启用")
    return PerfWorknoticeClient(settings.PERF_REPORT_DINGTALK_APP_KEY,
                                settings.PERF_REPORT_DINGTALK_APP_SECRET,
                                settings.PERF_REPORT_DINGTALK_AGENT_ID)
