"""展会扫码上传：会话创建的双照片来源 + 四个端点（2026-08-01）。"""

import io
import os
import re
import shutil
import subprocess
import tempfile
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
from app.expo.router import _upload_html, router, upload_page, upload_photo


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
        """端到端确认：一条带非 ASCII 签名段的乱码 URL 在端点层是干净的说明页，
        不是 500——这是 Task 1 曾经炸出的真实故障，路由层的 except ValueError 必须
        接得住（不能只在 upload_service 单测里绿）。

        老实交代机制：'é'*16 不满足 _SIGNATURE_RE 的 [0-9a-f]{16}，在形状校验这一步
        就被拒了，从未真正走到会对非 ASCII 抛 TypeError 的 hmac.compare_digest——
        凡是能通过 [0-9a-f]{16} 形状校验的字符串本身就只含 ASCII，两者在结构上
        互斥，不存在"形状合法但非 ASCII"的签名段能真正触达 compare_digest。"""
        cid, exp, _ = upload_service.make_token(42).split("-")
        mangled = f"{cid}-{exp}-{'é' * 16}"
        with _client() as client:
            resp = client.get(f"/api/expo/upload/{mangled}")
        assert resp.status_code == 200
        assert "无效" in resp.text

    def test_contract_violation_from_parse_token_is_not_swallowed(self, monkeypatch):
        """upload_page 的 except 子句刻意只窄到 ValueError——canonical_token（及其
        共用的 _parse_token_parts）的契约保证只抛 ValueError（见其文档：先做形状
        校验就是为了不让 TypeError 之类的意外逃出来）。若把 except 换宽成裸
        Exception，未来谁不小心破坏了这份契约（比如哪天多出一条会抛
        AttributeError 的分支），这里会把它悄悄压成客户能看到的"链接无效"说明页
        ——没有 logger、没有 print，宪法 6 对吞异常的最低要求（至少留痕）都保不住，
        问题会在生产里隐形。这里钉住"非 ValueError 必须原样炸穿"，而不是被温柔地
        转成一张解释页。

        patch 的是 _parse_token_parts（parse_token 与 canonical_token 共用的校验
        核心），不是任一个具体的包装函数——router 调用哪个包装函数是实现细节，
        这条测试锁的是"校验核心的契约"，不该因为路由内部换了个包装函数名就失效。
        """
        def _boom(token):
            raise RuntimeError("token validation contract violated")

        monkeypatch.setattr(upload_service, "_parse_token_parts", _boom)
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
        """端点层验证有界读（I1）：photo.file.read(MAX_UPLOAD_BYTES + 1) 只物化刚好
        够判定"超限"的字节数，而不是把整份超大 body 读进内存——这里确认改成有界读
        之后，超限判定本身仍然正确（不是只省了内存、把该拒的漏放过去）。

        注：这条测试本身对"是否真的有界读"是**vacuous** 的——它 post 的是
        b"\\xff" * (N+1)，不是有效图片，PIL 探针无论读多少字节都会拒绝，
        `read(N+1)`→`read()`、`read(N+1)`→`read(N)` 这两个变体都照样通过。
        真正锁定"读了多少字节"的是下面的
        test_handler_materializes_only_the_bounded_prefix；这条测试留着是因为
        它仍然验证了一个真实、独立的行为——超大非法内容端到端确实被拒。"""
        token = upload_service.make_token(44)
        oversize = b"\xff" * (upload_service.MAX_UPLOAD_BYTES + 1)
        with _client() as client:
            resp = client.post(
                f"/api/expo/upload/{token}",
                files={"photo": ("big.jpg", oversize, "image/jpeg")},
            )
        assert resp.status_code == 400
        assert upload_service.latest_pending(44) is None

    def test_handler_materializes_only_the_bounded_prefix(self, monkeypatch):
        """I1 的真正锁点：photo.file.read(MAX_UPLOAD_BYTES + 1) 只该物化
        MAX_UPLOAD_BYTES + 1 字节，不多不少——多了就是白白多一次全量内存拷贝
        （Starlette 早已把整个 body 落到 SpooledTemporaryFile，这一步省不掉那次
        落盘，只省堆内存这一份），少了会让合法但接近上限的图片被错误截断。

        用 spy 顶替 save_pending，直接测"传进来的 raw 有多长"，不依赖 PIL 探针
        的副作用——这样 read(N+1)→read()、read(N+1)→read(N) 两个变体都会被
        直接测出字节数不对，不再像 test_rejects_oversize_upload 那样靠"内容
        不是图片"这个巧合过关。"""
        seen = {}

        def spy(customer_id, raw, filename):
            seen["n"] = len(raw)
            raise ValueError("stop")

        monkeypatch.setattr(upload_service, "save_pending", spy)
        token = upload_service.make_token(44)
        with _client() as client:
            client.post(
                f"/api/expo/upload/{token}",
                files={"photo": ("big.jpg", b"\xff" * (upload_service.MAX_UPLOAD_BYTES * 2), "image/jpeg")},
            )
        assert seen["n"] == upload_service.MAX_UPLOAD_BYTES + 1


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

    def test_rejects_customer_without_consent(self, db):
        """I7：模块内其余落盘路径（create_session）都以 consent_at 为前提；发码
        端点在 happy path 下（register 强制 consent 才建档）也总是成立，但照片
        经这里落到磁盘、且经 /uploads 公开 URL 可读——发码是那道隐私红线生效前的
        最后一关，不该只靠"调用方应该都先 register 过"这个假设撑住。"""
        customer = ExpoCustomer(name="未同意", phone="13800138002", expo_code="t")
        db.add(customer)
        db.commit()
        db.refresh(customer)
        with _full_client(db) as client:
            resp = client.post(f"/api/expo/kiosk/upload-ticket?customer_id={customer.id}")
        assert resp.status_code == 400


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


