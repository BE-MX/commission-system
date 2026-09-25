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


def build_frontends():
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
    for name in ["frontend", "frontend-pm"]:
        folder = ROOT / name
        stamp = input_digest([folder], node)
        dist = STATE / "builds" / (name + "-" + stamp)
        if not (dist / "index.html").exists() or marker("build-" + name).get("digest") != stamp:
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
    with deployment_lock():
        ROOT, revision, previous = source_release.prepare(live, STATE, not args.no_pull,
                                                         pinned_revision=args.revision)
        import schema_release
        schema_release.check_recovery(recover_149=recover_149, recover_151=recover_151, recover_168=recover_168)
        from office_release import prepare as office_prepare, activate as office_activate, stage_static
        office_options = {"recover_168": True} if recover_168 else {"recover_149": True} if recover_149 else {"recover_151": True} if recover_151 else {}
        office = None if args.cloud_only else office_prepare(live, previous, revision, **office_options)
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
            schema_release.preflight(office, inventory, args.migration_credentials)
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
        outbound = outbound_release.prepare(ROOT, outbound_revision, release_id, allow_pending=bool(office and office.get('pending')))
        journal['outbound'] = outbound['receipt']
        atomic_json(STATE / "publish-current.json", journal)
        outputs = build_frontends()
        if office:
            stage_static({**outputs, "pm-lan": build_lan()}, office)
        backend = cloud_backend.prepare(ROOT, revision, allow_pending=bool(office), **office_options)
        import colorwork_routing
        colorwork_routes = colorwork_routing.prepare(ROOT / "deploy")
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
            prepared.append(static_sync.prepare(outputs[target["component"]], target["host"], target["root"],
                            STATE / "transfers", target["domain"]))
        if args.prepare_only:
            journal["status"] = "prepared"
            atomic_json(STATE / "publish-current.json", journal)
            print("Prepared and verified; no service or live static pointer activated.")
            return
        journal["status"] = "activating"
        atomic_json(STATE / "publish-current.json", journal)
        journal['outbound'] = outbound_release.phase(outbound, 'freeze')
        if recovery_original and journal['outbound'].get('schedule') != recovery_original['outbound']['schedule']:
            raise RuntimeError('Recovery 168 outbound baseline drift')
        atomic_json(STATE / "publish-current.json", journal)
        stopped = schema_release.migrate(office, inventory, args.migration_credentials) if office else []
        if office:
            print(json.dumps(office_activate(office)), flush=True)
            journal["completed"].append("office")
            atomic_json(STATE / "publish-current.json", journal)
        print(json.dumps(cloud_backend.activate(revision)), flush=True)
        journal["completed"].append("beijing-backend")
        atomic_json(STATE / "publish-current.json", journal)
        for item in colorwork_routes:
            result = colorwork_routing.activate(item, ROOT / "deploy")
            journal["completed"].append("colorwork-routing:" + result["region"])
            atomic_json(STATE / "publish-current.json", journal)
        if office:
            with schema_release.database_lock(ROOT, office["python"]):
                schema_release.schema_check(ROOT, office["python"])
                run([office["python"], "scripts/seed_pm.py"], cwd=ROOT / "backend")
                run([office["python"], "scripts/import_pantone.py"], cwd=ROOT / "backend")
        for item in prepared:
            print(json.dumps(static_sync.activate(item)), flush=True)
            journal["completed"].append(item["target"] + ":" + item["request"]["root"])
            atomic_json(STATE / "publish-current.json", journal)
        journal['outbound'] = outbound_release.phase(outbound, 'activate')
        atomic_json(STATE / "publish-current.json", journal)
        if stopped:
            schema_release.resume_external(stopped, office)
        journal['outbound'] = outbound_release.phase(outbound, 'verify')
        journal['completed'].append('singapore-outbound')
        atomic_json(STATE / "publish-current.json", journal)
        if office:
            schema_release.complete(office)
        summary = {"revision": revision, "scope": "cloud-only" if args.cloud_only else "office-and-cloud",
                   "schema": backend["schema"], "transfer_bytes": sum(item["bytes"] for item in prepared),
                   "deferred": journal["deferred"], "outbound": journal['outbound'],
                   "unmanaged_services": [dict(name=item['name'], status='not_deployed')
                                          for item in inventory.get('external_services', [])
                                          if item['name'] != 'ark-okki-outbound-poller']}
        atomic_json(STATE / "publish-success.json", summary)
        journal["status"] = "succeeded"
        atomic_json(STATE / "publish-current.json", journal)
        print("CLOUD RELEASE COMPLETED (office not included)" if args.cloud_only else "MANAGED APPLICATION RELEASE COMPLETED")
        print(json.dumps(summary), flush=True)
        print("Independent service and terminal installation coverage: deploy/platforms.json")
        for item in inventory["pending_targets"]:
            print("PENDING " + item["component"] + ": " + item["reason"])


