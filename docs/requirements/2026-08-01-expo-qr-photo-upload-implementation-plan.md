# 展会扫码上传照片入口 · 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 展会 kiosk 拍摄页增加次级入口，客户扫码后用自己手机上传照片，照片回到 kiosk 走既有生成管线。

**Architecture:** 签名令牌（HMAC，不落库）绑定 customer_id 与过期时间；照片落 `uploads/expo/pending/`；kiosk 轮询待取照片后进既有预览态；确认时待取文件移入 `PHOTO_DIR` 并复用既有 `create_session`。**零迁移、零新表。**

**Tech Stack:** FastAPI + Pillow（后端）、Vue 3 + qrcode@1.5.4（前端，已在 package.json）。

**设计依据：** `docs/requirements/2026-08-01-expo-qr-photo-upload.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `backend/app/core/config.py` | 新增 `EXPO_UPLOAD_SIGN_SECRET` | 修改 |
| `backend/app/expo/upload_service.py` | 令牌签发/校验 + 待取文件读写 + 机会式清理。**纯逻辑，不碰 DB** | 新建 |
| `backend/app/expo/router.py` | 4 个新端点 + `POST /sessions` 改造 | 修改 |
| `backend/app/expo/service.py` | `create_session` 支持待取文件来源 | 修改 |
| `backend/tests/test_expo_upload_ticket.py` | 令牌与待取文件的单元测试 | 新建 |
| `backend/tests/test_expo_upload_endpoints.py` | 端点级测试（含路径穿越、体积、互斥） | 新建 |
| `frontend/src/views/expo/kiosk/publicUrl.js` | 裸 IP → http 降级，供二维码两处共用 | 新建 |
| `frontend/src/views/expo/kiosk/ResultScreen.vue` | 改用共享 helper，删本地副本 | 修改 |
| `frontend/src/api/expo.js` | 两个新 API | 修改 |
| `frontend/src/views/expo/composables/useTryOnFlow.js` | 二维码状态 + idle 挂起 + 待取轮询 | 修改 |
| `frontend/src/views/expo/kiosk/CaptureScreen.vue` | 二维码面板 UI | 修改 |
| `docs/api-reference.md` | 新端点登记 | 修改 |

`upload_service.py` 独立成文件而不是塞进 `service.py`：它完全不碰数据库，只处理令牌与文件，边界清晰且可单独测；`app/expo/` 已有 `script_service.py` 这个子 service 先例。

---

## Task 1: 配置项与签名令牌

**Files:**
- Modify: `backend/app/core/config.py:101`（`ASSET_SIGN_SECRET` 同段落之后）
- Create: `backend/app/expo/upload_service.py`
- Test: `backend/tests/test_expo_upload_ticket.py`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_expo_upload_ticket.py`：

```python
"""展会扫码上传：令牌签发/校验 + 待取文件（2026-08-01）。

令牌不落库，customer_id 与过期时间明文随令牌传输，靠 HMAC 防篡改。
"""

import time

import pytest

from app.expo import upload_service


class TestToken:
    def test_roundtrip_returns_customer_id(self):
        token = upload_service.make_token(42)
        assert upload_service.parse_token(token) == 42

    def test_expired_token_rejected(self):
        token = upload_service.make_token(42, ttl_seconds=-1)
        with pytest.raises(ValueError, match="已过期"):
            upload_service.parse_token(token)

    def test_tampered_customer_id_rejected(self):
        _, exp, sig = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="校验失败"):
            upload_service.parse_token(f"99-{exp}-{sig}")

    def test_tampered_expiry_rejected(self):
        cid, exp, sig = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="校验失败"):
            upload_service.parse_token(f"{cid}-{int(exp) + 600}-{sig}")

    def test_tampered_signature_rejected(self):
        cid, exp, _ = upload_service.make_token(42).split("-")
        with pytest.raises(ValueError, match="校验失败"):
            upload_service.parse_token(f"{cid}-{exp}-0000000000000000")

    @pytest.mark.parametrize("bad", ["", "abc", "1-2", "1-2-3-4", "x-y-z"])
    def test_malformed_token_rejected(self, bad):
        with pytest.raises(ValueError, match="格式不正确"):
            upload_service.parse_token(bad)

    def test_expiry_checked_before_signature(self):
        """过期先于签名校验：过期令牌即使签名合法也不该泄露「签名对不对」的信息。"""
        token = upload_service.make_token(42, ttl_seconds=-1)
        with pytest.raises(ValueError, match="已过期"):
            upload_service.parse_token(token)

    def test_default_ttl_is_ten_minutes(self):
        before = int(time.time())
        _, exp, _ = upload_service.make_token(7).split("-")
        assert 595 <= int(exp) - before <= 605
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_ticket.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.expo.upload_service'`

- [ ] **Step 3: 加配置项**

在 `backend/app/core/config.py` 的 `ASSET_UPLOAD_STAGING` 那行之后、`# ── 客户售后管理` 之前插入：

```python
    # ── 展会扫码上传（2026-08-01）────────────────────────────
    # 手机上传页免鉴权，令牌即凭证。生产环境须在 backend/.env 覆盖为随机串
    EXPO_UPLOAD_SIGN_SECRET: str = "leshine-expo-upload-secret"
```

- [ ] **Step 4: 实现令牌部分**

创建 `backend/app/expo/upload_service.py`：

