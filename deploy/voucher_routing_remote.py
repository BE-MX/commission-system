"""Scoped Nginx preparation/activation; no application or database writes."""

import hashlib
import json
import os
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

# Existing, independently deployed office photo limit. Preserve it byte for byte;
# allow only this inspected body, not arbitrary unowned shipping routes.
OFFICE_PHOTO_RULE = """location = /api/mini/shipping-inspection/photos {
    client_max_body_size 21m;
    proxy_pass http://127.0.0.1:8002;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}"""


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
    checked = clean
    if feature == 'shipping-video' and region == 'office' and checked.count(OFFICE_PHOTO_RULE) == 1:
        checked = checked.replace(OFFICE_PHOTO_RULE, '')
    if begin in checked or end in checked or conflict in checked or (feature == 'shipping-video' and 'shipping-inspection' in checked):
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


def backend_context(backend):
    """Pin the live service and its cached configuration without exposing its environment."""
    result = subprocess.run(
        ["systemctl", "show", "ark-backend", "-p", "MainPID", "-p", "User",
         "-p", "WorkingDirectory", "-p", "ExecStart"],
        check=True, text=True, capture_output=True, timeout=10,
    )
    props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    pid = int(props.get("MainPID", "0"))
    if (pid <= 0 or props.get("User") != "ubuntu"
            or props.get("WorkingDirectory") != str(backend)
            or str(backend / ".venv/bin/uvicorn") not in props.get("ExecStart", "")
            or "--port 8001" not in props.get("ExecStart", "")):
        raise RuntimeError("Unexpected Beijing backend identity; routing unchanged")
    proc = Path("/proc") / str(pid)
    # The comm field can contain spaces; fields after its closing ')' start at #3.
    ticks = int((proc / "stat").read_text().rsplit(")", 1)[1].split()[19])
    boot = int(re.search(r"(?m)^btime (\d+)$", Path("/proc/stat").read_text()).group(1))
    started = boot + ticks / os.sysconf("SC_CLK_TCK")
    sources = [".env", "app/core/config.py", "app/core/storage/cos.py",
               "app/core/storage/files.py", "app/domestic/file_service.py", "app/domestic/router.py"]
    if any((backend / name).stat().st_mtime > started for name in sources):
        raise RuntimeError("Backend configuration or storage code changed after service start; routing unchanged")
    environment = dict(entry.split("=", 1) for entry in (proc / "environ").read_bytes().decode().split("\0") if "=" in entry)
    return pid, environment


def check_voucher_cos():
    """Use the running backend's identity; never write business rows or COS objects."""
    backend = Path("/home/ubuntu/commission-system/backend")
    pid, environment = backend_context(backend)
    probe = '''
import json, re
from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy import text
from app.core.config import get_settings
from app.core.database import engine
from app.core.storage.cos import CosObjectStore
from app.core.storage.files import reserve_processing_bytes
try:
    s = get_settings()
    if 'domestic' not in s.COS_ENABLED_DOMAINS or 'domestic' not in s.COS_MANAGED_DOMAINS:
        raise RuntimeError('Domestic COS must be enabled and managed')
    with engine.connect() as conn:
        conn.exec_driver_sql('START TRANSACTION READ ONLY')
        keys = list(conn.execute(text("SELECT DISTINCT voucher_path FROM ark_domestic_customer_requests WHERE voucher_path IS NOT NULL AND voucher_path <> '' ORDER BY voucher_path" )).scalars())
        conn.rollback()
    store = CosObjectStore('domestic')
    samples = 0
    cache = Path(s.COS_CACHE_ROOT)
    cache.mkdir(parents=True, exist_ok=True)
    for key in keys:
        head = store.head(key)
        size = int(head.get('Content-Length', -1))
        sha = head.get('x-cos-meta-sha256', '')
        if size < 0 or size > 20 * 1024 * 1024 or not re.fullmatch('[0-9a-f]{64}', sha):
            raise RuntimeError('Voucher lacks verified COS metadata')
        if samples < 3:
            with reserve_processing_bytes(max(1, size)), TemporaryDirectory(prefix='voucher-preflight-', dir=cache) as tmp:
                store.download(key, Path(tmp) / 'voucher', max_bytes=max(1, size), expected_sha256=sha)
            samples += 1
    # Exercise writable, budgeted scratch space even before the first voucher exists.
    with reserve_processing_bytes(1), TemporaryDirectory(prefix='voucher-preflight-', dir=cache) as tmp:
        (Path(tmp) / 'probe').write_bytes(b'x')
    print(json.dumps(dict(status='ready', historical_vouchers=len(keys), checksum_reads=samples)))
except Exception as exc:
    print(json.dumps(dict(status='failed', error_type=type(exc).__name__)))
    raise SystemExit(1)
'''
    result = subprocess.run(
        ["runuser", "-u", "ubuntu", "--", str(backend / ".venv/bin/python"), "-c", probe],
        cwd=backend, env=environment, text=True, capture_output=True, timeout=120,
    )
    if result.returncode:
        raise RuntimeError("Beijing voucher COS readiness failed; live routing unchanged")
    proof = json.loads(result.stdout.splitlines()[-1])
    if proof.get("status") != "ready":
        raise RuntimeError("Beijing voucher COS readiness failed; live routing unchanged")
    if backend_context(backend)[0] != pid:
        raise RuntimeError("Beijing backend restarted during COS checks; routing unchanged")
    proof["backend_pid"] = pid
    return proof


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
    if request["action"] not in {"prepare", "activate"}:
        raise ValueError("Unknown routing action")
    if request["action"] == "activate" and (
        baseline != request["baseline"] or digest(candidate) != request["candidate"]
    ):
        raise RuntimeError("Nginx configuration changed since preparation")
    readiness = check_voucher_cos() if feature == "voucher" and region == "cloud" else None
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
                "candidate": digest(candidate), "changed": candidate != original,
                "readiness": readiness}
    if candidate == original:
        return {"region": region, "status": "unchanged"}
    # COS preflight can take time; recheck drift immediately before writing.
    if digest(path.read_text()) != baseline:
        raise RuntimeError("Nginx configuration changed during readiness checks")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = state / (region + "-" + uuid.uuid4().hex + ".conf")
    backup.write_bytes(path.read_bytes())
    try:
        path.write_text(candidate)
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
        if digest(path.read_text()) != digest(candidate):
            raise RuntimeError("Nginx configuration changed during activation")
    except Exception:
        if digest(path.read_text()) != digest(candidate):
            raise RuntimeError(f"Nginx configuration changed; rollback blocked, backup retained at {backup}") from None
        path.write_bytes(backup.read_bytes())
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
        raise
    return {"region": region, "status": "activated", "backup": str(backup)}


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin))))
