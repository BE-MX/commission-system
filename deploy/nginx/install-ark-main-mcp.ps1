param(
    [string]$Server = "root@119.28.107.92",
    [string]$RemoteConfig = "/etc/nginx/conf.d/leshine.conf"
)

$ErrorActionPreference = "Stop"
$sshOptions = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ConnectionAttempts=3",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=4"
)
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$localSnippet = Join-Path $scriptRoot "ark-main-mcp-location.conf"
$remoteSnippet = "/etc/nginx/snippets/ark-main-mcp-location.conf"
$uploadPath = "/tmp/ark-main-mcp-location.conf"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not (Test-Path -LiteralPath $localSnippet)) {
    throw "Missing managed Nginx snippet: $localSnippet"
}

Write-Host "[1/4] Upload managed MCP location snippet"
& scp @sshOptions $localSnippet "${Server}:${uploadPath}"
if ($LASTEXITCODE -ne 0) { throw "Failed to upload MCP Nginx snippet" }

Write-Host "[2/4] Back up and install Nginx configuration"
$remoteScript = @'
set -eu
config="$1"
snippet="$2"
upload="$3"
stamp="$4"
backup="${config}.pre-mcp-${stamp}"
snippet_backup="${snippet}.pre-mcp-${stamp}"

cp -a "$config" "$backup"
snippet_existed=0
if [ -f "$snippet" ]; then
    cp -a "$snippet" "$snippet_backup"
    snippet_existed=1
fi
mkdir -p "$(dirname "$snippet")"
install -m 0644 "$upload" "$snippet"

restore_previous() {
    cp -a "$backup" "$config"
    if [ "$snippet_existed" = 1 ]; then
        cp -a "$snippet_backup" "$snippet"
    else
        rm -f "$snippet"
    fi
}

if ! python3 - "$config" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
anchor = "      location / {\n          try_files $uri $uri/ /index.html;\n      }\n"
include = "      include /etc/nginx/snippets/ark-main-mcp-location.conf;\n\n"
legacy_start = "      location = /mcp/social-customer {\n"
legacy_end = "      location = /api/customer-image/public/logo {\n"
if anchor not in text:
    raise SystemExit("SPA location block not found; refusing to edit Nginx config")
if legacy_start in text:
    start = text.index(legacy_start)
    end = text.index(legacy_end, start)
    text = text[:start] + text[end:]
if include not in text:
    text = text.replace(anchor, include + anchor, 1)
path.write_text(text, encoding="utf-8")
PY
then
    restore_previous
    echo "Nginx edit failed; restored $backup and prior snippet" >&2
    exit 1
fi

if ! nginx -t; then
    restore_previous
    nginx -t
    echo "Nginx validation failed; restored $backup and prior snippet" >&2
    exit 1
fi

nginx -s reload
rm -f "$upload"
echo "backup=$backup"
'@
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript))
& ssh @sshOptions $Server "echo '$encoded' | base64 -d | sh -s -- '$RemoteConfig' '$remoteSnippet' '$uploadPath' '$timestamp'"
if ($LASTEXITCODE -ne 0) { throw "Failed to install or reload Nginx MCP route" }

Write-Host "[3/4] Verify public route is no longer handled by the SPA"
$probeFile = Join-Path ([IO.Path]::GetTempPath()) "ark-mcp-initialize-$PID.json"
$probePayload = @{
    jsonrpc = "2.0"
    id = 1
    method = "initialize"
    params = @{
        protocolVersion = "2025-06-18"
        capabilities = @{}
        clientInfo = @{ name = "ark-nginx-probe"; version = "1.0" }
    }
} | ConvertTo-Json -Depth 5 -Compress
[IO.File]::WriteAllText($probeFile, $probePayload, [Text.UTF8Encoding]::new($false))
$probe = & curl.exe -sS -o NUL -w "%{http_code} %{content_type}" --max-time 20 -X POST `
    "https://leshine.work/mcp/" `
    -H "Content-Type: application/json" `
    -H "Accept: application/json, text/event-stream" `
    --data-binary "@$probeFile"
$curlExit = $LASTEXITCODE
Remove-Item -LiteralPath $probeFile -Force -ErrorAction SilentlyContinue
if ($curlExit -ne 0) { throw "Public MCP route probe failed" }
if ($probe -notmatch '^200 application/json') {
    throw "Unexpected public MCP response: $probe"
}

Write-Host "[4/4] Public MCP route ready: $probe"