```python
"""展会扫码上传：令牌签发/校验 + 待取照片读写（2026-08-01）。

刻意不落库：令牌的两个职责——绑定到哪个客户、什么时候作废——都能用密码学表达。
若另立 ticket 表，「照片有没有传上来」就有两份真相（表里的 status 与磁盘上的文件），
必须保持同步；本项目已在这类不同步上栽过（素材域 folder_upload 静默失败）。
代价是令牌在有效期内可重复使用，靠 10 分钟短有效期 + kiosk 顾问预览兜住。

本模块不碰数据库，只处理令牌与文件，可脱离 DB 单测。
"""

import hashlib
import hmac
import logging
import time
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.expo import ai_pipeline

logger = logging.getLogger("commission.expo")

TICKET_TTL_SECONDS = 600          # 10 分钟：够客户翻相册，又限制二维码被拍走后的滥用窗口
PENDING_DIR = ai_pipeline.UPLOAD_ROOT / "pending"
STALE_AFTER_SECONDS = 2 * 3600    # 待取照片留存上界
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _sign(customer_id: int, exp: int) -> str:
    secret = get_settings().EXPO_UPLOAD_SIGN_SECRET
    msg = f"{customer_id}:{exp}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def make_token(customer_id: int, ttl_seconds: int = TICKET_TTL_SECONDS) -> str:
    """签发上传令牌：{customer_id}-{过期时间戳}-{签名}。"""
    exp = int(time.time()) + ttl_seconds
    return f"{customer_id}-{exp}-{_sign(customer_id, exp)}"


def parse_token(token: str) -> int:
    """校验令牌并返回 customer_id；非法或过期抛 ValueError（文案直接面向客户）。"""
    parts = (token or "").split("-")
    if len(parts) != 3:
        raise ValueError("上传码格式不正确")
    try:
        customer_id, exp = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError("上传码格式不正确") from None
    # 过期先于签名校验：过期的码无需再暴露签名是否正确
    if exp < time.time():
        raise ValueError("上传码已过期，请回到展位屏幕重新获取")
    if not hmac.compare_digest(parts[2], _sign(customer_id, exp)):
        raise ValueError("上传码校验失败")
    return customer_id
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_ticket.py -q`
Expected: PASS，8 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/core/config.py backend/app/expo/upload_service.py backend/tests/test_expo_upload_ticket.py
git commit -m "feat(expo): sign upload tickets for the QR photo entrance"
```

---

## Task 2: 待取文件读写与机会式清理

**Files:**
- Modify: `backend/app/expo/upload_service.py`
- Test: `backend/tests/test_expo_upload_ticket.py`

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/test_expo_upload_ticket.py` 末尾追加：

```python
class TestPendingFiles:
    @pytest.fixture(autouse=True)
    def _isolate_pending_dir(self, tmp_path, monkeypatch):
        """待取目录指向 tmp，避免测试污染真实 uploads/expo/pending。"""
        monkeypatch.setattr(upload_service, "PENDING_DIR", tmp_path / "pending")

    @staticmethod
    def _jpeg_bytes(size=(80, 120)):
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", size, (120, 90, 70)).save(buf, "JPEG")
        return buf.getvalue()

    def test_save_pending_writes_file_named_for_customer(self):
        name = upload_service.save_pending(42, self._jpeg_bytes(), "my photo.JPG")
        assert name.startswith("c42_")
        assert name.endswith(".jpg")
        assert (upload_service.PENDING_DIR / name).exists()

    def test_save_pending_rejects_non_image(self):
        with pytest.raises(ValueError, match="不是有效的图片"):
            upload_service.save_pending(42, b"definitely-not-an-image", "x.jpg")

    def test_save_pending_rejects_oversize(self):
        oversize = b"\xff" * (upload_service.MAX_UPLOAD_BYTES + 1)
        with pytest.raises(ValueError, match="过大"):
            upload_service.save_pending(42, oversize, "big.jpg")

    def test_save_pending_downscales_large_image(self):
        from PIL import Image

        name = upload_service.save_pending(42, self._jpeg_bytes((4000, 3000)), "p.jpg")
        with Image.open(upload_service.PENDING_DIR / name) as im:
            assert max(im.size) <= ai_pipeline.UPLOAD_MAX_EDGE

    def test_latest_pending_returns_newest_of_many(self):
        import os

        first = upload_service.save_pending(42, self._jpeg_bytes(), "a.jpg")
        second = upload_service.save_pending(42, self._jpeg_bytes(), "b.jpg")
        # mtime 分辨率在部分文件系统上不足以区分同秒写入，显式拉开
        os.utime(upload_service.PENDING_DIR / first, (time.time() - 60,) * 2)
        assert upload_service.latest_pending(42).name == second

    def test_latest_pending_ignores_other_customers(self):
        upload_service.save_pending(99, self._jpeg_bytes(), "other.jpg")
        assert upload_service.latest_pending(42) is None

    def test_latest_pending_none_when_empty(self):
        assert upload_service.latest_pending(42) is None

    def test_resolve_pending_blocks_path_traversal(self):
        with pytest.raises(ValueError, match="非法"):
            upload_service.resolve_pending(42, "../../etc/passwd")

    def test_resolve_pending_blocks_other_customers_file(self):
        name = upload_service.save_pending(99, self._jpeg_bytes(), "x.jpg")
        with pytest.raises(ValueError, match="不属于该客户"):
            upload_service.resolve_pending(42, name)

    def test_resolve_pending_missing_file(self):
        with pytest.raises(ValueError, match="不存在"):
            upload_service.resolve_pending(42, "c42_deadbeef.jpg")

    def test_sweep_stale_removes_only_expired(self):
        import os

        fresh = upload_service.save_pending(42, self._jpeg_bytes(), "fresh.jpg")
        stale = upload_service.save_pending(42, self._jpeg_bytes(), "stale.jpg")
        old = time.time() - upload_service.STALE_AFTER_SECONDS - 60
        os.utime(upload_service.PENDING_DIR / stale, (old, old))

        assert upload_service.sweep_stale() == 1
        assert (upload_service.PENDING_DIR / fresh).exists()
        assert not (upload_service.PENDING_DIR / stale).exists()

    def test_sweep_stale_survives_missing_dir(self):
        """目录尚未创建时清理不得抛异常——它挂在发码路径上，抛了就发不出码。"""
        assert upload_service.sweep_stale() == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_ticket.py::TestPendingFiles -q`
Expected: FAIL，`AttributeError: module 'app.expo.upload_service' has no attribute 'save_pending'`

