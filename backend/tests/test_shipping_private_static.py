"""Public upload mounts cannot bypass inspection media authorization."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.bootstrap import static_files


@pytest.mark.parametrize("private_folder", ["shipping-inspection", "custom-inspection", "assets/private-inspection"])
def test_public_static_routes_block_inspection_media(tmp_path, monkeypatch, private_folder):
    uploads = tmp_path / "uploads"
    private = uploads / private_folder
    private.mkdir(parents=True)
    (private / "photo.jpg").write_bytes(b"private-photo")
    (private / "video.mp4").write_bytes(b"private-video")
    legacy = uploads / "shipping-inspection"
    legacy.mkdir(exist_ok=True)
    (legacy / "old.jpg").write_bytes(b"private-legacy")
    assets = uploads / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "public.jpg").write_bytes(b"public-asset")
    (uploads / "avatar.jpg").write_bytes(b"public-avatar")
    monkeypatch.setattr(static_files, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(static_files, "ASSET_STORAGE_ROOT", assets)
    monkeypatch.setattr("app.shipping_inspection.file_service.storage_root", lambda: private)
    app = FastAPI()
    static_files.mount_uploads(app)
    with TestClient(app) as client:
        for filename in ("photo.jpg", "video.mp4"):
            path = f"/uploads/{private_folder}/{filename}"
            assert client.get(path).status_code == 404
            assert client.head(path).status_code == 404
            assert client.get(path, headers={"Authorization": "Bearer irrelevant"}).status_code == 404
        assert client.get('/uploads/shipping-inspection/old.jpg').status_code == 404
        assert client.get('/uploads/avatar.jpg').content == b"public-avatar"
        assert client.get('/uploads/assets/public.jpg').content == b"public-asset"
