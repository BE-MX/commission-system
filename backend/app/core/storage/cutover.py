"""Validated migration receipts for a quiesced deployment cutover.

This module never commits. The deployment caller owns the transaction and must
keep every file-writing instance frozen until its configuration is switched.
"""
import json
import mimetypes
import re

from app.core.storage.cos import StorageError, validate_key
from app.core.storage.models import StorageTransfer
from app.core.storage.transfers import transfer_id


def verified_rows(manifest, journal, *, bucket, prefix):
    if manifest.get('version') != 1:
        raise ValueError('Unsupported manifest')
    domain = validate_key(manifest['domain'])
    expected = {validate_key(row['relative_path']): row for row in manifest['files']}
    if len(expected) != len(manifest['files']):
        raise ValueError('Duplicate manifest keys')
    for row in expected.values():
        if type(row.get('size')) is not int or row['size'] < 0 or not re.fullmatch(r'[0-9a-f]{64}', row.get('sha256', '')):
            raise ValueError('Invalid verified file identity')
    verified = {}
    for line in journal.splitlines():
        receipt = json.loads(line)
        key = validate_key(receipt['relative_path'])
        if key not in expected:
            raise StorageError('Receipt not present in final manifest')
        row = expected[key]
        identity = (receipt.get('domain'), receipt.get('source_instance'), receipt.get('target_bucket'),
                    receipt.get('target_key'), receipt.get('size'), receipt.get('sha256'))
        wanted = (domain, manifest['source_instance'], bucket, prefix + '/' + domain + '/' + key,
                  row['size'], row['sha256'])
        if identity != wanted or not receipt.get('verified_at'):
            raise StorageError('Only exact full-readback receipts can authorize cutover')
        verified[key] = row
    if verified.keys() != expected.keys():
        raise StorageError('Incomplete verified migration; cutover refused')
    return list(verified.values())


def verified_union(inputs, *, bucket, prefix):
    """Combine instance receipts only when the shared target bytes agree."""
    domains = {}
    for manifest, journal in inputs:
        rows = verified_rows(manifest, journal, bucket=bucket, prefix=prefix)
        target = domains.setdefault(manifest['domain'], {})
        for row in rows:
            previous = target.get(row['relative_path'])
            if previous and (previous['size'], previous['sha256']) != (row['size'], row['sha256']):
                raise StorageError('Instances disagree on a shared target; resolve before cutover')
            target[row['relative_path']] = row
    return {domain: list(rows.values()) for domain, rows in domains.items()}


def check_reference_coverage(db, domain, rows):
    """Read-only precondition: copying existing files cannot hide missing originals.

    Repeat inside the frozen cutover transaction, since an earlier report cannot
    prove that no new references were created during the bulk copy.
    """
    by_key = {row['relative_path']: row for row in rows}
    references = []
    if domain == 'asset':
        from app.asset.models import Asset, AssetVersion
        for key, thumbnail, size in db.query(Asset.storage_path, Asset.thumbnail_path, Asset.file_size):
            references.append((key, size))
            if thumbnail:
                references.append((thumbnail, None))
        references.extend(db.query(AssetVersion.storage_path, AssetVersion.file_size).all())
    elif domain == 'shipping-inspection':
        from app.shipping_inspection.models import ShippingInspectionPhoto
        references.extend((key, None) for key, in db.query(ShippingInspectionPhoto.file_path))
    else:
        raise ValueError('Unsupported durable reference domain')
    missing = 0
    mismatched = 0
    for key, size in references:
        validate_key(key)
        row = by_key.get(key)
        if row is None:
            missing += 1
        elif size and size != row['size']:
            mismatched += 1
    if missing or mismatched:
        # No customer filenames or keys in service logs.
        raise StorageError(f'Reference coverage failed: missing={missing}, size_mismatch={mismatched}')
    return len(references)


def register_ready(db, domain, rows, source_instance):
    if domain not in {'asset', 'shipping-inspection'}:
        raise ValueError('Domain does not use durable local transfers')
    check_reference_coverage(db, domain, rows)
    for row in rows:
        key = validate_key(row['relative_path'])
        existing = db.get(StorageTransfer, transfer_id(domain, key))
        if existing:
            if (existing.status, existing.file_size, existing.sha256, existing.source_instance) != (
                    'ready', row['size'], row['sha256'], source_instance):
                raise StorageError('Existing transfer conflicts with migration; do not overwrite')
            continue
        db.add(StorageTransfer(id=transfer_id(domain, key), domain=domain, object_key=key,
                              source_instance=source_instance, file_size=row['size'], sha256=row['sha256'],
                              content_type=mimetypes.guess_type(key)[0] or 'application/octet-stream', status='ready'))
    db.flush()


def migrate_customer_references(db, rows):
    from app.customer_media.models import CustomerMediaAsset
    by_key = {row['relative_path']: row for row in rows}
    records = db.query(CustomerMediaAsset).filter(CustomerMediaAsset.storage_provider == 'local',
                                                 CustomerMediaAsset.deleted_at.is_(None)).with_for_update().all()
    for asset in records:
        row = by_key.get(asset.object_key)
        if row is None or (asset.file_size, asset.sha256) != (row['size'], row['sha256']):
            raise StorageError('Customer asset reference does not match verified bytes')
        asset.storage_provider = 'cos'
    db.flush()
    return len(records)