if __name__ == "__main__":
    sys.modules["publish"] = sys.modules[__name__]
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--storage-maintenance', metavar='PLAN_JSON', help='Freeze/restore API ingress and direct office LAN access')
    parser.add_argument('--recover-colorwork-start-order', metavar='PLAN_JSON', help='Recover the inspected schema-160 dependency-order interruption')
    parser.add_argument('--finalize-release', metavar='PLAN_JSON', help='Complete the inspected post-DDL activated release without repeating migrations')
    parser.add_argument('--storage-cutover', metavar='PLAN_JSON', help='Execute a journalled COS cutover phase')
    parser.add_argument("--storage-routing-only", metavar="PROBES_JSON", help="Prepare/activate public COS routing with explicit cloud object probes")
    parser.add_argument("--okki-outbound-only", action="store_true", help="Deploy and enable only the Singapore outbound worker")
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
    parser.add_argument("--recover-migration-151", action="store_true", help="Resume only the reviewed 151 foreign-key failure preserving original writer evidence")
    parser.add_argument("--recover-migration-149", action="store_true", help="Resume only the inspected revision-149 overflow with original writer evidence")
    parser.add_argument("--migration-credentials", help="Override protected DBA user/password file; defaults to .deploy_state/credentials/migration.env when DDL is pending")
    try:
        args = parser.parse_args()
        if args.recover_migration_168 and any(value for key, value in vars(args).items() if key not in {"recover_migration_168", "prepare_only", "revision", "live_root", "no_pull", "migration_credentials"}):
            raise RuntimeError("Recovery 168 only accepts a pinned full release")
        if args.recover_colorwork_start_order:
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
        elif args.migrate_only:
            if args.cloud_only or args.no_pull or args.revision or args.recover_migration_149 or args.recover_migration_151:
                raise RuntimeError("Migration-only uses its pinned plan; cloud-only/no-pull/revision do not apply")
            from migration_only import execute
            execute(args.migrate_only, args.migration_credentials, args.prepare_only)
        else:
            publish(args)
    except Exception as error:
        if any(getattr(locals().get('args'), key, None) for key in ['storage_maintenance', 'finalize_release', 'storage_cutover', 'recover_colorwork_start_order']):
            print('STORAGE MAINTENANCE FAILED: ' + str(error), file=sys.stderr, flush=True)
            sys.exit(1)
        if not getattr(locals().get("args"), "storage_routing_only", None) and not getattr(locals().get("args"), "receipt_routing_only", False) and not getattr(locals().get("args"), "okki_outbound_only", False) and STATE.exists() and not getattr(locals().get("args"), "restore_pre151", None) and not getattr(locals().get("args"), "office_lan_https", None) and not getattr(locals().get("args"), "migrate_only", None) and not getattr(locals().get("args"), "voucher_routing_only", False) and not getattr(locals().get("args"), "colorwork_routing_only", False) and not getattr(locals().get("args"), "shipping_video_routing_only", False):
            journal = marker("publish-current")
            journal.update(status="failed", error_type=type(error).__name__)
            atomic_json(STATE / "publish-current.json", journal)
        print("DEPLOY FAILED: " + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
