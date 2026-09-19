"""Scoped Nginx preparation/activation; no application or database writes."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import ssl
import uuid
import urllib.request
import urllib.parse

SPECS = {
    "office": ("/etc/nginx/conf.d/leshine.conf", "8002", 1),
    "cloud": ("/etc/nginx/sites-enabled/ark-cloud.conf", "8001", 2),
    "cloud-ip": ("/etc/nginx/sites-enabled/ark-ip-ssl.conf", "8001", 1),
    "hair": ("/etc/nginx/conf.d/hair.leshine.conf", "", 1),
    "video": ("/etc/nginx/conf.d/video.leshine.conf", "", 1),
}
BEGIN = "# BEGIN ARK STORAGE PUBLIC ROUTING"
END = "# END ARK STORAGE PUBLIC ROUTING"
STATE = Path("/etc/nginx/.ark-backups/storage-public")
IP_CERTIFICATE = Path('/etc/nginx/ssl/expo-ip.crt')


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


def render(original, snippet, region):
    _, port, expected = SPECS[region]
    # Replace only our blocks. Unknown layout or conflicting rules must be reviewed.
    clean = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", original, flags=re.S)
    if BEGIN in clean or END in clean or "X-Ark-Storage" in clean:
        raise ValueError("Conflicting storage routing; inspect the current configuration")
    if region in {'hair', 'video'}:
        anchor = re.compile(r'(root /var/www/' + ('hair-styles' if region == 'hair' else r'video\.leshine\.work') + r';\s*index index\.html;)')
    else:
        anchor = re.compile(r"location /api/\s*\{\s*proxy_pass http://127\.0\.0\.1:" + port + r";")
    if len(anchor.findall(clean)) != expected:
        raise ValueError("Unexpected storage routing layout")
    block = BEGIN + "\n" + snippet.strip() + "\n" + END + "\n"
    # Insert before the anchor for every site, so repeated preparation preserves
    # whitespace and yields the same digest.
    return anchor.sub(lambda match: block + match.group(0), clean)


def run(args):
    subprocess.run(args, check=True, stdout=sys.stderr, stderr=sys.stderr, timeout=30)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_urls(probes, region='cloud'):
    if not probes:
        raise ValueError('Explicit migrated object probes are required before activation')
    paths = []
    for relative in probes:
        if not isinstance(relative, str) or not re.fullmatch(r'/uploads/(avatars|card|festival|hair|video|assets|expo|tag_images)/[A-Za-z0-9_./%-]+', relative):
            raise ValueError('Invalid readiness probe')
        decoded = urllib.parse.unquote(relative)
        if any(part in {'', '.', '..'} for part in decoded[1:].split('/')) or '%' in decoded or '\\' in decoded:
            raise ValueError('Invalid readiness probe')
        if decoded.startswith(('/uploads/expo/pending/', '/uploads/expo/beautify_previews/')):
            raise ValueError('Temporary inputs cannot prove COS readiness')
        paths.append(relative)
    if region in {'hair', 'video'}:
        prefix = '/uploads/' + region + '/'
        paths = [path[len(prefix):] for path in paths if path.startswith(prefix)]
        pattern = r'(assets|yidaoqie/gallery)/.+' if region == 'hair' else r'(videos|posters)/.+'
        if not paths or not all(re.fullmatch(pattern, path) for path in paths):
            raise ValueError('Missing or invalid standalone site probes')
        return ['https://' + region + '.leshine.work/' + path for path in paths]
    if region not in {'cloud', 'office', 'cloud-ip'}:
        raise ValueError('Unknown routing region')
    expected = {'avatars', 'card', 'festival', 'hair', 'video', 'assets', 'expo', 'tag_images'}
    if {path.split('/')[2] for path in paths} != expected:
        raise ValueError('Each redirected namespace needs a migrated object probe')
    host = {'cloud':'leshine.cloud', 'office':'leshine.work', 'cloud-ip':'154.8.205.162'}[region]
    return ['https://' + host + path for path in paths]


def healthy(probes, region='cloud'):
    handlers = [NoRedirect()]
    if region == 'cloud-ip':
        # The kiosk intentionally pins this existing self-signed certificate.
        # Trust only the deployed certificate; never use CERT_NONE.
        context = ssl.create_default_context(cafile=str(IP_CERTIFICATE))
        context.check_hostname = False
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    for url in probe_urls(probes, region):
        request = urllib.request.Request(url, method='HEAD')
        with opener.open(request, timeout=30) as response:
            if response.status != 200 or response.headers.get('X-Ark-Storage') != 'cos':
                raise RuntimeError('COS application is not ready; public routing unchanged')


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
    certificate = hashlib.sha256(IP_CERTIFICATE.read_bytes()).hexdigest() if region == 'cloud-ip' else None
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
                "candidate": digest(candidate), "changed": candidate != original,
                "certificate": certificate}
    if request["action"] != "activate":
        raise ValueError("Unknown routing action")
    if baseline != request["baseline"] or digest(candidate) != request["candidate"]:
        raise RuntimeError("Nginx configuration changed since preparation")
    if certificate != request.get('certificate'):
        raise RuntimeError('Kiosk certificate changed since preparation')
    # Validate both origin readiness and the actual public destination.
    probe_urls(request.get('probes'), region)
    healthy(request.get("probes"))
    if candidate == original:
        healthy(request.get("probes"), region)
        return {"region": region, "status": "unchanged"}
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = STATE / (region + "-" + uuid.uuid4().hex + ".conf")
    backup.write_bytes(path.read_bytes())
    try:
        path.write_text(candidate)
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
        healthy(request.get("probes"), region)
    except Exception:
        path.write_bytes(backup.read_bytes())
        run(["nginx", "-t"])
        run(["systemctl", "reload", "nginx"])
        raise
    return {"region": region, "status": "activated", "backup": str(backup)}


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin))))
