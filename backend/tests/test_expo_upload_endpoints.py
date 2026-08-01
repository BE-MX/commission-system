"""展会扫码上传：会话创建的双照片来源 + 四个端点（2026-08-01）。"""

import io
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.auth.utils import create_access_token
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.expo import ai_pipeline, service, upload_service
from app.expo.models import ExpoCustomer
from app.expo.router import router, upload_page, upload_photo


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


# ==================== 端点层（HTTP） ====================

@pytest.fixture(autouse=True)
def _non_default_upload_secret(monkeypatch):
    """功能测试统一钉死成非默认密钥，不依赖 backend/.env 里配没配这个变量——
    默认值本身的行为单独在下面的 fail-closed 用例里测，且显式 monkeypatch 回默认值
    （同 tests/test_expo_upload_ticket.py 的 _non_default_secret 套路）。"""
    monkeypatch.setattr(get_settings(), "EXPO_UPLOAD_SIGN_SECRET", "unit-test-secret-not-default")


@contextmanager
def _client():
    """两个 upload 端点免鉴权、不碰 DB——独立挂载，不带 app.expo.router 的其余端点
    （那些需要 get_db/权限依赖），对齐 tests/test_dashboard_preference.py:123 的做法。"""
    app = FastAPI()
    app.add_api_route("/api/expo/upload/{token}", upload_page, methods=["GET"])
    app.add_api_route("/api/expo/upload/{token}", upload_photo, methods=["POST"])
    with TestClient(app) as c:
        yield c


@contextmanager
def _full_client(db, permissions=("expo:write",)):
    """挂载完整 expo router：测 create_upload_ticket / create_session 这类
    既要鉴权又要碰 DB 的端点，需要真实 JWT + get_db 覆盖。"""
    app = FastAPI()
    app.include_router(router, prefix="/api/expo")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": "1", "username": "u1", "roles": [], "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


class TestUploadPage:
    def test_renders_for_valid_token_without_leaking_customer_name(self, db):
        """页面渲染成功、含 90 天留存文案；且不回显客户姓名——二维码由共享屏签发，
        屏上任何人都能扫，在陌生人可达的页面上显名是隐私泄露（产品明确决策）。"""
        customer = _customer(db)
        token = upload_service.make_token(customer.id)
        with _client() as client:
            resp = client.get(f"/api/expo/upload/{token}")
        assert resp.status_code == 200
        assert "保留 90 天" in resp.text
        assert customer.name not in resp.text

    def test_expired_token_renders_explanation_not_bare_404(self):
        token = upload_service.make_token(42, ttl_seconds=-1)
        with _client() as client:
            resp = client.get(f"/api/expo/upload/{token}")
        assert resp.status_code == 200
        assert "已过期" in resp.text

    def test_non_ascii_signature_renders_explanation_not_500(self):
        """hmac.compare_digest 遇到非 ASCII 字符抛 TypeError 而非 ValueError；
        Task 1 曾在这里炸出真实 500。confirm 该修复在端点层仍然生效
        （不是只在 upload_service 单测里绿，路由层的 except ValueError 也接得住）。"""
        cid, exp, _ = upload_service.make_token(42).split("-")
        mangled = f"{cid}-{exp}-{'é' * 16}"
        with _client() as client:
            resp = client.get(f"/api/expo/upload/{mangled}")
        assert resp.status_code == 200
        assert "无效" in resp.text

    def test_contract_violation_from_parse_token_is_not_swallowed(self, monkeypatch):
        """upload_page 的 except 子句刻意只窄到 ValueError——parse_token 的契约保证
        只抛 ValueError（见其文档：先做形状校验就是为了不让 TypeError 之类的意外
        逃出来）。若把 except 换宽成裸 Exception，未来谁不小心破坏了这份契约
        （比如 parse_token 哪天多出一条会抛 AttributeError 的分支），这里会把它
        悄悄压成客户能看到的"链接无效"说明页——没有 logger、没有 print，宪法 6
        对吞异常的最低要求（至少留痕）都保不住，问题会在生产里隐形。
        这里钉住"非 ValueError 必须原样炸穿"，而不是被温柔地转成一张解释页。"""
        def _boom(token):
            raise RuntimeError("parse_token contract violated")

        monkeypatch.setattr(upload_service, "parse_token", _boom)
        with _client() as client:
            with pytest.raises(RuntimeError):
                client.get("/api/expo/upload/whatever")


