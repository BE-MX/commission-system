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
    # create_session 落盘用的是真实 ai_pipeline.PHOTO_DIR/RESULT_DIR（ensure_dirs 两个都建）；
    # 不隔离的话，每次跑这份测试都会往仓库真实的 uploads/expo/ 下写残留目录/文件，
    # 越攒越多且没人清理，CI/新 clone 上尤其明显。
    # REPO_ROOT 一并挪到 tmp_path 保持 to_rel() 的相对路径推导成立——PHOTO_DIR/RESULT_DIR
    # 挪到 tmp_path/uploads/expo/{photos,results}，相对层级不变，断言里的路径前缀照旧成立。
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ai_pipeline, "PHOTO_DIR", tmp_path / "uploads" / "expo" / "photos")
    monkeypatch.setattr(ai_pipeline, "RESULT_DIR", tmp_path / "uploads" / "expo" / "results")


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
    # 复制 + 提交成功后才清理原件：磁盘上最终仍只留一份，只是不再靠“移动”来保证
    assert not (upload_service.PENDING_DIR / name).exists()


def test_create_session_pending_survives_failed_commit(db, monkeypatch):
    """copy 而非 move 的理由：commit 失败（展位现场对公网 RDS 的连接抖动是真实故障，
    不是理论风险）时，客户的待取照片不能凭空消失——原件必须还在，能直接重试确认，
    而不是被打发回去重新扫码重传。"""
    customer = _customer(db)
    name = upload_service.save_pending(customer.id, _jpeg_bytes(), "p.jpg")

    def _boom():
        raise RuntimeError("connection reset")

    monkeypatch.setattr(db, "commit", _boom)

    with pytest.raises(RuntimeError):
        service.create_session(db, customer.id, None, None, pending_name=name)

    assert (upload_service.PENDING_DIR / name).exists()  # 待取原件还在，可以直接重试确认


def test_create_session_pending_vanishing_before_copy_is_clean_error(db, monkeypatch):
    """resolve_pending 的 is_file() 探测和真正复制之间有极小的 TOCTOU 窗口（并发二次
    确认、sweep_stale 抢先清理、Windows AV 文件锁）。文件在窗口内消失时必须是干净的
    ValueError（对客户可读+被 router 的 except ValueError 接住），不能是裸的
    FileNotFoundError/PermissionError 逃逸成没有 expo 标记日志的 500。"""
    customer = _customer(db)
    name = upload_service.save_pending(customer.id, _jpeg_bytes(), "p.jpg")

    def _vanished(_src, _dst):
        raise FileNotFoundError("vanished mid-flight")

    monkeypatch.setattr(service.shutil, "copy", _vanished)

    with pytest.raises(ValueError, match="已失效"):
        service.create_session(db, customer.id, None, None, pending_name=name)


def test_create_session_from_pending_preserves_real_suffix(db):
    """save_pending 接受 .png/.webp，downscale_inplace 只重编码超过 UPLOAD_MAX_EDGE 的图——
    一张小 PNG 经扫码确认后，文件名后缀必须跟着真实格式走，否则静态挂载会用 .jpg 名字
    服务一个实际是 PNG 的文件，浏览器按错误的 Content-Type 处理。"""
    customer = _customer(db)
    buf = io.BytesIO()
    Image.new("RGB", (80, 120), (10, 20, 30)).save(buf, "PNG")
    png_bytes = buf.getvalue()
    name = upload_service.save_pending(customer.id, png_bytes, "p.png")

    session = service.create_session(db, customer.id, None, None, pending_name=name)

    assert session.photo_path.endswith(".png")
    with Image.open(ai_pipeline.to_abs(session.photo_path)) as im:
        assert im.format == "PNG"


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
    """二选一防线的两条臂：全无与全有都要挡。全有那一臂曾经被弱化成
    `upload_file is None and pending_name is None`（只挡全无），5 个原有测试
    照样全绿——这条断言专门补上那个洞。"""
    customer = _customer(db)
    with pytest.raises(ValueError, match="二选一"):
        service.create_session(db, customer.id, None, None)

    class _Upload:
        filename = "photo.jpg"
        file = io.BytesIO(_jpeg_bytes())

    with pytest.raises(ValueError, match="二选一"):
        service.create_session(db, customer.id, _Upload(), None, pending_name="whatever.jpg")


def test_create_session_rejects_empty_string_pending_name(db):
    """守卫只测 is None，分支曾经测真值（if pending_name:）——两个判据一旦不一致，
    空字符串就能从守卫缝里溜过去，砸到 upload_file.filename（None 无此属性）变成 500。
    resolve_pending 本身对空串/纯空白已经能给出干净的 ValueError，这里确认从
    create_session 整条路径调用时，空字符串走的是这条干净路径而不是 AttributeError。"""
    customer = _customer(db)
    with pytest.raises(ValueError):
        service.create_session(db, customer.id, None, None, pending_name="")


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