# ==================== <script> 语法防线（结构性，2026-08-01） ====================
# ~140 行 CSS/JS 活在一个 f-string 里，没有任何 linter/formatter/类型检查会看它——
# I3（token 非规范拼入 JS 字符串字面量导致整个 <script> 块语法错误）就是靠手动
# extract + `node --check` 才找到的。把这道检查钉进测试，不再依赖人工事后抽查。

def _extract_script(html_text: str) -> str:
    m = re.search(r"<script>(.*)</script>", html_text, re.S)
    assert m, "上传页里找不到 <script> 块"
    return m.group(1)


def _assert_valid_js(js_source: str) -> None:
    """node 不在 PATH 时干净跳过——不把这条防线的可用性强加给没装 node 的环境。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在 PATH，跳过 JS 语法检查")
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(js_source)
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    finally:
        os.unlink(path)


def test_upload_page_script_is_valid_javascript():
    """基线：一个规范 token 渲染出的 <script> 必须是合法 JS。"""
    token = upload_service.make_token(1)
    _assert_valid_js(_extract_script(_upload_html(token, None)))


def test_upload_page_rejects_non_canonical_token_before_it_reaches_the_script():
    """I3 端到端回归：hmac.compare_digest 通不过、但 int() 通得过的"非规范但签名
    有效"令牌——这里用一个前置裸换行的 customer_id 段（int('\\n42') == 42，
    签名照样对得上，因为 _sign 是对解析后的数值签的）。

    旧实现把客户端传来的原始 token 字符串原样嵌进 `fetch('...')` 的单引号 JS
    字面量：`fetch('/api/expo/upload/\\n42-...')`——一个裸换行会提前截断整个字符
    串字面量，砸掉整条 <script>（页面看起来正常，两个按钮却悄无声息地失效）。
    upload_page 现在改用 canonical_token 重建规范 ASCII 形式再嵌入，这里通过
    真实 HTTP GET + node --check 端到端确认修复生效，而不是只在 upload_service
    单测里验证 canonical_token 这一个函数。"""
    from urllib.parse import quote

    token = upload_service.make_token(42)
    cid, exp, sig = token.split("-")
    noisy = f"\n{cid}-{exp}-{sig}"
    with _client() as client:
        # 真实浏览器/httpx 客户端都不会在 URL 里发送裸控制字符——%0A 才是实际
        # 会经过网络到达服务端的字节，quote() 在这里只是重现"客户端已经做了合规
        # 编码，问题出在服务端如何处理解码后的值"这个真实场景，不是绕过校验
        resp = client.get(f"/api/expo/upload/{quote(noisy, safe='')}")
    assert resp.status_code == 200
    _assert_valid_js(_extract_script(resp.text))


# ==================== delete_customer 必须够得着待取照片（I3） ====================

def test_delete_customer_purges_pending_uploads(db):
    """隐私合规：delete_customer 原逻辑只走 customer.sessions 关联的
    photo_path/image_path，够不着扫码上传的待取照片（uploads/expo/pending/，
    与 photos/、results/ 平级、同样经 /uploads 公开挂载可读的第二个照片仓库）。
    待取照片本靠 sweep_stale 兜底 2 小时清理，但客户主动要求删除时不该让他们
    再多等这 2 小时——上传页承诺「可随时联系我们删除」。"""
    customer = _customer(db)
    name = upload_service.save_pending(customer.id, _jpeg_bytes(), "p.jpg")
    assert (upload_service.PENDING_DIR / name).exists()

    assert service.delete_customer(db, customer.id) is True

    assert not (upload_service.PENDING_DIR / name).exists()


def test_delete_customer_pending_purge_is_customer_scoped(db):
    """裁剪按客户隔离：删客户 A 不该动客户 B 的待取照片。"""
    customer = _customer(db)
    other_name = upload_service.save_pending(customer.id + 999, _jpeg_bytes(), "other.jpg")

    service.delete_customer(db, customer.id)

    assert (upload_service.PENDING_DIR / other_name).exists()