- [ ] **Step 3: 实现待取文件部分**

在 `backend/app/expo/upload_service.py` 末尾追加：

```python
def _pending_dir() -> Path:
    """每次现取而不是模块级缓存：测试用 monkeypatch 换 PENDING_DIR 才能生效。"""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    return PENDING_DIR


def save_pending(customer_id: int, raw: bytes, filename: str | None) -> str:
    """落一张待取照片，返回纯文件名。非图片 / 超限抛 ValueError。

    免鉴权端点，体积与内容双重校验：Content-Type 可以伪造，能不能被 Pillow 解析不能。
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"照片过大，请压缩后重试（上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB）")

    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()          # verify 后对象不可再用，仅作有效性探针
    except Exception:
        raise ValueError("上传的文件不是有效的图片") from None

    suffix = Path(filename or "photo.jpg").suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    target = _pending_dir() / f"c{customer_id}_{uuid.uuid4().hex[:10]}{suffix}"
    target.write_bytes(raw)
    # 手机原片动辄 3~5MB，落盘即压：这张图要经隧道回源到展位屏做「佩戴前」对比
    ai_pipeline.downscale_inplace(target)
    return target.name


def latest_pending(customer_id: int) -> Path | None:
    """该客户最新的待取照片；没有则 None。客户可能连传多张，取最后一张。"""
    if not PENDING_DIR.exists():
        return None
    files = [p for p in PENDING_DIR.glob(f"c{customer_id}_*") if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def resolve_pending(customer_id: int, name: str) -> Path:
    """待取文件名 → 绝对路径，三道校验：路径穿越、归属、存在性。"""
    root = _pending_dir().resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise ValueError("待取照片名非法")
    if not candidate.name.startswith(f"c{customer_id}_"):
        raise ValueError("待取照片不属于该客户")
    if not candidate.is_file():
        raise ValueError("待取照片不存在或已被清理")
    return candidate


def sweep_stale(now: float | None = None) -> int:
    """删除超过 STALE_AFTER_SECONDS 的待取照片，返回删除条数。

    **不能挂定时任务**：云端展会实例 SCHEDULER_ENABLED=false（防与办公室实例双跑），
    而那台正是跑展会的机器。改为发码与确认两个路径上机会式触发，残留上界由此有保证。
    绝不抛异常——它挂在发码路径上，抛了就发不出码。
    """
    if not PENDING_DIR.exists():
        return 0
    deadline = (now or time.time()) - STALE_AFTER_SECONDS
    removed = 0
    for path in PENDING_DIR.glob("c*"):
        try:
            if path.is_file() and path.stat().st_mtime < deadline:
                path.unlink()
                removed += 1
        except OSError as exc:
            msg = f"[expo] pending sweep skipped {path.name}: {exc}"
            logger.warning(msg)
            print(msg, flush=True)
    return removed
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_ticket.py -q`
Expected: PASS，20 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/expo/upload_service.py backend/tests/test_expo_upload_ticket.py
git commit -m "feat(expo): store and sweep pending photos for QR upload"
```

---

## Task 3: `create_session` 支持待取文件来源

**Files:**
- Modify: `backend/app/expo/service.py:133-151`
- Test: `backend/tests/test_expo_upload_endpoints.py`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_expo_upload_endpoints.py`：

```python
"""展会扫码上传：会话创建的双照片来源（2026-08-01）。"""

import io

import pytest
from PIL import Image

from app.expo import service, upload_service
from app.expo.models import ExpoCustomer
from datetime import datetime


@pytest.fixture(autouse=True)
def _isolate_pending_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "PENDING_DIR", tmp_path / "pending")


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
    """待取来源与现场拍照必须落到同一形态，下游（对比图/分析）不该看出区别。"""
    customer = _customer(db)
    name = upload_service.save_pending(customer.id, _jpeg_bytes(), "p.jpg")
    from_pending = service.create_session(db, customer.id, None, None, pending_name=name)

    class _Upload:
        filename = "photo.jpg"
        file = io.BytesIO(_jpeg_bytes())

    from_camera = service.create_session(db, customer.id, _Upload(), None)

    assert from_pending.photo_path.rsplit(".", 1)[1] == from_camera.photo_path.rsplit(".", 1)[1]
    assert from_pending.photo_path.startswith("uploads/expo/photos/c")
    assert from_camera.photo_path.startswith("uploads/expo/photos/c")


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_endpoints.py -q`
Expected: FAIL，`TypeError: create_session() got an unexpected keyword argument 'pending_name'`

- [ ] **Step 3: 改造 `create_session`**

在 `backend/app/expo/service.py` 顶部 import 区加入：

```python
from app.expo import upload_service
```

把 `create_session` 的签名与落盘段（`service.py:133-151`）替换为：

```python
def create_session(
    db: Session, customer_id: int, upload_file,
    operator_user_id: int | None, mode: str = "tryon",
    pending_name: str | None = None,
) -> ExpoSession:
    """建会话。照片来源二选一：现场拍照的 upload_file，或扫码上传的 pending_name。

    刻意不为扫码上传新开一个建会话端点：会话创建带着同意校验与分析管线启动的副作用，
    两条路会分叉，日后改一条漏一条。分支只在「照片从哪来」这一处，落盘之后完全共用。
    """
    if (upload_file is None) == (pending_name is None):
        raise ValueError("照片来源须在现场拍照与扫码上传之间二选一")

    customer = db.get(ExpoCustomer, customer_id)
    if not customer:
        raise ValueError("客户不存在")
    if not customer.consent_at:
        raise ValueError("客户未同意拍照存储，无法创建会话")

    ai_pipeline.ensure_dirs()
    if pending_name:
        source = upload_service.resolve_pending(customer_id, pending_name)
        photo_path = ai_pipeline.PHOTO_DIR / f"c{customer_id}_{uuid.uuid4().hex[:10]}{source.suffix}"
        # 移动而非复制：同一张照片没有在磁盘上留两份的理由，且待取目录随之自然收敛
        shutil.move(str(source), str(photo_path))
    else:
        suffix = Path(upload_file.filename or "photo.jpg").suffix.lower() or ".jpg"
        photo_path = ai_pipeline.PHOTO_DIR / f"c{customer_id}_{uuid.uuid4().hex[:10]}{suffix}"
        with open(photo_path, "wb") as f:
            shutil.copyfileobj(upload_file.file, f)
    # kiosk 相机件已是 1080px（原样跳过）；顾问文件选择兜底传的手机原片在此压下来——
    # photo_url 会作为"佩戴前"对比图经 frp 隧道回源展示。扫码上传的已在 save_pending
    # 压过一次，downscale_inplace 幂等，重复调用只是空转
    ai_pipeline.downscale_inplace(photo_path)
```

