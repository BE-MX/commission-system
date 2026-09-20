"""Copy-only final snapshots; reuse exact readback receipts for unchanged bytes."""
import json
import os
from pathlib import Path
import sys


def snapshot(root, instance, attempt, reuse_asset_receipts=False):
    stage = root / '.deploy_state/cloud-storage-migration'
    os.chdir(root / 'backend')
    sys.path.insert(0, str(stage / 'lib'))
    sys.path.insert(0, str(root / 'backend'))
    from app.core.config import Settings
    from app.core.storage.cos import CosObjectStore, file_digest, validate_key
    from app.core.storage.migration import copy_manifest, write_manifest
    from app.core.storage.cutover import verified_rows
    from app.core.time import beijing_now
    settings = Settings(_env_file=root / 'backend/.env')
    cos = Settings(_env_file=stage / 'cos.env')
    if (cos.COS_BUCKET, cos.COS_KEY_PREFIX) != ('leshine-ark-1259007308', 'ark/production'):
        raise RuntimeError('Unexpected destination')
    fields = {'asset':'ASSET_STORAGE_ROOT', 'shipping-inspection':'SHIPPING_INSPECTION_STORAGE_ROOT',
              'customer-media':'CUSTOMER_MEDIA_STORAGE_ROOT', 'design-image':'DESIGN_IMAGE_STORAGE_ROOT',
              'domestic':'DOMESTIC_STORAGE_ROOT', 'training':'TRAINING_STORAGE_ROOT',
              'aftersales':'AFTERSALES_STORAGE_ROOT', 'ai-chat':'AI_CHAT_STORAGE_ROOT',
              'knowledge':'KNOWLEDGE_STORAGE_ROOT'}
    roots = {domain: Path(getattr(settings, field)).resolve() for domain, field in fields.items()}
    roots.update({domain: root / 'uploads' / domain for domain in ['avatars','card','expo','festival','tag_images']})
    roots.update({'design-attachments':root/'backend/uploads/design', 'insight':root/'backend/uploads/insight',
                  'receipt-proofs':root/'backend/data/receipt-proofs', 'pm':root/'backend/data/pm'})
    approved_empty = json.loads((stage / 'empty-source-approvals.json').read_text())[instance]
    previous_assets = {}
    if reuse_asset_receipts:
        baseline = json.loads((stage / 'office-asset-initial.json').read_text(encoding='utf-8'))
        previous_assets = {row['relative_path']: row for row in baseline['files']}
    evidence = []
    for domain, folder in roots.items():
        if not folder.is_dir():
            baseline = stage / f'{instance}-{domain}-initial.json'
            if domain not in approved_empty or (baseline.exists() and json.loads(baseline.read_text())['files']):
                raise RuntimeError('Missing source root requires explicit empty-source audit')
        missing = []
        if domain == 'asset' and instance == 'office':
            from app.core.database import engine
            from sqlalchemy import text
            with engine.connect() as db:
                db.exec_driver_sql('SET TRANSACTION READ ONLY')
                keys = set(db.execute(text('SELECT storage_path FROM ark_assets')).scalars())
                keys.update(db.execute(text('SELECT thumbnail_path FROM ark_assets WHERE thumbnail_path IS NOT NULL')).scalars())
                keys.update(db.execute(text('SELECT storage_path FROM ark_asset_versions')).scalars())
                db.rollback()
            keys.discard(None)
            keys.discard('')
        else:
            keys = set()
            def fail(error):
                raise error
            directories = os.walk(folder, onerror=fail, followlinks=False) if folder.exists() else []
            for directory, dirs, files in directories:
                parent = Path(directory)
                if domain == 'expo' and parent == folder:
                    dirs[:] = [name for name in dirs if name not in {'pending','beautify_previews'}]
                for name in dirs + files:
                    path = parent / name
                    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                        raise RuntimeError('Snapshot source contains a link')
                keys.update((parent / name).relative_to(folder).as_posix() for name in files)
        if domain == 'expo' and instance == 'office':
            keys -= {'hair_colors/swatch_52babe3828.png','hair_colors/swatch_e89e220146.png'}
        rows = []
        for key in sorted(keys):
            validate_key(key)
            path = folder / key
            if not path.is_file():
                missing.append(key)
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
                raise RuntimeError('Snapshot source escaped root')
            before = path.stat()
            old = previous_assets.get(key) if domain == 'asset' and instance == 'office' else None
            if old and (old['size'], old['mtime_ns']) == (before.st_size, before.st_mtime_ns):
                # Only with explicit operator approval to reuse prior asset readbacks.
                row = old
            else:
                size, sha = file_digest(path)
                row = dict(relative_path=key, size=size, sha256=sha, mtime_ns=before.st_mtime_ns)
            after = path.stat()
            if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                raise RuntimeError('Source changed while snapshotting')
            rows.append(row)
        if missing:
            accepted = json.loads((stage/'office-asset-missing.json').read_text()) if domain == 'asset' and instance == 'office' else []
            if set(missing) != set(accepted):
                raise RuntimeError('Unapproved missing originals')
        manifest = dict(version=1, domain=domain, source_instance=instance, root=str(folder),
                        created_at=beijing_now().isoformat(), files=rows)
        manifest_path = stage / f'snapshot-{attempt}-{instance}-{domain}.json'
        if manifest_path.exists():
            saved = json.loads(manifest_path.read_text(encoding='utf-8'))
            if saved['files'] != rows or saved['root'] != str(folder):
                raise RuntimeError('Snapshot identity changed; use a fresh attempt')
            manifest = saved
        else:
            write_manifest(manifest, manifest_path)
        store = CosObjectStore(domain, settings=cos)
        valid = {}
        wanted = {row['relative_path']:row for row in rows}
        journals = list(stage.glob(f'{instance}-{domain}-*.jsonl'))
        journals += list(stage.glob(f'snapshot-*-{instance}-{domain}.jsonl'))
        for journal in journals:
            for line in journal.read_text(encoding='utf-8').splitlines():
                receipt = json.loads(line)
                key = receipt.get('relative_path')
                row = wanted.get(key)
                if row and receipt.get('verified_at') and (
                    receipt.get('domain'), receipt.get('source_instance'), receipt.get('target_bucket'),
                    receipt.get('target_key'), receipt.get('size'), receipt.get('sha256')) == (
                        domain, instance, store.bucket, store.key(key), row['size'], row['sha256']):
                    valid[key] = receipt
        journal_path = manifest_path.with_suffix('.jsonl')
        pending = [row for row in rows if row['relative_path'] not in valid]
        if pending:
            copy_manifest({**manifest, 'files':pending}, store, journal_path, cache_root=stage/'cache')
            for line in journal_path.read_text(encoding='utf-8').splitlines():
                receipt = json.loads(line)
                valid[receipt['relative_path']] = receipt
        journal = '\n'.join(json.dumps(valid[row['relative_path']]) for row in rows)
        verified_rows(manifest, journal, bucket=store.bucket, prefix=cos.COS_KEY_PREFIX)
        evidence.append({'manifest':manifest, 'journal':journal})
        print(json.dumps({'domain':domain, 'files':len(rows), 'new_readbacks':len(pending), 'missing':len(missing)}),flush=True)
    destination = stage / f'snapshot-{attempt}-{instance}-evidence.json'
    if destination.exists():
        if json.loads(destination.read_text()) != evidence:
            raise RuntimeError('Do not overwrite snapshot evidence')
    else:
        with destination.open('x', encoding='utf-8') as stream:
            json.dump(evidence, stream)
    print(json.dumps({'evidence':destination.name,'domains':len(evidence)}),flush=True)


if __name__ == '__main__':
    arguments = sys.argv[1:]
    reuse_asset_receipts = arguments[-1:] == ['--reuse-asset-receipts']
    instance, attempt = arguments[:-1] if reuse_asset_receipts else arguments
    if instance not in {'office','beijing'} or not __import__('re').fullmatch('[a-z0-9-]{1,64}', attempt):
        raise ValueError('Invalid snapshot identity')
    snapshot(Path('D:/commission-system' if instance == 'office' else '/home/ubuntu/commission-system'), instance, attempt, reuse_asset_receipts)
