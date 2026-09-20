"""Install the office-only HTTPS proxy without changing application releases."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import time
import urllib.request
import zipfile
from uuid import uuid4

DOMAIN = 'lan.leshine.cloud'
SERVICE = 'ArkOfficeHttps'
VERSION = '2.11.4'
ARCHIVE_SHA512 = 'cd5ccfd86a4b40732cf715890d0dca5bf3f63adefec5a7914de85adf240c60ce7e5d2791631b88ef9758e46b23bb1730e020b9c5d696889740b284ffd4788e35'


def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True, encoding='utf-8', errors='replace').strip()


def powershell(command):
    return run('powershell', '-NoProfile', '-NonInteractive', '-Command', '$ErrorActionPreference="Stop"; ' + command)


def validate_plan(plan):
    if set(plan) - {'live_root', 'address', 'subnet', 'backend_port', 'previous_address'} or not {'live_root', 'address', 'subnet', 'backend_port'} <= set(plan):
        raise ValueError('Unexpected HTTPS plan fields')
    address = ipaddress.ip_address(plan['address'])
    subnet = ipaddress.ip_network(plan['subnet'])
    if not address.is_private or address.is_loopback or address.version != 4 or address not in subnet or subnet.prefixlen < 16:
        raise ValueError('HTTPS must bind to a specific office IPv4 subnet')
    if plan['backend_port'] != 8001:
        raise ValueError('Unexpected office backend port')
    if 'previous_address' in plan:
        previous = ipaddress.ip_address(plan['previous_address'])
        if previous not in subnet or previous == address:
            raise ValueError('Previous address must be distinct and in the office subnet')
    root = Path(plan['live_root']).resolve()
    if not (root / 'backend/app/main.py').is_file():
        raise ValueError('Office checkout is missing')
    return root


def configuration(address, directory):
    directory = directory.as_posix()
    if any(c in directory for c in '\n\r"{}'):
        raise ValueError('Unsafe HTTPS configuration path')
    return f'''{{
    admin off
    auto_https off
}}
https://{DOMAIN} {{
    bind {address}
    tls "{directory}/certs/fullchain.pem" "{directory}/certs/privkey.pem"
    reverse_proxy 127.0.0.1:8001
}}
'''


def validate_certificate(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from datetime import datetime, timezone, timedelta
    certificate = x509.load_pem_x509_certificate((directory / 'certs/fullchain.pem').read_bytes())
    key = serialization.load_pem_private_key((directory / 'certs/privkey.pem').read_bytes(), password=None)
    if DOMAIN not in certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName):
        raise ValueError('Certificate does not cover the LAN domain')
    if certificate.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
        raise ValueError('Certificate key mismatch')
    if certificate.not_valid_after_utc <= datetime.now(timezone.utc) + timedelta(days=7):
        raise ValueError('Certificate expires too soon')
    return certificate.not_valid_after_utc.isoformat()


def verify(address, directory):
    # Connect directly to the office address; retain real hostname/SNI and CA validation.
    context = ssl.create_default_context()
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    expected = x509.load_pem_x509_certificate((directory / 'certs/fullchain.pem').read_bytes()).public_bytes(serialization.Encoding.DER)
    for path in ['/health', '/shipping/scan']:
        with socket.create_connection((address, 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=DOMAIN) as connection:
                if connection.getpeercert(binary_form=True) != expected:
                    raise RuntimeError('HTTPS is serving a different certificate; perform a reviewed renewal/restart')
                connection.sendall(f'GET {path} HTTP/1.1\r\nHost: {DOMAIN}\r\nConnection: close\r\n\r\n'.encode())
                chunks = []
                while chunk := connection.recv(65536):
                    chunks.append(chunk)
                response = b''.join(chunks)
                if not response.startswith(b'HTTP/1.1 200 '):
                    raise RuntimeError(f'HTTPS verification failed: {path}')
                if path == '/health' and b'"connected"' not in response:
                    raise RuntimeError('HTTPS backend health failed')


def execute(plan_file, prepare_only=False):
    if os.name != 'nt':
        raise RuntimeError('Office HTTPS must run on the Windows office server')
    plan = json.loads(Path(plan_file).read_text(encoding='utf-8-sig'))
    root = validate_plan(plan)
    if powershell('([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)') != 'True':
        raise RuntimeError('Office HTTPS requires an administrator session')
    nssm = shutil.which('nssm')
    if not nssm or Path(run(nssm, 'get', 'CommissionSystem', 'AppDirectory')).resolve() != root / 'backend':
        raise RuntimeError('Plan does not match the installed office backend')
    if '--port 8001' not in run(nssm, 'get', 'CommissionSystem', 'AppParameters'):
        raise RuntimeError('Office backend port differs from verified plan')
    with urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=10) as response:
        if json.load(response).get('database') != 'connected':
            raise RuntimeError('Office backend is unhealthy')
    directory = root / '.deploy_state/office-lan-https'
    directory.mkdir(parents=True, exist_ok=True)
    # Directory holds private key and proxy executable; only admins and SYSTEM can modify.
    run('icacls', directory, '/inheritance:r', '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F')
    expiry = validate_certificate(directory)
    executable = directory / 'caddy.exe'
    archive = directory / f'caddy-{VERSION}.zip'
    if not archive.exists():
        urllib.request.urlretrieve(f'https://github.com/caddyserver/caddy/releases/download/v{VERSION}/caddy_{VERSION}_windows_amd64.zip', archive)
    if hashlib.sha512(archive.read_bytes()).hexdigest() != ARCHIVE_SHA512:
        raise RuntimeError('Caddy archive checksum mismatch')
    with zipfile.ZipFile(archive) as package:
        expected = package.read('caddy.exe')
    if executable.exists() and executable.read_bytes() != expected:
        raise RuntimeError('Existing HTTPS executable differs from pinned package')
    if not executable.exists():
        executable.write_bytes(expected)
    config = directory / 'Caddyfile'
    candidate = directory / 'Caddyfile.next'
    candidate.write_text(configuration(plan['address'], directory), encoding='utf-8')
    run(executable, 'validate', '--config', candidate, '--adapter', 'caddyfile')
    marker = directory / 'installed.json'
    existing = powershell(f'if(Get-Service -Name {SERVICE} -ErrorAction SilentlyContinue){{"exists"}}') == 'exists'
    if existing:
        if not marker.exists() or Path(run(nssm, 'get', SERVICE, 'Application')).resolve() != executable:
            raise RuntimeError('HTTPS service is not owned by this installer')
        record = json.loads(marker.read_text(encoding='utf-8'))
        installed_address = record.get('address')
        if any(record.get(k) != v for k, v in {'domain':DOMAIN, 'version':VERSION}.items()) or installed_address not in {plan['address'], plan.get('previous_address', plan['address'])}:
            raise RuntimeError('HTTPS ownership marker differs from plan')
        if config.read_text(encoding='utf-8') != configuration(installed_address, directory):
            raise RuntimeError('Installed HTTPS configuration has drifted')
        expected_parameters = f'run --config {config} --adapter caddyfile'
        if run(nssm, 'get', SERVICE, 'AppParameters').replace('"', '') != expected_parameters or Path(run(nssm, 'get', SERVICE, 'AppDirectory')).resolve() != directory:
            raise RuntimeError('HTTPS service parameters or working directory have drifted')
        if run(nssm, 'get', SERVICE, 'ObjectName').lower() not in ['localsystem', 'nt authority\\system']:
            raise RuntimeError('HTTPS service account has drifted')
        firewall = json.loads(powershell(f'$r=Get-NetFirewallRule -Name {SERVICE}; $a=$r | Get-NetFirewallAddressFilter; $p=$r | Get-NetFirewallPortFilter; [pscustomobject]@{{enabled=[string]$r.Enabled;action=[string]$r.Action;direction=[string]$r.Direction;local=@($a.LocalAddress);remote=@($a.RemoteAddress);port=@($p.LocalPort);protocol=[string]$p.Protocol}} | ConvertTo-Json -Compress'))
        if firewall['enabled'] != 'True' or firewall['action'] != 'Allow' or firewall['direction'] != 'Inbound' or firewall['local'] != [installed_address] or firewall['port'] != ['443'] or firewall['protocol'] != 'TCP' or [str(ipaddress.ip_network(n)) for n in firewall['remote']] != [plan['subnet']]:
            raise RuntimeError('HTTPS firewall rule differs from plan')
    if 'previous_address' in plan:
        if not existing:
            raise RuntimeError('Address migration requires an owned installation')
        if powershell(f'if(Get-NetIPAddress -AddressFamily IPv4 -IPAddress {plan["address"]} -ErrorAction SilentlyContinue){{"assigned"}}') != 'assigned':
            raise RuntimeError('New address is not assigned to this server')
    if prepare_only:
        print(json.dumps({'status': 'prepared', 'domain': DOMAIN, 'expires_at': expiry}))
        return
    if existing:
        if installed_address != plan['address']:
            readdress(nssm, directory, record, plan['address'], expiry)
            print(json.dumps({'status': 'readdressed', 'domain': DOMAIN, 'address': plan['address'], 'expires_at': expiry}))
            return
        if config.read_text(encoding='utf-8') != candidate.read_text(encoding='utf-8'):
            raise RuntimeError('Existing configuration differs; review before replacement')
        if run(nssm, 'status', SERVICE) != 'SERVICE_RUNNING':
            run(nssm, 'start', SERVICE)
        verify(plan['address'], directory)
        print(json.dumps({'status': 'verified', 'domain': DOMAIN, 'expires_at': expiry}))
        return
    if powershell('Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -eq 443} | Select-Object -ExpandProperty LocalAddress'):
        raise RuntimeError('Port 443 is already occupied')
    if powershell(f'if(Get-NetFirewallRule -Name {SERVICE} -ErrorAction SilentlyContinue){{"exists"}}'):
        raise RuntimeError('Existing firewall rule is not owned by installer')
    config.write_bytes(candidate.read_bytes())
    installed = False
    try:
        installed = True
        run(nssm, 'install', SERVICE, executable, 'run', '--config', config, '--adapter', 'caddyfile')
        run(nssm, 'set', SERVICE, 'AppDirectory', directory)
        run(nssm, 'set', SERVICE, 'AppStdout', directory / 'service-out.log')
        run(nssm, 'set', SERVICE, 'AppStderr', directory / 'service-error.log')
        run(nssm, 'set', SERVICE, 'AppRotateFiles', '1')
        run(nssm, 'set', SERVICE, 'AppRotateBytes', '10485760')
        run(nssm, 'set', SERVICE, 'Start', 'SERVICE_AUTO_START')
        powershell(f'New-NetFirewallRule -Name {SERVICE} -DisplayName "Ark office LAN HTTPS" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 -LocalAddress {plan["address"]} -RemoteAddress {plan["subnet"]} -Profile Any | Out-Null')
        run(nssm, 'start', SERVICE)
        for attempt in range(10):
            try:
                verify(plan['address'], directory)
                break
            except (OSError, RuntimeError):
                if attempt == 9:
                    raise
                time.sleep(1)
        marker.write_text(json.dumps({'domain': DOMAIN, 'version': VERSION, 'address': plan['address'], 'expires_at': expiry}), encoding='utf-8')
        print(json.dumps({'status': 'succeeded', 'domain': DOMAIN, 'expires_at': expiry}))
    except Exception as original:
        if installed:
            if powershell(f'if(Get-Service -Name {SERVICE} -ErrorAction SilentlyContinue){{"exists"}}') == 'exists':
                if Path(run(nssm, 'get', SERVICE, 'Application')).resolve() != executable:
                    raise RuntimeError('HTTPS installation failed and service ownership changed; manual recovery required') from original
                subprocess.run([nssm, 'stop', SERVICE], capture_output=True)
                run(nssm, 'remove', SERVICE, 'confirm')
            powershell(f'Get-NetFirewallRule -Name {SERVICE} -ErrorAction SilentlyContinue | Remove-NetFirewallRule; exit 0')
            residue = powershell(f'$s=Get-Service -Name {SERVICE} -ErrorAction SilentlyContinue; $r=Get-NetFirewallRule -Name {SERVICE} -ErrorAction SilentlyContinue; $l=Get-NetTCPConnection -State Listen | Where-Object {{$_.LocalAddress -eq "{plan["address"]}" -and $_.LocalPort -eq 443}}; if($s -or $r -or $l){{"residue"}}')
            if residue:
                raise RuntimeError('HTTPS rollback incomplete; service, listener or firewall remains') from original
        raise


def readdress(nssm, directory, record, address, expiry):
    """Called only after ownership, old config/firewall and new NIC checks."""
    config = directory / 'Caddyfile'
    marker = directory / 'installed.json'
    old_config, old_marker = config.read_bytes(), marker.read_bytes()
    backup = directory / ('readdress-backup-' + uuid4().hex)
    backup.mkdir()
    (backup / 'Caddyfile').write_bytes(old_config)
    (backup / 'installed.json').write_bytes(old_marker)
    original_status = run(nssm, 'status', SERVICE)
    try:
        if original_status != 'SERVICE_STOPPED':
            run(nssm, 'stop', SERVICE)
        (directory / 'Caddyfile.next').replace(config)
        powershell(f'Get-NetFirewallRule -Name {SERVICE} | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress {address}')
        run(nssm, 'start', SERVICE)
        for attempt in range(10):
            try:
                verify(address, directory)
                break
            except (OSError, RuntimeError):
                if attempt == 9:
                    raise
                time.sleep(1)
        next_marker = directory / 'installed.json.next'
        next_marker.write_text(json.dumps({**record, 'address': address, 'expires_at': expiry}), encoding='utf-8')
        next_marker.replace(marker)
    except Exception:
        if run(nssm, 'status', SERVICE) != 'SERVICE_STOPPED':
            run(nssm, 'stop', SERVICE)
        config.write_bytes(old_config)
        marker.write_bytes(old_marker)
        powershell(f'Get-NetFirewallRule -Name {SERVICE} | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress {record["address"]}')
        if original_status != 'SERVICE_STOPPED':
            run(nssm, 'start', SERVICE)
        raise
