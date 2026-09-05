"""One-time TLS setup for existing registered domains; run remotely as root."""

import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

REGIONS = {
    "beijing": {"files": ["/etc/nginx/sites-enabled/ark-cloud.conf"],
                "domains": ["leshine.cloud", "www.leshine.cloud"], "certificate": "leshine.cloud"},
    "singapore": {"files": ["/etc/nginx/conf.d/leshine.conf", "/etc/nginx/sites-enabled/deputy-relay.conf"],
                  "domains": ["leshine.work", "www.leshine.work", "relay.leshine.work"], "certificate": "leshine.work"},
}


def reload():
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)


def write_configs(changes):
    parent = Path("/etc/nginx/.ark-backups")
    parent.mkdir(exist_ok=True)
    parent.chmod(0o700)
    backup = parent / uuid.uuid4().hex
    backup.mkdir(mode=0o700)
    previous = {}
    for path, content in changes.items():
        previous[path] = path.read_bytes()
        (backup / path.name).write_bytes(previous[path])
        path.write_text(content)
    try:
        reload()
    except Exception:
        for path, content in previous.items():
            path.write_bytes(content)
        reload()
        raise
    print("Nginx backup: " + str(backup), flush=True)


def setup(region, phase):
    spec = REGIONS[region]
    paths = [Path(name).resolve() for name in spec["files"]]
    if any(not path.is_relative_to("/etc/nginx") for path in paths):
        raise ValueError("Nginx path escaped its configuration directory")
    changes = {}
    for path in paths:
        content = path.read_text()
        if phase == "challenge":
            content, count = re.subn(r"(server_name [^;]+;\s*)return 301 https://\$host\$request_uri;",
                r"\1location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }\n    location / { return 301 https://$host$request_uri; }", content)
            if count != 1 and "/.well-known/acme-challenge/" not in content:
                raise RuntimeError("Expected one HTTP redirect block: " + path.name)
        elif phase == "activate":
            certificate = spec["certificate"]
            fullchain = Path("/etc/letsencrypt/live") / certificate / "fullchain.pem"
            if not fullchain.is_file():
                raise RuntimeError("Issue and verify certificate before activation")
            content = content.replace("/etc/nginx/ssl/" + certificate + "_bundle.crt", str(fullchain))
            content = content.replace("/etc/nginx/ssl/" + certificate + ".key", str(fullchain.parent / "privkey.pem"))
        else:
            raise ValueError("Unknown TLS setup phase")
        if content != path.read_text():
            changes[path] = content
    if changes:
        write_configs(changes)
    Path("/var/www/letsencrypt").mkdir(parents=True, exist_ok=True, mode=0o755)
    hook = Path("/etc/letsencrypt/renewal-hooks/deploy/ark-reload-nginx")
    body = "#!/bin/sh\nnginx -t && systemctl reload nginx\n"
    if not hook.exists():
        hook.write_text(body)
        hook.chmod(0o755)
    print(json.dumps({"region": region, "phase": phase, "domains": spec["domains"]}))


if __name__ == "__main__":
    request = json.load(sys.stdin)
    setup(request["region"], request["phase"])
