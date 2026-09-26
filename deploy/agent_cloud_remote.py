"""Fixed-scope preparation and preflight for the Agent cloud migration."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import signal
import urllib.request
import uuid

STATE = Path('/var/lib/ark-agent-migration')
NODE = '/root/.nvm/versions/node/v22.22.1/bin/node'
PM2 = '/root/.nvm/versions/node/v22.22.1/lib/node_modules/pm2/bin/pm2'


def run(args, *, check=True, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=90, **kwargs)


def pause_okki_scheduler():
    """Stop the inspected nine ESM cron tasks only at an observed idle boundary."""
    processes = json.loads(run([NODE, PM2, 'jlist']).stdout)
    process = next(p for p in processes if p['name'] == 'okki-index')
    if process['pm2_env']['status'] == 'stopped' and not process.get('pid'):
        return
    pid = process['pid']
    try:
        urllib.request.urlopen('http://127.0.0.1:9229/json/list', timeout=1)
    except OSError:
        os.kill(pid, signal.SIGUSR1)
    for _ in range(10):
        try:
            with urllib.request.urlopen('http://127.0.0.1:9229/json/list', timeout=2) as response:
                targets = json.load(response)
            break
        except OSError:
            time.sleep(0.3)
    else:
        raise RuntimeError('Cannot connect to the inspected process inspector')
    listener = run(['ss', '-lntp', 'sport', '=', ':9229']).stdout
    if len(targets) != 1 or ('pid=' + str(pid) + ',') not in listener or '127.0.0.1:9229' not in listener:
        raise RuntimeError('Inspector does not belong to the inspected OKKI process')
    expression = """(async()=>{
      const cron=process.getBuiltinModule('module').createRequire('/root/.openclaw/workspace/okki-sync/index.js')('/root/.openclaw/workspace/okki-sync/node_modules/node-cron/dist/esm/node-cron.js').default;
      const tasks=[...cron.getTasks().values()];
      const expected=['55 23 * * *','5 0 * * *','*/30 * * * *','0 2 * * *','*/30 * * * *','30 1 * * *','0 3 * * *','*/5 * * * *','15 3 * * *'].sort();
      if(JSON.stringify(tasks.map(t=>t.cronExpression).sort())!==JSON.stringify(expected)) throw Error('Unexpected cron registry');
      if(tasks.some(t=>t.getStatus()!=='idle')) return {ready:false};
      for(const t of tasks) t.runner.beforeRun=()=>false;
      for(const t of tasks) t.stop();
      return {ready:true,count:tasks.length};
    })()"""
    script = """const req=JSON.parse(process.argv[1]);
