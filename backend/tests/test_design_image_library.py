"""提示词模板库与参考图库（公/私库）服务层测试。"""

from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError as PydanticValidationError

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.design_image import library_service, service
from app.design_image.models import (
    DesignImageAsset,
    DesignImageLibraryAsset,
    DesignImagePromptTemplate,
    DesignImageSession,
)
from app.design_image.schemas import PromptTemplateUpsert


def _user(db, username: str) -> ArkUser:
    row = ArkUser(
        username=username,
        password_hash="test-hash",
        real_name=username,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _session(db, owner_id: int) -> DesignImageSession:
    row = DesignImageSession(owner_user_id=owner_id, title="对话", status="active")
    db.add(row)
    db.flush()
    return row


def _image_bytes(fmt: str = "PNG", size=(64, 64)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (25, 80, 140)).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def users(db):
    owner = _user(db, "owner")
    other = _user(db, "other")
    db.commit()
    return owner, other


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path))
    return tmp_path


# ── 提示词模板 ─────────────────────────────────


def test_seed_prompt_templates_is_idempotent_and_listed_in_order(db):
    first = library_service.seed_prompt_templates(db)
    assert first["created"] == first["total"]
    assert db.query(DesignImagePromptTemplate).count() == first["total"]

    second = library_service.seed_prompt_templates(db)
    assert second["created"] == 0
    assert second["skipped"] == second["total"]

    rows = library_service.list_prompt_templates(db)
    assert [row.sort for row in rows] == sorted(row.sort for row in rows)
    assert all(row.is_active for row in rows)
    assert all(row.options for row in rows)


def test_prompt_template_crud_and_soft_delete(db):
    payload = PromptTemplateUpsert(
        category="scene",
        name="门店场景",
        content="在{scene}里拍一张",
        options=[{"key": "scene", "label": "场景", "choices": ["沙龙"]}],
        sort=5,
    )
    row = library_service.create_prompt_template(db, payload)
    assert row.id is not None

    updated = library_service.update_prompt_template(
        db, row.id, PromptTemplateUpsert(
            category="scene", name="门店场景 v2", content="在{scene}里拍两张",
            options=[{"key": "scene", "label": "场景", "choices": ["沙龙"]}], sort=1,
        )
    )
    assert updated.name == "门店场景 v2"

    library_service.delete_prompt_template(db, row.id)
    assert db.get(DesignImagePromptTemplate, row.id).is_active is False
    assert all(item.id != row.id for item in library_service.list_prompt_templates(db))
    # 管理视角：include_inactive 能看到已停用模板并可据此恢复
    inactive_ids = {item.id for item in library_service.list_prompt_templates(db, include_inactive=True)}
    assert row.id in inactive_ids
    with pytest.raises(service.DesignImageNotFoundError):
        library_service.delete_prompt_template(db, 999_999)


def test_prompt_template_schema_requires_option_for_every_placeholder():
    with pytest.raises(PydanticValidationError):
        PromptTemplateUpsert(category="x", name="x", content="缺少{missing}的定义")
    with pytest.raises(PydanticValidationError):
        PromptTemplateUpsert(
            category="x", name="x", content="ok",
            options=[{"key": "dup", "label": "a", "choices": ["1"]},
                     {"key": "dup", "label": "b", "choices": ["2"]}],
        )


# ── 参考图库 ─────────────────────────────────


def test_library_upload_visibility_and_clone(db, storage, users):
    owner, other = users
    session = _session(db, owner.id)
    db.commit()

    private_row = library_service.create_library_asset(
        db, owner.id, _image_bytes(), "image/png", "private", "我的私图"
    )
    public_row = library_service.create_library_asset(
        db, owner.id, _image_bytes(), "image/png", "public", "全员公图"
    )

    mine = library_service.list_library_assets(db, owner.id, "private")
    theirs = library_service.list_library_assets(db, other.id, "private")
    everyone = library_service.list_library_assets(db, other.id, "public")
    assert [row.id for row in mine] == [private_row.id]
    assert theirs == []
    assert [row.id for row in everyone] == [public_row.id]
    with pytest.raises(service.DesignImageValidationError):
        library_service.list_library_assets(db, owner.id, "internal")

    # 复制进会话成为草稿资产：新存储路径、源行不动、归属当前会话
    clone = library_service.clone_library_asset_to_session(
        db, owner.id, public_row.id, session.id
    )
    assert clone.session_id == session.id
    assert clone.status == "draft"
    assert clone.asset_type == "upload"
    assert clone.storage_path != public_row.storage_path
    assert clone.expires_at is not None
    assert db.get(DesignImageLibraryAsset, public_row.id).deleted_at is None
    assert (storage / clone.storage_path).is_file()
    assert (storage / public_row.storage_path).is_file()

    # 他人私库：复制与读内容都与随机不存在 ID 同为 404
    with pytest.raises(service.DesignImageNotFoundError):
        library_service.clone_library_asset_to_session(db, other.id, private_row.id, session.id)
    with pytest.raises(service.DesignImageNotFoundError):
        library_service.open_library_asset_content(db, other.id, private_row.id)


def test_library_delete_rules(db, storage, users):
    owner, other = users
    private_row = library_service.create_library_asset(
        db, owner.id, _image_bytes(), "image/png", "private", "私图"
    )
    public_row = library_service.create_library_asset(
        db, owner.id, _image_bytes(), "image/png", "public", "公图"
    )

    # 公库：非管理员删除被拒，管理员删除成功
    with pytest.raises(service.DesignImageValidationError):
        library_service.delete_library_asset(db, owner.id, public_row.id, is_admin=False)
    library_service.delete_library_asset(db, other.id, public_row.id, is_admin=True)
    assert db.get(DesignImageLibraryAsset, public_row.id).deleted_at is not None
    assert all(row.id != public_row.id for row in library_service.list_library_assets(db, owner.id, "public"))

    # 私库：他人删除 404，本人删除成功且文件被清理
    with pytest.raises(service.DesignImageNotFoundError):
        library_service.delete_library_asset(db, other.id, private_row.id, is_admin=False)
    library_service.delete_library_asset(db, owner.id, private_row.id, is_admin=False)
    assert db.get(DesignImageLibraryAsset, private_row.id).deleted_at is not None
    assert not (storage / private_row.storage_path).exists()


def test_library_content_streams_with_suffix_and_thumbnail(db, storage, users):
    owner, _ = users
    row = library_service.create_library_asset(
        db, owner.id, _image_bytes(), "image/png", "public", "公图"
    )

    original = library_service.open_library_asset_content(db, owner.id, row.id)
    assert original.mime_type == "image/png"
    assert original.suffix == ".png"
    assert original.stream.read(8) == b"\x89PNG\r\n\x1a\n"
    original.stream.close()

    thumbnail = library_service.open_library_asset_content(db, owner.id, row.id, thumbnail=True)
    assert thumbnail.stream.read(8) == b"\x89PNG\r\n\x1a\n"
    thumbnail.stream.close()


def test_library_rejects_non_image_upload(db, storage, users):
    owner, _ = users
    with pytest.raises(Exception):
        library_service.create_library_asset(
            db, owner.id, b"not an image", "image/png", "private", "坏图"
        )
    assert db.query(DesignImageLibraryAsset).count() == 0
    assert db.query(DesignImageAsset).count() == 0
