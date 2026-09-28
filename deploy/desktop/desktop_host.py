"""SSH-only controller. No listener, no credentials, no alternate deploy engine."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from desktop_checks import command, configure_path, probe, protocol, recovery, redact

PREFIX = "ARK_DEPLOY_EVENT "
RUN_ID = re.compile(r"[0-9a-f]{32}")
SHA = re.compile(r"[0-9a-f]{40}")


def atomic(path, data):
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    os.replace(temporary, path)


def root_path(value):
    # cmd.exe interprets percent expansion even within quotes. Do not allow any
    # command metacharacters in this explicitly selected installation path.
    if not isinstance(value, str) or re.search(r'[\r\n"%!&|<>^]', value):
        raise ValueError("安装目录包含不支持的命令字符")
    root = Path(value).resolve()
    if not root.is_dir() or not (root / "deploy/deploy.bat").is_file():
        raise ValueError("安装目录中没有 deploy/deploy.bat")
    return root


def run_path(root, run_id):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run id")
    return root / ".deploy_state/desktop/runs" / run_id


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def process_identity(pid):
    """PID reuse must not turn an interrupted worker into a running release."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times]):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def summarize(path):
    record = read(path / "operation.json")
    if record["status"] == "running" and (not record.get("process_identity") or process_identity(record.get("pid", 0)) != record.get("process_identity")):
        record["status"] = "unknown"
    elif record["status"] == "starting" and time.time() - (path / "operation.json").stat().st_mtime > 60:
        record["status"] = "unknown"
    # Structured events are written separately; output size is bounded without
    # losing the plan or completed steps when the build log becomes large.
    event_file = path / "events.jsonl"
    events = []
    if event_file.exists():
        for line in event_file.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if item.get("run_id") == record["run_id"] and item.get("protocol") == 1:
                    events.append(item)
            except ValueError:
                continue  # A live writer may not have flushed the last line yet.
    record["events"] = events
    log = path / "output.log"
    if log.exists():
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 24000))
            record["log"] = stream.read().decode("utf-8", errors="replace")
    record["diagnosis"] = diagnose(record)
    return record


def diagnose(record):
    failed = [e for e in record.get("events", []) if e.get("status") == "failed"]
    text = record.get("log", "")
    facts = []
    if failed:
        facts.append("已确认失败步骤：" + failed[-1]["label"] + "（" + failed[-1].get("error_type", "error") + "）")
    for patterns, detail in [
        (("Permission denied", "publickey"), "SSH 身份验证失败：核对办公室账号的密钥与目标主机授权。"),
        (("Host key verification failed",), "SSH 主机身份校验失败：人工核对 known_hosts，程序不会关闭身份校验。"),
        (("Could not resolve", "Connection timed out", "Connection refused"), "连接失败：检查办公室连接、隧道、DNS 和对应主机端口。"),
        (("checkout must be clean",), "安装仓库有未提交改动：审查后处理，再准备候选；不要直接清理业务文件。"),
        (("migration requires inspection", "failed-after-ddl", "held stopped", "recovery-required"), "迁移或切换需要恢复核验：保留原始 writer 记录，检查数据库实际结构；不要删除记录或启动旧代码。"),
        (("Deployment locked",), "发布锁存在：恢复查看原任务并核对进程，不要删除锁并发发布。"),
        (("No space left", "not enough space", "磁盘空间不足"), "磁盘空间不足：检查该步骤所在机器的制品目录和可用空间。"),
        (("certificate", "CERTIFICATE_VERIFY_FAILED"), "HTTPS 证书校验失败：检查证书域名、有效期与服务器时间。"),
    ]:
        if any(pattern.lower() in text.lower() for pattern in patterns):
            facts.append("日志线索：" + detail)
    if record.get("status") == "unknown":
        facts.append("未取得可确认的完成回执；先恢复状态、自检服务与原任务日志，不能把断线当作失败后直接重试。")
    if not facts and record.get("status") == "failed":
        facts.append("暂无足够证据确定根因。查看末尾错误日志并执行三处环境自检；已完成步骤可能已生效。")
    return facts


