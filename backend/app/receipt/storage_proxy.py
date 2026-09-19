"""Forward private images to the configured canonical storage backend."""
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from fastapi.responses import Response

from app.core.config import get_settings

HOP_HEADER = "X-Ark-Receipt-Proxy-Hop"


def origin():
    from app.core.storage.files import managed
    if managed('receipt-proofs'):
        return ''
    value = get_settings().RECEIPT_STORAGE_PROXY_URL.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, "回款凭证存储入口配置无效")
    return value


def forward(request, path, content=None, filename=None):
    target = origin()
    if not target:
        return None
    if request.headers.get(HOP_HEADER):
        raise HTTPException(503, "回款凭证存储入口形成循环，请联系管理员")
    headers = {"Authorization": request.headers.get("authorization", ""), HOP_HEADER: "1"}
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            if content is None:
                upstream = client.get(target + path, headers=headers)
            else:
                upstream = client.post(target + path, headers=headers,
                                       files={"file": (filename or "receipt", content, "application/octet-stream")})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "回款凭证存储入口暂不可用，请稍后重试") from exc
    if upstream.status_code >= 300:
        # Never expose upstream HTML, redirects or infrastructure diagnostics.
        status = upstream.status_code if upstream.status_code in {401, 403, 404, 409, 413, 422} else 503
        raise HTTPException(status, "回款凭证请求未完成，请检查文件或稍后重试")
    return Response(upstream.content, status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type", "application/octet-stream"),
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