其余部分（构造 `ExpoSession` 起）保持不变。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_endpoints.py -q`
Expected: PASS，5 passed

- [ ] **Step 5: 跑既有会话测试确认无回归**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -k expo -q`
Expected: PASS，全绿（既有调用方全部走 `upload_file` 位置参数，签名向后兼容）

- [ ] **Step 6: 提交**

```bash
git add backend/app/expo/service.py backend/tests/test_expo_upload_endpoints.py
git commit -m "feat(expo): let create_session take a pending photo as its source"
```

---

## Task 4: 四个后端端点

**Files:**
- Modify: `backend/app/expo/router.py`（新增端点 + `POST /sessions` 改造）
- Test: `backend/tests/test_expo_upload_endpoints.py`

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/test_expo_upload_endpoints.py` 末尾追加：

```python
class TestUploadPage:
    """手机上传页与收图端点：免鉴权，令牌即凭证。"""

    def test_page_renders_for_valid_token(self, client, db):
        customer = _customer(db)
        token = upload_service.make_token(customer.id)
        res = client.get(f"/api/expo/upload/{token}")
        assert res.status_code == 200
        assert "上传照片" in res.text
        assert "保留 90 天" in res.text          # 隐私说明是红线，免鉴权页必须写明
        assert customer.name not in res.text     # 共享屏发出的码不带姓名（2026-08-01 决策）

    def test_page_explains_expiry_instead_of_bare_404(self, client):
        expired = upload_service.make_token(1, ttl_seconds=-1)
        res = client.get(f"/api/expo/upload/{expired}")
        assert res.status_code == 200
        assert "已过期" in res.text

    def test_upload_stores_pending(self, client, db):
        customer = _customer(db)
        token = upload_service.make_token(customer.id)
        res = client.post(f"/api/expo/upload/{token}",
                          files={"photo": ("p.jpg", _jpeg_bytes(), "image/jpeg")})
        assert res.status_code == 200
        assert upload_service.latest_pending(customer.id) is not None

    def test_upload_rejects_bad_token(self, client):
        res = client.post("/api/expo/upload/1-2-3",
                          files={"photo": ("p.jpg", _jpeg_bytes(), "image/jpeg")})
        assert res.status_code == 400

    def test_blank_pending_photo_is_a_clean_400(self, client, db):
        """空串必须归一为 None 后走二选一守卫，得到 400——不能漏成 AttributeError 的 500。
        multipart 里「字段在但值为空」很常见（Task 3 实测发现）。"""
        customer = _customer(db)
        res = client.post(f"/api/expo/sessions?customer_id={customer.id}",
                          data={"pending_photo": "   "})
        assert res.status_code == 400

    def test_mangled_url_does_not_500(self, client):
        """免鉴权端点上非 ASCII 签名段必须走 400 而非 500（Task 1 审查 I2）：
        微信改写链接、URL 被截断都会命中，客户看到的应是说明而不是内部错误。"""
        res = client.get("/api/expo/upload/1-9999999999-é")
        assert res.status_code == 200 and "无效" in res.text

    def test_upload_rejects_non_image(self, client, db):
        customer = _customer(db)
        token = upload_service.make_token(customer.id)
        res = client.post(f"/api/expo/upload/{token}",
                          files={"photo": ("x.jpg", b"not-an-image", "image/jpeg")})
        assert res.status_code == 400
        assert upload_service.latest_pending(customer.id) is None
```

`conftest.py` **没有**全局 `client` fixture——本项目的既有做法是每个端点测试文件自建一个只挂所需路由的迷你 app（见 `tests/test_dashboard_preference.py:123`）。两个 upload 端点本就免鉴权，无需造 token。在本文件 import 区之后加入：

```python
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.expo.router import upload_page, upload_photo


@contextmanager
def _client():
    """只挂两个免鉴权端点的迷你 app：它们不依赖 DB，无需覆盖 get_db。

    发码与取待取两个端点带 expo:write，端点层无独立逻辑（发码=调 make_token，
    取待取=调 latest_pending），已在服务层测透，不重复造 token。
    """
    app = FastAPI()
    app.add_api_route("/api/expo/upload/{token}", upload_page, methods=["GET"])
    app.add_api_route("/api/expo/upload/{token}", upload_photo, methods=["POST"])
    with TestClient(app) as c:
        yield c
```

并把本节测试里的 `client` 参数改为在用例内 `with _client() as client:`（`db` fixture 仍按需保留，用于建客户）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_endpoints.py::TestUploadPage -q`
Expected: FAIL，404（端点未注册）

- [ ] **Step 3: 加端点**

在 `backend/app/expo/router.py` 的 import 区加入 `Form`、`Response` 与 `upload_service`：

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from app.expo import ai_pipeline, script_service, service, upload_service
```

在「分享落地页」一节之后插入：

```python
# ---------------- 扫码上传照片（2026-08-01）----------------
# 两个 upload 端点**刻意免鉴权**：客户手机没有也不应有展位账号，令牌即凭证
#（HMAC 绑定 customer_id + 10 分钟过期，见 upload_service）。这是机器对机器
# 白名单之外的第三类豁免，与 /share/{short_code} 同性质。