class TestUploadPhoto:
    def test_stores_pending_file(self):
        token = upload_service.make_token(42)
        with _client() as client:
            resp = client.post(
                f"/api/expo/upload/{token}",
                files={"photo": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["uploaded"] is True
        assert upload_service.latest_pending(42) is not None

    def test_rejects_bad_token(self):
        with _client() as client:
            resp = client.post(
                "/api/expo/upload/not-a-real-token",
                files={"photo": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        assert resp.status_code == 400

    def test_rejects_non_image_and_leaves_no_pending_file(self):
        token = upload_service.make_token(43)
        with _client() as client:
            resp = client.post(
                f"/api/expo/upload/{token}",
                files={"photo": ("x.jpg", b"definitely-not-an-image", "image/jpeg")},
            )
        assert resp.status_code == 400
        assert upload_service.latest_pending(43) is None

    def test_rejects_oversize_upload(self):
        """端点层验证有界读（F2）：photo.file.read(MAX_UPLOAD_BYTES + 1) 只物化刚好
        够判定"超限"的字节数，而不是把整份超大 body 读进内存——这里确认改成有界读
        之后，超限判定本身仍然正确（不是只省了内存、把该拒的漏放过去）。"""
        token = upload_service.make_token(44)
        oversize = b"\xff" * (upload_service.MAX_UPLOAD_BYTES + 1)
        with _client() as client:
            resp = client.post(
                f"/api/expo/upload/{token}",
                files={"photo": ("big.jpg", oversize, "image/jpeg")},
            )
        assert resp.status_code == 400
        assert upload_service.latest_pending(44) is None


class TestUploadTicketFailClosed:
    """密钥停在仓库默认值时，签发端点必须拒发（fail-closed），而不是带着没锁的
    授权模型继续发码——见 upload_service.secret_is_default 的文档。"""

    def test_default_secret_returns_503(self, db, monkeypatch):
        customer = _customer(db)
        monkeypatch.setattr(
            get_settings(), "EXPO_UPLOAD_SIGN_SECRET",
            Settings.model_fields["EXPO_UPLOAD_SIGN_SECRET"].default,
        )
        with _full_client(db) as client:
            resp = client.post(f"/api/expo/kiosk/upload-ticket?customer_id={customer.id}")
        assert resp.status_code == 503

    def test_non_default_secret_issues_ticket(self, db):
        """非默认密钥（本文件 autouse fixture 已钉死）下正常放行，避免上一条用例
        单靠"改成默认值必 503"就误以为端点恒久 503。"""
        customer = _customer(db)
        with _full_client(db) as client:
            resp = client.post(f"/api/expo/kiosk/upload-ticket?customer_id={customer.id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["token"]


class TestCreateSessionPendingPhotoForm:
    """POST /sessions 的 pending_photo 表单字段：空串归一化守卫。"""

    def test_blank_pending_photo_alone_is_clean_400(self, db):
        customer = _customer(db)
        with _full_client(db) as client:
            resp = client.post(
                f"/api/expo/sessions?customer_id={customer.id}&mode=scene",
                data={"pending_photo": ""},
            )
        assert resp.status_code == 400

    def test_blank_pending_photo_alongside_real_photo_still_succeeds(self, db):
        """真正的回归场景：前端可能无论走不走扫码，都固定 append 一个空的
        pending_photo 字段。若路由不把空串归一成 None，二选一守卫会把
        "photo 有值 + pending_photo=''（非 None）"误判成"两边都给了"而拒绝
        这次本该成功的现场拍照——这条测试直接卡住这条回归线。"""
        customer = _customer(db)
        with _full_client(db) as client:
            resp = client.post(
                f"/api/expo/sessions?customer_id={customer.id}&mode=scene",
                data={"pending_photo": ""},
                files={"photo": ("p.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["session_id"]
