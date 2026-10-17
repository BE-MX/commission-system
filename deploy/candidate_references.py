"""Conservative, read-only references for managed candidate retirement."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess

from static_retention import no_links

SHA = re.compile(r'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])', re.I)
STAGE = re.compile(r'office-next-(?:frontend-pm|frontend|pm-lan)-[0-9]+', re.I)


def tokens(text):
    return {item.lower() for pattern in (SHA, STAGE) for item in pattern.findall(text)}


def metadata_references(state):
    """Read control files, never logs, caches, business data or our own inventory.

    Top-level JSON plus nested plan/recovery/restore JSON are control records.
    Bounds are fail-closed: an incomplete inspection must not authorize deletion.
    """
    excluded = {'sources', 'builds', 'transfers', 'python-envs', 'desktop',
                'candidate-retention', 'timings', 'credentials'}
    refs, count = set(), 0
    for directory, folders, names in os.walk(state, followlinks=False):
        base = Path(directory)
        folders[:] = [name for name in folders if name not in excluded
                      and not name.startswith(('office-', 'connector-deps-', 'node_modules'))]
        for name in folders:
            no_links(base / name)
        for name in names:
            if not name.endswith('.json'):
                continue
            relative = (base / name).relative_to(state).as_posix().lower()
            if base != state and not any(word in relative for word in ('plan', 'recovery', 'restore')):
                continue
            path = base / name
            no_links(path)
            count += 1
            if count > 2000 or path.stat().st_size > 8 * 1024 * 1024:
                raise RuntimeError('Candidate reference inspection limit reached')
            # Parse first: a truncated control record is not proof of no reference.
            refs.update(tokens(json.dumps(json.loads(path.read_text(encoding='utf-8-sig')))))
    # Installed configuration can pin a candidate through PYTHONPATH or a launcher
    # variable; only reference tokens leave this function, never setting values.
    for folder in ('backend', 'frontend', 'frontend-pm', 'services/whatsapp-connector'):
        for path in (state.parent / folder).glob('.env*'):
            no_links(path)
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise RuntimeError('Installed setting reference cannot be inspected')
            refs.update(tokens(path.read_text(encoding='utf-8-sig')))
    return refs


def expand(text):
    for encoded in re.findall(r'(?i)-(?:enc|encodedcommand)\s+["\']?([A-Za-z0-9+/=]{20,})', text):
        text += '\n' + base64.b64decode(encoded).decode('utf-16le')
    return text


def inspect_runtime_text(text, live):
    """Follow explicit local launcher scripts, including encoded PowerShell."""
    refs, queue, seen = set(), [text], set()
    pattern = re.compile(r'''(?i)([A-Z]:[/\\][^:"'\r\n]*?\.(?:ps1|py|bat|cmd|json))(?=["'\s;]|$)''')
    while queue:
        content = expand(queue.pop())
        refs.update(tokens(content))
        for filename in pattern.findall(content):
            path = Path(filename)
            if path in seen:
                continue
            seen.add(path)
            no_links(path)
            if len(seen) > 100 or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                raise RuntimeError('Runtime launcher reference cannot be inspected')
            queue.append(path.read_text(encoding='utf-8-sig'))
    return refs


def runtime_references(live):
    if os.name != 'nt':
        raise RuntimeError('Office candidate cleanup requires Windows runtime inspection')
    # Capture privately; never print command lines, service environment or task args.
    code = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$rows=@(Get-CimInstance Win32_Process | ForEach-Object { "$($_.ExecutablePath) $($_.CommandLine)" })
$services=@(Get-CimInstance Win32_Service)
$rows+=@($services | ForEach-Object { $_.PathName })
$rows+=@(Get-ScheduledTask | Where-Object { $_.Settings.Enabled -or $_.State -eq 'Running' } | ForEach-Object {
    $_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }
})
$services | Where-Object { $_.PathName -match '(?i)nssm(?:\.exe)?(?:"|\s|$)' } | ForEach-Object {
    $p='HKLM:\SYSTEM\CurrentControlSet\Services\'+$_.Name+'\Parameters'
    if(Test-Path -LiteralPath $p) {
        $v=Get-ItemProperty -LiteralPath $p
        $rows+="$($v.Application) $($v.AppDirectory) $($v.AppParameters) $($v.AppEnvironment) $($v.AppEnvironmentExtra)"
    }
}
ConvertTo-Json -InputObject $rows -Compress
"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                             base64.b64encode(code.encode('utf-16le')).decode()],
                            capture_output=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError('Runtime reference inspection failed')
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError('Runtime reference inventory is empty')
    return set().union(*(inspect_runtime_text(row or '', live) for row in rows))