def start(root, request, sources):
    run_id = request["run_id"]
    path = run_path(root, run_id)
    mode = request.get("mode")
    if mode not in ("prepare", "deploy"):
        raise ValueError("Invalid release mode")
    if path.exists():
        existing = read(path / "operation.json")
        if existing["mode"] != mode or existing.get("prepared_run") != request.get("prepared_run"):
            raise ValueError("Run id already belongs to a different request")
        return summarize(path)
    protocol(root)
    recovery(root)
    revision = None
    if mode == "deploy":
        prepared = summarize(run_path(root, request.get("prepared_run")))
        if prepared["status"] != "prepared":
            raise ValueError("更新必须引用成功准备的任务")
        revision = prepared.get("revision")
        if not SHA.fullmatch(revision or ""):
            raise ValueError("准备记录中没有固定的完整 revision")
    state = root / ".deploy_state/desktop"
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "active.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError("已有桌面任务或未核验的中断记录；先恢复查看任务，勿删除 active.lock") from error
    spawned = False
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(run_id)
        path.mkdir(parents=True)
        record = dict(run_id=run_id, mode=mode, status="starting", revision=revision,
                      prepared_run=request.get("prepared_run"))
        atomic(path / "operation.json", record)
        atomic(state / "current.json", {"run_id": run_id})
        digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
        folder = state / "tools" / digest
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("desktop_host", "desktop_checks"):
            (folder / (name + ".py")).write_bytes(base64.b64decode(sources[name], validate=True))
        args = [sys.executable, "-X", "utf8", str(folder / "desktop_host.py"), "--worker", str(root), run_id]
        with (path / "worker.log").open("wb") as output:
            process = subprocess.Popen(args, cwd=root, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                       creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                                       close_fds=True)
        spawned = True
        # The worker owns operation.json after spawn; never overwrite its result.
        atomic(path / "launcher.json", {"pid": process.pid})
        return summarize(path)
    except Exception:
        if not spawned:
            if path.exists():
                atomic(path / "operation.json", dict(run_id=run_id, mode=mode, status="failed", error="worker-start-failed"))
            lock.unlink(missing_ok=True)
        raise


def worker(root, run_id):
    path = run_path(root, run_id)
    record = read(path / "operation.json")
    record.update(status="running", pid=os.getpid(), process_identity=process_identity(os.getpid()))
    atomic(path / "operation.json", record)
    child_started = False
    child_finished = False
    try:
        configure_path()
        # Activation checks are repeated on the publishing machine immediately
        # before invoking its normal engine, even if the GUI was disconnected.
        if record["mode"] == "deploy":
            with (path / "output.log").open("a", encoding="utf-8") as log:
                import contextlib
                with contextlib.redirect_stdout(log):
                    report = probe(root)
            atomic(path / "preflight.json", report)
            if not report["ready"]:
                raise RuntimeError("更新前复核未通过；请执行自检查看失败项")
        arguments = " --prepare-only" if record["mode"] == "prepare" else " --no-pull --revision " + record["revision"]
        environment = dict(os.environ, DEPLOY_NO_PAUSE="1", PYTHONUTF8="1", PYTHONUNBUFFERED="1", ARK_DESKTOP_RUN_ID=run_id)
        process = subprocess.Popen('"' + os.environ.get("COMSPEC", "cmd.exe") + '" /d /s /c ""' + str(root / "deploy/deploy.bat") + '"' + arguments + '"',
                                   cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        child_started = True
        result = None
        with (path / "output.log").open("a", encoding="utf-8") as log, (path / "events.jsonl").open("a", encoding="utf-8") as events:
            for line in process.stdout:
                safe = redact(line)
                log.write(safe)
                log.flush()
                if line.startswith(PREFIX):
                    try:
                        event = json.loads(line[len(PREFIX):])
                        if event.get("run_id") == run_id and event.get("protocol") == 1:
                            events.write(json.dumps(event, ensure_ascii=True) + "\n")
                            events.flush()
                            if event.get("kind") == "result":
                                result = event
                    except ValueError:
                        log.write("Invalid desktop event; result will require verification.\n")
            code = process.wait()
            child_finished = True
        expected = "prepared" if record["mode"] == "prepare" else "succeeded"
        if code == 0 and result and result.get("status") == expected and SHA.fullmatch(result.get("revision", "")):
            if record["mode"] == "deploy" and result["revision"] != record["revision"]:
                raise RuntimeError("部署回执版本与已确认版本不一致")
            record.update(status=expected, revision=result["revision"], exit_code=code)
        else:
            record.update(status="failed" if code else "unknown", exit_code=code)
    except Exception as error:
        # If the worker lost its pipe after spawning, the deployment may still
        # run. Keep the active lock and report unknown, never auto-retry/kill.
        record.update(status="unknown" if child_started and not child_finished else "failed", error=redact(error))
        with (path / "output.log").open("a", encoding="utf-8") as log:
            log.write("\nDESKTOP: " + redact(error) + "\n")
    finally:
        atomic(path / "operation.json", record)
        lock = root / ".deploy_state/desktop/active.lock"
        if record["status"] != "unknown" and lock.exists() and lock.read_text() == run_id:
            lock.unlink()


def dispatch(request, sources):
    root = root_path(request.get("root"))
    action = request.get("action")
    if action == "probe":
        return probe(root)
    if action == "status":
        run_id = request.get("run_id")
        if not run_id:
            current = root / ".deploy_state/desktop/current.json"
            if not current.exists():
                return {"status": "none", "events": [], "log": "尚无桌面任务"}
            run_id = read(current)["run_id"]
        return summarize(run_path(root, run_id))
    if action == "start":
        return start(root, request, sources)
    raise ValueError("Unsupported desktop action")


def main(request, sources):
    try:
        print("ARK_RESPONSE " + json.dumps(dispatch(request, sources), ensure_ascii=True), flush=True)
    except Exception as error:
        print("ARK_RESPONSE " + json.dumps({"error": redact(error)}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit("Internal worker entry only")
    worker(root_path(sys.argv[2]), sys.argv[3])
