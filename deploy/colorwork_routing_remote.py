"""Scoped Nginx preparation/activation; no application or database writes."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid
import urllib.request

SPECS = {
    "office": ("/etc/nginx/conf.d/leshine.conf", "8002", 1),
    "cloud": ("/etc/nginx/sites-enabled/ark-cloud.conf", "8001", 2),
}
BEGIN = "# BEGIN ARK COLORWORK ROUTING"
END = "# END ARK COLORWORK ROUTING"
STATE = Path("/etc/nginx/.ark-backups/colorwork")


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


def render(original, snippet, region):
    _, port, expected = SPECS[region]
    # Replace only our blocks. Unknown layout or conflicting rules must be reviewed.
    clean = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", original, flags=re.S)
    if BEGIN in clean or END in clean or "/api/colorwork/" in clean:
        raise ValueError("Conflicting colorwork routing; inspect the current configuration")
    anchor = re.compile(r"location /api/\s*\{\s*proxy_pass http://127\.0\.0\.1:" + port + r";")
    if len(anchor.findall(clean)) != expected:
        raise ValueError("Unexpected API upstream layout")
    block = BEGIN + "\n" + snippet.strip() + "\n" + END + "\n"
    return anchor.sub(lambda match: block + match.group(0), clean)


def run(args):
    subprocess.run(args, check=True, stdout=sys.stderr, stderr=sys.stderr, timeout=30)


def healthy(region):
    domain = "leshine.cloud" if region == "cloud" else "leshine.work"
    url = "https://" + domain + "/api/colorwork/workbench/api/health"
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200 or json.load(response) != {"status": "ok", "module": "colorwork"}:
            raise RuntimeError("Colorwork readiness failed: " + domain)


def execute(request):
    region = request["region"]
    path = Path(SPECS[region][0]).resolve()
    if not path.is_relative_to("/etc/nginx"):
        raise ValueError("Nginx configuration escaped /etc/nginx")
    original = path.read_text()
    candidate = render(original, request["snippet"], region)
    baseline = digest(original)
    if request["action"] == "prepare":
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Syntax validation uses a separate config and never reloads live workers.
        check = STATE / (region + "-syntax.conf")
        check.write_text("events {}\nhttp { server { listen 127.0.0.1:18979;\n"
                         + request["snippet"] + "\n} }\n")
        run(["nginx", "-t", "-c", str(check)])
        candidate_path = STATE / (region + "-candidate.conf")
        candidate_path.write_text(candidate)
        return {"region": region, "status": "prepared", "baseline": baseline,
                "candidate": digest(candidate), "changed": candidate != original}
    if request["action"] != "activate":
        raise ValueError("Unknown routing action")
    if baseline != request["baseline"] or digest(candidate) != request["candidate"]:
        raise RuntimeError("Nginx configuration changed since preparation")
    # Never switch users to an unstarted module or a different service on 8787.
    healthy("cloud")
    if candidate == original:
        healthy(region)
        return {"region": region, "status": "unchanged"}
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = STATE / (region + "-" + uuid.uuid4().hex + ".conf")
    backup.write_bytes(path.read_bytes())
    try:
        path.write_text(candidate)
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
        healthy(region)
    except Exception:
        path.write_bytes(backup.read_bytes())
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
        raise
    return {"region": region, "status": "activated", "backup": str(backup)}


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin))))