@router.post("/kiosk/upload-ticket", summary="签发扫码上传令牌（kiosk 拍摄页）")
def create_upload_ticket(
    customer_id: int = Query(...),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    # 密钥停在仓库默认值 = 任何能读代码的人都能离线伪造令牌，往任意客户名下投图。
    # 免登录端点的授权模型全压在这个密钥上，故此处 fail-closed 拒发，逼着部署时配 .env
    #（照 app/domestic/router.py 对 qr_secret_is_default 的处理；Task 1 代码审查 C1）
    if upload_service.secret_is_default():
        raise HTTPException(503, "扫码上传未配置签名密钥，请联系管理员")
    if not db.get(ExpoCustomer, customer_id):
        raise HTTPException(404, "客户不存在")
    upload_service.sweep_stale()   # 机会式清理：云端展会实例无调度器，只能挂在这条路上
    token = upload_service.make_token(customer_id)
    return ok({
        "token": token,
        "path": f"/api/expo/upload/{token}",
        "expires_in": upload_service.TICKET_TTL_SECONDS,
    })


@router.get("/upload/{token}", summary="手机上传页（免鉴权，令牌即凭证）",
            response_class=HTMLResponse)
def upload_page(token: str):
    try:
        upload_service.parse_token(token)
    except ValueError as exc:
        return HTMLResponse(_upload_html(None, str(exc)))
    return HTMLResponse(_upload_html(token, None))


@router.post("/upload/{token}", summary="手机上传照片（免鉴权，令牌即凭证）")
def upload_photo(token: str, photo: UploadFile = File(...)):
    try:
        customer_id = upload_service.parse_token(token)
        upload_service.save_pending(customer_id, photo.file.read(), photo.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok({"uploaded": True})


@router.get("/kiosk/pending-photo", summary="取该客户最新的扫码待取照片")
def get_pending_photo(
    customer_id: int = Query(...),
    _user=Depends(require_permission("expo:write")),
):
    latest = upload_service.latest_pending(customer_id)
    if not latest:
        return ok({"pending": None})
    return ok({"pending": {
        "name": latest.name,
        "photo_url": service._to_url(ai_pipeline.to_rel(latest)),
        "uploaded_at": int(latest.stat().st_mtime),
    }})
```

在 `router.py` 末尾追加页面渲染函数：

```python
def _upload_html(token: str | None, error: str | None) -> str:
    """手机上传页。服务端渲染而非进前端路由：与 /share 同范式，且 /m/ 已冻结
    为素材域专用（CLAUDE.md 前端约定 21）。黑金语系与分享页保持一致。"""
    style = """body{margin:0;background:#0c0a08;color:#f3ead9;
font-family:"PingFang SC",-apple-system,sans-serif;padding:34px 22px;text-align:center}
h1{font-size:15px;letter-spacing:.3em;color:#e8c479;font-weight:400;margin:0 0 6px}
.sub{color:#8d8371;font-size:12px;margin-bottom:26px}
.btn{display:block;margin:14px auto;max-width:300px;padding:16px;border-radius:14px;
border:1px solid rgba(232,196,121,.5);color:#f7e3b0;font-size:15px;background:rgba(232,196,121,.06)}
.tips{max-width:320px;margin:26px auto 0;text-align:left;color:#8d8371;font-size:12px;line-height:2}
.tips b{color:#e8c479;font-weight:400}
.privacy{color:#6b6355;font-size:11px;line-height:1.9;margin-top:28px}
.state{margin-top:20px;font-size:14px;color:#e8c479;min-height:22px}
.err{color:#d98b7a;font-size:14px;margin-top:40px}"""
    if error:
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>莱莎健康假发 · 上传照片</title><style>{style}</style></head><body>
<h1>莱 莎 · 健 康 假 发</h1><div class="err">{error}</div></body></html>"""

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>莱莎健康假发 · 上传照片</title><style>{style}</style></head><body>
<h1>莱 莎 · 健 康 假 发</h1>
<div class="sub">上传照片，生成您的试戴效果</div>
<label class="btn">从相册选择<input type="file" accept="image/*" hidden id="album"/></label>
<label class="btn">现在拍一张<input type="file" accept="image/*" capture="user" hidden id="shot"/></label>
<div class="state" id="state"></div>
<div class="tips">
<b>略微俯拍</b>镜头稍高于视线，微微抬头，眼神更明亮<br/>
<b>微侧面容</b>面部带一点角度，露出约四分之三面容<br/>
<b>构图靠上</b>头部位于画面上三分之一，露出肩颈与上身
</div>
<div class="privacy">照片仅用于本次体验与效果回看，保留 90 天，可随时联系我们删除。</div>
<script>
var state=document.getElementById('state');
function send(input){{
  var f=input.files&&input.files[0]; if(!f) return;
  state.textContent='上传中…';
  var fd=new FormData(); fd.append('photo',f,f.name||'photo.jpg');
  fetch('/api/expo/upload/{token}',{{method:'POST',body:fd}})
    .then(function(r){{return r.json().then(function(b){{return {{ok:r.ok,body:b}};}});}})
    .then(function(r){{
      state.textContent = r.ok ? '上传成功，请回到展位屏幕查看'
                               : (r.body && r.body.message) || '上传失败，请重试';
    }})
    .catch(function(){{state.textContent='网络不稳，请重试';}});
}}
document.getElementById('album').onchange=function(){{send(this);}};
document.getElementById('shot').onchange=function(){{send(this);}};
</script></body></html>"""
```

在 `router.py` 的 models import 补上 `ExpoCustomer`：

```python
from app.expo.models import ExpoCustomer, ExpoResult, ExpoScript, ExpoWig
```

- [ ] **Step 4: 改造 `POST /sessions`**

把 `router.py:71-85` 的 `create_session` 端点替换为：

```python
@router.post("/sessions", summary="建会话（照片来源：现场拍照 photo / 扫码上传 pending_photo 二选一）")
def create_session(
    customer_id: int = Query(...),
    mode: str = Query("tryon", pattern="^(tryon|scene)$"),
    photo: UploadFile | None = File(None),
    pending_photo: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("expo:write")),
):
    # 空串归一为 None：multipart 表单里「字段在但值为空」很常见（前端条件 append 漏判、
    # 客户端库补空字段），而 `"" is not None` 会骗过 service 的二选一守卫，接着在
    # upload_file 为 None 时取 .filename 炸出 AttributeError 而不是干净的 400
    #（Task 3 实现者实测发现）。归一放在这一层：service 收到的应当已是规范输入
    pending_photo = (pending_photo or "").strip() or None
    try:
        session = service.create_session(
            db, customer_id, photo, _user_id(current_user),
            mode=mode, pending_name=pending_photo,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    upload_service.sweep_stale()   # 确认路径上的第二次机会式清理
    if mode == "tryon":
        ai_pipeline.start_analysis(session.id)
    return ok({"session_id": session.id}, code=201)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_expo_upload_endpoints.py -q`
Expected: PASS，10 passed

- [ ] **Step 6: 全量回归 + 约定检查**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS，全绿

Run: `./backend/.venv/Scripts/python.exe scripts/check_conventions.py`
Expected: `增量改动无违规 ✓`

- [ ] **Step 7: 提交**

```bash
git add backend/app/expo/router.py backend/tests/test_expo_upload_endpoints.py
git commit -m "feat(expo): serve the phone upload page and accept QR photos"
```

---

## Task 5: 前端 http 降级 helper 抽取

**Files:**
- Create: `frontend/src/views/expo/kiosk/publicUrl.js`
- Modify: `frontend/src/views/expo/kiosk/ResultScreen.vue:225-234`
- Test: `frontend/tests/expoPublicUrl.test.mjs`
- Modify: `frontend/package.json`（加 test 脚本）

- [ ] **Step 1: 建 helper**

创建 `frontend/src/views/expo/kiosk/publicUrl.js`：

```js
/**
 * 给**客户手机**扫的二维码用的 origin。
 *
 * 展位平板自己走 https 只是为了拿 secure context 开相机——IP 签不到 CA 证书，
 * 服务器挂的是自签证书，客户手机（尤其微信内置浏览器）根本不认，扫出来是白屏。
 * 所以 host 为裸 IP 时把链接降回 http；将来换成备案域名（正规证书）则保持 https。
 *
 * 抽成共享 helper 而非在各页复制：两份必然在换域名时漏改一份，而漏改的症状是
 * 「客户扫码白屏」，展位现场没人能定位。分享二维码与扫码上传两处共用。
 */
const IPV4_HOST = /^\d{1,3}(\.\d{1,3}){3}$/

export function publicOrigin() {
  // 只处理标准端口：带显式端口时无从推断对应的 http 端口，宁可原样不猜
  if (IPV4_HOST.test(location.hostname) && !location.port) {
    return `http://${location.hostname}`
  }
  return location.origin
}
```

- [ ] **Step 2: ResultScreen 改用 helper**

在 `ResultScreen.vue` 的 `<script setup>` import 区加入：

```js
import { publicOrigin } from './publicUrl'
```

把 `shareUrl` 计算属性与其上方的 `IPV4_HOST` 常量、注释块整体替换为：

```js
const shareUrl = computed(() => {
  if (!current.value?.short_code) return ''
  return `${publicOrigin()}/api/expo/share/${current.value.short_code}`
})
```

- [ ] **Step 3: 加降级规则的测试**

本项目前端测试是 `node --test` 跑 `frontend/tests/*.test.mjs` 直接 import 纯 JS 模块（见 `tests/invoiceAccessories.test.mjs`）。`publicUrl.js` 读 `location`，node 下需自造全局。

创建 `frontend/tests/expoPublicUrl.test.mjs`：

```js
import test from 'node:test'
import assert from 'node:assert/strict'

import { publicOrigin } from '../src/views/expo/kiosk/publicUrl.js'

function withLocation(hostname, port, origin, fn) {
  globalThis.location = { hostname, port, origin }
  try { fn() } finally { delete globalThis.location }
}

test('裸 IP 且无显式端口 → 降到 http（客户手机不认自签证书）', () => {
  withLocation('154.8.205.162', '', 'https://154.8.205.162', () => {
    assert.equal(publicOrigin(), 'http://154.8.205.162')
  })
})

test('备案域名 → 保持原 origin，不降级', () => {
  withLocation('leshine.work', '', 'https://leshine.work', () => {
    assert.equal(publicOrigin(), 'https://leshine.work')
  })
})

test('裸 IP 带显式端口 → 原样不猜（无从推断对应的 http 端口）', () => {
  withLocation('192.168.101.193', '8001', 'http://192.168.101.193:8001', () => {
    assert.equal(publicOrigin(), 'http://192.168.101.193:8001')
  })
})
```

在 `frontend/package.json` 的 `scripts` 里追加：

```json
    "test:expo-publicurl": "node --test tests/expoPublicUrl.test.mjs"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm run test:expo-publicurl`
Expected: `# pass 3`

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built in ...`，无报错

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/expo/kiosk/publicUrl.js frontend/src/views/expo/kiosk/ResultScreen.vue frontend/tests/expoPublicUrl.test.mjs frontend/package.json
git commit -m "refactor(expo): share the http-downgrade rule between both QR codes"
```

---

## Task 6: 前端 API 与流程状态

**Files:**
- Modify: `frontend/src/api/expo.js`
- Modify: `frontend/src/views/expo/composables/useTryOnFlow.js`

- [ ] **Step 1: 加 API**

在 `frontend/src/api/expo.js` 的 `createSession` 之前插入：

```js
// ── 扫码上传照片（2026-08-01）──
export function createUploadTicket(customerId) {
  return expoClient.post(`/kiosk/upload-ticket?customer_id=${customerId}`, null, { ...KIOSK })
}

export function getPendingPhoto(customerId) {
  return expoClient.get('/kiosk/pending-photo', {
    params: { customer_id: customerId },
    // 与会话轮询同口径的短超时：弱网下不让在途请求长期占坑
    timeout: 10000,
    ...KIOSK,
  })
}
```

把 `createSession` 替换为支持双来源：

```js
export function createSession(customerId, photoBlob, mode = 'tryon', pendingName = null) {
  const form = new FormData()
  if (pendingName) form.append('pending_photo', pendingName)
  else form.append('photo', photoBlob, 'photo.jpg')
  return expoClient.post(`/sessions?customer_id=${customerId}&mode=${mode}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    ...KIOSK,
  })
}
```

- [ ] **Step 2: flow 加二维码状态与 idle 挂起**

在 `useTryOnFlow.js` 的 import 区补 API 与 helper：

```js
import {
  createSession, createUploadTicket, generateResults, getPendingPhoto, getScenes,
  getSession, getWigColors, registerCustomer, setReaction, submitFeedback, updateCustomer,
} from '@/api/expo'
import { publicOrigin } from '@/views/expo/kiosk/publicUrl'
```

在 `const guideShown = ref(false)` 附近加状态：

```js
  const qrUrl = ref('')          // 非空 = 二维码面板开启中
  const qrExpiresAt = ref(0)     // 毫秒时间戳；到点自动关面板并重新武装 idle
  const pendingName = ref('')    // 待取照片文件名，确认时随 createSession 提交
```

把 `touch()` 改为在二维码开启时不武装 idle：

```js
  function touch() {
    if (idleTimer) clearTimeout(idleTimer)
    if (step.value === 'attract') return
    // 二维码开启期间挂起清场：扫码→翻相册→上传必然超过 60 秒，不挂起则功能上线即坏。
    // 上界由令牌 10 分钟过期保证（closeQr 在到期时被调用），不会永久停在拍摄页
    if (qrUrl.value) return
    if (NO_IDLE_STEPS.includes(step.value) || generating.value) return
    idleTimer = setTimeout(resetAll, IDLE_MS)
  }
```

新增三个动作（放在 `submitRegister` 之后）：

```js
  // ── 扫码上传照片 ──
  let qrTimer = null

  async function openQr() {
    errorText.value = ''
    try {
      await registerPromise            // 建档可能仍在途，customerId 未兑现时拿不到码
      const res = await createUploadTicket(customerId.value)
      qrUrl.value = `${publicOrigin()}${res.data.path}`
      qrExpiresAt.value = Date.now() + res.data.expires_in * 1000
      touch()                          // 立即生效：清掉已武装的 idle 计时
      qrTimer = setTimeout(closeQr, res.data.expires_in * 1000)
      pollPending()
    } catch (e) {
      errorText.value = '二维码获取失败，请直接拍照或呼叫顾问'
    }
  }

  function closeQr() {
    if (qrTimer) { clearTimeout(qrTimer); qrTimer = null }
    qrUrl.value = ''
    qrExpiresAt.value = 0
    touch()                            // 重新武装 idle
  }

  // 待取照片轮询：沿用 POLL_MS 节奏，面板关闭即自然停止
  function pollPending() {
    if (!qrUrl.value) return
    getPendingPhoto(customerId.value)
      .then((res) => {
        if (!qrUrl.value) return       // 轮询在途期间面板已关，丢弃结果
        if (res.data.pending) {
          pendingName.value = res.data.pending.name
          const url = res.data.pending.photo_url
          closeQr()
          onPendingArrived?.(url)      // 由 CaptureScreen 注册，进预览态
          return
        }
        setTimeout(pollPending, POLL_MS)
      })
      .catch(() => { setTimeout(pollPending, POLL_MS) })
  }

  // CaptureScreen 注册的回调：待取照片到达时把它显示为预览
  let onPendingArrived = null
  function setPendingHandler(fn) { onPendingArrived = fn }
```

在 `resetAll()` 内补清场（与其他状态并列）：

```js
    closeQr()
    pendingName.value = ''
```

在 return 的对象里补出口：

```js
    qrUrl, qrExpiresAt, pendingName, openQr, closeQr, setPendingHandler,
```

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built in ...`，无报错

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/expo.js frontend/src/views/expo/composables/useTryOnFlow.js
git commit -m "feat(expo): hold the kiosk idle reset while the upload QR is open"
```

---

## Task 7: 拍摄页二维码面板

**Files:**
- Modify: `frontend/src/views/expo/kiosk/CaptureScreen.vue`

- [ ] **Step 1: 加入口按钮**

在 `CaptureScreen.vue` 模板的「本地相册」`<label>` 之后（`cameraOn` 分支内）插入：

```html
        <button class="xk-btn ghost side" @click="flow.openQr()">
          <svg class="btn-ico" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
            <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
            <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
            <path d="M13.5 13.5h3v3h-3zM18 18h2.5v2.5H18z" />
          </svg>
          扫码传照片
        </button>
```

- [ ] **Step 2: 加二维码浮层**

在拍摄示范浮层之后插入：

```html
    <div v-if="flow.qrUrl.value" class="qr-overlay" @click.self="flow.closeQr()">
      <div class="qr-panel">
        <div class="qr-title">用手机上传照片</div>
        <div class="qr-sub">相册里的美照、或用手机拍一张，都比现场更从容</div>
        <canvas ref="qrCanvas" width="220" height="220" class="qr-canvas" />
        <div class="qr-hint">微信扫一扫 · 上传后本屏自动显示</div>
        <button class="xk-btn ghost" @click="flow.closeQr()">取消，我现场拍</button>
      </div>
    </div>
```

- [ ] **Step 3: 画二维码并接收待取照片**

在 `<script setup>` 中加入（`watch` 需从 vue 引入）：

```js
const qrCanvas = ref(null)

// 二维码：qrcode 动态引入，失败静默降级为不显示（与 ResultScreen 同策略）
watch([() => flow.qrUrl.value, qrCanvas], async () => {
  if (!flow.qrUrl.value) return
  await nextTick()
  if (!qrCanvas.value) return
  try {
    const QRCode = (await import('qrcode')).default
    // 墨色码点 + 暖米底：黑金语系里可扫性最稳的组合（反色码部分扫码器不认）
    await QRCode.toCanvas(qrCanvas.value, flow.qrUrl.value, {
      width: 220, margin: 1,
      color: { dark: '#0c0a08', light: '#f3ead9' },
    })
  } catch (e) { /* 依赖缺失时不显示二维码，不阻断流程 */ }
}, { immediate: true })

