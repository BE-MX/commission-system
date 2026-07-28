"""微信小程序服务端接口客户端：access_token + 小程序码（wxacode.getUnlimited）

access_token 走 stable_token 接口：同参数幂等返回同一 token，不会把其他
调用方手里的 token 顶掉。注意它要求服务器出口 IP 在微信公众平台的
「IP 白名单」里——jscode2session 没这个要求，所以登录一直正常
不代表这里能通，首次部署报 40164 就是白名单没加。

同步 httpx：调用方（domestic router）是 sync def 端点，跑在线程池里，
不引入事件循环。
"""

import base64
import logging
import threading
import time

import httpx

from app.core.config import get_settings

logger = logging.getLogger("commission")
settings = get_settings()

_STABLE_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/stable_token"
_WXACODE_URL = "https://api.weixin.qq.com/wxa/getwxacodeunlimit"

_token_lock = threading.Lock()
_token_cache = {"value": "", "expires_at": 0.0}


class WxApiError(RuntimeError):
    """微信接口报错。message 面向使用者，直接透传给前端提示。"""


def get_access_token(force_refresh: bool = False) -> str:
    """取小程序全局 access_token，内存缓存、过期前 5 分钟主动换新。"""
    with _token_lock:
        if not force_refresh and _token_cache["value"] and time.time() < _token_cache["expires_at"]:
            return _token_cache["value"]

        if not settings.WX_MINI_APPID or not settings.WX_MINI_SECRET:
            raise WxApiError("未配置 WX_MINI_APPID / WX_MINI_SECRET，无法调用微信接口")

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(_STABLE_TOKEN_URL, json={
                    "grant_type": "client_credential",
                    "appid": settings.WX_MINI_APPID,
                    "secret": settings.WX_MINI_SECRET,
                    "force_refresh": force_refresh,
                })
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WxApiError(f"微信接口网络异常: {exc}") from exc

        if "access_token" not in data:
            errcode = data.get("errcode")
            hint = "（服务器出口 IP 未加入微信公众平台 IP 白名单）" if errcode == 40164 else ""
            raise WxApiError(f"获取微信 access_token 失败: {errcode} {data.get('errmsg')}{hint}")

        _token_cache["value"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 7200)) - 300
        return _token_cache["value"]


def get_wxacode_image(scene: str, page: str) -> tuple[bytes, str]:
    """生成小程序码，返回 (图片字节, MIME)。getUnlimited：数量不限、永久有效。

    正式版走 check_path=True：页面不存在时微信直接报错，宁可生成失败给出
    明确提示，也不发出一张扫开是白屏的坏码。体验版（trial）没法校验
    未发布的页面，只能 check_path=False。
    MIME 从响应头取——微信实际返回的是 image/jpeg，别硬编码 png。
    """
    env_version = settings.WX_MINI_ENV_VERSION or "release"
    body = {
        "scene": scene,
        "page": page,
        "check_path": env_version == "release",
        "env_version": env_version,
        "width": 430,
    }

    def _call(token: str) -> httpx.Response:
        try:
            with httpx.Client(timeout=15) as client:
                return client.post(f"{_WXACODE_URL}?access_token={token}", json=body)
        except httpx.HTTPError as exc:
            raise WxApiError(f"微信接口网络异常: {exc}") from exc

    def _image_of(resp: httpx.Response) -> tuple[bytes, str] | None:
        content_type = resp.headers.get("content-type", "")
        if content_type.startswith("image/"):
            return resp.content, content_type.split(";")[0]
        return None

    def _json_of(resp: httpx.Response) -> dict:
        try:
            return resp.json()
        except ValueError as exc:
            raise WxApiError(f"微信接口返回无法解析: {exc}") from exc

    # 成功返回图片二进制，失败返回 JSON——用 content-type 分辨
    resp = _call(get_access_token())
    image = _image_of(resp)
    if image:
        return image

    data = _json_of(resp)
    if data.get("errcode") in (40001, 42001):  # token 失效/被顶，强刷重试一次
        resp = _call(get_access_token(force_refresh=True))
        image = _image_of(resp)
        if image:
            return image
        data = _json_of(resp)

    errcode = data.get("errcode")
    hints = {
        41030: "页面在正式版中不存在——先发布包含进度页的小程序版本；体验期把 .env 的 WX_MINI_ENV_VERSION 设为 trial",
        40164: "服务器出口 IP 未加入微信公众平台 IP 白名单",
    }
    logger.warning("wxacode generate failed: %s %s", errcode, data.get("errmsg"))
    print(f"[mini] 小程序码生成失败: {errcode} {data.get('errmsg')}", flush=True)
    raise WxApiError(f"生成小程序码失败: {errcode} {data.get('errmsg')} {hints.get(errcode, '')}".rstrip())


def get_wxacode_base64(scene: str, page: str) -> str:
    content, mime = get_wxacode_image(scene, page)
    return f"data:{mime};base64," + base64.b64encode(content).decode()
