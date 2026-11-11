"""Client for the configured, restricted Singapore website fetch command."""

import base64
import codecs
import json
import re
import subprocess
from urllib.parse import urlsplit

from app.core.public_fetch import PublicResponse
from app.project_radar.singapore_worker import MAX_BODY_BYTES, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, TEXT_TYPES


def fetch_via_singapore(host, url, *, etag=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", host):
        raise ValueError("Invalid Singapore SSH host alias")
    payload = json.dumps({"url": url, "etag": etag}, ensure_ascii=True).encode("ascii")
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Singapore fetch request too large")
    # The dedicated key forces the worker. Without that restriction the command simply exits.
    result = subprocess.run(
        [
            "ssh", "-T", "-S", "none", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no", "-o", "IdentitiesOnly=yes", host, "/usr/bin/false",
        ],
        input=payload, capture_output=True, check=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise ValueError("Singapore fetch response too large")
    data = json.loads(result.stdout)
    status = data["status_code"]
    body = base64.b64decode(data["content"], validate=True)
    final = urlsplit(data["url"])
    content_type = data["content_type"]
    returned_etag = data["etag"]
    if (
        final.scheme != "https" or not final.hostname or final.username is not None
        or final.port not in {None, 443}
    ):
        raise ValueError("Invalid Singapore fetch final URL")
    valid_status = type(status) is int and (200 <= status < 300 or (status == 304 and etag and not body))
    if not valid_status or len(body) > MAX_BODY_BYTES or not isinstance(content_type, str):
        raise ValueError("Invalid Singapore fetch response")
    if returned_etag is not None and not isinstance(returned_etag, str):
        raise ValueError("Invalid Singapore fetch ETag")
    if status != 304 and content_type and not content_type.startswith(TEXT_TYPES):
        raise ValueError("Unsupported Singapore fetch content type")
    return PublicResponse(
        data["url"], status, body, content_type, codecs.lookup(data["encoding"]).name, returned_etag,
    )
