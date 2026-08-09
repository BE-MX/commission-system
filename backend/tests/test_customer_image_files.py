"""Stable customer product asset storage tests."""

import io

import pytest
from PIL import Image
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.customer_image import file_service, service
from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageProduct,
    CustomerImageProductAsset,
)
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


def _invite(db, suffix="aaaaaa"):
    row = CustomerImageInvite(
        customer_id=f"customer-{suffix}",
        customer_name_snapshot="Customer",
        created_by=1,
        okki_salesperson_id_snapshot="1007",
        token_hash=suffix[0] * 64,
        token_suffix=suffix,
        starts_at=file_service.utcnow(),
        expires_at=file_service.utcnow().replace(year=2099),
        quota_total=2,
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
        file_service.open_product_asset_content(db, product.id, first.id)
    assert second.retired_at is None
    assert product.config_version == 3


def test_cover_is_a_single_zero_position_slot(db):
    product = _product(db)
    with pytest.raises(ValueError, match="position must be zero"):
        file_service.replace_product_asset_from_upload(
            db, product, "cover", 1, _png_bytes(), "image/png"
        )


def test_reference_retire_and_reorder_keep_history_and_stable_positions(db):
    from app.customer_image.service import retire_product_reference, reorder_product_references

    product = CustomerImageProduct(
        name="References", category="box", fixed_prompt="x", output_prompt="y", created_by=1,
    )
    db.add(product)
    db.flush()
    references = [
        CustomerImageProductAsset(
            product_id=product.id, role="reference", position=index,
            storage_path=f"reference-{index}.png", mime_type="image/png", file_size=1,
            width=1, height=1, sha256=str(index + 1) * 64,
        )
        for index in range(3)
    ]
    cover = CustomerImageProductAsset(
        product_id=product.id, role="cover", position=0, storage_path="cover.png",
        mime_type="image/png", file_size=1, width=1, height=1, sha256="f" * 64,
    )
    db.add_all([*references, cover])
    db.commit()

    reordered = reorder_product_references(
        db, product.id, [references[2].id, references[0].id, references[1].id]
    )
    assert [(row.id, row.position) for row in reordered] == [
        (references[2].id, 0), (references[0].id, 1), (references[1].id, 2),
    ]
    version_after_reorder = db.get(CustomerImageProduct, product.id).config_version

    retire_product_reference(db, product.id, references[0].id)
    current = service.list_current_product_assets(db, product.id)
    current_references = [row for row in current if row.role == "reference"]
    assert [(row.id, row.position) for row in current_references] == [
        (references[2].id, 0), (references[1].id, 1),
    ]
    assert db.get(CustomerImageProductAsset, references[0].id).retired_at is not None
    assert db.get(CustomerImageProductAsset, references[0].id).storage_path == "reference-0.png"
    assert db.get(CustomerImageProduct, product.id).config_version == version_after_reorder + 1


def test_reference_reorder_rejects_missing_duplicate_cover_and_cross_product_ids(db):
    from app.customer_image.service import CustomerImageConflictError, reorder_product_references

    first = CustomerImageProduct(name="First", category="box", fixed_prompt="x", output_prompt="y", created_by=1)
    second = CustomerImageProduct(name="Second", category="box", fixed_prompt="x", output_prompt="y", created_by=1)
    db.add_all([first, second])
    db.flush()
    own = CustomerImageProductAsset(product_id=first.id, role="reference", position=0, storage_path="own.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="a" * 64)
    cover = CustomerImageProductAsset(product_id=first.id, role="cover", position=0, storage_path="cover.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="b" * 64)
    other = CustomerImageProductAsset(product_id=second.id, role="reference", position=0, storage_path="other.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="c" * 64)
    db.add_all([own, cover, other])
    db.commit()

    for invalid in ([], [own.id, own.id], [cover.id], [other.id]):
        with pytest.raises(CustomerImageConflictError):
            reorder_product_references(db, first.id, invalid)


def test_published_product_keeps_at_least_one_current_reference(db):
    from app.customer_image.service import CustomerImageConflictError, retire_product_reference

    product = CustomerImageProduct(
        name="Published", category="box", fixed_prompt="x", output_prompt="y",
        created_by=1, is_published=True,
    )
    db.add(product)
    db.flush()
    reference = CustomerImageProductAsset(
        product_id=product.id, role="reference", position=0,
        storage_path="reference.png", mime_type="image/png", file_size=1,
        width=1, height=1, sha256="a" * 64,
    )
    db.add(reference)
    db.commit()

    with pytest.raises(CustomerImageConflictError):
        retire_product_reference(db, product.id, reference.id)
    db.refresh(reference)
    assert reference.retired_at is None


def test_product_lock_statement_uses_mysql_for_update():
    statement = file_service._product_for_update_statement(7)

    compiled = str(statement.compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compiled
    assert "ark_customer_image_products.id = %s" in compiled


def test_last_reference_position_statement_is_a_mysql_locking_read():
    statement = file_service._last_reference_position_for_update_statement(7)

    compiled = str(statement.compile(dialect=mysql.dialect()))
    assert "ark_customer_image_product_assets.position" in compiled
    assert "ark_customer_image_product_assets.product_id = %s" in compiled
    assert "ark_customer_image_product_assets.`role` = %s" in compiled
    assert "ark_customer_image_product_assets.retired_at IS NULL" in compiled
    assert "ORDER BY ark_customer_image_product_assets.position DESC" in compiled
    assert "LIMIT %s FOR UPDATE" in compiled


def test_stale_sessions_replace_one_slot_without_lost_version(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    Session = sessionmaker(bind=db.get_bind())
    first_db = Session()
    second_db = Session()
    try:
        first_product = first_db.get(CustomerImageProduct, product.id)
        second_product = second_db.get(CustomerImageProduct, product.id)
        assert first_product.config_version == second_product.config_version == 1

        file_service.replace_product_asset_from_upload(
            first_db, first_product, "cover", 0, _png_bytes("red"), "image/png"
        )
        file_service.replace_product_asset_from_upload(
            second_db, second_product, "cover", 0, _png_bytes("blue"), "image/png"
        )
    finally:
        first_db.close()
        second_db.close()
        db.expire_all()

    assert db.get(CustomerImageProduct, product.id).config_version == 3
    current = db.query(CustomerImageProductAsset).filter(
        CustomerImageProductAsset.product_id == product.id,
        CustomerImageProductAsset.role == "cover",
        CustomerImageProductAsset.position == 0,
        CustomerImageProductAsset.retired_at.is_(None),
    ).all()
    assert len(current) == 1


def test_stale_sessions_append_two_references_without_retiring_either(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    Session = sessionmaker(bind=db.get_bind())
    first_db = Session()
    second_db = Session()
    try:
        first_product = first_db.get(CustomerImageProduct, product.id)
        second_product = second_db.get(CustomerImageProduct, product.id)
        first = file_service.append_product_reference_from_upload(
            first_db, first_product, _png_bytes("red"), "image/png"
        )
        second = file_service.append_product_reference_from_upload(
            second_db, second_product, _png_bytes("blue"), "image/png"
        )
    finally:
        first_db.close()
        second_db.close()
        db.expire_all()

    current = db.query(CustomerImageProductAsset).filter(
        CustomerImageProductAsset.product_id == product.id,
        CustomerImageProductAsset.role == "reference",
        CustomerImageProductAsset.retired_at.is_(None),
    ).order_by(CustomerImageProductAsset.position).all()
    assert [row.id for row in current] == [first.id, second.id]
    assert [row.position for row in current] == [0, 1]
    assert len({row.position for row in current}) == 2
    assert db.get(CustomerImageProduct, product.id).config_version == 3


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

    assert file_service.open_product_asset_content(db, product.id, asset.id).read() == normalized.content


def test_other_users_private_library_is_not_listed_and_cannot_be_copied(
    db, tmp_path, monkeypatch
):
    from app.design_image import library_service

    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    normalized = file_service.normalize_upload(_png_bytes(), "image/png")
    stored = file_service.save_private_image(normalized, owner_user_id=8, kind="library")
    other_private = DesignImageLibraryAsset(
        scope="private", owner_user_id=8, created_by=8, title="Other private",
        storage_path=stored.relative_path, mime_type=stored.mime_type, file_size=stored.file_size,
        width=stored.width, height=stored.height, sha256=stored.sha256,
    )
    db.add(other_private)
    db.commit()

    assert library_service.list_library_assets(db, 7, "private") == []
    with pytest.raises(FileNotFoundError, match="library asset not found"):
        file_service.replace_product_asset_from_library(
            db, product, "cover", 0, other_private.id, admin_id=7
        )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.customer_image.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/customer-image")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["customer_image:admin"]
    }
    response = TestClient(app).post(
        f"/api/customer-image/products/{product.id}/assets/library",
        json={"source_asset_id": other_private.id, "role": "cover", "position": 0},
    )
    assert response.status_code == 404


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
        file_service.open_product_asset_content(db, second_product.id, asset.id)

    asset.retired_at = file_service.utcnow()
    db.commit()
    with pytest.raises(FileNotFoundError):
        file_service.open_product_asset_content(db, first_product.id, asset.id)


def test_frozen_generation_reads_only_its_listed_retired_reference(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    invite = _invite(db)
    listed = file_service.replace_product_asset_from_upload(
        db, product, "reference", 0, _png_bytes("red"), "image/png"
    )
    unlisted = file_service.replace_product_asset_from_upload(
        db, product, "reference", 1, _png_bytes("green"), "image/png"
    )
    listed.retired_at = file_service.utcnow()
    unlisted.retired_at = file_service.utcnow()
    logo = CustomerImageAsset(
        invite_id=invite.id, asset_type="logo", storage_path="unused.png",
        mime_type="image/png", file_size=1, width=1, height=1, sha256="f" * 64,
    )
    db.add(logo)
    db.flush()
    generation = CustomerImageGeneration(
        invite_id=invite.id, product_id=product.id, logo_asset_id=logo.id,
        request_id="request-1", product_name_snapshot=product.name,
        config_version_snapshot=product.config_version, option_snapshot={},
        prompt_snapshot="prompt", reference_asset_ids=[listed.id],
        preset_name="customer_image_generation",
    )
    db.add(generation)
    db.commit()

    assert file_service.open_generation_reference_content(
        db, invite.id, generation.id, listed.id
    ).read()
    with pytest.raises(FileNotFoundError):
        file_service.open_generation_reference_content(
            db, invite.id, generation.id, unlisted.id
        )
    other_invite = _invite(db, "bbbbbb")
    with pytest.raises(FileNotFoundError):
        file_service.open_generation_reference_content(
            db, other_invite.id, generation.id, listed.id
        )


def test_frozen_generation_rejects_listed_asset_from_another_product(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    other_product = _product(db)
    invite = _invite(db)
    cross_product_asset = file_service.replace_product_asset_from_upload(
        db, other_product, "reference", 0, _png_bytes(), "image/png"
    )
    logo = CustomerImageAsset(
        invite_id=invite.id, asset_type="logo", storage_path="unused.png",
        mime_type="image/png", file_size=1, width=1, height=1, sha256="f" * 64,
    )
    db.add(logo)
    db.flush()
    generation = CustomerImageGeneration(
        invite_id=invite.id, product_id=product.id, logo_asset_id=logo.id,
        request_id="request-cross-product", product_name_snapshot=product.name,
        config_version_snapshot=product.config_version, option_snapshot={},
        prompt_snapshot="prompt", reference_asset_ids=[cross_product_asset.id],
        preset_name="customer_image_generation",
    )
    db.add(generation)
    db.commit()

    with pytest.raises(FileNotFoundError):
        file_service.open_generation_reference_content(
            db, invite.id, generation.id, cross_product_asset.id
        )


def test_invite_assets_use_private_kinds_and_enforce_invite_scope(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    invite = _invite(db)
    other_invite = _invite(db, "bbbbbb")
    normalized = file_service.normalize_upload(_png_bytes(), "image/png")

    asset = file_service.save_invite_image(db, invite.id, normalized, "logo")

    assert asset.storage_path.startswith(f"{invite.id}/customer-logo/")
    assert file_service.open_invite_asset_content(db, invite.id, asset.id).read()
    assert file_service.open_invite_asset_content(
        db, invite.id, asset.id, thumbnail=True
    ).read()
    with pytest.raises(FileNotFoundError):
        file_service.open_invite_asset_content(db, other_invite.id, asset.id)
    asset.deleted_at = file_service.utcnow()
    db.commit()
    with pytest.raises(FileNotFoundError):
        file_service.open_invite_asset_content(db, invite.id, asset.id)


def test_invite_asset_database_failure_cleans_files(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    invite = _invite(db)
    normalized = file_service.normalize_upload(_png_bytes(), "image/png")
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db failed")))

    with pytest.raises(RuntimeError, match="db failed"):
        file_service.save_invite_image(db, invite.id, normalized, "generated")

    assert list(tmp_path.rglob("*.png")) == []


def test_generated_invite_asset_uses_output_partition_and_is_readable(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    invite = _invite(db)
    normalized = file_service.normalize_upload(_png_bytes("blue"), "image/png")

    asset = file_service.save_invite_image(db, invite.id, normalized, "generated")

    assert asset.storage_path.startswith(f"{invite.id}/customer-output/")
    assert file_service.open_invite_asset_content(
        db, invite.id, asset.id
    ).read() == normalized.content


def test_storage_wrapper_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    with pytest.raises(file_service.ImageStorageError):
        file_service.resolve_private_path("../outside.png")


@pytest.mark.parametrize(
    "error",
    [OSError("disk unavailable"), file_service.ImageStorageError("storage unavailable")],
)
def test_content_open_preserves_storage_failures_for_503(monkeypatch, error):
    monkeypatch.setattr(
        file_service,
        "resolve_private_path",
        lambda _path: (_ for _ in ()).throw(error),
    )

    with pytest.raises(type(error), match="unavailable"):
        file_service._open_relative_content("asset.png", "asset not found")


def test_library_copy_preserves_directory_error_for_503(db, monkeypatch):
    product = _product(db)
    source = DesignImageLibraryAsset(
        scope="public", owner_user_id=1, created_by=1, title="source",
        storage_path="directory", mime_type="image/png", file_size=1,
        width=1, height=1, sha256="a" * 64,
    )
    db.add(source)
    db.commit()
    monkeypatch.setattr(
        file_service,
        "resolve_private_path",
        lambda _path: (_ for _ in ()).throw(IsADirectoryError("source is a directory")),
    )

    with pytest.raises(IsADirectoryError, match="directory"):
        file_service.replace_product_asset_from_library(
            db, product, "cover", 0, source.id, admin_id=1
        )


def test_delete_product_rejects_invite_reference_and_keeps_files(db, tmp_path, monkeypatch):
    from app.customer_image.service import CustomerImageConflictError, delete_product
    from app.customer_image.models import CustomerImageInviteProduct

    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    asset = file_service.replace_product_asset_from_upload(db, product, "cover", 0, _png_bytes(), "image/png")
    invite = _invite(db)
    db.add(CustomerImageInviteProduct(invite_id=invite.id, product_id=product.id))
    db.commit()

    with pytest.raises(CustomerImageConflictError):
        delete_product(db, product.id)

    assert db.get(CustomerImageProduct, product.id) is not None
    assert file_service.resolve_private_path(asset.storage_path).is_file()


def test_delete_product_maps_reference_race_and_keeps_files(db, tmp_path, monkeypatch):
    from app.customer_image.service import CustomerImageConflictError, delete_product

    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    asset = file_service.replace_product_asset_from_upload(
        db, product, "cover", 0, _png_bytes(), "image/png"
    )
    image_path = file_service.resolve_private_path(asset.storage_path)
    real_rollback = db.rollback
    rolled_back = False

    def fail_commit():
        raise IntegrityError("DELETE product", {}, Exception("foreign key race"))

    def track_rollback():
        nonlocal rolled_back
        rolled_back = True
        real_rollback()

    monkeypatch.setattr(db, "commit", fail_commit)
    monkeypatch.setattr(db, "rollback", track_rollback)

    with pytest.raises(CustomerImageConflictError, match="in use"):
        delete_product(db, product.id)

    assert rolled_back is True
    assert db.get(CustomerImageProduct, product.id) is not None
    assert image_path.is_file()


def test_delete_unreferenced_product_cleans_files_only_after_commit(db, tmp_path, monkeypatch):
    from app.customer_image.service import delete_product
    from app.design_image.service import _thumbnail_path

    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    product = _product(db)
    asset = file_service.replace_product_asset_from_upload(db, product, "cover", 0, _png_bytes(), "image/png")
    image_path = file_service.resolve_private_path(asset.storage_path)
    thumb_path = file_service.resolve_private_path(_thumbnail_path(asset.storage_path))
    assert image_path.is_file() and thumb_path.is_file()

    delete_product(db, product.id)

    assert db.get(CustomerImageProduct, product.id) is None
    assert not image_path.exists()
    assert not thumb_path.exists()
