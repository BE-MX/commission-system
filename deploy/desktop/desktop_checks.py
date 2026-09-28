"""Read-only office/cloud probes, also used after a failed release."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

SSH = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
       "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2"]
HOSTS = {"beijing": "ubuntu@154.8.205.162", "singapore": "root@119.28.107.92"}


def redact(value):
    value = str(value)
    value = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    value = re.sub(r'''(?ix)((?:password|passwd|secret|token|api[_-]?key|authorization|COMMISSION_DB_PASSWORD)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''', r"\1[REDACTED]", value)
    return value


def command(args, root, timeout=25):
    result = subprocess.run(args, cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError(redact((result.stderr or result.stdout)[-1200:]) or "命令失败，退出码 " + str(result.returncode))
    return result.stdout.strip()


def http(url, health=False):
    with urllib.request.urlopen(url, timeout=12) as response:
        if response.status != 200:
            raise RuntimeError("HTTP " + str(response.status))
        if health:
            data = json.load(response)
            if data.get("status") != "ok" or data.get("database") != "connected":
                raise RuntimeError("应用或数据库未就绪")
            return "HTTP 200；应用正常，数据库已连接"
        return "HTTPS 200；证书校验通过（仅验证网页可达）"


def configure_path():
    git = shutil.which("git")
    if git:
        ssh_bin = Path(git).parent.parent / "usr/bin"
        if (ssh_bin / "ssh.exe").exists():
            os.environ["PATH"] = str(ssh_bin) + os.pathsep + os.environ.get("PATH", "")


def probe(root):
    configure_path()
    rows = []

    def check(group, name, action, required=True):
        try:
            detail = action()
            rows.append(dict(group=group, name=name, status="ok", detail=redact(detail), required=required))
            print("ARK_CHECK " + json.dumps(rows[-1], ensure_ascii=True), flush=True)
            return detail
        except Exception as error:
            rows.append(dict(group=group, name=name, status="failed" if required else "warning",
                             detail=redact(error), required=required))
            print("ARK_CHECK " + json.dumps(rows[-1], ensure_ascii=True), flush=True)
            return None

    def clean():
        status = command(["git", "status", "--porcelain", "--untracked-files=normal"], root)
        if status:
            raise RuntimeError("工作区有未提交改动，请先审查处理；桌面工具不会自动提交或清理。\n" + status[:1200])
        return command(["git", "rev-parse", "HEAD"], root)

    check("办公室服务器", "运行源码与工作区", clean)
    check("办公室服务器", "部署入口与进度协议", lambda: protocol(root))
    check("办公室服务器", "发布锁与迁移恢复记录", lambda: recovery(root))
    for tool in ("git", "node", "npm.cmd", "ssh"):
        check("办公室服务器", tool, lambda tool=tool: shutil.which(tool) or missing(tool + " 未安装或不在 PATH"))
    nssm = shutil.which("nssm") or str(Path.home() / "AppData/Local/Microsoft/WinGet/Links/nssm.exe")
    directory = check("办公室服务器", "服务安装目录", lambda: command([nssm, "get", "CommissionSystem", "AppDirectory"], root))
    if directory and Path(directory).resolve() != (root / "backend").resolve():
        rows.append(dict(group="办公室服务器", name="服务归属", status="failed", required=True, detail="所选仓库不是 NSSM 正在使用的安装目录"))
    for service in ("CommissionSystem", "WhatsAppConnector"):
        check("办公室服务器", service, lambda service=service: running(command([nssm, "status", service], root), "SERVICE_RUNNING"))
    parameters = check("办公室服务器", "后端监听参数", lambda: command([nssm, "get", "CommissionSystem", "AppParameters"], root))
    port = re.search(r"--port[ =]+(\d+)", parameters or "")
    check("办公室服务器", "后端与数据库", lambda: http("http://127.0.0.1:" + (port.group(1) if port else missing("无法识别服务端口")) + "/health", True))

    inventory = json.loads((root / "deploy/platforms.json").read_text(encoding="utf-8-sig"))
    for group, host, units in (("leshine.cloud", HOSTS["beijing"], ["nginx", "ark-backend", "ark-colorwork"]),
                               ("leshine.work", HOSTS["singapore"], ["nginx", "frps"])):
        for unit in units:
            check(group, unit, lambda host=host, unit=unit: running(command(["ssh", *SSH, host, "systemctl is-active " + unit], root), "active"))
    check("leshine.cloud", "后端与数据库", lambda: cloud_health(root))
    check("leshine.work", "新加坡到办公室的业务隧道", lambda: cloud_health(root, "singapore", 8002))
    for domain in ("leshine.cloud", "leshine.work"):
        check(domain, "公网 API 路由与鉴权", lambda domain=domain: public_api(domain))
    for target in inventory.get("static_targets", []):
        domain = target["domain"]
        if not re.fullmatch(r"[a-z0-9.-]+\.leshine\.(?:work|cloud)|leshine\.(?:work|cloud)", domain):
            raise ValueError("未登记的公开域名")
        check("leshine.work" if domain.endswith("work") else "leshine.cloud", domain, lambda domain=domain: http("https://" + domain + "/"))
    for item in inventory.get("external_services", []):
        if item["name"] == "frps":
            continue
        group = {"office": "办公室服务器", "beijing": "leshine.cloud", "singapore": "leshine.work"}.get(item["host"], item["host"])
        if item["manager"] == "systemd" and item["host"] in HOSTS and re.fullmatch(r"[a-zA-Z0-9_-]+", item["name"]):
            unit = item.get("timer", item["name"])
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", unit):
                raise ValueError("Invalid service unit")
            # Timers may intentionally be stopped; report actual state as an
            # advisory. The deployment engine verifies/restores its baseline.
            check(group, unit + "（原状态）", lambda item=item, unit=unit: service_detail(command(["ssh", *SSH, HOSTS[item["host"]], "systemctl show " + unit + " --property=ActiveState,SubState,UnitFileState --no-pager"], root)), False)
        elif item["manager"] == "pm2":
            registered_host = HOSTS.get(item["host"])
            writer = next((w for w in inventory.get("migration_writers", []) if w.get("kind") == "pm2" and w.get("host") == registered_host), None)
            if writer:
                check(group, item["name"] + "（root PM2 PID）", lambda writer=writer, item=item: pm2_pid(root, writer, item["name"]), False)
            else:
                rows.append(dict(group=group, name=item["name"], status="unknown", required=False, detail="未登记可验证的 PM2 执行路径；不宣称已启动，不参与本次更新"))
        elif item["manager"] == "systemd-user" and item.get("user") == "root" and item["host"] in HOSTS:
            check(group, item["name"] + "（用户服务）", lambda item=item: user_service(root, item), False)
        else:
            rows.append(dict(group=group, name=item["name"], status="unknown", required=False, detail="尚无对应状态探针，未验证；不计入本次更新成功范围"))
    return dict(checks=rows, checked_at=time.strftime("%Y-%m-%d %H:%M:%S +08:00", time.gmtime(time.time() + 8 * 3600)),
                ready=all(row["status"] == "ok" for row in rows if row["required"]))


def service_detail(value):
    if "ActiveState=active" not in value.splitlines():
        raise RuntimeError(value + "；当前未运行。可能为原有停用状态，不会自动启用。")
    return value


def positive_pid(value):
    if not value.strip().isdigit() or int(value.strip()) <= 0:
        raise RuntimeError("未发现运行 PID：" + value)
    return "运行 PID=" + value


def pm2_pid(root, writer, service):
    binary = writer.get("executable", "")
    target = writer.get("host")
    if target not in HOSTS.values() or not re.fullmatch(r"/root/\.nvm/versions/node/v[0-9.]+/bin/pm2", binary) or not re.fullmatch(r"[A-Za-z0-9_-]+", service):
        raise ValueError("未登记或无效的 PM2 查询目标")
    # The registered PM2 belongs to root even when SSH uses ubuntu. Match the
    # installed schema_release.pm2_command context; never select ubuntu's daemon.
    prefix = "sudo -n -H -u root " if not target.startswith("root@") else ""
    remote = prefix + "env HOME=/root PM2_HOME=/root/.pm2 PATH=" + binary.rsplit("/", 1)[0] + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin " + binary + " pid " + service
    return positive_pid(command(["ssh", *SSH, target, remote], root))


def user_service(root, item):
    unit = item.get("unit", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.service", unit):
        raise ValueError("未登记或无效的用户服务 unit")
    target = HOSTS[item["host"]]
    prefix = "sudo -n -H -u root " if not target.startswith("root@") else ""
    remote = prefix + "env XDG_RUNTIME_DIR=/run/user/0 systemctl --user show " + unit + " --property=ActiveState,SubState,UnitFileState --no-pager"
    return service_detail(command(["ssh", *SSH, target, remote], root))


def missing(message):
    raise RuntimeError(message)


def public_api(domain):
    # Anonymous request intentionally stops at HTTPBearer before any user data
    # lookup. HTML/WAF/static fallbacks are never treated as healthy API routes.
    try:
        with urllib.request.urlopen("https://" + domain + "/api/auth/me", timeout=12):
            raise RuntimeError("匿名请求意外成功，未证明预期鉴权行为")
    except urllib.error.HTTPError as error:
        with error:
            if error.code not in (401, 403):
                raise RuntimeError("API 返回 HTTP " + str(error.code)) from None
            data = json.load(error)
            message = data.get("detail", data.get("message"))
            if message != "Not authenticated":
                raise RuntimeError("未收到应用预期的匿名鉴权响应") from None
            return "HTTPS API 正确拒绝匿名请求；业务路由可达，未读取用户数据"


def running(actual, expected):
    if actual != expected:
        raise RuntimeError("服务状态：" + actual + "；预期：" + expected)
    return actual


def protocol(root):
    source = root / "deploy/desktop_events.py"
    if not source.exists() or "from desktop_events import" not in (root / "deploy/publish.py").read_text(encoding="utf-8"):
        raise RuntimeError("服务器部署器尚未包含桌面进度协议；请先集成本次 deploy 改动，不能用历史成功记录替代")
    return "统一 deploy.bat；桌面进度协议 v1"


def recovery(root):
    state = root / ".deploy_state"
    if (state / "publish.lock").exists():
        raise RuntimeError("发布锁存在；请恢复查看正在运行的任务，勿删除锁后重试")
    path = state / "schema-writers.json"
    if path.exists():
        status = json.loads(path.read_text(encoding="utf-8")).get("status")
        if status not in ("completed", "restored-before-ddl"):
            raise RuntimeError("迁移需要人工核验：" + str(status) + "；保留 schema-writers.json，勿自动恢复旧代码")
    return "未发现发布锁或未完成的迁移恢复记录；候选准备阶段会继续核验数据库实际版本"


def cloud_health(root, region="beijing", port=8001):
    data = json.loads(command(["ssh", *SSH, HOSTS[region], "curl --fail --silent --show-error --max-time 10 http://127.0.0.1:" + str(port) + "/health"], root))
    if data.get("status") != "ok" or data.get("database") != "connected":
        raise RuntimeError(region + " 应用或数据库未就绪")
    return "应用正常，数据库已连接"