const ws=new WebSocket(req.url);
const timer=setTimeout(()=>{process.stderr.write('Inspector timeout');process.exit(2)},10000);
ws.onopen=()=>ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression:req.expression,awaitPromise:true,returnByValue:true}}));
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id!==1)return;
if(m.error||m.result.exceptionDetails){process.stderr.write(m.result?.exceptionDetails?.exception?.description || 'Inspector evaluation failed');process.exit(3)}
console.log(JSON.stringify(m.result.result.value));clearTimeout(timer);ws.close();};
"""
    for _ in range(24):
        result = run([NODE, '--input-type=module', '-e', script,
                      json.dumps({'url': targets[0]['webSocketDebuggerUrl'], 'expression': expression})], check=False)
        if result.returncode:
            raise RuntimeError('Scheduler inspection failed: ' + result.stderr[:600])
        if json.loads(result.stdout).get('ready'):
            run([NODE, PM2, 'stop', 'okki-index'])
            return
        time.sleep(3)
    raise RuntimeError('OKKI internal tasks did not reach an idle boundary')


def main(action):
    os.umask(0o077)
    if action == 'prepare-target':
        if shutil.disk_usage('/').free < 10 * 1024**3:
            raise RuntimeError('At least 10 GiB free space required')
        paths = ['/root/.openclaw', '/root/.local/share/pnpm', '/root/.nvm/versions/node/v22.22.1',
                 '/opt/google', '/opt/social-customer-mcp', '/opt/deputy-relay', '/usr/local/bin/node']
        if not (STATE / 'target-prepared').exists():
            for path in paths:
                if Path(path).exists():
                    raise RuntimeError('Destination already exists: ' + path)
            STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
            (STATE / 'target-prepared').write_text('2026-09-26\n')
        return {'status': 'target-prepared', 'free_gib': shutil.disk_usage('/').free // 1024**3}
    if action == 'snapshot-source':
        state = STATE / 'source'
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not (state / 'freeze-id').exists():
            (state / 'freeze-id').write_text(uuid.uuid4().hex)
        # Sensitive runtime state stays on the two servers under root-only paths.
        (state / 'crontab').write_text(run(['crontab', '-l']).stdout)
        (state / 'pm2.json').write_text(run([NODE, PM2, 'jlist']).stdout)
        for name in ['dingtalk-monitor', 'social-customer-mcp', 'deputy-relay', 'ark-okki-outbound-poller.timer']:
            (state / (name + '.state')).write_text(run(['systemctl', 'show', name,
                '-p', 'ActiveState', '-p', 'UnitFileState']).stdout)
        return {'status': 'source-snapshotted'}
    if action == 'validate-target':
        version = run([NODE, '--version']).stdout.strip()
        env = dict(os.environ, PATH=str(Path(NODE).parent) + ':' + os.environ['PATH'])
        openclaw = run(['/root/.local/share/pnpm/openclaw', '--version'], env=env).stdout.strip()
        chrome = run(['/opt/google/chrome/chrome', '--version']).stdout.strip()
        run(['/opt/social-customer-mcp/.venv/bin/python', '-c', 'import uvicorn,sqlalchemy,mcp'])
        return {'status': 'target-validated', 'node': version, 'openclaw': openclaw,
                'chrome': chrome, 'free_gib': shutil.disk_usage('/').free // 1024**3}
    if action == 'validate-staged':
        payload = STATE / 'payload'
        node = str(payload / NODE.lstrip('/'))
        package = payload / 'root/.local/share/pnpm/global/5/.pnpm/openclaw@2026.6.6/node_modules/openclaw/openclaw.mjs'
        version = run([node, str(package), '--version']).stdout.strip()
        chrome = run([str(payload / 'opt/google/chrome/chrome'), '--version']).stdout.strip()
        run([str(payload / 'opt/social-customer-mcp/.venv/bin/python'), '-c', 'import uvicorn,sqlalchemy,mcp'])
        return {'status': 'staged-validated', 'openclaw': version, 'chrome': chrome}
    if action == 'freeze-source':
        state = STATE / 'source'
        assert (state / 'crontab').is_file() and (state / 'pm2.json').is_file()
        if not (state / 'freeze-started').exists():
            current = run(['crontab', '-l']).stdout
            if current != (state / 'crontab').read_text():
                raise RuntimeError('Cron changed since preparation; re-inventory before freezing')
            (state / 'freeze-started').write_text('2026-09-26\n')
        cron = '\n'.join(l for l in (state / 'crontab').read_text().splitlines()
                         if '/root/.openclaw' not in l) + '\n'
        run(['crontab', '-'], input=cron)
        run(['systemctl', 'stop', 'ark-okki-outbound-poller.timer'])
        pause_okki_scheduler()
        # Drain all externally scheduled writes; never kill an in-flight business job.
        for _ in range(24):
            active = run(['systemctl', 'show', 'ark-okki-outbound-poller.service', '-p', 'MainPID', '--value']).stdout.strip()
            locks = run(['lslocks', '-n', '--notruncate', '-o', 'PATH']).stdout
            busy = any('/tmp/' + k in locks for k in ['okki-', 'shopify-'])
            if active == '0' and not busy:
                break
            time.sleep(5)
        else:
            raise RuntimeError('Writers not drained; source cron/timer remain paused, no target activation')
        env = dict(os.environ, XDG_RUNTIME_DIR='/run/user/0')
        run(['systemctl', '--user', 'stop', 'openclaw-gateway'], env=env)
        run(['systemctl', '--user', 'disable', 'openclaw-gateway'], env=env)
        run(['systemctl', 'stop', 'dingtalk-monitor', 'social-customer-mcp', 'deputy-relay'])
        run(['systemctl', 'disable', 'dingtalk-monitor', 'social-customer-mcp', 'deputy-relay', 'ark-okki-outbound-poller.timer'])
        run([NODE, PM2, 'stop', 'okki-index', 'leshine-customer-mcp', 'shipment-tracking-mcp'])
        run([NODE, PM2, 'save'])
        return main('verify-frozen')
    if action == 'configure-target':
        payload = STATE / 'payload'
        marker = STATE / 'configured'
        if marker.exists():
            return {'status': 'target-configured'}
        # The preflight verified these destination roots were absent.
        roots = ['root/.openclaw', 'root/.mcporter', 'root/.local/share/pnpm', 'root/.nvm/versions/node/v22.22.1',
                 'opt/google', 'opt/social-customer-mcp', 'opt/deputy-relay', 'usr/local/bin/node']
        progress_path = STATE / 'promotion.json'
        promoted = json.loads(progress_path.read_text()) if progress_path.exists() else []
        for relative in roots:
            src, dest = payload / relative, Path('/') / relative
            if relative in promoted:
                assert dest.exists() and not src.exists()
                continue
            if dest.exists():
                # Only the interrupted, task-owned initial stream can exist here.
                if relative != 'root/.openclaw' or not (STATE / 'target-prepared').exists():
                    raise RuntimeError('Unexpected destination: ' + str(dest))
                dest.rename(STATE / 'interrupted-initial-openclaw')
            dest.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dest)
            promoted.append(relative)
            progress_path.write_text(json.dumps(promoted))
        source = payload / 'var/lib/ark-agent-migration/source'
        if source.exists():
            source.rename(STATE / 'source')
        for src in (payload / 'etc/systemd/system').glob('*'):
            dest = Path('/etc/systemd/system') / src.name
            if dest.exists() and dest.read_bytes() != src.read_bytes():
                raise RuntimeError('Unit already exists: ' + src.name)
            shutil.copy2(src, dest)
        gateway = (payload / 'root/.config/systemd/user/openclaw-gateway.service').read_text()
        gateway_path = Path('/root/.config/systemd/user/openclaw-gateway.service')
        gateway_path.parent.mkdir(parents=True, exist_ok=True)
        gateway_path.write_text(gateway)
        # Install system units, but do not start them until source-frozen evidence is verified.
        if run(['id', 'social-customer-mcp'], check=False).returncode:
            run(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', 'social-customer-mcp'])
        run(['chown', '-R', 'social-customer-mcp:social-customer-mcp', '/opt/social-customer-mcp'])
        run(['chown', 'root:root', '/opt/social-customer-mcp/.env'])
        Path('/opt/social-customer-mcp/.env').chmod(0o600)
        run(['chown', '-R', 'www-data:www-data', '/opt/deputy-relay'])
        run(['chown', 'root:root', '/opt/deputy-relay/.env'])
        Path('/opt/deputy-relay/.env').chmod(0o600)
        chrome_link = Path('/usr/bin/google-chrome')
        if not chrome_link.exists():
            chrome_link.symlink_to('/opt/google/chrome/google-chrome')
        envfile = Path('/opt/social-customer-mcp/.env')
        envtext = '\n'.join(l for l in envfile.read_text().splitlines() if not l.startswith(
            ('SOCIAL_CUSTOMER_MCP_ALLOWED_HOSTS=', 'SOCIAL_CUSTOMER_MCP_ALLOWED_ORIGINS=')))
        envtext += '\nSOCIAL_CUSTOMER_MCP_ALLOWED_HOSTS=leshine.cloud,www.leshine.cloud,127.0.0.1:8100,localhost:8100\n'
        envtext += 'SOCIAL_CUSTOMER_MCP_ALLOWED_ORIGINS=https://leshine.cloud,https://www.leshine.cloud,https://leshine.work,https://www.leshine.work\n'
        envfile.write_text(envtext)
        apps = []
        for proc in json.loads((STATE / 'source/pm2.json').read_text()):
            name, config = proc['name'], proc['pm2_env']
            if name not in ['okki-index', 'leshine-customer-mcp', 'shipment-tracking-mcp']:
                continue
            transient = {'SSH_AUTH_SOCK', 'DBUS_SESSION_BUS_ADDRESS', 'JOURNAL_STREAM', 'INVOCATION_ID',
                         'SYSTEMD_EXEC_PID', 'MEMORY_PRESSURE_WATCH', 'MEMORY_PRESSURE_WRITE', 'OPENCLAW_GATEWAY_SERVICE_PID'}
            apps.append({'name': name, 'script': config['pm_exec_path'], 'cwd': config['pm_cwd'],
                         'interpreter': NODE, 'args': config.get('args', []),
                         'node_args': config.get('node_args', []),
                         'env': {k: v for k, v in config.get('env', {}).items()
                           if isinstance(v, str) and k not in transient}})
            if name != 'okki-index':
                path = Path(config['pm_exec_path'])
                text = path.read_text()
                old = "app.listen(port, '0.0.0.0'" if name == 'leshine-customer-mcp' else "app.listen(PORT, '0.0.0.0'"
                if text.count(old) != 1:
                    if text.count(old.replace('0.0.0.0', '127.0.0.1')) != 1:
                        raise RuntimeError('MCP listen anchor changed')
                else:
                    path.write_text(text.replace(old, old.replace('0.0.0.0', '127.0.0.1')))
        relay = Path('/opt/deputy-relay/src/index.js')
        text = relay.read_text()
        if "server.listen(PORT, () => {" in text:
            relay.write_text(text.replace("server.listen(PORT, () => {", "server.listen(PORT, '127.0.0.1', () => {"))
        # Stale browser locks identify the old hostname; only discard lock symlinks.
        for name in ['SingletonLock', 'SingletonSocket', 'SingletonCookie']:
            for lock in Path('/root/.openclaw/browser').rglob(name):
                if lock.is_symlink():
                    lock.unlink()
        (STATE / 'apps.json').write_text(json.dumps({'apps': apps}))
        run(['systemctl', 'daemon-reload'])
        marker.write_text('2026-09-26\n')
        return {'status': 'target-configured', 'apps': [x['name'] for x in apps]}
    if action == 'activate-target':
        assert (STATE / 'configured').exists() and (STATE / 'source/frozen-verified').exists()
        env = dict(os.environ, PATH=str(Path(NODE).parent) + ':' + os.environ['PATH'], HOME='/root', PM2_HOME='/root/.pm2')
        run([NODE, PM2, 'start', str(STATE / 'apps.json')], env=env)
        run([NODE, PM2, 'save'], env=env)
        run([NODE, PM2, 'startup', 'systemd', '-u', 'root', '--hp', '/root'], env=env)
        units = ['social-customer-mcp', 'deputy-relay', 'dingtalk-monitor']
        run(['systemctl', 'enable', '--now', *units])
        run(['loginctl', 'enable-linger', 'root'])
        run(['systemctl', 'start', 'user@0.service'])
        userenv = dict(env, XDG_RUNTIME_DIR='/run/user/0')
        run(['systemctl', '--user', 'daemon-reload'], env=userenv)
        run(['systemctl', '--user', 'enable', '--now', 'openclaw-gateway'], env=userenv)
        run(['systemctl', 'enable', '--now', 'ark-okki-outbound-poller.timer'])
        cron = ['SHELL=/bin/bash', 'PATH=/root/.nvm/versions/node/v22.22.1/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin']
        for line in (STATE / 'source/crontab').read_text().splitlines():
            if '/root/.openclaw' in line and not line.lstrip().startswith('#'):
                parts = line.split(None, 5)
                if len(parts) != 6:
                    raise RuntimeError('Unsupported cron syntax')
                cron.append(' '.join(parts[:5]) + ' root ' + parts[5])
        cronpath = Path('/etc/cron.d/ark-agent-sync')
        cronpath.write_text('\n'.join(cron) + '\n')
        cronpath.chmod(0o644)
        (STATE / 'activated').write_text('2026-09-26\n')
        return {'status': 'target-activated', 'cron_jobs': len(cron) - 2}
    if action == 'verify-target':
        userenv = dict(os.environ, XDG_RUNTIME_DIR='/run/user/0')
        if run(['systemctl', '--user', 'is-active', 'openclaw-gateway'], check=False, env=userenv).stdout.strip() != 'active':
            raise RuntimeError('Target gateway not active')
        for name in ['dingtalk-monitor', 'social-customer-mcp', 'deputy-relay', 'ark-okki-outbound-poller.timer']:
            if run(['systemctl', 'is-active', name], check=False).stdout.strip() != 'active':
                raise RuntimeError('Target unit not active: ' + name)
        apps = json.loads(run([NODE, PM2, 'jlist']).stdout)
        states = {p['name']: p['pm2_env']['status'] for p in apps}
        for name in ['okki-index', 'leshine-customer-mcp', 'shipment-tracking-mcp']:
            if states.get(name) != 'online':
                raise RuntimeError('Target PM2 not online: ' + name)
        import urllib.request
        checks = {}
        for port in [3100, 3200, 3800, 8100]:
            with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/health', timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError('Health failed')
                checks[str(port)] = response.status
        return {'status': 'target-verified', 'pm2': states, 'health': checks}
    if action == 'retire-source':
        main('verify-frozen')
        backups = STATE / 'source/retired-units'
        backups.mkdir(exist_ok=True)
        for name in ['ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer', 'dingtalk-monitor.service', 'social-customer-mcp.service', 'deputy-relay.service']:
            path = Path('/etc/systemd/system') / name
            run(['systemctl', 'disable', name], check=False)
            if path.is_symlink() and path.resolve() == Path('/dev/null'):
                continue
            path.rename(backups / name)
            path.symlink_to('/dev/null')
        env = dict(os.environ, XDG_RUNTIME_DIR='/run/user/0')
        run(['systemctl', '--user', 'disable', 'openclaw-gateway'], env=env)
        unit = Path('/root/.config/systemd/user/openclaw-gateway.service')
        if not unit.is_symlink():
            unit.rename(backups / 'openclaw-gateway.service')
            unit.symlink_to('/dev/null')
        run(['systemctl', '--user', 'daemon-reload'], env=env)
        run([NODE, PM2, 'delete', 'okki-index', 'leshine-customer-mcp', 'shipment-tracking-mcp'])
        run([NODE, PM2, 'save', '--force'])
        run(['systemctl', 'daemon-reload'])
        (STATE / 'source/retired').write_text('Migrated to leshine.cloud / 154.8.205.162 on 2026-09-26\n')
        return {'status': 'source-retired'}
    if action == 'verify-frozen':
        for name in ['dingtalk-monitor', 'social-customer-mcp', 'deputy-relay', 'ark-okki-outbound-poller.timer', 'ark-okki-outbound-poller.service']:
            result = run(['systemctl', 'is-active', name], check=False)
            if result.stdout.strip() not in ['inactive', 'failed']:
                raise RuntimeError('Source still active: ' + name)
        if any('/root/.openclaw' in l and not l.lstrip().startswith('#')
               for l in run(['crontab', '-l']).stdout.splitlines()):
            raise RuntimeError('Source cron still enabled')
        env = dict(os.environ, XDG_RUNTIME_DIR='/run/user/0')
        gateway = run(['systemctl', '--user', 'show', 'openclaw-gateway', '-p', 'ActiveState', '-p', 'MainPID'], env=env).stdout
        if 'ActiveState=inactive' not in gateway or 'MainPID=0\n' not in gateway:
            raise RuntimeError('Source gateway still active')
        pm2 = json.loads(run([NODE, PM2, 'jlist']).stdout)
        for name in ['okki-index', 'leshine-customer-mcp', 'shipment-tracking-mcp']:
            matches = [p for p in pm2 if p['name'] == name]
            if len(matches) != 1 or matches[0]['pm2_env']['status'] != 'stopped' or matches[0].get('pid', 0):
                raise RuntimeError('Source PM2 not fully stopped: ' + name)
        locks = run(['lslocks', '-n', '--notruncate', '-o', 'PATH']).stdout
        if any('/tmp/' + k in locks for k in ['okki-', 'shopify-']):
            raise RuntimeError('Source business locks still held')
        freeze_id = (STATE / 'source/freeze-id').read_text().strip()
        (STATE / 'source/frozen-verified').write_text(freeze_id)
        return {'status': 'source-frozen', 'freeze_id': freeze_id}
    raise ValueError('Unknown migration phase')


if __name__ == '__main__':
    try:
        print(json.dumps(main(json.load(sys.stdin)['action'])))
    except Exception as exc:
        # Called processes can contain secrets; never echo their stdout/stderr.
        print(type(exc).__name__ + ': ' + (str(exc) if not isinstance(exc, subprocess.CalledProcessError)
              else 'Remote validation command failed'), file=sys.stderr)
        sys.exit(1)
