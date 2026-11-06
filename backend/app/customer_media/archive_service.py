"""Authenticated client ZIP exports, using bounded private disk rather than archive-sized RAM."""
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from sqlalchemy import select

from app.core.config import get_settings
from app.core.storage.cos import StorageError
from app.core.storage.files import reserve_processing_bytes
from app.customer_media import service
from app.customer_media.archive_paths import ArchiveNames, tag_folders
from app.customer_media.models import CustomerMediaAsset, CustomerMediaBatch, CustomerMediaDownload
from app.customer_media.storage import storage_for

logger = logging.getLogger("commission")
MAX_ARCHIVE_ENTRIES = 10000
CHUNK_BYTES = 1024 * 1024


class ArchiveTooLarge(service.CustomerMediaError):
    pass


@dataclass(frozen=True)
class ArchiveAsset:
    id: int
    file_name: str
    file_size: int
    sha256: str
    storage_provider: str
    object_key: str


@dataclass
class PreparedArchive:
    path: Path
    resources: ExitStack
    filename: str = "LeShine-materials.zip"

    def close(self):
        self.resources.close()


def _authorized_assets(db, customer_id, asset_ids):
    rows = list(db.scalars(select(CustomerMediaAsset).join(
        CustomerMediaBatch, CustomerMediaBatch.id == CustomerMediaAsset.batch_id,
    ).where(
        CustomerMediaAsset.id.in_(asset_ids), CustomerMediaAsset.deleted_at.is_(None),
        CustomerMediaBatch.customer_id == customer_id, CustomerMediaBatch.status == "published",
    ).order_by(CustomerMediaAsset.id)))
    if len(rows) != len(asset_ids):
        # No partial ZIP, and no disclosure of other customers' filenames or IDs.
        raise service.CustomerMediaNotFound("Some selected files are no longer available. Refresh the library and try again.")
    return rows


def _plan(db, account, asset_ids):
    rows = _authorized_assets(db, account.customer_id, asset_ids)
    tags = service.asset_tags_map(db, asset_ids)
    dimensions = [{"id": dim["dimension_id"], "name": dim["name"], "label": dim["label"]}
                  for dim in service.portal_used_tags(db, account)]
    names = ArchiveNames()
    plan = []
    entry_count = total_bytes = max_source_bytes = 0
    for row in rows:
        asset = ArchiveAsset(**{name: getattr(row, name) for name in ArchiveAsset.__dataclass_fields__})
        paths = []
        for folders in tag_folders(tags.get(asset.id, []), dimensions):
            entry_count += 1
            if entry_count > MAX_ARCHIVE_ENTRIES:
                raise ArchiveTooLarge("This selection creates too many ZIP entries. Please select fewer files.")
            path = names.file(folders, asset.file_name)
            paths.append(path)
            total_bytes += asset.file_size + len(path.encode("utf-8")) * 2 + 256
        if asset.storage_provider == "cos":
            max_source_bytes = max(max_source_bytes, asset.file_size)
        plan.append((asset, paths))
    reservation = total_bytes + max_source_bytes + 65536
    if reservation > get_settings().COS_CACHE_MAX_BYTES:
        raise ArchiveTooLarge("Selected files are too large for one ZIP. Please select fewer files and try again.")
    return plan, reservation


def _write_original(archive, path, asset, arcnames):
    for arcname in arcnames:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source, archive.open(arcname, "w", force_zip64=True) as target:
            for block in iter(lambda: source.read(CHUNK_BYTES), b""):
                size += len(block)
                if size > asset.file_size:
                    raise StorageError("Original exceeds recorded size")
                digest.update(block)
                target.write(block)
        if size != asset.file_size or digest.hexdigest() != asset.sha256:
            raise StorageError("Original does not match recorded checksum")


def prepare_portal_archive(db, account, asset_ids, token, ip):
    """All references are authorized before any I/O and rechecked before returning the ZIP."""
    asset_ids = sorted(set(asset_ids))
    account_id, customer_id = account.id, account.customer_id
    resources = ExitStack()
    try:
        plan, reserved_bytes = _plan(db, account, asset_ids)
        # Release the read transaction while downloading originals/building the archive.
        db.rollback()
        resources.enter_context(reserve_processing_bytes(reserved_bytes))
        cache = Path(get_settings().COS_CACHE_ROOT).resolve()
        directory = Path(resources.enter_context(TemporaryDirectory(prefix="customer-media-zip-", dir=cache)))
        output = directory / "materials.zip"
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            for asset, arcnames in plan:
                with storage_for(asset.storage_provider).materialize_original(asset, directory) as path:
                    _write_original(archive, path, asset, arcnames)
        # Changes to session, customer assignment or publication during preparation must fail closed.
        db.expire_all()
        current_account = service.portal_session(db, token)
        if current_account.id != account_id or current_account.customer_id != customer_id:
            raise service.CustomerMediaForbidden("Your session has changed. Please sign in again.")
        _authorized_assets(db, customer_id, asset_ids)
        db.add_all([CustomerMediaDownload(asset_id=asset_id, account_id=account_id, ip_address=ip[:45])
                    for asset_id in asset_ids])
        db.commit()
        return PreparedArchive(output, resources)
    except Exception as exc:
        logger.warning("[customer-media] ZIP export failed type=%s", type(exc).__name__)
        print(f"[customer-media] ZIP export failed type={type(exc).__name__}", flush=True)
        try:
            db.rollback()
        finally:
            resources.close()
        raise