// 手机传到的照片直接进既有预览态：与现场拍照共用「重拍 / 就用这张」两个按钮，
// 顾问在同一个位置做同一个决定
flow.setPendingHandler((photoUrl) => { previewUrl.value = photoUrl })
```

- [ ] **Step 4: `confirm()` / `retake()` 支持待取来源**

待取照片没有本地 blob，`previewUrl` 是服务端 URL，两处既有实现都会因此走错。

把 `CaptureScreen.vue:243-261` 的 `retake()` 与 `confirm()` 替换为：

```js
function retake() {
  // 只对本地 blob 调 revoke：待取照片的 previewUrl 是服务端 URL，
  // 对非 blob URL 调 revokeObjectURL 是无声的错用
  if (previewUrl.value.startsWith('blob:')) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  photoBlob = null
  flow.pendingName.value = ''   // 不清则「重拍」后仍会提交上一张扫码传来的照片
  // 恢复取景（snap 时 pause 了）；仅相机路径，文件选择兜底下 video 无流，play() 会 reject
  if (cameraOn.value) videoEl.value?.play?.()?.catch(() => {})
}

async function confirm() {
  // 两种来源二选一即可提交：现场拍照有 blob，扫码上传有待取文件名
  if ((!photoBlob && !flow.pendingName.value) || submitting.value) return
  submitting.value = true
  try {
    // 不在此处 stopCamera：上传失败会留在拍摄页（errorText 提示），提前停流
    // 会让「重拍」露出黑屏死相机；成功离屏时 onBeforeUnmount(stopCamera) 兜底
    await flow.submitPhoto(photoBlob)
  } finally {
    submitting.value = false
  }
}
```

再把 `useTryOnFlow.js` 的 `submitPhoto` 里那行 `createSession` 调用（`useTryOnFlow.js:223`）改为带上待取文件名：

```js
      res = await createSession(customerId.value, blob, mode.value, pendingName.value || null)
