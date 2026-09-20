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
    # COS owns an explicit public deny for its internal storage gateway. Ignore
    # only that exact rule inside its managed block when checking for conflicts;
    # retain the original block byte-for-byte in the rendered configuration.
    inspection = re.sub(
        r"(?ms)^[ \t]*# BEGIN ARK STORAGE PUBLIC ROUTING\r?\n.*?^[ \t]*# END ARK STORAGE PUBLIC ROUTING[ \t]*$",
        lambda match: re.sub(
            r"(?m)^[ \t]*location\s+\^~\s+/api/colorwork/storage/\s*\{\s*return\s+404;\s*\}[ \t]*$",
            "", match.group(0)),
        clean,
    )
    if BEGIN in clean or END in clean or "/api/colorwork/" in inspection:
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


def syntax_config(snippet, scratch):
    """Root nginx -t also chowns temp dirs; isolate every runtime path.

    Keep this helper in each standalone script: transport sends only that file.
    """
    prefix = scratch.resolve().as_posix()
    paths = "".join(
        f'{directive} "{prefix}/{directory}";\n'
        for directive, directory in (
            ("client_body_temp_path", "body"), ("proxy_temp_path", "proxy"),
            ("fastcgi_temp_path", "fastcgi"), ("uwsgi_temp_path", "uwsgi"),
            ("scgi_temp_path", "scgi"),
        )
    )
    return (f'pid "{prefix}/nginx.pid";\nerror_log stderr;\nevents {{}}\nhttp {{\n'
            + paths + "access_log off;\nserver { listen 127.0.0.1:18979;\n"
            + snippet + "\n} }\n")


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
        # Never let a root syntax check inherit the production temp paths.
        scratch = STATE / (region + "-syntax")
        scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        check = STATE / (region + "-syntax.conf")
        check.write_text(syntax_config(request["snippet"], scratch))
        run(["nginx", "-t", "-c", str(check), "-e", "stderr"])
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
