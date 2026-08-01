"""展会扫码上传：会话创建的双照片来源（2026-08-01）。"""

import io

import pytest
from PIL import Image

from app.expo import ai_pipeline, service, upload_service
from app.expo.models import ExpoCustomer
from datetime import datetime


@pytest.fixture(autouse=True)
def _isolate_pending_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "PENDING_DIR", tmp_path / "pending")
    # create_session 落盘用的是真实 ai_pipeline.PHOTO_DIR；不隔离的话，每次跑这份测试
    # 都会往仓库真实的 uploads/expo/photos/ 写残留文件，越攒越多且没人清理。
    # REPO_ROOT 一并挪到 tmp_path 保持 to_rel() 的相对路径推导成立——PHOTO_DIR 挪到
    # tmp_path/uploads/expo/photos，相对层级不变，断言里 "uploads/expo/photos/" 前缀照旧成立。
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ai_pipeline, "PHOTO_DIR", tmp_path / "uploads" / "expo" / "photos")


def _jpeg_bytes(size=(80, 120)):
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 90, 70)).save(buf, "JPEG")
    return buf.getvalue()


def _customer(db):
    customer = ExpoCustomer(name="陈女士", phone="13800138000", expo_code="t",
                            consent_at=datetime.utcnow())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def test_create_session_from_pending_moves_file(db):
    customer = _customer(db)
    name = upload_service.save_pending(customer.id, _jpeg_bytes(), "p.jpg")

    session = service.create_session(db, customer.id, None, None, pending_name=name)

    assert session.photo_path.startswith("uploads/expo/photos/")
    assert not (upload_service.PENDING_DIR / name).exists()  # 移动而非复制，磁盘不留两份


def test_create_session_from_pending_matches_camera_shape(db):
    """待取来源与现场拍照必须落到同一形态，下游（对比图/分析）不该看出区别。

    只比扩展名没有区分力——两边构造用的都是 .jpg，恒等式永远成立，测不出任何回归。
    真正要验证的是两条路径最终落盘的图片经过了同一次 downscale_inplace：故意传一张
    超过 UPLOAD_MAX_EDGE 的大图，如果某条分支漏调用/漏落盘，两边的像素尺寸会露馅。
    """
    customer = _customer(db)
    photo_bytes = _jpeg_bytes(size=(2000, 3000))
    name = upload_service.save_pending(customer.id, photo_bytes, "p.jpg")
    from_pending = service.create_session(db, customer.id, None, None, pending_name=name)

    class _Upload:
        filename = "photo.jpg"
        file = io.BytesIO(photo_bytes)

    from_camera = service.create_session(db, customer.id, _Upload(), None)

    assert from_pending.photo_path.rsplit(".", 1)[1] == from_camera.photo_path.rsplit(".", 1)[1]
    assert from_pending.photo_path.startswith("uploads/expo/photos/c")
    assert from_camera.photo_path.startswith("uploads/expo/photos/c")

    with Image.open(ai_pipeline.to_abs(from_pending.photo_path)) as im:
        pending_size = im.size
    with Image.open(ai_pipeline.to_abs(from_camera.photo_path)) as im:
        camera_size = im.size
    # 两边都必须真的被压过（max edge 落到阈值），而不是碰巧都保持原图尺寸一致
    assert max(pending_size) == ai_pipeline.UPLOAD_MAX_EDGE
    assert pending_size == camera_size


def test_create_session_requires_exactly_one_source(db):
    customer = _customer(db)
    with pytest.raises(ValueError, match="二选一"):
        service.create_session(db, customer.id, None, None)


def test_create_session_rejects_foreign_pending(db):
    customer = _customer(db)
    stranger = upload_service.save_pending(customer.id + 999, _jpeg_bytes(), "x.jpg")
    with pytest.raises(ValueError, match="不属于该客户"):
        service.create_session(db, customer.id, None, None, pending_name=stranger)


def test_create_session_still_blocks_without_consent(db):
    customer = ExpoCustomer(name="未同意", phone="13800138001", expo_code="t")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    name = upload_service.save_pending(customer.id, _jpeg_bytes(), "p.jpg")
    with pytest.raises(ValueError, match="未同意"):
        service.create_session(db, customer.id, None, None, pending_name=name)
