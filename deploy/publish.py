"""One release entry for office and cloud; explicit partial scope for cloud-only."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import cloud_backend
import static_sync
from desktop_events import emit, step, enabled as desktop_enabled
from runtime_root import resolve_live_root

ROOT = resolve_live_root(sys.argv[1:], __file__)
STATE = ROOT / ".deploy_state"
SG = "root@119.28.107.92"
BJ = "ubuntu@154.8.205.162"


def run(args, cwd=ROOT, capture=False):
    print("  " + " ".join(str(a) for a in args[:4]), flush=True)
    result = subprocess.run([str(a) for a in args], cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None, timeout=1200)
    return result.stdout.strip() if capture else ""


def atomic_json(path, data):
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def deployment_lock():
    STATE.mkdir(exist_ok=True)
    lock = STATE / "publish.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Deployment locked; inspect the running/previous process before retrying") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink()


def input_digest(paths, extra=""):
    digest = hashlib.sha256(extra.encode())
    ignored = {"node_modules", "dist", "dist-lan", ".venv", "__pycache__", ".pytest_cache", ".git", ".deploy_state", "release"}
    for path in paths:
        files = []
        if path.is_dir():
            for directory, folders, names in os.walk(path):
                folders[:] = sorted(n for n in folders if n not in ignored)
                files.extend(Path(directory) / n for n in sorted(names))
        else:
            files = [path]
        for file in files:
            if not file.is_file() or any(part in ignored for part in file.relative_to(ROOT).parts):
                continue
            digest.update(file.relative_to(ROOT).as_posix().encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def marker(name):
    path = STATE / (name + ".json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def npm_command():
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not executable:
        raise RuntimeError("Node.js/npm is required on the publishing machine")
    return executable


def npm_install(folder):
    stamp = input_digest([folder / "package.json", folder / "package-lock.json"],
                         run(["node", "--version"], capture=True))
    name = "deps-" + folder.name
    if marker(name).get("digest") != stamp or not (folder / "node_modules").exists():
        run([npm_command(), "ci", "--no-audit", "--no-fund"], cwd=folder)
        atomic_json(STATE / (name + ".json"), {"digest": stamp})


def pnpm_command():
    executable = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if not executable:
        raise RuntimeError("Registered customer portal requires pnpm on the publishing machine")
    return executable


def portal_install(folder):
    if not (folder / "pnpm-lock.yaml").is_file():
        raise RuntimeError("Customer portal requires its committed pnpm lockfile")
    executable = pnpm_command()
    stamp = input_digest([folder / "package.json", folder / "pnpm-lock.yaml"],
                         run(["node", "--version"], capture=True) + run([executable, "--version"], capture=True))
    name = "deps-" + folder.name
    if marker(name).get("digest") != stamp or not (folder / "node_modules").exists():
        run([executable, "install", "--frozen-lockfile", "--ignore-scripts"], cwd=folder)
        atomic_json(STATE / (name + ".json"), {"digest": stamp})


def build_frontends(include_portal=False):
    extension = ROOT / "extensions/whatsapp-translation"
    downloads = ROOT / "frontend/public/downloads/whatsapp-translation"
    stamp = input_digest([extension])
    packaged = STATE / "builds" / ("extension-" + stamp)
    if marker("extension").get("digest") != stamp or not (packaged / "latest.json").exists():
        npm_install(extension)
        run([npm_command(), "run", "package", "--", "--output", downloads], cwd=extension)
        shutil.copytree(downloads, packaged, dirs_exist_ok=True)
        atomic_json(STATE / "extension.json", {"digest": stamp, "files": static_sync.manifest(packaged, False)})
    elif static_sync.manifest(packaged, False) != marker("extension")["files"]:
        raise RuntimeError("Cached extension package is corrupt")
    shutil.copytree(packaged, downloads, dirs_exist_ok=True)
    outputs = {}
    node = run(["node", "--version"], capture=True)
    for name in ["frontend", "frontend-pm"] + (["frontend-portal"] if include_portal else []):
        folder = ROOT / name
        stamp = input_digest([folder], node)
        dist = STATE / "builds" / (name + "-" + stamp)
        if not (dist / "index.html").exists() or marker("build-" + name).get("digest") != stamp:
            if name == "frontend-portal":
                portal_install(folder)
                run([pnpm_command(), "exec", "vite", "build", "--outDir", dist], cwd=folder)
            else:
                npm_install(folder)
                run([npm_command(), "run", "build", "--", "--outDir", dist], cwd=folder)
            atomic_json(STATE / ("build-" + name + ".json"), {"digest": stamp, "files": static_sync.manifest(dist)})
        elif static_sync.manifest(dist) != marker("build-" + name)["files"]:
            raise RuntimeError("Cached build is corrupt: " + name)
        else:
            print(f"  {name}: unchanged, build skipped", flush=True)
        outputs[name] = dist
    return outputs


def build_lan():
    folder = ROOT / "frontend-pm"
    stamp = input_digest([folder], run(["node", "--version"], capture=True) + ":base=/pm/")
    dist = STATE / "builds" / ("pm-lan-" + stamp)
    if not (dist / "index.html").exists() or marker("build-pm-lan").get("digest") != stamp:
        npm_install(folder)
        run([npm_command(), "run", "build", "--", "--base=/pm/", "--outDir", dist], cwd=folder)
        atomic_json(STATE / "build-pm-lan.json", {"digest": stamp, "files": static_sync.manifest(dist)})
    elif static_sync.manifest(dist) != marker("build-pm-lan")["files"]:
        raise RuntimeError("Cached LAN build is corrupt")
    return dist


def publish(args):
    global ROOT
    recover_168 = getattr(args, "recover_migration_168", False)
    if recover_168 and (args.cloud_only or not args.revision or args.recover_migration_149 or args.recover_migration_151):
        raise RuntimeError("Recovery 168 requires a pinned full release")
    recover_149 = getattr(args, "recover_migration_149", False)
    recover_151 = getattr(args, "recover_migration_151", False)
    if recover_151 and (recover_149 or args.cloud_only or not args.revision):
        raise RuntimeError("Recovery 151 requires a pinned full office/cloud release")
    if recover_149 and (args.cloud_only or not args.revision):
        raise RuntimeError("Recovery 149 requires a pinned --revision and a full office/cloud release")
    import source_release
    live = ROOT
    emit("begin", prepare_only=args.prepare_only)
    with deployment_lock():
        ROOT, revision, previous = step("source", "获取并校验候选源码", source_release.prepare, live, STATE, not args.no_pull,
                                                         pinned_revision=args.revision)
        if desktop_enabled():
            emit("plan", revision=revision, previous=previous,
                 files=run(["git", "diff", "--name-status", previous, revision], cwd=live, capture=True).splitlines())
        import schema_release
        schema_release.check_recovery(recover_149=recover_149, recover_151=recover_151, recover_168=recover_168)
        from office_release import prepare as office_prepare, activate as office_activate, stage_static
        office_options = {"recover_168": True} if recover_168 else {"recover_149": True} if recover_149 else {"recover_151": True} if recover_151 else {}
        office = None if args.cloud_only else step("office-prepare", "办公室服务、依赖与迁移链预检", office_prepare, live, previous, revision, **office_options)
        if recover_149:
            office["recover_149"] = True
        if recover_151:
            office["recover_151"] = True
        if recover_168:
            office["recover_168"] = True
        inventory = json.loads((ROOT / "deploy/platforms.json").read_text(encoding="utf-8-sig"))
        import okki_outbound_release as outbound_release
        outbound_targets = [item for item in inventory.get('external_services', [])
                            if item.get('name') == 'ark-okki-outbound-poller']
        if len(outbound_targets) != 1 or outbound_targets[0].get('source') != 'deploy/okki_outbound_poller.js':
            raise RuntimeError('Required managed outbound service missing from release inventory')
        if office:
            step("schema-preflight", "共享数据库与全部写入实例预检", schema_release.preflight, office, inventory, args.migration_credentials)
            emit("schema", target=office.get("schema"), pending=office.get("pending", []))
        previous_release = marker('publish-current')
        recovery_original = None
        if recover_168:
            from migration_recovery168 import prepare_release
            recovery_original = prepare_release(STATE, ROOT, revision, previous_release)
        scope = 'cloud-only' if args.cloud_only else 'office-and-cloud'
        release_id = (previous_release.get('release_id') if previous_release.get('revision') == revision
                      and previous_release.get('scope') == scope
                      and previous_release.get('status') != 'succeeded' else None) or uuid.uuid4().hex
        if recovery_original:
            release_id = recovery_original["release_id"]
        journal = {"revision": revision, "release_id": release_id,
                   "scope": scope, "status": "preparing", "completed": [], "deferred": []}
        outbound_revision = recovery_original["revision"] if recovery_original else revision
        if recovery_original:
            journal["recovery_original"] = recovery_original
            journal["outbound_artifact_revision"] = outbound_revision
        outbound = step("outbound-prepare", "准备已登记的出库轮询器", outbound_release.prepare, ROOT, outbound_revision, release_id, allow_pending=bool(office and office.get('pending')))
        journal['outbound'] = outbound['receipt']
        atomic_json(STATE / "publish-current.json", journal)
        outputs = step("build", "构建已登记站点与浏览器扩展", build_frontends,
                       include_portal=any(target["component"] == "frontend-portal" for target in inventory["static_targets"]))
        if office:
            step("office-static", "准备办公室静态文件与内网 PM 站", stage_static, {**{name: dist for name, dist in outputs.items() if name in {"frontend", "frontend-pm"}}, "pm-lan": build_lan()}, office)
        backend = step("beijing-prepare", "准备北京后端与色块服务", cloud_backend.prepare, ROOT, revision, allow_pending=bool(office), **office_options)
        import mail_worker_release
        mail_worker = None
        if any(item.get('name') == 'ark-mail-outreach' for item in inventory.get('external_services', [])):
            mail_worker = step('mail-worker-prepare', '准备北京邮件 Worker 与固定 CLI', mail_worker_release.prepare, ROOT, revision, release_id)
            journal['mail_worker'] = mail_worker['receipt']
            atomic_json(STATE / 'publish-current.json', journal)
        import colorwork_routing
        colorwork_routes = step("routing-prepare", "校验色块路由配置", colorwork_routing.prepare, ROOT / "deploy")
        prepared = []
        outputs["customer-media"] = outputs["frontend"] / "customer-media"
        for target in inventory["static_targets"]:
            if args.cloud_only and target.get("backend_owner") == "office":
                files = static_sync.manifest(outputs[target["component"]])
                comparison = static_sync.remote(target["host"], {"action": "plan", "root": target["root"], "manifest": files})
                if comparison["missing"]:
                    journal["deferred"].append(target["domain"] + ": changed frontend waits for matching office backend")
                    print("DEFERRED " + journal["deferred"][-1], flush=True)
                    atomic_json(STATE / "publish-current.json", journal)
                    continue
            prepared.append(step("static-prepare:" + target["domain"], "增量准备 " + target["domain"], static_sync.prepare, outputs[target["component"]], target["host"], target["root"],
                            STATE / "transfers", target["domain"]))
        if args.prepare_only:
            journal["status"] = "prepared"
            atomic_json(STATE / "publish-current.json", journal)
            print("Prepared and verified; no service or live static pointer activated.")
            emit("result", status="prepared", revision=revision)
            return
        journal["status"] = "activating"
        atomic_json(STATE / "publish-current.json", journal)
        journal['outbound'] = step("freeze", "暂停并排空出库轮询器", outbound_release.phase, outbound, 'freeze')
        if recovery_original and journal['outbound'].get('schedule') != recovery_original['outbound']['schedule']:
            raise RuntimeError('Recovery 168 outbound baseline drift')
        atomic_json(STATE / "publish-current.json", journal)
        if mail_worker:
            journal['mail_worker'] = step('mail-worker-freeze', '停止邮件领取并排空发送及回执', mail_worker_release.invoke, mail_worker, 'freeze')
            atomic_json(STATE / 'publish-current.json', journal)
        stopped = step("migration", "共享数据库迁移（无变更则跳过）", schema_release.migrate, office, inventory, args.migration_credentials) if office else []
        journal['outbound'] = step("outbound-install", "安装完整出库制品并保持调度暂停", outbound_release.phase, outbound, 'install')
        atomic_json(STATE / "publish-current.json", journal)
        if office:
            print(json.dumps(step("office-activate", "切换并验证办公室应用及静态文件", office_activate, office)), flush=True)
            journal["completed"].append("office")
            atomic_json(STATE / "publish-current.json", journal)
        print(json.dumps(step("beijing-activate", "切换并验证北京后端与色块服务", cloud_backend.activate, revision)), flush=True)
        journal["completed"].append("beijing-backend")
        atomic_json(STATE / "publish-current.json", journal)
        for item in colorwork_routes:
            result = step("routing:" + item["payload"]["region"], "激活色块路由 " + item["payload"]["region"], colorwork_routing.activate, item, ROOT / "deploy")
            journal["completed"].append("colorwork-routing:" + result["region"])
            atomic_json(STATE / "publish-current.json", journal)
        if office:
            with schema_release.database_lock(ROOT, office["python"]):
                schema_release.schema_check(ROOT, office["python"])
                step("seed-pm", "同步 PM 基础数据", run, [office["python"], "scripts/seed_pm.py"], cwd=ROOT / "backend")
                step("seed-pantone", "同步色卡基础数据", run, [office["python"], "scripts/import_pantone.py"], cwd=ROOT / "backend")
        for item in prepared:
            print(json.dumps(step("static-activate:" + item["request"].get("host", item["target"]), "切换并验证静态站 " + item["request"].get("host", item["target"]), static_sync.activate, item)), flush=True)
            journal["completed"].append(item["target"] + ":" + item["request"]["root"])
            atomic_json(STATE / "publish-current.json", journal)
        journal['outbound'] = step("outbound-activate", "更新已登记的出库脚本并核验模式目标", outbound_release.phase, outbound, 'activate')
        atomic_json(STATE / "publish-current.json", journal)
        if stopped:
            step("writers-resume", "恢复原本运行的关联写入服务", schema_release.resume_external, stopped, office, outbound=outbound, journal=journal)
        journal['outbound'] = step("outbound-verify", "核验出库版本摘要与调度状态", outbound_release.verify_completion, outbound, journal)
        journal['completed'].append('singapore-outbound')
        if mail_worker:
            journal['mail_worker'] = step('mail-worker-activate', '切换并验证北京邮件 Worker', mail_worker_release.invoke, mail_worker, 'activate')
            journal['mail_worker'] = step('mail-worker-verify', '核验邮件 Worker 版本、OAuth 与回执', mail_worker_release.invoke, mail_worker, 'verify')
            journal['completed'].append('beijing-mail-worker')
        atomic_json(STATE / "publish-current.json", journal)
        if office:
            schema_release.complete(office)
        summary = {"revision": revision, "scope": "cloud-only" if args.cloud_only else "office-and-cloud",
                   "schema": backend["schema"], "transfer_bytes": sum(item["bytes"] for item in prepared),
                   "deferred": journal["deferred"], "outbound": journal['outbound'],
                   "unmanaged_services": [dict(name=item['name'], status='not_deployed')
                                          for item in inventory.get('external_services', [])
                                          if item['name'] not in {'ark-okki-outbound-poller', 'ark-mail-outreach'}]}
        if mail_worker:
            summary['mail_worker'] = journal['mail_worker']
        atomic_json(STATE / "publish-success.json", summary)
        journal["status"] = "succeeded"
        atomic_json(STATE / "publish-current.json", journal)
        emit("result", status="succeeded", revision=revision, completed=journal["completed"],
             unmanaged_services=summary["unmanaged_services"], deferred=journal["deferred"])
        print("CLOUD RELEASE COMPLETED (office not included)" if args.cloud_only else "MANAGED APPLICATION RELEASE COMPLETED")
        print(json.dumps(summary), flush=True)
        print("Independent service and terminal installation coverage: deploy/platforms.json")
        for item in inventory["pending_targets"]:
            print("PENDING " + item["component"] + ": " + item["reason"])


if __name__ == "__main__":
    sys.modules["publish"] = sys.modules[__name__]
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--colorwork-backup-policy', action='store_true', help='Install hourly retention of two recent Colorwork recovery backups')
    parser.add_argument('--agent-cloud-migration', choices=['prepare', 'validate-staged', 'freeze-source', 'copy-frozen-state', 'configure-target', 'activate-target', 'verify-target', 'retire-source', 'nginx-prepare', 'nginx-activate', 'nginx-verify', 'source-routes-prepare', 'source-routes-activate', 'source-routes-verify'], help='Execute one journalled phase of the inspected Agent migration')
    parser.add_argument('--storage-maintenance', metavar='PLAN_JSON', help='Freeze/restore API ingress and direct office LAN access')
    parser.add_argument('--recover-colorwork-start-order', metavar='PLAN_JSON', help='Recover the inspected schema-160 dependency-order interruption')
    parser.add_argument('--finalize-release', metavar='PLAN_JSON', help='Complete the inspected post-DDL activated release without repeating migrations')
    parser.add_argument('--storage-cutover', metavar='PLAN_JSON', help='Execute a journalled COS cutover phase')
    parser.add_argument("--storage-routing-only", metavar="PROBES_JSON", help="Prepare/activate public COS routing with explicit cloud object probes")
    parser.add_argument("--okki-outbound-only", action="store_true", help="Deploy and enable only the Beijing outbound worker")
    parser.add_argument('--okki-sync-only', metavar='PLAN_JSON', help='Prepare/activate only the reviewed Beijing outbound mirror')
    parser.add_argument('--mail-worker-stage', choices=['prepare', 'provision', 'configure', 'oauth', 'enable-sending'], help='Prepare Beijing mail service/OAuth without activating application code')
    parser.add_argument("--cloud-only", action="store_true")
    parser.add_argument("--no-pull", action="store_true")
    parser.add_argument("--revision", help="Pin a reviewed full commit SHA; fetch still runs unless --no-pull")
    parser.add_argument("--live-root", help="Installed checkout for a pinned deployer under its .deploy_state/sources")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--restore-pre151", metavar="PLAN", help="Restore only the reviewed compatible applications after the failed 151 migration")
    parser.add_argument("--office-lan-https", metavar="PLAN", help="Configure only office LAN HTTPS using an existing domain certificate")
    parser.add_argument("--shipping-video-routing-only", action="store_true", help="Enable 100MB private shipping video uploads on existing backends")
    parser.add_argument("--voucher-routing-only", action="store_true", help="Route recharge uploads and voucher reads to the office only")
    parser.add_argument("--receipt-routing-only", action="store_true", help="Route receipts and 10MiB proofs to the office only")
    parser.add_argument("--colorwork-routing-only", action="store_true", help="Route colorwork to the existing healthy Beijing module")
    parser.add_argument("--migrate-only", metavar="PLAN", help="Execute only the reviewed 137 -> 138 migration using a verified local plan")
    parser.add_argument("--recover-migration-168", action="store_true", help="Recover only the inspected 168 collation incident")
    parser.add_argument("--invoice-schema-only", metavar="PLAN", help="Repair only the reviewed 164 -> 167 invoice schema gap")
    parser.add_argument("--recover-invoice-166", metavar="PLAN", help="Resume only the inspected partial invoice migration 166")
    parser.add_argument("--recover-migration-151", action="store_true", help="Resume only the reviewed 151 foreign-key failure preserving original writer evidence")
    parser.add_argument("--recover-migration-149", action="store_true", help="Resume only the inspected revision-149 overflow with original writer evidence")
    parser.add_argument("--migration-credentials", help="Override protected DBA user/password file; defaults to .deploy_state/credentials/migration.env when DDL is pending")
    try:
        args = parser.parse_args()
        if args.okki_sync_only:
            if any(value for key, value in vars(args).items() if key not in {'okki_sync_only', 'prepare_only'}):
                raise RuntimeError('Outbound mirror release only accepts its plan and --prepare-only')
            from okki_sync_release import execute
            execute(args.okki_sync_only, args.prepare_only)
            sys.exit(0)
        if args.recover_migration_168 and any(value for key, value in vars(args).items() if key not in {"recover_migration_168", "prepare_only", "revision", "live_root", "no_pull", "migration_credentials"}):
            raise RuntimeError("Recovery 168 only accepts a pinned full release")
        if args.mail_worker_stage:
            if any(value for key, value in vars(args).items() if key not in {'mail_worker_stage', 'revision', 'live_root', 'no_pull'}):
                raise RuntimeError('Mail setup cannot be combined with application release actions')
            source = Path(__file__).resolve().parent.parent
            actual = run(['git', 'rev-parse', 'HEAD'], cwd=source, capture=True)
            if args.revision != actual or run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=source, capture=True):
                raise RuntimeError('Mail setup requires the clean pinned candidate')
            with deployment_lock():
                if args.mail_worker_stage in {'configure', 'enable-sending'}:
                    from mail_worker_config import configure
                    print(json.dumps(configure(source, ROOT, args.revision, enable_sending=args.mail_worker_stage == 'enable-sending')), flush=True)
                else:
                    from mail_worker_release import execute
                    execute(source, args.revision, args.mail_worker_stage)
        elif args.colorwork_backup_policy:
            if any(value for key, value in vars(args).items() if key not in {'colorwork_backup_policy', 'prepare_only'}):
                raise RuntimeError('Backup policy only accepts --prepare-only')
            from colorwork_backup_policy import execute
            execute(args.prepare_only)
        elif args.agent_cloud_migration:
            if any(value for key, value in vars(args).items() if key != 'agent_cloud_migration'):
                raise RuntimeError('Agent migration cannot be combined with other release actions')
            from agent_cloud_migration import execute
            execute(args.agent_cloud_migration)
        elif args.recover_colorwork_start_order:
            if any(value for key, value in vars(args).items() if key not in {'recover_colorwork_start_order', 'prepare_only'}):
                raise RuntimeError('Start-order recovery only accepts --prepare-only')
            from recover_colorwork_order import execute
            execute(args.recover_colorwork_start_order, args.prepare_only)
        elif args.storage_cutover:
            if any(value for key, value in vars(args).items() if key not in {'storage_cutover', 'prepare_only'}):
                raise RuntimeError('Storage cutover only accepts --prepare-only')
            from storage_cutover import execute
            execute(args.storage_cutover, args.prepare_only)
        elif args.finalize_release:
            if any(value for key, value in vars(args).items() if key not in {'finalize_release', 'prepare_only'}):
                raise RuntimeError('Release finalization only accepts --prepare-only')
            from release_finalize_dispatch import execute
            execute(args.finalize_release, args.prepare_only)
        elif args.storage_maintenance:
            if any(value for key, value in vars(args).items() if key not in {'storage_maintenance', 'prepare_only'}):
                raise RuntimeError('Storage maintenance only accepts --prepare-only')
            from storage_maintenance import execute
            execute(args.storage_maintenance, args.prepare_only)
        elif args.storage_routing_only:
            if any(value for key, value in vars(args).items() if key not in {"storage_routing_only", "prepare_only"}):
                raise RuntimeError('Storage routing only accepts --prepare-only')
            from storage_routing import execute
            execute(args.prepare_only, args.storage_routing_only)
        elif args.receipt_routing_only:
            if any(value for key, value in vars(args).items() if key not in {"receipt_routing_only", "prepare_only"}):
                raise RuntimeError("Receipt routing only accepts --prepare-only")
            from voucher_routing import execute
            execute(args.prepare_only, feature="receipt")
        elif args.okki_outbound_only:
            if any(value for key, value in vars(args).items() if key not in {"okki_outbound_only", "prepare_only"}):
                raise RuntimeError("Outbound-only accepts only --prepare-only")
            from okki_outbound_release import execute
            execute(args.prepare_only)
        elif args.restore_pre151:
            if any(value for key, value in vars(args).items() if key not in {"restore_pre151", "prepare_only"}):
                raise RuntimeError("Restore pre151 only accepts its plan and --prepare-only")
            from restore_152 import execute
            execute(args.restore_pre151, args.prepare_only)
        elif args.office_lan_https:
            if args.shipping_video_routing_only or args.colorwork_routing_only or args.voucher_routing_only or args.migrate_only or args.cloud_only or args.no_pull or args.revision or args.recover_migration_149 or args.recover_migration_151 or args.migration_credentials:
                raise RuntimeError("Office LAN HTTPS only accepts its plan and --prepare-only")
            from office_lan_https import execute
            execute(args.office_lan_https, args.prepare_only)
        elif args.shipping_video_routing_only:
            if args.colorwork_routing_only or args.voucher_routing_only or args.migrate_only or args.cloud_only or args.no_pull or args.revision or args.recover_migration_149 or args.recover_migration_151 or args.migration_credentials:
                raise RuntimeError("Shipping video routing only accepts --prepare-only")
            from voucher_routing import execute
            execute(args.prepare_only, feature="shipping-video")
        elif args.colorwork_routing_only:
            if args.voucher_routing_only or args.migrate_only or args.cloud_only or args.no_pull or args.revision or args.recover_migration_149 or args.recover_migration_151 or args.migration_credentials:
                raise RuntimeError("Colorwork routing only accepts --prepare-only")
            from colorwork_routing import execute
            execute(args.prepare_only)
        elif args.voucher_routing_only:
            if args.migrate_only or args.cloud_only or args.no_pull or args.revision or args.recover_migration_149 or args.recover_migration_151 or args.migration_credentials:
                raise RuntimeError("Voucher routing only accepts --prepare-only")
            from voucher_routing import execute
            execute(args.prepare_only)
        elif args.recover_invoice_166:
            if any(value for key, value in vars(args).items()
                   if key not in {"recover_invoice_166", "prepare_only", "migration_credentials"}):
                raise RuntimeError("Invoice 166 recovery accepts only its plan and migration credential")
            from invoice_schema_repair import recover_execute
            recover_execute(args.recover_invoice_166, args.migration_credentials, args.prepare_only)
        elif args.invoice_schema_only:
            if any(value for key, value in vars(args).items()
                   if key not in {"invoice_schema_only", "prepare_only", "migration_credentials"}):
                raise RuntimeError("Invoice schema repair accepts only its plan and migration credential")
            from invoice_schema_repair import execute
            execute(args.invoice_schema_only, args.migration_credentials, args.prepare_only)
        elif args.migrate_only:
            if args.cloud_only or args.no_pull or args.revision or args.recover_migration_149 or args.recover_migration_151:
                raise RuntimeError("Migration-only uses its pinned plan; cloud-only/no-pull/revision do not apply")
            from migration_only import execute
            execute(args.migrate_only, args.migration_credentials, args.prepare_only)
        else:
            publish(args)
    except Exception as error:
        if any(getattr(locals().get('args'), key, None) for key in ['okki_sync_only', 'mail_worker_stage', 'colorwork_backup_policy', 'storage_maintenance', 'finalize_release', 'storage_cutover', 'recover_colorwork_start_order']):
            print('STORAGE MAINTENANCE FAILED: ' + str(error), file=sys.stderr, flush=True)
            sys.exit(1)
        if not getattr(locals().get("args"), "storage_routing_only", None) and not getattr(locals().get("args"), "receipt_routing_only", False) and not getattr(locals().get("args"), "okki_outbound_only", False) and STATE.exists() and not getattr(locals().get("args"), "restore_pre151", None) and not getattr(locals().get("args"), "office_lan_https", None) and not getattr(locals().get("args"), "migrate_only", None) and not getattr(locals().get("args"), "invoice_schema_only", None) and not getattr(locals().get("args"), "recover_invoice_166", None) and not getattr(locals().get("args"), "voucher_routing_only", False) and not getattr(locals().get("args"), "colorwork_routing_only", False) and not getattr(locals().get("args"), "shipping_video_routing_only", False):
            journal = marker("publish-current")
            journal.update(status="failed", error_type=type(error).__name__)
            atomic_json(STATE / "publish-current.json", journal)
        print("DEPLOY FAILED: " + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
