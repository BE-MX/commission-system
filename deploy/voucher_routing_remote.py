"""Scoped Nginx preparation/activation; no application or database writes."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

SPECS = {
    "office": ("/etc/nginx/conf.d/leshine.conf", "8002", 1),
    "cloud": ("/etc/nginx/sites-enabled/ark-cloud.conf", "8001", 2),
}
BEGIN = "# BEGIN ARK DOMESTIC VOUCHER ROUTING"
END = "# END ARK DOMESTIC VOUCHER ROUTING"
STATE = Path("/etc/nginx/.ark-backups/domestic-voucher")


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


def render(original, snippet, region, feature="voucher"):
    _, port, expected = SPECS[region]
    if feature not in {"voucher", "shipping-video", "receipt"}:
        raise ValueError("Unknown routing feature")
    begin, end, conflict = (BEGIN, END, "/api/domestic/") if feature == "voucher" else (
        "# BEGIN ARK SHIPPING VIDEO ROUTING", "# END ARK SHIPPING VIDEO ROUTING", "/api/mini/shipping-inspection/videos")
    if feature == "receipt":
        begin, end, conflict = "# BEGIN ARK RECEIPT ROUTING", "# END ARK RECEIPT ROUTING", "/api/receipts"
    # Replace only our blocks. Unknown layout or conflicting rules must be reviewed.
    clean = re.sub(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", "", original, flags=re.S)
    if begin in clean or end in clean or conflict in clean or (feature == 'shipping-video' and '/api/shipping-inspection/station/' in clean):
        raise ValueError("Conflicting domestic routing; inspect the current configuration")
    anchor = re.compile(r"location /api/\s*\{\s*proxy_pass http://127\.0\.0\.1:" + port + r";")
    if len(anchor.findall(clean)) != expected:
        raise ValueError("Unexpected API upstream layout")
    block = begin + "\n" + snippet.strip() + "\n" + end + "\n"
    return anchor.sub(lambda match: block + match.group(0), clean)


def run(args):
    subprocess.run(args, check=True, stdout=sys.stderr, stderr=sys.stderr, timeout=30)


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
    feature = request.get("feature", "voucher")
    candidate = render(original, request["snippet"], region, feature)
    state = STATE if feature == "voucher" else STATE.parent / feature
    baseline = digest(original)
    if request["action"] == "prepare":
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never let a root syntax check inherit the production temp paths.
        scratch = state / (region + "-syntax")
        scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        check = state / (region + "-syntax.conf")
        check.write_text(syntax_config(request["snippet"], scratch))
        run(["nginx", "-t", "-c", str(check), "-e", "stderr"])
        candidate_path = state / (region + "-candidate.conf")
        candidate_path.write_text(candidate)
        return {"region": region, "status": "prepared", "baseline": baseline,
                "candidate": digest(candidate), "changed": candidate != original}
    if request["action"] != "activate":
        raise ValueError("Unknown routing action")
    if baseline != request["baseline"] or digest(candidate) != request["candidate"]:
        raise RuntimeError("Nginx configuration changed since preparation")
    if candidate == original:
        return {"region": region, "status": "unchanged"}
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = state / (region + "-" + uuid.uuid4().hex + ".conf")
    backup.write_bytes(path.read_bytes())
    try:
        path.write_text(candidate)
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
    except Exception:
        path.write_bytes(backup.read_bytes())
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
        raise
    return {"region": region, "status": "activated", "backup": str(backup)}


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin))))
