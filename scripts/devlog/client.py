# scripts/devlog/client.py
"""读取开发机本地配置（.devlog_state/collector.json，Git 忽略），调用生产机器端点。token 不进代码、不打印。"""
import json
import urllib.request
import urllib.parse
from pathlib import Path


def load_config(state: Path) -> dict | None:
    path = state / "collector.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("token"), str) or len(data["token"]) < 24:
        return None
    url = urllib.parse.urlsplit(data.get("base_url", ""))
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        return None
    return data


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OSError("Machine endpoint redirect refused")


def _request(config, method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(config["base_url"].rstrip("/") + path, data=data, method=method,
                                     headers={"X-Devlog-Token": config["token"], "Content-Type": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(config, path, body):
    return _request(config, "POST", path, body)


def get_json(config, path):
    return _request(config, "GET", path)