```

`submitPhoto` 其余部分不动——它的 register 兑现、错误文案与停留策略对两种来源完全一致。

- [ ] **Step 5: 加样式**

在 `<style scoped>` 末尾追加（颜色全部走既有 `--xk-*` token，不写裸 hex）：

```css
.qr-overlay {
  position: fixed; inset: 0; z-index: 40; display: flex;
  align-items: center; justify-content: center;
  background: rgba(6, 5, 4, 0.82); backdrop-filter: blur(6px);
}
.qr-panel {
  display: flex; flex-direction: column; align-items: center; gap: 14px;
  padding: 32px 34px; border-radius: 20px;
  border: 1px solid var(--xk-gold-line); background: var(--xk-ink);
}
.qr-title { font-size: 17px; color: var(--xk-gold); letter-spacing: 0.1em; }
.qr-sub { font-size: 12px; color: var(--xk-mut); }
.qr-canvas { border-radius: 12px; }
.qr-hint { font-size: 12px; color: var(--xk-gold-dim); letter-spacing: 0.08em; }
```

- [ ] **Step 6: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built in ...`，无报错

- [ ] **Step 7: 提交**

```bash
git add frontend/src/views/expo/kiosk/CaptureScreen.vue
git commit -m "feat(expo): add the QR upload panel to the capture screen"
```

