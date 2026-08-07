"""Stable customer product asset storage tests."""

import io

import pytest
from PIL import Image

from app.customer_image import file_service
from app.customer_image.models import CustomerImageProduct, CustomerImageProductAsset
from app.design_image.models import DesignImageLibraryAsset


def _png_bytes(color="red"):
    output = io.BytesIO()
    Image.new("RGB", (12, 8), color).save(output, format="PNG")
    return output.getvalue()


def _product(db):
    row = CustomerImageProduct(
        name="Wig", category="wig", fixed_prompt="fixed", output_prompt="output", created_by=1
    )
    db.add(row)
    db.commit()
    return row


def test_upload_replacement_retires_old_row_without_deleting_old_file(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)

    first = file_service.replace_product_asset_from_upload(db, product, "cover", 0, _png_bytes("red"), "image/png")
    old_path = file_service.resolve_private_path(first.storage_path)
    second = file_service.replace_product_asset_from_upload(db, product, "cover", 0, _png_bytes("blue"), "image/png")

    db.refresh(first)
    assert first.retired_at is not None
    assert old_path.read_bytes()
    with pytest.raises(FileNotFoundError):
        file_service.open_product_asset(db, product.id, first.id)
    assert file_service.open_product_asset(
        db, product.id, first.id, allow_retired=True
    ).read()
    assert second.retired_at is None
    assert product.config_version == 3


def test_library_copy_survives_source_deletion(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    normalized = file_service.normalize_upload(_png_bytes(), "image/png")
    source = file_service.save_private_image(normalized, owner_user_id=1, kind="library")
    library = DesignImageLibraryAsset(
        scope="public", owner_user_id=1, created_by=1, title="source",
        storage_path=source.relative_path, mime_type=source.mime_type, file_size=source.file_size,
        width=source.width, height=source.height, sha256=source.sha256,
    )
    db.add(library)
    db.commit()

    asset = file_service.replace_product_asset_from_library(db, product, "reference", 0, library.id, admin_id=1)
    file_service.delete_private_file(library.storage_path)
    library.deleted_at = file_service.utcnow()
    db.commit()

    assert file_service.open_product_asset(db, product.id, asset.id).read() == normalized.content


def test_database_failure_cleans_new_product_files(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db failed")))

    with pytest.raises(RuntimeError, match="db failed"):
        file_service.replace_product_asset_from_upload(db, product, "cover", 0, _png_bytes(), "image/png")

    assert list(tmp_path.rglob("*.png")) == []


def test_replacement_database_failure_restores_current_asset(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    current = file_service.replace_product_asset_from_upload(
        db, product, "cover", 0, _png_bytes("red"), "image/png"
    )
    current_path = file_service.resolve_private_path(current.storage_path)
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db failed")))

    with pytest.raises(RuntimeError, match="db failed"):
        file_service.replace_product_asset_from_upload(
            db, product, "cover", 0, _png_bytes("blue"), "image/png"
        )

    db.refresh(current)
    assert current.retired_at is None
    assert current_path.is_file()
    assert len(list(tmp_path.rglob("*.png"))) == 2


def test_product_asset_open_rejects_retired_and_cross_product_rows(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    first_product = _product(db)
    second_product = _product(db)
    asset = file_service.replace_product_asset_from_upload(
        db, first_product, "cover", 0, _png_bytes(), "image/png"
    )

    with pytest.raises(FileNotFoundError):
        file_service.open_product_asset(db, second_product.id, asset.id)

    asset.retired_at = file_service.utcnow()
    db.commit()
    with pytest.raises(FileNotFoundError):
        file_service.open_product_asset(db, first_product.id, asset.id)


def test_storage_wrapper_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    with pytest.raises(file_service.ImageStorageError):
        file_service.resolve_private_path("../outside.png")
