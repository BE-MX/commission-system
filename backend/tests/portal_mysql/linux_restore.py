"""Byte-preserving Linux mysql client, routed only to the fixture-owned process.

Windows mysql batch_readline removes CR even with --binary-mode. The remote host
gets temporary owned-process credentials only; backup bytes are streamed via SSH.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import time
import uuid


def verify_loopback_listeners(output, port):
    addresses = [line.split()[3] for line in output.decode('ascii').splitlines()]
    assert addresses and all(address in {'127.0.0.1:' + str(port), '[::1]:' + str(port)}
        for address in addresses), 'SSH restore forward must listen exclusively on loopback'


def verify_owned_identity(probe, expected, pause=time.sleep):
    """Retry only read-only handshake failures, never restore SQL or a mismatch."""
    for attempt in range(3):
        result = probe()
        if result.returncode == 0:
            assert result.stdout.decode('ascii').strip().split('\t') == expected, 'Owned restore target changed'
            return
        transient = re.match(rb'ERROR (?:2003|2013) \(HY000\):', result.stderr)
        # Pytest renders CompletedProcess locals on assertion failures. Do not
        # let captured client diagnostics expose protected data in that output.
        result.stderr = b''
        assert transient and attempt < 2, 'Owned identity probe failed; no restore SQL transmitted'
        pause(.5)


@contextmanager
def linux_restore(request, directory, allowed):
    ssh = Path(request.config.getoption('portal_restore_ssh')).resolve(strict=True)
    scp = ssh.with_name('scp.exe').resolve(strict=True)
    host = request.config.getoption('portal_restore_host')
    client = request.config.getoption('portal_restore_client')
    digest = request.config.getoption('portal_restore_sha256')
    assert re.fullmatch(r'[a-z][a-z0-9_-]*@[a-zA-Z0-9.-]+', host)
    assert client.startswith('/') and re.fullmatch(r'[/a-zA-Z0-9._-]+', client)
    assert re.fullmatch(r'[0-9a-f]{64}', digest)
    runtime = json.loads((directory / 'runtime.json').read_text())
    assert runtime['port'] == allowed['port'] and Path(runtime['datadir']).resolve() == (directory / 'data').resolve()
    remote = '/home/' + host.split('@')[0] + '/.cache/ark-owned-restore-' + uuid.uuid4().hex
    remote_port = 40000 + secrets.randbelow(20000)
    common = ['-C', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3']
    def run(command, **kwargs):
        result = subprocess.run([str(ssh), *common, host, command], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=kwargs.pop('timeout', 30), **kwargs)
        if result.returncode:
            with (directory / 'protected-restore.stderr').open('ab') as errors:
                errors.write(result.stderr)
            result.stderr = b''
        assert result.returncode == 0, 'Protected Linux restore transport failed; diagnostics withheld'
        return result.stdout
    # Pin the client before supplying any temporary credential or backup bytes.
    actual_hash = run('sha256sum ' + shlex.quote(client)).decode('ascii').split()[0]
    assert actual_hash == digest, 'Linux restore client differs from its approved hash'
    run('umask 077 && mkdir ' + shlex.quote(remote))
    credential = directory / 'linux-restore-client.cnf'
    tunnel = None
    try:
        credential.write_text('[client]\nhost=127.0.0.1\nport=' + str(remote_port)
            + '\nuser=root\npassword=' + allowed['password'] + '\n', encoding='utf-8')
        uploaded = subprocess.run([str(scp), *common, str(credential), host + ':' + remote + '/client.cnf'],
            capture_output=True, timeout=30)
        assert uploaded.returncode == 0, 'Cannot install temporary owned-server credential'
        run('chmod 600 ' + shlex.quote(remote + '/client.cnf'))
        with (directory / 'restore-tunnel.log').open('wb') as errors:
            tunnel = subprocess.Popen([str(ssh), *common, '-o', 'ExitOnForwardFailure=yes', '-N',
                '-R', '127.0.0.1:' + str(remote_port) + ':127.0.0.1:' + str(allowed['port']), host],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                creationflags=subprocess.CREATE_NO_WINDOW)
            invocation = shlex.quote(client) + ' --defaults-file=' + shlex.quote(remote + '/client.cnf') \
                + ' --no-login-paths --protocol=TCP --host=127.0.0.1 --port=' + str(remote_port) \
                + ' --user=root --default-character-set=utf8mb4 --binary-mode --batch --skip-column-names'
            def probe():
                assert tunnel.poll() is None, 'Owned-loopback reverse tunnel failed'
                return subprocess.run([str(ssh), *common, host, invocation + ' --execute='
                    + shlex.quote('SELECT @@server_uuid, @@port, @@GLOBAL.event_scheduler')],
                    capture_output=True, timeout=20)
            # First and subsequent read-only probes share the same refusal policy.
            verify_owned_identity(probe, [runtime['server_uuid'], str(allowed['port']), 'OFF'])
            def restore(backup):
                assert tunnel.poll() is None
                verify_loopback_listeners(run('ss -H -lnt ' + shlex.quote('sport = :' + str(remote_port))), remote_port)
                verify_owned_identity(probe, [runtime['server_uuid'], str(allowed['port']), 'OFF'])
                verify_loopback_listeners(run('ss -H -lnt ' + shlex.quote('sport = :' + str(remote_port))), remote_port)
                with backup.open('rb') as data:
                    run(invocation + ' ' + shlex.quote(allowed['database']), stdin=data, timeout=900)
            yield restore
    finally:
        # A tunnel shutdown error must not skip either credential cleanup.
        try:
            if tunnel is not None and tunnel.poll() is None:
                tunnel.terminate()
                try:
                    tunnel.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    tunnel.kill(); tunnel.wait(timeout=15)
        finally:
            try:
                credential.unlink(missing_ok=True)
            finally:
                run('rm -f ' + shlex.quote(remote + '/client.cnf') + ' && rmdir ' + shlex.quote(remote))