---

## Task 8: 文档同步

**Files:**
- Modify: `docs/api-reference.md`

- [ ] **Step 1: 登记新端点**

在 `docs/api-reference.md` 的展会试戴（`/api/expo`）一节补入下面四行，格式对齐该节既有行：

```markdown
| POST | `/api/expo/kiosk/upload-ticket` | expo:write | 签发扫码上传令牌（10 分钟有效），顺带清理过期待取照片 |
| GET | `/api/expo/upload/{token}` | **免鉴权，令牌即凭证** | 客户手机上传页（服务端渲染 HTML） |
| POST | `/api/expo/upload/{token}` | **免鉴权，令牌即凭证** | 客户手机提交照片，落 uploads/expo/pending/ |
| GET | `/api/expo/kiosk/pending-photo` | expo:write | 取该客户最新的扫码待取照片 |
```

并把该节 `POST /api/expo/sessions` 那一行的说明改为：

```markdown
| POST | `/api/expo/sessions` | expo:write | 建会话。照片来源二选一：`photo`（现场拍照，multipart 文件）或 `pending_photo`（扫码上传的待取文件名，Form 字段），两者必须恰好提供一个 |
```

- [ ] **Step 2: 提交**

```bash
git add docs/api-reference.md
git commit -m "docs(expo): register the QR upload endpoints"
```

---

## 收尾验收

- [ ] `cd backend && ./.venv/Scripts/python.exe -m pytest -q` 全绿
- [ ] `cd frontend && npm run build` 通过
- [ ] `./backend/.venv/Scripts/python.exe scripts/check_conventions.py` 无红项
- [ ] 派独立 agent 对抗性审查（跨 3+ 文件 + 新增免鉴权端点，触发 CLAUDE.md DoD 第 5 条）。审查视角：令牌伪造与重放、路径穿越、免鉴权端点的资源耗尽、idle 挂起后的状态泄漏（上一位客户的待取照片被下一位看到）、前后端契约
- [ ] 真机验收：手机扫码 → 相册与拍照两条路各走一次 → kiosk 预览 → 生成。**必须在云端展会实例上验**，本地 localhost 的二维码手机扫不到
